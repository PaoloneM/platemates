from django.contrib import admin

from .models import MealSlot, SlotDish, SystemRule, TeamRule, WeeklyMenu


class MealSlotInline(admin.TabularInline):
    model = MealSlot
    fields = ["date", "meal", "people", "outcome", "rating"]
    extra = 0


class SlotDishInline(admin.TabularInline):
    model = SlotDish
    autocomplete_fields = ["recipe"]
    extra = 0


@admin.register(WeeklyMenu)
class WeeklyMenuAdmin(admin.ModelAdmin):
    list_display = ["team", "week_start", "status"]
    list_filter = ["team", "status"]
    filter_horizontal = ["excluded_rules"]
    inlines = [MealSlotInline]


@admin.register(MealSlot)
class MealSlotAdmin(admin.ModelAdmin):
    list_display = ["menu", "date", "meal", "people", "outcome"]
    list_filter = ["menu__team", "outcome"]
    inlines = [SlotDishInline]


@admin.register(TeamRule)
class TeamRuleAdmin(admin.ModelAdmin):
    list_display = ["team", "text"]
    list_filter = ["team"]


@admin.register(SystemRule)
class SystemRuleAdmin(admin.ModelAdmin):
    list_display = ["text_en", "code", "position", "active"]
    list_editable = ["position", "active"]
