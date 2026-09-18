import uuid

from django.conf import settings
from django.db import models


class StoredFile(models.Model):
    """A private file living in R2. Bytes never pass through this backend -
    the app PUTs and GETs them directly with presigned URLs."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        READY = 'ready', 'Ready'

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='stored_files', on_delete=models.CASCADE,
    )
    # Server-generated: users/{owner_id}/{uuid}-{sanitized name}. Never client supplied.
    key = models.CharField(max_length=512, unique=True)
    original_name = models.CharField(max_length=255)
    content_type = models.CharField(max_length=128)
    size = models.BigIntegerField()
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [models.Index(fields=['owner', 'status'])]

    def __str__(self):
        return f'{self.original_name} ({self.status})'
