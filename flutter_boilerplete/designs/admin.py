from django.contrib import admin

from .models import Category, Design, DesignPurchase, SubCategory


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ('id', 'label')
    search_fields = ('label',)


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


@admin.register(DesignPurchase)
class DesignPurchaseAdmin(admin.ModelAdmin):
    list_display = ('user', 'design_title', 'amount', 'created_at')
    search_fields = ('user__email', 'design_title')
    # A ledger: what was charged is not edited after the fact.
    readonly_fields = ('user', 'design', 'design_title', 'amount', 'created_at')
