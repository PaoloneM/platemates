"""Shopping list: a pure output computed from a menu, never stored.

Quantities are scaled to each slot's actual diners, summed per (ingredient, unit), and grouped by
ingredient category so the list follows the supermarket aisles.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal

from apps.catalog.models import Unit

from .models import MealSlot, SlotDish, WeeklyMenu


@dataclass
class ShoppingItem:
    ingredient_id: int
    name: str
    category: str
    unit: str
    # None when only "to taste" amounts are involved.
    quantity: Decimal | None = None
    # Dates the ingredient is needed on, so the user can split the shopping.
    needed_on: set[str] = field(default_factory=set)

    def as_dict(self) -> dict[str, object]:
        return {
            "ingredient_id": self.ingredient_id,
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "quantity": None if self.quantity is None else str(_round(self.quantity, self.unit)),
            "needed_on": sorted(self.needed_on),
        }


def build_shopping_list(menu: WeeklyMenu) -> list[ShoppingItem]:
    dishes = (
        SlotDish.objects.filter(slot__menu=menu, slot__people__gt=0)
        .exclude(slot__outcome=MealSlot.Outcome.SKIPPED)
        .select_related("slot", "recipe")
        .prefetch_related("recipe__ingredients__ingredient")
    )

    items: dict[tuple[int, str], ShoppingItem] = {}
    for dish in dishes:
        for line in dish.recipe.ingredients.all():
            unit = Unit.TO_TASTE if line.quantity is None else line.unit
            key = (line.ingredient_id, unit)
            item = items.get(key)
            if item is None:
                item = items[key] = ShoppingItem(
                    ingredient_id=line.ingredient_id,
                    name=line.ingredient.name,
                    category=line.ingredient.category,
                    unit=unit,
                )
            amount = line.scaled_quantity(dish.slot.people)
            if amount is not None:
                item.quantity = (item.quantity or Decimal(0)) + amount
            item.needed_on.add(dish.slot.date.isoformat())

    return sorted(items.values(), key=lambda i: (i.category, i.name, i.unit))


def group_by_category(items: list[ShoppingItem]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for item in items:
        grouped[item.category].append(item.as_dict())
    return dict(grouped)


def _round(quantity: Decimal, unit: str) -> Decimal:
    # Pieces round up to whole units in practice, but showing 1.5 eggs is more honest than
    # silently buying a different amount: keep one decimal for pieces, whole numbers otherwise.
    step = Decimal("0.1") if unit == Unit.PIECE else Decimal("1")
    return quantity.quantize(step, rounding=ROUND_HALF_UP)
