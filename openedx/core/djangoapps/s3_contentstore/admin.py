from django.contrib import admin

from .models import S3AssetMetadata


@admin.register(S3AssetMetadata)
class S3AssetMetadataAdmin(admin.ModelAdmin):
    """Admin registration for S3AssetMetadata."""

    list_display = (
        "asset_name",
        "location_str",
        "course_key_str",
        "content_type",
        "length",
        "locked",
        "created_at",
        "updated_at",
    )

    list_filter = (
        "content_type",
        "locked",
        "course_key_str",
    )

    search_fields = (
        "asset_name",
        "location_str",
        "s3_key",
        "course_key_str",
    )

    readonly_fields = (
        "content_digest",
        "s3_key",
        "created_at",
        "updated_at",
    )

    ordering = ("-created_at",)

    list_per_page = 50

    fieldsets = (
        (
            None,
            {
                "fields": (
                    "asset_name",
                    "location_str",
                    "course_key_str",
                    "s3_key",
                    "content_type",
                    "length",
                    "locked",
                    "thumbnail_location",
                    "import_path",
                    "content_digest",
                ),
            },
        ),
        (
            "Timestamps & Metadata",
            {
                "fields": (
                    "created_at",
                    "updated_at",
                    "custom_metadata",
                ),
                "classes": ("collapse",),
            },
        ),
    )
