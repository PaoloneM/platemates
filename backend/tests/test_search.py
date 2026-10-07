import json

import pytest

from ai import AIUnavailableError, ChatResult
from apps.assistant import search
from apps.assistant.agent import run_turn
from apps.assistant.models import AssistantSession, Mode
from apps.assistant.web import count_jsonld_recipes
from apps.catalog.models import Ingredient
from apps.recipes import embeddings
from apps.recipes.models import Recipe, RecipeEmbedding, Visibility
from apps.teams.models import RecipeBookEntry, Team

# -- embeddings -------------------------------------------------------------------------------


class FakeEmbeddings:
    """Vectors from keywords, so similarity is predictable."""

    model = "fake-embeddings"
    AXES = ["zucca", "patat", "pesce", "dolce"]

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[1.0 if axis in t.lower() else 0.01 for axis in self.AXES] for t in texts]


class DownEmbeddings:
    model = "down"

    def embed(self, texts):
        raise AIUnavailableError("embedding service down")


@pytest.fixture
def fake_embeddings(monkeypatch):
    provider = FakeEmbeddings()
    monkeypatch.setattr(embeddings, "get_embedding_provider", lambda: provider)
    return provider


def recipe(team, title, *ingredients, visibility=Visibility.SHARED):
    r = Recipe.objects.create(title=title, owner_team=team, visibility=visibility)
    for name in ingredients:
        r.ingredients.create(ingredient=Ingredient.objects.get_or_create(name=name)[0])
    RecipeBookEntry.objects.create(team=team, recipe=r, status="approved")
    return r


def test_recipes_are_reembedded_only_when_they_change(team, fake_embeddings):
    soup = recipe(team, "Vellutata di zucca", "zucca")
    assert embeddings.refresh_embedding(soup)
    assert embeddings.refresh_embedding(soup)
    assert fake_embeddings.calls == 1  # unchanged document: skipped
    soup.title = "Crema di zucca"
    soup.save()
    embeddings.refresh_embedding(soup)
    assert fake_embeddings.calls == 2
    assert RecipeEmbedding.objects.get(recipe=soup).model == "fake-embeddings"


def test_a_down_embedding_service_never_breaks_saving(team):
    soup = recipe(team, "Vellutata di zucca", "zucca")
    assert embeddings.refresh_embedding(soup, DownEmbeddings()) is False
    assert not RecipeEmbedding.objects.exists()


def test_similar_recipes_respect_visibility(team, user, fake_embeddings):
    other = Team.objects.create(name="Other")
    pumpkin = recipe(team, "Risotto alla zucca", "zucca")
    secret = recipe(other, "Zucca segreta", "zucca", visibility=Visibility.PRIVATE)
    recipe(team, "Torta", "dolce")
    for r in Recipe.objects.all():
        embeddings.refresh_embedding(r)
    found = [r for r, _ in embeddings.similar_recipes(user, "qualcosa con la zucca")]
    assert pumpkin in found
    assert secret not in found  # another team's private recipe


# -- local search -----------------------------------------------------------------------------


def test_keywords_are_rough_stems_without_filler():
    assert search.keywords("qualcosa con le patate e i porri") == ["patat", "porr"]


def test_all_keywords_must_match(team, user, fake_embeddings):
    recipe(team, "Vellutata di porri", "porro", "patata", "paprika dolce")
    recipe(team, "Purè", "patata")
    titles = lambda q: [r["title"] for r in search.local_results(user, team, q)]  # noqa: E731
    assert titles("patate e porri")[0] == "Vellutata di porri"
    # "dolce" matches the paprika, but "cioccolato" matches nothing: no keyword match.
    assert "Vellutata di porri" not in titles("un dolce al cioccolato")


def test_local_results_tell_book_from_shared(team, user, fake_embeddings):
    other = Team.objects.create(name="Other")
    mine = recipe(team, "Zucca al forno", "zucca")
    theirs = recipe(other, "Zucca in agrodolce", "zucca")
    kinds = {r["recipe"]: r["kind"] for r in search.local_results(user, team, "zucca")}
    assert kinds == {mine.pk: "book", theirs.pk: "shared"}


# -- web search -------------------------------------------------------------------------------


class FakeChat:
    model = "fake"

    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def dishes(*names):
    return ChatResult(content=json.dumps({"dishes": list(names)}))


def listing(*urls):
    return ChatResult(content="\n".join(f"Ricetta - {u}" for u in urls))


def verify_known(pages):
    return lambda url: (
        {"kind": "web", "url": url, "site": "x.it", "title": pages[url], "servings": 4}
        if url in pages
        else None
    )


def test_web_results_come_from_verified_pages_per_dish(db):
    chat = FakeChat(dishes("Orata al forno", "Branzino al cartoccio"))
    search_chat = FakeChat(
        listing("https://a.it/orata", "https://a.it/collection", "https://b.it/orata"),
        listing("https://c.it/branzino"),
    )
    pages = {
        "https://a.it/orata": "Orata",
        "https://b.it/orata": "Orata 2",
        "https://c.it/branzino": "Branzino",
    }
    results, notice = search.web_results(
        "secondo di pesce", "Italian", search_chat, chat, verify=verify_known(pages)
    )
    assert notice is None
    assert [(r["title"], r["dish"]) for r in results] == [
        ("Orata", "Orata al forno"),
        ("Orata 2", "Orata al forno"),
        ("Branzino", "Branzino al cartoccio"),
    ]
    assert search_chat.sent[0][0][0]["content"].startswith("Do one web search for: ricetta ")


def test_a_failed_web_search_is_retried(db):
    chat = FakeChat(dishes("Polpette al sugo"))
    search_chat = FakeChat(
        ChatResult(content="Sorry, the search tool had a technical error."),
        listing("https://a.it/polpette"),
    )
    results, _ = search.web_results(
        "polpette",
        "Italian",
        search_chat,
        chat,
        verify=verify_known({"https://a.it/polpette": "Polpette"}),
    )
    assert [r["title"] for r in results] == ["Polpette"]


def test_without_a_web_search_provider(db):
    assert search.web_results("x", "Italian", None) == ([], "web_search_unavailable")


def test_collection_pages_declare_several_recipes():
    page = (
        '<script type="application/ld+json">{"@type": "ItemList", "itemListElement": '
        '[{"@type": "Recipe", "name": "a"}, {"@type": "Recipe", "name": "b"}]}</script>'
    )
    assert count_jsonld_recipes(page) == 2


# -- in the conversation ----------------------------------------------------------------------


@pytest.fixture
def session(team, user):
    return AssistantSession.objects.create(team=team, user=user, mode=Mode.SEARCH)


def test_a_search_turn_records_results(session, fake_embeddings):
    recipe(session.team, "Zucca al forno", "zucca")
    for r in Recipe.objects.all():
        embeddings.refresh_embedding(r)
    chat = FakeChat(dishes("Risotto alla zucca"))
    search_chat = FakeChat(listing("https://a.it/risotto"))
    run_turn(
        session,
        "qualcosa con la zucca",
        chat=chat,
        search_chat=search_chat,
        verify_page=verify_known({"https://a.it/risotto": "Risotto alla zucca"}),
    )
    session.refresh_from_db()
    results = session.messages[-1]["results"]
    assert [r["kind"] for r in results] == ["book", "web"]
    assert session.mode == Mode.SEARCH


def test_picking_a_web_result_turns_the_conversation_into_an_import(session):
    extracted = {
        "title": "Risotto",
        "servings": 4,
        "ingredients": [
            {
                "name": "riso",
                "quantity": 320,
                "unit": "g",
                "category": "cereal",
                "season_months": [],
            }
        ],
        "steps": ["Cuocere."],
    }
    chat = FakeChat(ChatResult(content=json.dumps(extracted)))
    from apps.assistant.web import PageRecipe

    run_turn(
        session,
        "https://a.it/risotto",
        chat=chat,
        read_page=lambda url: PageRecipe(url=url, text="Risotto " * 50, structured=False),
    )
    session.refresh_from_db()
    assert session.mode == Mode.LINK
    assert session.draft["title"] == "Risotto"
