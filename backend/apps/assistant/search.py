"""'Help me search': recipes matching a request, from the local pool and from the web.

The request is first read by the chat model (`understand`): what is wanted, its keywords, a few
concrete dishes, and what it rules out. Local results are the recipes the user can see that it
does not rule out, with every keyword (full text) or close in embedding similarity to the best
match (see `rank`). Web results come
from the chat model's own web search (Unsloth Studio), and are never shown as the model states
them: asked for structured results it invented every URL (2026-10-06), and even real results are
often collection or search pages. So only URLs present in its answer are kept, each page is
opened (with the same public-address checks as link import), and a result is shown only if the
page exists and carries schema.org Recipe data; its title is the page's own.
"""

from __future__ import annotations

import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlsplit

from django.contrib.postgres.search import SearchQuery, SearchVector
from django.db.models import OuterRef, Q, StringAgg, Subquery, TextField, Value
from django.db.models.functions import Coalesce

from ai import AIError, ChatProvider
from apps.catalog.models import IngredientCategory
from apps.recipes.embeddings import similar_recipes
from apps.recipes.models import Recipe, RecipeIngredient
from apps.siteconfig import registry
from apps.teams.models import RecipeBookEntry
from apps.usage.context import carry

from .web import (
    URL_RE,
    PageError,
    clean_title,
    count_jsonld_recipes,
    fetch,
    find_jsonld_recipe,
    servings_of,
)

log = logging.getLogger(__name__)

MAX_LOCAL = 6
MAX_WEB = 6

# A vague request ("un secondo di pesce al forno") finds mostly category and collection pages,
# which are not importable; a concrete dish ("orata al forno") finds recipe pages. So the
# request is first turned into a few concrete dishes (`understand`), then each dish gets
# exactly one web search: left free, the model chained searches (90-110 s, context nearly full).
DISH_SEARCH_PROMPT = (
    "Do one web search for: ricetta {dish}. Then list the pages from the results that contain "
    "one recipe each: title and exact URL, one per line."
)
DISH_COUNT = 3
PER_DISH = 2
# Studio's search tool fails intermittently (the model then answers without any URL); parallel
# searches make it more likely, so at most this many run at once, and a failed one is retried.
PARALLEL_SEARCHES = 2


def search_query(messages: list[dict[str, Any]], text: str) -> str:
    """The request, with the user's earlier messages as context for refinements ("faster")."""
    earlier = [m["content"] for m in messages if m["role"] == "user"][-2:]
    return " ".join([*earlier, text]).strip()[:500]


# -- understanding the request ----------------------------------------------------------------

# Ingredient categories a request can rule out ("senza carne o pesce", "vegetariano").
CATEGORIES = [c.value for c in IngredientCategory]

UNDERSTAND_PROMPT = """\
The user is looking for recipes; the text is their request, earlier messages first (later ones \
refine it). Describe what they want, in {language}:
- query: what they want, in a few words, without anything they want to avoid;
- keywords: the words a recipe that fits must contain in its title or ingredients (dish names, \
key ingredients), singular or as written; none for a vague request;
- dishes: {count} concrete, different dishes that satisfy the request, by their common names; \
if the request names a specific dish, put it first;
- exclude_categories: ingredient categories the request rules out ("without meat": red_meat, \
white_meat, cured_meat; "vegetarian": those and fish, seafood);
- exclude_ingredients: single ingredients the request rules out.
Answer as JSON."""
UNDERSTAND_SCHEMA = {
    "type": "object",
    "properties": {
        "query": {"type": "string"},
        "keywords": {"type": "array", "items": {"type": "string"}},
        "dishes": {"type": "array", "items": {"type": "string"}},
        "exclude_categories": {"type": "array", "items": {"type": "string", "enum": CATEGORIES}},
        "exclude_ingredients": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["query", "keywords", "dishes", "exclude_categories", "exclude_ingredients"],
}


@dataclass
class Request:
    """What a search request asks for. Negations live only in the exclusions: an embedding
    reads "senza pesce" as "pesce" (a sea bass came first, 2026-10-11)."""

    query: str
    keywords: list[str]
    dishes: list[str]
    exclude_categories: list[str] = field(default_factory=list)
    exclude_ingredients: list[str] = field(default_factory=list)


def plain_request(text: str) -> Request:
    """The request as typed, when the model cannot read it: no exclusions."""
    return Request(query=text, keywords=keywords(text), dishes=[text])


def understand(text: str, language_name: str, chat: ChatProvider) -> Request:
    """One model call (no tools, about 1 s) turns the request into what both searches need."""
    try:
        result = chat.chat(
            [
                {
                    "role": "system",
                    "content": UNDERSTAND_PROMPT.format(language=language_name, count=DISH_COUNT),
                },
                {"role": "user", "content": text},
            ],
            temperature=0.2,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "request", "schema": UNDERSTAND_SCHEMA},
            },
        )
        data = json.loads(result.content or "{}")
    except (AIError, json.JSONDecodeError) as exc:
        log.warning("could not read the request %r: %s", text, exc)
        return plain_request(text)

    def strings(key: str) -> list[str]:
        return [str(v).strip() for v in data.get(key) or [] if str(v).strip()]

    return Request(
        query=str(data.get("query") or "").strip() or text,
        keywords=strings("keywords"),
        dishes=strings("dishes")[:DISH_COUNT] or [text],
        exclude_categories=[c for c in strings("exclude_categories") if c in CATEGORIES],
        exclude_ingredients=strings("exclude_ingredients"),
    )


# -- local search -----------------------------------------------------------------------------

# Words that say nothing about the dish, left out of the keywords of a request the model could
# not read.
STOPWORDS = {
    "qualcosa",
    "ricetta",
    "ricette",
    "piatto",
    "piatti",
    "fare",
    "voglio",
    "vorrei",
    "senza",
    "dello",
    "della",
    "delle",
    "degli",
    "nella",
    "nelle",
    "come",
    "anche",
    "molto",
    "poco",
    "something",
    "recipe",
    "recipes",
    "with",
    "without",
    "dish",
    "some",
    "make",
}


def keywords(text: str) -> list[str]:
    """The meaningful words of a request: 4+ letters, not filler."""
    words = re.findall(r"[^\W\d_]+", text.lower())
    return [w for w in words if len(w) >= 4 and w not in STOPWORDS]


def _main_ingredient_names():
    """A recipe's main ingredients (not optional, not basic), as one string, for full-text."""
    return Coalesce(
        Subquery(
            RecipeIngredient.objects.filter(
                recipe=OuterRef("pk"), optional=False, ingredient__basic=False
            )
            .values("recipe")
            .annotate(names=StringAgg("ingredient__name", Value(" ")))
            .values("names"),
            output_field=TextField(),
        ),
        Value(""),
        output_field=TextField(),
    )


def candidates(user, request: Request):
    """The recipes the user can see that the request does not rule out."""
    recipes = Recipe.objects.visible_to(user)
    ruled_out = Q()
    if request.exclude_categories:
        ruled_out |= Q(ingredient__category__in=request.exclude_categories)
    for name in request.exclude_ingredients:
        ruled_out |= Q(ingredient__name__icontains=name)
    if ruled_out:
        lines = RecipeIngredient.objects.filter(ruled_out, optional=False)
        recipes = recipes.exclude(pk__in=lines.values("recipe"))
    return recipes


def keyword_matches(recipes, words: list[str]) -> set[int]:
    """Recipes whose title or main ingredients have every word, by Italian stems (PostgreSQL
    full text): "formaggi" finds "formaggio", but not inside other words as a substring
    search did ("sale" in "salsiccia"). Basic ingredients never count."""
    if not words:
        return set()
    document = SearchVector("title", weight="A", config="italian") + SearchVector(
        _main_ingredient_names(), weight="B", config="italian"
    )
    query = SearchQuery(" ".join(words), config="italian", search_type="plain")
    return set(
        recipes.annotate(document=document).filter(document=query).values_list("pk", flat=True)
    )


@dataclass
class Scored:
    recipe: Recipe
    similarity: float
    keyword: bool
    score: float
    kept: bool = False


def rank(user, request: Request) -> list[Scored]:
    """Every candidate worth a look, best first, `kept` for those offered.

    A recipe with every keyword is always offered. Others are offered by similarity, only
    when close to the best one: absolute similarities depend on the model and on the request
    (one word scores lower than a phrase), but a right match stands out from the rest."""
    recipes = candidates(user, request)
    matched = keyword_matches(recipes, request.keywords)
    similarity: dict[int, tuple[Recipe, float]] = {}
    try:
        texts = list(dict.fromkeys([request.query, *request.dishes]))
        allowed = set(recipes.values_list("pk", flat=True))
        for recipe, value in similar_recipes(user, texts, limit=MAX_LOCAL * 3):
            if recipe.pk in allowed:
                similarity[recipe.pk] = (recipe, value)
    except AIError as exc:
        log.info("semantic search unavailable, keywords only: %s", exc)
    missing = matched - similarity.keys()
    for recipe in Recipe.objects.filter(pk__in=missing):
        similarity[recipe.pk] = (recipe, 0.0)

    bonus = registry.get("search.keyword_bonus") / 100
    scored = sorted(
        (
            Scored(recipe, value, pk in matched, value + (bonus if pk in matched else 0))
            for pk, (recipe, value) in similarity.items()
        ),
        key=lambda s: -s.score,
    )
    floor = registry.get("search.min_similarity") / 100
    margin = registry.get("search.margin") / 100
    best = max((s.similarity for s in scored if not s.keyword), default=0.0)
    for s in scored:
        s.kept = s.keyword or (s.similarity >= floor and s.similarity >= best - margin)
    return scored


def local_results(user, team, request: Request) -> list[dict[str, Any]]:
    """The recipes offered: keyword matches and the closest similar ones, at most MAX_LOCAL."""
    offered = [s for s in rank(user, request) if s.kept][:MAX_LOCAL]
    in_book = set(
        RecipeBookEntry.objects.filter(
            team=team, recipe__in=[s.recipe for s in offered]
        ).values_list("recipe_id", flat=True)
    )
    return [
        {
            "kind": "book" if s.recipe.pk in in_book else "shared",
            "recipe": s.recipe.pk,
            "title": s.recipe.title,
            "course": s.recipe.course,
            "total_minutes": s.recipe.total_minutes,
            "similarity": round(s.similarity, 2),
        }
        for s in offered
    ]


def _verify(url: str) -> dict[str, Any] | None:
    """The page as a result if it exists and holds a recipe; None otherwise."""
    try:
        final_url, page = fetch(url)
    except PageError as exc:
        log.info("search result %s dropped: %s", url, exc.reason)
        return None
    recipe = find_jsonld_recipe(page)
    # A page about one recipe: collections ("107 secondi di pesce") declare several Recipe
    # objects, or one without ingredients or method.
    if (
        not recipe
        or count_jsonld_recipes(page) != 1
        or len(recipe.get("recipeIngredient") or []) < 2
        or not recipe.get("recipeInstructions")
    ):
        return None
    return {
        "kind": "web",
        "url": final_url,
        "site": urlsplit(final_url).hostname.removeprefix("www."),
        "title": clean_title(str(recipe.get("name") or "")) or final_url,
        "servings": servings_of(recipe.get("recipeYield")),
    }


def _urls(answer: str) -> list[str]:
    return list(dict.fromkeys(u.rstrip(".,;:)]}*") for u in URL_RE.findall(answer)))


def search_dish(dish: str, search_chat: ChatProvider, verify=_verify) -> list[dict[str, Any]]:
    """Verified recipe pages for one dish, from one web search (retried once if it failed)."""
    urls: list[str] = []
    for _attempt in range(2):
        try:
            answer = search_chat.chat(
                [{"role": "user", "content": DISH_SEARCH_PROMPT.format(dish=dish)}], temperature=0.2
            ).content
        except AIError as exc:
            log.warning("web search for %r failed: %s", dish, exc)
            continue
        urls = _urls(answer)
        if urls:
            break
    known = set(Recipe.objects.filter(source_url__in=urls).values_list("source_url", flat=True))
    found = []
    for url in urls:
        if url in known:
            continue
        if result := verify(url):
            found.append(result)
            if len(found) == PER_DISH:
                break
    return found


def web_results(dishes: list[str], search_chat: ChatProvider | None, verify=_verify):
    """Verified recipe pages for the dishes a request was turned into. Returns (results, error
    code or None)."""
    if search_chat is None:
        return [], "web_search_unavailable"
    with ThreadPoolExecutor(max_workers=PARALLEL_SEARCHES) as pool:
        # carry(): the searches are billed to the same team as the request.
        search = carry(lambda d: search_dish(d, search_chat, verify))
        per_dish = list(pool.map(search, dishes))
    results, seen = [], set()
    for dish, found in zip(dishes, per_dish, strict=True):
        for result in found:
            if result["url"] not in seen:
                seen.add(result["url"])
                results.append({**result, "dish": dish})
    if not results:
        return [], "web_search_empty"
    return results[: DISH_COUNT * PER_DISH], None
