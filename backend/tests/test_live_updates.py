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
