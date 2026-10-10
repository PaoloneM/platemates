"""System ingredients, and those a team adds for itself."""

import importlib

import pytest
from django.apps import apps
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.matching import match_ingredient
from apps.catalog.models import Ingredient, IngredientCategory
from apps.recipes.models import Recipe, RecipeIngredient
from apps.teams.models import Membership, Team


@pytest.fixture
def neighbours(db):
    """Another team, with its own user and an ingredient of its own."""
    user = get_user_model().objects.create_user("bea")
    team = Team.objects.create(name="Famiglia Bianchi")
    Membership.objects.create(user=user, team=team, role=Membership.Role.OWNER)
    client = APIClient()
    client.force_authenticate(user)
    own = Ingredient.objects.create(name="cavolo nero di casa", owner_team=team)
    return team, client, own


@pytest.fixture
def tomato(db):
    return Ingredient.objects.create(name="pomodoro", aliases=["pomodori"])


def names(client, query=""):
    response = client.get(f"/api/ingredients/?{query}")
    assert response.status_code == 200, response.json()
    return [i["name"] for i in response.json()["results"]]


def line(ingredient):
    return {"ingredient": ingredient.pk, "quantity": "100", "unit": "g", "position": 0}


def recipe(team, *ingredients, **extra):
    return {
        "team": team.pk,
        "title": "Zuppa",
        "servings": 2,
        "visibility": "shared",
        "ingredients": [line(i) for i in ingredients],
        **extra,
    }


# -- adding and seeing -------------------------------------------------------------------------


def test_a_team_adds_ingredients_for_itself(api, team, tomato):
    created = api.post("/api/ingredients/", {"team": team.pk, "name": "Zucca"}, format="json")
    assert created.status_code == 201, created.json()
    assert created.json()["team"] == team.pk
    assert created.json()["team_name"] == "Test team"
    assert Ingredient.objects.get(name="zucca").owner_team == team


def test_only_staff_add_system_ingredients(api, user, team):
    assert api.post("/api/ingredients/", {"name": "zucca"}, format="json").status_code == 403
    system = {"team": Team.system().pk, "name": "zucca"}
    assert api.post("/api/ingredients/", system, format="json").status_code == 403
    user.is_staff = True
    user.save()
    # The system team's ingredient is a system ingredient.
    assert api.post("/api/ingredients/", system, format="json").json()["team"] is None


def test_an_ingredient_is_added_to_one_of_your_teams(api, team, neighbours):
    other = {"team": neighbours[0].pk, "name": "zucca"}
    assert api.post("/api/ingredients/", other, format="json").status_code == 400


def test_a_team_sees_system_ingredients_and_its_own(api, user, team, tomato, neighbours):
    Ingredient.objects.create(name="zucca", owner_team=team)
    assert names(api) == ["pomodoro", "zucca"]
    assert names(neighbours[1]) == ["cavolo nero di casa", "pomodoro"]
    assert api.get(f"/api/ingredients/{neighbours[2].pk}/").status_code == 404
    # Staff see every team's additions in Manage, and pick only what a team can use.
    user.is_staff = True
    user.save()
    assert names(api, "owner=teams") == ["cavolo nero di casa", "zucca"]
    assert names(api, "owner=system") == ["pomodoro"]
    assert names(api, f"team={team.pk}") == ["pomodoro", "zucca"]
    assert names(api, f"team={Team.system().pk}") == ["pomodoro"]


def test_a_name_is_unique_among_what_a_team_can_use(api, team, tomato, neighbours):
    for name in ("pomodoro", "Pomodori"):
        body = {"team": team.pk, "name": name}
        assert api.post("/api/ingredients/", body, format="json").status_code == 400
    # Two teams may each add theirs.
    body = {"team": team.pk, "name": "cavolo nero di casa"}
    assert api.post("/api/ingredients/", body, format="json").status_code == 201


# -- changing ----------------------------------------------------------------------------------


def test_members_change_their_own_ingredients_staff_the_system_ones(
    api, user, team, tomato, neighbours
):
    own = Ingredient.objects.create(name="zucca", owner_team=team)
    change = {"category": IngredientCategory.VEGETABLE}
    assert api.patch(f"/api/ingredients/{own.pk}/", change, format="json").status_code == 200
    assert api.patch(f"/api/ingredients/{tomato.pk}/", change, format="json").status_code == 403
    theirs = f"/api/ingredients/{neighbours[2].pk}/"
    assert api.patch(theirs, change, format="json").status_code == 404
    assert api.delete(f"/api/ingredients/{own.pk}/").status_code == 204
    # An edit never moves an ingredient between teams or into the system catalog.
    moved = api.patch(f"/api/ingredients/{neighbours[2].pk}/", {"team": None}, format="json")
    assert moved.status_code == 404
    user.is_staff = True
    user.save()
    api.patch(theirs, {"team": None}, format="json")
    assert Ingredient.objects.get(pk=neighbours[2].pk).owner_team == neighbours[0]


# -- recipes and preferences -------------------------------------------------------------------


def test_recipes_use_system_ingredients_and_the_team_own(api, team, tomato, neighbours):
    own = Ingredient.objects.create(name="zucca", owner_team=team)
    assert api.post("/api/recipes/", recipe(team, tomato, own), format="json").status_code == 201
    theirs = recipe(team, neighbours[2])
    assert api.post("/api/recipes/", theirs, format="json").status_code == 400


def test_a_version_keeps_the_original_team_ingredients(api, team, neighbours):
    other, _client, own = neighbours
    original = Recipe.objects.create(title="Ribollita", owner_team=other)
    RecipeIngredient.objects.create(recipe=original, ingredient=own, quantity=200, unit="g")
    version = recipe(team, own, derived_from=original.pk)
    response = api.post("/api/recipes/", version, format="json")
    assert response.status_code == 201, response.json()
    # Shown by name in the recipe, though the team cannot pick it elsewhere.
    assert response.json()["ingredients"][0]["ingredient_name"] == "cavolo nero di casa"
    edited = {"ingredients": [line(own)], "title": "Ribollita nostra"}
    url = f"/api/recipes/{response.json()['id']}/"
    assert api.patch(url, edited, format="json").status_code == 200


def test_system_recipes_use_system_ingredients_only(api, user, team, tomato):
    user.is_staff = True
    user.save()
    system = Team.system()
    assert api.post("/api/recipes/", recipe(system, tomato), format="json").status_code == 201
    own = Ingredient.objects.create(name="zucca", owner_team=team)
    assert api.post("/api/recipes/", recipe(system, own), format="json").status_code == 400


def test_preferences_use_system_ingredients_and_the_team_own(api, team, tomato, neighbours):
    def prefer(ingredient):
        body = {"team": team.pk, "kind": "avoids", "ingredient": ingredient.pk}
        return api.post("/api/preferences/", body, format="json").status_code

    assert prefer(tomato) == 201
    assert prefer(neighbours[2]) == 400


# -- matching drafts ---------------------------------------------------------------------------


def test_matching_looks_at_what_the_team_can_use(team, tomato, neighbours):
    own = Ingredient.objects.create(name="zucca", owner_team=team)
    assert match_ingredient("zucca", team)["match"] == own.pk
    assert match_ingredient("zucca")["match"] is None  # system recipes: system ones only
    assert match_ingredient("cavolo nero di casa", team)["candidates"] == []


def test_matching_prefers_system_ingredients(team, tomato):
    Ingredient.objects.create(name="pomodoro ramato", aliases=["pomodori"], owner_team=team)
    assert match_ingredient("pomodori", team)["match"] == tomato.pk


def test_matching_is_close_to_aliases_too(db):
    lentil = Ingredient.objects.create(name="lenticchia", aliases=["lenticchie secche"])
    assert match_ingredient("lenticchie secca")["match"] == lentil.pk


# -- promoting and merging ---------------------------------------------------------------------


def test_staff_promote_a_team_ingredient(api, user, tomato, neighbours):
    _other, _client, own = neighbours
    own.aliases = ["pomodori", "cavolo di casa"]
    own.save()
    url = f"/api/ingredients/{own.pk}/promote/"
    assert api.post(url).status_code == 403
    user.is_staff = True
    user.save()
    promoted = api.post(url).json()
    assert promoted["team"] is None
    # An alias a system ingredient holds stays that ingredient's.
    assert promoted["aliases"] == ["cavolo di casa"]


def test_promoting_a_name_the_system_has_asks_to_merge(api, user, tomato, neighbours):
    user.is_staff = True
    user.save()
    clash = Ingredient.objects.create(name="pomodoro", owner_team=neighbours[0])
    response = api.post(f"/api/ingredients/{clash.pk}/promote/")
    assert response.status_code == 409
    assert response.json()["into"] == tomato.pk


def test_staff_merge_a_team_ingredient_into_a_system_one(api, user, team, tomato, neighbours):
    other, _client, own = neighbours
    soup = Recipe.objects.create(title="Ribollita", owner_team=other)
    RecipeIngredient.objects.create(recipe=soup, ingredient=own, quantity=200, unit="g")
    user.is_staff = True
    user.save()
    elsewhere = Ingredient.objects.create(name="zucca", owner_team=team)
    url = f"/api/ingredients/{own.pk}/merge/"
    assert api.post(url, {"into": elsewhere.pk}, format="json").status_code == 400
    assert api.post(url, {"into": tomato.pk}, format="json").status_code == 200
    assert soup.ingredients.get().ingredient == tomato
    assert "cavolo nero di casa" in Ingredient.objects.get(pk=tomato.pk).aliases


# -- the seed fix ------------------------------------------------------------------------------


def test_the_skipped_base_ingredients_are_restored(db):
    restore = importlib.import_module(
        "apps.catalog.migrations.0007_restore_base_ingredients"
    ).restore
    variant = Ingredient.objects.create(name="lenticchie secche", aliases=["lenticchia"])
    restore(apps, None)
    restore(apps, None)  # idempotent
    lentil = Ingredient.objects.get(name="lenticchia", owner_team=None)
    # The variant stays itself; the base name is no longer its alias.
    assert lentil.aliases == ["lenticchie"]
    assert Ingredient.objects.get(pk=variant.pk).aliases == []
    assert set(Ingredient.objects.values_list("name", flat=True)) >= {"yogurt", "paprika"}
