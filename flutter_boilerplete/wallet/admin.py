from django.contrib import admin

from .models import PaymentMethod, WalletTransaction


@admin.register(WalletTransaction)
class WalletTransactionAdmin(admin.ModelAdmin):
    list_display = ('transaction_id', 'sender_number', 'user', 'amount', 'status', 'created_at')
    list_filter = ('status',)
    search_fields = ('transaction_id', 'user__email')
    # Status changes go through the approve/deny API so the balance stays in sync.
    readonly_fields = ('user', 'transaction_id', 'sender_number', 'amount', 'status', 'created_at', 'reviewed_at')


@admin.register(PaymentMethod)
class PaymentMethodAdmin(admin.ModelAdmin):
    list_display = ('name', 'number', 'is_active')
