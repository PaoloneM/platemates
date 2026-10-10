"""Shared catalogs: normalized ingredients and kitchen tools.

Ingredients come in two kinds:
- **system** ingredients (no owner team), curated by staff and shared by every team: one
  "tomato" for everyone is what makes recipes comparable across teams and keeps the shopping
  list free of duplicates;
- **team** ingredients, added by a team for itself when the system catalog lacks one. Only
  that team picks them; staff promote them to system ingredients or merge them into one.

Kitchen tools are global.
"""

from __future__ import annotations

import uuid

from django.contrib.postgres.fields import ArrayField
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.provenance import ProvenanceMixin
from apps.core.seasons import month_set_field


class Unit(models.TextChoices):
    GRAM = "g", _("gram")
    MILLILITRE = "ml", _("millilitre")
    PIECE = "pc", _("piece")
    # For quantities nobody weighs (salt, pepper, oil for greasing). Never scaled or summed as
    # amounts on the shopping list; the ingredient is just listed.
    TO_TASTE = "tt", _("to taste")


class IngredientCategory(models.TextChoices):
    """Food category: drives nutritional variety rules and shopping-list grouping.

    Proteins are split finely on purpose, because "no same protein on adjacent days" needs to tell
    red meat from fish from legumes.
    """

    VEGETABLE = "vegetable", _("Vegetable")
    FRUIT = "fruit", _("Fruit")
    LEGUME = "legume", _("Legume")
    CEREAL = "cereal", _("Cereal, pasta, bread")
    RED_MEAT = "red_meat", _("Red meat")
    WHITE_MEAT = "white_meat", _("White meat")
    CURED_MEAT = "cured_meat", _("Cured / processed meat")
    FISH = "fish", _("Fish")
    SEAFOOD = "seafood", _("Seafood")
    EGG = "egg", _("Egg")
    DAIRY = "dairy", _("Milk, yogurt, cream")
    CHEESE = "cheese", _("Cheese")
    FAT = "fat", _("Oil, butter, fat")
    NUT_SEED = "nut_seed", _("Nut, seed")
    HERB_SPICE = "herb_spice", _("Herb, spice")
    CONDIMENT = "condiment", _("Condiment, sauce")
    SWEETENER = "sweetener", _("Sugar, honey, sweetener")
    OTHER = "other", _("Other")


PROTEIN_CATEGORIES: frozenset[str] = frozenset(
    {
        IngredientCategory.LEGUME,
        IngredientCategory.RED_MEAT,
        IngredientCategory.WHITE_MEAT,
        IngredientCategory.CURED_MEAT,
        IngredientCategory.FISH,
        IngredientCategory.SEAFOOD,
        IngredientCategory.EGG,
        IngredientCategory.CHEESE,
    }
)


class IngredientQuerySet(models.QuerySet):
    def system(self) -> IngredientQuerySet:
        return self.filter(owner_team__isnull=True)

    def usable_by(self, team) -> IngredientQuerySet:
        """What a team's recipes and preferences may use: system ingredients and its own. The
        system team's recipes use system ingredients only."""
        if team is None or team.is_system:
            return self.system()
        return self.filter(models.Q(owner_team__isnull=True) | models.Q(owner_team=team))

    def visible_to(self, user) -> IngredientQuerySet:
        """System ingredients and those of the user's teams; staff see every team's additions."""
        if user.is_staff:
            return self
        return self.filter(
            models.Q(owner_team__isnull=True) | models.Q(owner_team__memberships__user=user)
        ).distinct()


class Ingredient(ProvenanceMixin, models.Model):
    # Stable identity across installations: what an export file refers to (apps/transfer).
    uid = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    # Normalized, singular, lowercase. Variants people type ("tomatoes", "pomodori") live in
    # `aliases` and resolve here. Unique among system ingredients, and within a team's own.
    name = models.CharField(max_length=120)
    aliases = ArrayField(models.CharField(max_length=120), default=list, blank=True)
    category = models.CharField(
        max_length=20, choices=IngredientCategory.choices, default=IngredientCategory.OTHER
    )
    default_unit = models.CharField(max_length=2, choices=Unit.choices, default=Unit.GRAM)
    season_months = month_set_field("Months in which the ingredient is in season.")
    # The team that added it for itself; none for system ingredients.
    owner_team = models.ForeignKey(
        "families.Team",
        null=True,
        blank=True,
        on_delete=models.CASCADE,
        related_name="ingredients",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    objects = IngredientQuerySet.as_manager()

    class Meta:
        ordering = ["name"]
        constraints = [
            models.UniqueConstraint(
                fields=["name"],
                condition=models.Q(owner_team__isnull=True),
                name="unique_system_ingredient_name",
            ),
            models.UniqueConstraint(
                fields=["owner_team", "name"],
                condition=models.Q(owner_team__isnull=False),
                name="unique_team_ingredient_name",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs) -> None:
        self.name = normalize_name(self.name)
        self.aliases = sorted({normalize_name(a) for a in self.aliases} - {self.name})
        super().save(*args, **kwargs)

    @property
    def is_system(self) -> bool:
        return self.owner_team_id is None

    @property
    def is_protein(self) -> bool:
        return self.category in PROTEIN_CATEGORIES


class KitchenTool(models.Model):
    """A piece of equipment a recipe may need and a team may own."""

    name = models.CharField(max_length=80, unique=True)
    # Stable code of the tools the app ships with ("conventional_oven"): the interface shows
    # them translated. Null for tools added by users, which are shown by their name, in the
    # language they were written in.
    code = models.SlugField(max_length=40, unique=True, null=True, blank=True, editable=False)
    # Tools that heat up the kitchen (conventional oven, deep fryer) are less welcome in summer.
    heats_kitchen = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name


def normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())
