from django.db import models
from django.db.models import Q
from django.utils import timezone

from designs.models import Category
from storage.models import StoredFile


class BannerQuerySet(models.QuerySet):
    def live(self):
        """Banners the home screen should show right now: switched on, inside
        their schedule (when they have one) and with a picture."""
        now = timezone.now()
        return (
            self.filter(is_active=True, image_file__isnull=False)
            .filter(Q(start_at__isnull=True) | Q(start_at__lte=now))
            .filter(Q(end_at__isnull=True) | Q(end_at__gt=now))
        )


class Banner(models.Model):
    class Status(models.TextChoices):
        LIVE = 'live', 'Live'
        INACTIVE = 'inactive', 'Inactive'
        SCHEDULED = 'scheduled', 'Scheduled'
        EXPIRED = 'expired', 'Expired'

    title = models.CharField(max_length=100)
    # Cloudinary picture. Always set through the API; nullable in the database
    # only because the file row is unlinked (not the banner deleted) if it is
    # ever reclaimed.
    image_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    # Text the admin gave the button over the banner, stored as typed. Blank is
    # allowed: the app then shows "Try Now" if the banner has a category, and no
    # button if it does not.
    cta_label = models.CharField(max_length=40, blank=True, default='Try Now')
    # Where tapping the banner leads. A deleted category leaves the banner in
    # place, just without a destination.
    category = models.ForeignKey(
        Category, related_name='banners', on_delete=models.SET_NULL, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    # Lower numbers come first; banners with no priority come last.
    priority = models.PositiveIntegerField(null=True, blank=True)
    # Optional schedule. Outside it the banner is kept but not shown.
    start_at = models.DateTimeField(null=True, blank=True)
    end_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = BannerQuerySet.as_manager()

    class Meta:
        ordering = [models.F('priority').asc(nulls_last=True), '-created_at']

    def __str__(self):
        return self.title

    @property
    def status(self):
        """Why the banner is or is not showing. Switched off wins over any
        schedule."""
        now = timezone.now()
        if not self.is_active:
            return self.Status.INACTIVE
        if self.start_at and self.start_at > now:
            return self.Status.SCHEDULED
        if self.end_at and self.end_at <= now:
            return self.Status.EXPIRED
        return self.Status.LIVE
