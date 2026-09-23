from django.conf import settings
from django.db import models

from storage.models import StoredFile


class WalletTransaction(models.Model):
    """A top-up request. The user's balance only changes when an admin approves it."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DENIED = 'denied', 'Denied'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='wallet_transactions', on_delete=models.CASCADE,
    )
    # The payment reference the user got from their bank/mobile wallet. Unique so
    # the same payment can't be credited twice.
    transaction_id = models.CharField(max_length=64, unique=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # The number the money was sent from, so an admin can match it to the payment.
    sender_number = models.CharField(max_length=32, blank=True, default='')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    created_at = models.DateTimeField(auto_now_add=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ('-created_at',)

    def __str__(self):
        return f'{self.transaction_id} ({self.status})'


class PaymentMethod(models.Model):
    """A mobile financial service (bKash, Nagad...) the user can send money to.
    Admin-managed; users only read the active ones."""

    name = models.CharField(max_length=50)
    number = models.CharField(max_length=32)
    # Cloudinary logo, uploaded by this backend. Optional.
    icon_file = models.ForeignKey(
        StoredFile, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ('id',)

    def __str__(self):
        return f'{self.name} {self.number}'
