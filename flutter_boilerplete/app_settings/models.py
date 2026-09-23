from django.conf import settings
from django.db import models
from django.db.models import Q

from .limits import MAX_CONTACT_LENGTH, MAX_URL_LENGTH


class AppSetting(models.Model):
    """The options an admin can set for the whole app - one document.

    There is only ever one row: it always has [SINGLETON_PK] as its id, the
    database refuses any other, and saving a new instance replaces the existing
    document instead of adding a second one.

    A blank option means "not set". New options are new columns here."""

    SINGLETON_PK = 1

    # Where the Android app can be installed from - the Play Store page, or a
    # direct download link.
    android_app_url = models.CharField(max_length=MAX_URL_LENGTH, blank=True, default='')
    # Where the iOS app can be installed from - the App Store page or TestFlight.
    ios_app_url = models.CharField(max_length=MAX_URL_LENGTH, blank=True, default='')

    # Help & Support contact channels shown to every user. Each has its own
    # value and its own switch, so an admin can hide a channel without losing
    # the value already saved for it.
    help_support_email = models.CharField(max_length=MAX_CONTACT_LENGTH, blank=True, default='')
    help_support_email_enabled = models.BooleanField(default=True)
    help_support_whatsapp = models.CharField(max_length=MAX_CONTACT_LENGTH, blank=True, default='')
    help_support_whatsapp_enabled = models.BooleanField(default=True)
    help_support_telegram = models.CharField(max_length=MAX_CONTACT_LENGTH, blank=True, default='')
    help_support_telegram_enabled = models.BooleanField(default=True)
    help_support_phone = models.CharField(max_length=MAX_CONTACT_LENGTH, blank=True, default='')
    help_support_phone_enabled = models.BooleanField(default=True)

    updated_at = models.DateTimeField(auto_now=True)
    # Who saved it last. Kept as a record only: deleting that account leaves
    # the settings in place.
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='+', on_delete=models.SET_NULL,
        null=True, blank=True,
    )

    class Meta:
        verbose_name = 'app setting'
        verbose_name_plural = 'app setting'
        constraints = [
            models.CheckConstraint(
                condition=Q(pk=1), name='app_setting_is_a_single_document',
            ),
        ]

    def __str__(self):
        return 'App setting'

    def save(self, *args, **kwargs):
        self.pk = self.SINGLETON_PK
        # A second `AppSetting(...).save()` is an edit of the one document, not
        # a second insert that the constraint would then have to refuse.
        kwargs.pop('force_insert', None)
        super().save(*args, **kwargs)

    @classmethod
    def current(cls):
        """The saved settings, or None until an admin has saved any."""
        return cls.objects.filter(pk=cls.SINGLETON_PK).first()
