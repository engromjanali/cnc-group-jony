from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.crypto import constant_time_compare
from rest_framework import permissions, status
from rest_framework.exceptions import APIException, ValidationError
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from . import config
from .cleanup import run_cleanup
from .models import StoredFile
from .services import get_storage_service
from .validators import build_object_key, file_extension, sanitize_file_name


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


class GenerateUploadUrlView(StorageView):
    """POST /api/v1/storage/upload/presign

    Client requests a presigned PUT URL to upload a file directly to Cloudflare R2,
    completely bypassing the backend server and any payload limits.
    """

    def post(self, request):
        file_name = (request.data.get('file_name') or '').strip()
        if not file_name:
            raise ValidationError({'file_name': 'File name is required.'})

        clean_name = sanitize_file_name(file_name)
        extension = file_extension(clean_name)

        from app_settings.models import AppSetting
        allowed_extensions = AppSetting.get_current_allowed_file_extensions()
        if extension not in allowed_extensions:
            allowed = ', '.join(sorted(allowed_extensions))
            raise ValidationError(
                {'file_name': f'Unsupported file type: .{extension}. Allowed: {allowed}.'}
            )

        file_size = request.data.get('file_size')
        if file_size is None:
            raise ValidationError({'file_size': 'File size is required.'})
        try:
            file_size = int(file_size)
            if file_size <= 0:
                raise ValueError
        except (ValueError, TypeError):
            raise ValidationError({'file_size': 'File size must be a positive integer.'})

        if file_size > config.MAX_DIRECT_UPLOAD_BYTES:
            limit_mb = config.MAX_DIRECT_UPLOAD_BYTES / (1024 * 1024)
            raise ValidationError(
                {'file_size': f'File is {file_size / (1024 * 1024):.1f} MB; the limit is {limit_mb:g} MB.'}
            )

        content_type = (request.data.get('content_type') or '').strip().lower()
        if not content_type or content_type not in config.ALLOWED_FILE_CONTENT_TYPES:
            content_type = 'application/octet-stream'

        folder = request.data.get('folder')
        prefix = config.file_key_prefix(user_id=None, prefix=folder)
        storage_key = build_object_key(user_id=request.user.id, file_name=clean_name, prefix=prefix)

        stored_file = StoredFile.objects.create(
            owner=request.user,
            provider=StoredFile.Provider.R2,
            storage_key=storage_key,
            original_name=clean_name,
            content_type=content_type,
            size=file_size,
            status=StoredFile.Status.PENDING,
        )

        service = get_storage_service(StoredFile.Provider.R2)
        upload_url = service.presigned_upload_url(storage_key, content_type=content_type)

        return Response(
            {
                'file_id': str(stored_file.id),
                'upload_url': upload_url,
                'storage_key': storage_key,
                'content_type': content_type,
                'expires_in': config.UPLOAD_URL_TTL_SECONDS,
            },
            status=status.HTTP_201_CREATED,
        )


class CompleteUploadView(StorageView):
    """POST /api/v1/storage/upload/complete

    Client verifies that the direct R2 PUT upload succeeded. The backend calls
    R2 describe (head_object) to verify the object exists and records its actual size.
    """

    def post(self, request):
        file_id = request.data.get('file_id')
        if not file_id:
            raise ValidationError({'file_id': 'file_id is required.'})

        user = request.user
        stored_filter = {'id': file_id}
        if not user.is_staff:
            stored_filter['owner'] = user
        stored_file = get_object_or_404(StoredFile, **stored_filter)

        if stored_file.status == StoredFile.Status.READY:
            return Response({
                'file_id': str(stored_file.id),
                'storage_key': stored_file.storage_key,
                'original_name': stored_file.original_name,
                'content_type': stored_file.content_type,
                'size': stored_file.size,
                'status': stored_file.status,
            })

        service = get_storage_service(stored_file.provider)
        obj_meta = service.describe(stored_file.storage_key)
        if obj_meta is None:
            raise ValidationError(
                {'file_id': 'File does not exist in storage. Ensure upload completed before verifying.'}
            )

        stored_file.size = obj_meta.size
        stored_file.status = StoredFile.Status.READY
        stored_file.save(update_fields=['size', 'status', 'updated_at'])

        return Response({
            'file_id': str(stored_file.id),
            'storage_key': stored_file.storage_key,
            'original_name': stored_file.original_name,
            'content_type': stored_file.content_type,
            'size': stored_file.size,
            'status': stored_file.status,
        })
