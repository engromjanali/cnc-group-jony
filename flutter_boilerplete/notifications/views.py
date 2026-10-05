from django.db import transaction
from rest_framework import generics, permissions
from rest_framework.exceptions import APIException
from rest_framework.parsers import JSONParser
from rest_framework.pagination import PageNumberPagination

from .models import Notification
from .push import PushUnavailable, send_to_all_users
from .serializers import NotificationSerializer


class NotificationUnavailable(APIException):
    """503: the push could not be sent (a server-side problem)."""

    status_code = 503
    default_detail = 'Notifications cannot be sent right now. Please try again later.'
    default_code = 'notification_unavailable'


class AdminNotificationSendView(generics.CreateAPIView):
    """POST /api/v1/admin/notification/send

    JSON body: `title` and `body` (both required). Saves the notification and
    pushes it to every user. If the push fails nothing is saved, so the admin
    can simply send it again."""

    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [JSONParser]

    def perform_create(self, serializer):
        try:
            with transaction.atomic():
                notification = serializer.save(sent_by=self.request.user)
                send_to_all_users(notification)
        except PushUnavailable as error:
            raise NotificationUnavailable() from error


class NotificationDetailView(generics.RetrieveAPIView):
    """GET /api/v1/notification/<id> - one notification, for the screen a
    tapped push opens."""

    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]


class NotificationPagination(PageNumberPagination):
    page_size = 20


class NotificationListView(generics.ListAPIView):
    queryset = Notification.objects.all()
    serializer_class = NotificationSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = NotificationPagination
