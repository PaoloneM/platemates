"""Ingredients a draft names that the catalog does not know.

A draft's line is resolved when its name is a system ingredient's name or alias. The other
names become `IngredientProposal`s, one per name however many drafts use it, with what the
model proposes: another name (an alias) of one of the similar catalog entries, or a new
ingredient with its category, season, usual unit and whether it is a pantry staple. Nothing
enters the catalog until staff approve the proposal; approving one publishes the drafts that
were waiting only for it (`publishing.auto_publish`).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from django.db import transaction
from django.utils import timezone

from ai import AIError, ChatProvider
from apps.assistant.agent import LANGUAGE_NAMES
from apps.catalog.matching import match_ingredient
from apps.catalog.models import Ingredient, IngredientCategory, Unit, normalize_name
from apps.core.provenance import Source

from .models import IngredientProposal, SystemDraft

log = logging.getLogger(__name__)

CLASSIFY_PROMPT = """\
A recipe catalog does not know these ingredient names, used by recipes written in {language}. \
For each name decide:
- "alias" when it is just another name of one of the catalog entries listed with it (a plural, \
another spelling, a variety cooks treat as the same thing): give that entry's id;
- "new" when it is a distinct ingredient: give its category, the months it is in season in \
Italy when fresh (empty when it is available all year, or preserved), its usual unit (g, ml or \
pc) and whether it is a pantry staple in almost every kitchen (salt, water, oil, black pepper).
Preserved products (canned, dried, frozen, puree, pickled) are distinct from the fresh one, \
never its alias. When unsure, choose "new".

{items}"""

CLASSIFY_SCHEMA = {
    "type": "object",
    "properties": {
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "action": {"type": "string", "enum": ["alias", "new"]},
                    "alias_of": {"type": ["integer", "null"]},
                    "category": {"type": "string", "enum": IngredientCategory.values},
                    "season_months": {"type": "array", "items": {"type": "integer"}},
                    "default_unit": {"type": "string", "enum": ["g", "ml", "pc"]},
                    "basic": {"type": "boolean"},
                },
                "required": ["name", "action", "category", "default_unit", "basic"],
            },
        }
    },
    "required": ["ingredients"],
}


def known(name: str) -> Ingredient | None:
    """The system ingredient with this name or alias."""
    match = match_ingredient(name)
    if match["exact"]:
        return Ingredient.objects.get(pk=match["match"])
    return None


def resolve(name: str) -> Ingredient | None:
    """The catalog entry a draft line stands for: known, or its proposal approved."""
    if (ingredient := known(name)) is not None:
        return ingredient
    proposal = IngredientProposal.objects.filter(
        name=normalize_name(name), status=IngredientProposal.Status.APPROVED
    ).first()
    return proposal.ingredient if proposal else None


def unresolved(draft: SystemDraft) -> list[str]:
    """The draft's ingredient names that are neither known nor approved."""
    lines = (draft.draft or {}).get("ingredients") or []
    return [line["name"] for line in lines if resolve(line["name"]) is None]


def _line_guess(line: dict[str, Any]) -> dict[str, Any]:
    """What the draft itself says about an ingredient: the fallback when the model cannot be
    asked."""
    unit = line.get("unit")
    return {
        "action": IngredientProposal.Action.NEW,
        "category": line.get("category") or IngredientCategory.OTHER,
        "season_months": sorted(line.get("season_months") or []),
        "default_unit": unit if unit in (Unit.GRAM, Unit.MILLILITRE, Unit.PIECE) else Unit.GRAM,
        "basic": False,
    }


def classify(
    names: dict[str, dict[str, Any]], language: str, chat: ChatProvider
) -> dict[str, dict[str, Any]]:
    """What the model proposes for each unknown name (`names`: name -> its draft line)."""
    candidates = {name: match_ingredient(name)["candidates"] for name in names}
    items = "\n".join(
        f"- {name}: "
        + (
            "catalog entries like it: "
            + ", ".join(f'id {c["id"]} "{c["name"]}"' for c in candidates[name])
            if candidates[name]
            else "no similar catalog entry"
        )
        for name in names
    )
    guesses = {name: _line_guess(line) for name, line in names.items()}
    try:
        answer = chat.chat(
            [
                {
                    "role": "user",
                    "content": CLASSIFY_PROMPT.format(
                        language=LANGUAGE_NAMES.get(language, "Italian"), items=items
                    ),
                }
            ],
            temperature=0.1,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ingredients", "schema": CLASSIFY_SCHEMA},
            },
        )
        rows = json.loads(answer.content or "{}").get("ingredients") or []
    except (AIError, ValueError) as exc:
        log.warning("classifying ingredients failed, keeping the drafts' guesses: %s", exc)
        return guesses
    for row in rows:
        name = normalize_name(str(row.get("name") or ""))
        if name not in guesses:
            continue
        offered = {c["id"] for c in candidates[name]}
        if row.get("action") == "alias" and row.get("alias_of") in offered:
            guesses[name] = {**guesses[name], "action": "alias", "alias_of": row["alias_of"]}
            continue
        category = row.get("category")
        unit = row.get("default_unit")
        months = sorted(
            {m for m in row.get("season_months") or [] if isinstance(m, int) and 1 <= m <= 12}
        )
        guesses[name] = {
            "action": "new",
            "category": category
            if category in IngredientCategory.values
            else guesses[name]["category"],
            "season_months": [] if len(months) == 12 else months,
            "default_unit": unit if unit in ("g", "ml", "pc") else guesses[name]["default_unit"],
            "basic": bool(row.get("basic")),
        }
    return guesses


def propose_for(draft: SystemDraft, chat: ChatProvider) -> list[IngredientProposal]:
    """Make sure every unknown name of the draft has a proposal, linked to the draft."""
    lines = {line["name"]: line for line in (draft.draft or {}).get("ingredients") or []}
    unknown = {name: line for name, line in lines.items() if known(name) is None}
    if not unknown:
        return []
    existing = {p.name: p for p in IngredientProposal.objects.filter(name__in=unknown)}
    fresh = {name: line for name, line in unknown.items() if name not in existing}
    if fresh:
        for name, guess in classify(fresh, draft.language, chat).items():
            existing[name], _ = IngredientProposal.objects.get_or_create(
                name=name,
                defaults={
                    "action": guess["action"],
                    "alias_of_id": guess.get("alias_of"),
                    "category": guess["category"],
                    "season_months": guess["season_months"],
                    "default_unit": guess["default_unit"],
                    "basic": guess["basic"],
                },
            )
    proposals = [existing[name] for name in unknown]
    draft.ingredient_proposals.add(*proposals)
    return proposals


@transaction.atomic
def approve(proposal: IngredientProposal, user=None) -> Ingredient:
    """Put the proposal into the catalog: an alias added to the existing ingredient, or a new
    system ingredient. What staff changed is their decision; the rest is the model's."""
    proposal = IngredientProposal.objects.select_for_update().get(pk=proposal.pk)
    if proposal.status == IngredientProposal.Status.APPROVED and proposal.ingredient:
        return proposal.ingredient
    if proposal.action == IngredientProposal.Action.ALIAS and proposal.alias_of is not None:
        ingredient = proposal.alias_of
        if proposal.name != ingredient.name and proposal.name not in ingredient.aliases:
            ingredient.aliases = [*ingredient.aliases, proposal.name]
            ingredient.save()
    else:
        ingredient = known(proposal.name) or Ingredient(name=proposal.name, owner_team=None)
        if ingredient.pk is None:
            for field in ("category", "season_months", "default_unit"):
                value = getattr(proposal, field) or getattr(ingredient, field)
                if field in proposal.edited:
                    ingredient.set_by_user(field, value)
                else:
                    ingredient.propose(field, value, Source.LLM)
            ingredient.basic = proposal.basic
            ingredient.save()
    proposal.ingredient = ingredient
    proposal.status = IngredientProposal.Status.APPROVED
    proposal.decided_at = timezone.now()
    proposal.decided_by = user
    proposal.save()
    return ingredient


def reject(proposal: IngredientProposal, user=None) -> None:
    """Keep the name out of the catalog: the drafts that use it wait for staff."""
    proposal.status = IngredientProposal.Status.REJECTED
    proposal.decided_at = timezone.now()
    proposal.decided_by = user
    proposal.save(update_fields=["status", "decided_at", "decided_by"])
