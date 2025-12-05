from django.apps import AppConfig


class S3ContentStoreConfig(AppConfig):
    """
    Django app configuration for S3ContentStore.
    This app provides S3-backed storage for Open edX course assets.
    """

    name = "openedx.core.djangoapps.s3_contentstore"
    label = "s3_contentstore"
    verbose_name = "S3 Content Store"

    def ready(self):
        """
        Called when Django starts up.
        """
        pass
