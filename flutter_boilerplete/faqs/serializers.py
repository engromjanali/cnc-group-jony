from rest_framework import serializers

from .limits import MAX_ANSWER_LENGTH, MAX_QUESTION_LENGTH
from .models import Faq


class FaqSerializer(serializers.ModelSerializer):
    """Used by the FAQ lists and the admin add/edit endpoints.

    Whitespace around the question and answer is trimmed, and either one left
    blank is refused."""

    question = serializers.CharField(max_length=MAX_QUESTION_LENGTH)
    answer = serializers.CharField(max_length=MAX_ANSWER_LENGTH)
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = Faq
        fields = ('id', 'question', 'answer', 'order', 'is_active', 'updated_at')
        read_only_fields = ('updated_at',)
