"""Where a campaign's search for recipe pages comes from (`RECIPE_SEARCH`).

- "studio": the chat model's own web search tool (`ai.get_web_search_provider`); the model
  lists the pages it found.
- "searxng": a SearXNG instance of ours (compose profile `campaign`), asked by code. Studio's
  tool searches the public engines from one address in quick succession and gets cut off after
  a few dozen searches; SearXNG spreads the queries over many engines, and asking it costs no
  model time.

Either way the URLs are only candidates: every page is opened and verified
(`drafting.verify_source`).
"""

from __future__ import annotations

import logging

import httpx
from django.conf import settings

log = logging.getLogger(__name__)

TIMEOUT_SECONDS = 30
MAX_RESULTS = 12


class SearchError(Exception):
    pass


class SearxngSearch:
    def __init__(self, base_url: str, timeout: float = TIMEOUT_SECONDS):
        self.base_url = base_url
        self.timeout = timeout

    def urls(self, query: str, language: str = "it") -> list[str]:
        """Result URLs for the query, best first; SearchError when the engine fails."""
        try:
            response = httpx.get(
                f"{self.base_url}/search",
                params={"q": query, "format": "json", "language": language},
                timeout=self.timeout,
            )
            response.raise_for_status()
            results = response.json().get("results") or []
        except (httpx.HTTPError, ValueError) as exc:
            raise SearchError(str(exc)) from exc
        urls = [r.get("url") for r in results if str(r.get("url") or "").startswith("http")]
        return list(dict.fromkeys(urls))[:MAX_RESULTS]


def get_recipe_searcher() -> SearxngSearch | None:
    """The searcher campaigns use by code; None when the model's own tool searches."""
    if settings.RECIPE_SEARCH == "searxng":
        return SearxngSearch(settings.SEARXNG_URL)
    return None
