from django.contrib import admin

from .models import AppSetting


@admin.register(AppSetting)
class AppSettingAdmin(admin.ModelAdmin):
    list_display = ('__str__', 'android_app_url', 'ios_app_url', 'updated_at')
    readonly_fields = ('updated_at', 'updated_by')

    def has_add_permission(self, request):
        # One document: once it exists it is edited, not added to.
        return not AppSetting.objects.exists() and super().has_add_permission(request)

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)
