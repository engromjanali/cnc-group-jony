from rest_framework import serializers

from storage import config as storage_config
from storage.models import StoredFile
from storage.services import delivery_url
from storage.uploads import discard, store_upload
from storage.validators import file_extension, sanitize_file_name

from .models import Category, Design, SubCategory


def design_image_url(design, request):
    """Where a design's preview can be displayed from, newest source first:
    a Cloudinary upload, then a legacy local file, then a legacy URL string."""
    if design.image_file_id:
        return delivery_url(design.image_file.storage_key)
    if design.image:
        url = design.image.url
        return request.build_absolute_uri(url) if request else url
    return design.image_url or None


def legacy_design_file_url(design, request):
    """A permanent URL for an older design's cutting file, or None.

    Files in R2 deliberately get None here: their only URLs are presigned and
    expire within minutes, so they must never sit in a payload the app might
    cache. Clients fetch one from /design/<id>/download-url at download time."""
    if design.design_stored_file_id:
        return None
    if design.design_file:
        url = design.design_file.url
        return request.build_absolute_uri(url) if request else url
    return design.design_file_url or None


def has_design_file(design):
    return bool(design.design_stored_file_id or design.design_file or design.design_file_url)


class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ('id', 'label')

    def validate_label(self, value):
        qs = Category.objects.filter(label__iexact=value)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('A category with this label already exists.')
        return value


class SubCategorySerializer(serializers.ModelSerializer):
    category_label = serializers.CharField(source='category.label', read_only=True)

    class Meta:
        model = SubCategory
        fields = ('id', 'category', 'category_label', 'label')

    def validate(self, attrs):
        category = attrs.get('category') or getattr(self.instance, 'category', None)
        label = attrs.get('label') or getattr(self.instance, 'label', None)
        qs = SubCategory.objects.filter(category=category, label__iexact=label)
        if self.instance:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise serializers.ValidationError('This sub category already exists for the selected category.')
        return attrs


class DesignWriteSerializer(serializers.ModelSerializer):
    """Used by the admin add/update endpoints: one multipart request carries
    the form fields and both files, and everything else happens here.

    `image` goes to Cloudinary and `design_file` to private R2. If any step of
    a save fails, whatever was already uploaded is removed again; when a file
    is replaced the old one is removed once the new state is saved. A plain
    `image_url` / `design_file_url` string is still accepted for seeding.
    """

    sub_category_label = serializers.CharField(required=False, allow_blank=True, write_only=True)
    image = serializers.ImageField(write_only=True, required=False)
    design_file = serializers.FileField(write_only=True, required=False)

    class Meta:
        model = Design
        fields = (
            'id', 'category', 'sub_category', 'sub_category_label', 'title',
            'image', 'image_url',
            'design_file', 'design_file_url', 'design_file_name',
            'description',
        )

    def validate_image(self, image):
        # Pillow has already opened it, so this is the file's real format
        # rather than whatever the client claimed.
        image_format = (getattr(getattr(image, 'image', None), 'format', '') or '').lower()
        if image_format not in storage_config.ALLOWED_IMAGE_FORMATS:
            raise serializers.ValidationError(
                f'Unsupported image format: {image_format or "unknown"}. Use JPG, PNG, WebP or GIF.',
            )
        return image

    def validate_design_file(self, design_file):
        extension = file_extension(sanitize_file_name(design_file.name))
        if extension not in storage_config.ALLOWED_FILE_EXTENSIONS:
            allowed = ', '.join(sorted(storage_config.ALLOWED_FILE_EXTENSIONS))
            raise serializers.ValidationError(f'Unsupported file type. Allowed: {allowed}.')
        return design_file

    def validate(self, attrs):
        category = attrs.get('category') or getattr(self.instance, 'category', None)
        sub_category = attrs.get('sub_category') if 'sub_category' in attrs else getattr(self.instance, 'sub_category', None)

        label = attrs.pop('sub_category_label', '').strip()
        if label and not sub_category:
            sub_category = SubCategory.objects.filter(category=category, label__iexact=label).first()
            if sub_category is None:
                sub_category = SubCategory.objects.create(category=category, label=label)
            attrs['sub_category'] = sub_category

        if sub_category and sub_category.category_id != category.id:
            raise serializers.ValidationError(
                {'sub_category': 'Sub category does not belong to the selected category.'}
            )

        has_image = (
            attrs.get('image') or attrs.get('image_url')
            or getattr(self.instance, 'image_file', None)
            or getattr(self.instance, 'image', None)
            or getattr(self.instance, 'image_url', None)
        )
        if not has_image:
            raise serializers.ValidationError({'image': 'Provide an image file or an image_url.'})

        uploads = [f for f in (attrs.get('image'), attrs.get('design_file')) if f]
        total = sum(f.size for f in uploads)
        if total > storage_config.MAX_DESIGN_UPLOAD_BYTES:
            limit_mb = storage_config.MAX_DESIGN_UPLOAD_BYTES / (1024 * 1024)
            raise serializers.ValidationError(
                f'The image and design file together are {total / (1024 * 1024):.1f} MB; '
                f'the limit is {limit_mb:g} MB.',
            )

        if attrs.get('design_file') and not attrs.get('design_file_name'):
            attrs['design_file_name'] = attrs['design_file'].name
        return attrs

    def create(self, validated_data):
        return self._save(None, validated_data)

    def update(self, instance, validated_data):
        return self._save(instance, validated_data)

    def _save(self, instance, validated_data):
        owner = self.context['request'].user
        image = validated_data.pop('image', None)
        design_file = validated_data.pop('design_file', None)

        uploaded = []  # removed again if the save fails
        replaced = []  # removed once the new state is saved
        try:
            if image is not None:
                stored = store_upload(
                    owner, StoredFile.Provider.CLOUDINARY, image,
                    file_name=image.name, content_type=image.content_type,
                )
                uploaded.append(stored)
                validated_data['image_file'] = stored
                if instance is not None and instance.image_file_id:
                    replaced.append(instance.image_file)

            if design_file is not None:
                content_type = design_file.content_type
                if content_type not in storage_config.ALLOWED_FILE_CONTENT_TYPES:
                    content_type = 'application/octet-stream'
                stored = store_upload(
                    owner, StoredFile.Provider.R2, design_file,
                    file_name=design_file.name, content_type=content_type,
                )
                uploaded.append(stored)
                validated_data['design_stored_file'] = stored
                if instance is not None and instance.design_stored_file_id:
                    replaced.append(instance.design_stored_file)

            if instance is None:
                design = super().create(validated_data)
            else:
                design = super().update(instance, validated_data)
        except Exception:
            for stored in uploaded:
                discard(stored)
            raise

        for stored in replaced:
            discard(stored)
        return design

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        data['image_url'] = design_image_url(instance, request)
        data['design_file_url'] = legacy_design_file_url(instance, request)
        data['has_design_file'] = has_design_file(instance)
        return data


class DesignDetailSerializer(serializers.ModelSerializer):
    """Used by the public design details endpoint."""

    category_id = serializers.IntegerField(source='category.id', read_only=True)
    category_label = serializers.CharField(source='category.label', read_only=True)
    sub_category_label = serializers.CharField(source='sub_category.label', read_only=True, default=None)
    image_url = serializers.SerializerMethodField()
    design_file_url = serializers.SerializerMethodField()
    has_design_file = serializers.SerializerMethodField()

    class Meta:
        model = Design
        fields = (
            'id', 'title', 'category_id', 'category_label', 'sub_category_label',
            'image_url', 'description', 'design_file_url', 'design_file_name',
            'has_design_file', 'created_at',
        )

    def get_image_url(self, obj):
        return design_image_url(obj, self.context.get('request'))

    def get_design_file_url(self, obj):
        return legacy_design_file_url(obj, self.context.get('request'))

    def get_has_design_file(self, obj):
        return has_design_file(obj)
