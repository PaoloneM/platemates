import importlib
from decimal import Decimal

import pytest
from django.apps import apps as django_apps

from apps.catalog.models import Ingredient
from apps.recipes.models import Recipe
from apps.teams.models import Preference

seed_migration = importlib.import_module("apps.catalog.migrations.0005_seed_common_ingredients")


@pytest.fixture
def staff(api, user):
    user.is_staff = True
    user.save()
    return api


def recipe_with(team, title, *lines):
    recipe = Recipe.objects.create(title=title, owner_team=team)
    for ingredient, quantity, unit in lines:
        recipe.ingredients.create(ingredient=ingredient, quantity=quantity, unit=unit)
    return recipe


# -- seed -------------------------------------------------------------------------------------


@pytest.mark.seeded
def test_common_ingredients_are_seeded(db):
    zucchina = Ingredient.objects.get(name="zucchina")
    assert zucchina.category == "vegetable" and zucchina.season_months == [5, 6, 7, 8, 9]
    assert "zucchine" in zucchina.aliases
    # Preserved forms are distinct from the fresh product, with no season.
    assert Ingredient.objects.get(name="pomodoro pelato").season_months == []
    assert Ingredient.objects.count() >= 150


@pytest.mark.seeded
def test_seeding_again_changes_nothing(db):
    Ingredient.objects.filter(name="zucchina").update(category="other")
    before = Ingredient.objects.count()
    seed_migration.seed(django_apps, None)
    assert Ingredient.objects.count() == before
    assert Ingredient.objects.get(name="zucchina").category == "other"  # user edit kept


# -- listing ----------------------------------------------------------------------------------


def test_usage_counts_filters_and_ordering(staff, team):
    tomato = Ingredient.objects.create(name="pomodoro", category="vegetable")
    Ingredient.objects.create(name="sale", category="condiment")
    recipe_with(team, "A", (tomato, 100, "g"))
    recipe_with(team, "B", (tomato, 100, "g"))
    rows = staff.get("/api/ingredients/?ordering=-usage").json()["results"]
    assert [(r["name"], r["usage_count"]) for r in rows] == [("pomodoro", 2), ("sale", 0)]
    only = staff.get("/api/ingredients/?category=condiment").json()["results"]
    assert [r["name"] for r in only] == ["sale"]


# -- editing ----------------------------------------------------------------------------------


def test_only_staff_can_change_merge_or_delete(api, team):
    a = Ingredient.objects.create(name="pomodori")
    b = Ingredient.objects.create(name="pomodoro")
    assert (
        api.patch(f"/api/ingredients/{a.pk}/", {"category": "fruit"}, format="json").status_code
        == 403
    )
    assert (
        api.post(f"/api/ingredients/{a.pk}/merge/", {"into": b.pk}, format="json").status_code
        == 403
    )
    assert api.delete(f"/api/ingredients/{a.pk}/").status_code == 403


def test_names_clashing_with_an_alias_are_refused(staff):
    Ingredient.objects.create(name="pomodoro", aliases=["pomodori"])
    response = staff.post("/api/ingredients/", {"name": "Pomodori"}, format="json")
    assert response.status_code == 400


def test_changing_a_season_updates_the_recipes(staff, team):
    leek = Ingredient.objects.create(name="porro")
    soup = recipe_with(team, "Vellutata", (leek, 300, "g"))
    soup.propose("season_months", soup.derive_season_months(), "derived")
    soup.save()
    staff.patch(
        f"/api/ingredients/{leek.pk}/", {"season_months": {"seasons": ["winter"]}}, format="json"
    )
    soup.refresh_from_db()
    assert soup.season_months == [1, 2, 12]


def test_used_ingredients_cannot_be_deleted(staff, team):
    tomato = Ingredient.objects.create(name="pomodoro")
    unused = Ingredient.objects.create(name="tamarindo")
    recipe_with(team, "Sugo", (tomato, 100, "g"))
    blocked = staff.delete(f"/api/ingredients/{tomato.pk}/")
    assert blocked.status_code == 409 and blocked.json()["recipes"] == ["Sugo"]
    assert staff.delete(f"/api/ingredients/{unused.pk}/").status_code == 204


# -- merging ----------------------------------------------------------------------------------


def test_merge_moves_recipes_and_keeps_the_name_as_alias(staff, team):
    dup = Ingredient.objects.create(name="pomodori", aliases=["pomodori maturi"])
    tomato = Ingredient.objects.create(name="pomodoro", season_months=[6, 7, 8])
    sugo = recipe_with(team, "Sugo", (dup, 200, "g"))
    both = recipe_with(team, "Doppio", (dup, 100, "g"), (tomato, 50, "g"))
    Preference.objects.create(team=team, kind="likes", ingredient=dup)

    response = staff.post(f"/api/ingredients/{dup.pk}/merge/", {"into": tomato.pk}, format="json")
    assert response.status_code == 200
    assert response.json()["moved"] == 1 and response.json()["combined"] == 1
    assert not Ingredient.objects.filter(pk=dup.pk).exists()
    tomato.refresh_from_db()
    assert set(tomato.aliases) == {"pomodori", "pomodori maturi"}
    assert sugo.ingredients.get().ingredient == tomato
    assert both.ingredients.get().quantity == Decimal("150")  # same unit: added up
    assert Preference.objects.get().ingredient == tomato
    sugo.refresh_from_db()
    assert sugo.season_months == [6, 7, 8]  # follows the target's season now


def test_cannot_merge_into_itself(staff):
    a = Ingredient.objects.create(name="pomodoro")
    assert (
        staff.post(f"/api/ingredients/{a.pk}/merge/", {"into": a.pk}, format="json").status_code
        == 400
    )
