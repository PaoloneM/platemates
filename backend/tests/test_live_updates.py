"""Real-time notices of what changed: a day's meals, a recipe's parts, and which tab did it."""

import datetime as dt

import pytest

from apps.menus.models import SlotDish, WeeklyMenu
from apps.realtime import events as realtime
from apps.recipes.models import Recipe
from apps.teams.models import RecipeBookEntry, Team

MONDAY = dt.date(2026, 10, 12)
TAB = {"HTTP_X_PLATEMATES_CLIENT": "tab-1"}


@pytest.fixture
def sent(monkeypatch):
    emitted = []
    monkeypatch.setattr(
        realtime, "_emit", lambda event, data, room: emitted.append((event, data, room))
    )
    return emitted


def put_day(api, team, body, **extra):
    url = f"/api/calendar/{MONDAY.isoformat()}/?team={team.pk}"
    return api.put(url, body, format="json", **extra)


def test_a_days_change_says_which_meals_and_which_tab(
    api, team, pasta_recipe, sent, django_capture_on_commit_callbacks
):
    with django_capture_on_commit_callbacks(execute=True):
        put_day(api, team, {"people": {"dinner": 5}, "dishes": {"lunch": [pasta_recipe.pk]}}, **TAB)
    [(_event, data, room)] = [s for s in sent if s[0] == "calendar"]
    assert room == f"team-{team.pk}"
    assert data["date"] == MONDAY.isoformat() and data["origin"] == "tab-1"
    assert {(c["meal"], c["what"]) for c in data["changes"]} == {
        ("dinner", "people"),
        ("lunch", "dishes"),
    }


def test_nothing_changed_nothing_sent(api, team, sent, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        put_day(api, team, {"note": ""})
    assert not [s for s in sent if s[0] == "calendar"]


def test_a_note_is_the_days_own_change(api, team, sent, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        put_day(api, team, {"note": "Ospiti"})
    [(_, data, _)] = [s for s in sent if s[0] == "calendar"]
    assert data["changes"] == [{"meal": None, "what": "note"}]
    assert "origin" not in data  # no tab said who it was


def test_accepting_a_proposal_is_sent_too(
    api, team, pasta_recipe, sent, django_capture_on_commit_callbacks
):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    menu.create_empty_slots()
    SlotDish.objects.create(
        slot=menu.slots.get(date=MONDAY, meal="dinner"), recipe=pasta_recipe, proposed=True
    )
    with django_capture_on_commit_callbacks(execute=True):
        api.post(f"/api/menus/{menu.pk}/review/", {"action": "accept"}, format="json")
    changes = [c for s in sent if s[0] == "calendar" for c in s[1]["changes"]]
    assert {"meal": "dinner", "what": "dishes"} in changes


def test_a_recipes_change_reaches_its_team_and_the_books_that_keep_it(
    api, team, pasta_recipe, sent, django_capture_on_commit_callbacks
):
    pasta_recipe.owner_team = team
    pasta_recipe.save()
    reader = Team.objects.create(name="Lettori")
    RecipeBookEntry.objects.create(team=reader, recipe=pasta_recipe, status="approved")
    with django_capture_on_commit_callbacks(execute=True):
        api.patch(f"/api/recipes/{pasta_recipe.pk}/", {"title": "Pasta"}, format="json", **TAB)
    recipe_events = [s for s in sent if s[0] == "recipe"]
    assert {room for _, _, room in recipe_events} == {f"team-{team.pk}", f"team-{reader.pk}"}
    assert "title" in recipe_events[0][1]["fields"]
    assert recipe_events[0][1]["origin"] == "tab-1"


def test_a_recipe_saved_unchanged_sends_nothing(
    api, team, sent, django_capture_on_commit_callbacks
):
    recipe = Recipe.objects.create(title="Uguale", owner_team=team, visibility="private")
    with django_capture_on_commit_callbacks(execute=True):
        api.patch(f"/api/recipes/{recipe.pk}/", {"title": "Uguale"}, format="json")
    assert not [s for s in sent if s[0] == "recipe"]


# -- the recipe book ----------------------------------------------------------------------------


def rooms(sent, action):
    return {room for event, data, room in sent if event == "recipe" and data["action"] == action}


def test_a_new_private_recipe_reaches_its_team_only(
    api, team, sent, django_capture_on_commit_callbacks
):
    Team.objects.create(name="Altri")
    with django_capture_on_commit_callbacks(execute=True):
        body = {"team": team.pk, "title": "Segreta", "servings": 2, "visibility": "private"}
        assert api.post("/api/recipes/", body, format="json").status_code == 201
    assert rooms(sent, "created") == {f"team-{team.pk}"}


def test_a_shared_recipe_reaches_every_team_but_the_system(
    api, team, sent, django_capture_on_commit_callbacks
):
    other = Team.objects.create(name="Altri")
    with django_capture_on_commit_callbacks(execute=True):
        body = {"team": team.pk, "title": "Per tutti", "servings": 2, "visibility": "shared"}
        created = api.post("/api/recipes/", body, format="json").json()
    assert rooms(sent, "created") == {f"team-{team.pk}", f"team-{other.pk}"}
    with django_capture_on_commit_callbacks(execute=True):
        api.delete(f"/api/recipes/{created['id']}/")
    assert rooms(sent, "deleted") == {f"team-{team.pk}", f"team-{other.pk}"}


def test_a_book_gaining_or_losing_a_recipe_is_the_teams_own_news(
    api, team, sent, django_capture_on_commit_callbacks
):
    other = Team.objects.create(name="Altri")
    shared = Recipe.objects.create(title="Della community", owner_team=other, visibility="shared")
    with django_capture_on_commit_callbacks(execute=True):
        entry = api.post(
            "/api/recipe-book/",
            {"team": team.pk, "recipe": shared.pk, "status": "approved"},
            format="json",
        ).json()
    with django_capture_on_commit_callbacks(execute=True):
        api.delete(f"/api/recipe-book/{entry['id']}/")
    assert rooms(sent, "book_added") == {f"team-{team.pk}"}
    assert rooms(sent, "book_removed") == {f"team-{team.pk}"}
    book_events = [d for e, d, _ in sent if e == "recipe" and d["action"].startswith("book_")]
    assert all(d["team"] == team.pk and d["recipe"] == shared.pk for d in book_events)
