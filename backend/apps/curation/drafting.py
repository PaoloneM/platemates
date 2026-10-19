"""Drafting a system recipe: find real recipe pages for a dish, draft one recipe from them, and
say how far the draft can be trusted.

Sources come from the chat model's own web search, never trusted as stated: every URL is opened
(public addresses only) and kept only if it holds exactly one recipe in schema.org data, as for
the assistant's search. The ratings come from those pages too:

- **reliability**, from the sources found: high with two pages whose ingredients agree, medium
  with one page (or two that disagree), low when there is none and the model wrote the recipe
  from what it knows;
- **web rating**, the pages' own `aggregateRating`, brought to a 0-5 scale and averaged by
  number of votes; none when the pages publish no rating or there are no pages.

Neither is estimated by the model.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from decimal import Decimal
from itertools import combinations
from typing import Any
from urllib.parse import urlsplit

from ai import AIError, ChatProvider
from apps.assistant.agent import LANGUAGE_NAMES, extract_draft, vocabulary_hint
from apps.assistant.draft import DRAFT_SCHEMA, normalize_draft
from apps.assistant.search import _urls
from apps.assistant.web import (
    PageError,
    clean_title,
    count_jsonld_recipes,
    fetch,
    find_jsonld_recipe,
    from_jsonld,
)
from apps.recipes.models import Recipe

log = logging.getLogger(__name__)

MAX_SOURCES = 2
# Share of ingredient words two pages must have in common for their recipes to "agree".
AGREEMENT_THRESHOLD = 0.35
MAX_BATCH = 20

# Words that say nothing about which ingredient a line is about.
_NOISE = {
    "g",
    "gr",
    "kg",
    "ml",
    "cl",
    "l",
    "dl",
    "cucchiaio",
    "cucchiai",
    "cucchiaino",
    "cucchiaini",
    "tazza",
    "tazze",
    "bicchiere",
    "pizzico",
    "q.b",
    "qb",
    "quanto",
    "basta",
    "circa",
    "di",
    "del",
    "della",
    "dello",
    "dei",
    "degli",
    "delle",
    "da",
    "per",
    "con",
    "senza",
    "e",
    "o",
    "a",
    "al",
    "alla",
    "allo",
    "ai",
    "agli",
    "alle",
    "in",
    "un",
    "una",
    "uno",
    "fresco",
    "fresca",
    "freschi",
    "fresche",
    "tritato",
    "tritata",
    "grattugiato",
    "grattugiata",
    "extravergine",
    "q",
    "b",
    "cup",
    "cups",
    "tbsp",
    "tsp",
    "oz",
    "lb",
    "of",
    "the",
    "and",
    "or",
    "fresh",
    "chopped",
}


@dataclass
class Source:
    url: str
    site: str
    title: str
    recipe: dict[str, Any] = field(repr=False)
    rating: float | None = None
    rating_count: int | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "site": self.site,
            "title": self.title,
            "rating": self.rating,
            "rating_count": self.rating_count,
        }


def _number(value) -> float | None:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return None


def rating_of(recipe: dict[str, Any]) -> tuple[float | None, int | None]:
    """A page's own rating, on a 0-5 scale, and its number of votes (schema.org
    `aggregateRating`). (None, None) when the page publishes none or it makes no sense."""
    rating = recipe.get("aggregateRating")
    if isinstance(rating, list):
        rating = rating[0] if rating else None
    if not isinstance(rating, dict):
        return None, None
    value = _number(rating.get("ratingValue"))
    best = _number(rating.get("bestRating")) or 5.0
    worst = _number(rating.get("worstRating")) or 0.0
    count = _number(rating.get("ratingCount")) or _number(rating.get("reviewCount"))
    if value is None or best <= worst or not worst <= value <= best or not count:
        return None, None
    # Most sites rate on stars out of 5; some out of 10 or 100: bring them all to 5.
    scaled = value if best == 5 else value / best * 5
    return round(scaled, 2), int(count)


def web_rating(sources: list[Source]) -> tuple[Decimal | None, int | None]:
    """The sources' ratings averaged by number of votes."""
    rated = [s for s in sources if s.rating is not None and s.rating_count]
    if not rated:
        return None, None
    votes = sum(s.rating_count for s in rated)
    average = sum(s.rating * s.rating_count for s in rated) / votes
    return Decimal(str(round(average, 2))), votes


def _ingredient_words(recipe: dict[str, Any]) -> set[str]:
    words = set()
    for line in recipe.get("recipeIngredient") or []:
        for word in re.findall(r"[a-zàèéìòù]+", str(line).lower()):
            if len(word) >= 4 and word not in _NOISE:
                words.add(word)
    return words


def agreement_of(sources: list[Source]) -> float | None:
    """How much the sources' ingredient lists overlap (Jaccard on their words), 0 to 1. A rough
    measure, enough to tell "two versions of the same dish" from "two different dishes"."""
    if len(sources) < 2:
        return None
    pairs = [
        (_ingredient_words(a.recipe), _ingredient_words(b.recipe))
        for a, b in combinations(sources, 2)
    ]
    scores = [len(x & y) / len(x | y) for x, y in pairs if x | y]
    return round(sum(scores) / len(scores), 2) if scores else 0.0


def reliability_of(sources: list[Source], agreement: float | None) -> str:
    if not sources:
        return "low"
    if len(sources) >= 2 and agreement is not None and agreement >= AGREEMENT_THRESHOLD:
        return "high"
    return "medium"


# -- finding sources ---------------------------------------------------------------------------


def verify_source(url: str) -> Source | None:
    """The page as a source if it exists and holds exactly one complete recipe."""
    try:
        final_url, page = fetch(url)
    except PageError as exc:
        log.info("source %s dropped: %s", url, exc.reason)
        return None
    recipe = find_jsonld_recipe(page)
    if (
        not recipe
        or count_jsonld_recipes(page) != 1
        or len(recipe.get("recipeIngredient") or []) < 2
        or not recipe.get("recipeInstructions")
    ):
        return None
    rating, count = rating_of(recipe)
    return Source(
        url=final_url,
        site=urlsplit(final_url).hostname.removeprefix("www."),
        title=clean_title(str(recipe.get("name") or "")) or final_url,
        recipe=recipe,
        rating=rating,
        rating_count=count,
    )


SEARCH_PROMPT = (
    "Do one web search for: ricetta {dish}. Then list the pages from the results that contain "
    "one recipe each: title and exact URL, one per line, up to eight. Only URLs that appear in "
    "the search results, never one you make up; if the search fails or finds nothing, answer "
    "exactly: NO RESULTS"
)


def _site(url: str) -> str:
    return (urlsplit(url).hostname or "").removeprefix("www.")


def publisher(site: str) -> str:
    """The site's own domain: "blog.giallozafferano.it" and "ricette.giallozafferano.it" are one
    publisher, whose two pages are not two independent versions of a dish."""
    return ".".join(site.split(".")[-2:])


def _model_urls(dish: str, search_chat: ChatProvider) -> list[str]:
    """URLs the chat model's own search found (retried once when it brings none: Studio's
    search fails now and then)."""
    for _attempt in range(2):
        try:
            answer = search_chat.chat(
                [{"role": "user", "content": SEARCH_PROMPT.format(dish=dish)}],
                temperature=0.2,
            ).content
        except AIError as exc:
            log.warning("web search for %r failed: %s", dish, exc)
            continue
        if urls := _urls(answer):
            return urls
    return []


def search_sources(
    dish: str, search_chat: ChatProvider | None, verify=verify_source, sites=(), searcher=None
) -> tuple[list[Source], list[dict[str, Any]]]:
    """Up to MAX_SOURCES verified recipe pages for a dish, and every link the search offered
    with what became of it (`CandidateLink` fields). The search is `searcher`'s when given
    (`searching`), otherwise the chat model's own.

    `sites` (`SourceSite`s) steer it: pages of trusted sites are tried first, blocked ones never.
    """
    if searcher is not None:
        try:
            urls = searcher.urls(f"ricetta {dish}")
        except Exception as exc:
            log.warning("web search for %r failed: %s", dish, exc)
            urls = []
    elif search_chat is not None:
        urls = _model_urls(dish, search_chat)
    else:
        return [], []
    # Trusted sites are not named to the model: asked for them, it makes URLs up on them when
    # the search fails. Their pages simply go first.
    trusted = [s for s in sites if s.trusted]
    blocked = [s for s in sites if not s.trusted]

    def is_trusted(url: str) -> bool:
        return any(s.covers(_site(url)) for s in trusted)

    # Trusted sites first, otherwise in the search's order.
    ordered = sorted(urls, key=lambda url: not is_trusted(url))
    found: list[Source] = []
    links: list[dict[str, Any]] = []
    seen_sites: set[str] = set()
    for position, url in enumerate(ordered):
        site = _site(url)
        link = {
            "url": url[:500],
            "site": site[:120],
            "trusted": is_trusted(url),
            "position": position,
        }
        if any(s.covers(site) for s in blocked):
            link["outcome"] = "blocked"
        elif len(found) == MAX_SOURCES:
            link["outcome"] = "not_checked"
        # Two pages of the same site are rarely two independent versions of a dish.
        elif publisher(site) in seen_sites:
            link["outcome"] = "same_site"
        elif (source := verify(url)) is None:
            link["outcome"] = "rejected"
        elif publisher(source.site) in seen_sites:
            link["outcome"] = "same_site"
        else:
            found.append(source)
            seen_sites.update({publisher(site), publisher(source.site)})
            link.update(
                outcome="used",
                title=source.title[:200],
                rating=source.rating,
                rating_count=source.rating_count,
            )
        links.append(link)
    return found, links


def find_sources(dish: str, search_chat: ChatProvider | None, verify=verify_source) -> list[Source]:
    """The verified pages alone (see `search_sources`)."""
    return search_sources(dish, search_chat, verify)[0]


# -- drafting ----------------------------------------------------------------------------------

COMBINE_PROMPT = """\
Below are {count} recipes for the same dish, "{dish}", from different web pages. Write ONE \
recipe for it in the JSON schema, in {language}: keep the ingredients and steps the sources \
agree on, choose reasonable quantities where they differ, leave out what only one source adds \
unless it is essential. Do not add anything none of the sources has.
- Steps: concise, one action each, merged where the sources describe the same action; usually \
no more than ten.
- Ingredient names: generic, singular, lowercase, in {language}. The name is the basic \
ingredient; variety, origin and preparation go in the note ("fagioli cannellini secchi" -> name \
"fagiolo cannellino", note "secchi"; "pane raffermo toscano" -> "pane", note "raffermo, \
toscano"). Units g, ml, pc, tt (to taste, quantity null).
- Give each ingredient its category and season_months (Italian seasons; empty for what is \
available all year), and the dish's climate_months.
"""

FROM_KNOWLEDGE_PROMPT = """\
No web page was found for the dish "{dish}". Write the most common, traditional version of its \
recipe in the JSON schema, in {language}, as a careful cook would, with usual quantities for the \
servings you choose. Ingredient names are generic, singular, lowercase, in {language}; units g, \
ml, pc, tt (to taste, quantity null). Give each ingredient its category and season_months \
(Italian seasons; empty for what is available all year), and the dish's climate_months. If you \
do not know the dish, return an empty title, no ingredients and no steps.
"""

THEME_PROMPT = """\
Suggest {count} different, well-known dishes for this theme, by their common names in \
{language}: "{theme}". Prefer traditional dishes that home cooks make. Leave out these, which \
already exist: {existing}. Answer as JSON."""
THEME_SCHEMA = {
    "type": "object",
    "properties": {"dishes": {"type": "array", "items": {"type": "string"}}},
    "required": ["dishes"],
}


def _json_answer(chat: ChatProvider, system: str, user: str, temperature: float) -> dict:
    result = chat.chat(
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=temperature,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "recipe", "schema": DRAFT_SCHEMA},
        },
    )
    return json.loads(result.content or "{}")


def draft_recipe(
    dish: str,
    sources: list[Source],
    language: str,
    chat: ChatProvider,
    budget: int,
    vocabulary: list[str] = (),
) -> dict[str, Any]:
    """One recipe draft from the sources (or from the model's knowledge without any).
    `vocabulary`: the catalog's ingredient names, for the draft to use them."""
    language_name = LANGUAGE_NAMES.get(language, "English")
    hint = vocabulary_hint(list(vocabulary))
    if len(sources) == 1:
        # One page: extracted faithfully, as a linked page is imported.
        page = from_jsonld(sources[0].url, sources[0].recipe)
        return extract_draft(page, language_name, chat, vocabulary)
    if not sources:
        raw = _json_answer(
            chat, FROM_KNOWLEDGE_PROMPT.format(dish=dish, language=language_name) + hint, dish, 0.3
        )
        return normalize_draft(raw)
    share = budget // len(sources)
    texts = [
        f"## Source {n}: {s.title} ({s.site})\n{from_jsonld(s.url, s.recipe).text[:share]}"
        for n, s in enumerate(sources, 1)
    ]
    raw = _json_answer(
        chat,
        COMBINE_PROMPT.format(count=len(sources), dish=dish, language=language_name) + hint,
        "\n\n".join(texts),
        0.2,
    )
    draft = normalize_draft(raw)
    draft["source_url"] = sources[0].url
    return draft


def dishes_for_theme(
    theme: str,
    count: int,
    language: str,
    chat: ChatProvider,
    exclude: list[str] = (),
    temperature: float = 0.5,
) -> list[str]:
    """Dish names for a theme ("10 autumn first courses"), leaving out existing system recipes
    and the dishes in `exclude` (already drafted or queued)."""
    existing = list(
        Recipe.objects.filter(owner_team__is_system=True).values_list("title", flat=True)[:300]
    )
    avoid = list(dict.fromkeys([*existing, *exclude]))
    result = chat.chat(
        [
            {
                "role": "user",
                "content": THEME_PROMPT.format(
                    count=count,
                    theme=theme,
                    language=LANGUAGE_NAMES.get(language, "English"),
                    existing=", ".join(avoid[:600]) or "(none)",
                ),
            }
        ],
        temperature=temperature,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "dishes", "schema": THEME_SCHEMA},
        },
    )
    names = json.loads(result.content or "{}").get("dishes") or []
    taken = {title.casefold() for title in avoid}
    unique = dict.fromkeys(
        str(name).strip()[:200]
        for name in names
        if str(name).strip() and str(name).strip().casefold() not in taken
    )
    return list(unique)[:count]
