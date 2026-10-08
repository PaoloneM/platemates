"""Weekly menus: 7 days x {lunch, dinner}, each slot with its own number of diners.

Each slot also records what actually happened (the implicit feedback signal), which together with
optional ratings feeds the RAG context of future generations.
"""

from __future__ import annotations

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.recipes.models import Course, Recipe
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
    # A change to the people proposed by the generator (from the week's instructions), with its
    # reason. Applied to the calendar only when the user accepts it; null when there is none.
    proposed_people = models.PositiveSmallIntegerField(null=True, blank=True)
    people_note = models.CharField(max_length=200, blank=True)
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
    """A dish served at a slot. Usually one; several when a meal has more courses.

    Either a recipe, or a dish named by its title only: a new dish the generator suggests (not
    in any recipe book yet), or one the user writes in ("pizza out"). A dish without a recipe
    adds nothing to the shopping list.
    """

    slot = models.ForeignKey(MealSlot, on_delete=models.CASCADE, related_name="slot_dishes")
    recipe = models.ForeignKey(
        Recipe, null=True, blank=True, on_delete=models.PROTECT, related_name="slot_dishes"
    )
    title = models.CharField(max_length=200, blank=True)
    course = models.CharField(max_length=10, choices=Course.choices, blank=True)
    # The generator's one-line description of a new dish, or why it chose this one.
    note = models.CharField(max_length=200, blank=True)
    # Proposed by the generator and not accepted yet. Accepting makes it a user decision;
    # rejecting deletes it; regenerating replaces only proposals.
    proposed = models.BooleanField(default=False)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        ordering = ["slot", "position", "id"]
        verbose_name_plural = "slot dishes"
        constraints = [
            models.UniqueConstraint(fields=["slot", "recipe"], name="unique_slot_dish"),
            models.CheckConstraint(
                condition=models.Q(recipe__isnull=False) | ~models.Q(title=""),
                name="slot_dish_has_recipe_or_title",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.slot}: {self.recipe or self.title}"

    @property
    def display_title(self) -> str:
        return self.recipe.title if self.recipe else self.title

    @property
    def display_course(self) -> str:
        return self.recipe.course if self.recipe else self.course


class MenuGeneration(models.Model):
    """One request to generate a week's menu, run in the background by `menu_worker`.

    Keeps a snapshot of the rules it used and what came back, so the user sees what a proposal
    was based on, and later generations can learn from the history.
    """

    class Status(models.TextChoices):
        QUEUED = "queued", _("Queued")
        RUNNING = "running", _("Running")
        DONE = "done", _("Done")
        FAILED = "failed", _("Failed")

    menu = models.ForeignKey(WeeklyMenu, on_delete=models.CASCADE, related_name="generations")
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # False: the standing rules only (system and team). True: the week's settings too.
    use_week_settings = models.BooleanField(default=False)
    # The language the proposal is written in (new dishes, notes, rationale).
    language = models.CharField(max_length=10, default="it")
    # Whether the model reasoned before answering (setting `menu.thinking` at the time).
    thinking = models.BooleanField(default=False)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.QUEUED)
    # {"system": [...], "team": [...], "week": "..."}: the rules as they were.
    rules = models.JSONField(default=dict, blank=True)
    # The model's answer once validated (see `apps/menus/generation.py`).
    result = models.JSONField(null=True, blank=True)
    error = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            # One generation at a time per week: a second request waits for the first.
            models.UniqueConstraint(
                fields=["menu"],
                condition=models.Q(status__in=["queued", "running"]),
                name="one_active_generation_per_menu",
            )
        ]

    def __str__(self) -> str:
        return f"{self.menu} ({self.status})"
