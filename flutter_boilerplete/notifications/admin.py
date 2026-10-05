from django.contrib import admin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('id', 'title', 'sent_by', 'created_at')
    search_fields = ('title', 'body')
    readonly_fields = ('sent_by', 'created_at')
