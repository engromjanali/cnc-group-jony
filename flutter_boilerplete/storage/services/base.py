from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass(frozen=True)
class StoredObject:
    """What a provider reports about an object it holds."""

    size: int
    content_type: str


@dataclass(frozen=True)
class UploadedObject:
    """What a provider reports after taking an upload: where it put the file
    (`storage_key`) and what it actually stored."""

    storage_key: str
    size: int
    content_type: str


class StorageService(ABC):
    """One storage provider. Views and models only ever talk to this interface,
    so swapping a provider means adding an implementation, not editing callers.

    `storage_key` is whatever the provider addresses objects by - an R2 object
    key or a Cloudinary public_id. It is the only thing persisted; URLs are
    always built on demand."""

    provider: str

    @abstractmethod
    def store(self, file, *, owner_id, file_name, content_type, folder=None, key_prefix=None, **kwargs):
        """Upload `file` (a readable file object) for `owner_id` and return an
        `UploadedObject`. The provider picks the storage key, never the client."""

    @abstractmethod
    def describe(self, storage_key):
        """The object's metadata, or None when it does not exist."""

    @abstractmethod
    def delete(self, storage_key):
        """Remove the object. Deleting a missing object is not an error."""

    @abstractmethod
    def url_for(self, storage_key, download_name=None):
        """A URL a client can fetch the object from. Private providers return
        a short-lived signed URL, so never persist the result."""
