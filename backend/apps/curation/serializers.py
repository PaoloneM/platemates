from rest_framework import serializers

from apps.catalog.matching import match_ingredient

from .drafting import MAX_BATCH
from .models import SystemDraft


class SystemDraftSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()

    class Meta:
        model = SystemDraft
        fields = [
            "id",
            "dish",
            "language",
            "status",
            "sources",
            "draft",
            "reliability",
            "agreement",
            "web_rating",
            "web_rating_count",
            "error",
            "recipe",
            "requested_by_name",
            "created_at",
            "finished_at",
        ]
        read_only_fields = fields

    def get_requested_by_name(self, draft) -> str | None:
        user = draft.requested_by
        return (user.get_full_name() or user.email) if user else None


class SystemDraftDetailSerializer(SystemDraftSerializer):
    """With each draft ingredient's catalog match, for the recipe editor (as the assistant)."""

    matches = serializers.SerializerMethodField()

    class Meta(SystemDraftSerializer.Meta):
        fields = [*SystemDraftSerializer.Meta.fields, "matches"]
        read_only_fields = fields

    def get_matches(self, draft) -> list[dict]:
        if not draft.draft:
            return []
        # A system recipe uses system ingredients only.
        return [match_ingredient(line["name"]) for line in draft.draft["ingredients"]]


class DraftRequestSerializer(serializers.Serializer):
    """Dishes by name (one per entry), or a theme and how many dishes to draft for it."""

    dishes = serializers.ListField(
        child=serializers.CharField(max_length=200), required=False, max_length=MAX_BATCH
    )
    theme = serializers.CharField(max_length=300, required=False)
    count = serializers.IntegerField(min_value=1, max_value=MAX_BATCH, required=False, default=5)

    def validate(self, attrs):
        dishes = [" ".join(d.split()) for d in attrs.get("dishes", []) if d.strip()]
        theme = attrs.get("theme", "").strip()
        if bool(dishes) == bool(theme):
            raise serializers.ValidationError("Give either dishes or a theme.")
        attrs["dishes"] = list(dict.fromkeys(dishes))
        attrs["theme"] = theme
        return attrs
