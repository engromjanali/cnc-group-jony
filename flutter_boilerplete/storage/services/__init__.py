from .base import StorageService, StoredObject, UploadedObject
from .cloudinary_service import CloudinaryStorageService, delivery_url
from .r2_service import R2StorageService

_SERVICES = {
    CloudinaryStorageService.provider: CloudinaryStorageService,
    R2StorageService.provider: R2StorageService,
}


def get_storage_service(provider):
    """The implementation for a `StoredFile.provider` value."""
    return _SERVICES[provider]()


__all__ = [
    'StorageService',
    'StoredObject',
    'UploadedObject',
    'CloudinaryStorageService',
    'R2StorageService',
    'delivery_url',
    'get_storage_service',
]
