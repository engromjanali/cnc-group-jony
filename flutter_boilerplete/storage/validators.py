import re
import unicodedata
import uuid

from rest_framework import serializers

# Private design files. `application/octet-stream` is included because CNC
# toolpath files (.dxf/.dwg/.nc) are commonly sent with no specific type, so the
# extension allowlist below is what actually constrains those uploads.
ALLOWED_FILE_CONTENT_TYPES = frozenset({
    'application/pdf',
    'application/zip',
    'application/x-zip-compressed',
    'image/svg+xml',
    'image/vnd.dxf',
    'application/dxf',
    'application/x-dxf',
    'image/vnd.dwg',
    'application/acad',
    'application/octet-stream',
})

ALLOWED_FILE_EXTENSIONS = frozenset({
    'pdf', 'zip', 'svg', 'dxf', 'dwg', 'nc', 'tap', 'gcode', 'cnc', 'plt', 'ai', 'eps',
})

# Public preview images uploaded straight to Cloudinary.
ALLOWED_IMAGE_CONTENT_TYPES = frozenset({
    'image/jpeg', 'image/png', 'image/webp', 'image/gif',
})

MAX_FILE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 10 * 1024 * 1024

_UNSAFE_CHARS = re.compile(r'[^A-Za-z0-9._-]+')


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
    return f'users/{user_id}/{uuid.uuid4()}-{sanitize_file_name(file_name)}'


def validate_private_upload(file_name, content_type, size):
    if content_type not in ALLOWED_FILE_CONTENT_TYPES:
        raise serializers.ValidationError(
            {'contentType': [f'Unsupported content type: {content_type}.']},
        )
    if file_extension(sanitize_file_name(file_name)) not in ALLOWED_FILE_EXTENSIONS:
        raise serializers.ValidationError(
            {'fileName': ['Unsupported file extension.']},
        )
    if size <= 0 or size > MAX_FILE_BYTES:
        raise serializers.ValidationError(
            {'size': [f'File size must be between 1 and {MAX_FILE_BYTES} bytes.']},
        )
