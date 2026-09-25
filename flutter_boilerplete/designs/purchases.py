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


def is_owned(user, design):
    """Whether `user` may download `design` without paying now."""
    return price_of(design) == 0 or DesignPurchase.objects.filter(user=user, design=design).exists()


def charge_for_design(user, design):
    """Takes the design's price from the user's wallet, once.

    Returns `(charged, already_owned)`: `charged` is what was taken now (0 for a
    free design or one they already bought). Raises `InsufficientBalance` -
    changing nothing - when the wallet holds less than the price.

    Safe against a double tap or a retry: the purchase row is unique per (user,
    design), so however many requests race, exactly one creates it and takes the
    money; the balance is only lowered by a conditional UPDATE, so it can never go
    below zero even when two different purchases race."""
    price = price_of(design)
    if price == 0:
        return Decimal('0.00'), False

    with transaction.atomic():
        _, created = DesignPurchase.objects.get_or_create(
            user=user, design=design,
            defaults={'design_title': design.title, 'amount': price},
        )
        if not created:
            return Decimal('0.00'), True

        taken = User.objects.filter(pk=user.pk, wallet_balance__gte=price).update(
            wallet_balance=F('wallet_balance') - price,
        )
        if not taken:
            user.refresh_from_db(fields=['wallet_balance'])
            # Undo the purchase row created above.
            transaction.set_rollback(True)
            raise InsufficientBalance(user.wallet_balance, price)
    return price, False
