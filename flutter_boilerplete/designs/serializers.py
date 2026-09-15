from rest_framework import serializers

from .models import Category, Design, SubCategory


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
    """Used by the admin add/update endpoints.

    Accepts either an uploaded `image`/`design_file`, or a plain
    `image_url`/`design_file_url` string (e.g. for seeding from an existing
    asset). `image_url`/`design_file_url` in the response always reflect
    whichever one was actually stored.
    """

    sub_category_label = serializers.CharField(required=False, allow_blank=True, write_only=True)

    class Meta:
        model = Design
        fields = (
            'id', 'category', 'sub_category', 'sub_category_label', 'title',
            'image', 'image_url',
            'design_file', 'design_file_url', 'design_file_name',
            'description',
        )
        extra_kwargs = {
            'image': {'required': False, 'write_only': True},
            'design_file': {'required': False, 'write_only': True},
        }

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

        has_image = attrs.get('image') or attrs.get('image_url') or getattr(self.instance, 'image', None) or getattr(self.instance, 'image_url', None)
        if not has_image:
            raise serializers.ValidationError({'image': 'Provide either an image upload or an image_url.'})

        design_file = attrs.get('design_file')
        if design_file and not attrs.get('design_file_name'):
            attrs['design_file_name'] = design_file.name
        return attrs

    def to_representation(self, instance):
        data = super().to_representation(instance)
        request = self.context.get('request')
        if instance.image:
            url = instance.image.url
            data['image_url'] = request.build_absolute_uri(url) if request else url
        if instance.design_file:
            url = instance.design_file.url
            data['design_file_url'] = request.build_absolute_uri(url) if request else url
        return data


class DesignDetailSerializer(serializers.ModelSerializer):
    """Used by the public design details endpoint."""

    category_id = serializers.IntegerField(source='category.id', read_only=True)
    category_label = serializers.CharField(source='category.label', read_only=True)
    sub_category_label = serializers.CharField(source='sub_category.label', read_only=True, default=None)
    image_url = serializers.SerializerMethodField()
    design_file_url = serializers.SerializerMethodField()

    class Meta:
        model = Design
        fields = (
            'id', 'title', 'category_id', 'category_label', 'sub_category_label',
            'image_url', 'description', 'design_file_url', 'design_file_name', 'created_at',
        )

    def _absolute(self, url):
        request = self.context.get('request')
        return request.build_absolute_uri(url) if request else url

    def get_image_url(self, obj):
        return self._absolute(obj.image.url) if obj.image else (obj.image_url or None)

    def get_design_file_url(self, obj):
        return self._absolute(obj.design_file.url) if obj.design_file else (obj.design_file_url or None)
