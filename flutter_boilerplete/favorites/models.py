from django.conf import settings
from django.db import models

from designs.models import Design


class Favorite(models.Model):
    """A design a user has saved. One row per (user, design)."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='favorites', on_delete=models.CASCADE,
    )
    design = models.ForeignKey(Design, related_name='favorites', on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('-created_at', '-id')
        constraints = [
            models.UniqueConstraint(fields=('user', 'design'), name='one_favorite_per_design'),
        ]

    def __str__(self):
        return f'{self.user_id} -> {self.design_id}'
