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
    id: int
    title: str
    course: str


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


def _usual(team: Team, date: dt.date) -> dict[str, int]:
    return {meal: team.usual_people(date.weekday(), meal) for meal in Meal.values}


def calendar(team: Team, start: dt.date, days: int) -> list[Day]:
    """The `days` dates from `start`, each with the people expected and the dishes planned."""
    from apps.menus.models import SlotDish

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
        recipe = slot_dish.recipe
        dishes.setdefault((slot_dish.slot.date, slot_dish.slot.meal), []).append(
            Dish(id=recipe.pk, title=recipe.title, course=recipe.course)
        )

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
            )
        )
    return result


@transaction.atomic
def set_day(
    team: Team,
    date: dt.date,
    people: dict[str, int] | None = None,
    note: str | None = None,
    dishes: dict[str, list[Recipe]] | None = None,
) -> Day:
    """Change a date: people at the given meals (the others keep their value), the note
    (None keeps it), the dishes of the given planned meals. Returns the resulting day."""
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
    _sync_menu(team, date, merged, dishes or {})
    return calendar(team, date, 1)[0]


def _sync_menu(
    team: Team, date: dt.date, people: dict[str, int], dishes: dict[str, list[Recipe]]
) -> None:
    """Keep the week's menu in step with the calendar: slot counts, and the dishes given."""
    from apps.menus.models import MealSlot, SlotDish, WeeklyMenu

    for meal in PLANNED_MEALS:
        MealSlot.objects.filter(menu__team=team, date=date, meal=meal).update(people=people[meal])
    if not dishes:
        return
    week_start = date - dt.timedelta(days=date.weekday())
    menu, created = WeeklyMenu.objects.get_or_create(team=team, week_start=week_start)
    if created:
        menu.create_empty_slots()
    for meal, recipes in dishes.items():
        slot = menu.slots.get(date=date, meal=meal)
        slot.slot_dishes.all().delete()
        SlotDish.objects.bulk_create(
            SlotDish(slot=slot, recipe=recipe, position=index)
            for index, recipe in enumerate(dict.fromkeys(recipes))
        )
