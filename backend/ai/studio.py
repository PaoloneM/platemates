"""Unsloth Studio specifics, on top of the OpenAI-compatible protocol.

Behaviour carried over from the `spyone` project, where it was verified against Studio 2026.9.2:

- Auth is a bearer API key created under Settings -> API keys (or keyless routes, if enabled).
- `{"detail": "Not authenticated"}` means a missing/expired key, not a bug; 503 means no model
  is loaded.
- Studio serves only the loaded chat model unless "Switch model by request" (Settings -> API) is
  on; with it off, a mismatched `model` fails with an unhelpful 404, so we check first.
- `enable_thinking` toggles the reasoning trace of thinking models; `enable_tools` toggles Studio's
  own server-side tools, which include a working web search (verified 2026-10-05: cited URLs
  resolved). Both are off unless asked for; when tools are on, only `web_search` is enabled and
  the number of tool calls per message is capped (see `SAFE_TOOLS`). Client-side function
  calling (`tools=`) works independently of `enable_tools`.
"""

from __future__ import annotations

from typing import Any

from .base import ModelNotLoadedError
from .openai_compatible import OpenAICompatibleChat

# Studio's server-side tools for local models include `python`, `terminal` and `edit_file`,
# which run on the Studio host. Prompts carry user text, so a prompt injection could run commands
# on the machine: only ever enable the web search.
SAFE_TOOLS = ["web_search"]


class StudioChat(OpenAICompatibleChat):
    PROVIDER = "unsloth_studio"

    def __init__(
        self,
        *,
        enable_thinking: bool = False,
        enable_tools: bool = False,
        max_tool_calls: int = 1,
        tool_timeout_seconds: int = 15,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self.enable_thinking = enable_thinking
        self.enable_tools = enable_tools
        # Tool-call iterations per message (Studio's default is 25). Left free, the model chains
        # searches: 90-110 s and a nearly full context, against 6-15 s for one search.
        self.max_tool_calls = max_tool_calls
        # Per tool call (Studio's default is 300 s). Its web search sometimes hangs: better to
        # fail fast and let the caller retry than to hold a request for minutes.
        self.tool_timeout_seconds = tool_timeout_seconds

    def _extra_payload(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "enable_thinking": self.enable_thinking,
            "enable_tools": self.enable_tools,
        }
        if self.enable_tools:
            payload["enabled_tools"] = SAFE_TOOLS
            payload["max_tool_calls_per_message"] = self.max_tool_calls
            payload["tool_call_timeout"] = self.tool_timeout_seconds
        return payload

    def is_model_loaded(self) -> bool:
        return any(
            entry.get("id") == self.model and entry.get("loaded") for entry in self._list_models()
        )

    def auto_switches_models(self) -> bool:
        """Whether Studio loads a requested chat model on demand ("Switch model by request")."""
        return bool(self._request("GET", "/api/settings/openai-auto-switch").json().get("enabled"))

    def ensure_model_available(self) -> None:
        """Raise a clear error if the model is neither loaded nor auto-loadable."""
        if self.is_model_loaded() or self.auto_switches_models():
            return
        raise ModelNotLoadedError(
            f"'{self.model}' is not the loaded chat model in Unsloth Studio. Load it there, or "
            "turn on 'Switch model by request' under Settings > API."
        )

    def health(self) -> dict[str, Any]:
        report = super().health()
        if not report["ok"]:
            return report
        try:
            report["model_loaded"] = self.is_model_loaded()
            report["auto_switch"] = self.auto_switches_models()
        except Exception as exc:  # health must never raise
            report["warning"] = str(exc)
        return report
