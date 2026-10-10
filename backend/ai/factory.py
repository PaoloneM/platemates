"""Build the configured providers from `settings.AI`.

Adding a provider means adding an entry to one of the registries below; nothing else in the
application changes.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import lru_cache
from typing import Any

from django.conf import settings

from .anthropic import AnthropicChat
from .base import ChatProvider, EmbeddingProvider
from .openai_compatible import OpenAICompatibleChat, OpenAICompatibleEmbeddings
from .studio import StudioChat

CHAT_PROVIDERS: dict[str, Callable[..., ChatProvider]] = {
    "anthropic": AnthropicChat,
    "openai_compatible": OpenAICompatibleChat,
    "unsloth_studio": StudioChat,
}

EMBEDDING_PROVIDERS: dict[str, Callable[..., EmbeddingProvider]] = {
    # OpenAI's own API speaks the same protocol: only the address, key and model differ.
    "openai": OpenAICompatibleEmbeddings,
    "openai_compatible": OpenAICompatibleEmbeddings,
}


def _config_kwargs(config: dict[str, Any]) -> dict[str, Any]:
    return {
        "base_url": config["BASE_URL"],
        "model": config["MODEL"],
        "api_key": config["API_KEY"],
        "timeout_seconds": config["TIMEOUT_SECONDS"],
    }


def _build(registry: dict[str, Callable[..., Any]], config: dict[str, Any], kind: str) -> Any:
    name = config["PROVIDER"]
    try:
        factory = registry[name]
    except KeyError:
        raise ValueError(
            f"Unknown {kind} provider '{name}'. Known: {', '.join(sorted(registry))}."
        ) from None
    return factory(**_config_kwargs(config))


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
    """A chat provider whose model can search the web itself, or None if the provider can't:
    Unsloth Studio (its server-side tools, `enable_tools`) and Claude (Anthropic's web search
    tool), one search per message."""
    config = settings.AI["CHAT"]
    if config["PROVIDER"] == "anthropic":
        return AnthropicChat(**_config_kwargs(config), web_search=True)
    if config["PROVIDER"] == "unsloth_studio":
        return StudioChat(**_config_kwargs(config), enable_tools=True)
    return None


@lru_cache(maxsize=1)
def get_reasoning_chat_provider() -> ChatProvider:
    """The chat provider with the model's own reasoning on, where the provider has a switch
    for it (Unsloth Studio's `enable_thinking`, Claude's adaptive thinking); otherwise the
    plain chat provider."""
    config = settings.AI["CHAT"]
    if config["PROVIDER"] == "anthropic":
        return AnthropicChat(**_config_kwargs(config), thinking=True)
    if config["PROVIDER"] == "unsloth_studio":
        return StudioChat(**_config_kwargs(config), enable_thinking=True)
    return get_chat_provider()


@lru_cache(maxsize=1)
def get_embedding_provider() -> EmbeddingProvider:
    return _build(EMBEDDING_PROVIDERS, settings.AI["EMBEDDINGS"], "embeddings")
