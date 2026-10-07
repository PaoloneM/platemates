from decimal import Decimal

import pytest

from apps.catalog.models import Ingredient
from apps.core.provenance import Source
from apps.core.seasons import (
    ALL_MONTHS,
    intersect_months,
    is_season_aligned,
    months_to_seasons,
    seasons_to_months,
)
from apps.menus.models import MealSlot, SlotDish, WeeklyMenu
from apps.menus.shopping import build_shopping_list
from tests.conftest import MONDAY


def test_empty_month_list_means_all_year():
    assert intersect_months([], None) == ALL_MONTHS
    assert intersect_months([1, 2, 3], [], [3, 4]) == {3}


def test_seasons_are_views_onto_months():
    assert seasons_to_months(["winter"]) == [1, 2, 12]
    assert months_to_seasons([12, 1, 2, 3]) == ["winter"]
    assert is_season_aligned([12, 1, 2])
    assert not is_season_aligned([12, 1, 2, 3])
    assert is_season_aligned([])


def test_ingredient_name_is_normalized(db):
    ingredient = Ingredient.objects.create(name="  Olive   OIL ", aliases=["Olio", "olive oil"])
    assert ingredient.name == "olive oil"
    assert ingredient.aliases == ["olio"]


def test_automatic_sources_never_override_the_user(db):
    ingredient = Ingredient.objects.create(name="pumpkin")
    assert ingredient.propose("season_months", [9, 10, 11], Source.LLM)
    ingredient.set_by_user("season_months", [10, 11])
    assert not ingredient.propose("season_months", [1], Source.LLM)
    assert ingredient.season_months == [10, 11]


def test_recipe_seasonality_is_derived_from_ingredients(pasta_recipe):
    assert pasta_recipe.derive_season_months() == [6, 7, 8, 9]
    pasta_recipe.season_months = pasta_recipe.derive_season_months()
    pasta_recipe.climate_months = [5, 6, 7]
    assert pasta_recipe.suitable_months() == {6, 7}


def test_quantities_scale_linearly(pasta_recipe):
    line = pasta_recipe.ingredients.get(ingredient__name="spaghetti")
    assert line.scaled_quantity(3) == Decimal("240")
    assert pasta_recipe.ingredients.get(ingredient__name="salt").scaled_quantity(3) is None


def test_new_menu_gets_fourteen_slots_with_team_defaults(team):
    team.default_people = {"lunch": 2, "dinner": 3}
    team.save()
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    menu.create_empty_slots()
    assert menu.slots.count() == 14
    assert {s.people for s in menu.slots.filter(meal="dinner")} == {3}


@pytest.fixture
def menu(team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    menu.create_empty_slots()
    return menu


def test_shopping_list_sums_scaled_quantities(menu, pasta_recipe):
    lunch, dinner = menu.slots.filter(date=MONDAY).order_by("meal")
    lunch.people, dinner.people = 2, 3
    lunch.save()
    dinner.save()
    for slot in (lunch, dinner):
        SlotDish.objects.create(slot=slot, recipe=pasta_recipe)

    items = {i.name: i for i in build_shopping_list(menu)}
    assert items["spaghetti"].quantity == Decimal("400")  # 160 + 240
    assert items["salt"].quantity is None
    assert items["tomato"].needed_on == {MONDAY.isoformat()}


def test_shopping_list_ignores_empty_and_skipped_slots(menu, pasta_recipe):
    empty, skipped = menu.slots.filter(date=MONDAY).order_by("meal")
    empty.people = 0
    empty.save()
    skipped.outcome = MealSlot.Outcome.SKIPPED
    skipped.save()
    for slot in (empty, skipped):
        SlotDish.objects.create(slot=slot, recipe=pasta_recipe)
    assert build_shopping_list(menu) == []
