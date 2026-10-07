import json

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from ai import AIUnavailableError, ChatResult
from apps.assistant.agent import HISTORY_BUDGET_CHARS, _trim, run_turn
from apps.assistant.draft import normalize_draft
from apps.assistant.models import AssistantSession
from apps.catalog.matching import match_ingredient
from apps.catalog.models import Ingredient
from apps.recipes.models import Recipe

DRAFT = {
    "title": "Frittata di zucchine",
    "course": "main",
    "servings": 3,
    "ingredients": [
        {"name": "Uova", "quantity": 5, "unit": "pc", "category": "egg"},
        {"name": "parmigiano", "quantity": 50, "unit": "g", "category": "cheese"},
        {"name": "zucchina", "quantity": 0.5, "unit": "kg", "season_months": [5, 6, 7]},
        {"name": "sale", "quantity": 3, "unit": "q.b."},
    ],
    "steps": ["Sbattere le uova.", " ", "Cuocere in padella."],
}


class FakeChat:
    """Replays canned model answers and records what it was sent."""

    model = "fake"

    def __init__(self, *results):
        self.results = list(results)
        self.sent = []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def proposing(draft, text=""):
    call = {
        "id": "call-1",
        "type": "function",
        "function": {"name": "propose_recipe", "arguments": json.dumps(draft)},
    }
    return ChatResult(content=text, tool_calls=[call], finish_reason="tool_calls")


# -- draft normalization ----------------------------------------------------------------------


def test_draft_is_normalized():
    draft = normalize_draft(DRAFT)
    eggs, cheese, zucchini, salt = draft["ingredients"]
    assert eggs == {
        "name": "uova",
        "quantity": "5",
        "unit": "pc",
        "note": "",
        "optional": False,
        "category": "egg",
        "season_months": [],
    }
    assert cheese["quantity"] == "50"  # never "5E+1"
    assert (zucchini["quantity"], zucchini["unit"]) == ("500", "g")  # kg converted
    assert (salt["quantity"], salt["unit"]) == (None, "tt")
    assert draft["steps"] == ["Sbattere le uova.", "Cuocere in padella."]


def test_unknown_values_fall_back_safely():
    draft = normalize_draft(
        {
            "title": "x",
            "course": "brunch",
            "servings": "many",
            "ingredients": [
                {"name": "", "quantity": 1, "unit": "g"},
                {
                    "name": "farina",
                    "quantity": "lots",
                    "unit": "g",
                    "category": "powder",
                    "season_months": [0, 13, 3],
                },
            ],
        }
    )
    assert draft["course"] == "single"
    assert draft["servings"] == 2
    [flour] = draft["ingredients"]
    assert (flour["quantity"], flour["category"], flour["season_months"]) == (None, "other", [3])


# -- ingredient matching ----------------------------------------------------------------------


def test_matching_exact_alias_and_similar(db):
    tomato = Ingredient.objects.create(name="pomodoro", aliases=["pomodori pelati"])
    assert match_ingredient("Pomodoro")["match"] == tomato.pk
    assert match_ingredient("pomodori pelati")["exact"] is True
    similar = match_ingredient("pomodori")
    assert similar["exact"] is False
    assert similar["candidates"][0]["id"] == tomato.pk
    assert similar["match"] == tomato.pk  # similar enough to be preselected
    assert match_ingredient("cioccolato") == {"match": None, "exact": False, "candidates": []}


# -- one turn ---------------------------------------------------------------------------------


@pytest.fixture
def session(team, user):
    return AssistantSession.objects.create(team=team, user=user)


def test_a_proposal_becomes_the_draft(session):
    chat = FakeChat(proposing(DRAFT))
    result = run_turn(session, "Frittata di zucchine per 3", chat=chat)
    session.refresh_from_db()
    assert result.draft_updated
    assert session.draft["title"] == "Frittata di zucchine"
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "tool"]  # tool call and its result stay paired
    messages, kwargs = chat.sent[0]
    assert messages[0]["role"] == "system" and "Italian" in messages[0]["content"]
    assert kwargs["tools"][0]["function"]["name"] == "propose_recipe"


def test_a_question_leaves_the_draft_alone(session):
    run_turn(session, "una torta", chat=FakeChat(ChatResult(content="Quale torta?")))
    session.refresh_from_db()
    assert session.draft is None
    assert session.messages[-1] == {"role": "assistant", "content": "Quale torta?"}


def test_unreadable_tool_arguments_are_reported_back_to_the_model(session):
    broken = ChatResult(
        content="",
        tool_calls=[{"id": "c", "function": {"name": "propose_recipe", "arguments": "{not json"}}],
    )
    result = run_turn(session, "x", chat=FakeChat(broken))
    assert not result.draft_updated
    assert "could not be read" in session.messages[-1]["content"]


def test_history_is_trimmed_at_user_turns():
    long = "x" * 3000
    history = [
        {"role": "user", "content": long},
        {"role": "assistant", "content": "", "tool_calls": [{"id": "a"}]},
        {"role": "tool", "tool_call_id": "a", "content": long},
        {"role": "user", "content": long},
        {"role": "assistant", "content": long},
        {"role": "user", "content": "last"},
    ]
    trimmed = _trim(history)
    assert trimmed[0]["role"] == "user"
    assert sum(len(json.dumps(m)) for m in trimmed) <= HISTORY_BUDGET_CHARS
    assert trimmed[-1]["content"] == "last"


# -- API --------------------------------------------------------------------------------------


@pytest.fixture
def fake_chat(monkeypatch):
    def install(*results):
        chat = FakeChat(*results)
        monkeypatch.setattr("apps.assistant.agent.get_chat_provider", lambda: chat)
        return chat

    return install


def test_conversation_through_the_api(api, team, fake_chat):
    Ingredient.objects.create(name="uova")
    fake_chat(ChatResult(content="Quante persone?"), proposing(DRAFT))
    created = api.post("/api/assistant/sessions/", {"team": team.pk, "mode": "tell"}, format="json")
    assert created.status_code == 201
    url = f"/api/assistant/sessions/{created.json()['id']}/"

    first = api.post(url + "messages/", {"text": "Frittata di zucchine"}, format="json").json()
    assert first["transcript"][-1] == {
        "role": "assistant",
        "text": "Quante persone?",
        "draft": False,
    }
    second = api.post(url + "messages/", {"text": "Per 3"}, format="json").json()
    assert second["draft"]["servings"] == 3
    assert second["transcript"][-1]["draft"] is True
    assert second["matches"][0]["exact"] is True  # "uova" is in the catalog
    assert second["matches"][2]["match"] is None


def test_unknown_modes_are_refused(api, team):
    response = api.post(
        "/api/assistant/sessions/", {"team": team.pk, "mode": "dance"}, format="json"
    )
    assert response.status_code == 400


def test_sessions_are_private_to_their_author(api, team, user):
    session = AssistantSession.objects.create(team=team, user=user)
    other = get_user_model().objects.create_user("eve")
    client = APIClient()
    client.force_authenticate(other)
    assert client.get(f"/api/assistant/sessions/{session.pk}/").status_code == 404


def test_model_outage_is_a_503(api, team, user, fake_chat):
    fake_chat(AIUnavailableError("down"))
    session = AssistantSession.objects.create(team=team, user=user)
    response = api.post(
        f"/api/assistant/sessions/{session.pk}/messages/", {"text": "x"}, format="json"
    )
    assert response.status_code == 503


def test_closing_links_the_saved_recipe(api, team, user):
    session = AssistantSession.objects.create(team=team, user=user)
    recipe = Recipe.objects.create(title="x", owner_team=team)
    closed = api.post(
        f"/api/assistant/sessions/{session.pk}/close/", {"recipe": recipe.pk}, format="json"
    ).json()
    assert (closed["status"], closed["recipe"]) == ("saved", recipe.pk)
    again = api.post(
        f"/api/assistant/sessions/{session.pk}/messages/", {"text": "x"}, format="json"
    )
    assert again.status_code == 409


def test_preserved_products_are_all_year_whatever_the_model_says():
    draft = normalize_draft(
        {
            "title": "Sugo",
            "servings": 4,
            "steps": [],
            "ingredients": [
                {
                    "name": "pomodoro pelato",
                    "quantity": 400,
                    "unit": "g",
                    "season_months": [6, 7, 8],
                },
                {
                    "name": "pisello surgelato",
                    "quantity": 200,
                    "unit": "g",
                    "season_months": [4, 5],
                },
                {"name": "pomodoro", "quantity": 400, "unit": "g", "season_months": [6, 7, 8]},
            ],
        }
    )
    assert [i["season_months"] for i in draft["ingredients"]] == [[], [], [6, 7, 8]]
