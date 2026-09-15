from django.contrib import admin

from .models import Category, Design, SubCategory


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
    list_display = ('id', 'title', 'category', 'sub_category', 'created_at')
    list_filter = ('category', 'sub_category')
    search_fields = ('title',)
