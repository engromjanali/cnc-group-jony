"""Checking a Google sign-in.

The app signs the user in with Firebase Auth's Google provider and sends the
resulting Firebase ID token. It is only trusted after its signature, expiry,
audience (this Firebase project) and issuer have been checked against Google's
published keys - never by decoding it and reading the email out of it.
"""
from django.conf import settings
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

GOOGLE_PROVIDER = 'google.com'


class InvalidGoogleToken(Exception):
    """The token is not a valid, verified Google sign-in for this project."""


def verify_google_id_token(token):
    """Returns the token's claims, or raises InvalidGoogleToken.

    Requires a verified email and that the sign-in itself went through Google,
    so a Firebase account made another way (say, email + password with an
    address nobody confirmed) can't be used to take over an existing user."""
    try:
        claims = id_token.verify_firebase_token(
            token, google_requests.Request(), audience=settings.FIREBASE_PROJECT_ID,
        )
    except ValueError as error:
        raise InvalidGoogleToken('Invalid or expired Google sign-in.') from error

    if claims is None:
        raise InvalidGoogleToken('Invalid or expired Google sign-in.')
    if (claims.get('firebase') or {}).get('sign_in_provider') != GOOGLE_PROVIDER:
        raise InvalidGoogleToken('This sign-in did not come from Google.')
    if not claims.get('email') or not claims.get('email_verified'):
        raise InvalidGoogleToken('Your Google account has no verified email address.')
    return claims
