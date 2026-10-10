"""Providers speaking the OpenAI-compatible HTTP API.

This is the only module (together with `studio`, which extends it) that knows HTTP exists.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from . import usage
from .base import (
    AIError,
    AIUnavailableError,
    AuthError,
    ChatMessage,
    ChatResult,
    ModelNotLoadedError,
)


class _HTTPProvider:
    """Shared plumbing: base URL, bearer auth, timeouts and error mapping."""

    # The name usage is reported under, unless the configuration gives the provider's own
    # ("openai" for OpenAI's paid API, "openai_compatible" for the free local service).
    PROVIDER = "openai_compatible"

    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str | None = None,
        timeout_seconds: float = 60.0,
        client: httpx.Client | None = None,
        provider: str | None = None,
    ) -> None:
        self.provider = provider or self.PROVIDER
        self.model = model
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._client = client or httpx.Client(base_url=self._base_url, timeout=timeout_seconds)

    def close(self) -> None:
        self._client.close()

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        try:
            response = self._client.request(method, path, headers=self._headers(), **kwargs)
        except httpx.ConnectError as exc:
            raise AIUnavailableError(f"{self._base_url} is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(
                f"{self._base_url} did not answer within {self._timeout:.0f}s on {path}."
            ) from exc
        self._raise_for_status(response, path)
        return response

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        if response.is_success:
            return
        detail = _detail(response)
        if response.status_code in (401, 403):
            raise AuthError(f"{self._base_url} rejected the API key: {detail}")
        if response.status_code in (404, 503) and path.startswith("/v1/"):
            raise ModelNotLoadedError(
                f"'{self.model}' is not available at {self._base_url}{path}: {detail}"
            )
        raise AIError(f"{path} failed with status {response.status_code}: {detail}")

    def _list_models(self) -> list[dict[str, Any]]:
        return self._request("GET", "/v1/models").json().get("data") or []

    def health(self) -> dict[str, Any]:
        try:
            models = [entry.get("id") for entry in self._list_models()]
        except AIError as exc:
            return {"ok": False, "base_url": self._base_url, "model": self.model, "error": str(exc)}
        return {
            "ok": True,
            "base_url": self._base_url,
            "model": self.model,
            "model_listed": self.model in models,
        }


class OpenAICompatibleChat(_HTTPProvider):
    """Chat completions on any OpenAI-compatible server."""

    def _extra_payload(self) -> dict[str, Any]:
        """Provider-specific request fields. Subclasses override this, not `chat`."""
        return {}

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": False,
            **self._extra_payload(),
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if tools:
            payload["tools"] = tools
        if response_format is not None:
            payload["response_format"] = response_format

        data = self._request("POST", "/v1/chat/completions", json=payload).json()
        usage.report(usage.from_openai(self.provider, self.model, "chat", data.get("usage")))
        choices = data.get("choices") or []
        if not choices:
            raise AIError("The provider returned no completion choices.")
        message = choices[0].get("message") or {}
        return ChatResult(
            content=(message.get("content") or "").strip(),
            tool_calls=message.get("tool_calls") or [],
            finish_reason=choices[0].get("finish_reason"),
            raw=data,
        )

    def chat_stream(
        self,
        messages: list[ChatMessage],
        *,
        on_delta: Callable[[str, str], None],
        deadline: float | None = None,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        """Like `chat`, receiving the answer as it is written.

        `on_delta(kind, text)` gets every piece: kind "reasoning" (the model's own reasoning,
        where it has one) or "content"; it may raise to stop the call. `deadline` is a
        `time.monotonic()` value: past it the call is abandoned. The connection is closed
        either way, so the server can stop generating.
        """
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": temperature,
            "stream": True,
            **self._extra_payload(),
        }
        if max_tokens is not None:
            payload["max_tokens"] = max_tokens
        if response_format is not None:
            payload["response_format"] = response_format
        path = "/v1/chat/completions"
        content: list[str] = []
        finish_reason = None
        try:
            with self._client.stream(
                "POST", path, json=payload, headers=self._headers()
            ) as response:
                if not response.is_success:
                    response.read()
                    self._raise_for_status(response, path)
                for line in response.iter_lines():
                    if deadline is not None and time.monotonic() > deadline:
                        raise AIUnavailableError(
                            f"{self._base_url} took longer than the time allowed on {path}."
                        )
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    choice = (json.loads(data).get("choices") or [{}])[0]
                    delta = choice.get("delta") or {}
                    finish_reason = choice.get("finish_reason") or finish_reason
                    if reasoning := delta.get("reasoning_content"):
                        on_delta("reasoning", reasoning)
                    if piece := delta.get("content"):
                        content.append(piece)
                        on_delta("content", piece)
        except httpx.ConnectError as exc:
            raise AIUnavailableError(f"{self._base_url} is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(
                f"{self._base_url} stopped answering for {self._timeout:.0f}s on {path}."
            ) from exc
        # Streams carry no usage unless asked, which not every compatible server accepts: the
        # call is counted, its tokens are not.
        usage.report(usage.from_openai(self.provider, self.model, "stream", None))
        return ChatResult(content="".join(content).strip(), finish_reason=finish_reason)


class OpenAICompatibleEmbeddings(_HTTPProvider):
    """Embeddings on any OpenAI-compatible server.

    Covers the bundled `services/embeddings` container, Unsloth Studio's `/v1/embeddings`, and
    cloud APIs that expose the same shape.
    """

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        data = self._request(
            "POST", "/v1/embeddings", json={"model": self.model, "input": texts}
        ).json()
        usage.report(usage.from_openai(self.provider, self.model, "embeddings", data.get("usage")))
        items = sorted(data.get("data") or [], key=lambda item: item.get("index", 0))
        if len(items) != len(texts):
            raise AIError(f"Asked for {len(texts)} embeddings, got {len(items)}.")
        return [item["embedding"] for item in items]


def _detail(response: httpx.Response) -> str:
    """Pull a human-readable message out of an error response."""
    try:
        payload = response.json()
    except ValueError:
        return response.text[:300]
    if isinstance(payload, dict):
        return str(payload.get("detail", payload.get("error", payload)))[:300]
    return str(payload)[:300]
