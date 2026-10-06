import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Ingredient
from apps.families.models import Family, Membership, RecipeBookEntry
from apps.recipes.models import Recipe


@pytest.fixture
def tomato(db):
    return Ingredient.objects.create(name="tomato", season_months=[6, 7, 8, 9])


@pytest.fixture
def basil(db):
    return Ingredient.objects.create(name="basil", season_months=[5, 6, 7, 8])


@pytest.fixture
def other(db):
    """A second family with its own user."""
    user = get_user_model().objects.create_user("bob")
    family = Family.objects.create(name="Other")
    Membership.objects.create(user=user, family=family, role=Membership.Role.OWNER)
    client = APIClient()
    client.force_authenticate(user)
    return family, client


def payload(family, *lines, **extra):
    return {
        "family": family.pk,
        "title": "Pasta al pomodoro",
        "servings": 2,
        "steps": ["Boil the pasta.", "  ", "Add the sauce."],
        "ingredients": [{"ingredient": i.pk, "quantity": "100", "unit": "g"} for i in lines],
        **extra,
    }


def create(api, family, *lines, **extra):
    response = api.post("/api/recipes/", payload(family, *lines, **extra), format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_creating_a_recipe_puts_it_in_the_family_book(api, family, tomato):
    recipe = create(api, family, tomato)
    assert recipe["owner_family"] == family.pk
    assert recipe["visibility"] == "shared"
    assert recipe["steps"] == ["Boil the pasta.", "Add the sauce."]
    assert recipe["can_edit"] is True
    assert recipe["book_entries"] == [
        {
            "id": recipe["book_entries"][0]["id"],
            "family": family.pk,
            "status": "approved",
            "rating": None,
        }
    ]


def test_recipe_requires_one_of_your_families(api, family, other, tomato):
    response = api.post("/api/recipes/", payload(other[0], tomato), format="json")
    assert response.status_code == 400
    no_family = {k: v for k, v in payload(family, tomato).items() if k != "family"}
    assert api.post("/api/recipes/", no_family, format="json").status_code == 400


def test_season_is_derived_from_ingredients_until_the_user_sets_it(api, family, tomato, basil):
    recipe = create(api, family, tomato, basil)
    assert recipe["season_months"]["months"] == [6, 7, 8]
    assert recipe["provenance"]["season_months"] == "derived"

    url = f"/api/recipes/{recipe['id']}/"
    api.patch(url, {"season_months": {"seasons": ["summer", "autumn"]}}, format="json")
    # A user decision survives ingredient changes...
    updated = api.patch(url, {"ingredients": [{"ingredient": tomato.pk}]}, format="json").json()
    assert updated["season_months"]["months"] == [6, 7, 8, 9, 10, 11]
    assert updated["provenance"]["season_months"] == "user"
    # ...until it is handed back to automatic derivation.
    auto = api.patch(url, {"season_months": {"auto": True}}, format="json").json()
    assert auto["season_months"]["months"] == [6, 7, 8, 9]
    assert auto["provenance"]["season_months"] == "derived"


def test_ingredients_with_no_common_season_give_their_union(family, tomato):
    cabbage = Ingredient.objects.create(name="cabbage", season_months=[11, 12, 1])
    recipe = Recipe.objects.create(title="x", owner_family=family)
    recipe.ingredients.create(ingredient=tomato)
    recipe.ingredients.create(ingredient=cabbage)
    assert recipe.derive_season_months() == [1, 6, 7, 8, 9, 11, 12]


def test_private_recipes_are_invisible_to_other_families(api, family, other, tomato):
    shared = create(api, family, tomato)
    private = create(api, family, tomato, title="Secret", visibility="private")
    _, client = other
    titles = [r["title"] for r in client.get("/api/recipes/").json()["results"]]
    assert titles == [shared["title"]]
    assert client.get(f"/api/recipes/{private['id']}/").status_code == 404


def test_only_the_owner_family_edits(api, family, other, tomato):
    recipe = create(api, family, tomato)
    _, client = other
    response = client.patch(f"/api/recipes/{recipe['id']}/", {"title": "Mine"}, format="json")
    assert response.status_code == 403
    assert client.get(f"/api/recipes/{recipe['id']}/").json()["can_edit"] is False


def test_other_families_can_add_a_shared_recipe_to_their_book(api, family, other, tomato):
    recipe = create(api, family, tomato)
    other_family, client = other
    added = client.post(
        "/api/recipe-book/", {"family": other_family.pk, "recipe": recipe["id"]}, format="json"
    )
    assert added.status_code == 201
    # Now the owner cannot delete it any more...
    assert api.delete(f"/api/recipes/{recipe['id']}/").status_code == 409
    # ...but can remove it from its own book.
    own = RecipeBookEntry.objects.get(family=family, recipe_id=recipe["id"])
    assert api.delete(f"/api/recipe-book/{own.pk}/").status_code == 204
    assert Recipe.objects.filter(pk=recipe["id"]).exists()


def test_private_recipes_cannot_be_added_by_others(api, family, other, tomato):
    private = create(api, family, tomato, visibility="private")
    other_family, client = other
    response = client.post(
        "/api/recipe-book/", {"family": other_family.pk, "recipe": private["id"]}, format="json"
    )
    assert response.status_code == 400


def test_removing_a_private_recipe_from_the_book_deletes_it(api, family, tomato):
    private = create(api, family, tomato, visibility="private")
    entry = RecipeBookEntry.objects.get(family=family, recipe_id=private["id"])
    assert api.delete(f"/api/recipe-book/{entry.pk}/").status_code == 204
    assert not Recipe.objects.filter(pk=private["id"]).exists()


def test_recipe_book_lists_summaries_with_filters(api, family, tomato):
    create(api, family, tomato, title="Pasta al pomodoro", course="first")
    create(api, family, tomato, title="Insalata caprese", course="side")
    book = api.get(f"/api/recipe-book/?family={family.pk}").json()["results"]
    assert [e["recipe_summary"]["title"] for e in book] == ["Insalata caprese", "Pasta al pomodoro"]
    assert book[0]["recipe_summary"]["season_months"] == [6, 7, 8, 9]
    filtered = api.get(f"/api/recipe-book/?family={family.pk}&course=first").json()["results"]
    assert [e["recipe_summary"]["title"] for e in filtered] == ["Pasta al pomodoro"]
    searched = api.get(f"/api/recipe-book/?family={family.pk}&search=capr").json()["results"]
    assert len(searched) == 1


def test_ingredient_search_matches_aliases(api, tomato):
    tomato.aliases = ["pomodori"]
    tomato.save()
    assert [i["name"] for i in api.get("/api/ingredients/?search=Pomodori").json()["results"]] == [
        "tomato"
    ]


def test_catalogs_are_open_to_additions_but_only_staff_change_them(api, user, tomato):
    assert api.post("/api/cuisines/", {"name": "Italiana"}, format="json").status_code == 201
    assert api.post("/api/ingredients/", {"name": "basilico"}, format="json").status_code == 201
    assert (
        api.patch(f"/api/ingredients/{tomato.pk}/", {"name": "x"}, format="json").status_code == 403
    )
    assert api.delete(f"/api/ingredients/{tomato.pk}/").status_code == 403
    user.is_staff = True
    user.save()
    assert (
        api.patch(
            f"/api/ingredients/{tomato.pk}/", {"aliases": ["pomodori"]}, format="json"
        ).status_code
        == 200
    )
