"""Build the configured providers from `settings.AI`.

Adding a provider means adding an entry to one of the registries below; nothing else in the
application changes.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from django.conf import settings

from .base import ChatProvider, EmbeddingProvider
from .openai_compatible import OpenAICompatibleChat, OpenAICompatibleEmbeddings
from .studio import StudioChat

CHAT_PROVIDERS: dict[str, Callable[..., ChatProvider]] = {
    "openai_compatible": OpenAICompatibleChat,
    "unsloth_studio": StudioChat,
}

EMBEDDING_PROVIDERS: dict[str, Callable[..., EmbeddingProvider]] = {
    "openai_compatible": OpenAICompatibleEmbeddings,
}


def _build(registry: dict[str, Callable[..., Any]], config: dict[str, Any], kind: str) -> Any:
    name = config["PROVIDER"]
    try:
        factory = registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown {kind} provider '{name}'. Known: {', '.join(sorted(registry))}."
        ) from None
    return factory(
        base_url=config["BASE_URL"],
        model=config["MODEL"],
        api_key=config["API_KEY"],
        timeout_seconds=config["TIMEOUT_SECONDS"],
    )


@lru_cache(maxsize=1)
def get_chat_provider() -> ChatProvider:
    return _build(CHAT_PROVIDERS, settings.AI["CHAT"], "chat")


@lru_cache(maxsize=1)
def get_vision_provider() -> ChatProvider:
    """The chat provider, pointed at the model that reads images (`LLM_VISION_MODEL`)."""
    config = settings.AI["CHAT"]
    return _build(CHAT_PROVIDERS, {**config, "MODEL": config["VISION_MODEL"]}, "chat")


@lru_cache(maxsize=1)
def get_web_search_provider() -> ChatProvider | None:
    """A chat provider whose model can search the web itself, or None if the provider can't.

    Only Unsloth Studio has a built-in web search (its server-side tools, `enable_tools`).
    """
    config = settings.AI["CHAT"]
    if config["PROVIDER"] != "unsloth_studio":
        return None
    return StudioChat(
        base_url=config["BASE_URL"],
        model=config["MODEL"],
        api_key=config["API_KEY"],
        timeout_seconds=config["TIMEOUT_SECONDS"],
        enable_tools=True,
    )


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return _build(EMBEDDING_PROVIDERS, settings.AI["EMBEDDINGS"], "embeddings")
