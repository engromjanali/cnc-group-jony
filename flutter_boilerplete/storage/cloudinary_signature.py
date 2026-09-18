import time

import cloudinary.utils
from django.conf import settings


def build_upload_signature(user_id):
    """Signs a direct-to-Cloudinary upload. The API secret stays here; the app
    only ever receives the resulting signature."""
    if not settings.CLOUDINARY_CLOUD_NAME or not settings.CLOUDINARY_API_SECRET:
        raise RuntimeError('Cloudinary is not configured (see .env.example).')

    timestamp = int(time.time())
    folder = f'users/{user_id}'
    signature = cloudinary.utils.api_sign_request(
        {'timestamp': timestamp, 'folder': folder},
        settings.CLOUDINARY_API_SECRET,
    )
    return {
        'cloudName': settings.CLOUDINARY_CLOUD_NAME,
        'apiKey': settings.CLOUDINARY_API_KEY,
        'timestamp': timestamp,
        'folder': folder,
        'signature': signature,
    }
