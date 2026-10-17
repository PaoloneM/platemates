"""Which models report their changes to the audit, and how: their team, a readable label, the
fields left out. Saves and deletes reach the collector through Django's signals, only while a
request is collecting (`recorder.collecting`); outside requests nothing is even looked at.

Left out on purpose: shopping item ticks (frequent, and `bought_by` already says who), the
assistant's sessions (one user's drafts), whatever has no team or belongs to the system team
(no owners to read it). Meals, their dishes and a recipe's ingredients are written in bulk:
they report through `recorder.note` where they are written (`teams/calendar.py`,
`menus/review.py`, `recipes/serializers.py`).
"""

from __future__ import annotations

import datetime as dt
import decimal
import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import cache
from typing import Any

from django.apps import apps
from django.db.models.signals import post_delete, post_init, post_save

from .recorder import collecting, note

log = logging.getLogger(__name__)

# Never worth showing: identity, bookkeeping, derived data.
ALWAYS_LEFT_OUT = {"id", "uid", "created_at", "updated_at", "provenance", "position", "token"}


@dataclass(frozen=True)
class Tracked:
    model: str  # "app_label.ModelName"
    type: str  # the name the interface translates
    team: Callable[[Any], int | None] = lambda obj: obj.team_id
    label: Callable[[Any], str] = str
    left_out: frozenset[str] = frozenset()
    parent: Callable[[Any], tuple[str, str] | None] = lambda obj: None
    ops: frozenset[str] = field(default=frozenset({"create", "update", "delete"}))


TRACKED = [
    Tracked("families.Team", "team", team=lambda t: t.pk, label=lambda t: t.name),
    Tracked(
        "families.Membership",
        "membership",
        label=lambda m: m.user.get_full_name() or m.user.email,
    ),
    Tracked("families.Member", "member", label=lambda m: m.name or str(m.birth_year or "")),
    Tracked("families.Preference", "preference"),
    Tracked("families.RecipeBookEntry", "book_entry", label=lambda e: e.recipe.title),
    Tracked("menus.TeamRule", "team_rule", label=lambda r: r.text[:120]),
    # A week's settings; the week itself appears as a side effect of planning a day.
    Tracked(
        "menus.WeeklyMenu",
        "week",
        label=lambda m: m.week_start.isoformat(),
        ops=frozenset({"update"}),
    ),
    Tracked(
        "menus.MenuGeneration",
        "generation",
        team=lambda g: g.menu.team_id,
        label=lambda g: g.menu.week_start.isoformat(),
        ops=frozenset({"create"}),
    ),
    Tracked("menus.ShoppingList", "shopping_list", label=lambda s: s.title),
    Tracked(
        "menus.ShoppingItem",
        "shopping_item",
        team=lambda i: i.shopping_list.team_id,
        label=lambda i: i.name,
        left_out=frozenset({"bought", "bought_at", "bought_by"}),
        parent=lambda i: ("shopping_list", str(i.shopping_list_id)),
    ),
    Tracked(
        "recipes.Recipe",
        "recipe",
        team=lambda r: r.owner_team_id,
        label=lambda r: r.title,
        left_out=frozenset({"web_rating", "web_rating_count"}),
    ),
    Tracked(
        "catalog.Ingredient", "ingredient", team=lambda i: i.owner_team_id, label=lambda i: i.name
    ),
    Tracked(
        "accounts.Invitation",
        "invitation",
        label=lambda i: i.note or i.role,
        left_out=frozenset({"expires_at"}),
    ),
]


@cache
def _system_team() -> int | None:
    from apps.teams.models import Team

    return Team.objects.filter(is_system=True).values_list("pk", flat=True).first()


def team_of(tracked: Tracked, obj) -> int | None:
    team = tracked.team(obj)
    return None if team is None or team == _system_team() else team


def json_value(value: Any) -> Any:
    if isinstance(value, dt.datetime | dt.date | dt.time):
        return value.isoformat()
    if isinstance(value, decimal.Decimal | uuid.UUID):
        return str(value)
    return value


def _fields(model, tracked: Tracked):
    return [
        f
        for f in model._meta.concrete_fields
        if not f.primary_key and f.name not in ALWAYS_LEFT_OUT | tracked.left_out
    ]


def _values(obj, fields) -> dict[str, Any]:
    return {f.name: json_value(getattr(obj, f.attname)) for f in fields}


def _readable(field_, value):
    """A foreign key as its object's name rather than its id."""
    if value is None or not field_.is_relation:
        return value
    related = field_.related_model._default_manager.filter(pk=value).first()
    return str(related) if related is not None else value


def _safe(handler):
    """A failure to log a change must never fail the change itself."""

    def run(*args, **kwargs):
        try:
            handler(*args, **kwargs)
        except Exception:
            log.exception("audit: change not collected")

    return run


def connect() -> None:
    for tracked in TRACKED:
        model = apps.get_model(tracked.model)
        fields = _fields(model, tracked)
        by_name = {f.name: f for f in fields}

        def initial(sender, instance, tracked=tracked, fields=fields, **kwargs):
            if collecting() and "update" in tracked.ops:
                instance._audit_initial = _values(instance, fields)

        def saved(sender, instance, created, tracked=tracked, fields=fields, by_name=by_name, **kw):
            if not collecting() or kw.get("raw"):
                return
            team = team_of(tracked, instance)
            if team is None:
                return
            if created:
                if "create" in tracked.ops:
                    note(
                        team,
                        tracked.type,
                        instance.pk,
                        tracked.label(instance),
                        "create",
                        parent=tracked.parent(instance),
                    )
                return
            if "update" not in tracked.ops:
                return
            before = getattr(instance, "_audit_initial", None)
            after = _values(instance, fields)
            if before is None:
                return  # not loaded while collecting: nothing to compare with
            changed = [name for name, value in after.items() if before.get(name) != value]
            if not changed:
                return
            note(
                team,
                tracked.type,
                instance.pk,
                tracked.label(instance),
                "update",
                before={n: _readable(by_name[n], before.get(n)) for n in changed},
                after={n: _readable(by_name[n], after[n]) for n in changed},
                parent=tracked.parent(instance),
            )
            instance._audit_initial = after

        def deleted(sender, instance, tracked=tracked, **kwargs):
            if not collecting() or "delete" not in tracked.ops:
                return
            try:
                team = team_of(tracked, instance)
                label = tracked.label(instance)
                parent = tracked.parent(instance)
            except Exception:  # the parent went first (cascade): its own line says it
                return
            if team is not None:
                note(team, tracked.type, instance.pk, label, "delete", parent=parent)

        uid = f"audit-{tracked.model}"
        post_init.connect(_safe(initial), sender=model, weak=False, dispatch_uid=f"{uid}-init")
        post_save.connect(_safe(saved), sender=model, weak=False, dispatch_uid=f"{uid}-save")
        post_delete.connect(_safe(deleted), sender=model, weak=False, dispatch_uid=f"{uid}-delete")
