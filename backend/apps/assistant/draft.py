"""The recipe draft every assistant mode produces, and its normalization.

The same shape comes out of "tell me", link import and photo import, and goes into the recipe
editor for review. Whatever the model returns is normalized here: unknown units, categories or
courses fall back to safe values rather than failing, because the user reviews everything anyway.
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from apps.catalog.models import IngredientCategory, Unit, normalize_name
from apps.recipes.models import Course

MONTHS = {"type": "array", "items": {"type": "integer", "minimum": 1, "maximum": 12}}

DRAFT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "description": {"type": "string"},
        "course": {"type": "string", "enum": list(Course.values)},
        "cuisine": {
            "type": "string",
            "description": "cuisine type or origin, written in the recipe's language "
            "(e.g. 'italiana', 'giapponese' for an Italian recipe); empty if unknown",
        },
        "servings": {"type": "integer", "minimum": 1},
        "prep_minutes": {"type": ["integer", "null"]},
        "cook_minutes": {"type": ["integer", "null"]},
        "ingredients": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "generic, singular, lowercase: 'tomato', not 'peeled "
                        "tomatoes' (details go in note)",
                    },
                    "quantity": {"type": ["number", "null"]},
                    "unit": {
                        "type": "string",
                        "enum": list(Unit.values),
                        "description": "g, ml, pc (pieces) or tt (to taste, quantity null)",
                    },
                    "note": {"type": "string"},
                    "optional": {"type": "boolean"},
                    "category": {"type": "string", "enum": list(IngredientCategory.values)},
                    "season_months": {
                        **MONTHS,
                        "description": "months the ingredient is in season; empty = all year",
                    },
                },
                # Category and season are required so the model always proposes them: the
                # user then only confirms, instead of filling them in for every new ingredient.
                "required": ["name", "quantity", "unit", "category", "season_months"],
            },
        },
        "steps": {"type": "array", "items": {"type": "string"}},
        "climate_months": {
            **MONTHS,
            "description": "months the dish suits the weather; empty = all year",
        },
        "source_url": {"type": "string", "description": "page the recipe was imported from"},
    },
    "required": ["title", "servings", "ingredients", "steps"],
}

_UNIT_ALIASES = {
    "g": Unit.GRAM,
    "gr": Unit.GRAM,
    "grammi": Unit.GRAM,
    "gram": Unit.GRAM,
    "grams": Unit.GRAM,
    "kg": Unit.GRAM,
    "ml": Unit.MILLILITRE,
    "l": Unit.MILLILITRE,
    "cl": Unit.MILLILITRE,
    "pc": Unit.PIECE,
    "pz": Unit.PIECE,
    "pcs": Unit.PIECE,
    "piece": Unit.PIECE,
    "n": Unit.PIECE,
    "tt": Unit.TO_TASTE,
    "qb": Unit.TO_TASTE,
    "q.b.": Unit.TO_TASTE,
    "to taste": Unit.TO_TASTE,
}
_SCALE = {"kg": 1000, "l": 1000, "cl": 10}


def _int(value, minimum: int = 0) -> int | None:
    try:
        number = round(float(value))
    except (TypeError, ValueError):
        return None
    return number if number >= minimum else None


def _months(value) -> list[int]:
    if not isinstance(value, list):
        return []
    months = sorted({m for m in (_int(v, 1) for v in value) if m is not None and m <= 12})
    return [] if len(months) == 12 else months


def _line(raw: dict[str, Any]) -> dict[str, Any] | None:
    name = normalize_name(str(raw.get("name") or ""))
    if not name:
        return None
    unit_text = str(raw.get("unit") or "").strip().lower()
    unit = _UNIT_ALIASES.get(unit_text, Unit.PIECE if unit_text else Unit.TO_TASTE)
    try:
        quantity = Decimal(str(raw.get("quantity"))) * _SCALE.get(unit_text, 1)
    except (InvalidOperation, ValueError):
        quantity = None
    if quantity is not None and (not quantity.is_finite() or quantity <= 0):
        quantity = None
    if unit == Unit.TO_TASTE:
        quantity = None
    category = raw.get("category")
    return {
        "name": name,
        # Fixed-point text: Decimal("50").normalize() would print as "5E+1".
        "quantity": None if quantity is None else format(quantity.normalize(), "f"),
        "unit": unit.value,
        "note": str(raw.get("note") or "").strip(),
        "optional": bool(raw.get("optional")),
        "category": category if category in IngredientCategory.values else "other",
        "season_months": _months(raw.get("season_months")),
    }


def normalize_draft(raw: dict[str, Any]) -> dict[str, Any]:
    """Coerce whatever the model produced into a valid draft."""
    course = raw.get("course")
    steps = raw.get("steps") or []
    if isinstance(steps, str):
        steps = [s for s in re.split(r"\n+", steps)]
    return {
        "title": str(raw.get("title") or "").strip()[:200],
        "description": str(raw.get("description") or "").strip(),
        "course": course if course in Course.values else Course.SINGLE.value,
        "cuisine": str(raw.get("cuisine") or "").strip()[:80],
        "servings": _int(raw.get("servings"), 1) or 2,
        "prep_minutes": _int(raw.get("prep_minutes")),
        "cook_minutes": _int(raw.get("cook_minutes")),
        "ingredients": [
            line
            for line in (_line(i) for i in raw.get("ingredients") or [] if isinstance(i, dict))
            if line
        ],
        "steps": [str(s).strip() for s in steps if str(s).strip()],
        "climate_months": _months(raw.get("climate_months")),
        "source_url": _url(raw.get("source_url")),
    }


def _url(value) -> str:
    text = str(value or "").strip()
    return text[:500] if re.match(r"https?://", text, re.IGNORECASE) else ""
