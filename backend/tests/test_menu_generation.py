import datetime as dt
import json

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from rest_framework.test import APIClient

from ai import AIError, ChatResult
from apps.catalog.models import Ingredient, IngredientCategory, KitchenTool
from apps.menus import generation as engine
from apps.menus import review
from apps.menus.models import MenuGeneration, SlotDish, TeamRule, WeeklyMenu
from apps.menus.shopping import build_shopping_list
from apps.recipes.models import Recipe, RecipeIngredient, Visibility
from apps.teams.calendar import calendar, set_day
from apps.teams.models import CalendarDay, Membership, Preference, RecipeBookEntry, Team

MONDAY = dt.date(2026, 10, 5)
TUESDAY = MONDAY + dt.timedelta(1)
THURSDAY = MONDAY + dt.timedelta(3)


class FakeChat:
    """Answers with the given replies in turn; records what it was asked."""

    model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply if isinstance(reply, str) else json.dumps(reply))


def answer(meals=(), people=(), rationale="Varied week."):
    return {"meals": list(meals), "people_changes": list(people), "rationale": rationale}


def meal(date, which, *dishes):
    return {"date": date.isoformat(), "meal": which, "dishes": list(dishes)}


def dish(ref=None, title=None, note="", course=None):
    return {"recipe_id": ref, "new_title": title, "course": course, "note": note}


@pytest.fixture
def book(team):
    """Three recipes in the team's book; the typical week has 2 at lunch and 3 at dinner."""
    recipes = []
    for title in ["Pasta e ceci", "Orata al forno", "Minestrone"]:
        recipe = Recipe.objects.create(title=title, owner_team=team)
        RecipeBookEntry.objects.create(team=team, recipe=recipe, status="approved")
        recipes.append(recipe)
    return recipes


@pytest.fixture
def menu(team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    menu.create_empty_slots()
    return menu


def queued(menu, **kwargs):
    return MenuGeneration.objects.create(menu=menu, **kwargs)


def context_for(menu, **kwargs):
    """The context of a generation; a finished one, so it does not hold the week."""
    return engine.build_context(queued(menu, status=MenuGeneration.Status.DONE, **kwargs))


def ref_of(context, recipe):
    return next(ref for ref, r in context.candidates.items() if r == recipe)


# -- rules -------------------------------------------------------------------------------------


def test_standard_rules_ignore_the_weeks_settings(menu, team):
    TeamRule.objects.create(team=team, text="Fish twice")
    menu.instructions = "No fish"
    menu.use_team_rules = False
    menu.save()
    rules = engine.rules_for(menu, use_week_settings=False, language="en")
    assert rules["team"] == ["Fish twice"] and rules["week"] == ""
    assert any("Healthy Eating Plate" in text for text in rules["system"])


def test_week_settings_leave_out_team_rules(menu, team):
    fish = TeamRule.objects.create(team=team, text="Fish twice")
    TeamRule.objects.create(team=team, text="Pizza on friday")
    menu.instructions = "No fish"
    menu.save()
    menu.excluded_rules.add(fish)
    rules = engine.rules_for(menu, use_week_settings=True, language="it")
    assert rules["team"] == ["Pizza on friday"] and rules["week"] == "No fish"
    assert any("piatto sano" in text for text in rules["system"])
    menu.use_team_rules = False
    menu.save()
    assert engine.rules_for(menu, use_week_settings=True, language="it")["team"] == []


# -- candidates and prompt ---------------------------------------------------------------------


def test_candidates_respect_avoids_tools_and_rejections(team, book):
    _, orata, minestrone = book
    fish = Ingredient.objects.create(name="orata", category=IngredientCategory.FISH)
    RecipeIngredient.objects.create(recipe=orata, ingredient=fish)
    Preference.objects.create(team=team, kind=Preference.Kind.AVOIDS, ingredient=fish)
    oven = KitchenTool.objects.create(name="Test oven")
    hob = KitchenTool.objects.create(name="Test hob")
    team.tools.add(hob)
    minestrone.tools.add(oven)
    rejected = Recipe.objects.create(title="Trippa", visibility=Visibility.SHARED)
    RecipeBookEntry.objects.create(team=team, recipe=rejected, status="rejected")
    shared = Recipe.objects.create(title="Ribollita", visibility=Visibility.SHARED)
    titles = {r.title: facts for r, facts in engine.candidate_recipes(team, MONDAY)}
    assert set(titles) == {"Pasta e ceci", "Ribollita"}
    assert titles["Pasta e ceci"]["in_book"] and not titles["Ribollita"]["in_book"]
    assert shared.pk  # shared recipes are offered to discover


def test_other_teams_private_recipes_are_never_candidates(team, book):
    other = Team.objects.create(name="Other team")
    Recipe.objects.create(
        title="Segreto di famiglia", owner_team=other, visibility=Visibility.PRIVATE
    )
    titles = {r.title for r, _ in engine.candidate_recipes(team, MONDAY)}
    assert "Segreto di famiglia" not in titles


def test_out_of_season_recipes_are_flagged(team, book):
    pasta = book[0]
    pasta.season_months = [6, 7, 8]
    pasta.climate_months = [6, 7, 8]
    pasta.save()
    facts = {r.title: f for r, f in engine.candidate_recipes(team, MONDAY)}
    assert facts["Pasta e ceci"]["in_season"] is False
    assert facts["Minestrone"]["in_season"] is True


def test_the_prompt_lists_open_fixed_and_empty_meals(menu, team, book):
    set_day(team, TUESDAY, dishes={"dinner": [book[2]]})
    set_day(team, THURSDAY, people={"lunch": 0})
    context = context_for(menu, language="it")
    prompt = context.messages[1]["content"]
    assert "2026-10-05 lunedì pranzo: 2 people, OPEN" in prompt
    assert "2026-10-06 martedì cena: 3 people, FIXED: Minestrone" in prompt
    assert "2026-10-08 giovedì pranzo: nobody at home" in prompt
    assert "Pasta e ceci" in prompt and "Italian" in context.messages[0]["content"]


def test_the_prompt_lists_what_was_eaten_recently(team, book):
    set_day(team, MONDAY - dt.timedelta(3), dishes={"dinner": [book[1]]})
    menu = WeeklyMenu.objects.get(team=team, week_start=MONDAY - dt.timedelta(7))
    this_week = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    this_week.create_empty_slots()
    prompt = context_for(this_week).messages[1]["content"]
    assert "## Eaten in the last two weeks\n- Orata al forno" in prompt
    assert "last eaten 2026-10-02" in prompt
    assert menu.pk


# -- validating and applying -------------------------------------------------------------------


def test_a_valid_answer_becomes_proposals(menu, team, book):
    context = context_for(menu)
    pasta = ref_of(context, book[0])
    chat = FakeChat(
        answer(
            meals=[
                meal(MONDAY, "lunch", dish(pasta, note="Quick")),
                meal(MONDAY, "dinner", dish(title="Zuppa di farro", course="first")),
            ]
        )
    )
    generation = queued(menu)
    engine.run_generation(generation, chat=chat)
    generation.refresh_from_db()
    assert generation.status == "done", generation.error
    day = calendar(team, MONDAY, 1)[0]
    assert [(d.recipe, d.proposed, d.note) for d in day.dishes["lunch"]] == [
        (book[0].pk, True, "Quick")
    ]
    assert [(d.recipe, d.title, d.course) for d in day.dishes["dinner"]] == [
        (None, "Zuppa di farro", "first")
    ]
    menu.refresh_from_db()
    assert menu.rationale == "Varied week."
    assert len(generation.result["unplanned"]) == 12
    assert chat.calls[0]["response_format"]["type"] == "json_schema"


def test_fixed_meals_unknown_recipes_and_duplicates_are_dropped(menu, team, book):
    set_day(team, TUESDAY, dishes={"dinner": [book[2]]})
    context = context_for(menu)
    pasta = ref_of(context, book[0])
    proposal = engine.validate_answer(
        context,
        answer(
            meals=[
                meal(TUESDAY, "dinner", dish(pasta)),
                meal(MONDAY, "lunch", dish(pasta), dish(pasta), dish("R999")),
                meal(MONDAY + dt.timedelta(14), "lunch", dish(pasta)),
            ]
        ),
    )
    assert [(m["date"], m["meal"]) for m in proposal["meals"]] == [("2026-10-05", "lunch")]
    assert len(proposal["meals"][0]["dishes"]) == 1
    assert len(proposal["dropped"]) == 3


def test_people_changes_are_proposed_and_planned_for(menu, team, book):
    context = context_for(menu)
    pasta = ref_of(context, book[0])
    proposal = engine.validate_answer(
        context,
        answer(
            people=[
                {"date": THURSDAY.isoformat(), "meal": "dinner", "people": 5, "reason": "Guests"},
                {"date": TUESDAY.isoformat(), "meal": "lunch", "people": 0, "reason": "Away"},
                {"date": TUESDAY.isoformat(), "meal": "dinner", "people": 3, "reason": "Same"},
                {"date": TUESDAY.isoformat(), "meal": "dinner", "people": 99, "reason": "Too many"},
            ],
            meals=[
                meal(THURSDAY, "dinner", dish(pasta)),
                meal(TUESDAY, "lunch", dish(pasta)),
            ],
        ),
    )
    assert proposal["people"] == [
        {"date": "2026-10-08", "meal": "dinner", "people": 5, "reason": "Guests"},
        {"date": "2026-10-06", "meal": "lunch", "people": 0, "reason": "Away"},
    ]
    # Nobody at home after the change: no dishes there.
    assert [(m["date"], m["meal"]) for m in proposal["meals"]] == [("2026-10-08", "dinner")]
    engine.apply_proposal(context, proposal)
    day = calendar(team, THURSDAY, 1)[0]
    assert day.people["dinner"] == 3  # unchanged until accepted
    assert day.proposed_people == {"dinner": 5} and day.people_notes == {"dinner": "Guests"}


def test_recipe_ids_in_free_text_become_titles(menu, team, book):
    context = context_for(menu)
    pasta = ref_of(context, book[0])
    proposal = engine.validate_answer(
        context,
        answer(meals=[meal(MONDAY, "lunch", dish(pasta))], rationale=f"Legumes with {pasta}."),
    )
    assert proposal["rationale"] == "Legumes with «Pasta e ceci»."


def test_an_answer_that_plans_nothing_is_retried_then_fails(menu, book):
    chat = FakeChat("not json", answer(meals=[meal(MONDAY, "lunch", dish("R999"))]))
    generation = queued(menu)
    engine.run_generation(generation, chat=chat)
    generation.refresh_from_db()
    assert generation.status == "failed" and "not usable" in generation.error
    assert len(chat.calls) == 2


def test_an_unavailable_model_fails_the_generation(menu, book):
    generation = queued(menu)
    engine.run_generation(generation, chat=FakeChat(AIError("Studio is down")))
    generation.refresh_from_db()
    assert (generation.status, generation.error) == ("failed", "Studio is down")
    assert generation.finished_at is not None


def test_regenerating_replaces_only_proposals(menu, team, book):
    set_day(team, TUESDAY, dishes={"dinner": [book[2]]})
    first = queued(menu)
    context = engine.build_context(first)
    pasta, orata = ref_of(context, book[0]), ref_of(context, book[1])
    engine.run_generation(first, chat=FakeChat(answer(meals=[meal(MONDAY, "lunch", dish(pasta))])))
    second = queued(menu)
    engine.run_generation(
        second, chat=FakeChat(answer(meals=[meal(MONDAY, "dinner", dish(orata))]))
    )
    dishes = SlotDish.objects.filter(slot__menu=menu)
    assert sorted((d.slot.date, d.slot.meal, d.proposed) for d in dishes) == [
        (MONDAY, "dinner", True),
        (TUESDAY, "dinner", False),
    ]


# -- review ------------------------------------------------------------------------------------


def proposed_week(menu, team, book):
    context = context_for(menu)
    pasta = ref_of(context, book[0])
    proposal = engine.validate_answer(
        context,
        answer(
            people=[{"date": THURSDAY.isoformat(), "meal": "dinner", "people": 5, "reason": "x"}],
            meals=[meal(MONDAY, "lunch", dish(pasta)), meal(THURSDAY, "dinner", dish(pasta))],
        ),
    )
    engine.apply_proposal(context, proposal)


def test_accepting_makes_proposals_the_users_and_updates_the_calendar(menu, team, book):
    proposed_week(menu, team, book)
    review.accept(menu, [(THURSDAY, "dinner")])
    thursday = calendar(team, THURSDAY, 1)[0]
    assert thursday.people["dinner"] == 5 and thursday.proposed_people == {}
    assert [d.proposed for d in thursday.dishes["dinner"]] == [False]
    assert CalendarDay.objects.get(team=team, date=THURSDAY).people == {"dinner": 5}
    assert [d.proposed for d in calendar(team, MONDAY, 1)[0].dishes["lunch"]] == [True]
    review.accept(menu)
    assert not SlotDish.objects.filter(slot__menu=menu, proposed=True).exists()


def test_rejecting_removes_proposals_and_keeps_user_dishes(menu, team, book):
    set_day(team, TUESDAY, dishes={"dinner": [book[2]]})
    proposed_week(menu, team, book)
    review.reject(menu)
    assert list(
        SlotDish.objects.filter(slot__menu=menu).values_list("recipe__title", flat=True)
    ) == ["Minestrone"]
    assert calendar(team, THURSDAY, 1)[0].proposed_people == {}


def test_editing_a_meal_keeps_the_proposals_left_in_it(menu, team, book):
    proposed_week(menu, team, book)
    set_day(team, MONDAY, dishes={"lunch": [book[0], book[1]]})
    dishes = calendar(team, MONDAY, 1)[0].dishes["lunch"]
    assert [(d.title, d.proposed) for d in dishes] == [
        ("Pasta e ceci", True),
        ("Orata al forno", False),
    ]


def test_setting_the_people_settles_the_proposed_change(menu, team, book):
    proposed_week(menu, team, book)
    set_day(team, THURSDAY, people={"dinner": 4})
    assert calendar(team, THURSDAY, 1)[0].proposed_people == {}


def test_proposals_stay_off_the_shopping_list_until_accepted(menu, team, book):
    tomato = Ingredient.objects.create(name="pomodoro", category=IngredientCategory.VEGETABLE)
    RecipeIngredient.objects.create(recipe=book[0], ingredient=tomato, quantity=100)
    proposed_week(menu, team, book)
    assert build_shopping_list(menu) == []
    review.accept(menu)
    assert [item.name for item in build_shopping_list(menu)] == ["pomodoro"]


# -- API and worker ----------------------------------------------------------------------------


def generate(client, team, **extra):
    body = {"team": team.pk, "week_start": MONDAY.isoformat(), **extra}
    return client.post("/api/menus/generate/", body, format="json")


def test_generating_queues_one_generation_per_week(api, team):
    first = generate(api, team, use_week_settings=True)
    assert first.status_code == 202
    assert first.json()["status"] == "queued" and first.json()["use_week_settings"] is True
    assert WeeklyMenu.objects.get(team=team, week_start=MONDAY).slots.count() == 14
    second = generate(api, team)
    assert second.status_code == 409 and second.json()["id"] == first.json()["id"]
    latest = api.get(f"/api/menu-generations/?team={team.pk}&week_start={MONDAY}").json()
    assert [g["id"] for g in latest["results"]] == [first.json()["id"]]


def test_generations_follow_the_interface_language(api, team):
    response = api.post(
        "/api/menus/generate/",
        {"team": team.pk, "week_start": MONDAY.isoformat()},
        format="json",
        HTTP_ACCEPT_LANGUAGE="en",
    )
    assert MenuGeneration.objects.get(pk=response.json()["id"]).language == "en"


def test_members_generate_and_review(team, member, book):
    _, client = member
    assert generate(client, team).status_code == 202
    menu = WeeklyMenu.objects.get(team=team, week_start=MONDAY)
    proposed_week(menu, team, book)
    response = client.post(
        f"/api/menus/{menu.pk}/review/",
        {"action": "accept", "meals": [{"date": THURSDAY.isoformat(), "meal": "dinner"}]},
        format="json",
    )
    assert response.status_code == 204
    assert calendar(team, THURSDAY, 1)[0].people["dinner"] == 5


def test_other_teams_cannot_generate_or_see_generations(team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    queued(menu)
    stranger = get_user_model().objects.create_user("eve", password="pw")
    client = APIClient()
    client.force_authenticate(stranger)
    assert generate(client, team).status_code == 400
    assert client.get("/api/menu-generations/").json()["results"] == []
    assert client.post(f"/api/menus/{menu.pk}/review/", {"action": "reject"}).status_code == 404


def test_generate_validates_the_week(api, team):
    response = generate(api, team, week_start=TUESDAY.isoformat())
    assert response.status_code == 400


def test_the_worker_runs_queued_generations(menu, book, monkeypatch):
    generation = queued(menu)
    context = engine.build_context(generation)
    pasta = ref_of(context, book[0])
    chat = FakeChat(answer(meals=[meal(MONDAY, "lunch", dish(pasta))]))
    monkeypatch.setattr(engine, "get_chat_provider", lambda: chat)
    call_command("menu_worker", "--once")
    generation.refresh_from_db()
    assert generation.status == "done" and generation.started_at is not None


def test_the_worker_fails_generations_left_running(menu):
    generation = queued(menu, status=MenuGeneration.Status.RUNNING)
    call_command("menu_worker", "--once")
    generation.refresh_from_db()
    assert generation.status == "failed" and "Interrupted" in generation.error


def test_membership_fixture_is_an_owner(team, user):
    assert Membership.objects.get(team=team, user=user).role == "owner"


def test_thinking_follows_the_setting(menu, book, monkeypatch):
    from apps.siteconfig.models import ConfigVar

    ConfigVar.objects.create(key="menu.thinking", value=True)
    ConfigVar.objects.create(key="llm.context_tokens", value=65536)
    generation = queued(menu)
    context = engine.build_context(generation)
    chat = FakeChat(answer(meals=[meal(MONDAY, "lunch", dish(ref_of(context, book[0])))]))
    monkeypatch.setattr(engine, "get_reasoning_chat_provider", lambda: chat)
    monkeypatch.setattr(engine, "get_chat_provider", lambda: pytest.fail("plain chat used"))
    engine.run_generation(generation)
    generation.refresh_from_db()
    assert generation.status == "done" and generation.thinking is True
    assert chat.calls[0]["max_tokens"] == engine.MAX_THINKING_TOKENS


def test_thinking_needs_a_large_enough_context(db):
    from apps.siteconfig.models import ConfigVar

    ConfigVar.objects.create(key="menu.thinking", value=True)
    assert engine.use_thinking() is False
    ConfigVar.objects.create(key="llm.context_tokens", value=32768)
    assert engine.use_thinking() is True


def test_more_candidates_with_a_larger_context(db):
    from apps.siteconfig.models import ConfigVar

    assert engine.max_book_candidates() == 40
    ConfigVar.objects.create(key="llm.context_tokens", value=65536)
    assert engine.max_book_candidates() == 200
