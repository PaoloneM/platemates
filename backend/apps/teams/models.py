"""Teams: the parametric profile that every suggestion is computed against.

Nothing about a specific team is hardcoded anywhere else: people, ages, tastes, tools and the
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
    BREAKFAST = "breakfast", _("Breakfast")
    LUNCH = "lunch", _("Lunch")
    DINNER = "dinner", _("Dinner")


# Meals the menu proposes dishes for. Breakfast is only counted (diners on the calendar, and
# later the shopping list), not planned.
PLANNED_MEALS = (Meal.LUNCH, Meal.DINNER)


def default_people_per_meal() -> dict[str, int]:
    """Default of the removed `Team.default_people`; kept because migration 0001 imports it."""
    return {Meal.LUNCH: 2, Meal.DINNER: 3}


def default_typical_week() -> list[dict]:
    """Initial typical week: every day active, 2 at lunch, 3 at dinner. Editable per team."""
    return [
        {"active": True, Meal.BREAKFAST: 0, Meal.LUNCH: 2, Meal.DINNER: 3} for _weekday in range(7)
    ]


class Team(models.Model):
    name = models.CharField(max_length=120)
    users = models.ManyToManyField(
        settings.AUTH_USER_MODEL, through="Membership", related_name="teams"
    )
    tools = models.ManyToManyField(KitchenTool, blank=True, related_name="teams")
    # The usual week, Monday first: per day whether the team eats together at all, and how many
    # people at each meal. Calendar days start from it; a menu slot's own count is what matters.
    typical_week = models.JSONField(default=default_typical_week)
    # Ceiling on preparation + cooking time the team can sustain on an ordinary day.
    max_weekday_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    notes = models.TextField(
        blank=True, help_text="A note for the team's users; not passed to the LLM."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name_plural = "teams"
        ordering = ["name"]

    def __str__(self) -> str:
        return self.name

    def usual_people(self, weekday: int, meal: str) -> int:
        """People usually at `meal` on `weekday` (0 = Monday); 0 on inactive days."""
        day = self.typical_week[weekday]
        return int(day.get(meal, 0)) if day.get("active", True) else 0


class CalendarDay(models.Model):
    """A date that differs from the team's typical week: guests, someone away, a meal out.

    Only the meals that differ are stored (`people`, meal -> count); the others follow the
    typical week. A row with no overrides and no note has no reason to exist and is deleted.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="calendar_days")
    date = models.DateField()
    people = models.JSONField(default=dict)
    note = models.CharField(max_length=200, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["team", "date"]
        constraints = [models.UniqueConstraint(fields=["team", "date"], name="unique_calendar_day")]

    def __str__(self) -> str:
        return f"{self.team} {self.date}: {self.people}"


class Membership(models.Model):
    """Which application users may see and edit a team."""

    class Role(models.TextChoices):
        OWNER = "owner", _("Owner")
        MEMBER = "member", _("Member")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE)
    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=10, choices=Role.choices, default=Role.MEMBER)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["user", "team"], name="unique_membership")]

    def __str__(self) -> str:
        return f"{self.user} in {self.team} ({self.role})"


class Member(models.Model):
    """A person who eats at the team table. Not necessarily an application user."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="members")
    name = models.CharField(max_length=80, blank=True)
    # Birth year rather than age: it does not go stale. Used for similarity between teams.
    birth_year = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1900), MaxValueValidator(2100)]
    )

    class Meta:
        ordering = ["team", "birth_year"]

    def __str__(self) -> str:
        return self.name or f"member #{self.pk}"


class Preference(models.Model):
    """A taste or aversion, on an ingredient, a cuisine, or in free text."""

    class Kind(models.TextChoices):
        LOVES = "loves", _("Loves")
        LIKES = "likes", _("Likes")
        DISLIKES = "dislikes", _("Dislikes")
        AVOIDS = "avoids", _("Never propose")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="preferences")
    # Null: the preference applies to the whole team.
    member = models.ForeignKey(
        Member, null=True, blank=True, on_delete=models.CASCADE, related_name="preferences"
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
    """A recipe as seen by one team: in its recipe book, or a candidate awaiting approval."""

    class Status(models.TextChoices):
        # Proposed by discovery or by the menu engine; the user has not accepted it yet.
        CANDIDATE = "candidate", _("Candidate")
        APPROVED = "approved", _("In the recipe book")
        REJECTED = "rejected", _("Rejected")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="recipe_book")
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
        constraints = [models.UniqueConstraint(fields=["team", "recipe"], name="unique_book_entry")]

    def __str__(self) -> str:
        return f"{self.team}: {self.recipe} ({self.status})"


class TeamEmbedding(models.Model):
    """A team profile's vector, for collaborative recommendation. One per embedding model.

    Undimensioned for the same reason as `recipes.RecipeEmbedding`.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="embeddings")
    model = models.CharField(max_length=200)
    vector = VectorField()
    content_hash = models.CharField(max_length=64)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "model"], name="unique_team_embedding")
        ]

    def __str__(self) -> str:
        return f"{self.team} [{self.model}]"
