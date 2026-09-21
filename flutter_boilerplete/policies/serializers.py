import html

from django.utils.html import strip_tags
from rest_framework import serializers

from .limits import MAX_CONTENT_LENGTH, MAX_TITLE_LENGTH
from .models import PrivacyPolicy


def visible_text(markup):
    """The text a reader would see in [markup]: tags removed, entities decoded,
    non-breaking spaces counted as the blanks they look like."""
    return html.unescape(strip_tags(markup)).replace('\xa0', ' ').strip()


class PrivacyPolicySerializer(serializers.ModelSerializer):
    """The policy as the app reads and writes it: a title and its HTML content,
    stamped by the server with when it was last saved.

    Whitespace around either is trimmed. Content that would show nothing - an
    empty editor writes `<p><br></p>` - is refused like a blank one."""

    title = serializers.CharField(max_length=MAX_TITLE_LENGTH)
    content = serializers.CharField(max_length=MAX_CONTENT_LENGTH)

    class Meta:
        model = PrivacyPolicy
        fields = ('title', 'content', 'updated_at')
        read_only_fields = ('updated_at',)

    def validate_content(self, value):
        if not visible_text(value):
            raise serializers.ValidationError('This field may not be blank.')
        return value
