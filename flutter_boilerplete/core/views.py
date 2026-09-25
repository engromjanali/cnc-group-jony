from django.conf import settings
from rest_framework import permissions
from rest_framework.response import Response
from rest_framework.views import APIView

from app_settings.models import AppSetting


class ConfigView(APIView):
    """GET /api/v1/config - bootstrap payload the client fetches before login.

    Reads dynamic app settings saved by admin (maintenance mode, minimum version,
    recommended version, registration status, store urls, support email).
    """

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        setting = AppSetting.current()
        return Response({
            'app_name': 'Cnc Group Jony',
            'api_version': 'v1',
            'version': setting.app_version if setting and setting.app_version else '1.0.0',
            'min_supported_version': setting.min_supported_version if setting and setting.min_supported_version else '1.0.0',
            'maintenance_mode': setting.maintenance_mode if setting is not None else False,
            'features': {
                'registration_enabled': setting.registration_enabled if setting is not None else True,
                'social_login_enabled': setting.google_login_enabled if setting is not None else True,
                'google_login_enabled': setting.google_login_enabled if setting is not None else True,
            },
            'support_email': setting.help_support_email if setting and setting.help_support_email else 'support@example.com',
            'android_app_url': setting.android_app_url if setting else '',
            'ios_app_url': setting.ios_app_url if setting else '',
            'help_support_email': setting.help_support_email if setting else '',
            'help_support_email_enabled': setting.help_support_email_enabled if setting is not None else True,
            'help_support_whatsapp': setting.help_support_whatsapp if setting else '',
            'help_support_whatsapp_enabled': setting.help_support_whatsapp_enabled if setting is not None else True,
            'help_support_telegram': setting.help_support_telegram if setting else '',
            'help_support_telegram_enabled': setting.help_support_telegram_enabled if setting is not None else True,
            'help_support_phone': setting.help_support_phone if setting else '',
            'help_support_phone_enabled': setting.help_support_phone_enabled if setting is not None else True,
            'debug': settings.DEBUG,
        })
