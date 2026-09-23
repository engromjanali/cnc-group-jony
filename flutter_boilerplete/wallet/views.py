from django.db import transaction
from django.db.models import F
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response
from rest_framework.views import APIView

from accounts.models import User

from storage.uploads import discard
from storage.views import StorageErrorsMixin

from .models import PaymentMethod, WalletTransaction
from .serializers import (
    PaymentMethodSerializer,
    WalletAddSerializer,
    WalletTransactionSerializer,
)


class WalletAddView(generics.CreateAPIView):
    """POST /api/v1/wallet/add - submit a top-up request: transaction_id + amount.
    It stays `pending` until an admin approves it."""

    serializer_class = WalletAddSerializer
    permission_classes = [permissions.IsAuthenticated]

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class AdminWalletListView(generics.ListAPIView):
    """GET /api/v1/admin/wallet/list - top-up requests, newest first.
    Optional `?status=pending|approved|denied`."""

    serializer_class = WalletTransactionSerializer
    permission_classes = [permissions.IsAdminUser]

    def get_queryset(self):
        queryset = WalletTransaction.objects.select_related('user')
        wanted = self.request.query_params.get('status')
        if wanted in WalletTransaction.Status.values:
            queryset = queryset.filter(status=wanted)
        return queryset


class _AdminWalletReviewView(APIView):
    permission_classes = [permissions.IsAdminUser]
    new_status = None

    def post(self, request, pk):
        with transaction.atomic():
            # Locked so two admins can't both review (and credit) the same request.
            tnx = get_object_or_404(WalletTransaction.objects.select_for_update(), pk=pk)
            if tnx.status != WalletTransaction.Status.PENDING:
                return Response(
                    {'detail': f'Already {tnx.status}.'}, status=status.HTTP_409_CONFLICT,
                )
            tnx.status = self.new_status
            tnx.reviewed_at = timezone.now()
            tnx.save(update_fields=['status', 'reviewed_at'])
            if self.new_status == WalletTransaction.Status.APPROVED:
                User.objects.filter(pk=tnx.user_id).update(
                    wallet_balance=F('wallet_balance') + tnx.amount,
                )
        tnx = WalletTransaction.objects.select_related('user').get(pk=pk)
        return Response(WalletTransactionSerializer(tnx).data)


class AdminWalletApproveView(_AdminWalletReviewView):
    """POST /api/v1/admin/wallet/approve/<id> - approve and credit the user's wallet."""

    new_status = WalletTransaction.Status.APPROVED


class AdminWalletDenyView(_AdminWalletReviewView):
    """POST /api/v1/admin/wallet/deny/<id> - deny; the balance is untouched."""

    new_status = WalletTransaction.Status.DENIED


class PaymentMethodListView(generics.ListAPIView):
    """GET /api/v1/wallet/payment-methods - where to send money: the active
    payment methods, for any signed-in user."""

    queryset = PaymentMethod.objects.filter(is_active=True).select_related('icon_file')
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = None


class AdminPaymentMethodListView(generics.ListAPIView):
    """GET /api/v1/admin/wallet/payment-method/list - all of them, including
    switched-off ones."""

    queryset = PaymentMethod.objects.select_related('icon_file')
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAdminUser]
    pagination_class = None


class AdminPaymentMethodAddView(StorageErrorsMixin, generics.CreateAPIView):
    """POST /api/v1/admin/wallet/payment-method/add - multipart: name, number,
    icon (image, optional), is_active (optional)."""

    queryset = PaymentMethod.objects.all()
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminPaymentMethodUpdateView(StorageErrorsMixin, generics.UpdateAPIView):
    """PUT/PATCH /api/v1/admin/wallet/payment-method/update/<id> - same fields,
    all optional on PATCH."""

    queryset = PaymentMethod.objects.select_related('icon_file')
    serializer_class = PaymentMethodSerializer
    permission_classes = [permissions.IsAdminUser]
    parser_classes = [MultiPartParser, FormParser, JSONParser]


class AdminPaymentMethodDeleteView(generics.DestroyAPIView):
    """DELETE /api/v1/admin/wallet/payment-method/delete/<id> - also removes
    its icon from Cloudinary."""

    queryset = PaymentMethod.objects.select_related('icon_file')
    permission_classes = [permissions.IsAdminUser]

    def perform_destroy(self, instance):
        icon = instance.icon_file
        super().perform_destroy(instance)
        if icon is not None:
            discard(icon)
