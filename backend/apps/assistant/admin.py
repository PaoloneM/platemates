from django.contrib import admin

from .models import AssistantSession


@admin.register(AssistantSession)
class AssistantSessionAdmin(admin.ModelAdmin):
    list_display = ["user", "family", "mode", "status", "updated_at"]
    list_filter = ["mode", "status"]
