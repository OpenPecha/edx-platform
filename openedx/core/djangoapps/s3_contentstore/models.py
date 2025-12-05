"""
Django models for S3ContentStore metadata storage.

This module contains the database models used to store metadata about assets
stored in S3. The actual file data is stored in S3, while the metadata
(content type, size, location, etc.) is stored in the database for efficient
querying and management.
"""

from django.db import models
from django.utils import timezone


class S3AssetMetadata(models.Model):
    """
    Database model for storing S3 asset metadata.

    This model stores metadata about course assets that are stored in S3.
    It enables efficient querying, filtering, and management of assets
    without needing to query S3 directly.

    Attributes:
        location_str: The string representation of the AssetKey (unique)
        course_key_str: The string representation of the CourseKey
        s3_key: The S3 object key where the file is stored
        asset_name: The display name of the asset (e.g., 'image.png')
        content_type: MIME type of the asset
        content_digest: MD5 hash of the file content
        length: File size in bytes
        thumbnail_location: String representation of the thumbnail AssetKey
        import_path: Original import path (for course import/export)
        locked: Whether the asset is locked
        custom_metadata: JSON field for additional custom attributes
        created_at: Timestamp when the asset was first uploaded
        updated_at: Timestamp when the asset was last modified
    """

    # Primary identifier - the asset's location as a string
    # Max length reduced from 500 to 255 for MySQL compatibility
    location_str = models.CharField(
        max_length=255,
        unique=True,
        db_index=True,
        help_text="String representation of the asset's location (AssetKey)",
    )

    # Course association - allows filtering all assets for a course
    course_key_str = models.CharField(
        max_length=255,
        db_index=True,
        help_text="String representation of the course key",
    )

    # S3 storage location
    s3_key = models.CharField(
        max_length=255,
        db_index=True,
        help_text="S3 object key where the file is stored",
    )

    # Asset metadata
    asset_name = models.CharField(
        max_length=255, default="", help_text="Display name of the asset"
    )

    content_type = models.CharField(
        max_length=255,
        default="application/octet-stream",
        help_text="MIME type of the asset",
    )

    content_digest = models.CharField(
        max_length=64, blank=True, default="", help_text="MD5 hash of the file content"
    )

    length = models.BigIntegerField(default=0, help_text="File size in bytes")

    # Related assets
    thumbnail_location = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="String representation of the thumbnail location",
    )

    # Import/export support
    import_path = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Original import path from course archive",
    )

    # Access control
    locked = models.BooleanField(default=False, help_text="Whether the asset is locked")

    # Extensibility - store additional attributes as JSON
    custom_metadata = models.JSONField(
        null=True, blank=True, help_text="Additional custom metadata as JSON"
    )

    # Timestamps
    created_at = models.DateTimeField(
        default=timezone.now,
        db_index=True,
        help_text="Timestamp when the asset was first uploaded",
    )

    updated_at = models.DateTimeField(
        auto_now=True, help_text="Timestamp when the asset was last modified"
    )

    class Meta:
        app_label = "s3_contentstore"
        db_table = "s3_contentstore_asset_metadata"
        indexes = [
            models.Index(fields=["course_key_str", "created_at"]),
            models.Index(fields=["course_key_str", "asset_name"]),
            models.Index(fields=["content_type"]),
        ]
        ordering = ["-created_at"]
        verbose_name = "S3 Asset Metadata"
        verbose_name_plural = "S3 Asset Metadata"

    def __str__(self):
        return f"{self.asset_name} ({self.location_str})"

    def __repr__(self):
        return f"<S3AssetMetadata: {self.location_str}>"
