"""Shopping lists: generated from a week's menu, ticked live, edited by hand, merged."""

import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.models import Ingredient
from apps.catalog.services import merge_ingredients
from apps.menus.models import ShoppingItem, ShoppingList, SlotDish, WeeklyMenu
from apps.menus.shopping import weeks_to_prepare
from apps.recipes.models import Recipe
from apps.teams.models import Membership, Team

TODAY = timezone.localdate()
THIS_MONDAY = TODAY - dt.timedelta(days=TODAY.weekday())


@pytest.fixture
def events(monkeypatch):
    sent = []
    monkeypatch.setattr(
        "apps.menus.shopping_api.publish", lambda team, event, data: sent.append((event, data))
    )
    return sent


def planned_week(team, recipe, monday=THIS_MONDAY, people=(2, 3)):
    """A menu with the recipe at Monday's lunch and dinner, for that many people."""
    menu = WeeklyMenu.objects.create(team=team, week_start=monday)
    menu.create_empty_slots()
    for slot, count in zip(menu.slots.filter(date=monday).order_by("meal"), people, strict=False):
        slot.people = count
        slot.save()
        SlotDish.objects.create(slot=slot, recipe=recipe)
    return menu


def generate(api, menu):
    response = api.post("/api/shopping-lists/generate/", {"menu": menu.pk}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def items_of(api, list_id):
    return {i["name"]: i for i in api.get(f"/api/shopping-lists/{list_id}/").json()["items"]}


# -- weeks and generation ----------------------------------------------------------------------


def test_a_week_becomes_a_list(api, team, pasta_recipe, events, django_capture_on_commit_callbacks):
    menu = planned_week(team, pasta_recipe)
    weeks = api.get(f"/api/shopping-lists/weeks/?team={team.pk}").json()
    assert weeks == [{"menu": menu.pk, "week_start": THIS_MONDAY.isoformat()}]

    with django_capture_on_commit_callbacks(execute=True):
        created = generate(api, menu)

    assert created["weeks"] == [THIS_MONDAY.isoformat()]
    assert (created["total"], created["bought"]) == (3, 0)
    items = items_of(api, created["id"])
    assert items["spaghetti"]["quantity"] == "400.00"  # 160 for 2 + 240 for 3
    assert items["salt"]["quantity"] is None and items["salt"]["unit"] == "tt"
    assert items["tomato"]["needed_on"] == [THIS_MONDAY.isoformat()]
    assert api.get(f"/api/shopping-lists/weeks/?team={team.pk}").json() == []
    assert events == [("shopping", {"team": team.pk, "list": created["id"]})]


def test_every_generation_is_a_new_list_and_deleting_one_frees_its_week(api, team, pasta_recipe):
    menu = planned_week(team, pasta_recipe)
    first, second = generate(api, menu), generate(api, menu)
    assert first["id"] != second["id"]
    assert len(api.get(f"/api/shopping-lists/?team={team.pk}").json()) == 2
    api.delete(f"/api/shopping-lists/{first['id']}/")
    api.delete(f"/api/shopping-lists/{second['id']}/")
    assert len(weeks_to_prepare(team)) == 1


def test_only_weeks_from_now_on_with_something_to_buy(team, pasta_recipe):
    planned_week(team, pasta_recipe, monday=THIS_MONDAY - dt.timedelta(days=7))  # past
    WeeklyMenu.objects.create(team=team, week_start=THIS_MONDAY + dt.timedelta(days=7))  # empty
    later = planned_week(team, pasta_recipe, monday=THIS_MONDAY + dt.timedelta(days=14))
    assert list(weeks_to_prepare(team)) == [later]


def test_an_item_is_optional_when_every_line_asking_for_it_is(api, team, pasta_recipe):
    pasta_recipe.ingredients.filter(ingredient__name="tomato").update(optional=True)
    created = generate(api, planned_week(team, pasta_recipe))
    items = items_of(api, created["id"])
    assert items["tomato"]["optional"] is True and items["spaghetti"]["optional"] is False


def test_a_list_does_not_follow_later_menu_changes(api, team, pasta_recipe):
    menu = planned_week(team, pasta_recipe)
    created = generate(api, menu)
    SlotDish.objects.filter(slot__menu=menu).delete()
    assert items_of(api, created["id"])["spaghetti"]["quantity"] == "400.00"


def post_generate(api, body):
    return api.post("/api/shopping-lists/generate/", body, format="json")


def test_a_day_or_a_meal_becomes_a_list_and_the_week_stays_to_prepare(api, team, pasta_recipe):
    planned_week(team, pasta_recipe)
    day = post_generate(api, {"team": team.pk, "date": THIS_MONDAY.isoformat(), "title": "Lunedì"})
    assert day.status_code == 201, day.json()
    assert (day.json()["title"], day.json()["weeks"]) == ("Lunedì", [])
    assert items_of(api, day.json()["id"])["spaghetti"]["quantity"] == "400.00"
    dinner = post_generate(
        api, {"team": team.pk, "date": THIS_MONDAY.isoformat(), "meal": "dinner"}
    ).json()
    # planned_week: dinner for 2, lunch for 3 (slots in meal order).
    assert items_of(api, dinner["id"])["spaghetti"]["quantity"] == "160.00"
    assert dinner["title"] == f"{THIS_MONDAY:%d/%m} dinner"
    assert len(weeks_to_prepare(team)) == 1


def test_a_recipe_becomes_a_list_for_some_people(api, team, pasta_recipe):
    created = post_generate(api, {"team": team.pk, "recipe": pasta_recipe.pk, "people": 4})
    assert created.status_code == 201, created.json()
    items = items_of(api, created.json()["id"])
    assert items["spaghetti"]["quantity"] == "320.00"  # 160 for 2
    assert items["spaghetti"]["needed_on"] == []
    assert created.json()["title"] == pasta_recipe.title


def test_nothing_to_buy_makes_no_list(api, team, pasta_recipe):
    planned_week(team, pasta_recipe)
    tuesday = (THIS_MONDAY + dt.timedelta(days=1)).isoformat()
    response = post_generate(api, {"team": team.pk, "date": tuesday})
    assert response.status_code == 400 and response.json()["code"] == "nothing_to_buy"
    assert not ShoppingList.objects.exists()


@pytest.mark.parametrize(
    "body",
    [
        {"date": "2026-10-12"},  # no team
        {"team": 0, "date": "2026-10-12", "recipe": 1},  # two things at once
        {"meal": "dinner"},  # a meal without a date
    ],
)
def test_what_to_shop_for_must_be_clear(api, team, body):
    body = {**body, "team": team.pk} if body.get("team") == 0 else body
    assert post_generate(api, body).status_code == 400


def test_no_list_from_another_teams_days_or_private_recipes(api, team, pasta_recipe):
    other = Team.objects.create(name="Altri")
    planned_week(other, pasta_recipe)
    body = {"team": other.pk, "date": THIS_MONDAY.isoformat()}
    assert post_generate(api, body).status_code == 400
    secret = Recipe.objects.create(title="Segreto", owner_team=other, visibility="private")
    body = {"team": team.pk, "recipe": secret.pk, "people": 2}
    assert post_generate(api, body).status_code == 400


def test_merging_other_lists_joins_their_titles(api, team, pasta_recipe):
    planned_week(team, pasta_recipe)
    week = generate(api, WeeklyMenu.objects.get(team=team))
    recipe = post_generate(
        api, {"team": team.pk, "recipe": pasta_recipe.pk, "people": 2, "title": "Pasta"}
    ).json()
    merged = api.post(
        "/api/shopping-lists/merge/", {"lists": [week["id"], recipe["id"]]}, format="json"
    ).json()
    assert merged["title"] == f"{week['title']} + Pasta"
    assert items_of(api, merged["id"])["spaghetti"]["quantity"] == "560.00"


# -- ticking and editing -----------------------------------------------------------------------


def test_ticking_records_who_and_when(
    api, user, team, pasta_recipe, events, django_capture_on_commit_callbacks
):
    created = generate(api, planned_week(team, pasta_recipe))
    item = items_of(api, created["id"])["spaghetti"]
    with django_capture_on_commit_callbacks(execute=True):
        ticked = api.patch(f"/api/shopping-items/{item['id']}/", {"bought": True}, format="json")
    assert ticked.json()["bought"] is True and ticked.json()["bought_at"]
    assert ShoppingItem.objects.get(pk=item["id"]).bought_by == user
    assert events[-1] == ("shopping", {"team": team.pk, "list": created["id"]})
    assert api.get(f"/api/shopping-lists/{created['id']}/").json()["bought"] == 1
    api.patch(f"/api/shopping-items/{item['id']}/", {"bought": False}, format="json")
    stored = ShoppingItem.objects.get(pk=item["id"])
    assert (stored.bought, stored.bought_at, stored.bought_by) == (False, None, None)


def test_items_are_added_corrected_and_removed_by_hand(api, team, pasta_recipe):
    created = generate(api, planned_week(team, pasta_recipe))
    url = "/api/shopping-items/"
    soap = api.post(
        url, {"shopping_list": created["id"], "name": " detersivo  piatti "}, format="json"
    ).json()
    assert (soap["name"], soap["manual"], soap["category"]) == ("detersivo piatti", True, "other")
    milk = Ingredient.objects.create(name="latte", category="dairy", default_unit="ml")
    added = api.post(
        url,
        {"shopping_list": created["id"], "ingredient": milk.pk, "quantity": "1000"},
        format="json",
    ).json()
    assert (added["name"], added["category"], added["unit"]) == ("latte", "dairy", "ml")
    fixed = api.patch(
        f"{url}{added['id']}/", {"quantity": "500", "note": "parzialmente scremato"}, format="json"
    ).json()
    assert fixed["quantity"] == "500.00" and fixed["note"] == "parzialmente scremato"
    assert (
        api.post(url, {"shopping_list": created["id"], "name": " "}, format="json").status_code
        == 400
    )
    assert api.delete(f"{url}{soap['id']}/").status_code == 204
    assert "detersivo piatti" not in items_of(api, created["id"])


def test_items_go_into_the_cart_at_once(
    api, user, team, pasta_recipe, events, django_capture_on_commit_callbacks
):
    created = generate(api, planned_week(team, pasta_recipe))
    other = generate(api, planned_week(team, pasta_recipe, monday=THIS_MONDAY + dt.timedelta(7)))
    items = items_of(api, created["id"])
    stranger = items_of(api, other["id"])["salt"]["id"]
    with django_capture_on_commit_callbacks(execute=True):
        response = api.post(
            f"/api/shopping-lists/{created['id']}/buy/",
            {"items": [items["spaghetti"]["id"], items["salt"]["id"], stranger]},
            format="json",
        )
    assert response.json() == {"bought": 2}
    assert events[-1] == ("shopping", {"team": team.pk, "list": created["id"]})
    after = items_of(api, created["id"])
    assert after["spaghetti"]["bought"] and not after["tomato"]["bought"]
    assert ShoppingItem.objects.get(pk=items["salt"]["id"]).bought_by == user
    assert not ShoppingItem.objects.get(pk=stranger).bought


def test_another_teams_ingredient_cannot_be_added(api, team, pasta_recipe):
    created = generate(api, planned_week(team, pasta_recipe))
    theirs = Ingredient.objects.create(name="segreto", owner_team=Team.objects.create(name="Altri"))
    response = api.post(
        "/api/shopping-items/",
        {"shopping_list": created["id"], "ingredient": theirs.pk},
        format="json",
    )
    assert response.status_code == 400


# -- merging -----------------------------------------------------------------------------------


def test_merging_sums_items_and_keeps_ticks_bought_everywhere(api, team, pasta_recipe):
    first = generate(api, planned_week(team, pasta_recipe))
    second = generate(
        api, planned_week(team, pasta_recipe, monday=THIS_MONDAY + dt.timedelta(days=7))
    )
    one, two = items_of(api, first["id"]), items_of(api, second["id"])
    for items in (one, two):
        api.patch(
            f"/api/shopping-items/{items['spaghetti']['id']}/", {"bought": True}, format="json"
        )
    api.patch(f"/api/shopping-items/{one['tomato']['id']}/", {"bought": True}, format="json")
    api.post("/api/shopping-items/", {"shopping_list": first["id"], "name": "Caffè"}, format="json")
    api.post(
        "/api/shopping-items/", {"shopping_list": second["id"], "name": "caffè"}, format="json"
    )

    response = api.post(
        "/api/shopping-lists/merge/", {"lists": [first["id"], second["id"]]}, format="json"
    )
    assert response.status_code == 201, response.json()
    merged = response.json()
    assert sorted(merged["weeks"]) == [
        THIS_MONDAY.isoformat(),
        (THIS_MONDAY + dt.timedelta(days=7)).isoformat(),
    ]
    items = items_of(api, merged["id"])
    assert items["spaghetti"]["quantity"] == "800.00" and items["spaghetti"]["bought"] is True
    assert items["tomato"]["quantity"] == "1500.00" and items["tomato"]["bought"] is False
    assert len(items["tomato"]["needed_on"]) == 2
    assert [name for name in items if name.lower() == "caffè"] == ["Caffè"]
    assert not ShoppingList.objects.filter(pk__in=[first["id"], second["id"]]).exists()
    assert weeks_to_prepare(team).count() == 0


def test_merging_needs_two_lists_of_one_team(api, team, pasta_recipe):
    first = generate(api, planned_week(team, pasta_recipe))
    url = "/api/shopping-lists/merge/"
    assert api.post(url, {"lists": [first["id"]]}, format="json").status_code == 400
    assert api.post(url, {"lists": [first["id"], first["id"]]}, format="json").status_code == 400


def test_ingredient_merges_carry_shopping_items(api, team, pasta_recipe):
    created = generate(api, planned_week(team, pasta_recipe))
    tomato = Ingredient.objects.get(name="tomato")
    target = Ingredient.objects.create(name="pomodoro")
    merge_ingredients(tomato, target)
    item = ShoppingItem.objects.get(shopping_list_id=created["id"], name="tomato")
    assert item.ingredient == target


# -- teams -------------------------------------------------------------------------------------


def test_another_team_sees_and_touches_nothing(api, team, pasta_recipe):
    menu = planned_week(team, pasta_recipe)
    created = generate(api, menu)
    item = items_of(api, created["id"])["salt"]
    stranger = get_user_model().objects.create_user("eve")
    Membership.objects.create(user=stranger, team=Team.objects.create(name="Altri"))
    other = APIClient()
    other.force_authenticate(stranger)
    assert other.get(f"/api/shopping-lists/{created['id']}/").status_code == 404
    assert other.get("/api/shopping-lists/").json() == []
    assert (
        other.patch(
            f"/api/shopping-items/{item['id']}/", {"bought": True}, format="json"
        ).status_code
        == 404
    )
    assert (
        other.post("/api/shopping-lists/generate/", {"menu": menu.pk}, format="json").status_code
        == 400
    )
    assert other.get(f"/api/shopping-lists/weeks/?team={team.pk}").status_code == 400
    response = other.post(
        "/api/shopping-items/", {"shopping_list": created["id"], "name": "x"}, format="json"
    )
    assert response.status_code == 400
    assert ShoppingItem.objects.filter(shopping_list_id=created["id"]).count() == 3
    assert Decimal(ShoppingItem.objects.get(pk=item["id"]).bought) == 0
