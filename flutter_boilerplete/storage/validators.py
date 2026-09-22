import re
import unicodedata
import uuid

from rest_framework import serializers

from . import config

_UNSAFE_CHARS = re.compile(r'[^A-Za-z0-9._-]+')


def validate_image_upload(image):
    """Shared by every serializer that accepts an image file for Cloudinary."""
    # Pillow has already opened it, so this is the file's real format rather
    # than whatever the client claimed.
    image_format = (getattr(getattr(image, 'image', None), 'format', '') or '').lower()
    if image_format not in config.ALLOWED_IMAGE_FORMATS:
        raise serializers.ValidationError(
            f'Unsupported image format: {image_format or "unknown"}. Use JPG, PNG, WebP or GIF.',
        )
    if image.size > config.MAX_DESIGN_UPLOAD_BYTES:
        limit_mb = config.MAX_DESIGN_UPLOAD_BYTES / (1024 * 1024)
        raise serializers.ValidationError(
            f'The image is {image.size / (1024 * 1024):.1f} MB; the limit is {limit_mb:g} MB.',
        )
    return image


def sanitize_file_name(name):
    """Strip any path or unsafe character out of a client-supplied file name."""
    name = unicodedata.normalize('NFKD', name).encode('ascii', 'ignore').decode()
    name = name.replace('\\', '/').rsplit('/', 1)[-1]
    name = _UNSAFE_CHARS.sub('-', name).strip('.-')
    return name[:120] or 'file'


def file_extension(name):
    _, _, extension = name.rpartition('.')
    return extension.lower() if '.' in name else ''


def build_object_key(user_id, file_name):
    """users/{userId}/{uuid}-{sanitizedFileName} - always server generated."""
    return f'{config.file_key_prefix(user_id)}{uuid.uuid4()}-{sanitize_file_name(file_name)}'
