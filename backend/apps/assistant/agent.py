"""One conversational turn of the recipe assistant.

The model either answers in text (usually a short question) or calls `propose_recipe` with a
complete draft. Every later correction ("three eggs, not two") makes it call the tool again with
the whole updated draft, so the latest call is always the current draft.

A message containing a link (in "tell" or "link" mode) is handled differently: the page is read
(`web.py`), a separate extraction call turns its text into a draft, and that draft is recorded
in the history as if the model had proposed it, so later corrections work the same way.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any

from ai import ChatProvider, get_chat_provider

from .draft import DRAFT_SCHEMA, normalize_draft
from .models import AssistantSession, Mode
from .web import PageError, PageRecipe, find_url, read_recipe_page

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

_COMMON_RULES = """\
- After every correction, call propose_recipe again with the whole updated draft. Never drop \
something the user said; never contradict them.
- Ingredient names: generic, singular, lowercase ("tomato", not "peeled tomatoes"; details go in \
the note). Units: g, ml, pc (pieces), tt (to taste, with quantity null). Convert kg and l.
- Fill category and season_months for each ingredient, and climate_months for the dish \
(empty = all year), from general knowledge; the user will review them.
- Keep replies to one or two sentences in {language}: the draft is shown to the user \
separately, do not repeat it in text.
"""

SYSTEM_PROMPTS = {
    Mode.LINK: """\
You help a family import a recipe from a web page into their recipe book. The draft you see was \
extracted from the page the user linked. Apply the user's corrections faithfully; do not add \
anything the page or the user did not say. If the user sends another link, it is imported for \
you.
"""
    + _COMMON_RULES,
    Mode.TELL: """\
You help a family add a recipe they know to their recipe book. The user describes it in their \
own words.

- As soon as you know the dish, call propose_recipe with a complete draft. Do not ask \
permission first.
- If the user did not give quantities, servings or times, propose usual ones for that dish and \
say in one short sentence that they are your suggestion.
- Ask a question only when something essential is really unclear (e.g. which dish they mean). \
At most one short question at a time.
- Write the recipe, including the cuisine name, in {language}.
"""
    + _COMMON_RULES,
}

EXTRACTION_PROMPT = """\
Turn the recipe in the text below into the JSON schema. The text comes from a web page.

- Use only what the text says for title, servings, times, ingredients, quantities and steps. \
Never invent or embellish. Leave out anything that is not part of the recipe (ads, comments, \
other recipes).
- Keep title, description and steps in the page's language.
- Ingredient names: always in {language} (translate them if the page is in another language), \
generic, singular, lowercase, so they match the family's catalog. The name is the basic \
ingredient; variety, origin and preparation go in the note. Examples in Italian: "pomodori \
pelati" -> name "pomodoro", note "pelati"; "pecorino romano DOP grattugiato" -> "pecorino", \
note "romano DOP, grattugiato"; "eggs" -> "uovo"; "parmesan" -> "parmigiano".
- Notes: a few words at most (variety, cut, "grated"); never copy explanations or advice from \
the page into them.
- For every ingredient give its category and season_months (empty = all year).
- Units: g, ml, pc (pieces), tt (to taste, quantity null). Convert kg, l, cups, ounces, pounds \
and spoons to g or ml (approximately) and keep the original measure in the note.
- You may infer course, cuisine (in {language}), each ingredient's category and season_months, \
and the dish's climate_months (empty = all year).
- If the text contains no recipe, return an empty title, no ingredients and no steps.
"""


@dataclass
class TurnResult:
    reply: str
    draft_updated: bool
    # Stable code when a linked page could not be imported (see web.PageError).
    error: str | None = None


# Keys the chat API accepts in a message; anything else (e.g. our "error" code) stays local.
_MESSAGE_KEYS = {"role", "content", "tool_calls", "tool_call_id", "name"}


def _for_model(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [{k: v for k, v in m.items() if k in _MESSAGE_KEYS} for m in messages]


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
    read_page=read_recipe_page,
) -> TurnResult:
    """Add the user's message, ask the model, record its answer. Saves the session."""
    chat = chat or get_chat_provider()
    language_name = LANGUAGE_NAMES.get(language, "Italian")
    url = find_url(text) if session.mode in (Mode.TELL, Mode.LINK) else None
    if url:
        return _import_link(session, text, url, language_name, chat, read_page)

    system = SYSTEM_PROMPTS[session.mode].format(language=language_name)
    session.messages = [*session.messages, {"role": "user", "content": text.strip()}]

    history = _trim(session.messages)
    prompt = [{"role": "system", "content": system}]
    if session.draft and len(history) < len(session.messages):
        # Older turns were trimmed away: keep the current draft in view.
        prompt.append({"role": "system", "content": "Current draft: " + json.dumps(session.draft)})
    result = chat.chat([*prompt, *_for_model(history)], temperature=0.3, tools=[PROPOSE_RECIPE])

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
                    draft = normalize_draft(json.loads(function.get("arguments") or "{}"))
                    # The model tends to drop the source when rewriting the draft.
                    if session.draft and not draft["source_url"]:
                        draft["source_url"] = session.draft.get("source_url", "")
                    session.draft = draft
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


def extract_draft(page: PageRecipe, language_name: str, chat: ChatProvider) -> dict[str, Any]:
    """Structure a page's recipe text into a draft. Facts from structured data win."""
    result = chat.chat(
        [
            {"role": "system", "content": EXTRACTION_PROMPT.format(language=language_name)},
            {"role": "user", "content": page.text},
        ],
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {"name": "recipe", "schema": DRAFT_SCHEMA},
        },
    )
    draft = normalize_draft(json.loads(result.content or "{}"))
    for key, value in page.facts.items():
        # Title, servings, times and steps read verbatim from schema.org data are kept as the
        # page states them, rather than as the model rewrote them.
        if value:
            draft[key] = value
    return draft


def _import_link(session, text, url, language_name, chat, read_page) -> TurnResult:
    session.messages = [*session.messages, {"role": "user", "content": text.strip()}]
    error = None
    try:
        page = read_page(url)
        draft = extract_draft(page, language_name, chat)
        if not draft["ingredients"] and not draft["steps"]:
            error = "no_recipe"
    except PageError as exc:
        log.info("could not read %s: %s", url, exc)
        error = exc.reason
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        log.warning("extraction from %s unusable: %s", url, exc)
        error = "no_recipe"

    if error:
        # Shown to the user (translated from `error` by the UI) and kept in the history so the
        # model knows the import failed.
        session.messages = [
            *session.messages,
            {
                "role": "assistant",
                "content": f"I could not import a recipe from {url} ({error}).",
                "error": error,
            },
        ]
        session.save(update_fields=["messages", "updated_at"])
        return TurnResult(reply="", draft_updated=False, error=error)

    call_id = f"import-{len(session.messages)}"
    session.draft = draft
    session.messages = [
        *session.messages,
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": call_id,
                    "type": "function",
                    "function": {
                        "name": "propose_recipe",
                        "arguments": json.dumps(draft, ensure_ascii=False),
                    },
                }
            ],
        },
        {
            "role": "tool",
            "tool_call_id": call_id,
            "content": f"Draft imported from {page.url} and shown to the user for review.",
        },
    ]
    session.save(update_fields=["messages", "draft", "updated_at"])
    return TurnResult(reply="", draft_updated=True)
