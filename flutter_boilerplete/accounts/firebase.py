"""Checking a Firebase sign-in - the one place tokens are verified.

Only Google sign-in goes through Firebase: the app signs the user in with
Firebase Authentication's Google provider and sends the resulting Firebase ID
token. Email + password does NOT - those accounts and their passwords live in
this backend (`/auth/register`, `/auth/login`).

The token is verified with the **Firebase Admin SDK** and a **service account**
(the standard way), never by decoding it and trusting what it says. Besides the
signature, expiry, audience and issuer, `check_revoked=True` asks Firebase
itself whether the token was revoked and whether that Firebase user has been
disabled - which a signature check alone cannot know.
"""
import base64
import binascii
import json
import logging
import threading

import firebase_admin
from django.conf import settings
from firebase_admin import auth, credentials
from firebase_admin import exceptions as firebase_exceptions

logger = logging.getLogger(__name__)

GOOGLE = 'google.com'

# Anything else Firebase can sign in with is refused - including its own
# email + password accounts, which this app does not use (an email + password
# user is created and signed in by this backend, not by Firebase).
ALLOWED_PROVIDERS = {GOOGLE}

# The private_key_id of the example key shipped in .env.example. It is well-formed
# but worthless - Google has never heard of it - so using it must be reported as
# "replace me", not attempted.
EXAMPLE_KEY_ID = 'a1b2c3d4e5f60718293a4b5c6d7e8f9012345678'

_APP_NAME = 'cnc-backend'
_app = None
_lock = threading.Lock()


class InvalidFirebaseToken(Exception):
    """The token is not a valid, verified Google sign-in for this project.
    Shown to the caller (a 400)."""


class FirebaseNotConfigured(Exception):
    """No usable service account is set up. A server problem, not the caller's:
    sign-in is refused (fail closed) and the reason is logged."""


class FirebaseUnavailable(Exception):
    """Firebase could not be reached to check the token. Also not the
    caller's fault - they can try again."""


def _service_account_info():
    """The service account, from `FIREBASE_SERVICE_ACCOUNT_JSON` or, as an
    alternative, `FIREBASE_SERVICE_ACCOUNT_FILE` (a path).

    The same `FIREBASE_SERVICE_ACCOUNT_JSON` value works locally (`.env`) and on
    the server (Vercel's dashboard), so nothing differs between them. It is
    either the key file's JSON or that JSON **base64-encoded**. Base64 is the
    safest: it has no quotes or `\n` sequences for a `.env` parser or a
    dashboard to mangle."""
    raw = (settings.FIREBASE_SERVICE_ACCOUNT_JSON or '').strip()
    path = (settings.FIREBASE_SERVICE_ACCOUNT_FILE or '').strip()

    if raw:
        if not raw.startswith('{'):
            try:
                raw = base64.b64decode(raw, validate=True).decode('utf-8')
            except (binascii.Error, ValueError) as error:
                raise FirebaseNotConfigured(
                    'FIREBASE_SERVICE_ACCOUNT_JSON is neither JSON nor base64 of JSON.',
                ) from error
        try:
            # strict=False: a `.env` in double quotes turns the key's `\n` into
            # real line breaks, which strict JSON refuses inside a string.
            return json.loads(raw, strict=False)
        except ValueError as error:
            raise FirebaseNotConfigured(
                'FIREBASE_SERVICE_ACCOUNT_JSON is not valid JSON - use the whole key '
                'file (or its base64), not a part of it.',
            ) from error
    if path:
        try:
            with open(path, encoding='utf-8') as key_file:
                return json.load(key_file)
        except (OSError, ValueError) as error:
            raise FirebaseNotConfigured(
                f'FIREBASE_SERVICE_ACCOUNT_FILE ({path}) cannot be read as a service '
                'account key.',
            ) from error
    raise FirebaseNotConfigured(
        'No Firebase service account: set FIREBASE_SERVICE_ACCOUNT_JSON (or '
        'FIREBASE_SERVICE_ACCOUNT_FILE). Google sign-in is disabled until then.',
    )


def _service_account_email():
    """For log messages only: which account needs the role."""
    try:
        return _service_account_info().get('client_email', 'the firebase-adminsdk account')
    except FirebaseNotConfigured:
        return 'the firebase-adminsdk account'


def _credential():
    """The SDK credential and the Firebase project it belongs to.

    The project is the key's own. If FIREBASE_PROJECT_ID is also set it must be
    the same one: a key from another project would verify tokens for the wrong
    project, or fail every one of them in a confusing way - so say so up front."""
    info = _service_account_info()
    if info.get('private_key_id') == EXAMPLE_KEY_ID:
        raise FirebaseNotConfigured(
            'FIREBASE_SERVICE_ACCOUNT_JSON still holds the EXAMPLE key from .env.example - '
            'replace it with the key you generated in the Firebase console.',
        )
    project = info.get('project_id')
    if not project:
        raise FirebaseNotConfigured('The service account key has no project_id.')
    expected = (settings.FIREBASE_PROJECT_ID or '').strip()
    if expected and expected != project:
        raise FirebaseNotConfigured(
            f'The service account is for project "{project}", but FIREBASE_PROJECT_ID '
            f'is "{expected}".',
        )
    try:
        return credentials.Certificate(info), project
    except ValueError as error:
        raise FirebaseNotConfigured(f'The service account key is not valid: {error}') from error


def _firebase_app():
    """The Admin SDK app, made on first use and then reused."""
    global _app
    with _lock:
        if _app is None:
            credential, project = _credential()
            _app = firebase_admin.initialize_app(
                credential, {'projectId': project}, name=_APP_NAME,
            )
        return _app


def verify_firebase_token(token):
    """Returns the token's claims, or raises:

    - `InvalidFirebaseToken` - forged, malformed, expired, revoked, for another
      project, the Firebase user disabled, no verified email, or not a Google
      sign-in;
    - `FirebaseNotConfigured` / `FirebaseUnavailable` - a server-side problem.
    """
    app = _firebase_app()  # may raise FirebaseNotConfigured

    try:
        claims = auth.verify_id_token(
            token, app=app, check_revoked=settings.FIREBASE_CHECK_REVOKED,
        )
    except (
        auth.InvalidIdTokenError,  # also expired and revoked
        auth.UserDisabledError,
        auth.UserNotFoundError,
        ValueError,  # not a JWT at all
    ) as error:
        raise InvalidFirebaseToken('Invalid or expired sign-in.') from error
    except firebase_exceptions.PermissionDeniedError as error:
        # The token was fine; the *service account* may not read Firebase users,
        # which the revoked / disabled check needs. A setup problem to fix once,
        # so say exactly how, without a stack trace on every attempt.
        logger.error(
            'Firebase refused the service account (%s) permission to look up users, so '
            'the sign-in cannot be checked for revocation. Fix: Google Cloud Console -> '
            'IAM & Admin -> IAM -> that service account -> add the role "Firebase '
            'Authentication Admin" (and make sure the "Identity Toolkit API" is enabled). '
            'Or, knowingly, set FIREBASE_CHECK_REVOKED=False.',
            _service_account_email(),
        )
        raise FirebaseNotConfigured(
            'The service account has no permission to look up Firebase users '
            '(role "Firebase Authentication Admin").',
        ) from error
    except (firebase_exceptions.FirebaseError, OSError) as error:
        logger.exception('Firebase could not verify a sign-in token')
        raise FirebaseUnavailable('Could not reach Firebase to check the sign-in.') from error

    if not claims.get('sub'):
        raise InvalidFirebaseToken('The sign-in has no user id.')
    if not claims.get('email'):
        raise InvalidFirebaseToken('The sign-in has no email address.')
    if not claims.get('email_verified'):
        raise InvalidFirebaseToken('Your email address is not verified yet.')
    if provider_of(claims) not in ALLOWED_PROVIDERS:
        raise InvalidFirebaseToken('This way of signing in is not supported.')
    return claims


def provider_of(claims):
    """How the user signed in to Firebase, e.g. `google.com`."""
    return (claims.get('firebase') or {}).get('sign_in_provider')
