"""One conversational turn of the recipe assistant.

The model either answers in text (usually a short question) or calls `propose_recipe` with a
complete draft. Every later correction ("three eggs, not two") makes it call the tool again with
the whole updated draft, so the latest call is always the current draft.

A message containing a link (in "tell" or "link" mode) is handled differently: the page is read
(`web.py`), a separate extraction call turns its text into a draft, and that draft is recorded
in the history as if the model had proposed it, so later corrections work the same way.

A photo goes through the same extraction, after a first, strictly literal transcription by the
vision model: asked merely to "transcribe", models embellish (Qwen once added steps that were not
on the card). Photos of the same session are read together, so a recipe spanning two pages can
be sent as two photos.
"""

from __future__ import annotations

import base64
import json
import logging
from dataclasses import dataclass
from typing import Any

from ai import ChatProvider, get_chat_provider, get_vision_provider, get_web_search_provider

from . import search
from .draft import DRAFT_SCHEMA, normalize_draft
from .models import AssistantSession, Attachment, Mode
from .web import TEXT_BUDGET_CHARS, PageError, PageRecipe, find_url, read_recipe_page

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
- Fill category and season_months for each ingredient, and climate_months for the dish, from \
general knowledge; the user will review them.
- season_months: the months the ingredient is in season in Italy. Fresh vegetables, fruit and \
most fish have a season: give it (e.g. leek: Sep-Apr, zucchini: May-Sep, basil: Jun-Sep). Use \
an empty list for what is available all year regardless of season: pantry staples (pasta, rice, \
flour, oil, salt, spices, sugar, dried legumes, eggs, milk, cheese, cured meats), potatoes, \
onions, garlic, and evergreen herbs (rosemary, sage, bay leaf, thyme, parsley).
- climate_months: the months the dish suits the weather (hot soups and oven dishes in the cold \
months, cold salads in the warm ones); empty only if it suits any season.
- Keep replies to one or two sentences in {language}: the draft is shown to the user \
separately, do not repeat it in text.
"""

SYSTEM_PROMPTS = {
    Mode.PHOTO: """\
You help a family add a recipe to their recipe book from photos (a cookbook page, a handwritten \
card, a screenshot). The draft you see was transcribed from the user's photos. Apply the user's \
corrections faithfully; do not add anything the photos or the user did not say. If the user \
sends another photo, it is read for you.
"""
    + _COMMON_RULES,
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

TRANSCRIPTION_PROMPT = """\
Transcribe, word for word, all the text written in this image.
- Copy exactly what is written: same words, same numbers, same order. Keep the original language.
- Do not add, complete, explain, correct or reformat anything; do not add steps or details that \
are not written.
- Keep line breaks and list structure. Where a word is illegible write [?].
- If the image contains no text, answer exactly: NO TEXT
"""

EXTRACTION_PROMPT = """\
Turn the recipe in the text below into the JSON schema. The text comes from a web page, or is the \
transcription of photos (a cookbook page, a handwritten card, a screenshot).

- Use only what the text says for title, servings, times, ingredients, quantities and steps. \
Never invent or embellish. Take preparation and cooking times whenever the text states them \
(e.g. "Preparazione 15 min · Cottura 25 min" -> prep_minutes 15, cook_minutes 25). Leave out \
anything that is not part of the recipe (ads, comments, other recipes).
- Keep title, description and steps in the source's language.
- Ingredient names: always in {language} (translate them if the page is in another language), \
generic, singular, lowercase, so they match the family's catalog. The name is the basic \
ingredient; variety, origin and preparation go in the note. Examples in Italian: "pomodori \
pelati" -> name "pomodoro", note "pelati"; "pecorino romano DOP grattugiato" -> "pecorino", \
note "romano DOP, grattugiato"; "eggs" -> "uovo"; "parmesan" -> "parmigiano".
- Notes: a few words at most (variety, cut, "grated"); never copy explanations or advice from \
the page into them.
- For every ingredient give its category and season_months.
- Units: g, ml, pc (pieces), tt (to taste, quantity null). Convert kg, l, cups, ounces, pounds \
and spoons to g or ml (approximately) and keep the original measure in the note.
- You may infer course, cuisine (in {language}), each ingredient's category and season_months, \
and the dish's climate_months:
- season_months: the months the ingredient is in season in Italy. Fresh vegetables, fruit and \
most fish have a season: give it (e.g. leek: Sep-Apr, zucchini: May-Sep, basil: Jun-Sep). Use \
an empty list for what is available all year regardless of season: pantry staples (pasta, rice, \
flour, oil, salt, spices, sugar, dried legumes, eggs, milk, cheese, cured meats), potatoes, \
onions, garlic, and evergreen herbs (rosemary, sage, bay leaf, thyme, parsley).
- climate_months: the months the dish suits the weather (hot soups and oven dishes in the cold \
months, cold salads in the warm ones); empty only if it suits any season.
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
    photo: Attachment | None = None,
    vision: ChatProvider | None = None,
    search_chat: ChatProvider | None = None,
    verify_page=None,
) -> TurnResult:
    """Add the user's message, ask the model, record its answer. Saves the session."""
    chat = chat or get_chat_provider()
    language_name = LANGUAGE_NAMES.get(language, "Italian")
    if photo is not None:
        return _import_photo(
            session, text, photo, language_name, chat, vision or get_vision_provider()
        )
    url = find_url(text)
    if url:
        if session.mode == Mode.SEARCH:
            # A result was picked (or a link pasted): from here on, this is a link import, and
            # later messages correct the draft instead of searching again.
            session.mode = Mode.LINK
            session.save(update_fields=["mode"])
        return _import_link(session, text, url, language_name, chat, read_page)
    if session.mode == Mode.SEARCH:
        return _search(
            session,
            text,
            language_name,
            chat,
            search_chat or get_web_search_provider(),
            verify_page,
        )

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


def transcribe(photo: Attachment, vision: ChatProvider) -> str:
    """Literal transcription of the text in a photo; empty when there is none."""
    image = base64.b64encode(bytes(photo.data)).decode()
    result = vision.chat(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": TRANSCRIPTION_PROMPT},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{photo.content_type};base64,{image}"},
                    },
                ],
            }
        ],
        temperature=0,
        max_tokens=1500,
    )
    text = result.content.strip()
    return "" if text.upper().startswith("NO TEXT") else text


def _import_photo(session, text, photo, language_name, chat, vision) -> TurnResult:
    message = {
        "role": "user",
        "content": (text.strip() + " [photo]").strip(),
        "attachment": photo.pk,
    }
    session.messages = [*session.messages, message]
    error = None
    try:
        photo.transcription = transcribe(photo, vision)
        photo.save(update_fields=["transcription"])
        if len(photo.transcription) < 20:
            error = "no_text_in_photo"
        else:
            # Every photo of the session: a recipe may span several pages.
            pages = [a.transcription for a in session.attachments.all() if a.transcription]
            combined = "\n\n--- next photo ---\n\n".join(pages)[:TEXT_BUDGET_CHARS]
            draft = extract_draft(
                PageRecipe(url="", text=combined, structured=False), language_name, chat
            )
            if not draft["ingredients"] and not draft["steps"]:
                error = "no_recipe"
    except (json.JSONDecodeError, TypeError, AttributeError) as exc:
        log.warning("photo extraction unusable: %s", exc)
        error = "no_recipe"
    if error:
        return _record_failure(session, f"I could not read a recipe in the photo ({error}).", error)
    count = session.attachments.count()
    return _record_draft(
        session, draft, f"Draft transcribed from {count} photo(s) and shown to the user."
    )


def _record_failure(session, content: str, error: str) -> TurnResult:
    # Shown to the user (translated from `error` by the UI) and kept in the history so the model
    # knows the import failed.
    session.messages = [
        *session.messages,
        {"role": "assistant", "content": content, "error": error},
    ]
    session.save(update_fields=["messages", "updated_at"])
    return TurnResult(reply="", draft_updated=False, error=error)


def _record_draft(session, draft: dict[str, Any], outcome: str) -> TurnResult:
    """Record an imported draft as if the model had proposed it, for later corrections."""
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
        {"role": "tool", "tool_call_id": call_id, "content": outcome},
    ]
    session.save(update_fields=["messages", "draft", "updated_at"])
    return TurnResult(reply="", draft_updated=True)


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
        return _record_failure(session, f"I could not import a recipe from {url} ({error}).", error)
    return _record_draft(
        session, draft, f"Draft imported from {page.url} and shown to the user for review."
    )


def _search(session, text, language_name, chat, search_chat, verify_page) -> TurnResult:
    query = search.search_query(session.messages, text)
    session.messages = [*session.messages, {"role": "user", "content": text.strip()}]
    found = search.local_results(session.user, session.family, query)
    web, notice = search.web_results(
        query, language_name, search_chat, chat, **({"verify": verify_page} if verify_page else {})
    )
    found += web
    titles = "; ".join(r["title"] for r in found) or "nothing"
    message = {
        "role": "assistant",
        # For the model, should the conversation continue: what was shown.
        "content": f"Search results shown to the user: {titles}.",
        "results": found,
    }
    if notice:
        message["notice"] = notice
    session.messages = [*session.messages, message]
    session.save(update_fields=["messages", "updated_at"])
    return TurnResult(reply="", draft_updated=False)
