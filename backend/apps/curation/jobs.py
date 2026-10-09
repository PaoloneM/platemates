"""Running system recipe drafts in the background, in the worker (`manage.py worker`), with
their phases announced to staff in real time (searching, reading the pages, drafting)."""

from __future__ import annotations

import logging
from typing import Any

from django.db import connection, transaction
from django.utils import timezone

from ai import AIError, ChatProvider, get_chat_provider, get_web_search_provider
from apps.realtime.events import STAFF_ROOM, publish_to
from apps.siteconfig.registry import prompt_budget_chars

from .drafting import (
    agreement_of,
    draft_recipe,
    find_sources,
    reliability_of,
    verify_source,
    web_rating,
)
from .models import SystemDraft

log = logging.getLogger(__name__)

# PostgreSQL channel on which a queued draft wakes the worker up.
CHANNEL = "system_drafts"


class DraftInterrupted(Exception):
    """The worker is stopping: the draft is abandoned."""


def notify_worker() -> None:
    """Wake the worker up (at commit, inside a transaction). See `menus.generation`."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_notify(%s, '')", [CHANNEL])


def announce(draft: SystemDraft, phase: str, **extra: Any) -> None:
    publish_to(
        STAFF_ROOM,
        "system_draft",
        {"id": draft.pk, "dish": draft.dish, "status": draft.status, "phase": phase, **extra},
    )


def run_draft(
    draft: SystemDraft,
    chat: ChatProvider | None = None,
    search_chat: ChatProvider | None = None,
    verify=verify_source,
    should_stop=lambda: False,
) -> None:
    """Research and draft one recipe: ready for review, or failed."""

    def checkpoint(phase: str, **extra: Any) -> None:
        if should_stop():
            raise DraftInterrupted
        announce(draft, phase, **extra)

    try:
        checkpoint("searching")
        if search_chat is None:
            search_chat = get_web_search_provider()
        sources = find_sources(draft.dish, search_chat, verify)
        checkpoint("drafting", sources=len(sources))
        recipe = draft_recipe(
            draft.dish, sources, draft.language, chat or get_chat_provider(), prompt_budget_chars()
        )
        if not recipe["title"] or not recipe["ingredients"]:
            raise AIError("The model found no recipe for this dish.")
        agreement = agreement_of(sources)
        rating, votes = web_rating(sources)
        draft.sources = [s.as_dict() for s in sources]
        draft.draft = recipe
        draft.agreement = agreement
        draft.reliability = reliability_of(sources, agreement)
        draft.web_rating, draft.web_rating_count = rating, votes
        draft.status = SystemDraft.Status.READY
    except DraftInterrupted:
        draft.status = SystemDraft.Status.FAILED
        draft.error = "Interrupted: the worker was stopped. Try again."
    except (AIError, ValueError) as exc:
        log.warning("system draft %s failed: %s", draft.pk, exc)
        draft.status = SystemDraft.Status.FAILED
        draft.error = str(exc)[:2000]
    except Exception as exc:
        log.exception("system draft %s crashed", draft.pk)
        draft.status = SystemDraft.Status.FAILED
        draft.error = f"Unexpected error: {exc}"[:2000]
    draft.finished_at = timezone.now()
    draft.save()
    announce(draft, draft.status)


def claim_next() -> SystemDraft | None:
    with transaction.atomic():
        draft = (
            SystemDraft.objects.select_for_update(skip_locked=True)
            .filter(status=SystemDraft.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if draft is None:
            return None
        draft.status = SystemDraft.Status.RUNNING
        draft.started_at = timezone.now()
        draft.save(update_fields=["status", "started_at"])
        return draft


def fail_interrupted() -> int:
    return SystemDraft.objects.filter(status=SystemDraft.Status.RUNNING).update(
        status=SystemDraft.Status.FAILED,
        error="Interrupted: the worker stopped before finishing.",
        finished_at=timezone.now(),
    )
