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


def recipe(team, title, *ingredients, visibility=Visibility.SHARED, category="other"):
    r = Recipe.objects.create(title=title, owner_team=team, visibility=visibility)
    for name in ingredients:
        ingredient = Ingredient.objects.get_or_create(name=name, defaults={"category": category})
        r.ingredients.create(ingredient=ingredient[0])
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
    found = [r for r, _ in embeddings.similar_recipes(user, ["qualcosa con la zucca"])]
    assert pumpkin in found
    assert secret not in found  # another team's private recipe


# -- local search -----------------------------------------------------------------------------


def embed_all():
    for r in Recipe.objects.all():
        embeddings.refresh_embedding(r)


def titles(user, team, request):
    if isinstance(request, str):
        request = search.plain_request(request)
    return [r["title"] for r in search.local_results(user, team, request)]


def test_keywords_are_the_meaningful_words():
    assert search.keywords("qualcosa con le patate e i porri") == ["patate", "porri"]


def test_all_keywords_must_match_by_italian_stems(team, user, fake_embeddings):
    recipe(team, "Vellutata di porri", "porro", "patata", "paprika dolce")
    recipe(team, "Purè", "patata")
    assert titles(user, team, "patate e porri") == ["Vellutata di porri"]
    # "dolce" matches the paprika, but "cioccolato" matches nothing: no keyword match.
    assert "Vellutata di porri" not in titles(user, team, "un dolce al cioccolato")


def test_basic_ingredients_say_nothing_about_a_dish(team, user, fake_embeddings):
    salt = Ingredient.objects.create(name="sale", basic=True)
    soup = recipe(team, "Vellutata di zucca", "zucca")
    soup.ingredients.create(ingredient=salt)
    assert "sale" not in embeddings.recipe_document(soup)
    assert "zucca" in embeddings.recipe_document(soup)
    assert titles(user, team, "sale") == []


def test_marking_an_ingredient_basic_reembeds_its_recipes(
    api, user, team, fake_embeddings, django_capture_on_commit_callbacks
):
    user.is_staff = True
    user.save()
    soup = recipe(team, "Vellutata di zucca", "zucca", "panna")
    embed_all()
    calls = fake_embeddings.calls
    cream = Ingredient.objects.get(name="panna")
    with django_capture_on_commit_callbacks(execute=True):
        response = api.patch(f"/api/ingredients/{cream.pk}/", {"basic": True}, format="json")
    assert response.json()["basic"] is True
    assert fake_embeddings.calls == calls  # the save only queued it
    embeddings.embed_pending()  # the worker
    assert fake_embeddings.calls == calls + 1
    assert "panna" not in embeddings.recipe_document(soup)


def test_what_the_request_rules_out_is_never_offered(team, user, fake_embeddings):
    recipe(team, "Pesce al forno con patate", "orata", category="fish")
    recipe(team, "Patate al forno", "patata")
    embed_all()
    request = search.Request(
        query="patate al forno", keywords=["patate"], dishes=[], exclude_categories=["fish"]
    )
    assert titles(user, team, request) == ["Patate al forno"]
    request.exclude_categories, request.exclude_ingredients = [], ["orata"]
    assert titles(user, team, request) == ["Patate al forno"]


def test_only_recipes_close_to_the_best_are_offered(team, user, fake_embeddings):
    recipe(team, "Torta di zucca", "zucca", "dolce")  # zucca and dolce
    recipe(team, "Crema di zucca", "zucca")  # zucca only: far from the best
    embed_all()
    request = search.Request(query="dolce zucca", keywords=[], dishes=[])
    assert titles(user, team, request) == ["Torta di zucca"]


def test_the_margin_counts_from_the_best_keyword_match_too(team, user, fake_embeddings):
    recipe(team, "Torta di zucca", "zucca", "dolce")
    recipe(team, "Crema di zucca", "zucca")  # similar enough alone, far from the best
    embed_all()
    request = search.Request(query="dolce zucca", keywords=["torta"], dishes=[])
    assert titles(user, team, request) == ["Torta di zucca"]


def test_a_keyword_match_is_offered_even_when_not_similar(team, user, fake_embeddings):
    recipe(team, "Hummus di ceci", "cece")
    recipe(team, "Torta di zucca", "zucca")
    embed_all()
    request = search.Request(query="zucca", keywords=["ceci"], dishes=[])
    assert titles(user, team, request)[:2] == ["Torta di zucca", "Hummus di ceci"]


def test_local_results_tell_book_from_shared(team, user, fake_embeddings):
    other = Team.objects.create(name="Other")
    mine = recipe(team, "Zucca al forno", "zucca")
    theirs = recipe(other, "Zucca in agrodolce", "zucca")
    request = search.plain_request("zucca")
    kinds = {r["recipe"]: r["kind"] for r in search.local_results(user, team, request)}
    assert kinds == {mine.pk: "book", theirs.pk: "shared"}


# -- the search probe (Manage) -----------------------------------------------------------------


@pytest.fixture
def admin(user):
    from apps.accounts.models import UserProfile

    UserProfile.objects.create(user=user, is_admin=True)
    return user


def test_the_probe_shows_every_candidate_and_what_is_offered(api, admin, team, fake_embeddings):
    recipe(team, "Torta di zucca", "zucca", "dolce")
    recipe(team, "Crema di zucca", "zucca")
    embed_all()
    body = {"text": "dolce zucca", "plain": True}
    response = api.post("/api/search-probe/", body, format="json")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["request"]["keywords"] == ["dolce", "zucca"]
    assert data["tuning"] == {"min_similarity": 40, "margin": 6, "keyword_bonus": 10}
    assert [(r["title"], r["kept"]) for r in data["results"]] == [
        ("Torta di zucca", True),
        ("Crema di zucca", False),
    ]
    # Other values, for this probe only: a wide margin lets the second one through.
    wide = api.post("/api/search-probe/", {**body, "margin": 50}, format="json").json()
    assert [r["kept"] for r in wide["results"]] == [True, True]
    assert wide["tuning"]["margin"] == 50


def test_only_administrators_probe(api, team):
    response = api.post("/api/search-probe/", {"text": "zucca", "plain": True}, format="json")
    assert response.status_code == 403


# -- reading the request ----------------------------------------------------------------------


def test_the_model_reads_the_request_negations_into_exclusions():
    answer = {
        "query": "peperoni ripieni",
        "keywords": ["peperoni", "ripieni"],
        "dishes": ["Peperoni ripieni di riso", "Peperoni ripieni di cous cous"],
        "exclude_categories": ["red_meat", "fish", "not-a-category"],
        "exclude_ingredients": [" "],
    }
    chat = FakeChat(ChatResult(content=json.dumps(answer)))
    request = search.understand("peperoni ripieni, ma senza carne o pesce", "Italian", chat)
    assert request.query == "peperoni ripieni"
    assert request.exclude_categories == ["red_meat", "fish"]
    assert request.exclude_ingredients == []
    assert request.dishes[0] == "Peperoni ripieni di riso"


def test_without_the_model_the_request_is_taken_as_typed():
    chat = FakeChat(AIUnavailableError("down"))
    request = search.understand("peperoni ripieni", "Italian", chat)
    assert (request.query, request.keywords, request.dishes) == (
        "peperoni ripieni",
        ["peperoni", "ripieni"],
        ["peperoni ripieni"],
    )


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
        ["Orata al forno", "Branzino al cartoccio"], search_chat, verify=verify_known(pages)
    )
    assert notice is None
    assert [(r["title"], r["dish"]) for r in results] == [
        ("Orata", "Orata al forno"),
        ("Orata 2", "Orata al forno"),
        ("Branzino", "Branzino al cartoccio"),
    ]
    assert search_chat.sent[0][0][0]["content"].startswith("Do one web search for: ricetta ")


def test_a_failed_web_search_is_retried(db):
    search_chat = FakeChat(
        ChatResult(content="Sorry, the search tool had a technical error."),
        listing("https://a.it/polpette"),
    )
    results, _ = search.web_results(
        ["Polpette al sugo"],
        search_chat,
        verify=verify_known({"https://a.it/polpette": "Polpette"}),
    )
    assert [r["title"] for r in results] == ["Polpette"]


def test_without_a_web_search_provider(db):
    assert search.web_results(["x"], None) == ([], "web_search_unavailable")


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
