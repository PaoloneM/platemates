"""Shopping lists: computed from a week's menu, then stored as a list the team ticks off.

`build_shopping_list` computes what a menu needs: quantities scaled to each slot's actual
diners, summed per (ingredient, unit), in aisle order by ingredient category; `for_slots` does
the same for a day or a meal, `for_recipe` for one recipe and a number of people. `snapshot`
(a week) and `store` keep the result as a `ShoppingList`, a picture of the menu at that moment:
changing the menu afterwards does not change the list. Only a week's list is linked to its
menu: a list for a day, a meal or a recipe leaves the week among those to prepare. `merge`
joins lists into one. `weeks_to_prepare` lists the weeks that have something to buy and no
list yet.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.catalog.models import Unit, normalize_name

from .models import MealSlot, ShoppingItem, ShoppingList, SlotDish, WeeklyMenu


@dataclass
class NeededIngredient:
    ingredient_id: int
    name: str
    category: str
    unit: str
    # None when only "to taste" amounts are involved.
    quantity: Decimal | None = None
    # Dates the ingredient is needed on, so the user can split the shopping.
    needed_on: set[str] = field(default_factory=set)
    # Every recipe line asking for it is optional.
    optional: bool = True

    def as_dict(self) -> dict[str, object]:
        return {
            "ingredient_id": self.ingredient_id,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "quantity": None if self.quantity is None else str(_round(self.quantity, self.unit)),
            "needed_on": sorted(self.needed_on),
            "optional": self.optional,
        }


def _countable_dishes():
    """The dishes that need shopping: accepted (proposals count once accepted), with a recipe
    (a dish name alone has no ingredients), in a slot where somebody eats and was not skipped."""
    return SlotDish.objects.filter(
        slot__people__gt=0, recipe__isnull=False, proposed=False
    ).exclude(slot__outcome=MealSlot.Outcome.SKIPPED)


def _needed(portions) -> list[NeededIngredient]:
    """What `portions` need: (recipe, people, date or None) each, summed per (ingredient, unit),
    in aisle order."""
    items: dict[tuple[int, str], NeededIngredient] = {}
    for recipe, people, date in portions:
        for line in recipe.ingredients.all():
            unit = Unit.TO_TASTE if line.quantity is None else line.unit
            key = (line.ingredient_id, unit)
            item = items.get(key)
            if item is None:
                item = items[key] = NeededIngredient(
                    ingredient_id=line.ingredient_id,
                    name=line.ingredient.name,
                    category=line.ingredient.category,
                    unit=unit,
                )
            amount = line.scaled_quantity(people)
            if amount is not None:
                item.quantity = (item.quantity or Decimal(0)) + amount
            if date is not None:
                item.needed_on.add(date.isoformat())
            item.optional = item.optional and line.optional
    return sorted(items.values(), key=lambda i: (i.category, i.name, i.unit))


def _for_dishes(dishes) -> list[NeededIngredient]:
    dishes = dishes.select_related("slot", "recipe").prefetch_related(
        "recipe__ingredients__ingredient"
    )
    return _needed((dish.recipe, dish.slot.people, dish.slot.date) for dish in dishes)


def build_shopping_list(menu: WeeklyMenu) -> list[NeededIngredient]:
    return _for_dishes(_countable_dishes().filter(slot__menu=menu))


def for_slots(slots) -> list[NeededIngredient]:
    """What some meals need: a day's, or one meal's."""
    return _for_dishes(_countable_dishes().filter(slot__in=slots))


def for_recipe(recipe, people: int) -> list[NeededIngredient]:
    """What one recipe needs for `people`, outside any menu."""
    return _needed([(recipe, people, None)])


def group_by_category(items: list[NeededIngredient]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item.as_dict())
    return dict(grouped)


def _round(quantity: Decimal, unit: str) -> Decimal:
    # Pieces round up to whole units in practice, but showing 1.5 eggs is more honest than
    # silently buying a different amount: keep one decimal for pieces, whole numbers otherwise.
    step = Decimal("0.1") if unit == Unit.PIECE else Decimal("1")
    return quantity.quantize(step, rounding=ROUND_HALF_UP)


# -- stored lists -------------------------------------------------------------------------------


def week_title(menus) -> str:
    """ "12/10 - 18/10": the days the list covers, from its first week's Monday to its last
    week's Sunday."""
    starts = sorted(m.week_start for m in menus)
    if not starts:
        return ""
    first, last = starts[0], starts[-1] + dt.timedelta(days=6)
    return f"{first:%d/%m} - {last:%d/%m}"


def weeks_to_prepare(team, today: dt.date | None = None):
    """The team's menus from the current week on with something to buy and no list yet."""
    today = today or timezone.localdate()
    monday = today - dt.timedelta(days=today.weekday())
    return (
        WeeklyMenu.objects.filter(team=team, week_start__gte=monday, shopping_lists__isnull=True)
        .filter(Exists(_countable_dishes().filter(slot__menu=OuterRef("pk"))))
        .order_by("week_start")
    )


def snapshot(menu: WeeklyMenu, user=None) -> ShoppingList:
    """A new list with what the week's menu needs now. Every call makes a new list."""
    return store(menu.team, week_title([menu]), build_shopping_list(menu), [menu], user)


@transaction.atomic
def store(team, title: str, needed: list[NeededIngredient], menus=(), user=None) -> ShoppingList:
    """A new list with these items. `menus`: the weeks it covers whole (a week's list)."""
    shopping_list = ShoppingList.objects.create(team=team, title=title[:120], created_by=user)
    shopping_list.menus.add(*menus)
    ShoppingItem.objects.bulk_create(
        ShoppingItem(
            shopping_list=shopping_list,
            ingredient_id=item.ingredient_id,
            name=item.name,
            category=item.category,
            unit=item.unit,
            quantity=None if item.quantity is None else _round(item.quantity, item.unit),
            optional=item.optional,
            needed_on=sorted(dt.date.fromisoformat(d) for d in item.needed_on),
            position=position,
        )
        for position, item in enumerate(needed)
    )
    return shopping_list


def _merge_key(item: ShoppingItem) -> tuple:
    who = (
        ("ingredient", item.ingredient_id)
        if item.ingredient_id
        else ("name", normalize_name(item.name))
    )
    return (*who, item.unit)


@transaction.atomic
def merge(lists: list[ShoppingList], user=None) -> ShoppingList:
    """One list from several of the same team, which are deleted. Items of the same ingredient
    (or, without one, the same name) in the same unit are summed; an item is bought only if it
    was bought in every list it came from."""
    team = lists[0].team
    menus = WeeklyMenu.objects.filter(shopping_lists__in=lists).distinct()
    # Weeks only: their dates. With a day's, a meal's or a recipe's list: the titles joined.
    weeks_only = all(sl.menus.exists() for sl in lists)
    title = week_title(menus) if weeks_only else " + ".join(sl.title for sl in lists)
    merged = ShoppingList.objects.create(team=team, title=title[:120], created_by=user)
    merged.menus.set(menus)

    combined: dict[tuple, ShoppingItem] = {}
    sources = ShoppingItem.objects.filter(shopping_list__in=lists).order_by(
        "shopping_list__created_at", "position", "pk"
    )
    for item in sources:
        key = _merge_key(item)
        into = combined.get(key)
        if into is None:
            combined[key] = ShoppingItem(
                shopping_list=merged,
                ingredient_id=item.ingredient_id,
                name=item.name,
                category=item.category,
                unit=item.unit,
                quantity=item.quantity,
                optional=item.optional,
                needed_on=list(item.needed_on),
                note=item.note,
                manual=item.manual,
                bought=item.bought,
                bought_at=item.bought_at,
                bought_by_id=item.bought_by_id,
                position=len(combined),
            )
            continue
        if item.quantity is not None:
            into.quantity = (into.quantity or Decimal(0)) + item.quantity
        into.optional = into.optional and item.optional
        into.needed_on = sorted(set(into.needed_on) | set(item.needed_on))
        into.note = "; ".join(n for n in dict.fromkeys([into.note, item.note]) if n)
        into.manual = into.manual and item.manual
        if into.bought and not item.bought:
            into.bought, into.bought_at, into.bought_by_id = False, None, None
    ShoppingItem.objects.bulk_create(combined.values())
    ShoppingList.objects.filter(pk__in=[sl.pk for sl in lists]).delete()
    return merged
