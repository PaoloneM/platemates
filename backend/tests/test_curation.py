import json
from decimal import Decimal

import pytest
from django.core.management import call_command

from ai import AIError, ChatResult
from apps.accounts.models import UserProfile
from apps.curation import drafting, jobs
from apps.curation.models import SystemDraft
from apps.menus.models import MenuGeneration, WeeklyMenu
from apps.recipes.models import Recipe
from apps.teams.models import Team


class FakeChat:
    model = "fake"

    def __init__(self, *replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, messages, **kwargs):
        self.calls.append(messages)
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return ChatResult(content=reply if isinstance(reply, str) else json.dumps(reply))


def page_recipe(name, ingredients, rating=None):
    recipe = {
        "@type": "Recipe",
        "name": name,
        "recipeYield": "4",
        "recipeIngredient": ingredients,
        "recipeInstructions": [{"text": "Cuoci."}, {"text": "Servi."}],
    }
    if rating:
        recipe["aggregateRating"] = rating
    return recipe


def source(site, ingredients, rating=None, count=None):
    return drafting.Source(
        url=f"https://{site}/ricetta",
        site=site,
        title="Ribollita",
        recipe=page_recipe("Ribollita", ingredients),
        rating=rating,
        rating_count=count,
    )


DRAFT = {
    "title": "Ribollita",
    "description": "",
    "course": "first",
    "cuisine": "toscana",
    "servings": 4,
    "prep_minutes": 30,
    "cook_minutes": 120,
    "ingredients": [
        {
            "name": "cavolo nero",
            "quantity": "300",
            "unit": "g",
            "note": "",
            "optional": False,
            "category": "vegetable",
            "season_months": [11, 12, 1, 2],
        }
    ],
    "steps": ["Cuoci.", "Servi."],
    "climate_months": [11, 12, 1, 2],
}


# -- ratings -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "rating,expected",
    [
        ({"ratingValue": "4.6", "ratingCount": "120"}, (4.6, 120)),
        ({"ratingValue": "4,2", "reviewCount": 8, "bestRating": "5"}, (4.2, 8)),
        ({"ratingValue": 8, "bestRating": 10, "ratingCount": 3}, (4.0, 3)),
        ({"ratingValue": 90, "bestRating": 100, "worstRating": 0, "ratingCount": 2}, (4.5, 2)),
        ([{"ratingValue": 5, "ratingCount": 1}], (5.0, 1)),
        ({"ratingValue": 4.5}, (None, None)),  # no votes
        ({"ratingValue": 7, "ratingCount": 3}, (None, None)),  # out of scale
        ({"ratingValue": "molto buona", "ratingCount": 3}, (None, None)),
        ("4 stelle", (None, None)),
    ],
)
def test_page_ratings_are_brought_to_five_stars(rating, expected):
    assert drafting.rating_of({"aggregateRating": rating}) == expected


def test_the_web_rating_is_averaged_by_votes():
    sources = [source("a.it", [], 5.0, 10), source("b.it", [], 4.0, 30), source("c.it", [])]
    assert drafting.web_rating(sources) == (Decimal("4.25"), 40)
    assert drafting.web_rating([source("a.it", [])]) == (None, None)


def test_reliability_follows_the_sources_and_their_agreement():
    alike = [
        source("a.it", ["300 g di cavolo nero", "200 g fagioli cannellini", "pane raffermo"]),
        source(
            "b.it", ["cavolo nero 250 g", "fagioli cannellini lessati", "pane toscano raffermo"]
        ),
    ]
    unlike = [alike[0], source("c.it", ["500 g di orata", "limone", "prezzemolo"])]
    assert drafting.agreement_of(alike) >= drafting.AGREEMENT_THRESHOLD
    assert drafting.reliability_of(alike, drafting.agreement_of(alike)) == "high"
    assert drafting.reliability_of(unlike, drafting.agreement_of(unlike)) == "medium"
    assert drafting.reliability_of(alike[:1], None) == "medium"
    assert drafting.reliability_of([], None) == "low"


# -- sources -----------------------------------------------------------------------------------


def test_sources_are_verified_pages_of_different_sites():
    chat = FakeChat(
        "Ecco: https://a.it/r1 https://a.it/r2 https://nope.it/x https://b.it/r https://c.it/r"
    )
    pages = {
        "https://a.it/r1": source("a.it", ["cavolo"]),
        "https://a.it/r2": source("a.it", ["cavolo"]),
        "https://b.it/r": source("b.it", ["cavolo"]),
        "https://c.it/r": source("c.it", ["cavolo"]),
    }
    found = drafting.find_sources("ribollita", chat, verify=pages.get)
    assert [s.site for s in found] == ["a.it", "b.it"]


def test_a_search_without_urls_is_retried_once():
    chat = FakeChat("Nessun risultato.", "https://a.it/r")
    found = drafting.find_sources("ribollita", chat, verify=lambda url: source("a.it", []))
    assert len(found) == 1 and len(chat.calls) == 2


def test_no_web_search_means_no_sources():
    assert drafting.find_sources("ribollita", None) == []


# -- drafting ----------------------------------------------------------------------------------


def test_without_sources_the_model_writes_from_what_it_knows():
    chat = FakeChat(DRAFT)
    draft = drafting.draft_recipe("ribollita", [], "it", chat, 9000)
    assert draft["title"] == "Ribollita" and "No web page was found" in chat.calls[0][0]["content"]


def test_one_source_is_extracted_faithfully():
    chat = FakeChat({**DRAFT, "title": "Rewritten", "servings": 2})
    page = source("a.it", ["300 g di cavolo nero", "fagioli"])
    draft = drafting.draft_recipe("ribollita", [page], "it", chat, 9000)
    # Facts from the page's structured data win over the model's rewriting.
    assert (draft["title"], draft["servings"], draft["source_url"]) == (
        "Ribollita",
        4,
        "https://a.it/ricetta",
    )


def test_two_sources_are_combined():
    chat = FakeChat(DRAFT)
    pages = [source("a.it", ["cavolo nero"]), source("b.it", ["cavolo nero"])]
    draft = drafting.draft_recipe("ribollita", pages, "it", chat, 9000)
    prompt = chat.calls[0]
    assert "2 recipes for the same dish" in prompt[0]["content"]
    assert "Source 1" in prompt[1]["content"] and "Source 2" in prompt[1]["content"]
    assert draft["source_url"] == "https://a.it/ricetta"


def test_dishes_for_a_theme_leave_out_existing_system_recipes(db):
    Recipe.objects.create(title="Ribollita", owner_team=Team.system())
    chat = FakeChat({"dishes": ["Ribollita", "Pappa al pomodoro", "Pappa al pomodoro", " "]})
    assert drafting.dishes_for_theme("zuppe toscane", 3, "it", chat) == ["Pappa al pomodoro"]
    assert "Ribollita" in chat.calls[0][0]["content"]


# -- running a draft ---------------------------------------------------------------------------


@pytest.fixture
def queued(db):
    return SystemDraft.objects.create(dish="ribollita", status=SystemDraft.Status.RUNNING)


def staff_events(sent):
    return [(d["phase"], d["status"]) for room, event, d in sent if event == "system_draft"]


def test_a_draft_becomes_ready_with_its_ratings(queued, realtime_events):
    pages = {
        "https://a.it/r": source("a.it", ["cavolo nero", "fagioli cannellini"], 4.5, 10),
        "https://b.it/r": source("b.it", ["cavolo nero", "fagioli cannellini"], 4.0, 10),
    }
    search = FakeChat("https://a.it/r https://b.it/r")
    jobs.run_draft(queued, chat=FakeChat(DRAFT), search_chat=search, verify=pages.get)
    queued.refresh_from_db()
    assert queued.status == "ready" and queued.reliability == "high"
    assert (queued.web_rating, queued.web_rating_count) == (Decimal("4.25"), 20)
    assert [s["site"] for s in queued.sources] == ["a.it", "b.it"]
    assert queued.draft["title"] == "Ribollita"
    assert staff_events(realtime_events) == [
        ("searching", "running"),
        ("drafting", "running"),
        ("ready", "ready"),
    ]
    assert {room for room, _, _ in realtime_events} == {"staff"}


def test_a_draft_without_sources_is_low_reliability(queued):
    jobs.run_draft(
        queued, chat=FakeChat(DRAFT), search_chat=FakeChat("niente", "niente"), verify=dict().get
    )
    queued.refresh_from_db()
    assert (queued.status, queued.reliability, queued.web_rating) == ("ready", "low", None)


def test_a_dish_the_model_does_not_know_fails(queued):
    empty = {**DRAFT, "title": "", "ingredients": [], "steps": []}
    jobs.run_draft(queued, chat=FakeChat(empty), search_chat=None, verify=dict().get)
    queued.refresh_from_db()
    assert queued.status == "failed" and "no recipe" in queued.error


def test_an_unavailable_model_fails_the_draft(queued):
    jobs.run_draft(queued, chat=FakeChat(AIError("Studio is down")), search_chat=None)
    queued.refresh_from_db()
    assert (queued.status, queued.error) == ("failed", "Studio is down")


def test_a_stopping_worker_interrupts_the_draft(queued):
    jobs.run_draft(queued, chat=FakeChat(DRAFT), search_chat=None, should_stop=lambda: True)
    queued.refresh_from_db()
    assert queued.status == "failed" and queued.error.startswith("Interrupted")


def test_the_worker_runs_menu_generations_before_drafts(team, monkeypatch):
    order = []
    draft = SystemDraft.objects.create(dish="ribollita")
    menu = WeeklyMenu.objects.create(team=team, week_start="2026-10-05")
    generation = MenuGeneration.objects.create(menu=menu)
    monkeypatch.setattr(
        "apps.menus.generation.run_generation", lambda g, **kw: order.append(("menu", g.pk))
    )
    monkeypatch.setattr(jobs, "run_draft", lambda d, **kw: order.append(("draft", d.pk)))
    call_command("worker", "--once")
    assert order == [("menu", generation.pk), ("draft", draft.pk)]


# -- API and publishing ------------------------------------------------------------------------


@pytest.fixture
def staff(api, user):
    user.is_staff = True
    user.save()
    return api


def test_only_staff_handle_drafts(api, team):
    assert api.get("/api/system-drafts/").status_code == 403
    assert api.post("/api/system-drafts/", {"dishes": ["x"]}, format="json").status_code == 403


def test_staff_request_dishes_by_name(staff, realtime_events, django_capture_on_commit_callbacks):
    with django_capture_on_commit_callbacks(execute=True):
        response = staff.post(
            "/api/system-drafts/",
            {"dishes": ["Ribollita", " ribollita ", "Ribollita"]},
            format="json",
        )
    assert response.status_code == 201
    assert [d["dish"] for d in response.json()] == ["Ribollita", "ribollita"]
    assert staff_events(realtime_events) == [("queued", "queued"), ("queued", "queued")]


def test_staff_request_a_theme(staff, monkeypatch):
    monkeypatch.setattr(
        "apps.curation.views.get_chat_provider",
        lambda: FakeChat({"dishes": ["Pappa al pomodoro", "Acquacotta"]}),
    )
    response = staff.post("/api/system-drafts/", {"theme": "zuppe toscane", "count": 2})
    assert [d["dish"] for d in response.json()] == ["Pappa al pomodoro", "Acquacotta"]


@pytest.mark.parametrize("body", [{}, {"dishes": ["a"], "theme": "b"}, {"dishes": ["  "]}])
def test_a_request_is_dishes_or_a_theme(staff, body):
    assert staff.post("/api/system-drafts/", body, format="json").status_code == 400


def ready_draft():
    return SystemDraft.objects.create(
        dish="ribollita",
        status=SystemDraft.Status.READY,
        draft=DRAFT,
        reliability="high",
        web_rating=Decimal("4.40"),
        web_rating_count=55,
    )


def test_a_draft_detail_brings_the_ingredient_matches(staff):
    draft = ready_draft()
    detail = staff.get(f"/api/system-drafts/{draft.pk}/").json()
    assert len(detail["matches"]) == 1 and detail["reliability"] == "high"


def test_drafts_are_counted_by_status(staff, api):
    ready_draft()
    ready_draft()
    SystemDraft.objects.create(dish="x", status=SystemDraft.Status.FAILED)
    counts = staff.get("/api/system-drafts/counts/").json()
    assert counts == {
        "queued": 0,
        "running": 0,
        "ready": 2,
        "failed": 1,
        "published": 0,
        "discarded": 0,
    }


def test_discarding_and_retrying(staff):
    draft = ready_draft()
    assert staff.post(f"/api/system-drafts/{draft.pk}/discard/").json()["status"] == "discarded"
    assert staff.post(f"/api/system-drafts/{draft.pk}/retry/").json()["status"] == "queued"
    assert staff.post(f"/api/system-drafts/{draft.pk}/retry/").status_code == 400


def test_a_discarded_draft_is_retried_for_a_reworded_dish(staff, realtime_events):
    draft = ready_draft()
    staff.post(f"/api/system-drafts/{draft.pk}/discard/")
    retried = staff.post(
        f"/api/system-drafts/{draft.pk}/retry/", {"dish": "  ribollita   toscana "}, format="json"
    ).json()
    assert (retried["dish"], retried["status"]) == ("ribollita toscana", "queued")
    assert retried["draft"] is None and retried["sources"] == [] and retried["web_rating"] is None
    assert staff.post(f"/api/system-drafts/{draft.pk}/discard/").status_code == 200
    blank = staff.post(f"/api/system-drafts/{draft.pk}/retry/", {"dish": " "}, format="json")
    assert blank.status_code == 400


def test_a_discarded_draft_is_restored_as_it_was(staff):
    draft = ready_draft()
    assert staff.post(f"/api/system-drafts/{draft.pk}/restore/").status_code == 400  # not discarded
    staff.post(f"/api/system-drafts/{draft.pk}/discard/")
    restored = staff.post(f"/api/system-drafts/{draft.pk}/restore/").json()
    assert restored["status"] == "ready" and restored["draft"]["title"] == "Ribollita"
    empty = SystemDraft.objects.create(dish="x", status=SystemDraft.Status.DISCARDED)
    assert staff.post(f"/api/system-drafts/{empty.pk}/restore/").status_code == 400


def publish(client, draft, team=None):
    return client.post(
        "/api/recipes/",
        {
            "team": (team or Team.system()).pk,
            "title": "Ribollita",
            "servings": 4,
            "visibility": "shared",
            "system_draft": draft.pk,
        },
        format="json",
    )


def test_publishing_a_draft_makes_a_system_recipe_with_its_web_rating(staff):
    draft = ready_draft()
    recipe = publish(staff, draft).json()
    assert recipe["author"]["kind"] == "system"
    assert (recipe["web_rating"], recipe["web_rating_count"]) == ("4.40", 55)
    draft.refresh_from_db()
    assert draft.status == "published" and draft.recipe_id == recipe["id"]
    assert publish(staff, draft).status_code == 400  # not twice


def test_a_draft_is_published_only_as_a_system_recipe(staff, team):
    assert publish(staff, ready_draft(), team=team).status_code == 400


def test_the_web_rating_cannot_be_written(staff, team):
    created = staff.post(
        "/api/recipes/",
        {"team": team.pk, "title": "x", "visibility": "private", "web_rating": "5.00"},
        format="json",
    ).json()
    assert created["web_rating"] is None


def test_staff_join_their_own_room(user, team, monkeypatch):
    from django.test import Client

    from apps.realtime import server

    monkeypatch.setattr(server, "close_old_connections", lambda: None)
    user.is_staff = True
    user.save()
    UserProfile.objects.create(user=user)
    client = Client()
    client.force_login(user)
    cookie = f"sessionid={client.cookies['sessionid'].value}"
    assert server.rooms_of(cookie, "admin")[1] == [f"team-{team.pk}", "staff"]
    # On the public plane a staff account is an ordinary member (apps/core/planes.py).
    assert server.rooms_of(cookie, "public")[1] == [f"team-{team.pk}"]
    # Administrators also join theirs (imports' progress), on the admin plane only.
    UserProfile.objects.filter(user=user).update(is_admin=True)
    assert server.rooms_of(cookie, "admin")[1] == [f"team-{team.pk}", "staff", "admin"]
    assert server.rooms_of(cookie, "public")[1] == [f"team-{team.pk}"]
