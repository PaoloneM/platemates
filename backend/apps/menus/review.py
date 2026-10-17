"""The user's review of a generated proposal: accept it or reject it, all or meal by meal.

Accepting makes the proposed dishes the user's own, and applies a proposed change of people to
the calendar through `set_day`, the one write path for a date. Rejecting deletes the proposed
dishes and drops the people change. Dishes the user chose are never touched.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from apps.teams.calendar import calendar, day_changed, day_summary, set_day

from .models import MealSlot, SlotDish, WeeklyMenu

# (date, meal); None means every meal of the week.
SlotKeys = list[tuple[dt.date, str]] | None


def _slots(menu: WeeklyMenu, keys: SlotKeys):
    slots = menu.slots.all()
    if keys is None:
        return slots
    wanted = {(date, meal) for date, meal in keys}
    return [slot for slot in slots if (slot.date, slot.meal) in wanted]


def _days_before(menu: WeeklyMenu, keys: SlotKeys) -> dict[dt.date, dict[str, object]]:
    """How the reviewed dates were, for the activity log and the team's browsers."""
    dates = sorted({slot.date for slot in _slots(menu, keys)})
    return {date: day_summary(calendar(menu.team, date, 1)[0]) for date in dates}


def _audit(menu: WeeklyMenu, before: dict[dt.date, dict[str, object]]) -> None:
    for date, summary in before.items():
        day_changed(menu.team, date, summary)


@transaction.atomic
def accept(menu: WeeklyMenu, keys: SlotKeys = None) -> None:
    before = _days_before(menu, keys)
    for slot in _slots(menu, keys):
        SlotDish.objects.filter(slot=slot, proposed=True).update(proposed=False)
        if slot.proposed_people is not None:
            set_day(menu.team, slot.date, people={slot.meal: slot.proposed_people})
    _audit(menu, before)


@transaction.atomic
def reject(menu: WeeklyMenu, keys: SlotKeys = None) -> None:
    before = _days_before(menu, keys)
    for slot in _slots(menu, keys):
        SlotDish.objects.filter(slot=slot, proposed=True).delete()
    MealSlot.objects.filter(pk__in=[s.pk for s in _slots(menu, keys)]).update(
        proposed_people=None, people_note=""
    )
    _audit(menu, before)
