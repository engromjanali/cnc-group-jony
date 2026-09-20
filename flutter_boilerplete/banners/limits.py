"""The cap on how many promotional banners can exist, and the machinery that
keeps it true when two admins add one at the same moment."""
from django.db import connection
from rest_framework import status
from rest_framework.exceptions import APIException

# Counts every banner, active or not: hiding a banner does not free its slot.
MAX_BANNERS = 10

# Arbitrary, but must stay the same everywhere: it names the advisory lock.
_ADVISORY_LOCK_KEY = 7301001


class BannerLimitReached(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_code = 'banner_limit_reached'
    default_detail = (
        f'You can have at most {MAX_BANNERS} banners. Delete one to add another.'
    )


def lock_banner_slots():
    """Makes concurrent adds take turns, so two requests cannot both see one
    free slot and both fill it. Call inside a transaction: the lock is released
    when it ends. Only Postgres needs this - SQLite already allows a single
    writer at a time."""
    if connection.vendor == 'postgresql':
        with connection.cursor() as cursor:
            cursor.execute('SELECT pg_advisory_xact_lock(%s)', [_ADVISORY_LOCK_KEY])


def ensure_room(banner_model):
    if banner_model.objects.count() >= MAX_BANNERS:
        raise BannerLimitReached()
