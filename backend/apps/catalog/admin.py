from django.contrib import admin

from .models import Ingredient, KitchenTool


@admin.register(Ingredient)
class IngredientAdmin(admin.ModelAdmin):
    list_display = ["name", "category", "default_unit", "season_months"]
    list_filter = ["category"]
    search_fields = ["name", "aliases"]


@admin.register(KitchenTool)
class KitchenToolAdmin(admin.ModelAdmin):
    list_display = ["name", "heats_kitchen"]
