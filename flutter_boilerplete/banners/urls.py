from django.urls import path

from .views import (
    AdminBannerAddView,
    AdminBannerDeleteView,
    AdminBannerListView,
    AdminBannerUpdateView,
    BannerListView,
)

urlpatterns = [
    path('banner/list', BannerListView.as_view(), name='banner-list'),
    path('admin/banner/list', AdminBannerListView.as_view(), name='admin-banner-list'),
    path('admin/banner/add', AdminBannerAddView.as_view(), name='admin-banner-add'),
    path(
        'admin/banner/update/<int:pk>',
        AdminBannerUpdateView.as_view(),
        name='admin-banner-update',
    ),
    path(
        'admin/banner/delete/<int:pk>',
        AdminBannerDeleteView.as_view(),
        name='admin-banner-delete',
    ),
]
