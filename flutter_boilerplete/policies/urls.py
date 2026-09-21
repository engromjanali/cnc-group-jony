from django.urls import path

from .views import AdminPrivacyPolicyView, PrivacyPolicyView

urlpatterns = [
    path('privacy-policy', PrivacyPolicyView.as_view(), name='privacy-policy'),
    path(
        'admin/privacy-policy',
        AdminPrivacyPolicyView.as_view(),
        name='admin-privacy-policy',
    ),
]
