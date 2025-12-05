"""
Management command to migrate course assets from MongoDB GridFS to S3.

This command reads assets from the MongoDB-based ContentStore and saves them
to the S3-based ContentStore. It supports migrating:
- A single course
- All courses in an organization
- All courses in the system

Usage:
    # Migrate a single course
    ./manage.py cms migrate_assets_to_s3 --course course-v1:Org+Course+Run

    # Migrate all courses in an organization
    ./manage.py cms migrate_assets_to_s3 --org MyOrg

    # Migrate all courses
    ./manage.py cms migrate_assets_to_s3 --all

    # Dry run (preview what would be migrated)
    ./manage.py cms migrate_assets_to_s3 --all --dry-run

    # Skip already migrated assets
    ./manage.py cms migrate_assets_to_s3 --all --skip-existing

    # Delete from MongoDB after successful migration
    ./manage.py cms migrate_assets_to_s3 --all --delete-after-migration
"""

import logging
import time
from textwrap import dedent

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from opaque_keys.edx.keys import CourseKey

from openedx.core.djangoapps.s3_contentstore.models import S3AssetMetadata
from openedx.core.djangoapps.s3_contentstore.s3 import S3ContentStore
from xmodule.contentstore.mongo import MongoContentStore
from xmodule.modulestore.django import modulestore

log = logging.getLogger(__name__)


class Command(BaseCommand):
    """
    Django management command to migrate course assets from MongoDB to S3.
    """

    help = dedent(__doc__ or "")

    def __init__(self, *args, **kwargs):
        """Initialize command with default attribute values."""
        super().__init__(*args, **kwargs)
        self.dry_run = False
        self.skip_existing = False
        self.delete_after = False
        self.batch_size = 100
        self.include_thumbnails = False
        self.verbosity = 1
        self.stats = {}
        self.mongo_store = None
        self.s3_store = None

    def add_arguments(self, parser):
        """Define command line arguments."""
        # Target selection (mutually exclusive)
        target_group = parser.add_mutually_exclusive_group(required=True)
        target_group.add_argument(
            "--course",
            type=str,
            help="Course ID to migrate (e.g., course-v1:Org+Course+Run)",
        )
        target_group.add_argument(
            "--org",
            type=str,
            help="Organization ID to migrate all courses for",
        )
        target_group.add_argument(
            "--all",
            action="store_true",
            dest="migrate_all",
            help="Migrate all courses in the system",
        )

        # Migration options
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Preview what would be migrated without making changes",
        )
        parser.add_argument(
            "--skip-existing",
            action="store_true",
            help="Skip assets that already exist in S3",
        )
        parser.add_argument(
            "--delete-after-migration",
            action="store_true",
            help="Delete assets from MongoDB after successful migration to S3",
        )
        parser.add_argument(
            "--batch-size",
            type=int,
            default=100,
            help="Number of assets to process in each batch (default: 100)",
        )
        parser.add_argument(
            "--include-thumbnails",
            action="store_true",
            help="Also migrate thumbnail assets",
        )

    def handle(self, *args, **options):
        """Execute the migration command."""
        self.dry_run = options["dry_run"]
        self.skip_existing = options["skip_existing"]
        self.delete_after = options["delete_after_migration"]
        self.batch_size = options["batch_size"]
        self.include_thumbnails = options["include_thumbnails"]
        self.verbosity = options["verbosity"]

        # Statistics tracking
        self.stats = {
            "courses_processed": 0,
            "assets_found": 0,
            "assets_migrated": 0,
            "assets_skipped": 0,
            "assets_failed": 0,
            "bytes_migrated": 0,
        }

        start_time = time.time()

        if self.dry_run:
            self.stdout.write(self.style.WARNING("\n=== DRY RUN MODE ===\n"))

        try:
            # Initialize content stores
            self._init_content_stores()

            # Get courses to migrate
            if options["course"]:
                courses = [self._parse_course_key(options["course"])]
            elif options["org"]:
                courses = self._get_courses_for_org(options["org"])
            else:
                courses = self._get_all_courses()

            if not courses:
                self.stdout.write(self.style.WARNING("No courses found to migrate."))
                return

            self.stdout.write(f"\nFound {len(courses)} course(s) to process.\n")

            # Process each course
            for course_key in courses:
                self._migrate_course(course_key)

        except Exception as e:  # pylint: disable=broad-exception-caught
            raise CommandError(f"Migration failed: {str(e)}") from e

        elapsed_time = time.time() - start_time

        # Print summary
        self._print_summary(elapsed_time)

    def _init_content_stores(self):
        """Initialize MongoDB and S3 content stores."""

        # Get MongoDB contentstore configuration
        # We need to connect to MongoDB directly, not use the current CONTENTSTORE
        mongo_config = getattr(settings, "CONTENTSTORE_MONGO", None)

        if not mongo_config:
            # Try to get from DOC_STORE_CONFIG if available
            doc_store_config = getattr(settings, "DOC_STORE_CONFIG", None)
            if doc_store_config:
                mongo_config = {
                    "ENGINE": "xmodule.contentstore.mongo.MongoContentStore",
                    "DOC_STORE_CONFIG": doc_store_config,
                }
            else:
                # Fallback: try common MongoDB settings
                mongo_config = {
                    "ENGINE": "xmodule.contentstore.mongo.MongoContentStore",
                    "DOC_STORE_CONFIG": {
                        "host": getattr(settings, "MONGODB_HOST", "mongodb"),
                        "port": getattr(settings, "MONGODB_PORT", 27017),
                        "db": getattr(settings, "MONGODB_NAME", "edxapp"),
                        "collection": "fs",
                        "user": getattr(settings, "MONGODB_USER", None),
                        "password": getattr(settings, "MONGODB_PASSWORD", None),
                    },
                }

        self.stdout.write("Initializing MongoDB ContentStore...")

        try:
            mongo_options = mongo_config.get("DOC_STORE_CONFIG", {})
            self.mongo_store = MongoContentStore(**mongo_options)
            self.stdout.write(self.style.SUCCESS("  MongoDB ContentStore initialized."))
        except Exception as e:  # pylint: disable=broad-exception-caught
            raise CommandError(f"Failed to initialize MongoDB ContentStore: {e}") from e

        # Initialize S3 ContentStore
        self.stdout.write("Initializing S3 ContentStore...")

        try:
            s3_config = settings.CONTENTSTORE.get("DOC_STORE_CONFIG", {})
            self.s3_store = S3ContentStore(**s3_config)

            # Check S3 connection
            if not self.s3_store.check_connection():
                raise CommandError(
                    "Failed to connect to S3. Check your credentials and bucket configuration."
                )

            self.stdout.write(self.style.SUCCESS("  S3 ContentStore initialized."))
        except ImportError as exc:
            raise CommandError(
                "S3ContentStore not available. Is the s3_contentstore app installed?"
            ) from exc
        except Exception as e:  # pylint: disable=broad-exception-caught
            raise CommandError(f"Failed to initialize S3 ContentStore: {e}") from e

    def _parse_course_key(self, course_id):
        """Parse a course ID string into a CourseKey."""
        try:
            return CourseKey.from_string(course_id)
        except Exception as e:  # pylint: disable=broad-exception-caught
            raise CommandError(f"Invalid course ID '{course_id}': {e}") from e

    def _get_courses_for_org(self, org):
        """Get all course keys for an organization."""

        self.stdout.write(f"Finding courses for organization: {org}")

        store = modulestore()
        courses = store.get_courses()  # type: ignore[union-attr]
        org_courses = [c.id for c in courses if c.id.org == org]

        self.stdout.write(f"  Found {len(org_courses)} course(s) for org '{org}'.")
        return org_courses

    def _get_all_courses(self):
        """Get all course keys in the system."""

        self.stdout.write("Finding all courses...")

        store = modulestore()
        courses = store.get_courses()  # type: ignore[union-attr]
        course_keys = [c.id for c in courses]

        self.stdout.write(f"  Found {len(course_keys)} total course(s).")
        return course_keys

    def _migrate_course(self, course_key):
        """Migrate all assets for a single course."""
        self.stdout.write(f"\n{'=' * 60}")
        self.stdout.write(f"Processing course: {course_key}")
        self.stdout.write(f"{'=' * 60}")

        self.stats["courses_processed"] += 1

        try:
            # Ensure stores are initialized
            assert self.mongo_store is not None, "MongoDB store not initialized"

            # Get all assets from MongoDB
            assets, total_count = self.mongo_store.get_all_content_for_course(
                course_key,
                start=0,
                maxresults=-1,  # Get all
            )

            if self.include_thumbnails:
                thumbnails = self.mongo_store.get_all_content_thumbnails_for_course(
                    course_key
                )
                assets.extend(
                    [{"asset_key": t} for t in thumbnails]
                    if isinstance(thumbnails, list)
                    else []
                )

            self.stdout.write(f"  Found {len(assets)} asset(s) in MongoDB.")
            self.stats["assets_found"] += len(assets)

            # Process each asset
            for i, asset_info in enumerate(assets, 1):
                asset_key = asset_info.get("asset_key")
                if not asset_key:
                    continue

                self._migrate_asset(asset_key, i, len(assets))

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.stdout.write(
                self.style.ERROR(f"  Error processing course {course_key}: {e}")
            )
            log.exception(f"Error migrating course {course_key}")

    def _migrate_asset(self, asset_key, index, total):
        """Migrate a single asset from MongoDB to S3."""
        asset_name = (
            asset_key.block_id if hasattr(asset_key, "block_id") else str(asset_key)
        )

        if self.verbosity >= 2:
            self.stdout.write(f"  [{index}/{total}] Processing: {asset_name}")

        # Ensure stores are initialized
        assert self.mongo_store is not None, "MongoDB store not initialized"
        assert self.s3_store is not None, "S3 store not initialized"

        try:
            # Check if asset already exists in S3
            if self.skip_existing:
                if S3AssetMetadata.objects.filter(location_str=str(asset_key)).exists():
                    if self.verbosity >= 2:
                        self.stdout.write("    Skipping (already exists in S3)")
                    self.stats["assets_skipped"] += 1
                    return

            # Read from MongoDB
            try:
                content = self.mongo_store.find(asset_key, throw_on_not_found=True)
            except Exception as e:  # pylint: disable=broad-exception-caught
                if self.verbosity >= 1:
                    self.stdout.write(
                        self.style.WARNING(
                            f"    Warning: Could not read from MongoDB: {e}"
                        )
                    )
                self.stats["assets_failed"] += 1
                return

            if self.dry_run:
                if self.verbosity >= 1:
                    content_length = getattr(content, "length", 0) or 0
                    size_kb = content_length / 1024
                    self.stdout.write(
                        f"    Would migrate: {asset_name} ({size_kb:.1f} KB)"
                    )
                self.stats["assets_migrated"] += 1
                self.stats["bytes_migrated"] += getattr(content, "length", 0) or 0
                return

            # Save to S3
            self.s3_store.save(content)

            self.stats["assets_migrated"] += 1
            self.stats["bytes_migrated"] += getattr(content, "length", 0) or 0

            if self.verbosity >= 2:
                content_length = getattr(content, "length", 0) or 0
                size_kb = content_length / 1024
                self.stdout.write(
                    self.style.SUCCESS(f"    Migrated: {asset_name} ({size_kb:.1f} KB)")
                )

            # Delete from MongoDB if requested
            if self.delete_after:
                try:
                    self.mongo_store.delete(asset_key)
                    if self.verbosity >= 2:
                        self.stdout.write("    Deleted from MongoDB")
                except Exception as e:  # pylint: disable=broad-exception-caught
                    self.stdout.write(
                        self.style.WARNING(
                            f"    Warning: Could not delete from MongoDB: {e}"
                        )
                    )

        except Exception as e:  # pylint: disable=broad-exception-caught
            self.stdout.write(
                self.style.ERROR(f"    Error migrating {asset_name}: {e}")
            )
            log.exception(f"Error migrating asset {asset_key}")
            self.stats["assets_failed"] += 1

    def _print_summary(self, elapsed_time):
        """Print migration summary statistics."""
        self.stdout.write("\n" + "=" * 60)
        self.stdout.write("MIGRATION SUMMARY")
        self.stdout.write("=" * 60)

        if self.dry_run:
            self.stdout.write(self.style.WARNING("Mode: DRY RUN (no changes made)"))
        else:
            self.stdout.write("Mode: LIVE MIGRATION")

        self.stdout.write(f"\nCourses processed:  {self.stats['courses_processed']}")
        self.stdout.write(f"Assets found:       {self.stats['assets_found']}")
        self.stdout.write(f"Assets migrated:    {self.stats['assets_migrated']}")
        self.stdout.write(f"Assets skipped:     {self.stats['assets_skipped']}")
        self.stdout.write(f"Assets failed:      {self.stats['assets_failed']}")

        # Format bytes
        bytes_migrated = self.stats["bytes_migrated"]
        if bytes_migrated > 1024 * 1024 * 1024:
            size_str = f"{bytes_migrated / (1024 * 1024 * 1024):.2f} GB"
        elif bytes_migrated > 1024 * 1024:
            size_str = f"{bytes_migrated / (1024 * 1024):.2f} MB"
        elif bytes_migrated > 1024:
            size_str = f"{bytes_migrated / 1024:.2f} KB"
        else:
            size_str = f"{bytes_migrated} bytes"

        self.stdout.write(f"Data migrated:      {size_str}")
        self.stdout.write(f"Time elapsed:       {elapsed_time:.1f} seconds")

        if self.stats["assets_failed"] > 0:
            self.stdout.write(
                self.style.WARNING(
                    f"\nWarning: {self.stats['assets_failed']} asset(s) failed to migrate. "
                    "Check logs for details."
                )
            )
        elif not self.dry_run and self.stats["assets_migrated"] > 0:
            self.stdout.write(self.style.SUCCESS("\nMigration completed successfully!"))

        self.stdout.write("")
