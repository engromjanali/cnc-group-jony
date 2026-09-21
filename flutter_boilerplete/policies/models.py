from django.conf import settings
from django.db import models
from django.db.models import Q

from .limits import MAX_TITLE_LENGTH


class PrivacyPolicy(models.Model):
    """The app's privacy policy - one document, written by an admin.

    There is only ever one row: it always has [SINGLETON_PK] as its id, the
    database refuses any other, and saving a new instance replaces the existing
    document instead of adding a second one."""

    SINGLETON_PK = 1

    title = models.CharField(max_length=MAX_TITLE_LENGTH)
    # HTML, as the app's rich-text editor writes it; the app renders it.
    content = models.TextField()
    updated_at = models.DateTimeField(auto_now=True)
    # Who saved it last. Kept as a record only: deleting that account leaves
    # the policy in place.
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='+', on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        verbose_name = 'privacy policy'
        verbose_name_plural = 'privacy policy'
        constraints = [
            models.CheckConstraint(
                condition=Q(pk=1), name='privacy_policy_is_a_single_document',
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        # A second `PrivacyPolicy(...).save()` is an edit of the one document,
        # not a second insert that the constraint would then have to refuse.
        kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        """The saved policy, or None until an admin has written one."""
        return cls.objects.filter(pk=cls.SINGLETON_PK).first()
