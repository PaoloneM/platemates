"""Claude, through Anthropic's Messages API (`/v1/messages`).

The application speaks the OpenAI chat format everywhere (`base.ChatMessage`); this module
translates it, so nothing outside `ai/` knows which provider answers:

- system messages become the request's `system`; consecutive messages of the same role are
  merged (the API rejects them), and `tool` results go back in a user message as `tool_result`
  blocks after the assistant's `tool_use`;
- `response_format` (json_schema) becomes structured outputs (`output_config.format`), with the
  schema reduced to what they accept (no numeric or length bounds, closed objects);
- OpenAI-style function tools become Claude tools, and Claude's `tool_use` comes back as OpenAI
  `tool_calls`;
- `image_url` data URLs become base64 image blocks.

Verified against the API documentation on 2026-10-10: on Claude 4.7 and later a temperature
other than the default is refused, so none is sent; thinking is off unless asked for (adaptive
when on, its summary streamed as progress). "Off" is `disabled` on most models, but newer ones (Sonnet 5.5, 2026-10-10) refuse it
and ask for `between_tools`: the adapter switches when told so, once per model. The web
search is Anthropic's server-side tool, capped like Studio's to one search per message.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import httpx

from .base import AIError, AIUnavailableError, ChatMessage, ChatResult
from .openai_compatible import _detail, _HTTPProvider

API_VERSION = "2023-06-01"
# Required by the API. Enough for a week's menu or a long recipe; calls that need less say so.
DEFAULT_MAX_TOKENS = 16000
WEB_SEARCH_TOOL = "web_search_20250305"
# JSON Schema keywords structured outputs do not accept.
_UNSUPPORTED_SCHEMA_KEYS = {
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "minLength",
    "maxLength",
}
_DATA_URL = re.compile(r"^data:(?P<type>[\w/+.-]+);base64,(?P<data>.+)$", re.DOTALL)
_STOP_REASONS = {"end_turn": "stop", "max_tokens": "length", "tool_use": "tool_calls"}
# How each model is told not to think, learned from its own error message (see the docstring).
_THINKING_OFF: dict[str, dict[str, str]] = {}


class AnthropicChat(_HTTPProvider):
    def __init__(
        self,
        *,
        thinking: bool = False,
        web_search: bool = False,
        max_searches: int = 1,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.thinking = thinking
        self.web_search = web_search
        self.max_searches = max_searches

    # -- HTTP --------------------------------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"x-api-key": self._api_key or "", "anthropic-version": API_VERSION}

    def _raise_for_status(self, response: httpx.Response, path: str) -> None:
        # Rate limited or overloaded: the provider is there but cannot answer now.
        if response.status_code in (429, 529):
            raise AIUnavailableError(
                f"Anthropic is busy ({response.status_code}): {_detail(response)}"
            )
        super()._raise_for_status(response, path)

    def health(self) -> dict[str, Any]:
        try:
            self._request("GET", f"/v1/models/{self.model}")
        except AIError as exc:
            return {"ok": False, "base_url": self._base_url, "model": self.model, "error": str(exc)}
        return {"ok": True, "base_url": self._base_url, "model": self.model, "model_listed": True}

    # -- requests ----------------------------------------------------------------------------

    def _payload(
        self,
        messages: list[ChatMessage],
        *,
        max_tokens: int | None,
        tools: list[dict[str, Any]] | None,
        response_format: dict[str, Any] | None,
    ) -> dict[str, Any]:
        system, turns = to_anthropic_messages(messages)
        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": max_tokens or DEFAULT_MAX_TOKENS,
            "messages": turns,
            # Summarized: the reasoning is shown as progress, never needed word for word.
            "thinking": {"type": "adaptive", "display": "summarized"}
            if self.thinking
            else _THINKING_OFF.get(self.model, {"type": "disabled"}),
        }
        if system:
            payload["system"] = system
        claude_tools = [to_anthropic_tool(t) for t in tools or []]
        if self.web_search:
            claude_tools.append(
                {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": self.max_searches}
            )
        if claude_tools:
            payload["tools"] = claude_tools
        if response_format and response_format.get("type") == "json_schema":
            schema = (response_format.get("json_schema") or {}).get("schema") or {}
            payload["output_config"] = {
                "format": {"type": "json_schema", "schema": structured_schema(schema)}
            }
        return payload

    def chat(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        tools: list[dict[str, Any]] | None = None,
        response_format: dict[str, Any] | None = None,
    ) -> ChatResult:
        payload = self._payload(
            messages, max_tokens=max_tokens, tools=tools, response_format=response_format
        )
        data = self._with_thinking_off(
            payload, lambda: self._request("POST", "/v1/messages", json=payload).json()
        )
        return from_anthropic_response(data)

    def _with_thinking_off(self, payload: dict[str, Any], send: Callable[[], Any]) -> Any:
        """Send; if the model refused how thinking was turned off, learn its way and resend."""
        try:
            return send()
        except AIError as exc:
            if self.thinking or "between_tools" not in str(exc):
                raise
            _THINKING_OFF[self.model] = {"type": "between_tools"}
            payload["thinking"] = _THINKING_OFF[self.model]
            return send()

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
        """Like `chat`, receiving the answer as it is written: `on_delta("reasoning" or
        "content", text)`; past `deadline` (a `time.monotonic()` value) the call is abandoned."""
        payload = self._payload(
            messages, max_tokens=max_tokens, tools=None, response_format=response_format
        )
        payload["stream"] = True
        return self._with_thinking_off(payload, lambda: self._stream(payload, on_delta, deadline))

    def _stream(
        self,
        payload: dict[str, Any],
        on_delta: Callable[[str, str], None],
        deadline: float | None,
    ) -> ChatResult:
        path = "/v1/messages"
        content: list[str] = []
        stop_reason = None
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
                    event = json.loads(line[5:].strip() or "{}")
                    kind = event.get("type")
                    if kind == "error":
                        raise AIError(f"Anthropic stream error: {event.get('error')}")
                    if kind == "message_delta":
                        stop_reason = (event.get("delta") or {}).get("stop_reason") or stop_reason
                    if kind != "content_block_delta":
                        continue
                    delta = event.get("delta") or {}
                    if delta.get("type") == "thinking_delta" and delta.get("thinking"):
                        on_delta("reasoning", delta["thinking"])
                    elif delta.get("type") == "text_delta" and delta.get("text"):
                        content.append(delta["text"])
                        on_delta("content", delta["text"])
        except httpx.ConnectError as exc:
            raise AIUnavailableError(f"{self._base_url} is not reachable.") from exc
        except httpx.TimeoutException as exc:
            raise AIUnavailableError(
                f"{self._base_url} stopped answering for {self._timeout:.0f}s on {path}."
            ) from exc
        return ChatResult(
            content="".join(content).strip(),
            finish_reason=_STOP_REASONS.get(stop_reason, stop_reason),
        )


# -- translation (pure functions, tested on their own) ------------------------------------------


def _tool_id(value: str | None) -> str:
    """Claude's tool ids are letters, digits, `_` and `-`; ids from other providers (or ours,
    "import-3") are mapped the same way on the call and on its result, so they still pair."""
    return re.sub(r"[^A-Za-z0-9_-]", "_", value or "") or "call"


def _content_blocks(content: Any) -> list[dict[str, Any]]:
    if content is None:
        return []
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content.strip() else []
    blocks = []
    for part in content:
        if part.get("type") == "text" and (part.get("text") or "").strip():
            blocks.append({"type": "text", "text": part["text"]})
        elif part.get("type") == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if match := _DATA_URL.match(url):
                source = {"type": "base64", "media_type": match["type"], "data": match["data"]}
            else:
                source = {"type": "url", "url": url}
            blocks.append({"type": "image", "source": source})
    return blocks


def to_anthropic_messages(messages: list[ChatMessage]) -> tuple[str, list[dict[str, Any]]]:
    """OpenAI-format messages as Claude's `system` and `messages`."""
    system: list[str] = []
    turns: list[dict[str, Any]] = []

    def add(role: str, blocks: list[dict[str, Any]]) -> None:
        if not blocks:
            return
        if turns and turns[-1]["role"] == role:
            # Tool results lead the user turn that follows a tool use.
            turns[-1]["content"].extend(blocks)
        else:
            turns.append({"role": role, "content": list(blocks)})

    for message in messages:
        role = message.get("role")
        if role == "system":
            if text := str(message.get("content") or "").strip():
                system.append(text)
        elif role == "tool":
            add(
                "user",
                [
                    {
                        "type": "tool_result",
                        "tool_use_id": _tool_id(message.get("tool_call_id")),
                        "content": str(message.get("content") or ""),
                    }
                ],
            )
        elif role == "assistant":
            blocks = _content_blocks(message.get("content"))
            for call in message.get("tool_calls") or []:
                function = call.get("function") or {}
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": _tool_id(call.get("id")),
                        "name": function.get("name") or "tool",
                        "input": arguments if isinstance(arguments, dict) else {},
                    }
                )
            add("assistant", blocks)
        else:
            add("user", _content_blocks(message.get("content")))
    # A conversation starts with the user.
    if turns and turns[0]["role"] != "user":
        turns.insert(0, {"role": "user", "content": [{"type": "text", "text": "(start)"}]})
    return "\n\n".join(system), turns


def to_anthropic_tool(tool: dict[str, Any]) -> dict[str, Any]:
    function = tool.get("function") or tool
    return {
        "name": function["name"],
        "description": function.get("description", ""),
        "input_schema": function.get("parameters") or {"type": "object", "properties": {}},
    }


def structured_schema(schema: Any) -> Any:
    """A JSON Schema as structured outputs accept it: without numeric or length bounds, and with
    every object closed (`additionalProperties: false`). The app validates values itself."""
    if isinstance(schema, list):
        return [structured_schema(item) for item in schema]
    if not isinstance(schema, dict):
        return schema
    result = {
        key: structured_schema(value)
        for key, value in schema.items()
        if key not in _UNSUPPORTED_SCHEMA_KEYS
    }
    types = result.get("type")
    if types == "object" or (isinstance(types, list) and "object" in types):
        result["additionalProperties"] = False
    return result


def from_anthropic_response(data: dict[str, Any]) -> ChatResult:
    """Claude's reply as the OpenAI-shaped `ChatResult` the app expects."""
    texts: list[str] = []
    tool_calls: list[dict[str, Any]] = []
    found_urls: list[str] = []
    for block in data.get("content") or []:
        kind = block.get("type")
        if kind == "text":
            texts.append(block.get("text") or "")
        elif kind == "tool_use":
            tool_calls.append(
                {
                    "id": block.get("id"),
                    "type": "function",
                    "function": {
                        "name": block.get("name"),
                        "arguments": json.dumps(block.get("input") or {}, ensure_ascii=False),
                    },
                }
            )
        elif kind == "web_search_tool_result" and isinstance(block.get("content"), list):
            found_urls += [r["url"] for r in block["content"] if r.get("url")]
    content = "".join(texts).strip()
    if found_urls and "http" not in content:
        # The callers read result URLs from the text: keep them when the model left them out.
        content = "\n".join([content, *found_urls]).strip()
    stop = data.get("stop_reason")
    return ChatResult(
        content=content,
        tool_calls=tool_calls,
        finish_reason=_STOP_REASONS.get(stop, stop),
        raw=data,
    )
