"""Recipes: structured, scalable, with two-level seasonality.

A `Recipe` is shared across teams; how a given team relates to it (in its recipe book or still
a candidate, how much they like it) lives in `teams.RecipeBookEntry`.
"""

from __future__ import annotations

from decimal import Decimal

from django.contrib.postgres.fields import ArrayField
from django.core.validators import MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField

from apps.catalog.models import Ingredient, KitchenTool, Unit
from apps.core.provenance import ProvenanceMixin
from apps.core.seasons import ALL_MONTHS, as_months, intersect_months, month_set_field


class Cuisine(models.Model):
    """Cuisine type / origin, used to balance cultural variety across the week."""

    name = models.CharField(max_length=80, unique=True)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


class Course(models.TextChoices):
    FIRST = "first", _("First course")
    MAIN = "main", _("Main course")
    SIDE = "side", _("Side dish")
    SINGLE = "single", _("Single-dish meal")
    STARTER = "starter", _("Starter")
    DESSERT = "dessert", _("Dessert")


class Visibility(models.TextChoices):
    # Visible to every team: feeds collaborative recommendation. The default.
    SHARED = "shared", _("Shared with other teams")
    # Visible only to the owner team.
    PRIVATE = "private", _("Private to the team")


class RecipeQuerySet(models.QuerySet):
    def visible_to(self, user) -> RecipeQuerySet:
        """Shared recipes, plus the private ones of the user's teams."""
        return self.filter(
            models.Q(visibility=Visibility.SHARED) | models.Q(owner_team__memberships__user=user)
        ).distinct()

    def editable_by(self, user) -> RecipeQuerySet:
        """Only the team that owns a recipe edits it; staff can edit everything."""
        if user.is_staff:
            return self
        return self.filter(owner_team__memberships__user=user).distinct()


class Recipe(ProvenanceMixin, models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    # The method, one entry per step.
    steps = ArrayField(models.TextField(), default=list, blank=True)
    # The team that created the recipe and may edit it. Null for recipes seeded by staff.
    owner_team = models.ForeignKey(
        "families.Team",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="owned_recipes",
    )
    visibility = models.CharField(
        max_length=10, choices=Visibility.choices, default=Visibility.SHARED
    )
    course = models.CharField(max_length=10, choices=Course.choices, default=Course.SINGLE)
    cuisine = models.ForeignKey(
        Cuisine, null=True, blank=True, on_delete=models.SET_NULL, related_name="recipes"
    )
    # Quantities in `ingredients` are for this many people; scaling is linear from here.
    servings = models.PositiveSmallIntegerField(default=2, validators=[MinValueValidator(1)])
    prep_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    cook_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    tools = models.ManyToManyField(KitchenTool, blank=True, related_name="recipes")

    # Seasonality, level 1: derived bottom-up from the ingredients (see `derive_season_months`),
    # stored so it can be confirmed or overridden by the user like any other suggestion.
    season_months = month_set_field("Months in which the ingredients are in season.")
    # Seasonality, level 2: whether the dish suits the climate (a hot soup in August does not,
    # whatever its ingredients).
    climate_months = month_set_field("Months in which the dish suits the weather.")

    source_url = models.URLField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = RecipeQuerySet.as_manager()

    class Meta:
        ordering = ["title"]

    def __str__(self) -> str:
        return self.title

    @property
    def total_minutes(self) -> int | None:
        if self.prep_minutes is None and self.cook_minutes is None:
            return None
        return (self.prep_minutes or 0) + (self.cook_minutes or 0)

    def derive_season_months(self) -> list[int]:
        """Months in which every non-optional ingredient is in season.

        If the ingredients' seasons do not overlap at all, the union is returned instead: an
        empty list would read as "all year", and such recipes usually rely on a preserved
        ingredient anyway. The user confirms or corrects it, like any derived value.
        """
        month_lists = [
            line.ingredient.season_months
            for line in self.ingredients.select_related("ingredient")
            if not line.optional
        ]
        months = intersect_months(*month_lists)
        if not months:
            months = frozenset().union(*(as_months(m) for m in month_lists))
        return [] if months == ALL_MONTHS else sorted(months)

    def suitable_months(self) -> frozenset[int]:
        """Both seasonality levels combined: when the recipe makes sense to propose."""
        return intersect_months(self.season_months, self.climate_months)


class RecipeIngredient(models.Model):
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="ingredients")
    ingredient = models.ForeignKey(Ingredient, on_delete=models.PROTECT, related_name="uses")
    # Null for "to taste".
    quantity = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    unit = models.CharField(max_length=2, choices=Unit.choices, default=Unit.GRAM)
    optional = models.BooleanField(default=False)
    note = models.CharField(max_length=200, blank=True, help_text='E.g. "finely chopped".')
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["recipe", "position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["recipe", "ingredient"], name="unique_recipe_ingredient"
            )
        ]

    def __str__(self) -> str:
        return f"{self.ingredient} ({self.quantity} {self.unit})"

    def scaled_quantity(self, people: int) -> Decimal | None:
        """Quantity for `people` diners. None when the ingredient is not measured."""
        if self.quantity is None or self.unit == Unit.TO_TASTE:
            return None
        return self.quantity * Decimal(people) / Decimal(self.recipe.servings)


class RecipeEmbedding(models.Model):
    """A recipe's vector, one per embedding model.

    The column has no fixed dimension on purpose: swapping the embedding model only means
    recomputing rows for the new `model`, without a schema migration. The cost is that pgvector
    cannot build an ANN index on an undimensioned column; at recipe-book scale (thousands of rows)
    exact search is fast enough. Add a dimensioned, indexed column if that ever changes.
    """

    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="embeddings")
    model = models.CharField(max_length=200)
    vector = VectorField()
    # Hash of the text that was embedded, so stale vectors can be detected after edits.
    content_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["recipe", "model"], name="unique_recipe_embedding")
        ]

    def __str__(self) -> str:
        return f"{self.recipe} [{self.model}]"
