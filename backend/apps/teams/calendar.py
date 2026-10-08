"""The team calendar: who eats at home day by day, and what is on the table.

A date follows the team's typical week unless a `CalendarDay` overrides some of its meals.
This is what menus are built from: a meal with 0 people is not planned. The dishes of a date
live in the week's menu (`menus.WeeklyMenu`), created when the first dish is set.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field

from django.db import transaction

from apps.recipes.models import Recipe

from .models import PLANNED_MEALS, CalendarDay, Meal, Team


@dataclass
class Dish:
    # None for a dish named by its title only (a new dish, "pizza out").
    recipe: int | None
    title: str
    course: str
    # Proposed by the menu generator and not accepted yet.
    proposed: bool = False
    note: str = ""


@dataclass(frozen=True)
class NewDish:
    """A dish to set by its title, without a recipe."""

    title: str
    course: str = ""


# What `set_day` takes for a meal's dishes: recipes, or dishes named by their title.
DishInput = Recipe | NewDish


@dataclass
class Day:
    date: dt.date
    # The typical week's day: whether the team usually eats together, and how many.
    active: bool
    usual: dict[str, int]
    # What applies on this date: the usual counts with the overrides on top.
    people: dict[str, int]
    overridden: list[str] = field(default_factory=list)
    note: str = ""
    # Planned meals only (breakfast is counted, not planned).
    dishes: dict[str, list[Dish]] = field(default_factory=dict)
    # Changes to the people proposed by the menu generator, with their reasons; the counts
    # above stay as they are until the user accepts.
    proposed_people: dict[str, int] = field(default_factory=dict)
    people_notes: dict[str, str] = field(default_factory=dict)


def _usual(team: Team, date: dt.date) -> dict[str, int]:
    return {meal: team.usual_people(date.weekday(), meal) for meal in Meal.values}


def calendar(team: Team, start: dt.date, days: int) -> list[Day]:
    """The `days` dates from `start`, each with the people expected and the dishes planned."""
    from apps.menus.models import MealSlot, SlotDish

    end = start + dt.timedelta(days=days - 1)
    exceptions = {
        row.date: row for row in CalendarDay.objects.filter(team=team, date__range=(start, end))
    }
    dishes: dict[tuple[dt.date, str], list[Dish]] = {}
    for slot_dish in (
        SlotDish.objects.filter(slot__menu__team=team, slot__date__range=(start, end))
        .select_related("slot", "recipe")
        .order_by("slot__date", "slot__meal", "position", "id")
    ):
        dishes.setdefault((slot_dish.slot.date, slot_dish.slot.meal), []).append(
            Dish(
                recipe=slot_dish.recipe_id,
                title=slot_dish.display_title,
                course=slot_dish.display_course,
                proposed=slot_dish.proposed,
                note=slot_dish.note,
            )
        )
    proposals: dict[dt.date, dict[str, tuple[int, str]]] = {}
    for slot in MealSlot.objects.filter(
        menu__team=team, date__range=(start, end), proposed_people__isnull=False
    ):
        proposals.setdefault(slot.date, {})[slot.meal] = (slot.proposed_people, slot.people_note)

    result = []
    for offset in range(days):
        date = start + dt.timedelta(days=offset)
        usual = _usual(team, date)
        exception = exceptions.get(date)
        overrides = {
            meal: count
            for meal, count in (exception.people if exception else {}).items()
            if meal in Meal.values
        }
        result.append(
            Day(
                date=date,
                active=bool(team.typical_week[date.weekday()].get("active", True)),
                usual=usual,
                people={**usual, **overrides},
                overridden=[meal for meal in Meal.values if meal in overrides],
                note=exception.note if exception else "",
                dishes={meal: dishes.get((date, meal), []) for meal in PLANNED_MEALS},
                proposed_people={m: n for m, (n, _) in proposals.get(date, {}).items()},
                people_notes={m: note for m, (_, note) in proposals.get(date, {}).items() if note},
            )
        )
    return result


@transaction.atomic
def set_day(
    team: Team,
    date: dt.date,
    people: dict[str, int] | None = None,
    note: str | None = None,
    dishes: dict[str, list[DishInput]] | None = None,
) -> Day:
    """Change a date: people at the given meals (the others keep their value), the note
    (None keeps it), the dishes of the given planned meals. Returns the resulting day.

    Setting the people of a meal settles any change the generator proposed for it. Dishes kept
    from before keep whether they are still a proposal; new ones are the user's."""
    current = calendar(team, date, 1)[0]
    usual = current.usual
    merged = {**current.people, **(people or {})}
    overrides = {meal: count for meal, count in merged.items() if count != usual[meal]}
    note = current.note if note is None else note
    if overrides or note:
        CalendarDay.objects.update_or_create(
            team=team, date=date, defaults={"people": overrides, "note": note}
        )
    else:
        CalendarDay.objects.filter(team=team, date=date).delete()
    _sync_menu(team, date, merged, dishes or {}, frozenset(people or {}))
    return calendar(team, date, 1)[0]


def _dish_key(dish) -> tuple:
    if isinstance(dish, Recipe):
        return ("recipe", dish.pk)
    if isinstance(dish, NewDish):
        return ("title", dish.title.casefold())
    return ("recipe", dish.recipe_id) if dish.recipe_id else ("title", dish.title.casefold())


def _sync_menu(
    team: Team,
    date: dt.date,
    people: dict[str, int],
    dishes: dict[str, list[DishInput]],
    settled: frozenset[str] = frozenset(),
) -> None:
    """Keep the week's menu in step with the calendar: slot counts, and the dishes given.
    `settled`: meals whose people the user set, which drops the generator's proposal."""
    from apps.menus.models import MealSlot, SlotDish, WeeklyMenu

    for meal in PLANNED_MEALS:
        changes = {"people": people[meal]}
        if meal in settled:
            changes |= {"proposed_people": None, "people_note": ""}
        MealSlot.objects.filter(menu__team=team, date=date, meal=meal).update(**changes)
    if not dishes:
        return
    week_start = date - dt.timedelta(days=date.weekday())
    menu, created = WeeklyMenu.objects.get_or_create(team=team, week_start=week_start)
    if created:
        menu.create_empty_slots()
    for meal, wanted in dishes.items():
        slot = menu.slots.get(date=date, meal=meal)
        before = {_dish_key(dish): dish for dish in slot.slot_dishes.all()}
        unique = {_dish_key(dish): dish for dish in wanted}
        slot.slot_dishes.all().delete()
        rows = []
        for index, (key, dish) in enumerate(unique.items()):
            kept = before.get(key)
            row = SlotDish(slot=slot, position=index, proposed=bool(kept and kept.proposed))
            if kept:
                row.note = kept.note
            if isinstance(dish, Recipe):
                row.recipe = dish
            else:
                row.title, row.course = dish.title, dish.course
            rows.append(row)
        SlotDish.objects.bulk_create(rows)
