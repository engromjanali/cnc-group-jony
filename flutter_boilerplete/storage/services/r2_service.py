from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured

from .. import config
from ..validators import build_object_key
from .base import StorageService, StoredObject, UploadedObject

# R2 rejects the trailing checksum headers newer botocore versions add by
# default, so they are only sent when an operation requires them.
_BOTO_CONFIG = Config(
    region_name='auto',
    signature_version='s3v4',
    request_checksum_calculation='when_required',
    response_checksum_validation='when_required',
)


def _content_disposition(download_name):
    """RFC 6266 attachment header: an ASCII fallback plus the exact UTF-8 name,
    so quotes or non-Latin characters in the original name can't break it."""
    ascii_name = download_name.encode('ascii', 'ignore').decode().replace('"', '') or 'download'
    return f'attachment; filename="{ascii_name}"; filename*=UTF-8\'\'{quote(download_name)}'


class R2StorageService(StorageService):
    """Private files in an R2 bucket, reachable only through presigned URLs."""

    provider = 'r2'

    def __init__(self):
        if not (
            settings.R2_ACCOUNT_ID
            and settings.R2_ACCESS_KEY_ID
            and settings.R2_SECRET_ACCESS_KEY
            and settings.R2_BUCKET
        ):
            raise ImproperlyConfigured('R2 storage is not configured (see .env.example).')
        self._bucket = settings.R2_BUCKET
        self._client = boto3.client(
            's3',
            endpoint_url=f'https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
            aws_access_key_id=settings.R2_ACCESS_KEY_ID,
            aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
            config=_BOTO_CONFIG,
        )

    def store(self, file, *, owner_id, file_name, content_type, key_prefix=None, folder=None, **kwargs):
        prefix = key_prefix or folder or config.R2_DESIGN_FILE_PREFIX
        key = build_object_key(owner_id, file_name, prefix=prefix)
        # Read whole: uploads are capped at a few MB, and a known length keeps
        # R2 away from streaming/chunked signing it doesn't support.
        body = file.read()
        self._client.put_object(
            Bucket=self._bucket, Key=key, Body=body, ContentType=content_type,
        )
        return UploadedObject(storage_key=key, size=len(body), content_type=content_type)

    def describe(self, storage_key):
        try:
            head = self._client.head_object(Bucket=self._bucket, Key=storage_key)
        except ClientError:
            return None
        return StoredObject(
            size=head.get('ContentLength', 0),
            content_type=head.get('ContentType', ''),
        )

    def delete(self, storage_key):
        self._client.delete_object(Bucket=self._bucket, Key=storage_key)

    def url_for(self, storage_key, download_name=None):
        params = {'Bucket': self._bucket, 'Key': storage_key}
        if download_name:
            params['ResponseContentDisposition'] = _content_disposition(download_name)
        return self._client.generate_presigned_url(
            'get_object',
            Params=params,
            ExpiresIn=config.DOWNLOAD_URL_TTL_SECONDS,
        )
