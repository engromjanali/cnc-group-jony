from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView

from .views import (
    AdminUserListView,
    AdminUserUpdateView,
    ForgotPasswordView,
    GoogleLoginView,
    LoginView,
    LogoutView,
    ProfileView,
    RegisterView,
    ResetPasswordView,
    SetPasswordView,
)

urlpatterns = [
    path('auth/register', RegisterView.as_view(), name='register'),
    path('auth/login', LoginView.as_view(), name='login'),
    path('auth/google', GoogleLoginView.as_view(), name='google-login'),
    path('auth/set-password', SetPasswordView.as_view(), name='set-password'),
    path('auth/forgot-password', ForgotPasswordView.as_view(), name='forgot-password'),
    path('auth/reset-password', ResetPasswordView.as_view(), name='reset-password'),
    path('auth/logout', LogoutView.as_view(), name='logout'),
    path('auth/refresh', TokenRefreshView.as_view(), name='token-refresh'),
    # The same view under the path the design doc names.
    path('auth/token/refresh', TokenRefreshView.as_view(), name='token-refresh-alias'),
    path('user/profile', ProfileView.as_view(), name='profile'),
    path('admin/users/list', AdminUserListView.as_view(), name='admin-user-list'),
    path('admin/users/update/<int:pk>', AdminUserUpdateView.as_view(), name='admin-user-update'),
]
