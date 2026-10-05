from django.conf import settings
from django.db import models

from .limits import MAX_TITLE_LENGTH


class Notification(models.Model):
    """A notification an admin sent to every user. Kept so the app can show it
    again when the push is tapped."""

    title = models.CharField(max_length=MAX_TITLE_LENGTH)
    # Plain text; the app shows it as written, line breaks included.
    body = models.TextField()
    # Kept when the admin's account is deleted.
    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sent_notifications',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at', '-id']

    def __str__(self):
        return self.title
