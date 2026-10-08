from django.db import transaction
from rest_framework import serializers

from apps.recipes.models import Recipe
from apps.teams.models import PLANNED_MEALS, Team

from .models import MealSlot, MenuGeneration, SlotDish, SystemRule, TeamRule, WeeklyMenu

MAX_INSTRUCTIONS = 2000


class MealSlotSerializer(serializers.ModelSerializer):
    # Ordered list of recipe ids; written as a whole.
    dishes = serializers.PrimaryKeyRelatedField(
        many=True, queryset=Recipe.objects.all(), required=False
    )

    class Meta:
        model = MealSlot
        fields = [
            "id",
            "menu",
            "date",
            "meal",
            "people",
            "dishes",
            "outcome",
            "eaten_instead",
            "eaten_instead_note",
            "rating",
            "comment",
        ]
        read_only_fields = ["menu", "date", "meal"]

    def to_representation(self, instance):
        data = super().to_representation(instance)
        data["dishes"] = [d.recipe_id for d in instance.slot_dishes.all()]
        return data

    @transaction.atomic
    def update(self, instance, validated_data):
        dishes = validated_data.pop("dishes", None)
        slot = super().update(instance, validated_data)
        if dishes is not None:
            slot.slot_dishes.all().delete()
            SlotDish.objects.bulk_create(
                SlotDish(slot=slot, recipe=recipe, position=index)
                for index, recipe in enumerate(dishes)
            )
        return slot


def _one_line(text: str) -> str:
    text = " ".join(text.split())
    if not text:
        raise serializers.ValidationError("A rule needs some text.")
    return text


class SystemRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = SystemRule
        fields = ["id", "code", "text_it", "text_en", "position", "active"]
        read_only_fields = ["code"]

    def validate_text_it(self, text: str) -> str:
        return _one_line(text)

    def validate_text_en(self, text: str) -> str:
        return _one_line(text)


class TeamRuleSerializer(serializers.ModelSerializer):
    class Meta:
        model = TeamRule
        fields = ["id", "team", "text"]

    def validate_text(self, text: str) -> str:
        return _one_line(text)

    def validate_team(self, team):
        if self.instance and team != self.instance.team:
            raise serializers.ValidationError("A rule stays with its team.")
        return team


class WeeklyMenuSerializer(serializers.ModelSerializer):
    slots = MealSlotSerializer(many=True, read_only=True)
    excluded_rules = serializers.PrimaryKeyRelatedField(
        many=True, queryset=TeamRule.objects.all(), required=False
    )

    class Meta:
        model = WeeklyMenu
        fields = [
            "id",
            "team",
            "week_start",
            "status",
            "rationale",
            "instructions",
            "use_team_rules",
            "excluded_rules",
            "slots",
        ]
        read_only_fields = ["rationale"]

    def validate_week_start(self, value):
        if value.weekday() != 0:
            raise serializers.ValidationError("A week starts on Monday.")
        if self.instance and value != self.instance.week_start:
            raise serializers.ValidationError("A menu stays on its week.")
        return value

    def validate_instructions(self, text: str) -> str:
        if len(text) > MAX_INSTRUCTIONS:
            raise serializers.ValidationError(f"At most {MAX_INSTRUCTIONS} characters.")
        return text.strip()

    def validate(self, attrs):
        team = attrs.get("team") or self.instance.team
        if self.instance and team != self.instance.team:
            raise serializers.ValidationError({"team": "A menu stays with its team."})
        if any(rule.team_id != team.pk for rule in attrs.get("excluded_rules", [])):
            raise serializers.ValidationError({"excluded_rules": "Not one of the team's rules."})
        return attrs


class MenuGenerationSerializer(serializers.ModelSerializer):
    week_start = serializers.DateField(source="menu.week_start", read_only=True)

    class Meta:
        model = MenuGeneration
        fields = [
            "id",
            "menu",
            "week_start",
            "status",
            "use_week_settings",
            "rules",
            "result",
            "error",
            "created_at",
            "started_at",
            "finished_at",
        ]
        read_only_fields = fields


class GenerateSerializer(serializers.Serializer):
    """`POST /api/menus/generate/`: plan a week, with the standing rules or the week's too."""

    team = serializers.PrimaryKeyRelatedField(queryset=Team.objects.all())
    week_start = serializers.DateField()
    use_week_settings = serializers.BooleanField(default=False)

    def validate_week_start(self, value):
        if value.weekday() != 0:
            raise serializers.ValidationError("A week starts on Monday.")
        return value


class MealKeySerializer(serializers.Serializer):
    date = serializers.DateField()
    meal = serializers.ChoiceField(choices=PLANNED_MEALS)


class ReviewSerializer(serializers.Serializer):
    """`POST /api/menus/<id>/review/`: accept or reject the proposals, of some meals or all."""

    action = serializers.ChoiceField(choices=["accept", "reject"])
    meals = MealKeySerializer(many=True, required=False)
