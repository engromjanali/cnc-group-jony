from django.urls import path

from .views import CleanupView

urlpatterns = [
    path('storage/cleanup', CleanupView.as_view(), name='storage-cleanup'),
]
