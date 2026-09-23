from django.core.validators import EmailValidator, URLValidator
from rest_framework import serializers

from .limits import MAX_CONTACT_LENGTH, MAX_URL_LENGTH
from .models import AppSetting

# Only web links. The app opens these in a new browser tab, so anything else -
# `javascript:`, `data:`, `file:` - would be a way to run something instead of
# opening a page. There is no restriction on the host: a direct download link
# on the admin's own server is as valid as a store page.
web_url = URLValidator(schemes=['http', 'https'], message='Enter a valid web address starting with http:// or https://.')


class UrlField(serializers.CharField):
    """A web address that may be blank, which clears it. `null` clears it too."""

    def __init__(self, **kwargs):
        super().__init__(
            required=False, allow_blank=True, allow_null=True,
            max_length=MAX_URL_LENGTH, validators=[web_url], **kwargs,
        )

    def run_validation(self, data=serializers.empty):
        # A blank is how an option is switched off; it comes back as '' from
        # the base field before any validator sees it.
        value = super().run_validation(data)
        return '' if value is None else value


class ContactField(serializers.CharField):
    """A contact value (email, phone number, username) that may be blank,
    which switches the channel off. `null` clears it too."""

    def __init__(self, **kwargs):
        super().__init__(
            required=False, allow_blank=True, allow_null=True,
            max_length=MAX_CONTACT_LENGTH, **kwargs,
        )

    def run_validation(self, data=serializers.empty):
        value = super().run_validation(data)
        return '' if value is None else value


class AppSettingSerializer(serializers.ModelSerializer):
    """The app settings as the app reads and writes them.

    Every option is optional on the way in, so a client sends only what it
    changes; a blank one switches that option off. Whitespace around a value
    is trimmed. `updated_at` is stamped by the server."""

    android_app_url = UrlField()
    ios_app_url = UrlField()

    help_support_email = ContactField(
        validators=[EmailValidator(message='Enter a valid email address.')],
    )
    help_support_email_enabled = serializers.BooleanField(required=False)
    help_support_whatsapp = ContactField()
    help_support_whatsapp_enabled = serializers.BooleanField(required=False)
    help_support_telegram = ContactField()
    help_support_telegram_enabled = serializers.BooleanField(required=False)
    help_support_phone = ContactField()
    help_support_phone_enabled = serializers.BooleanField(required=False)

    class Meta:
        model = AppSetting
        fields = (
            'android_app_url', 'ios_app_url',
            'help_support_email', 'help_support_email_enabled',
            'help_support_whatsapp', 'help_support_whatsapp_enabled',
            'help_support_telegram', 'help_support_telegram_enabled',
            'help_support_phone', 'help_support_phone_enabled',
            'updated_at',
        )
        read_only_fields = ('updated_at',)
