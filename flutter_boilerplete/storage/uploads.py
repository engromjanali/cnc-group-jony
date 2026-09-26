import logging

from .models import StoredFile
from .services import get_storage_service

logger = logging.getLogger(__name__)


def store_upload(owner, provider, file, *, file_name, content_type, folder=None, key_prefix=None, **kwargs):
    """Uploads `file` to `provider` and records it. If recording fails the
    object is removed again, so nothing is left in storage with no row."""
    service = get_storage_service(provider)
    uploaded = service.store(
        file, owner_id=owner.id, file_name=file_name, content_type=content_type,
        folder=folder, key_prefix=key_prefix, **kwargs,
    )
    try:
        return StoredFile.objects.create(
            owner=owner,
            provider=provider,
            storage_key=uploaded.storage_key,
            original_name=file_name[:255],
            content_type=uploaded.content_type,
            size=uploaded.size,
            status=StoredFile.Status.READY,
        )
    except Exception:
        _delete_object(provider, uploaded.storage_key)
        raise


def discard(stored_file):
    """Removes a file from its provider and forgets it. Best effort on the
    provider side: a failure there is logged and the row is still removed, so
    at worst an object is left behind - never a row pointing at nothing."""
    _delete_object(stored_file.provider, stored_file.storage_key)
    stored_file.delete()


def _delete_object(provider, storage_key):
    try:
        get_storage_service(provider).delete(storage_key)
    except Exception:
        logger.exception('Failed to delete %s object %s', provider, storage_key)
