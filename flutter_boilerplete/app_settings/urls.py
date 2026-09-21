from django.urls import path

from .views import AdminAppSettingView, AppSettingView

urlpatterns = [
    path('app-setting', AppSettingView.as_view(), name='app-setting'),
    path('admin/app-setting', AdminAppSettingView.as_view(), name='admin-app-setting'),
]
