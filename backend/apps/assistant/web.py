"""Read the recipe on a web page the user linked.

Not a scraper: one page, the one the user gave, fetched once. The recipe text comes from the
page's schema.org `Recipe` data when present, otherwise from its visible text, cut around where
quantities cluster (generic "main content" extractors drop ingredient boxes; see
docs/architecture.md). The LLM then structures that text; it never sees anything else.
"""

from __future__ import annotations

import ipaddress
import json
import re
import socket
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit

import httpx
from lxml import html as lxml_html

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
MAX_BYTES = 3 * 1024 * 1024
MAX_REDIRECTS = 5
TIMEOUT_SECONDS = 20
# Text budget for the LLM: the chat model currently runs with an 8k-token context.
TEXT_BUDGET_CHARS = 9000

BLOCK_TAGS = (
    "p",
    "div",
    "li",
    "br",
    "tr",
    "td",
    "th",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "section",
    "article",
    "ul",
    "ol",
    "dd",
    "dt",
    "table",
    "blockquote",
    "pre",
)
URL_RE = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
QUANTITY_RE = re.compile(
    r"\b\d+([.,]\d+)?\s?(g|gr|kg|ml|cl|l|cucchiai[on]?[io]?|cucchiain[oi]|cups?|tbsp|tsp|oz|lb)\b",
    re.IGNORECASE,
)


class PageError(Exception):
    """The page cannot be read. `reason` is a stable code the UI translates."""

    def __init__(self, reason: str, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else reason)
        self.reason = reason


@dataclass
class PageRecipe:
    url: str
    # Text for the LLM to structure: the recipe and nothing else, within TEXT_BUDGET_CHARS.
    text: str
    # True when it came from schema.org data rather than the page's visible text.
    structured: bool
    # Facts taken verbatim from structured data, which the LLM must not rewrite.
    facts: dict = field(default_factory=dict)


def find_url(text: str) -> str | None:
    match = URL_RE.search(text)
    return match.group(0).rstrip(".,;:!?)]}") if match else None


# -- fetching ---------------------------------------------------------------------------------


def _check_public(url: str) -> None:
    """Refuse anything but http(s) to public addresses.

    The backend can reach the database, Keycloak, Unsloth Studio and the home network; a user
    pasting `http://keycloak:8080/...` or `http://192.168.1.1/` must not make it fetch them.
    Every address the name resolves to must be public. (A DNS answer changing between this check
    and the connection is not covered; acceptable for a team app, revisit if exposed widely.)
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise PageError("invalid_url", url)
    try:
        infos = socket.getaddrinfo(parts.hostname, parts.port or None, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise PageError("unreachable", str(exc)) from exc
    for info in infos:
        address = ipaddress.ip_address(info[4][0])
        if not address.is_global:
            raise PageError("forbidden_address", parts.hostname)


def fetch(url: str, client: httpx.Client | None = None) -> tuple[str, str]:
    """Download a page, checking every redirect hop. Returns (final URL, HTML)."""
    own = client is None
    client = client or httpx.Client(timeout=TIMEOUT_SECONDS, follow_redirects=False)
    try:
        for _ in range(MAX_REDIRECTS + 1):
            _check_public(url)
            try:
                with client.stream(
                    "GET",
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept-Language": "it-IT,it;q=0.9,en;q=0.8",
                    },
                ) as response:
                    if response.is_redirect:
                        url = urljoin(url, response.headers.get("location", ""))
                        continue
                    if response.status_code >= 400:
                        raise PageError("http_error", str(response.status_code))
                    kind = response.headers.get("content-type", "")
                    if "html" not in kind and "xml" not in kind:
                        raise PageError("not_html", kind)
                    body = b""
                    for chunk in response.iter_bytes():
                        body += chunk
                        if len(body) > MAX_BYTES:
                            raise PageError("too_large")
                    return url, body.decode(response.encoding or "utf-8", errors="replace")
            except httpx.HTTPError as exc:
                raise PageError("unreachable", str(exc)) from exc
        raise PageError("too_many_redirects")
    finally:
        if own:
            client.close()


# -- schema.org Recipe ------------------------------------------------------------------------


def find_jsonld_recipe(page: str) -> dict | None:
    for block in re.findall(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I
    ):
        try:
            data = json.loads(block.strip())
        except json.JSONDecodeError:
            continue
        recipe = _find_recipe(data)
        if recipe:
            return recipe
    return None


def count_jsonld_recipes(page: str) -> int:
    """How many schema.org Recipe objects a page declares (collections declare many)."""
    count = 0

    def walk(node):
        nonlocal count
        if isinstance(node, list):
            for item in node:
                walk(item)
        elif isinstance(node, dict):
            kinds = node.get("@type")
            if "Recipe" in (kinds if isinstance(kinds, list) else [kinds]):
                count += 1
            for value in node.values():
                if isinstance(value, (list, dict)):
                    walk(value)

    for block in re.findall(
        r"<script[^>]*application/ld\+json[^>]*>(.*?)</script>", page, re.S | re.I
    ):
        try:
            walk(json.loads(block.strip()))
        except json.JSONDecodeError:
            continue
    return count


def _find_recipe(node) -> dict | None:
    if isinstance(node, list):
        for item in node:
            if found := _find_recipe(item):
                return found
    elif isinstance(node, dict):
        kinds = node.get("@type")
        if "Recipe" in (kinds if isinstance(kinds, list) else [kinds]):
            return node
        for key in ("@graph", "mainEntity", "mainEntityOfPage"):
            if key in node and (found := _find_recipe(node[key])):
                return found
    return None


def iso_minutes(value) -> int | None:
    """'PT1H30M' -> 90. None when absent or unreadable."""
    if not isinstance(value, str):
        return None
    match = re.fullmatch(r"P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?(?:\d+S)?", value.strip().upper())
    if not match or not any(match.groups()):
        return None
    days, hours, minutes = (int(g or 0) for g in match.groups())
    return days * 1440 + hours * 60 + minutes or None


def servings_of(value) -> int | None:
    """recipeYield comes as 4, "4", "4 porzioni" or a list of those."""
    for item in value if isinstance(value, list) else [value]:
        match = re.search(r"\d+", str(item or ""))
        if match and 0 < int(match.group()) < 100:
            return int(match.group())
    return None


def _text(value) -> str:
    """Strip any HTML that sites leave in their structured data."""
    if not value:
        return ""
    return " ".join(lxml_html.fromstring(f"<div>{value}</div>").text_content().split())


def steps_of(instructions) -> list[str]:
    """recipeInstructions: a string, HowToStep items, or HowToSection groups of them."""
    if isinstance(instructions, str):
        return [s for s in (_text(p) for p in re.split(r"\n+|<br\s*/?>|</p>", instructions)) if s]
    steps: list[str] = []
    for item in instructions or []:
        if isinstance(item, str):
            steps.append(_text(item))
        elif isinstance(item, dict):
            if "itemListElement" in item:
                steps += steps_of(item["itemListElement"])
            else:
                steps.append(_text(item.get("text") or item.get("name")))
    return [s for s in steps if s]


def clean_title(title: str) -> str:
    """Drop the site name that pages append: "Lasagne con la zucca | Acadèmia.tv"."""
    return re.split(r"\s+[|\u2013\u2014]\s+", title, maxsplit=1)[0].strip()


# A bare number between words or before punctuation: "antiaderente 4 e", "pepe nero 8 .".
_PHOTO_REF = re.compile(r"\s(\d{1,2})(?=\s*[.,;:]|\s+[a-zà-ù]|\s+\d)")


def strip_photo_refs(steps: list[str]) -> list[str]:
    """Remove the photo numbers some sites (e.g. GialloZafferano) leave in their steps.

    They show up as the sequence 1, 2, 3, ... of bare numbers running through the whole method.
    Only numbers continuing that sequence are removed, and only when at least three are found,
    so an ordinary "aggiungete 4 uova" is left alone.
    """
    expected, hits = 1, []
    for index, step in enumerate(steps):
        for match in _PHOTO_REF.finditer(step):
            if int(match.group(1)) == expected:
                hits.append((index, match.start(), match.end()))
                expected += 1
    if len(hits) < 3:
        return steps
    cleaned = list(steps)
    for index, start, end in reversed(hits):
        cleaned[index] = cleaned[index][:start] + cleaned[index][end:]
    return [re.sub(r"\s+([.,;:])", r"\1", " ".join(s.split())) for s in cleaned]


def from_jsonld(url: str, recipe: dict) -> PageRecipe:
    ingredients = [_text(i) for i in recipe.get("recipeIngredient") or []]
    facts = {
        "title": clean_title(_text(recipe.get("name"))),
        "servings": servings_of(recipe.get("recipeYield")),
        "prep_minutes": iso_minutes(recipe.get("prepTime")),
        "cook_minutes": iso_minutes(recipe.get("cookTime")),
        "steps": strip_photo_refs(steps_of(recipe.get("recipeInstructions"))),
        "source_url": url,
    }
    lines = [f"Title: {facts['title']}"]
    if facts["servings"]:
        lines.append(f"Servings: {facts['servings']}")
    if description := _text(recipe.get("description")):
        lines.append(f"Description: {description}")
    if category := recipe.get("recipeCategory"):
        lines.append(f"Category: {category}")
    if cuisine := recipe.get("recipeCuisine"):
        lines.append(f"Cuisine: {cuisine}")
    lines += ["Ingredients:", *(f"- {i}" for i in ingredients), "Method:"]
    lines += [f"{n}. {s}" for n, s in enumerate(facts["steps"], 1)]
    return PageRecipe(
        url=url, text="\n".join(lines)[:TEXT_BUDGET_CHARS], structured=True, facts=facts
    )


# -- visible text fallback --------------------------------------------------------------------


def visible_text(page: str) -> str:
    """The page's visible text, cut to a window around where quantities cluster."""
    try:
        doc = lxml_html.fromstring(page)
    except Exception:  # lxml raises several types on garbage
        return ""
    for node in doc.xpath(
        "//script|//style|//noscript|//nav|//footer|//header|//form|//svg|//iframe|//aside"
    ):
        node.drop_tree()
    # Minified pages have no newlines between elements: put one after every block element, or
    # the whole page would come out as a single line.
    for node in doc.iter(*BLOCK_TAGS):
        node.tail = "\n" + (node.tail or "")
    lines = [" ".join(line.split()) for line in doc.text_content().splitlines()]
    lines = [line for line in lines if line]
    if not lines:
        return ""
    # Ingredient lists are where quantities cluster: start a little before the densest window.
    best, best_score = 0, -1
    for i in range(len(lines)):
        score = sum(1 for line in lines[i : i + 25] if QUANTITY_RE.search(line))
        if score > best_score:
            best, best_score = i, score
    out, size = [], 0
    for line in lines[max(0, best - 15) :]:
        if size + len(line) > TEXT_BUDGET_CHARS:
            break
        out.append(line)
        size += len(line) + 1
    return "\n".join(out)


def read_recipe_page(url: str, client: httpx.Client | None = None) -> PageRecipe:
    final_url, page = fetch(url, client)
    if recipe := find_jsonld_recipe(page):
        return from_jsonld(final_url, recipe)
    text = visible_text(page)
    if len(text) < 200:
        # Probably rendered by JavaScript, or a page with no recipe at all.
        raise PageError("no_content")
    return PageRecipe(url=final_url, text=text, structured=False, facts={"source_url": final_url})
