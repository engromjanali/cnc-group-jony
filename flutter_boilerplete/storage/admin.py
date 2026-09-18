from django.contrib import admin

from .models import StoredFile


@admin.register(StoredFile)
class StoredFileAdmin(admin.ModelAdmin):
    list_display = ['original_name', 'owner', 'status', 'size', 'created_at']
    list_filter = ['status']
    search_fields = ['original_name', 'key', 'owner__email']
    readonly_fields = ['id', 'key', 'created_at', 'updated_at']
