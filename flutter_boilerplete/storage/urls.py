from django.urls import path

from .views import CleanupView, CompleteUploadView, GenerateUploadUrlView

urlpatterns = [
    path('storage/cleanup', CleanupView.as_view(), name='storage-cleanup'),
    path('storage/upload/presign', GenerateUploadUrlView.as_view(), name='storage-upload-presign'),
    path('storage/upload/complete', CompleteUploadView.as_view(), name='storage-upload-complete'),
]
