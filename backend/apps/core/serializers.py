from __future__ import annotations

from rest_framework import serializers

from .provenance import Source
from .seasons import SEASON_MONTHS, is_season_aligned, months_to_seasons, seasons_to_months


class SeasonalityField(serializers.Field):
    """A month-set field, exposed in both editing modes.

    Read: `{"months": [...], "seasons": [...], "by_season": bool}`; `by_season` tells the UI
    whether the value can be shown in the default season mode or needs the advanced month view.
    Empty `months` means all year.

    Write: `{"seasons": [...]}` (season mode) or `{"months": [...]}` (advanced mode).
    """

    default_error_messages = {
        "invalid": 'Expected {"seasons": [...]} or {"months": [...]}.',
        "season": "Unknown season '{value}'. Known: {known}.",
        "month": "Months are integers from 1 to 12.",
    }

    def to_representation(self, value):
        months = sorted(value or [])
        return {
            "months": months,
            "seasons": months_to_seasons(months) if months else list(SEASON_MONTHS),
            "by_season": is_season_aligned(months),
        }

    def to_internal_value(self, data):
        if not isinstance(data, dict) or len(data) != 1:
            self.fail("invalid")
        if "seasons" in data:
            unknown = [s for s in data["seasons"] if s not in SEASON_MONTHS]
            if unknown:
                self.fail("season", value=unknown[0], known=", ".join(SEASON_MONTHS))
            months = seasons_to_months(data["seasons"])
        elif "months" in data:
            months = data["months"]
            if not all(isinstance(m, int) and 1 <= m <= 12 for m in months):
                self.fail("month")
        else:
            self.fail("invalid")
        months = sorted(set(months))
        # Every month selected is the same as "all year"; store it the canonical way.
        return [] if len(months) == 12 else months


class UserDecisionSerializerMixin(serializers.ModelSerializer):
    """Mark every provenance-tracked field written through the API as a user decision.

    Anything arriving from the REST API comes from a person, so it must not be overwritten later by
    an LLM suggestion or a derivation. Subclasses list the tracked fields in `Meta.tracked_fields`.
    """

    def _mark_user_fields(self, validated_data: dict) -> None:
        tracked = getattr(self.Meta, "tracked_fields", ())
        touched = {name: Source.USER.value for name in tracked if name in validated_data}
        if touched:
            current = validated_data.get("provenance") or getattr(self.instance, "provenance", {})
            validated_data["provenance"] = {**(current or {}), **touched}

    def create(self, validated_data: dict):
        self._mark_user_fields(validated_data)
        return super().create(validated_data)

    def update(self, instance, validated_data: dict):
        self._mark_user_fields(validated_data)
        return super().update(instance, validated_data)
