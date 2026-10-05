from django.urls import path

from .views import AdminNotificationSendView, NotificationDetailView, NotificationListView

urlpatterns = [
    path('notification', NotificationListView.as_view(), name='notification-list'),
    path(
        'admin/notification/send',
        AdminNotificationSendView.as_view(),
        name='admin-notification-send',
    ),
    path(
        'notification/<int:pk>',
        NotificationDetailView.as_view(),
        name='notification-detail',
    ),
]
