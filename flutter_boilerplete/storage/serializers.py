from rest_framework import serializers

from .models import StoredFile
from .validators import validate_private_upload


class UploadUrlRequestSerializer(serializers.Serializer):
    """Body of POST /files/upload-url. The object key is never taken from here -
    only the original name, which is sanitized before it becomes part of a key."""

    fileName = serializers.CharField(max_length=255)
    contentType = serializers.CharField(max_length=128)
    size = serializers.IntegerField()

    def validate(self, attrs):
        validate_private_upload(attrs['fileName'], attrs['contentType'], attrs['size'])
        return attrs


class StoredFileSerializer(serializers.ModelSerializer):
    fileId = serializers.UUIDField(source='id', read_only=True)
    fileName = serializers.CharField(source='original_name', read_only=True)
    contentType = serializers.CharField(source='content_type', read_only=True)

    class Meta:
        model = StoredFile
        fields = ['fileId', 'fileName', 'contentType', 'size', 'status', 'created_at']
        read_only_fields = fields
