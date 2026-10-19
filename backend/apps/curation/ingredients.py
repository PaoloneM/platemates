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

# What each category holds, for the model (the catalog's own use of them).
CATEGORY_GUIDE = """\
vegetable: vegetables, salad, mushrooms, potatoes; fruit: fresh fruit; legume: beans, \
chickpeas, lentils, peas; cereal: flour, pasta, rice, noodles, bread, breadcrumbs, tortillas; \
red_meat: beef, pork, lamb; white_meat: chicken, turkey, rabbit; cured_meat: ham, bacon, \
sausages, salami; fish; seafood: shellfish, molluscs; egg; dairy: milk, cream, butter, \
yogurt, bechamel; cheese: every cheese, grated or not; fat: cooking oils, lard; nut_seed: \
nuts and seeds (sesame); herb_spice: herbs, spices, chili, saffron, spice mixes; condiment: \
salt, vinegar, sauces, stock, tomato paste, wine for cooking; sweetener: sugar, honey, \
chocolate, cocoa; other: anything else (water, yeast)."""

CLASSIFY_PROMPT = """\
An ingredient name from a recipe in {language}: "{name}". The catalog does not have this name.
{candidates}

- same_as: the catalog entry this is just another name of: a plural, another spelling, a \
grade, cut or form cooks use the same way ("sale fino" is "sale", "zafferano in pistilli" is \
"zafferano", "olio extravergine di oliva" is "olio extravergine d'oliva"). "none" when it is a \
different ingredient. Preserved products (canned, dried, frozen, puree, pickled) are never the \
fresh one.
- category, one of: {guide}
- season_months: the months it is in season in Italy when fresh; empty when available all year \
or preserved.
- default_unit: g, ml or pc.
- basic: true only for pantry staples in almost every dish (salt, pepper, water, cooking oil); \
false for everything else."""


def _schema(options: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "same_as": {"type": "string", "enum": [*options, "none"]},
            "category": {"type": "string", "enum": IngredientCategory.values},
            "season_months": {"type": "array", "items": {"type": "integer"}},
            "default_unit": {"type": "string", "enum": ["g", "ml", "pc"]},
            "basic": {"type": "boolean"},
        },
        "required": ["same_as", "category", "season_months", "default_unit", "basic"],
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


def classify_one(
    name: str, line: dict[str, Any], language: str, chat: ChatProvider
) -> dict[str, Any]:
    """What the model proposes for one unknown name: another name of one of the similar
    catalog entries, or a new ingredient. The draft's own guess when the model fails."""
    guess = _line_guess(line)
    candidates = match_ingredient(name)["candidates"]
    by_name = {c["name"]: c["id"] for c in candidates}
    listed = (
        "Catalog entries like it: " + ", ".join(f'"{n}"' for n in by_name)
        if by_name
        else "The catalog has nothing like it."
    )
    prompt = CLASSIFY_PROMPT.format(
        language=LANGUAGE_NAMES.get(language, "Italian"),
        name=name,
        candidates=listed,
        guide=CATEGORY_GUIDE,
    )
    try:
        answer = chat.chat(
            [{"role": "user", "content": prompt}],
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "ingredient", "schema": _schema(list(by_name))},
            },
        )
        row = json.loads(answer.content or "{}")
    except (AIError, ValueError) as exc:
        log.warning("classifying %r failed, keeping the draft's guess: %s", name, exc)
        return guess
    if row.get("same_as") in by_name:
        return {**guess, "action": "alias", "alias_of": by_name[row["same_as"]]}
    category = row.get("category")
    unit = row.get("default_unit")
    months = sorted(
        {m for m in row.get("season_months") or [] if isinstance(m, int) and 1 <= m <= 12}
    )
    return {
        "action": "new",
        "category": category if category in IngredientCategory.values else guess["category"],
        "season_months": [] if len(months) == 12 else months,
        "default_unit": unit if unit in ("g", "ml", "pc") else guess["default_unit"],
        "basic": bool(row.get("basic")),
    }


def propose_for(draft: SystemDraft, chat: ChatProvider) -> list[IngredientProposal]:
    """Make sure every unknown name of the draft has a proposal, linked to the draft."""
    lines = {line["name"]: line for line in (draft.draft or {}).get("ingredients") or []}
    unknown = {name: line for name, line in lines.items() if known(name) is None}
    if not unknown:
        return []
    existing = {p.name: p for p in IngredientProposal.objects.filter(name__in=unknown)}
    fresh = {name: line for name, line in unknown.items() if name not in existing}
    if fresh:
        for name, line in fresh.items():
            guess = classify_one(name, line, draft.language, chat)
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
