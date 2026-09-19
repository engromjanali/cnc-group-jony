import re
import unicodedata
import uuid

from . import config

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
    return f'{config.file_key_prefix(user_id)}{uuid.uuid4()}-{sanitize_file_name(file_name)}'
