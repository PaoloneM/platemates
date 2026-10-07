from django.contrib import admin

from .models import MealSlot, SlotDish, WeeklyMenu


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
    inlines = [MealSlotInline]


@admin.register(MealSlot)
class MealSlotAdmin(admin.ModelAdmin):
    list_display = ["menu", "date", "meal", "people", "outcome"]
    list_filter = ["menu__team", "outcome"]
    inlines = [SlotDishInline]
