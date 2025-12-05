"""
S3 ContentStore Django app.

This app provides S3-backed storage for Open edX course assets (images, PDFs,
videos, etc.) as an alternative to MongoDB GridFS.
"""

default_app_config = 'openedx.core.djangoapps.s3_contentstore.apps.S3ContentStoreConfig'
