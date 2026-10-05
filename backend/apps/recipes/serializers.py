from django.db import transaction
from rest_framework import serializers

from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin

from .models import Cuisine, Recipe, RecipeIngredient


class CuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cuisine
        fields = ["id", "name"]


class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)

    class Meta:
        model = RecipeIngredient
        fields = [
            "id",
            "ingredient",
            "ingredient_name",
            "quantity",
            "unit",
            "optional",
            "note",
            "position",
        ]


class RecipeSerializer(UserDecisionSerializerMixin, serializers.ModelSerializer):
    season_months = SeasonalityField(required=False)
    climate_months = SeasonalityField(required=False)
    ingredients = RecipeIngredientSerializer(many=True, required=False)
    total_minutes = serializers.IntegerField(read_only=True)

    class Meta:
        model = Recipe
        fields = [
            "id",
            "title",
            "description",
            "instructions",
            "course",
            "cuisine",
            "servings",
            "prep_minutes",
            "cook_minutes",
            "total_minutes",
            "tools",
            "season_months",
            "climate_months",
            "source_url",
            "ingredients",
            "provenance",
        ]
        read_only_fields = ["provenance"]
        tracked_fields = ["course", "cuisine", "season_months", "climate_months", "tools"]

    @transaction.atomic
    def create(self, validated_data):
        lines = validated_data.pop("ingredients", [])
        recipe = super().create(validated_data)
        self._replace_lines(recipe, lines)
        return recipe

    @transaction.atomic
    def update(self, instance, validated_data):
        lines = validated_data.pop("ingredients", None)
        recipe = super().update(instance, validated_data)
        if lines is not None:
            self._replace_lines(recipe, lines)
        return recipe

    @staticmethod
    def _replace_lines(recipe: Recipe, lines: list[dict]) -> None:
        recipe.ingredients.all().delete()
        RecipeIngredient.objects.bulk_create(
            RecipeIngredient(recipe=recipe, **line) for line in lines
        )
