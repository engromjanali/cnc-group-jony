from django.conf import settings
from django.db import models

from storage.models import StoredFile


class WalletTransaction(models.Model):
    """A top-up request. The user's balance only changes when an admin approves it."""

    class Status(models.TextChoices):
        PENDING = 'pending', 'Pending'
        APPROVED = 'approved', 'Approved'
        DENIED = 'denied', 'Denied'

    class Source(models.TextChoices):
        # A user's own top-up request, reviewed by an admin.
        USER = 'user', 'User request'
        # An admin credited the wallet directly (no user request behind it).
        ADMIN = 'admin', 'Admin credit'

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='wallet_transactions', on_delete=models.CASCADE,
    )
    # The payment reference the user got from their bank/mobile wallet. Unique so
    # the same payment can't be credited twice.
    # Blank for an admin credit, which has no real payment reference.
    transaction_id = models.CharField(max_length=64, unique=True, blank=True, null=True)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    # The number the money was sent from, so an admin can match it to the payment.
    sender_number = models.CharField(max_length=32, blank=True, default='')
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.PENDING)
    source = models.CharField(max_length=10, choices=Source.choices, default=Source.USER)
    # Who reviewed/credited it - the reviewing admin for a user request, the
    # crediting admin for an admin credit. Kept as a record only.
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, related_name='+', on_delete=models.SET_NULL, null=True, blank=True,
    )
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
