from django.contrib import admin

from .models import ConfigVar


@admin.register(ConfigVar)
class ConfigVarAdmin(admin.ModelAdmin):
    list_display = ["key", "value", "updated_at", "updated_by"]
    readonly_fields = ["updated_at", "updated_by"]
