from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import constant_time_compare
from rest_framework import permissions, status
from rest_framework.exceptions import APIException
from rest_framework.response import Response
from rest_framework.views import APIView

from .cleanup import run_cleanup


class StorageUnavailable(APIException):
    status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    default_detail = 'File storage is not configured.'
    default_code = 'storage_unavailable'


class StorageErrorsMixin:
    """A provider that is missing its credentials surfaces as a 503 with a
    clear message instead of an opaque 500."""

    def handle_exception(self, exc):
        if isinstance(exc, ImproperlyConfigured):
            exc = StorageUnavailable()
        return super().handle_exception(exc)


class StorageView(StorageErrorsMixin, APIView):
    permission_classes = [permissions.IsAuthenticated]


class CleanupView(APIView):
    """GET /api/v1/storage/cleanup - reclaims stored files no design uses.

    Vercel Cron authenticates by sending `Authorization: Bearer <CRON_SECRET>`
    (https://vercel.com/docs/cron-jobs/manage-cron-jobs#securing-cron-jobs) -
    the same header JWTAuthentication reads, which would otherwise try to
    parse the secret as a JWT and reject it before this view ever runs. So
    this deliberately opts out of the project's default authentication and
    checks the header itself."""

    authentication_classes = []
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        expected = settings.CRON_SECRET
        provided = request.headers.get('Authorization', '')
        if not expected or not constant_time_compare(provided, f'Bearer {expected}'):
            return Response(status=status.HTTP_401_UNAUTHORIZED)

        return Response(run_cleanup())
