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


class RecipeBookEntrySerializer(serializers.ModelSerializer):
    recipe_title = serializers.CharField(source="recipe.title", read_only=True)

    class Meta:
        model = RecipeBookEntry
        fields = ["id", "family", "recipe", "recipe_title", "status", "rating", "notes", "added_at"]
