import json
import socket

import httpx
import pytest

from ai import ChatResult
from apps.assistant import web
from apps.assistant.agent import run_turn
from apps.assistant.models import AssistantSession, Mode
from apps.assistant.web import (
    PageError,
    PageRecipe,
    clean_title,
    fetch,
    find_jsonld_recipe,
    find_url,
    iso_minutes,
    servings_of,
    steps_of,
    visible_text,
)

JSONLD_PAGE = """<html><head><script type="application/ld+json">
{"@context": "https://schema.org", "@graph": [
  {"@type": "WebPage", "name": "x"},
  {"@type": ["Recipe"], "name": "Pasta e ceci | Sito", "recipeYield": ["4", "4 porzioni"],
   "prepTime": "PT15M", "cookTime": "PT1H",
   "recipeIngredient": ["Ceci lessati 400 g", "Ditalini 250 g"],
   "recipeInstructions": [{"@type": "HowToSection", "itemListElement": [
      {"@type": "HowToStep", "text": "Soffriggere <b>aglio</b>."},
      {"@type": "HowToStep", "text": "Aggiungere i ceci."}]}]}
]}</script></head><body></body></html>"""


def test_finds_a_recipe_nested_in_a_graph():
    recipe = find_jsonld_recipe(JSONLD_PAGE)
    assert recipe["name"] == "Pasta e ceci | Sito"
    assert steps_of(recipe["recipeInstructions"]) == ["Soffriggere aglio.", "Aggiungere i ceci."]


def test_structured_facts():
    assert iso_minutes("PT1H30M") == 90
    assert iso_minutes("P0DT0H20M") == 20
    assert iso_minutes("soon") is None
    assert servings_of(["4", "4 porzioni"]) == 4
    assert servings_of("per 6 persone") == 6
    assert servings_of(None) is None
    assert clean_title("Pasta e ceci | Sito") == "Pasta e ceci"
    assert clean_title("Pasta - al dente") == "Pasta - al dente"


def test_photo_numbers_are_removed_from_steps():
    steps = [
        "Tagliatelo a striscioline di circa 1cm 1 2 . La cotenna avanza.",
        "Versate il guanciale in una padella antiaderente 3 e rosolate.",
        "Aggiungete il pecorino 4 e il pepe nero 5 . Amalgamate con una frusta 6 , liscia.",
    ]
    assert web.strip_photo_refs(steps) == [
        "Tagliatelo a striscioline di circa 1cm. La cotenna avanza.",
        "Versate il guanciale in una padella antiaderente e rosolate.",
        "Aggiungete il pecorino e il pepe nero. Amalgamate con una frusta, liscia.",
    ]


def test_ordinary_numbers_in_steps_are_kept():
    steps = ["Sbattete 4 uova con 2 cucchiai di zucchero.", "Cuocete 20 minuti."]
    assert web.strip_photo_refs(steps) == steps


def test_visible_text_starts_near_the_ingredients():
    filler = "".join(f"<p>Chiacchiera numero {i} sulla storia del piatto.</p>" for i in range(60))
    page = (
        f"<html><body><nav>Menu Home Ricette</nav>{filler}"
        "<ul><li>320 g di spaghetti</li><li>150 g guanciale</li><li>50 g pecorino</li>"
        "<li>4 tuorli</li></ul><p>Cuocete la pasta.</p><script>var x=1</script></body></html>"
    )
    text = visible_text(page)
    assert "320 g di spaghetti" in text and "Cuocete la pasta." in text
    assert "Menu Home" not in text and "var x" not in text
    assert "Chiacchiera numero 0 " not in text  # the start of the page was cut


def test_finds_urls_in_messages():
    assert find_url("guarda https://example.com/ricetta?id=3, grazie") == (
        "https://example.com/ricetta?id=3"
    )
    assert find_url("nessun link qui") is None


# -- fetching safety --------------------------------------------------------------------------


def resolving_to(monkeypatch, address):
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a, **k: [(0, 0, 0, "", (address, 0))])


@pytest.mark.parametrize(
    "address", ["127.0.0.1", "10.0.0.5", "192.168.1.1", "172.18.0.3", "169.254.169.254", "::1"]
)
def test_internal_addresses_are_refused(monkeypatch, address):
    resolving_to(monkeypatch, address)
    with pytest.raises(PageError) as error:
        fetch("http://somewhere.example/")
    assert error.value.reason == "forbidden_address"


def test_only_http_urls(monkeypatch):
    with pytest.raises(PageError) as error:
        fetch("file:///etc/passwd")
    assert error.value.reason == "invalid_url"


def test_redirects_are_checked_at_every_hop(monkeypatch):
    def getaddrinfo(host, *args, **kwargs):
        return [(0, 0, 0, "", ("93.184.216.34" if host == "public.example" else "10.0.0.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", getaddrinfo)
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(302, headers={"location": "http://internal.example/admin"})
        )
    )
    with pytest.raises(PageError) as error:
        fetch("http://public.example/recipe", client)
    assert error.value.reason == "forbidden_address"


def test_fetch_returns_the_page(monkeypatch):
    resolving_to(monkeypatch, "93.184.216.34")
    client = httpx.Client(
        transport=httpx.MockTransport(lambda r: httpx.Response(200, html=JSONLD_PAGE))
    )
    url, page = fetch("https://public.example/r", client)
    assert url == "https://public.example/r" and "Pasta e ceci" in page


def test_non_html_is_refused(monkeypatch):
    resolving_to(monkeypatch, "93.184.216.34")
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: httpx.Response(
                200, content=b"%PDF", headers={"content-type": "application/pdf"}
            )
        )
    )
    with pytest.raises(PageError) as error:
        fetch("https://public.example/r.pdf", client)
    assert error.value.reason == "not_html"


# -- importing in a conversation --------------------------------------------------------------


class FakeChat:
    model = "fake"

    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def chat(self, messages, **kwargs):
        self.sent.append((messages, kwargs))
        return self.results.pop(0)


EXTRACTED = {
    "title": "Pasta e ceci riscritta",
    "servings": 2,
    "course": "first",
    "cuisine": "italiana",
    "ingredients": [
        {"name": "cece", "quantity": 400, "unit": "g", "category": "legume", "season_months": []}
    ],
    "steps": ["Passo riscritto dal modello."],
}


@pytest.fixture
def session(team, user):
    return AssistantSession.objects.create(team=team, user=user, mode=Mode.LINK)


def structured_page(url):
    recipe = find_jsonld_recipe(JSONLD_PAGE)
    return web.from_jsonld(url, recipe)


def test_import_keeps_the_page_facts_and_joins_the_conversation(session):
    chat = FakeChat(ChatResult(content=json.dumps(EXTRACTED)))
    result = run_turn(
        session, "https://public.example/pasta-e-ceci", chat=chat, read_page=structured_page
    )
    session.refresh_from_db()
    assert result.draft_updated and result.error is None
    draft = session.draft
    # Verbatim from the page's structured data, not the model's rewrite.
    assert draft["title"] == "Pasta e ceci"
    assert draft["servings"] == 4
    assert (draft["prep_minutes"], draft["cook_minutes"]) == (15, 60)
    assert draft["steps"] == ["Soffriggere aglio.", "Aggiungere i ceci."]
    assert draft["source_url"] == "https://public.example/pasta-e-ceci"
    # The model structured the ingredients from the page text.
    assert draft["ingredients"][0]["name"] == "cece"
    _, page_text = chat.sent[0][0]
    assert "Ceci lessati 400 g" in page_text["content"]
    assert chat.sent[0][1]["response_format"]["type"] == "json_schema"
    # Recorded as a proposal, so later corrections work as in "tell me".
    roles = [m["role"] for m in session.messages]
    assert roles == ["user", "assistant", "tool"]
    assert session.messages[1]["tool_calls"][0]["function"]["name"] == "propose_recipe"


def test_a_correction_after_an_import_keeps_the_source(session):
    corrected = {**EXTRACTED, "servings": 6}
    call = {"id": "c", "function": {"name": "propose_recipe", "arguments": json.dumps(corrected)}}
    chat = FakeChat(
        ChatResult(content=json.dumps(EXTRACTED)), ChatResult(content="", tool_calls=[call])
    )
    run_turn(session, "https://public.example/pasta-e-ceci", chat=chat, read_page=structured_page)
    run_turn(session, "per 6 persone", chat=chat)
    session.refresh_from_db()
    assert session.draft["servings"] == 6
    assert session.draft["source_url"] == "https://public.example/pasta-e-ceci"


def test_unreadable_pages_report_a_reason(session, api):
    def blocked(url):
        raise PageError("http_error", "403")

    result = run_turn(session, "https://public.example/x", chat=FakeChat(), read_page=blocked)
    assert result.error == "http_error"
    transcript = api.get(f"/api/assistant/sessions/{session.pk}/").json()["transcript"]
    assert transcript[-1] == {
        "role": "assistant",
        "text": "",
        "draft": False,
        "error": "http_error",
    }


def test_a_page_without_a_recipe(session):
    empty = {"title": "", "servings": 2, "ingredients": [], "steps": []}
    result = run_turn(
        session,
        "https://public.example/blog",
        chat=FakeChat(ChatResult(content=json.dumps(empty))),
        read_page=lambda url: PageRecipe(url=url, text="testo " * 100, structured=False),
    )
    assert result.error == "no_recipe"


def test_the_error_code_is_not_sent_back_to_the_model(session):
    run_turn(
        session,
        "https://public.example/x",
        chat=FakeChat(),
        read_page=lambda url: (_ for _ in ()).throw(PageError("unreachable")),
    )
    chat = FakeChat(ChatResult(content="Vuoi incollarmi il testo?"))
    run_turn(session, "e allora?", chat=chat)
    sent = chat.sent[0][0]
    assert all("error" not in m for m in sent)
