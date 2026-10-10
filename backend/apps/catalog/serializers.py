from django.db.models import Q
from rest_framework import serializers

from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin
from apps.teams.models import Team

from .models import Ingredient, KitchenTool, normalize_name


class IngredientSerializer(UserDecisionSerializerMixin, serializers.ModelSerializer):
    season_months = SeasonalityField(required=False)
    # Recipes using the ingredient (annotated by the view; 0 on create), and how many of them
    # are shared: a team's ingredient other teams already meet.
    usage_count = serializers.IntegerField(read_only=True, default=0)
    shared_usage_count = serializers.IntegerField(read_only=True, default=0)
    # The team that added it for itself; null for a system ingredient. Set on creation only
    # (the system team, or none, makes a system ingredient: staff only).
    team = serializers.PrimaryKeyRelatedField(
        source="owner_team", queryset=Team.objects.all(), allow_null=True, required=False
    )
    team_name = serializers.CharField(source="owner_team.name", read_only=True, default=None)

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
            "shared_usage_count",
            "team",
            "team_name",
            "provenance",
        ]
        read_only_fields = ["provenance"]
        tracked_fields = ["category", "default_unit", "season_months"]
        # Names are checked in `validate`, against what the owner can use (system ingredients
        # too), not by the per-team constraint DRF would turn into a required `team`.
        validators = []

    def validate(self, attrs):
        if self.instance is not None:
            # Whose it is changes only by promotion (`promote`), never by an edit.
            attrs.pop("owner_team", None)
            owner = self.instance.owner_team
        else:
            owner = attrs.get("owner_team")
            if owner is not None and owner.is_system:
                attrs["owner_team"] = owner = None
        if "name" in attrs:
            # Unique among what the owner's recipes can use: a team cannot add a second
            # "pomodoro" next to the system one, nor two of its own.
            name = attrs["name"]
            clash = Ingredient.objects.usable_by(owner).filter(
                Q(name=name) | Q(aliases__contains=[name])
            )
            if self.instance is not None:
                clash = clash.exclude(pk=self.instance.pk)
            if clash.exists():
                raise serializers.ValidationError(
                    {"name": "An ingredient with this name or alias already exists."}
                )
        return attrs

    def validate_name(self, name: str) -> str:
        return normalize_name(name)


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
