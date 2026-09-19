import logging
from datetime import timedelta

from django.utils import timezone

from . import config
from .models import StoredFile
from .registry import referenced_stored_file_ids
from .uploads import discard

logger = logging.getLogger(__name__)


def run_cleanup():
    """Safety net: reclaims stored files at least `CLEANUP_MAX_AGE_MINUTES`
    old that nothing points at any more (see registry.py for how consumers
    such as designs report what they still use).

    Designs already remove their own files when a save fails and when they are
    replaced or deleted, so this only catches what slipped through.

    Returns a summary dict for the caller to log/report.
    """
    cutoff = timezone.now() - timedelta(minutes=config.CLEANUP_MAX_AGE_MINUTES)
    orphaned = StoredFile.objects.filter(created_at__lt=cutoff).exclude(
        id__in=referenced_stored_file_ids(),
    )

    count = 0
    for stored_file in orphaned:
        discard(stored_file)
        count += 1
    return {'orphanedDeleted': count}
