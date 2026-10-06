from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.families.models import Family
from tests.conftest import MONDAY


def test_health_is_public(db):
    response = APIClient().get("/api/health/")
    assert response.status_code == 200
    assert response.json()["database"]["ok"] is True


def test_api_requires_authentication(db):
    assert APIClient().get("/api/recipes/").status_code in (401, 403)


def test_only_staff_can_create_families(api):
    assert api.post("/api/families/", {"name": "New"}, format="json").status_code == 403


def test_creating_a_family_makes_the_staff_user_its_owner(api, user):
    user.is_staff = True
    user.save()
    response = api.post("/api/families/", {"name": "New"}, format="json")
    assert response.status_code == 201
    assert api.get("/api/families/").json()["count"] == 1


def test_users_only_see_their_own_families(api, family):
    Family.objects.create(name="Someone else's")
    names = [f["name"] for f in api.get("/api/families/").json()["results"]]
    assert names == [family.name]


def test_cannot_create_a_menu_for_another_family(api, db):
    other = Family.objects.create(name="Other")
    response = api.post("/api/menus/", {"family": other.pk, "week_start": MONDAY}, format="json")
    assert response.status_code == 400


def test_menu_creation_and_shopping_list(api, family, pasta_recipe):
    menu = api.post("/api/menus/", {"family": family.pk, "week_start": MONDAY}, format="json")
    assert menu.status_code == 201
    slot = menu.json()["slots"][0]
    assert (
        api.patch(
            f"/api/slots/{slot['id']}/", {"dishes": [pasta_recipe.pk], "people": 4}, format="json"
        ).status_code
        == 200
    )

    items = api.get(f"/api/menus/{menu.json()['id']}/shopping-list/").json()["items"]
    spaghetti = next(i for i in items["cereal"] if i["name"] == "spaghetti")
    assert spaghetti["quantity"] == "320"


def test_menu_week_must_start_on_monday(api, family):
    response = api.post(
        "/api/menus/", {"family": family.pk, "week_start": "2026-10-06"}, format="json"
    )
    assert response.status_code == 400


def test_api_edits_are_recorded_as_user_decisions(api, db):
    response = api.post(
        "/api/ingredients/",
        {"name": "Zucca", "season_months": {"seasons": ["autumn"]}},
        format="json",
    )
    assert response.json()["provenance"] == {"season_months": "user"}


def test_slots_of_other_families_are_invisible(api, db):
    stranger = get_user_model().objects.create_user("bob")
    other = Family.objects.create(name="Other")
    other.users.add(stranger)
    menu = other.menus.create(week_start=MONDAY)
    menu.create_empty_slots()
    assert api.get("/api/slots/").json()["count"] == 0


def test_seasonality_in_season_mode(api, db):
    created = api.post(
        "/api/ingredients/",
        {"name": "asparagus", "season_months": {"seasons": ["spring"]}},
        format="json",
    ).json()
    assert created["season_months"] == {
        "months": [3, 4, 5],
        "seasons": ["spring"],
        "by_season": True,
    }


def test_seasonality_in_month_mode_flags_partial_seasons(api, db):
    created = api.post(
        "/api/ingredients/",
        {"name": "cherry", "season_months": {"months": [5, 6, 7]}},
        format="json",
    ).json()
    assert created["season_months"] == {"months": [5, 6, 7], "seasons": [], "by_season": False}


def test_all_months_is_stored_as_all_year(api, db):
    created = api.post(
        "/api/ingredients/",
        {"name": "rice", "season_months": {"months": list(range(1, 13))}},
        format="json",
    ).json()
    assert created["season_months"]["months"] == []
    assert created["season_months"]["by_season"] is True


def test_unknown_season_is_rejected(api, db):
    response = api.post(
        "/api/ingredients/", {"name": "x", "season_months": {"seasons": ["monsoon"]}}, format="json"
    )
    assert response.status_code == 400
