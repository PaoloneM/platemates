import re

from django.db.models import Count
from rest_framework import serializers

from apps.catalog.matching import match_ingredient
from apps.catalog.models import IngredientCategory

from .drafting import MAX_BATCH
from .models import Campaign, CandidateLink, IngredientProposal, SourceSite, SystemDraft
from .publishing import blockers


class SystemDraftSerializer(serializers.ModelSerializer):
    requested_by_name = serializers.SerializerMethodField()
    campaign_name = serializers.CharField(source="campaign.name", read_only=True, default=None)

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
            "campaign",
            "campaign_name",
            "target",
            "published_automatically",
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
    links = serializers.SerializerMethodField()
    # Why it was not published automatically (campaign drafts that are ready).
    blockers = serializers.SerializerMethodField()

    class Meta(SystemDraftSerializer.Meta):
        fields = [*SystemDraftSerializer.Meta.fields, "matches", "links", "blockers"]
        read_only_fields = fields

    def get_links(self, draft) -> list[dict]:
        return CandidateLinkSerializer(draft.links.all(), many=True).data

    def get_blockers(self, draft) -> list[str]:
        if draft.campaign_id is None or draft.status != SystemDraft.Status.READY:
            return []
        return blockers(draft)

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


class CandidateLinkSerializer(serializers.ModelSerializer):
    class Meta:
        model = CandidateLink
        fields = ["url", "site", "trusted", "outcome", "title", "rating", "rating_count"]
        read_only_fields = fields


TARGET_KEY = re.compile(r"^[a-z0-9_-]{1,40}$")


class CampaignSerializer(serializers.ModelSerializer):
    """A campaign with its progress: per target, how many drafts are in each state."""

    progress = serializers.SerializerMethodField()
    recipe_ids = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = [
            "id",
            "name",
            "language",
            "brief",
            "targets",
            "status",
            "notes",
            "progress",
            "recipe_ids",
            "created_at",
        ]
        read_only_fields = ["status", "notes", "progress", "recipe_ids", "created_at"]

    def validate_targets(self, targets):
        if not isinstance(targets, list) or not targets:
            raise serializers.ValidationError("At least one target.")
        clean, keys = [], set()
        for target in targets:
            if not isinstance(target, dict):
                raise serializers.ValidationError("Each target is {key, theme, count}.")
            key = str(target.get("key") or "").strip().lower()
            theme = " ".join(str(target.get("theme") or "").split())[:300]
            try:
                count = int(target.get("count"))
            except (TypeError, ValueError):
                count = 0
            if not TARGET_KEY.match(key) or key in keys or not theme or not 1 <= count <= 500:
                raise serializers.ValidationError(
                    "Each target needs a unique short key, a theme and a count from 1 to 500."
                )
            keys.add(key)
            clean.append({"key": key, "theme": theme, "count": count})
        return clean

    def get_progress(self, campaign) -> dict:
        rows = campaign.drafts.values("target", "status", "published_automatically").annotate(
            n=Count("pk")
        )
        waiting = set(
            campaign.drafts.filter(
                status=SystemDraft.Status.READY,
                ingredient_proposals__status=IngredientProposal.Status.PENDING,
            ).values_list("pk", flat=True)
        )
        waiting_by_target = dict(
            campaign.drafts.filter(pk__in=waiting)
            .values("target")
            .annotate(n=Count("pk"))
            .values_list("target", "n")
        )
        progress = {
            t["key"]: {
                "count": t["count"],
                **{status: 0 for status in SystemDraft.Status.values},
                "automatic": 0,
                "waiting_ingredients": waiting_by_target.get(t["key"], 0),
            }
            for t in campaign.targets
        }
        for row in rows:
            entry = progress.get(row["target"])
            if entry is None:
                continue
            entry[row["status"]] += row["n"]
            if row["published_automatically"]:
                entry["automatic"] += row["n"]
        return progress

    def get_recipe_ids(self, campaign) -> list[int]:
        return list(
            campaign.drafts.filter(status=SystemDraft.Status.PUBLISHED, recipe__isnull=False)
            .order_by("recipe_id")
            .values_list("recipe_id", flat=True)
        )


class SourceSiteSerializer(serializers.ModelSerializer):
    class Meta:
        model = SourceSite
        fields = ["id", "domain", "trusted", "note"]

    def validate_domain(self, domain: str) -> str:
        domain = domain.strip().lower().removeprefix("https://").removeprefix("http://")
        domain = domain.split("/")[0].removeprefix("www.")
        if "." not in domain or " " in domain:
            raise serializers.ValidationError("A domain, like giallozafferano.it.")
        return domain


class IngredientProposalSerializer(serializers.ModelSerializer):
    alias_of_name = serializers.CharField(source="alias_of.name", read_only=True, default=None)
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True, default=None)
    # Dishes of the drafts that use the name (the first few) and how many drafts wait for it.
    used_by = serializers.SerializerMethodField()
    waiting = serializers.SerializerMethodField()
    # Similar catalog entries, to pick another as the one it is an alias of.
    candidates = serializers.SerializerMethodField()

    class Meta:
        model = IngredientProposal
        fields = [
            "id",
            "name",
            "status",
            "action",
            "alias_of",
            "alias_of_name",
            "category",
            "default_unit",
            "season_months",
            "basic",
            "edited",
            "ingredient",
            "ingredient_name",
            "used_by",
            "waiting",
            "candidates",
            "created_at",
        ]
        read_only_fields = ["name", "status", "edited", "ingredient", "created_at"]

    EDITABLE = ("action", "alias_of", "category", "default_unit", "season_months", "basic")

    def get_used_by(self, proposal) -> list[str]:
        return [d.dish for d in list(proposal.drafts.all())[:5]]

    def get_waiting(self, proposal) -> int:
        return proposal.drafts.filter(status=SystemDraft.Status.READY).count()

    def get_candidates(self, proposal) -> list[dict]:
        return match_ingredient(proposal.name)["candidates"]

    def validate_alias_of(self, ingredient):
        if ingredient is not None and not ingredient.is_system:
            raise serializers.ValidationError("A system ingredient.")
        return ingredient

    def validate_category(self, category):
        if category not in IngredientCategory.values:
            raise serializers.ValidationError("Unknown category.")
        return category

    def validate_default_unit(self, unit):
        if unit not in ("g", "ml", "pc"):
            raise serializers.ValidationError("g, ml or pc.")
        return unit

    def validate_season_months(self, months):
        if any(not isinstance(m, int) or not 1 <= m <= 12 for m in months):
            raise serializers.ValidationError("Months from 1 to 12.")
        months = sorted(set(months))
        return [] if len(months) == 12 else months

    def validate(self, attrs):
        action = attrs.get("action", getattr(self.instance, "action", None))
        alias_of = attrs.get("alias_of", getattr(self.instance, "alias_of", None))
        if action == IngredientProposal.Action.ALIAS and alias_of is None:
            raise serializers.ValidationError(
                {"alias_of": "Which ingredient is it another name of?"}
            )
        return attrs

    def update(self, proposal, validated_data):
        changed = [
            f
            for f in self.EDITABLE
            if f in validated_data and validated_data[f] != getattr(proposal, f)
        ]
        proposal.edited = sorted({*proposal.edited, *changed})
        return super().update(proposal, validated_data)
