from rest_framework import serializers

from .models import Family, FamilyMember, Preference, RecipeBookEntry


class FamilyMemberSerializer(serializers.ModelSerializer):
    class Meta:
        model = FamilyMember
        fields = ["id", "family", "name", "birth_year"]


class PreferenceSerializer(serializers.ModelSerializer):
    class Meta:
        model = Preference
        fields = ["id", "family", "member", "kind", "ingredient", "cuisine", "note"]


class FamilySerializer(serializers.ModelSerializer):
    members = FamilyMemberSerializer(many=True, read_only=True)
    preferences = PreferenceSerializer(many=True, read_only=True)

    class Meta:
        model = Family
        fields = [
            "id",
            "name",
            "tools",
            "default_people",
            "max_weekday_minutes",
            "notes",
            "members",
            "preferences",
        ]


class RecipeSummarySerializer(serializers.Serializer):
    """What the recipe book list shows of each recipe."""

    id = serializers.IntegerField()
    title = serializers.CharField()
    course = serializers.CharField()
    cuisine_name = serializers.CharField(source="cuisine.name", default=None)
    servings = serializers.IntegerField()
    total_minutes = serializers.IntegerField()
    season_months = serializers.ListField(child=serializers.IntegerField())
    # Both seasonality levels combined (ingredients and climate): what "in season" means.
    # Empty = suitable all year.
    suitable_months = serializers.SerializerMethodField()
    visibility = serializers.CharField()

    def get_suitable_months(self, recipe) -> list[int]:
        months = recipe.suitable_months()
        return [] if len(months) == 12 else sorted(months)


class RecipeBookEntrySerializer(serializers.ModelSerializer):
    recipe_summary = RecipeSummarySerializer(source="recipe", read_only=True)

    class Meta:
        model = RecipeBookEntry
        fields = [
            "id",
            "family",
            "recipe",
            "recipe_summary",
            "status",
            "rating",
            "notes",
            "added_at",
        ]
