"""The settings administrators can change, and how the app reads them.

Each setting has a stable key, by which the interface shows it translated, a type, a default
and limits. `get` returns the stored value, or the default when none is stored or the stored
one no longer fits the definition (a limit changed since it was saved).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from apps.core.cache import cache_manager

from .models import ConfigVar

CACHE_KEY = "siteconfig:values"


@dataclass(frozen=True)
class Setting:
    key: str
    kind: str  # "bool" or "int"
    default: Any
    group: str
    minimum: int | None = None
    maximum: int | None = None

    def clean(self, value: Any) -> Any:
        """The value if it fits this setting; raises ValueError otherwise."""
        if self.kind == "bool":
            if type(value) is not bool:
                raise ValueError("Expected true or false.")
            return value
        if type(value) is not int:
            raise ValueError("Expected a whole number.")
        if self.minimum is not None and value < self.minimum:
            raise ValueError(f"At least {self.minimum}.")
        if self.maximum is not None and value > self.maximum:
            raise ValueError(f"At most {self.maximum}.")
        return value


SETTINGS: dict[str, Setting] = {
    setting.key: setting
    for setting in [
        # The context window the chat model is loaded with (Unsloth Studio: set when loading
        # it). Prompt budgets follow it; it must not exceed what the model really has.
        Setting("llm.context_tokens", "int", 8192, "llm", minimum=4096, maximum=262144),
        # The chat model's own reasoning before it answers, when planning a week. Better plans,
        # about four times slower (2-2.5 min against 30 s on Qwen3.6-35B, 2026-10-08).
        Setting("menu.thinking", "bool", False, "menu"),
        # Longest a generation may take, both attempts included; past it, it fails.
        Setting("menu.max_seconds", "int", 360, "menu", minimum=60, maximum=1800),
    ]
}


def context_tokens() -> int:
    return get("llm.context_tokens")


def prompt_budget_chars() -> int:
    """How much source text (a conversation, transcribed photos) a prompt may carry, scaled to
    the context. 9000 characters at 8k tokens, the size the prompts were first tuned at."""
    return context_tokens() * 9000 // 8192


def stored_values() -> dict[str, Any]:
    """Every stored value, by key, through the cache (cleared whenever one changes)."""
    return cache_manager.get_or_load(
        CACHE_KEY, lambda: dict(ConfigVar.objects.values_list("key", "value"))
    )


def get(key: str) -> Any:
    setting = SETTINGS[key]
    stored = stored_values()
    if key not in stored:
        return setting.default
    try:
        return setting.clean(stored[key])
    except ValueError:
        return setting.default
