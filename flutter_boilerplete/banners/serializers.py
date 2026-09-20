from django.db import transaction
from rest_framework import serializers

from designs.serializers import validate_image_upload
from storage.models import StoredFile
from storage.services import delivery_url
from storage.uploads import discard, store_upload

from .limits import ensure_room, lock_banner_slots
from .models import Banner


class BannerSerializer(serializers.ModelSerializer):
    """Used by the banner lists and the admin add/edit endpoints.

    `image` is uploaded by this backend to Cloudinary. It is required when a
    banner is created; on edit it is optional, and a replaced image is removed
    from storage once the new one is saved. Adding past the cap is refused
    with a 409 before anything is uploaded."""

    image = serializers.ImageField(write_only=True, required=False)
    image_url = serializers.SerializerMethodField()
    category_label = serializers.CharField(source='category.label', read_only=True, default=None)
    # Explicit default: on a multipart form an absent checkbox reads as False,
    # which would silently create every banner switched off.
    is_active = serializers.BooleanField(required=False, default=True)
    status = serializers.CharField(read_only=True)

    class Meta:
        model = Banner
        fields = (
            'id', 'title', 'image', 'image_url', 'cta_label',
            'category', 'category_label', 'is_active', 'priority',
            'start_at', 'end_at', 'status',
        )

    def get_image_url(self, obj):
        return delivery_url(obj.image_file.storage_key) if obj.image_file_id else None

    def validate_image(self, image):
        return validate_image_upload(image)

    def validate(self, attrs):
        if self.instance is None:
            if not attrs.get('image'):
                raise serializers.ValidationError({'image': 'An image is required for a new banner.'})
            # Fail early, before the upload. The check that actually guarantees
            # the cap runs again under a lock in create().
            ensure_room(Banner)

        start = attrs['start_at'] if 'start_at' in attrs else getattr(self.instance, 'start_at', None)
        end = attrs['end_at'] if 'end_at' in attrs else getattr(self.instance, 'end_at', None)
        if start and end and end <= start:
            raise serializers.ValidationError({'end_at': 'The end must be after the start.'})
        return attrs

    def create(self, validated_data):
        image = validated_data.pop('image')
        stored = self._store(image)
        try:
            with transaction.atomic():
                lock_banner_slots()
                ensure_room(Banner)
                return super().create({**validated_data, 'image_file': stored})
        except Exception:
            discard(stored)
            raise

    def update(self, instance, validated_data):
        image = validated_data.pop('image', None)
        if image is None:
            return super().update(instance, validated_data)

        stored = self._store(image)
        replaced = instance.image_file
        try:
            banner = super().update(instance, {**validated_data, 'image_file': stored})
        except Exception:
            discard(stored)
            raise

        if replaced is not None:
            discard(replaced)
        return banner

    def _store(self, image):
        return store_upload(
            self.context['request'].user, StoredFile.Provider.CLOUDINARY, image,
            file_name=image.name, content_type=image.content_type,
        )
