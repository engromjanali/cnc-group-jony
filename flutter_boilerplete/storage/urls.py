from django.urls import path

from .views import (
    CloudinarySignatureView,
    FileConfirmView,
    FileDeleteView,
    FileDownloadUrlView,
    FileUploadUrlView,
)

urlpatterns = [
    path(
        'uploads/image/signature',
        CloudinarySignatureView.as_view(),
        name='cloudinary-upload-signature',
    ),
    path('files/upload-url', FileUploadUrlView.as_view(), name='file-upload-url'),
    path('files/<uuid:pk>/confirm', FileConfirmView.as_view(), name='file-confirm'),
    path(
        'files/<uuid:pk>/download-url',
        FileDownloadUrlView.as_view(),
        name='file-download-url',
    ),
    path('files/<uuid:pk>', FileDeleteView.as_view(), name='file-delete'),
]
