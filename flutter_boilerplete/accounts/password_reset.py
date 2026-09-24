"""The password reset code: making one, emailing it, and checking it.

The design, in short:
- A 6-digit code is emailed; only a keyed hash is stored.
- It lives 10 minutes, works once, and dies after 5 wrong guesses.
- A new request retires the old code. A user gets at most one code a minute
  and five an hour. These limits are stored in the database, so they hold even
  where the per-IP request throttle can't (each serverless instance has its own
  cache).
"""
import hmac
import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.db import transaction
from django.db.models import F
from django.utils import timezone
from django.utils.crypto import salted_hmac

from .models import PasswordResetCode

logger = logging.getLogger(__name__)

CODE_LENGTH = 6
CODE_LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_COOLDOWN = timedelta(seconds=60)
MAX_PER_HOUR = 5
APP_NAME = 'CNC Design'


def hash_code(code):
    return salted_hmac('accounts.password_reset', str(code), secret=settings.SECRET_KEY).hexdigest()


def _new_code():
    return f'{secrets.randbelow(10 ** CODE_LENGTH):0{CODE_LENGTH}d}'


def issue_code(user):
    """A fresh code for `user`, or None when they asked too recently / too often.

    Any earlier code that was never used is retired, so only the newest works."""
    now = timezone.now()
    recent = list(user.password_reset_codes.filter(created_at__gte=now - timedelta(hours=1)))
    if recent and now - recent[0].created_at < RESEND_COOLDOWN:
        return None
    if len(recent) >= MAX_PER_HOUR:
        return None

    code = _new_code()
    with transaction.atomic():
        user.password_reset_codes.filter(used_at__isnull=True).update(used_at=now)
        PasswordResetCode.objects.create(
            user=user, code_hash=hash_code(code), expires_at=now + CODE_LIFETIME,
        )
    return code


def send_code_email(user, code):
    """Emails the code. A failure is logged, never raised: the request that
    triggered it must answer the same either way (it can't reveal whether an
    account exists)."""
    minutes = int(CODE_LIFETIME.total_seconds() // 60)
    text = (
        f'Your {APP_NAME} password reset code is: {code}\n\n'
        f'It expires in {minutes} minutes and can be used once.\n\n'
        "If you didn't ask to reset your password, ignore this email - "
        'your password has not been changed.'
    )
    html = (
        f'<p>Your {APP_NAME} password reset code is:</p>'
        f'<p style="font-size:28px;font-weight:bold;letter-spacing:6px">{code}</p>'
        f'<p>It expires in {minutes} minutes and can be used once.</p>'
        "<p>If you didn't ask to reset your password, ignore this email - "
        'your password has not been changed.</p>'
    )
    try:
        send_mail(
            f'Your {APP_NAME} password reset code', text, None, [user.email],
            html_message=html,
        )
    except Exception:  # noqa: BLE001 - see the docstring
        logger.exception('Could not send the password reset email to user %s', user.pk)


def find_valid_code(user, code):
    """The user's live code row if `code` matches it, else None.

    A wrong guess counts against the live code; after MAX_ATTEMPTS it is dead.
    "No code", "expired", "used up" and "wrong" all look the same to the caller."""
    live = user.password_reset_codes.filter(
        used_at__isnull=True, expires_at__gt=timezone.now(), attempts__lt=MAX_ATTEMPTS,
    ).first()
    if live is None:
        return None
    if hmac.compare_digest(hash_code(code.strip()), live.code_hash):
        return live
    PasswordResetCode.objects.filter(pk=live.pk).update(attempts=F('attempts') + 1)
    return None
