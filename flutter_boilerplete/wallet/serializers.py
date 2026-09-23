from decimal import Decimal

from rest_framework import serializers

from designs.serializers import validate_image_upload
from storage.models import StoredFile
from storage.services import delivery_url
from storage.uploads import discard, store_upload

from .models import PaymentMethod, WalletTransaction


class WalletAddSerializer(serializers.ModelSerializer):
    transaction_id = serializers.CharField(max_length=64)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal('0.01'))
    sender_number = serializers.CharField(max_length=32)

    class Meta:
        model = WalletTransaction
        fields = ('id', 'transaction_id', 'sender_number', 'amount', 'status', 'created_at')
        read_only_fields = ('id', 'status', 'created_at')

    def validate_transaction_id(self, value):
        if WalletTransaction.objects.filter(transaction_id=value).exists():
            raise serializers.ValidationError('This transaction id was already submitted.')
        return value


class WalletTransactionSerializer(serializers.ModelSerializer):
    user_email = serializers.EmailField(source='user.email', read_only=True)

    class Meta:
        model = WalletTransaction
        fields = (
            'id', 'user', 'user_email', 'transaction_id', 'sender_number', 'amount',
            'status', 'created_at', 'reviewed_at',
        )


class PaymentMethodSerializer(serializers.ModelSerializer):
    """`icon` is a multipart image upload sent to Cloudinary; reads only see
    `icon_url`. A replaced icon is removed from storage once the new one saves."""

    icon = serializers.ImageField(write_only=True, required=False)
    icon_url = serializers.SerializerMethodField()
    # Explicit default: an absent checkbox on a multipart form reads as False.
    is_active = serializers.BooleanField(required=False, default=True)

    class Meta:
        model = PaymentMethod
        fields = ('id', 'name', 'number', 'icon', 'icon_url', 'is_active')

    def get_icon_url(self, obj):
        return delivery_url(obj.icon_file.storage_key) if obj.icon_file_id else None

    def validate_icon(self, icon):
        return validate_image_upload(icon)

    def create(self, validated_data):
        icon = validated_data.pop('icon', None)
        if icon is None:
            return super().create(validated_data)
        stored = self._store(icon)
        try:
            return super().create({**validated_data, 'icon_file': stored})
        except Exception:
            discard(stored)
            raise

    def update(self, instance, validated_data):
        icon = validated_data.pop('icon', None)
        if icon is None:
            return super().update(instance, validated_data)
        stored = self._store(icon)
        replaced = instance.icon_file
        try:
            instance = super().update(instance, {**validated_data, 'icon_file': stored})
        except Exception:
            discard(stored)
            raise
        if replaced is not None:
            discard(replaced)
        return instance

    def _store(self, icon):
        return store_upload(
            self.context['request'].user, StoredFile.Provider.CLOUDINARY, icon,
            file_name=icon.name, content_type=icon.content_type,
        )
