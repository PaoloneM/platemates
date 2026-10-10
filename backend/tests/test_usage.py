"""What the AI providers consumed: reported by `ai/`, attributed to a team and a feature,
priced from the administrators' list."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest

from ai import usage as ai_usage
from ai.anthropic import AnthropicChat
from ai.openai_compatible import OpenAICompatibleEmbeddings
from ai.usage import Usage
from apps.accounts.models import UserProfile
from apps.recipes.embeddings import refresh_embedding
from apps.recipes.models import Recipe
from apps.usage.context import attribute, carry, current
from apps.usage.models import AIUsage, Feature, ModelPrice


def client(handler):
    return httpx.Client(base_url="http://ai.test", transport=httpx.MockTransport(handler))


@pytest.fixture
def reported(monkeypatch):
    """What providers report, without the database."""
    seen = []
    monkeypatch.setattr(ai_usage, "_recorder", seen.append)
    return seen


@pytest.fixture
def admin(user):
    UserProfile.objects.create(user=user, is_admin=True)
    return user


# -- providers report what they used -----------------------------------------------------------


def test_claude_reports_tokens_and_searches(reported):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "ok"}],
                "usage": {
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "cache_read_input_tokens": 5,
                    "cache_creation_input_tokens": 7,
                    "server_tool_use": {"web_search_requests": 1},
                },
            },
        )

    chat = AnthropicChat(base_url="http://ai.test", model="claude-x", client=client(handler))
    chat.chat([{"role": "user", "content": "x"}])
    assert reported == [
        Usage("anthropic", "claude-x", "chat", 120, 30, 5, 7, 1),
    ]


def test_claude_streams_report_the_final_counts(reported):
    events = [
        {"type": "message_start", "message": {"usage": {"input_tokens": 50, "output_tokens": 1}}},
        {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "ok"}},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 40},
        },
    ]
    stream = "".join(f"data: {json.dumps(e)}\n\n" for e in events)
    chat = AnthropicChat(
        base_url="http://ai.test",
        model="claude-x",
        client=client(lambda request: httpx.Response(200, text=stream)),
    )
    chat.chat_stream([{"role": "user", "content": "x"}], on_delta=lambda kind, text: None)
    assert (reported[0].input_tokens, reported[0].output_tokens) == (50, 40)


def test_embeddings_report_under_the_configured_provider(reported):
    def handler(request):
        return httpx.Response(
            200, json={"data": [{"index": 0, "embedding": [0.1]}], "usage": {"prompt_tokens": 9}}
        )

    embed = OpenAICompatibleEmbeddings(
        base_url="http://ai.test",
        model="text-embedding-3-small",
        provider="openai",
        client=client(handler),
    )
    embed.embed(["zuppa"])
    assert reported == [Usage("openai", "text-embedding-3-small", "embeddings", 9)]


def test_a_failing_recorder_never_fails_the_call(monkeypatch):
    def broken(usage):
        raise RuntimeError("database down")

    monkeypatch.setattr(ai_usage, "_recorder", broken)
    ai_usage.report(Usage("anthropic", "m", "chat"))  # no exception


# -- attribution -------------------------------------------------------------------------------


def test_usage_is_attributed_to_the_team_and_feature_at_work(team):
    with attribute(team=team, feature=Feature.ASSISTANT):
        ai_usage.report(Usage("anthropic", "claude-x", "chat", 10, 2))
    ai_usage.report(Usage("anthropic", "claude-x", "chat", 1, 1))

    first, second = AIUsage.objects.order_by("pk")
    assert (first.team, first.feature, first.input_tokens) == (team, "assistant", 10)
    assert (second.team, second.feature) == (None, "other")


def test_threads_carry_the_attribution(team, monkeypatch):
    # What the recorder would see in each thread (test threads cannot write to the test
    # database: its transaction is not theirs).
    seen = []
    monkeypatch.setattr(ai_usage, "_recorder", lambda usage: seen.append(current()))

    def work(n):
        ai_usage.report(Usage("anthropic", "claude-x", "chat", n))

    with attribute(team=team, feature=Feature.ASSISTANT), ThreadPoolExecutor(2) as pool:
        list(pool.map(carry(work), [1, 2, 3]))

    assert {(a.team_id, a.feature) for a in seen} == {(team.pk, "assistant")}
    assert len(seen) == 3


def test_recipe_embeddings_are_billed_to_the_recipe_team(team):
    recipe = Recipe.objects.create(title="Zuppa", owner_team=team)

    class Provider:
        model = "text-embedding-3-small"

        def embed(self, texts):
            ai_usage.report(Usage("openai", self.model, "embeddings", 5))
            return [[0.1, 0.2]]

    with attribute(team=None, feature=Feature.OTHER):
        refresh_embedding(recipe, Provider())

    row = AIUsage.objects.get()
    assert (row.team, row.feature) == (team, "embeddings")


# -- the report --------------------------------------------------------------------------------


def test_administrators_see_usage_and_estimated_costs(api, admin, team):
    with attribute(team=team, feature=Feature.MENU):
        ai_usage.report(
            Usage("anthropic", "claude-sonnet-5-5", "chat", 1_000_000, 100_000, 0, 0, 2)
        )
    with attribute(team=team, feature=Feature.ASSISTANT):
        ai_usage.report(Usage("unsloth_studio", "local-model", "chat", 500, 50))

    data = api.get("/api/usage/").json()

    # Sonnet 5.5: $2 per M input + $10 per M output x 0.1 M + 2 searches at $10/1000.
    assert Decimal(str(data["totals"]["cost"])) == Decimal("3.02")
    [mine] = data["teams"]
    assert mine["team"] == "Test team" and mine["calls"] == 2 and mine["unpriced_calls"] == 1
    assert Decimal(str(mine["features"]["menu"])) == Decimal("3.02")
    models = {m["model"]: m for m in data["models"]}
    assert models["local-model"]["priced"] is False
    assert data["months"] == [data["month"]]


def test_prices_are_kept_by_administrators(api, user, admin):
    price = ModelPrice.objects.get(model="claude-sonnet-5-5")
    url = f"/api/usage/prices/{price.pk}/"
    assert api.patch(url, {"input_per_mtok": "2.5"}, format="json").status_code == 200
    price.refresh_from_db()
    assert price.input_per_mtok == Decimal("2.5") and price.updated_by == user


def test_usage_is_for_administrators_only(api):
    assert api.get("/api/usage/").status_code == 403
    assert api.get("/api/usage/prices/").status_code == 403
