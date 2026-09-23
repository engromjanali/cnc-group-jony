from django.db import transaction
from rest_framework import permissions
from rest_framework.parsers import JSONParser
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import AppSetting
from .serializers import AppSettingSerializer

# What a client gets before any setting has been saved: the same fields, all
# blank, so it never has to handle a different shape.
NOT_SET_YET = {
    'android_app_url': '', 'ios_app_url': '',
    'help_support_email': '', 'help_support_email_enabled': True,
    'help_support_whatsapp': '', 'help_support_whatsapp_enabled': True,
    'help_support_telegram': '', 'help_support_telegram_enabled': True,
    'help_support_phone': '', 'help_support_phone_enabled': True,
    'updated_at': None,
}


class AppSettingView(APIView):
    """GET /api/v1/app-setting - the options the app reads, for anyone.

    Public, because the pages that use them (the web footer's store buttons)
    also show before sign-in. Authentication is skipped altogether rather than
    just not required: the app sends whatever token it still holds, and a stale
    one must not turn this read into a 401.

    Until an admin has saved any it is still a 200, with every option blank."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        setting = AppSetting.current()
        if setting is None:
            return Response(NOT_SET_YET)
        return Response(AppSettingSerializer(setting).data)


class AdminAppSettingView(APIView):
    """PATCH /api/v1/admin/app-setting - changes the options.

    JSON body with any of `android_app_url` and `ios_app_url`. Only the ones
    sent are changed, so a client that does not know a newer option leaves it
    as it is; a blank (or null) value switches an option off. Answers with the
    settings as they now are."""

    permission_classes = [permissions.IsAdminUser]
    parser_classes = [JSONParser]

    def patch(self, request):
        serializer = AppSettingSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        changes = serializer.validated_data

        # Nothing to change: leave the record - and when it was saved - alone.
        if not changes:
            return self._current()

        with transaction.atomic():
            setting, _ = AppSetting.objects.update_or_create(
                pk=AppSetting.SINGLETON_PK,
                defaults={**changes, 'updated_by': request.user},
            )
        return Response(AppSettingSerializer(setting).data)

    def _current(self):
        setting = AppSetting.current()
        return Response(NOT_SET_YET if setting is None else AppSettingSerializer(setting).data)
