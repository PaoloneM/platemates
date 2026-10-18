from django.db import transaction
from rest_framework import serializers

from apps.audit.recorder import collecting, note
from apps.catalog.models import Ingredient
from apps.core.planes import staff_powers
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
    return {"id": original.pk, "title": original.title, "author": author_of(original, teams)}


def _line_texts(recipe: Recipe) -> list[str]:
    """A recipe's ingredients as the activity log shows them: "160 g spaghetti"."""
    texts = []
    for line in recipe.ingredients.select_related("ingredient").order_by("position"):
        amount = "" if line.quantity is None else f"{line.quantity.normalize():f} {line.unit} "
        texts.append(f"{amount}{line.ingredient.name}")
    return texts


def _snapshot(recipe: Recipe) -> dict[str, object]:
    """What a recipe's page shows, part by part, to tell which parts a change touched."""
    return {
        "title": recipe.title,
        "description": recipe.description,
        "steps": list(recipe.steps),
        "servings": recipe.servings,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "course": recipe.course,
        "cuisine": recipe.cuisine_id,
        "visibility": recipe.visibility,
        "source_url": recipe.source_url,
        "season_months": list(recipe.season_months),
        "climate_months": list(recipe.climate_months),
        "tools": sorted(recipe.tools.values_list("pk", flat=True)),
        "ingredients": _line_texts(recipe),
        "owner_team": recipe.owner_team_id,
    }


def announce_recipe(recipe: Recipe, action: str, fields: list[str] | tuple = ()) -> None:
    """Tell the browsers that may show the recipe what happened to it (`recipe` event, once
    saved): `created`, `updated` (with the parts that changed) or `deleted`. They are the team
    that owns it, the teams that keep it in their book, and every team when it is shared (their
    community). Call it before deleting: the book entries go with the recipe."""
    from apps.realtime.events import publish_on_commit

    teams = set(RecipeBookEntry.objects.filter(recipe=recipe).values_list("team_id", flat=True))
    if recipe.owner_team_id:
        teams.add(recipe.owner_team_id)
    if recipe.visibility == Visibility.SHARED:
        teams |= set(Team.objects.filter(is_system=False).values_list("pk", flat=True))
    teams.discard(None)
    data = {"recipe": recipe.pk, "action": action, "fields": list(fields)}
    publish_on_commit(teams, "recipe", data)


def announce_book(team_id: int, recipe_id: int, action: str) -> None:
    """A team's recipe book gained (`book_added`) or lost (`book_removed`) a recipe: only that
    team's browsers care."""
    from apps.realtime.events import publish_on_commit

    publish_on_commit([team_id], "recipe", {"recipe": recipe_id, "action": action, "team": team_id})


class CuisineSerializer(serializers.ModelSerializer):
    class Meta:
        model = Cuisine
        fields = ["id", "name"]


class RecipeIngredientSerializer(serializers.ModelSerializer):
    ingredient_name = serializers.CharField(source="ingredient.name", read_only=True)
    # The team that added the ingredient for itself; null for a system ingredient.
    ingredient_team = serializers.IntegerField(
        source="ingredient.owner_team_id", read_only=True, default=None
    )
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
            "ingredient_team",
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
    # The user's own version of this recipe (a variant one of their teams owns), if any.
    my_version = serializers.SerializerMethodField()
    # Staff, on create: the system recipe draft this recipe publishes (`apps.curation`).
    system_draft = serializers.PrimaryKeyRelatedField(
        queryset=SystemDraft.objects.all(), write_only=True, required=False
    )
    # Staff, on create: the team recipe this system recipe is promoted from, reviewed in the
    # editor. "move" (the default) turns that recipe itself into the system one, keeping its
    # identity (books, menus, variants); "copy" leaves it to its team and makes a new one.
    promote_from = serializers.PrimaryKeyRelatedField(
        queryset=Recipe.objects.all(), write_only=True, required=False
    )
    promote_mode = serializers.ChoiceField(
        choices=["move", "copy"], write_only=True, required=False, default="move"
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
            "my_version",
            "system_draft",
            "promote_from",
            "promote_mode",
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
            staff_powers(user)
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

    def get_my_version(self, recipe) -> dict | None:
        teams = user_team_ids(self.context)
        if recipe.owner_team_id in teams:
            return None
        version = (
            Recipe.objects.filter(derived_from=recipe, owner_team__in=teams)
            .order_by("-created_at")
            .values("id", "title")
            .first()
        )
        return version

    def validate_team(self, team):
        if team.is_system:
            if not staff_powers(self._user()):
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

    def validate_promote_from(self, source):
        if not Recipe.objects.visible_to(self._user()).filter(pk=source.pk).exists():
            raise serializers.ValidationError("Recipe not found.")
        if source.owner_team is not None and source.owner_team.is_system:
            raise serializers.ValidationError("Already a system recipe.")
        return source

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
        if attrs.get("promote_from") is not None:
            if self.instance is not None or not getattr(attrs.get("team"), "is_system", False):
                raise serializers.ValidationError(
                    {"promote_from": "A recipe is promoted by creating a system recipe."}
                )
            if attrs.get("system_draft") is not None:
                raise serializers.ValidationError({"promote_from": "Not with a draft."})
            # A system recipe is nobody's variant: it stands on its own.
            attrs.pop("derived_from", None)
        else:
            attrs.pop("promote_mode", None)
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
        if owner is not None and attrs.get("ingredients"):
            self._check_ingredients(owner, attrs)
        return attrs

    def _check_ingredients(self, owner, attrs) -> None:
        """A recipe uses system ingredients and its team's own (a system recipe, system ones
        only). Lines it already has, or its original had, keep theirs: another team's
        ingredient in a shared recipe a team makes its own version of."""
        ids = {line["ingredient"].pk for line in attrs["ingredients"]}
        allowed = set(
            Ingredient.objects.usable_by(owner).filter(pk__in=ids).values_list("pk", flat=True)
        )
        inherited = [r for r in (self.instance, attrs.get("derived_from")) if r is not None]
        for recipe in inherited:
            allowed.update(recipe.ingredients.values_list("ingredient_id", flat=True))
        if ids - allowed:
            raise serializers.ValidationError(
                {"ingredients": "Use system ingredients or your team's own."}
            )

    @transaction.atomic
    def create(self, validated_data):
        source = validated_data.pop("promote_from", None)
        if source is not None and validated_data.pop("promote_mode") == "move":
            return self._move_to_system(source, validated_data)
        team = validated_data.pop("team")
        lines = validated_data.pop("ingredients", [])
        draft = validated_data.pop("system_draft", None)
        validated_data["owner_team"] = team
        if draft is not None:
            # The web rating comes from the draft's sources: read from the pages, never edited.
            validated_data["web_rating"] = draft.web_rating
            validated_data["web_rating_count"] = draft.web_rating_count
        recipe = super().create(validated_data)
        original = recipe.derived_from
        if original is not None and original.owner_team_id != team.pk:
            # The team's own version replaces the original it had added as it is; the original
            # recipe itself is untouched and can be added again.
            RecipeBookEntry.objects.filter(team=team, recipe=original).delete()
        if draft is not None:
            draft.status = SystemDraft.Status.PUBLISHED
            draft.recipe = recipe
            draft.save(update_fields=["status", "recipe"])
        self._replace_lines(recipe, lines)
        self._derive(recipe)
        RecipeBookEntry.objects.create(
            team=team, recipe=recipe, status=RecipeBookEntry.Status.APPROVED
        )
        announce_recipe(recipe, "created")
        return recipe

    def _move_to_system(self, recipe: Recipe, validated_data) -> Recipe:
        """The team's recipe becomes the system one, as reviewed: same recipe, so books, menus
        and variants keep pointing to it, and its team keeps it in the book (changing it
        from there makes the team's own version, as for any community recipe)."""
        system = validated_data.pop("team")
        former_owner = recipe.owner_team
        validated_data["owner_team"] = system
        self.instance = recipe
        recipe = self.update(recipe, validated_data)
        for team in (system, former_owner):
            if team is not None:
                RecipeBookEntry.objects.get_or_create(
                    team=team, recipe=recipe, defaults={"status": RecipeBookEntry.Status.APPROVED}
                )
        return recipe

    @transaction.atomic
    def update(self, instance, validated_data):
        before = _snapshot(instance)
        validated_data.pop("team", None)
        lines = validated_data.pop("ingredients", None)
        recipe = super().update(instance, validated_data)
        if lines is not None:
            self._replace_lines(recipe, lines)
        self._derive(recipe)
        after = _snapshot(recipe)
        if changed := sorted(k for k in after if after[k] != before.get(k)):
            announce_recipe(recipe, "updated", changed)
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
        before = _line_texts(recipe)
        recipe.ingredients.all().delete()
        RecipeIngredient.objects.bulk_create(
            RecipeIngredient(recipe=recipe, **{**line, "position": index})
            for index, line in enumerate(lines)
        )
        # The lines are written in bulk: the activity log hears of them here.
        team = recipe.owner_team
        if collecting() and team is not None and not team.is_system:
            after = _line_texts(recipe)
            note(
                team.pk,
                "recipe",
                recipe.pk,
                recipe.title,
                "update",
                before={"ingredients": before},
                after={"ingredients": after},
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
