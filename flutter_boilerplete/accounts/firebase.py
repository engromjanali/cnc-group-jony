"""Checking a Firebase sign-in - the one place tokens are verified.

Only Google sign-in goes through Firebase: the app signs the user in with
Firebase Authentication's Google provider and sends the resulting Firebase ID
token. Email + password does NOT - those accounts and their passwords live in
this backend (`/auth/register`, `/auth/login`). The token is only trusted after
its signature, expiry, audience (this Firebase project) and issuer have been
checked against Google's published keys - never by decoding it and reading the
email out of it.
"""
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE = 'google.com'

# Anything else Firebase can sign in with is refused - including its own
# email + password accounts, which this app does not use (an email + password
# user is created and signed in by this backend, not by Firebase).
ALLOWED_PROVIDERS = {GOOGLE}


class InvalidFirebaseToken(Exception):
    """The token is not a valid, verified Firebase sign-in for this project."""


def verify_firebase_token(token):
    """Returns the token's claims, or raises InvalidFirebaseToken.

    Requires a verified email - so someone can't claim an address they don't
    control - a Firebase user id, and a sign-in provider the app supports."""
    try:
        claims = id_token.verify_firebase_token(
            token, google_requests.Request(), audience=settings.FIREBASE_PROJECT_ID,
        )
    except ValueError as error:
        raise InvalidFirebaseToken('Invalid or expired sign-in.') from error

    if claims is None:
        raise InvalidFirebaseToken('Invalid or expired sign-in.')
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
