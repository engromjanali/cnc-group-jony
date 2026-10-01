from django.urls import path

from .views import (
    AdminFaqAddView,
    AdminFaqDeleteView,
    AdminFaqListView,
    AdminFaqUpdateView,
    FaqListView,
)

urlpatterns = [
    path('faq/list', FaqListView.as_view(), name='faq-list'),
    path('admin/faq/list', AdminFaqListView.as_view(), name='admin-faq-list'),
    path('admin/faq/add', AdminFaqAddView.as_view(), name='admin-faq-add'),
    path(
        'admin/faq/update/<int:pk>',
        AdminFaqUpdateView.as_view(),
        name='admin-faq-update',
    ),
    path(
        'admin/faq/delete/<int:pk>',
        AdminFaqDeleteView.as_view(),
        name='admin-faq-delete',
    ),
]
