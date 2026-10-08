"""The user's review of a generated proposal: accept it or reject it, all or meal by meal.

Accepting makes the proposed dishes the user's own, and applies a proposed change of people to
the calendar through `set_day`, the one write path for a date. Rejecting deletes the proposed
dishes and drops the people change. Dishes the user chose are never touched.
"""

from __future__ import annotations

import datetime as dt

from django.db import transaction

from apps.teams.calendar import set_day

from .models import MealSlot, SlotDish, WeeklyMenu

# (date, meal); None means every meal of the week.
SlotKeys = list[tuple[dt.date, str]] | None


def _slots(menu: WeeklyMenu, keys: SlotKeys):
    slots = menu.slots.all()
    if keys is None:
        return slots
    wanted = {(date, meal) for date, meal in keys}
    return [slot for slot in slots if (slot.date, slot.meal) in wanted]


@transaction.atomic
def accept(menu: WeeklyMenu, keys: SlotKeys = None) -> None:
    for slot in _slots(menu, keys):
        SlotDish.objects.filter(slot=slot, proposed=True).update(proposed=False)
        if slot.proposed_people is not None:
            set_day(menu.team, slot.date, people={slot.meal: slot.proposed_people})


@transaction.atomic
def reject(menu: WeeklyMenu, keys: SlotKeys = None) -> None:
    for slot in _slots(menu, keys):
        SlotDish.objects.filter(slot=slot, proposed=True).delete()
    MealSlot.objects.filter(pk__in=[s.pk for s in _slots(menu, keys)]).update(
        proposed_people=None, people_note=""
    )
