"""Families: the parametric profile that every suggestion is computed against.

Nothing about a specific family is hardcoded anywhere else: people, ages, tastes, tools and the
default number of diners per meal all live here and are editable at any time.
"""

from __future__ import annotations

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _
from pgvector.django import VectorField

from apps.catalog.models import Ingredient, KitchenTool
from apps.recipes.models import Cuisine, Recipe


class Meal(models.TextChoices):
    LUNCH = "lunch", _("Lunch")
    DINNER = "dinner", _("Dinner")


def default_people_per_meal() -> dict[str, int]:
    """Initial prefill for new menu slots. Only a starting value, editable per family."""
    return {Meal.LUNCH: 2, Meal.DINNER: 3}


class Family(models.Model):
    name = models.CharField(max_length=120)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="families"
    )
    tools = models.ManyToManyField(KitchenTool, blank=True, related_name="families")
    # How many people a new slot is prefilled with, per meal. The slot's own count is what
    # matters; this is only the default it starts from.
    default_people = models.JSONField(default=default_people_per_meal)
    # Ceiling on preparation + cooking time the family can sustain on an ordinary day.
    max_weekday_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(blank=True, help_text="Free-form context passed to the LLM.")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "families"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def default_people_for(self, meal: str) -> int:
        return int(self.default_people.get(meal, 0))


class Membership(models.Model):
    """Which application users may see and edit a family."""

    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        MEMBER = "member", _("Member")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "family"], name="unique_membership")]

    def __str__(self) -> str:
        return f"{self.user} in {self.family} ({self.role})"


class FamilyMember(models.Model):
    """A person who eats at the family table. Not necessarily an application user."""

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=80, blank=True)
    # Birth year rather than age: it does not go stale. Used for similarity between families.
    birth_year = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1900), MaxValueValidator(2100)]
    )

    class Meta:
        ordering = ["family", "birth_year"]

    def __str__(self) -> str:
        return self.name or f"member #{self.pk}"


class Preference(models.Model):
    """A taste or aversion, on an ingredient, a cuisine, or in free text."""

    class Kind(models.TextChoices):
        LOVES = "loves", _("Loves")
        LIKES = "likes", _("Likes")
        DISLIKES = "dislikes", _("Dislikes")
        AVOIDS = "avoids", _("Never propose")

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="preferences")
    # Null: the preference applies to the whole family.
    member = models.ForeignKey(
        FamilyMember, null=True, blank=True, on_delete=models.CASCADE, related_name="preferences"
    )
    kind = models.CharField(max_length=10, choices=Kind.choices)
    ingredient = models.ForeignKey(Ingredient, null=True, blank=True, on_delete=models.CASCADE)
    cuisine = models.ForeignKey(Cuisine, null=True, blank=True, on_delete=models.CASCADE)
    note = models.CharField(max_length=200, blank=True)

    class Meta:
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(ingredient__isnull=False)
                    | models.Q(cuisine__isnull=False)
                    | ~models.Q(note="")
                ),
                name="preference_has_subject",
            )
        ]

    def __str__(self) -> str:
        subject = self.ingredient or self.cuisine or self.note
        return f"{self.get_kind_display()}: {subject}"


class RecipeBookEntry(models.Model):
    """A recipe as seen by one family: in its recipe book, or a candidate awaiting approval."""

    class Status(models.TextChoices):
        # Proposed by discovery or by the menu engine; the user has not accepted it yet.
        CANDIDATE = "candidate", _("Candidate")
        APPROVED = "approved", _("In the recipe book")
        REJECTED = "rejected", _("Rejected")

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="recipe_book")
    recipe = models.ForeignKey(Recipe, on_delete=models.CASCADE, related_name="book_entries")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.CANDIDATE)
    # Explicit and optional; the implicit signal comes from menu outcomes.
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    notes = models.TextField(blank=True)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "recipe book entries"
        constraints = [
            models.UniqueConstraint(fields=["family", "recipe"], name="unique_book_entry")
        ]

    def __str__(self) -> str:
        return f"{self.family}: {self.recipe} ({self.status})"


class FamilyEmbedding(models.Model):
    """A family profile's vector, for collaborative recommendation. One per embedding model.

    Undimensioned for the same reason as `recipes.RecipeEmbedding`.
    """

    family = models.ForeignKey(Family, on_delete=models.CASCADE, related_name="embeddings")
    model = models.CharField(max_length=200)
    vector = VectorField()
    content_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["family", "model"], name="unique_family_embedding")
        ]

    def __str__(self) -> str:
        return f"{self.family} [{self.model}]"
