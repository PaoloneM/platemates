from rest_framework import serializers

from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin

from .models import Ingredient, KitchenTool


class IngredientSerializer(UserDecisionSerializerMixin, serializers.ModelSerializer):
    season_months = SeasonalityField(required=False)

    class Meta:
        model = Ingredient
        fields = [
            "id",
            "name",
            "aliases",
            "category",
            "default_unit",
            "season_months",
            "provenance",
        ]
        read_only_fields = ["provenance"]
        tracked_fields = ["category", "default_unit", "season_months"]


class KitchenToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenTool
        fields = ["id", "name", "heats_kitchen"]
