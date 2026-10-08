"""Weekly menus: 7 days x {lunch, dinner}, each slot with its own number of diners.

Each slot also records what actually happened (the implicit feedback signal), which together with
optional ratings feeds the RAG context of future generations.
"""

from __future__ import annotations

from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.recipes.models import Recipe
from apps.teams.calendar import calendar
from apps.teams.models import PLANNED_MEALS, Meal, Team


class SystemRule(models.Model):
    """A rule every team's menus follow, in natural language; shown to teams read-only.

    Rules guide the LLM on three levels: system, team (`TeamRule`) and week
    (`WeeklyMenu.instructions`), the later winning where they conflict. They are guidance:
    what must hold whatever the text says (meals with nobody at home are not planned, "never
    propose" preferences are excluded, dishes already set stay) is enforced by code.

    Kept in the database so staff can change them live from the management section. The rules
    the app ships with are seeded by a data migration and carry a stable `code`; seeding never
    overwrites them, and they are switched off rather than deleted. Rules added by staff have
    no code.
    """

    code = models.SlugField(max_length=40, unique=True, null=True, blank=True, editable=False)
    text_it = models.CharField(max_length=300)
    text_en = models.CharField(max_length=300)
    position = models.PositiveSmallIntegerField(default=0)
    active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self) -> str:
        return self.text_en


class TeamRule(models.Model):
    """One of the team's standing rules for planning its weeks, in natural language
    ("fish at least twice", "pizza on friday evening"). See `SystemRule`."""

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="rules")
    text = models.CharField(max_length=300)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["team", "created_at", "id"]

    def __str__(self) -> str:
        return self.text


class WeeklyMenu(models.Model):
    class Status(models.TextChoices):
        DRAFT = "draft", _("Draft")
        APPROVED = "approved", _("Approved")
        ARCHIVED = "archived", _("Archived")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="menus")
    # Always a Monday.
    week_start = models.DateField()
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    # The LLM's explanation of its choices, shown to the user and kept for later context.
    rationale = models.TextField(blank=True)
    # How to plan this week: free text on top of the system and team rules, which wins where
    # they conflict. It may also change the people ("thursday dinner we are five").
    instructions = models.TextField(blank=True)
    # False leaves out every team rule, including those added later; otherwise only the
    # excluded ones are left out.
    use_team_rules = models.BooleanField(default=True)
    excluded_rules = models.ManyToManyField(TeamRule, blank=True, related_name="excluded_from")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-week_start"]
        constraints = [
            models.UniqueConstraint(fields=["team", "week_start"], name="unique_team_week")
        ]

    def __str__(self) -> str:
        return f"{self.team} - week of {self.week_start}"

    def clean(self) -> None:
        if self.week_start and self.week_start.weekday() != 0:
            raise ValidationError({"week_start": "A week starts on Monday."})

    def create_empty_slots(self) -> list[MealSlot]:
        """Create the 14 planned slots, prefilled from the team calendar (typical week and
        the exceptions on these dates)."""
        slots = [
            MealSlot(menu=self, date=day.date, meal=meal, people=day.people[meal])
            for day in calendar(self.team, self.week_start, 7)
            for meal in PLANNED_MEALS
        ]
        return MealSlot.objects.bulk_create(slots)


class MealSlot(models.Model):
    class Outcome(models.TextChoices):
        PLANNED = "planned", _("Planned")
        FOLLOWED = "followed", _("Eaten as planned")
        REPLACED = "replaced", _("Ate something else")
        SKIPPED = "skipped", _("Skipped")

    menu = models.ForeignKey(WeeklyMenu, on_delete=models.CASCADE, related_name="slots")
    date = models.DateField()
    meal = models.CharField(max_length=10, choices=Meal.choices)
    # Diners for this occasion. 0 means nobody eats at home: the slot generates no shopping.
    people = models.PositiveSmallIntegerField(default=0)
    dishes = models.ManyToManyField(Recipe, through="SlotDish", related_name="slots", blank=True)

    # Implicit feedback.
    outcome = models.CharField(max_length=10, choices=Outcome.choices, default=Outcome.PLANNED)
    eaten_instead = models.ManyToManyField(Recipe, blank=True, related_name="eaten_instead_in")
    eaten_instead_note = models.CharField(max_length=200, blank=True)
    # Explicit, optional feedback on the meal as a whole.
    rating = models.PositiveSmallIntegerField(
        null=True, blank=True, validators=[MinValueValidator(1), MaxValueValidator(5)]
    )
    comment = models.TextField(blank=True)

    class Meta:
        ordering = ["date", "meal"]
        constraints = [
            models.UniqueConstraint(fields=["menu", "date", "meal"], name="unique_menu_slot")
        ]

    def __str__(self) -> str:
        return f"{self.date} {self.meal} ({self.people})"


class SlotDish(models.Model):
    """A dish served at a slot. Usually one; several when a meal has more courses."""

    slot = models.ForeignKey(MealSlot, on_delete=models.CASCADE, related_name="slot_dishes")
    recipe = models.ForeignKey(Recipe, on_delete=models.PROTECT, related_name="slot_dishes")
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["slot", "position", "id"]
        verbose_name_plural = "slot dishes"
        constraints = [models.UniqueConstraint(fields=["slot", "recipe"], name="unique_slot_dish")]

    def __str__(self) -> str:
        return f"{self.slot}: {self.recipe}"
