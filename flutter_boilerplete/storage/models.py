import uuid

from django.conf import settings
from django.db import models


class StoredFile(models.Model):
    """A file held by an external provider. Bytes never pass through this
    backend - the app uploads and downloads them directly."""

    class Provider(models.TextChoices):
        CLOUDINARY = 'cloudinary', 'Cloudinary'
        R2 = 'r2', 'Cloudflare R2'

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        READY = 'ready', 'Ready'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='stored_files', on_delete=models.CASCADE,
    )
    provider = models.CharField(max_length=16, choices=Provider.choices)
    # An R2 object key or a Cloudinary public_id, always server generated or
    # server verified. Never a URL - those are built on demand.
    storage_key = models.CharField(max_length=512)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        constraints = [
            models.UniqueConstraint(
                fields=['provider', 'storage_key'], name='unique_provider_storage_key',
            ),
        ]
        indexes = [models.Index(fields=['owner', 'status'])]

    def __str__(self):
        return f'{self.original_name} ({self.provider}, {self.status})'
