"""One conversational turn of the recipe assistant.

The model either answers in text (usually a short question) or calls `propose_recipe` with a
complete draft. Every later correction ("three eggs, not two") makes it call the tool again with
the whole updated draft, so the latest call is always the current draft.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ai import ChatProvider, get_chat_provider

from .draft import DRAFT_SCHEMA, normalize_draft
from .models import AssistantSession, Mode

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {"it": "Italian", "en": "English"}

# The chat model currently runs with an 8k-token context: keep the history well below it,
# leaving room for the system prompt, the tool schema and the answer.
HISTORY_BUDGET_CHARS = 9000

PROPOSE_RECIPE = {
    "type": "function",
    "function": {
        "name": "propose_recipe",
        "description": (
            "Show the user a complete recipe draft to review. Call it again with the whole "
            "updated draft after every correction."
        ),
        "parameters": DRAFT_SCHEMA,
    },
}

SYSTEM_PROMPTS = {
    Mode.TELL: """\
You help a family add a recipe they know to their recipe book. The user describes it in their \
own words.

- As soon as you know the dish, call propose_recipe with a complete draft. Do not ask \
permission first.
- If the user did not give quantities, servings or times, propose usual ones for that dish and \
say in one short sentence that they are your suggestion.
- Ask a question only when something essential is really unclear (e.g. which dish they mean). \
At most one short question at a time.
- After every correction, call propose_recipe again with the whole updated draft. Never drop \
something the user said; never contradict them.
- Ingredient names: generic, singular, lowercase ("tomato", not "peeled tomatoes"; details go in \
the note). Units: g, ml, pc (pieces), tt (to taste, with quantity null). Convert kg and l.
- Fill category and season_months for each ingredient, and climate_months for the dish \
(empty = all year), from general knowledge; the user will review them.
- Write the recipe (including the cuisine name) and your replies in {language}. Keep replies to one or two sentences: the \
draft is shown to the user separately, do not repeat it in text.
""",
}


@dataclass
class TurnResult:
    reply: str
    draft_updated: bool


def _trim(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop the oldest exchanges until the history fits the budget.

    Cuts only before a user message, so tool calls and their results stay paired. The current
    draft is never lost: it is re-sent as a system note by `run_turn`.
    """
    size = lambda msgs: sum(len(json.dumps(m, ensure_ascii=False)) for m in msgs)  # noqa: E731
    while size(history) > HISTORY_BUDGET_CHARS:
        cuts = [i for i, m in enumerate(history) if m["role"] == "user" and i > 0]
        if not cuts:
            break
        history = history[cuts[0] :]
    return history


def run_turn(
    session: AssistantSession,
    text: str,
    language: str = "it",
    chat: ChatProvider | None = None,
) -> TurnResult:
    """Add the user's message, ask the model, record its answer. Saves the session."""
    chat = chat or get_chat_provider()
    system = SYSTEM_PROMPTS[session.mode].format(language=LANGUAGE_NAMES.get(language, "Italian"))
    session.messages = [*session.messages, {"role": "user", "content": text.strip()}]

    history = _trim(session.messages)
    prompt = [{"role": "system", "content": system}]
    if session.draft and len(history) < len(session.messages):
        # Older turns were trimmed away: keep the current draft in view.
        prompt.append({"role": "system", "content": "Current draft: " + json.dumps(session.draft)})
    result = chat.chat([*prompt, *history], temperature=0.3, tools=[PROPOSE_RECIPE])

    draft_updated = False
    assistant: dict[str, Any] = {"role": "assistant", "content": result.content}
    tool_results: list[dict[str, Any]] = []
    if result.tool_calls:
        assistant["tool_calls"] = result.tool_calls
        for call in result.tool_calls:
            function = call.get("function") or {}
            outcome = "Draft shown to the user for review."
            if function.get("name") != "propose_recipe":
                outcome = f"Unknown tool {function.get('name')!r}."
            else:
                try:
                    session.draft = normalize_draft(json.loads(function.get("arguments") or "{}"))
                    draft_updated = True
                except (json.JSONDecodeError, TypeError, AttributeError) as exc:
                    log.warning("propose_recipe with unusable arguments: %s", exc)
                    outcome = f"The draft could not be read ({exc}); call propose_recipe again."
            tool_results.append(
                {"role": "tool", "tool_call_id": call.get("id", ""), "content": outcome}
            )
    session.messages = [*session.messages, assistant, *tool_results]
    session.save(update_fields=["messages", "draft", "updated_at"])
    return TurnResult(reply=result.content, draft_updated=draft_updated)
