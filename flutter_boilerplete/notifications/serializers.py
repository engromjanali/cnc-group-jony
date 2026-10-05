from rest_framework import serializers

from .limits import MAX_BODY_LENGTH, MAX_TITLE_LENGTH
from .models import Notification


class NotificationSerializer(serializers.ModelSerializer):
    """Used to send a notification and to read one back.

    Whitespace around the title and body is trimmed, and either one left blank
    is refused."""

    title = serializers.CharField(max_length=MAX_TITLE_LENGTH)
    body = serializers.CharField(max_length=MAX_BODY_LENGTH)

    class Meta:
        model = Notification
        fields = ('id', 'title', 'body', 'created_at')
        read_only_fields = ('created_at',)
