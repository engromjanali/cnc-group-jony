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

    # Maintenance mode, app versioning and registration status
    maintenance_mode = models.BooleanField(default=False)
    app_version = models.CharField(max_length=50, blank=True, default='1.0.0')
    min_supported_version = models.CharField(max_length=50, blank=True, default='1.0.0')
    registration_enabled = models.BooleanField(default=True)
    google_login_enabled = models.BooleanField(default=True)

    # Allowed file and image extensions (comma-separated, e.g. "jpg, jpeg, png, webp, gif")
    allowed_image_extensions = models.CharField(
        max_length=255, blank=True, default='jpg, jpeg, png, webp, gif',
    )
    allowed_file_extensions = models.CharField(
        max_length=500, blank=True, default='pdf, zip, svg, dxf, dwg, nc, tap, gcode, cnc, plt, ai, eps',
    )

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

    wallet_warning_text = models.CharField(max_length=2000, blank=True, default='')
    wallet_offer_text = models.CharField(max_length=2000, blank=True, default='')

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

    @staticmethod
    def _parse_extensions(raw_value, default_set, is_image=False):
        if not raw_value or not raw_value.strip():
            return frozenset(default_set)
        result = set()
        for item in raw_value.split(','):
            cleaned = item.strip().lstrip('.').lower()
            if cleaned:
                result.add(cleaned)
                if is_image:
                    if cleaned == 'jpg':
                        result.add('jpeg')
                    elif cleaned == 'jpeg':
                        result.add('jpg')
        return frozenset(result) if result else frozenset(default_set)

    def get_allowed_image_extensions(self):
        from storage import config as storage_config
        return self._parse_extensions(self.allowed_image_extensions, storage_config.ALLOWED_IMAGE_FORMATS, is_image=True)

    def get_allowed_file_extensions(self):
        from storage import config as storage_config
        return self._parse_extensions(self.allowed_file_extensions, storage_config.ALLOWED_FILE_EXTENSIONS, is_image=False)

    @classmethod
    def get_current_allowed_image_extensions(cls):
        setting = cls.current()
        if setting is not None:
            return setting.get_allowed_image_extensions()
        from storage import config as storage_config
        return storage_config.ALLOWED_IMAGE_FORMATS

    @classmethod
    def get_current_allowed_file_extensions(cls):
        setting = cls.current()
        if setting is not None:
            return setting.get_allowed_file_extensions()
        from storage import config as storage_config
        return storage_config.ALLOWED_FILE_EXTENSIONS
