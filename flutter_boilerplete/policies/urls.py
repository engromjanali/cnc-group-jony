from django.urls import path

from .views import (
    AdminPrivacyPolicyView,
    AdminTermsAndConditionsView,
    PrivacyPolicyView,
    TermsAndConditionsView,
)

urlpatterns = [
    path('privacy-policy', PrivacyPolicyView.as_view(), name='privacy-policy'),
    path(
        'admin/privacy-policy',
        AdminPrivacyPolicyView.as_view(),
        name='admin-privacy-policy',
    ),
    path(
        'terms-and-conditions',
        TermsAndConditionsView.as_view(),
        name='terms-and-conditions',
    ),
    path(
        'admin/terms-and-conditions',
        AdminTermsAndConditionsView.as_view(),
        name='admin-terms-and-conditions',
    ),
]

