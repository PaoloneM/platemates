from django.db import transaction
from rest_framework import serializers

from apps.core.provenance import Source
from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin
from apps.families.models import Family, Membership, RecipeBookEntry

from .models import Cuisine, Recipe, RecipeIngredient


class CuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cuisine
        fields = ["id", "name"]


class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)
    ingredient_category = serializers.CharField(source="ingredient.category", read_only=True)
    # Lets the editor preview the derived recipe season while ingredients change.
    ingredient_season_months = serializers.ListField(
        source="ingredient.season_months", child=serializers.IntegerField(), read_only=True
    )

    class Meta:
        model = RecipeIngredient
        fields = [
            "id",
            "ingredient",
            "ingredient_name",
            "ingredient_category",
            "ingredient_season_months",
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
    # Blank steps (an empty row left in the editor) are accepted and dropped in validate_steps.
    steps = serializers.ListField(
        child=serializers.CharField(allow_blank=True, trim_whitespace=False), required=False
    )
    total_minutes = serializers.IntegerField(read_only=True)
    cuisine_name = serializers.CharField(source="cuisine.name", read_only=True, default=None)
    # On create: the family that owns the recipe and gets it in its recipe book.
    family = serializers.PrimaryKeyRelatedField(
        queryset=Family.objects.all(), write_only=True, required=False
    )
    can_edit = serializers.SerializerMethodField()
    # How the requesting user's families relate to the recipe.
    book_entries = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = [
            "id",
            "title",
            "description",
            "steps",
            "course",
            "cuisine",
            "cuisine_name",
            "servings",
            "prep_minutes",
            "cook_minutes",
            "total_minutes",
            "tools",
            "season_months",
            "climate_months",
            "source_url",
            "visibility",
            "owner_family",
            "family",
            "can_edit",
            "book_entries",
            "ingredients",
            "provenance",
        ]
        read_only_fields = ["provenance", "owner_family"]
        tracked_fields = ["course", "cuisine", "season_months", "climate_months", "tools"]

    def _user(self):
        return self.context["request"].user

    def get_can_edit(self, recipe) -> bool:
        user = self._user()
        return (
            user.is_staff
            or Membership.objects.filter(user=user, family_id=recipe.owner_family_id).exists()
        )

    def get_book_entries(self, recipe) -> list[dict]:
        entries = RecipeBookEntry.objects.filter(
            recipe=recipe, family__memberships__user=self._user()
        )
        return [
            {"id": e.id, "family": e.family_id, "status": e.status, "rating": e.rating}
            for e in entries
        ]

    def validate_steps(self, steps):
        return [step.strip() for step in steps if step and step.strip()]

    def validate_family(self, family):
        if not Membership.objects.filter(user=self._user(), family=family).exists():
            raise serializers.ValidationError("Not one of your families.")
        return family

    def validate(self, attrs):
        if self.instance is None and "family" not in attrs:
            raise serializers.ValidationError({"family": "Required when creating a recipe."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        family = validated_data.pop("family")
        lines = validated_data.pop("ingredients", [])
        validated_data["owner_family"] = family
        recipe = super().create(validated_data)
        self._replace_lines(recipe, lines)
        self._derive(recipe)
        RecipeBookEntry.objects.create(
            family=family, recipe=recipe, status=RecipeBookEntry.Status.APPROVED
        )
        return recipe

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("family", None)
        lines = validated_data.pop("ingredients", None)
        recipe = super().update(instance, validated_data)
        if lines is not None:
            self._replace_lines(recipe, lines)
        self._derive(recipe)
        return recipe

    @staticmethod
    def _derive(recipe: Recipe) -> None:
        """Recompute derived properties the user has not taken over."""
        if recipe.propose("season_months", recipe.derive_season_months(), Source.DERIVED):
            recipe.save(update_fields=["season_months", "provenance"])

    @staticmethod
    def _replace_lines(recipe: Recipe, lines: list[dict]) -> None:
        recipe.ingredients.all().delete()
        RecipeIngredient.objects.bulk_create(
            RecipeIngredient(recipe=recipe, **{**line, "position": index})
            for index, line in enumerate(lines)
        )
