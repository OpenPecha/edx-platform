"""
S3-based ContentStore implementation using boto3/django-storages.

This module provides an S3-backed storage for course assets as an alternative
to MongoDB GridFS. It stores file data in S3 and metadata in the database.
"""

import hashlib
import json
import logging
import os
import re
from io import BytesIO

import boto3
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.files.base import ContentFile
from fs.osfs import OSFS
from opaque_keys.edx.keys import AssetKey
from storages.backends.s3boto3 import S3Boto3Storage

from openedx.core.djangoapps.s3_contentstore.models import S3AssetMetadata
from xmodule.contentstore.content import (
    ContentStore,
    StaticContent,
    StaticContentStream,
)
from xmodule.exceptions import NotFoundError
from xmodule.util.misc import escape_invalid_characters

log = logging.getLogger(__name__)


class S3ContentStore(ContentStore):
    """
    S3-backed ContentStore implementation.

    This class provides storage for course assets (images, PDFs, videos, etc.)
    using Amazon S3 as the backend storage. Asset metadata is stored in a
    PostgreSQL/MySQL database via Django ORM.

    Configuration example:
        CONTENTSTORE = {
            'ENGINE': 'openedx.core.djangoapps.s3_contentstore.s3.S3ContentStore',
            'OPTIONS': {
                'bucket': 'my-edx-course-assets',
                'region_name': 'us-east-1',
            },
            'ADDITIONAL_OPTIONS': {},
        }

    Environment variables used:
        - AWS_ACCESS_KEY_ID
        - AWS_SECRET_ACCESS_KEY
        - AWS_S3_ENDPOINT_URL (for S3-compatible services like MinIO)
    """

    def __init__(
        self,
        bucket=None,
        region_name=None,
        access_key=None,
        secret_key=None,
        endpoint_url=None,
        **kwargs,
    ):
        """
        Initialize the S3ContentStore.

        Args:
            bucket: S3 bucket name for storing assets
            region_name: AWS region (e.g., 'us-east-1')
            access_key: AWS access key ID (optional, uses environment if not provided)
            secret_key: AWS secret access key (optional, uses environment if not provided)
            endpoint_url: Custom S3 endpoint URL (for MinIO or other S3-compatible services)
            **kwargs: Additional options passed to boto3 or S3Boto3Storage
        """
        self.bucket = bucket or getattr(
            settings, "AWS_STORAGE_BUCKET_NAME", "edx-course-assets"
        )
        self.region_name = region_name or getattr(
            settings, "AWS_S3_REGION_NAME", "us-east-1"
        )
        self.access_key = access_key or getattr(settings, "AWS_ACCESS_KEY_ID", None)
        self.secret_key = secret_key or getattr(settings, "AWS_SECRET_ACCESS_KEY", None)
        self.endpoint_url = endpoint_url or getattr(
            settings, "AWS_S3_ENDPOINT_URL", None
        )

        log.info(
            "S3ContentStore initialized with bucket: %s, region: %s, endpoint: %s",
            self.bucket,
            self.region_name,
            self.endpoint_url,
        )

        # Initialize S3 client for direct operations
        self._init_s3_client()

        # Initialize django-storages S3 backend for file operations
        self._init_storage()

    def _init_s3_client(self):
        """Initialize boto3 S3 client."""
        client_kwargs = {
            "region_name": self.region_name,
        }
        if self.access_key and self.secret_key:
            client_kwargs["aws_access_key_id"] = self.access_key
            client_kwargs["aws_secret_access_key"] = self.secret_key
        if self.endpoint_url:
            client_kwargs["endpoint_url"] = self.endpoint_url

        self.s3_client = boto3.client("s3", **client_kwargs)
        self.s3_resource = boto3.resource("s3", **client_kwargs)

    def _init_storage(self):
        """Initialize django-storages S3Boto3Storage backend."""
        storage_kwargs = {
            "bucket_name": self.bucket,
            "region_name": self.region_name,
            "default_acl": "private",
            "querystring_auth": True,
            "file_overwrite": True,
        }
        if self.access_key and self.secret_key:
            storage_kwargs["access_key"] = self.access_key
            storage_kwargs["secret_key"] = self.secret_key
        if self.endpoint_url:
            storage_kwargs["endpoint_url"] = self.endpoint_url

        self.storage = S3Boto3Storage(**storage_kwargs)

    def _location_to_s3_key(self, location):
        """
        Convert an AssetKey location to an S3 object key.

        Args:
            location: An AssetKey identifying the asset

        Returns:
            str: S3 object key path (e.g., 'OrgName_CourseName_Run/asset/filename.png')
        """
        # Create a hierarchical path structure:
        # {org}_{course}_{run}/{block_type}/{block_id}
        course_key = location.course_key
        org = course_key.org.replace("+", "_").replace(":", "_")
        course = course_key.course.replace("+", "_").replace(":", "_")
        run = (
            course_key.run.replace("+", "_").replace(":", "_")
            if hasattr(course_key, "run")
            else "default"
        )

        return f"{org}_{course}_{run}/{location.block_type}/{location.block_id}"

    def save(self, content):
        """
        Save content to S3.

        Args:
            content: StaticContent object containing the asset data

        Returns:
            StaticContent: The saved content object
        """
        log.info("S3ContentStore.save() called for location: %s", content.location)
        log.info("Content type: %s, name: %s", content.content_type, content.name)

        s3_key = self._location_to_s3_key(content.location)
        log.info("S3 key: %s", s3_key)

        try:
            # Process content data
            if hasattr(content.data, "__iter__") and not isinstance(
                content.data, (bytes, str)
            ):
                # Handle chunked/iterable data
                file_obj = BytesIO()
                custom_md5 = hashlib.md5()
                for chunk in content.data:
                    if isinstance(chunk, str):
                        chunk = chunk.encode("utf-8")
                    file_obj.write(chunk)
                    custom_md5.update(chunk)
                file_obj.seek(0)
                content_digest = custom_md5.hexdigest()
                data_size = file_obj.getbuffer().nbytes
                log.info("Chunked data processed, size: %s", data_size)
            else:
                # Handle direct bytes/string data
                if isinstance(content.data, str):
                    data = content.data.encode("utf-8")
                else:
                    data = content.data
                file_obj = BytesIO(data)
                content_digest = hashlib.md5(data).hexdigest()
                data_size = len(data)
                log.info("Direct data, size: %s", data_size)

            # Upload to S3
            log.info("Uploading to S3 with storage backend: %s", type(self.storage))
            self.storage.save(s3_key, ContentFile(file_obj.getvalue()))
            log.info("Successfully uploaded %s to S3", s3_key)

            # Save metadata to database
            thumbnail_location_str = (
                str(content.thumbnail_location) if content.thumbnail_location else None
            )

            metadata, created = S3AssetMetadata.objects.update_or_create(
                location_str=str(content.location),
                defaults={
                    "course_key_str": str(content.location.course_key),
                    "s3_key": s3_key,
                    "asset_name": content.name,
                    "content_type": content.content_type,
                    "content_digest": content_digest,
                    "length": data_size,
                    "thumbnail_location": thumbnail_location_str,
                    "import_path": content.import_path or "",
                    "locked": getattr(content, "locked", False),
                },
            )
            log.info(
                "Metadata %s for %s",
                "created" if created else "updated",
                content.location,
            )

            return content

        except Exception as e:
            log.error("Error saving asset %s: %s", content.location, str(e))
            raise

    def delete(self, location_or_id):
        """
        Delete an asset from S3.

        Args:
            location_or_id: AssetKey or string identifier of the asset to delete
        """
        if isinstance(location_or_id, AssetKey):
            s3_key = self._location_to_s3_key(location_or_id)
            location_str = str(location_or_id)
        else:
            location_str = str(location_or_id)
            # Try to find the S3 key from metadata
            try:
                metadata = S3AssetMetadata.objects.get(location_str=location_str)
                s3_key = metadata.s3_key
            except S3AssetMetadata.DoesNotExist:
                log.warning("Metadata not found for deletion: %s", location_str)
                return

        try:
            # Delete from S3
            if self.storage.exists(s3_key):
                self.storage.delete(s3_key)
                log.info("Deleted S3 object: %s", s3_key)

            # Delete metadata
            S3AssetMetadata.objects.filter(location_str=location_str).delete()
            log.info("Deleted metadata for: %s", location_str)

        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Error deleting asset %s: %s", location_str, str(e))

    def find(self, filename, throw_on_not_found=True, as_stream=False):
        """
        Find and retrieve content from S3.

        Args:
            filename: AssetKey identifying the asset
            throw_on_not_found: If True, raise NotFoundError when asset not found
            as_stream: If True, return StaticContentStream for streaming

        Returns:
            StaticContent or StaticContentStream object, or None if not found

        Raises:
            NotFoundError: If asset not found and throw_on_not_found is True
        """
        log.debug("S3ContentStore.find() called for location: %s", filename)

        location_str = str(filename)

        try:
            metadata = S3AssetMetadata.objects.get(location_str=location_str)
        except S3AssetMetadata.DoesNotExist as exc:
            if throw_on_not_found:
                raise NotFoundError(location_str) from exc
            return None

        try:
            # Get file from S3
            s3_file = self.storage.open(metadata.s3_key, "rb")

            # Parse thumbnail location
            thumbnail_location = None
            if metadata.thumbnail_location:
                try:
                    thumbnail_location = AssetKey.from_string(
                        metadata.thumbnail_location
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    # Invalid thumbnail location string, leave as None
                    thumbnail_location = None

            if as_stream:
                return StaticContentStream(
                    filename,
                    metadata.asset_name,
                    metadata.content_type,
                    s3_file,
                    last_modified_at=metadata.updated_at,
                    thumbnail_location=thumbnail_location,
                    import_path=metadata.import_path or None,
                    length=metadata.length,
                    locked=metadata.locked,
                    content_digest=metadata.content_digest,
                )
            else:
                data = s3_file.read()
                s3_file.close()

                return StaticContent(
                    filename,
                    metadata.asset_name,
                    metadata.content_type,
                    data,
                    last_modified_at=metadata.updated_at,
                    thumbnail_location=thumbnail_location,
                    import_path=metadata.import_path or None,
                    length=metadata.length,
                    locked=metadata.locked,
                    content_digest=metadata.content_digest,
                )

        except ClientError as e:
            log.error("S3 error finding asset %s: %s", filename, str(e))
            if throw_on_not_found:
                raise NotFoundError(location_str) from e
            return None
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Error finding asset %s: %s", filename, str(e))
            if throw_on_not_found:
                raise NotFoundError(location_str) from e
            return None

    def export(self, location, output_directory):
        """
        Export an asset to the local filesystem.

        Args:
            location: AssetKey identifying the asset
            output_directory: Directory path to export to
        """
        content = self.find(location)

        filename = content.name
        if content.import_path:
            output_directory = os.path.join(
                output_directory, os.path.dirname(content.import_path)
            )

        if not os.path.exists(output_directory):
            os.makedirs(output_directory)

        export_name = escape_invalid_characters(
            name=filename, invalid_char_list=["/", "\\"]
        )

        disk_fs = OSFS(output_directory)
        with disk_fs.open(export_name, "wb") as asset_file:
            asset_file.write(content.data)

    def export_all_for_course(self, course_key, output_directory, assets_policy_file):
        """
        Export all assets for a course to the filesystem.

        Args:
            course_key: CourseKey identifying the course
            output_directory: Directory path to export to
            assets_policy_file: Path to write the assets policy JSON file
        """
        policy = {}
        assets, _ = self.get_all_content_for_course(course_key)

        for asset in assets:
            try:
                self.export(asset["asset_key"], output_directory)
                for attr, value in asset.items():
                    if attr not in [
                        "_id",
                        "md5",
                        "uploadDate",
                        "length",
                        "chunkSize",
                        "asset_key",
                    ]:
                        policy.setdefault(asset["asset_key"].block_id, {})[attr] = value
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.exception(
                    "Failed to export asset %s: %s", asset.get("asset_key"), str(e)
                )

        with open(assets_policy_file, "w") as f:
            json.dump(policy, f, sort_keys=True, indent=4)

    def get_all_content_thumbnails_for_course(self, course_key):
        """Get all thumbnail assets for a course."""
        return self._get_all_content_for_course(course_key, get_thumbnails=True)[0]

    def get_all_content_for_course(
        self, course_key, start=0, maxresults=-1, sort=None, filter_params=None
    ):
        """
        Get all content assets for a course.

        Args:
            course_key: CourseKey identifying the course
            start: Offset for pagination
            maxresults: Maximum number of results to return (-1 for all)
            sort: List of (field, direction) tuples for sorting
            filter_params: Additional filter parameters

        Returns:
            Tuple of (list of asset dicts, total count)
        """
        return self._get_all_content_for_course(
            course_key,
            start=start,
            maxresults=maxresults,
            get_thumbnails=False,
            sort=sort,
            filter_params=filter_params,
        )

    def _get_all_content_for_course(
        self,
        course_key,
        get_thumbnails=False,
        start=0,
        maxresults=-1,
        sort=None,
        filter_params=None,
    ):
        """
        Internal method to get all content for a course.

        Returns:
            Tuple of (list of asset dictionaries, total count)
        """
        # Build base query
        course_key_str = str(course_key)
        queryset = S3AssetMetadata.objects.filter(course_key_str=course_key_str)

        # Filter by asset type (thumbnails vs regular assets)
        if get_thumbnails:
            queryset = queryset.filter(location_str__contains="thumbnail")
        else:
            queryset = queryset.exclude(location_str__contains="thumbnail")

        # Apply additional filters
        if filter_params:
            if "contentType" in filter_params:
                queryset = queryset.filter(
                    content_type__startswith=filter_params["contentType"].rstrip("/*")
                )
            if "displayname" in filter_params:
                queryset = queryset.filter(
                    asset_name__icontains=filter_params["displayname"]
                )

        # Apply sorting
        if sort:
            order_by_fields = []
            for field, direction in sort:
                if field == "displayname":
                    db_field = "asset_name"
                elif field == "uploadDate":
                    db_field = "created_at"
                elif field == "contentType":
                    db_field = "content_type"
                else:
                    db_field = field

                if direction == -1:
                    db_field = f"-{db_field}"
                order_by_fields.append(db_field)
            queryset = queryset.order_by(*order_by_fields)
        else:
            queryset = queryset.order_by("-created_at")

        # Get total count before pagination
        total_count = queryset.count()

        # Apply pagination
        if maxresults > 0:
            queryset = queryset[start : start + maxresults]
        elif start > 0:
            queryset = queryset[start:]

        # Convert to asset dictionaries
        assets = []
        for metadata in queryset:
            try:
                asset_key = AssetKey.from_string(metadata.location_str)
            except Exception:  # pylint: disable=broad-exception-caught
                # Invalid asset key string, skip this asset
                continue

            assets.append(
                {
                    "asset_key": asset_key,
                    "displayname": metadata.asset_name,
                    "contentType": metadata.content_type,
                    "uploadDate": metadata.created_at,
                    "md5": metadata.content_digest,
                    "length": metadata.length,
                    "locked": metadata.locked,
                    "import_path": metadata.import_path,
                    "thumbnail_location": metadata.thumbnail_location,
                }
            )

        return assets, total_count

    def set_attr(self, asset_key, attr, value=True):
        """
        Set an attribute on an asset.

        Args:
            asset_key: AssetKey identifying the asset
            attr: Attribute name to set
            value: Value to set
        """
        self.set_attrs(asset_key, {attr: value})

    def get_attr(self, location, attr, default=None):
        """
        Get an attribute from an asset.

        Args:
            location: AssetKey identifying the asset
            attr: Attribute name to get
            default: Default value if attribute not found

        Returns:
            The attribute value or default
        """
        return self.get_attrs(location).get(attr, default)

    def set_attrs(self, location, attr_dict):
        """
        Set multiple attributes on an asset.

        Args:
            location: AssetKey identifying the asset
            attr_dict: Dictionary of attribute names and values

        Raises:
            NotFoundError: If the asset is not found
            AttributeError: If trying to set a protected attribute
        """
        protected_attrs = ["_id", "md5", "uploadDate", "length"]
        for attr in attr_dict.keys():
            if attr in protected_attrs:
                raise AttributeError(f"{attr} is a protected attribute.")

        location_str = str(location)

        try:
            metadata = S3AssetMetadata.objects.get(location_str=location_str)
        except S3AssetMetadata.DoesNotExist as exc:
            raise NotFoundError(location_str) from exc

        # Map attribute names to model fields
        attr_mapping = {
            "locked": "locked",
            "displayname": "asset_name",
            "contentType": "content_type",
            "import_path": "import_path",
            "thumbnail_location": "thumbnail_location",
        }

        # Update mapped fields
        for attr, value in attr_dict.items():
            if attr in attr_mapping:
                setattr(metadata, attr_mapping[attr], value)
            else:
                # Store unmapped attributes in custom_metadata JSON field
                if not metadata.custom_metadata:
                    metadata.custom_metadata = {}  # type: ignore[assignment]
                metadata.custom_metadata[attr] = value

        metadata.save()

    def get_attrs(self, location):
        """
        Get all attributes for an asset.

        Args:
            location: AssetKey identifying the asset

        Returns:
            Dictionary of all attributes

        Raises:
            NotFoundError: If the asset is not found
        """
        location_str = str(location)

        try:
            metadata = S3AssetMetadata.objects.get(location_str=location_str)
        except S3AssetMetadata.DoesNotExist as exc:
            raise NotFoundError(location_str) from exc

        attrs = {
            "_id": location_str,
            "displayname": metadata.asset_name,
            "contentType": metadata.content_type,
            "md5": metadata.content_digest,
            "uploadDate": metadata.created_at,
            "length": metadata.length,
            "locked": metadata.locked,
            "import_path": metadata.import_path,
            "thumbnail_location": metadata.thumbnail_location,
            "s3_key": metadata.s3_key,
        }

        # Merge custom metadata
        if metadata.custom_metadata:
            attrs.update(metadata.custom_metadata)

        return attrs

    def copy_all_course_assets(self, source_course_key, dest_course_key):
        """
        Copy all assets from one course to another.

        Args:
            source_course_key: Source CourseKey
            dest_course_key: Destination CourseKey
        """
        source_key_str = str(source_course_key)

        # Get all source assets
        source_assets = S3AssetMetadata.objects.filter(course_key_str=source_key_str)

        for source_metadata in source_assets:
            try:
                # Parse source location
                source_location = AssetKey.from_string(source_metadata.location_str)

                # Create destination location
                dest_location = dest_course_key.make_asset_key(
                    source_location.block_type, source_location.block_id
                ).for_branch(None)

                # Generate new S3 key for destination
                dest_s3_key = self._location_to_s3_key(dest_location)

                # Copy S3 object
                copy_source = {"Bucket": self.bucket, "Key": source_metadata.s3_key}
                self.s3_client.copy_object(
                    CopySource=copy_source, Bucket=self.bucket, Key=dest_s3_key
                )

                # Create new metadata record
                S3AssetMetadata.objects.update_or_create(
                    location_str=str(dest_location),
                    defaults={
                        "course_key_str": str(dest_course_key),
                        "s3_key": dest_s3_key,
                        "asset_name": source_metadata.asset_name,
                        "content_type": source_metadata.content_type,
                        "content_digest": source_metadata.content_digest,
                        "length": source_metadata.length,
                        "thumbnail_location": source_metadata.thumbnail_location,
                        "import_path": source_metadata.import_path,
                        "locked": source_metadata.locked,
                        "custom_metadata": source_metadata.custom_metadata,
                    },
                )

                log.info("Copied asset from %s to %s", source_location, dest_location)

            except Exception as e:  # pylint: disable=broad-exception-caught
                log.exception(
                    "Error copying asset %s: %s", source_metadata.location_str, str(e)
                )

    def delete_all_course_assets(self, course_key):
        """
        Delete all assets for a course.

        Args:
            course_key: CourseKey identifying the course
        """
        course_key_str = str(course_key)

        # Get all assets for this course
        assets = S3AssetMetadata.objects.filter(course_key_str=course_key_str)

        for metadata in assets:
            try:
                # Delete from S3
                if self.storage.exists(metadata.s3_key):
                    self.storage.delete(metadata.s3_key)
                    log.info("Deleted S3 object: %s", metadata.s3_key)
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.exception(
                    "Error deleting S3 object %s: %s", metadata.s3_key, str(e)
                )

        # Delete all metadata records
        deleted_count, _ = assets.delete()
        log.info(
            "Deleted %d asset metadata records for course %s", deleted_count, course_key
        )

    def remove_redundant_content_for_courses(self):
        """
        Find and remove redundant files (like .DS_Store) for all courses.

        Returns:
            int: Number of assets deleted
        """
        from xmodule.modulestore.django import ASSET_IGNORE_REGEX

        pattern = re.compile(ASSET_IGNORE_REGEX)

        # Find assets matching the ignore pattern
        all_assets = S3AssetMetadata.objects.all()
        assets_to_delete = []

        for metadata in all_assets:
            if pattern.match(metadata.asset_name):
                assets_to_delete.append(metadata)

        # Delete matching assets
        deleted_count = 0
        for metadata in assets_to_delete:
            try:
                if self.storage.exists(metadata.s3_key):
                    self.storage.delete(metadata.s3_key)
                metadata.delete()
                deleted_count += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                log.exception(
                    "Error deleting redundant asset %s: %s", metadata.s3_key, str(e)
                )

        log.info("Removed %d redundant assets", deleted_count)
        return deleted_count

    def check_connection(self):
        """
        Check if the S3 connection is working.

        Returns:
            bool: True if connection is successful, False otherwise
        """
        try:
            self.s3_client.head_bucket(Bucket=self.bucket)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code == "403":
                log.error("Access denied to S3 bucket %s", self.bucket)
            elif error_code == "404":
                log.error("S3 bucket %s does not exist", self.bucket)
            else:
                log.error("S3 connection error: %s", str(e))
            return False
        except Exception as e:  # pylint: disable=broad-exception-caught
            log.error("Unexpected error checking S3 connection: %s", str(e))
            return False

    def ensure_indexes(self):
        """
        Ensure database indexes are created.

        This is a no-op for S3ContentStore since Django ORM handles indexes
        via migrations.
        """
        # No-op: Django ORM handles indexes via migrations

    def get_url_for_asset(self, location, expires_in=3600):
        """
        Get a pre-signed URL for an asset.

        Args:
            location: AssetKey identifying the asset
            expires_in: URL expiration time in seconds (default: 1 hour)

        Returns:
            str: Pre-signed URL for the asset

        Raises:
            NotFoundError: If the asset is not found
        """
        location_str = str(location)

        try:
            metadata = S3AssetMetadata.objects.get(location_str=location_str)
        except S3AssetMetadata.DoesNotExist as exc:
            raise NotFoundError(location_str) from exc

        try:
            url = self.s3_client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": metadata.s3_key,
                },
                ExpiresIn=expires_in,
            )
            return url
        except Exception as e:
            log.error("Error generating presigned URL for %s: %s", location, str(e))
            raise


class S3ContentStoreWithMongoFallback(S3ContentStore):
    """
    S3 ContentStore with MongoDB fallback for existing assets.

    This class extends S3ContentStore to provide backward compatibility during
    migration from MongoDB to S3. When an asset is not found in S3, it falls
    back to MongoDB GridFS to serve existing content.

    New uploads always go to S3. Reads check S3 first, then MongoDB.

    The MongoDB connection uses the existing DOC_STORE_CONFIG from Django settings,
    which Tutor already configures. No additional MongoDB configuration needed.

    Configuration example:
        CONTENTSTORE = {
            'ENGINE': 'openedx.core.djangoapps.s3_contentstore.s3.S3ContentStoreWithMongoFallback',
            'DOC_STORE_CONFIG': {
                'bucket': 'my-edx-course-assets',
                'region_name': 'us-east-1',
                'access_key': '...',
                'secret_key': '...',
            },
        }

    Once migration is complete, switch to S3ContentStore (without fallback).
    """

    def __init__(self, **kwargs):
        """
        Initialize S3ContentStore with MongoDB fallback.

        MongoDB settings are read from Django's DOC_STORE_CONFIG automatically.
        Only S3 settings need to be passed.
        """
        # Initialize S3 store (parent class)
        super().__init__(**kwargs)

        # Lazy initialization for MongoDB store
        self._mongo_store = None

        log.info(
            "S3ContentStoreWithMongoFallback initialized. "
            "S3 bucket: %s, MongoDB fallback enabled (using DOC_STORE_CONFIG).",
            self.bucket,
        )

    def _get_mongo_store(self):
        """
        Lazily initialize and return the MongoDB ContentStore.

        Uses DOC_STORE_CONFIG from Django settings, which Tutor already configures.

        Returns:
            MongoContentStore instance or None if initialization fails
        """
        if self._mongo_store is not None:
            return self._mongo_store

        try:
            from xmodule.contentstore.mongo import MongoContentStore

            # Use DOC_STORE_CONFIG directly - Tutor already sets this up
            doc_store_config = getattr(settings, "DOC_STORE_CONFIG", {})

            if not doc_store_config:
                log.warning("DOC_STORE_CONFIG not found, MongoDB fallback disabled")
                return None

            self._mongo_store = MongoContentStore(**doc_store_config)
            log.info("MongoDB fallback ContentStore initialized using DOC_STORE_CONFIG")

            return self._mongo_store

        except Exception as e:
            log.error("Failed to initialize MongoDB fallback: %s", str(e))
            return None

    def find(self, location, throw_on_not_found=True, as_stream=False):
        """
        Find content, checking S3 first then falling back to MongoDB.

        Args:
            location: AssetKey identifying the asset
            throw_on_not_found: If True, raise NotFoundError when not found
            as_stream: If True, return StaticContentStream for streaming

        Returns:
            StaticContent or StaticContentStream, or None if not found
        """
        # Try S3 first
        try:
            content = super().find(
                location, throw_on_not_found=False, as_stream=as_stream
            )
            if content is not None:
                log.debug("Asset found in S3: %s", location)
                return content
        except Exception as e:
            log.debug("S3 lookup failed for %s: %s", location, str(e))

        # Fall back to MongoDB
        log.debug("Asset not in S3, trying MongoDB fallback: %s", location)
        mongo_store = self._get_mongo_store()

        if mongo_store is None:
            if throw_on_not_found:
                raise NotFoundError(str(location))
            return None

        try:
            content = mongo_store.find(
                location, throw_on_not_found=throw_on_not_found, as_stream=as_stream
            )
            if content is not None:
                log.info("Asset found in MongoDB (fallback): %s", location)
            return content
        except NotFoundError:
            if throw_on_not_found:
                raise
            return None
        except Exception as e:
            log.error("MongoDB fallback error for %s: %s", location, str(e))
            if throw_on_not_found:
                raise NotFoundError(str(location))
            return None

    def get_all_content_for_course(
        self, course_key, start=0, maxresults=-1, sort=None, filter_params=None
    ):
        """
        Get all content for a course, merging S3 and MongoDB results.

        Returns assets from both S3 and MongoDB, with S3 taking precedence
        for assets that exist in both stores.
        """
        # Get S3 assets
        s3_assets, s3_count = super().get_all_content_for_course(
            course_key, start=0, maxresults=-1, sort=sort, filter_params=filter_params
        )

        # Build set of S3 asset keys for deduplication
        s3_asset_keys = {str(a["asset_key"]) for a in s3_assets}

        # Get MongoDB assets
        mongo_assets = []
        mongo_store = self._get_mongo_store()
        if mongo_store:
            try:
                mongo_result, _ = mongo_store.get_all_content_for_course(
                    course_key,
                    start=0,
                    maxresults=-1,
                    sort=sort,
                    filter_params=filter_params,
                )
                # Only include MongoDB assets not already in S3
                for asset in mongo_result:
                    asset_key_str = str(asset.get("asset_key", ""))
                    if asset_key_str and asset_key_str not in s3_asset_keys:
                        mongo_assets.append(asset)
                        log.debug("Including MongoDB asset: %s", asset_key_str)
            except Exception as e:
                log.warning(
                    "Error getting MongoDB assets for %s: %s", course_key, str(e)
                )

        # Merge results
        all_assets = s3_assets + mongo_assets
        total_count = len(all_assets)

        # Apply sorting if needed (assets from different sources)
        if sort and mongo_assets:
            # Re-sort the merged list
            for field, direction in reversed(sort):
                reverse = direction == -1
                if field == "displayname":
                    all_assets.sort(
                        key=lambda x: x.get("displayname", ""), reverse=reverse
                    )
                elif field == "uploadDate":
                    all_assets.sort(key=lambda x: x.get("uploadDate"), reverse=reverse)
                elif field == "contentType":
                    all_assets.sort(
                        key=lambda x: x.get("contentType", ""), reverse=reverse
                    )

        # Apply pagination
        if maxresults > 0:
            all_assets = all_assets[start : start + maxresults]
        elif start > 0:
            all_assets = all_assets[start:]

        return all_assets, total_count

    def get_all_content_thumbnails_for_course(self, course_key):
        """Get thumbnails from both S3 and MongoDB."""
        # Get S3 thumbnails
        s3_thumbnails = super().get_all_content_thumbnails_for_course(course_key)
        s3_thumb_keys = {str(t) for t in s3_thumbnails} if s3_thumbnails else set()

        # Get MongoDB thumbnails
        mongo_thumbnails = []
        mongo_store = self._get_mongo_store()
        if mongo_store:
            try:
                mongo_result = mongo_store.get_all_content_thumbnails_for_course(
                    course_key
                )
                if mongo_result:
                    for thumb in mongo_result:
                        if str(thumb) not in s3_thumb_keys:
                            mongo_thumbnails.append(thumb)
            except Exception as e:
                log.warning("Error getting MongoDB thumbnails: %s", str(e))

        return (s3_thumbnails or []) + mongo_thumbnails

    def get_attr(self, location, attr, default=None):
        """Get attribute, checking S3 first then MongoDB."""
        try:
            return super().get_attr(location, attr, default)
        except NotFoundError:
            mongo_store = self._get_mongo_store()
            if mongo_store:
                try:
                    return mongo_store.get_attr(location, attr, default)
                except Exception:
                    pass
            return default

    def get_attrs(self, location):
        """Get all attributes, checking S3 first then MongoDB."""
        try:
            return super().get_attrs(location)
        except NotFoundError:
            mongo_store = self._get_mongo_store()
            if mongo_store:
                return mongo_store.get_attrs(location)
            raise

    def export(self, location, output_directory):
        """Export asset, checking S3 first then MongoDB."""
        try:
            return super().export(location, output_directory)
        except NotFoundError:
            mongo_store = self._get_mongo_store()
            if mongo_store:
                return mongo_store.export(location, output_directory)
            raise

    def export_all_for_course(self, course_key, output_directory, assets_policy_file):
        """Export all course assets from both S3 and MongoDB."""
        policy = {}
        assets, _ = self.get_all_content_for_course(course_key)

        for asset in assets:
            try:
                asset_key = asset.get("asset_key")
                if not asset_key:
                    continue

                # Try to export (will check S3 then MongoDB)
                self.export(asset_key, output_directory)

                for attr, value in asset.items():
                    if attr not in [
                        "_id",
                        "md5",
                        "uploadDate",
                        "length",
                        "chunkSize",
                        "asset_key",
                    ]:
                        policy.setdefault(asset_key.block_id, {})[attr] = value
            except Exception as e:
                log.exception(
                    "Failed to export asset %s: %s", asset.get("asset_key"), str(e)
                )

        with open(assets_policy_file, "w") as f:
            json.dump(policy, f, sort_keys=True, indent=4)
