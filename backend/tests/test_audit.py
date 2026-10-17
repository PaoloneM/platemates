"""The team's activity log: what its people change, for its owners, kept for a while."""

import datetime as dt

import pytest
from django.utils import timezone

from apps.audit import recorder
from apps.audit.models import AuditEvent
from apps.menus.models import ShoppingItem, SlotDish, WeeklyMenu
from apps.recipes.models import Recipe
from apps.siteconfig.models import ConfigVar
from apps.teams.models import Team

MONDAY = dt.date(2026, 10, 12)


@pytest.fixture(autouse=True)
def purge_inline(monkeypatch):
    """The lazy purge runs in the request's thread here, and every time."""
    # The purge itself, without the thread's closing of its own connection.
    monkeypatch.setattr(recorder, "spawn", lambda function: recorder.purge())
    monkeypatch.setattr(recorder, "_last_purge", 0.0)
    monkeypatch.setattr(recorder, "PURGE_EVERY_SECONDS", 0)


def events(api, team, **params):
    query = "&".join(f"{k}={v}" for k, v in {"team": team.pk, **params}.items())
    response = api.get(f"/api/audit-events/?{query}")
    assert response.status_code == 200, response.json()
    return response.json()["results"]


def own_recipe(team, title="Pasta e ceci"):
    return Recipe.objects.create(title=title, owner_team=team, visibility="private")


def test_a_change_is_recorded_with_its_fields_before_and_after(api, user, team):
    recipe = own_recipe(team)
    api.patch(f"/api/recipes/{recipe.pk}/", {"title": "Pasta e fagioli"}, format="json")
    [event] = events(api, team)
    assert event["action"] == "recipe.partial_update"
    assert (event["target_type"], event["target_label"]) == ("recipe", "Pasta e fagioli")
    assert event["user"] == user.pk
    [change] = event["changes"]
    assert change["op"] == "update"
    assert change["fields"]["title"] == ["Pasta e ceci", "Pasta e fagioli"]


def test_a_recipes_ingredients_are_recorded_as_lines(api, team, pasta_recipe):
    pasta_recipe.owner_team = team
    pasta_recipe.save()
    line = pasta_recipe.ingredients.get(ingredient__name__iexact="spaghetti")
    body = {"ingredients": [{"ingredient": line.ingredient_id, "quantity": "200", "unit": "g"}]}
    api.patch(f"/api/recipes/{pasta_recipe.pk}/", body, format="json")
    [change] = events(api, team)[0]["changes"]
    before, after = change["fields"]["ingredients"]
    name = line.ingredient.name
    assert f"160 g {name}" in before and after == [f"200 g {name}"]


def test_a_days_people_and_dishes_are_recorded(api, team, pasta_recipe):
    url = f"/api/calendar/{MONDAY.isoformat()}/?team={team.pk}"
    body = {"people": {"dinner": 5}, "dishes": {"dinner": [pasta_recipe.pk]}}
    assert api.put(url, body, format="json").status_code == 200
    [event] = events(api, team)
    assert (event["target_type"], event["target_label"]) == ("day", MONDAY.isoformat())
    fields = event["changes"][0]["fields"]
    assert fields["people.dinner"][1] == 5
    assert fields["dishes.dinner"] == [[], [pasta_recipe.title]]


def test_accepting_a_proposal_is_recorded(api, team, pasta_recipe):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    menu.create_empty_slots()
    slot = menu.slots.get(date=MONDAY, meal="dinner")
    SlotDish.objects.create(slot=slot, recipe=pasta_recipe, proposed=True)
    meals = [{"date": MONDAY.isoformat(), "meal": "dinner"}]
    api.post(f"/api/menus/{menu.pk}/review/", {"action": "accept", "meals": meals}, format="json")
    [event] = events(api, team)
    assert event["action"] == "weeklymenu.review"
    assert event["changes"][0]["fields"]["dishes.dinner"] == [
        [f"{pasta_recipe.title} ✦"],
        [pasta_recipe.title],
    ]


def test_ticks_are_not_recorded_but_items_are(api, team):
    created = api.post(
        "/api/shopping-lists/generate/",
        {"team": team.pk, "recipe": own_recipe(team).pk, "people": 2, "title": "Spesa"},
        format="json",
    )
    assert created.status_code == 400  # a recipe without ingredients: nothing to buy
    shopping_list = team.shopping_lists.create(title="Spesa")
    item = api.post(
        "/api/shopping-items/", {"shopping_list": shopping_list.pk, "name": "sapone"}, format="json"
    ).json()
    api.patch(f"/api/shopping-items/{item['id']}/", {"bought": True}, format="json")
    assert ShoppingItem.objects.get(pk=item["id"]).bought
    assert [e["action"] for e in events(api, team)] == ["shopping-item.create"]


def test_deleting_a_list_is_one_line_not_one_per_item(api, team):
    shopping_list = team.shopping_lists.create(title="Spesa")
    for name in ("pane", "latte", "uova"):
        shopping_list.items.create(name=name)
    api.delete(f"/api/shopping-lists/{shopping_list.pk}/")
    [event] = events(api, team)
    assert [(c["type"], c["op"]) for c in event["changes"]] == [("shopping_list", "delete")]


def test_failed_requests_and_reads_record_nothing(api, team):
    api.get(f"/api/recipes/?team={team.pk}")
    api.post("/api/recipes/", {"team": team.pk, "title": ""}, format="json")
    assert not AuditEvent.objects.exists()


def test_system_recipes_are_nobodys_activity(api, user, team):
    user.is_staff = True
    user.save()
    recipe = Recipe.objects.create(title="Lasagne", owner_team=Team.system())
    api.patch(f"/api/recipes/{recipe.pk}/", {"title": "Lasagne al forno"}, format="json")
    assert not AuditEvent.objects.exists()


def test_only_the_teams_owners_read_its_activity(api, team, member):
    own_recipe(team)
    _, client = member
    assert client.get(f"/api/audit-events/?team={team.pk}").status_code == 403
    other = Team.objects.create(name="Altri")
    assert api.get(f"/api/audit-events/?team={other.pk}").status_code == 400


# -- retention ---------------------------------------------------------------------------------


def make_events(team, user, count, age_days=0):
    created = [
        AuditEvent.objects.create(team=team, user=user, user_name="x", action="a", target_type="t")
        for _ in range(count)
    ]
    AuditEvent.objects.filter(pk__in=[e.pk for e in created]).update(
        created_at=timezone.now() - dt.timedelta(days=age_days)
    )


def test_old_events_go_and_never_show_before_they_do(api, user, team):
    make_events(team, user, 2, age_days=120)
    make_events(team, user, 1, age_days=10)
    assert len(events(api, team)) == 1  # read: past 90 days hidden, still stored
    assert AuditEvent.objects.count() == 3
    assert recorder.purge() == 2
    ConfigVar.objects.create(key="audit.retention_days", value=5)
    assert recorder.purge() == 1


def test_beyond_the_maximum_the_oldest_go_whatever_their_team(user, team):
    other = Team.objects.create(name="Altri")
    make_events(other, user, 3)
    make_events(team, user, 100)
    ConfigVar.objects.create(key="audit.max_events", value=100)
    assert recorder.purge() == 3
    assert not AuditEvent.objects.filter(team=other).exists()


def test_recording_triggers_the_lazy_purge(api, user, team):
    make_events(team, user, 1, age_days=200)
    recipe = own_recipe(team)
    api.patch(f"/api/recipes/{recipe.pk}/", {"title": "Altro"}, format="json")
    assert AuditEvent.objects.count() == 1  # the new one; the old one was purged


# -- statistics (administrators) ----------------------------------------------------------------


def test_administrators_see_the_most_active_teams(api, user, team):
    from apps.accounts.models import UserProfile

    other = Team.objects.create(name="Altri")
    make_events(team, user, 3)
    make_events(other, user, 1, age_days=4)
    assert api.get("/api/audit-stats/").status_code == 403
    UserProfile.objects.create(user=user, is_admin=True)
    data = api.get("/api/audit-stats/").json()
    assert data["total_events"] == 4 and data["table_bytes"] > 0
    assert (data["retention_days"], data["max_events"]) == (90, 1000)
    assert [(t["name"], t["events"]) for t in data["teams"]] == [(team.name, 3), ("Altri", 1)]
    assert all(t["bytes"] > 0 and t["last"] for t in data["teams"])
