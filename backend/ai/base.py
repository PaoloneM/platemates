"""Stable interfaces for the AI components.

These protocols are the contract between application logic and whatever model serves it. They are
deliberately shaped after the OpenAI chat/embeddings APIs, because that is the lowest common
denominator spoken by Unsloth Studio, llama.cpp, vLLM, Ollama and the main cloud providers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

# A chat message in OpenAI format: {"role": ..., "content": ...}, plus tool-call fields when the
# agentic loop needs them. Kept as a plain dict so tool calls pass through untouched.
ChatMessage = dict[str, Any]


class AIError(RuntimeError):
    """Base class for every failure coming from an AI provider."""


class AIUnavailableError(AIError):
    """The provider is not reachable, or did not answer in time."""


class AuthError(AIError):
    """The provider rejected the credentials."""


class ModelNotLoadedError(AIError):
    """The provider is up, but the requested model is not available."""


@dataclass(frozen=True)
class ChatResult:
    """The assistant's reply to a chat completion."""

    content: str
    # Tool calls requested by the model, in OpenAI format. Empty when it answered in plain text.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    finish_reason: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)


@runtime_checkable
class ChatProvider(Protocol):
    """A generative model that answers chat completions."""

    model: str

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult: ...

    def health(self) -> dict[str, Any]:
        """Report whether the provider is reachable and the model usable. Never raises."""
        ...


@runtime_checkable
class EmbeddingProvider(Protocol):
    """A model that turns text into vectors.

    `model` identifies the vector space. Vectors from different models are not comparable, so it is
    stored alongside every persisted embedding.
    """

    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...

    def health(self) -> dict[str, Any]:
        """Report whether the provider is reachable and the model usable. Never raises."""
        ...
