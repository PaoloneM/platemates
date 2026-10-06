"""'Help me search': recipes matching a request, from the local pool and from the web.

Local results come from embedding similarity over the recipes the user can see. Web results come
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
from typing import Any
from urllib.parse import urlsplit

from django.db.models import Q

from ai import AIError, ChatProvider, get_chat_provider
from apps.families.models import RecipeBookEntry
from apps.recipes.embeddings import similar_recipes
from apps.recipes.models import Recipe

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
# which are not importable; a concrete dish ("orata al forno") finds recipe pages. So the model
# first turns the request into a few concrete dishes (no tools: about 1 s), then each dish gets
# exactly one web search: left free, the model chained searches (90-110 s, context nearly full).
DISHES_PROMPT = """\
Suggest {count} concrete, different dishes that satisfy the request, by their common names in \
{language}. If the request already names a specific dish, put it first. Answer as JSON."""
DISHES_SCHEMA = {
    "type": "object",
    "properties": {"dishes": {"type": "array", "items": {"type": "string"}}},
    "required": ["dishes"],
}
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


# Words that say nothing about the dish; everything else of 4+ letters is a keyword.
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


def keywords(query: str) -> list[str]:
    """Rough stems of the query's meaningful words: "porri" -> "porr", "patate" -> "patat"."""
    words = [w for w in re.findall(r"[^\W\d_]+", query.lower()) if len(w) >= 4]
    return [w[: max(4, len(w) - 1)] for w in words if w not in STOPWORDS]


def keyword_matches(user, query: str) -> list[Recipe]:
    stems = keywords(query)
    if not stems:
        return []
    # Every keyword must appear in the title or in some ingredient: matching any single word
    # turned "un dolce al cioccolato" into a leek soup (its "paprika dolce"). Vaguer requests
    # are left to semantic similarity.
    recipes = Recipe.objects.visible_to(user)
    for stem in stems:
        recipes = recipes.filter(
            Q(title__icontains=stem) | Q(ingredients__ingredient__name__icontains=stem)
        )
    return list(recipes.distinct()[:MAX_LOCAL])


def local_results(user, family, query: str) -> list[dict[str, Any]]:
    """Keyword matches first, then semantically similar recipes."""
    matches = [(recipe, 1.0) for recipe in keyword_matches(user, query)]
    try:
        seen = {recipe.pk for recipe, _ in matches}
        matches += [
            (recipe, similarity)
            for recipe, similarity in similar_recipes(user, query, limit=MAX_LOCAL)
            if recipe.pk not in seen
        ]
    except AIError as exc:
        log.info("semantic search unavailable, keywords only: %s", exc)
    matches = matches[:MAX_LOCAL]
    in_book = set(
        RecipeBookEntry.objects.filter(
            family=family, recipe__in=[r for r, _ in matches]
        ).values_list("recipe_id", flat=True)
    )
    return [
        {
            "kind": "book" if recipe.pk in in_book else "shared",
            "recipe": recipe.pk,
            "title": recipe.title,
            "course": recipe.course,
            "total_minutes": recipe.total_minutes,
            "similarity": round(similarity, 2),
        }
        for recipe, similarity in matches
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


def suggest_dishes(query: str, language_name: str, chat: ChatProvider) -> list[str]:
    result = chat.chat(
        [
            {
                "role": "system",
                "content": DISHES_PROMPT.format(count=DISH_COUNT, language=language_name),
            },
            {"role": "user", "content": query},
        ],
        temperature=0.4,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "dishes", "schema": DISHES_SCHEMA},
        },
    )
    dishes = json.loads(result.content or "{}").get("dishes") or []
    return [str(d).strip() for d in dishes if str(d).strip()][:DISH_COUNT] or [query]


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


def web_results(
    query: str,
    language_name: str,
    search_chat: ChatProvider | None,
    chat: ChatProvider | None = None,
    verify=_verify,
):
    """Returns (results, error code or None)."""
    if search_chat is None:
        return [], "web_search_unavailable"
    try:
        dishes = suggest_dishes(query, language_name, chat or get_chat_provider())
    except (AIError, json.JSONDecodeError) as exc:
        log.warning("could not turn %r into dishes: %s", query, exc)
        dishes = [query]
    with ThreadPoolExecutor(max_workers=PARALLEL_SEARCHES) as pool:
        per_dish = list(pool.map(lambda d: search_dish(d, search_chat, verify), dishes))
    results, seen = [], set()
    for dish, found in zip(dishes, per_dish, strict=True):
        for result in found:
            if result["url"] not in seen:
                seen.add(result["url"])
                results.append({**result, "dish": dish})
    if not results:
        return [], "web_search_empty"
    return results[: DISH_COUNT * PER_DISH], None
