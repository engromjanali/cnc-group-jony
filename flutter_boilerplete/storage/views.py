from rest_framework import permissions, status
from rest_framework.generics import get_object_or_404
from rest_framework.response import Response
from rest_framework.views import APIView

from . import r2
from .cloudinary_signature import build_upload_signature
from .models import StoredFile
from .serializers import StoredFileSerializer, UploadUrlRequestSerializer
from .validators import MAX_FILE_BYTES, build_object_key


class CloudinarySignatureView(APIView):
    """POST /api/v1/uploads/image/signature

    Public preview images go straight from the app to Cloudinary; this only
    hands out a short-lived signature, never the API secret."""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        return Response(build_upload_signature(request.user.id))


class OwnedFileMixin:
    """Every private-file route resolves the file through the caller's own
    rows, so another user's id simply 404s."""

    permission_classes = [permissions.IsAuthenticated]

    def get_file(self, request, pk):
        return get_object_or_404(StoredFile, pk=pk, owner=request.user)


class FileUploadUrlView(APIView):
    """POST /api/v1/files/upload-url"""

    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        serializer = UploadUrlRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        key = build_object_key(request.user.id, data['fileName'])
        stored_file = StoredFile.objects.create(
            owner=request.user,
            key=key,
            original_name=data['fileName'][:255],
            content_type=data['contentType'],
            size=data['size'],
        )

        return Response(
            {
                'fileId': str(stored_file.id),
                'uploadUrl': r2.presigned_put_url(key, data['contentType']),
                'expiresIn': r2.UPLOAD_URL_TTL,
            },
            status=status.HTTP_201_CREATED,
        )


class FileConfirmView(OwnedFileMixin, APIView):
    """POST /api/v1/files/<id>/confirm - promotes a pending row to ready once
    the object is really in the bucket and within the size limit."""

    def post(self, request, pk):
        stored_file = self.get_file(request, pk)
        head = r2.head_object(stored_file.key)

        if head is None:
            stored_file.delete()
            return Response(
                {'detail': 'Upload was not found in storage.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        uploaded_size = head.get('ContentLength', 0)
        if uploaded_size > MAX_FILE_BYTES:
            r2.delete_object(stored_file.key)
            stored_file.delete()
            return Response(
                {'detail': f'Uploaded file exceeds the {MAX_FILE_BYTES} byte limit.'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        stored_file.size = uploaded_size
        stored_file.status = StoredFile.Status.READY
        stored_file.save(update_fields=['size', 'status', 'updated_at'])
        return Response(StoredFileSerializer(stored_file).data)


class FileDownloadUrlView(OwnedFileMixin, APIView):
    """GET /api/v1/files/<id>/download-url"""

    def get(self, request, pk):
        stored_file = self.get_file(request, pk)
        if stored_file.status != StoredFile.Status.READY:
            return Response(
                {'detail': 'File upload has not been confirmed yet.'},
                status=status.HTTP_409_CONFLICT,
            )

        return Response(
            {
                'downloadUrl': r2.presigned_get_url(
                    stored_file.key, stored_file.original_name,
                ),
                'fileName': stored_file.original_name,
                'expiresIn': r2.DOWNLOAD_URL_TTL,
            },
        )


class FileDeleteView(OwnedFileMixin, APIView):
    """DELETE /api/v1/files/<id>"""

    def delete(self, request, pk):
        stored_file = self.get_file(request, pk)
        r2.delete_object(stored_file.key)
        stored_file.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
