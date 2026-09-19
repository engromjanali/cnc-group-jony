import cloudinary.api
import cloudinary.uploader
import cloudinary.utils
from cloudinary.exceptions import NotFound
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .. import config
from .base import StorageService, StoredObject, UploadedObject


def delivery_url(public_id):
    """Display URL for a public image. Needs only the cloud name, so listing
    images never requires the API credentials."""
    url, _ = cloudinary.utils.cloudinary_url(
        public_id,
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        secure=True,
        raw_transformation=config.IMAGE_DELIVERY_TRANSFORMATION,
    )
    return url


class CloudinaryStorageService(StorageService):
    """Public preview images, uploaded by this backend with the API secret
    (which therefore never leaves it)."""

    provider = 'cloudinary'

    def __init__(self):
        if not (
            settings.CLOUDINARY_CLOUD_NAME
            and settings.CLOUDINARY_API_KEY
            and settings.CLOUDINARY_API_SECRET
        ):
            raise ImproperlyConfigured('Cloudinary is not configured (see .env.example).')
        # Passed per call instead of through cloudinary.config(), so nothing
        # depends on process-global SDK state.
        self._options = {
            'cloud_name': settings.CLOUDINARY_CLOUD_NAME,
            'api_key': settings.CLOUDINARY_API_KEY,
            'api_secret': settings.CLOUDINARY_API_SECRET,
            'secure': True,
        }

    def store(self, file, *, owner_id, file_name, content_type):
        result = cloudinary.uploader.upload(
            file,
            folder=config.image_folder(owner_id),
            resource_type='image',
            unique_filename=True,
            overwrite=False,
            **self._options,
        )
        return UploadedObject(
            storage_key=result['public_id'],
            size=result.get('bytes', 0),
            content_type=f"image/{result.get('format', '')}",
        )

    def describe(self, storage_key):
        try:
            resource = cloudinary.api.resource(storage_key, **self._options)
        except NotFound:
            return None
        return StoredObject(
            size=resource.get('bytes', 0),
            content_type=f"image/{resource.get('format', '')}",
        )

    def delete(self, storage_key):
        cloudinary.uploader.destroy(storage_key, invalidate=True, **self._options)

    def url_for(self, storage_key, download_name=None):
        return delivery_url(storage_key)
