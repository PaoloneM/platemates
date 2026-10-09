from django.db import transaction
from rest_framework import serializers

from apps.core.provenance import Source
from apps.core.serializers import SeasonalityField, UserDecisionSerializerMixin
from apps.curation.models import SystemDraft
from apps.teams.models import Membership, RecipeBookEntry, Team

from .embeddings import refresh_embedding
from .models import Cuisine, Recipe, RecipeIngredient, Visibility


def user_team_ids(context) -> set[int]:
    """The requesting user's teams, computed once per request."""
    if "user_team_ids" not in context:
        user = context["request"].user
        context["user_team_ids"] = set(
            Membership.objects.filter(user=user).values_list("team_id", flat=True)
        )
    return context["user_team_ids"]


def author_of(recipe: Recipe, teams: set[int]) -> dict:
    """Who a recipe is shown as coming from: the system, one of the user's teams, another team
    that signs its shared recipes, or the community (anonymous)."""
    team = recipe.owner_team
    if team is not None and team.is_system:
        return {"kind": "system", "name": team.name}
    if team is not None and team.pk in teams:
        return {"kind": "mine", "name": team.name}
    if team is not None and team.sign_shared_recipes:
        return {"kind": "team", "name": team.name}
    return {"kind": "community", "name": None}


def origin_of(recipe: Recipe, teams: set[int]) -> dict | None:
    """The original a recipe is a variant of, if the user can see it."""
    original = recipe.derived_from
    if original is None:
        return None
    if original.visibility != Visibility.SHARED and original.owner_team_id not in teams:
        return None
    return {"id": original.pk, "title": original.title}


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
    # On create: the team that owns the recipe and gets it in its recipe book.
    team = serializers.PrimaryKeyRelatedField(
        queryset=Team.objects.all(), write_only=True, required=False
    )
    # No default: whether a new recipe goes to the community is asked at its first save.
    visibility = serializers.ChoiceField(choices=Visibility.choices)
    # On create: the recipe this one is imported from and changed (stored as its original).
    derived_from = serializers.PrimaryKeyRelatedField(
        queryset=Recipe.objects.all(), required=False, allow_null=True
    )
    origin = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    # Staff, on create: the system recipe draft this recipe publishes (`apps.curation`).
    system_draft = serializers.PrimaryKeyRelatedField(
        queryset=SystemDraft.objects.all(), write_only=True, required=False
    )
    can_edit = serializers.SerializerMethodField()
    # How the requesting user's teams relate to the recipe.
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
            "owner_team",
            "team",
            "derived_from",
            "origin",
            "author",
            "system_draft",
            "web_rating",
            "web_rating_count",
            "can_edit",
            "book_entries",
            "ingredients",
            "provenance",
        ]
        read_only_fields = ["provenance", "owner_team", "web_rating", "web_rating_count"]
        tracked_fields = ["course", "cuisine", "season_months", "climate_months", "tools"]

    def _user(self):
        return self.context["request"].user

    def get_can_edit(self, recipe) -> bool:
        user = self._user()
        return (
            user.is_staff
            or Membership.objects.filter(user=user, team_id=recipe.owner_team_id).exists()
        )

    def get_book_entries(self, recipe) -> list[dict]:
        entries = RecipeBookEntry.objects.filter(
            recipe=recipe, team__memberships__user=self._user()
        )
        return [
            {"id": e.id, "team": e.team_id, "status": e.status, "rating": e.rating} for e in entries
        ]

    def validate_steps(self, steps):
        return [step.strip() for step in steps if step and step.strip()]

    def get_origin(self, recipe) -> dict | None:
        return origin_of(recipe, user_team_ids(self.context))

    def get_author(self, recipe) -> dict:
        return author_of(recipe, user_team_ids(self.context))

    def validate_team(self, team):
        if team.is_system:
            if not self._user().is_staff:
                raise serializers.ValidationError("Only staff write system recipes.")
            return team
        if not Membership.objects.filter(user=self._user(), team=team).exists():
            raise serializers.ValidationError("Not one of your teams.")
        return team

    def validate_derived_from(self, source):
        """Only a recipe the user can see; a copy of a copy is a variant of the original."""
        if source is None:
            return None
        if not Recipe.objects.visible_to(self._user()).filter(pk=source.pk).exists():
            raise serializers.ValidationError("Recipe not found.")
        return source.derived_from or source

    def validate_system_draft(self, draft):
        if draft.status != SystemDraft.Status.READY:
            raise serializers.ValidationError("This draft is not ready to publish.")
        return draft

    def validate(self, attrs):
        if attrs.get("system_draft") is not None and (
            self.instance is not None or not getattr(attrs.get("team"), "is_system", False)
        ):
            raise serializers.ValidationError(
                {"system_draft": "A draft is published as a new system recipe."}
            )
        if self.instance is None and "team" not in attrs:
            raise serializers.ValidationError({"team": "Required when creating a recipe."})
        if self.instance is not None:
            # A recipe's origin is set once, when it is imported.
            attrs.pop("derived_from", None)
        owner = attrs.get("team") or (self.instance.owner_team if self.instance else None)
        if (
            owner is not None
            and owner.is_system
            and attrs.get("visibility", Visibility.SHARED) != (Visibility.SHARED)
        ):
            raise serializers.ValidationError({"visibility": "System recipes are shared."})
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        team = validated_data.pop("team")
        lines = validated_data.pop("ingredients", [])
        draft = validated_data.pop("system_draft", None)
        validated_data["owner_team"] = team
        if draft is not None:
            # The web rating comes from the draft's sources: read from the pages, never edited.
            validated_data["web_rating"] = draft.web_rating
            validated_data["web_rating_count"] = draft.web_rating_count
        recipe = super().create(validated_data)
        if draft is not None:
            draft.status = SystemDraft.Status.PUBLISHED
            draft.recipe = recipe
            draft.save(update_fields=["status", "recipe"])
        self._replace_lines(recipe, lines)
        self._derive(recipe)
        RecipeBookEntry.objects.create(
            team=team, recipe=recipe, status=RecipeBookEntry.Status.APPROVED
        )
        return recipe

    @transaction.atomic
    def update(self, instance, validated_data):
        validated_data.pop("team", None)
        lines = validated_data.pop("ingredients", None)
        recipe = super().update(instance, validated_data)
        if lines is not None:
            self._replace_lines(recipe, lines)
        self._derive(recipe)
        return recipe

    @staticmethod
    def _derive(recipe: Recipe) -> None:
        """Recompute derived properties the user has not taken over, and the embedding."""
        if recipe.propose("season_months", recipe.derive_season_months(), Source.DERIVED):
            recipe.save(update_fields=["season_months", "provenance"])
        # After the transaction, so a slow or failing embedding service never blocks or undoes
        # the save; `embed_recipes` catches up on whatever was missed.
        transaction.on_commit(lambda: refresh_embedding(recipe))

    @staticmethod
    def _replace_lines(recipe: Recipe, lines: list[dict]) -> None:
        recipe.ingredients.all().delete()
        RecipeIngredient.objects.bulk_create(
            RecipeIngredient(recipe=recipe, **{**line, "position": index})
            for index, line in enumerate(lines)
        )


class RecipeCardSerializer(serializers.ModelSerializer):
    """A recipe in the recipe book screen: its own book or the community. Expects the queryset
    of `RecipeViewSet.browse` (book entries of the team prefetched as `team_book`)."""

    cuisine_name = serializers.CharField(source="cuisine.name", read_only=True, default=None)
    total_minutes = serializers.IntegerField(read_only=True)
    suitable_months = serializers.SerializerMethodField()
    author = serializers.SerializerMethodField()
    origin = serializers.SerializerMethodField()
    # The team's entry for this recipe, if it is in its recipe book.
    book = serializers.SerializerMethodField()

    class Meta:
        model = Recipe
        fields = [
            "id",
            "title",
            "course",
            "cuisine_name",
            "servings",
            "total_minutes",
            "suitable_months",
            "visibility",
            "author",
            "origin",
            "book",
            "web_rating",
            "web_rating_count",
        ]

    def get_suitable_months(self, recipe) -> list[int]:
        months = recipe.suitable_months()
        return [] if len(months) == 12 else sorted(months)

    def get_author(self, recipe) -> dict:
        return author_of(recipe, user_team_ids(self.context))

    def get_origin(self, recipe) -> dict | None:
        return origin_of(recipe, user_team_ids(self.context))

    def get_book(self, recipe) -> dict | None:
        entry = next(iter(getattr(recipe, "team_book", [])), None)
        return {"id": entry.pk, "rating": entry.rating} if entry else None
