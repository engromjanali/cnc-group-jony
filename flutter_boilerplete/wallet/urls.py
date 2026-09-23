from django.urls import path

from .views import (
    AdminPaymentMethodAddView,
    AdminPaymentMethodDeleteView,
    AdminPaymentMethodListView,
    AdminPaymentMethodUpdateView,
    PaymentMethodListView,
    AdminWalletApproveView,
    AdminWalletDenyView,
    AdminWalletListView,
    WalletAddView,
)

urlpatterns = [
    path('wallet/add', WalletAddView.as_view(), name='wallet-add'),
    path('admin/wallet/list', AdminWalletListView.as_view(), name='admin-wallet-list'),
    path('admin/wallet/approve/<int:pk>', AdminWalletApproveView.as_view(), name='admin-wallet-approve'),
    path('admin/wallet/deny/<int:pk>', AdminWalletDenyView.as_view(), name='admin-wallet-deny'),
    path('wallet/payment-methods', PaymentMethodListView.as_view(), name='wallet-payment-methods'),
    path(
        'admin/wallet/payment-method/list',
        AdminPaymentMethodListView.as_view(), name='admin-payment-method-list',
    ),
    path(
        'admin/wallet/payment-method/add',
        AdminPaymentMethodAddView.as_view(), name='admin-payment-method-add',
    ),
    path(
        'admin/wallet/payment-method/update/<int:pk>',
        AdminPaymentMethodUpdateView.as_view(), name='admin-payment-method-update',
    ),
    path(
        'admin/wallet/payment-method/delete/<int:pk>',
        AdminPaymentMethodDeleteView.as_view(), name='admin-payment-method-delete',
    ),
]
