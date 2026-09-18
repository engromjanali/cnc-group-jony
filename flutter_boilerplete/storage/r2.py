import boto3
from botocore.config import Config
from botocore.exceptions import ClientError
from django.conf import settings

UPLOAD_URL_TTL = 10 * 60
DOWNLOAD_URL_TTL = 5 * 60

# R2 rejects the trailing checksum headers newer botocore versions add by
# default, and a presigned URL signed with them fails when the client PUTs
# without them.
_CONFIG = Config(
    region_name='auto',
    signature_version='s3v4',
    request_checksum_calculation='when_required',
    response_checksum_validation='when_required',
)


def client():
    if not settings.R2_ACCOUNT_ID or not settings.R2_BUCKET:
        raise RuntimeError('R2 storage is not configured (see .env.example).')
    return boto3.client(
        's3',
        endpoint_url=f'https://{settings.R2_ACCOUNT_ID}.r2.cloudflarestorage.com',
        aws_access_key_id=settings.R2_ACCESS_KEY_ID,
        aws_secret_access_key=settings.R2_SECRET_ACCESS_KEY,
        config=_CONFIG,
    )


def presigned_put_url(key, content_type):
    """PUT URL signed with the content type the client must send verbatim."""
    return client().generate_presigned_url(
        'put_object',
        Params={
            'Bucket': settings.R2_BUCKET,
            'Key': key,
            'ContentType': content_type,
        },
        ExpiresIn=UPLOAD_URL_TTL,
    )


def presigned_get_url(key, download_name):
    return client().generate_presigned_url(
        'get_object',
        Params={
            'Bucket': settings.R2_BUCKET,
            'Key': key,
            'ResponseContentDisposition': f'attachment; filename="{download_name}"',
        },
        ExpiresIn=DOWNLOAD_URL_TTL,
    )


def head_object(key):
    """Returns the object's metadata, or None when it does not exist."""
    try:
        return client().head_object(Bucket=settings.R2_BUCKET, Key=key)
    except ClientError:
        return None


def delete_object(key):
    client().delete_object(Bucket=settings.R2_BUCKET, Key=key)
