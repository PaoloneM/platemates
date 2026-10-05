from django.db import transaction
from rest_framework import serializers

from apps.recipes.models import Recipe

from .models import MealSlot, SlotDish, WeeklyMenu


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


class WeeklyMenuSerializer(serializers.ModelSerializer):
    slots = MealSlotSerializer(many=True, read_only=True)

    class Meta:
        model = WeeklyMenu
        fields = ["id", "family", "week_start", "status", "rationale", "slots"]

    def validate_week_start(self, value):
        if value.weekday() != 0:
            raise serializers.ValidationError("A week starts on Monday.")
        return value
