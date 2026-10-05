from django.contrib import admin

from .models import Cuisine, Recipe, RecipeIngredient


class RecipeIngredientInline(admin.TabularInline):
    model = RecipeIngredient
    autocomplete_fields = ["ingredient"]
    extra = 1


@admin.register(Recipe)
class RecipeAdmin(admin.ModelAdmin):
    list_display = ["title", "course", "cuisine", "servings", "prep_minutes", "cook_minutes"]
    list_filter = ["course", "cuisine"]
    search_fields = ["title", "description"]
    filter_horizontal = ["tools"]
    inlines = [RecipeIngredientInline]


@admin.register(Cuisine)
class CuisineAdmin(admin.ModelAdmin):
    search_fields = ["name"]
