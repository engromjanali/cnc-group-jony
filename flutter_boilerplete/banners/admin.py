from django.contrib import admin

from .limits import MAX_BANNERS
from .models import Banner


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'is_active', 'priority', 'start_at', 'end_at')
    list_filter = ('is_active',)
    search_fields = ('title',)

    def has_add_permission(self, request):
        # Keeps this screen to the same cap as the API.
        return Banner.objects.count() < MAX_BANNERS and super().has_add_permission(request)
