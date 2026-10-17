"""Collecting what a request changes, and writing it as audit events.

`AuditMiddleware` opens a collector for every request that may change something (POST, PUT,
PATCH, DELETE). While the view runs, the models in `tracked.py` report their saves and deletes
through Django's signals, and code that writes in bulk (a day's people and dishes, a
recipe's ingredients) reports with `note`. When the response is a success, the collector
becomes one `AuditEvent` per team. Nothing is collected outside requests: the worker's writes
(a generated menu is a proposal) and commands are not the team's changes.

Retention is lazy: after writing events, at most once a minute per process and in a thread,
`purge` deletes the events older than `audit.retention_days` and those beyond the newest
`audit.max_events` (installation-wide). Reads also leave out what is past its age, so an
installation where nobody writes never shows expired events.
"""

from __future__ import annotations

import contextvars
import datetime as dt
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any

from django.db import connection
from django.utils import timezone

from apps.siteconfig import registry

log = logging.getLogger(__name__)

_current: contextvars.ContextVar[Collector | None] = contextvars.ContextVar(
    "audit_collector", default=None
)
WRITES = {"POST", "PUT", "PATCH", "DELETE"}
PURGE_EVERY_SECONDS = 60


@dataclass
class Change:
    team: int
    type: str
    id: str
    label: str
    op: str  # create, update, delete
    before: dict[str, Any] = field(default_factory=dict)
    after: dict[str, Any] = field(default_factory=dict)
    # (type, id) of the object this one belongs to: an item of a list deleted or created in
    # the same request is not worth its own line.
    parent: tuple[str, str] | None = None

    def fields(self) -> dict[str, list[Any]]:
        return {
            name: [self.before.get(name), value]
            for name, value in self.after.items()
            if self.before.get(name) != value
        }


class Collector:
    def __init__(self) -> None:
        self.action = ""
        self.changes: dict[tuple[int, str, str], Change] = {}

    def note(
        self,
        team: int,
        type: str,
        id: Any,
        label: str,
        op: str,
        before: dict[str, Any] | None = None,
        after: dict[str, Any] | None = None,
        parent: tuple[str, str] | None = None,
    ) -> None:
        key = (team, type, str(id))
        known = self.changes.get(key)
        if known is None:
            self.changes[key] = Change(
                team, type, str(id), label, op, dict(before or {}), dict(after or {}), parent
            )
            return
        known.label = label or known.label
        if op == "delete":
            if known.op == "create":
                del self.changes[key]  # made and unmade in one go: nothing happened
                return
            known.op = "delete"
        # The first "before" and the last "after" of each field.
        for name, value in (before or {}).items():
            known.before.setdefault(name, value)
        known.after.update(after or {})

    def events(self) -> dict[int, list[dict[str, Any]]]:
        """The changes worth recording, by team."""
        whole = {(c.type, c.id) for c in self.changes.values() if c.op in ("create", "delete")}
        by_team: dict[int, list[dict[str, Any]]] = {}
        for change in self.changes.values():
            if change.parent in whole:
                continue
            entry = {"type": change.type, "id": change.id, "label": change.label, "op": change.op}
            if change.op == "update":
                entry["fields"] = change.fields()
                if not entry["fields"]:
                    continue
            by_team.setdefault(change.team, []).append(entry)
        return by_team


def collecting() -> bool:
    return _current.get() is not None


def note(team: int | None, type: str, id: Any, label: str, op: str, **kwargs) -> None:
    """Report a change made without a save the signals see (bulk writes)."""
    collector = _current.get()
    if collector is not None and team is not None:
        collector.note(team, type, id, label, op, **kwargs)


def _user_name(user) -> str:
    return (user.get_full_name() or user.email or user.get_username())[:150]


def record(collector: Collector, user) -> int:
    """Write the collected changes as events. Returns how many."""
    from .models import AuditEvent

    events = [
        AuditEvent(
            team_id=team,
            user=user,
            user_name=_user_name(user),
            action=collector.action[:80],
            target_type=changes[0]["type"],
            target_label=changes[0]["label"][:200],
            changes=changes,
        )
        for team, changes in collector.events().items()
    ]
    AuditEvent.objects.bulk_create(events)
    return len(events)


# -- retention ----------------------------------------------------------------------------------


def oldest_kept() -> dt.datetime:
    return timezone.now() - dt.timedelta(days=registry.get("audit.retention_days"))


def purge() -> int:
    """Delete the events past their age and beyond the newest `audit.max_events`. Two range
    deletes: on `created_at` (indexed), and on the primary key below the newest events, found
    by reading that many entries of its index backwards. Returns how many were deleted."""
    from .models import AuditEvent

    deleted, _ = AuditEvent.objects.filter(created_at__lt=oldest_kept()).delete()
    keep = registry.get("audit.max_events")
    threshold = (
        AuditEvent.objects.order_by("-id").values_list("id", flat=True)[keep : keep + 1].first()
    )
    if threshold is not None:
        more, _ = AuditEvent.objects.filter(id__lte=threshold).delete()
        deleted += more
    return deleted


_last_purge = 0.0
_purge_lock = threading.Lock()


def _purge_in_thread() -> None:
    try:
        purge()
    except Exception:  # never let housekeeping break anything
        log.exception("audit purge failed")
    finally:
        connection.close()


def spawn(function) -> None:
    threading.Thread(target=function, daemon=True).start()


def maybe_purge() -> None:
    """Purge in the background, at most once a minute per process."""
    global _last_purge
    with _purge_lock:
        now = time.monotonic()
        if now - _last_purge < PURGE_EVERY_SECONDS:
            return
        _last_purge = now
    spawn(_purge_in_thread)


# -- the request --------------------------------------------------------------------------------


def _action(view_func, method: str) -> str:
    cls = getattr(view_func, "cls", None)
    actions = getattr(view_func, "actions", None)
    basename = getattr(view_func, "initkwargs", {}).get("basename")
    if cls is not None and actions and basename:
        return f"{basename}.{actions.get(method.lower(), method.lower())}"
    name = cls.__name__ if cls is not None else getattr(view_func, "__name__", "view")
    return f"{name}.{method.lower()}"


class AuditMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.method not in WRITES:
            return self.get_response(request)
        collector = Collector()
        token = _current.set(collector)
        try:
            response = self.get_response(request)
        finally:
            _current.reset(token)
        user = getattr(request, "user", None)
        if (
            collector.changes
            and 200 <= response.status_code < 400
            and user is not None
            and user.is_authenticated
        ):
            try:
                if record(collector, user):
                    maybe_purge()
            except Exception:  # the change is made; failing to log it must not hide that
                log.exception("audit events not recorded")
        return response

    def process_view(self, request, view_func, view_args, view_kwargs):
        collector = _current.get()
        if collector is not None:
            collector.action = _action(view_func, request.method)
