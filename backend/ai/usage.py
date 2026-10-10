"""What each call to a model consumed, reported to whoever listens.

Providers call `report()` after every successful request with the tokens (and web searches) the
provider says it used. `ai/` knows nothing about teams or databases: the application registers a
recorder (`set_recorder`) that attributes and stores the usage (apps/usage). Without one, usage
is simply dropped. A failing recorder never fails the call that consumed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Usage:
    provider: str
    model: str
    # "chat", "stream" or "embeddings".
    operation: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    web_searches: int = 0


_recorder: Callable[[Usage], None] | None = None


def set_recorder(recorder: Callable[[Usage], None] | None) -> None:
    global _recorder
    _recorder = recorder


def report(usage: Usage) -> None:
    if _recorder is None:
        return
    try:
        _recorder(usage)
    except Exception:  # accounting must never break the call that consumed
        log.exception("usage not recorded: %s", usage)


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def from_openai(provider: str, model: str, operation: str, usage: dict | None) -> Usage:
    """OpenAI-style `usage` (chat completions and embeddings)."""
    usage = usage or {}
    details = usage.get("prompt_tokens_details") or {}
    return Usage(
        provider=provider,
        model=model,
        operation=operation,
        input_tokens=_int(usage.get("prompt_tokens")),
        output_tokens=_int(usage.get("completion_tokens")),
        cache_read_tokens=_int(details.get("cached_tokens")),
    )


def from_anthropic(model: str, operation: str, usage: dict | None) -> Usage:
    """Anthropic's `usage` (a response, or the counts gathered from a stream)."""
    usage = usage or {}
    return Usage(
        provider="anthropic",
        model=model,
        operation=operation,
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        cache_read_tokens=_int(usage.get("cache_read_input_tokens")),
        cache_write_tokens=_int(usage.get("cache_creation_input_tokens")),
        web_searches=_int((usage.get("server_tool_use") or {}).get("web_search_requests")),
    )
