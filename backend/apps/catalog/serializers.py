from django.db.models import Q
from rest_framework import serializers

from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin

from .models import Ingredient, KitchenTool, normalize_name


class IngredientSerializer(UserDecisionSerializerMixin, serializers.ModelSerializer):
    season_months = SeasonalityField(required=False)
    # Recipes using the ingredient (annotated by the view; 0 on create).
    usage_count = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Ingredient
        fields = [
            "id",
            "name",
            "aliases",
            "category",
            "default_unit",
            "season_months",
            "usage_count",
            "provenance",
        ]
        read_only_fields = ["provenance"]
        tracked_fields = ["category", "default_unit", "season_months"]

    def validate_name(self, name: str) -> str:
        name = normalize_name(name)
        clash = Ingredient.objects.filter(Q(name=name) | Q(aliases__contains=[name]))
        if self.instance is not None:
            clash = clash.exclude(pk=self.instance.pk)
        if clash.exists():
            raise serializers.ValidationError(
                "An ingredient with this name or alias already exists."
            )
        return name


class KitchenToolSerializer(serializers.ModelSerializer):
    class Meta:
        model = KitchenTool
        fields = ["id", "code", "name", "heats_kitchen"]
        read_only_fields = ["code"]

    def validate_name(self, name: str) -> str:
        name = " ".join(name.split())
        existing = KitchenTool.objects.filter(name__iexact=name)
        if self.instance is not None:
            existing = existing.exclude(pk=self.instance.pk)
        if existing.exists():
            raise serializers.ValidationError("A kitchen tool with this name already exists.")
        return name
