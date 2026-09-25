from django.contrib import admin

from storage.uploads import discard

from .models import Category, Design, DesignPurchase, SubCategory


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'label')
    search_fields = ('label',)

    def delete_model(self, request, obj):
        image = obj.image_file
        super().delete_model(request, obj)
        if image is not None:
            discard(image)

    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related('image_file'):
            self.delete_model(request, obj)


@admin.register(SubCategory)
class SubCategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'label', 'category')
    list_filter = ('category',)
    search_fields = ('label',)


@admin.register(Design)
class DesignAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'category', 'sub_category', 'design_type', 'is_paid', 'amount', 'created_at')
    list_filter = ('category', 'sub_category', 'design_type', 'is_paid')
    search_fields = ('title',)

    def delete_model(self, request, obj):
        stored_files = [
            f for f in (obj.image_file, obj.design_stored_file) if f is not None
        ]
        legacy_image = obj.image
        legacy_file = obj.design_file
        super().delete_model(request, obj)
        for stored_file in stored_files:
            discard(stored_file)
        if legacy_image:
            legacy_image.delete(save=False)
        if legacy_file:
            legacy_file.delete(save=False)

    def delete_queryset(self, request, queryset):
        for obj in queryset.select_related('image_file', 'design_stored_file'):
            self.delete_model(request, obj)


@admin.register(DesignPurchase)
class DesignPurchaseAdmin(admin.ModelAdmin):
    list_display = ('user', 'design_title', 'amount', 'created_at')
    search_fields = ('user__email', 'design_title')
    # A ledger: what was charged is not edited after the fact.
    readonly_fields = ('user', 'design', 'design_title', 'amount', 'created_at')
