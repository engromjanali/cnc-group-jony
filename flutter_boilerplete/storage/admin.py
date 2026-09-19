from django.contrib import admin

from .models import StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'provider', 'owner', 'status', 'size', 'created_at']
    list_filter = ['provider', 'status']
    search_fields = ['original_name', 'storage_key', 'owner__email']
    readonly_fields = ['id', 'provider', 'storage_key', 'created_at', 'updated_at']
