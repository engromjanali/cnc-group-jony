"""Paying for a design with the wallet."""
from decimal import Decimal

from django.db import transaction
from django.db.models import F

from accounts.models import User

from .models import DesignPurchase


class InsufficientBalance(Exception):
    def __init__(self, balance, required):
        super().__init__('Not enough balance in the wallet.')
        self.balance = balance
        self.required = required


def price_of(design):
    """What the design costs: its amount when it is paid, otherwise nothing."""
    if design.is_paid and design.amount and design.amount > 0:
        return design.amount
    return Decimal('0.00')


def has_sufficient_balance(user, design):
    """Whether `user` has enough balance in their wallet to download `design`."""
    price = price_of(design)
    if price == 0:
        return True
    return user.wallet_balance >= price


def is_owned(user, design):
    """Backwards compatibility check: whether user has ever downloaded/purchased the design."""
    return price_of(design) == 0 or DesignPurchase.objects.filter(user=user, design=design).exists()


def charge_for_design(user, design):
    """Takes the design's price from the user's wallet upon successful download.

    Each call cuts the balance and records a purchase. Raises InsufficientBalance
    if user doesn't have enough balance."""
    price = price_of(design)
    if price == 0:
        return Decimal('0.00')

    with transaction.atomic():
        taken = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price,
        )
        if not taken:
            user.refresh_from_db(fields=['wallet_balance'])
            raise InsufficientBalance(user.wallet_balance, price)

        DesignPurchase.objects.create(
            user=user,
            design=design,
            design_title=design.title,
            amount=price,
        )
    return price

