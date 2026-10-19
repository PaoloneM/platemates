"""Running system recipe drafts in the background, in the worker (`manage.py worker`), with
their phases announced to staff in real time (searching, reading the pages, drafting)."""

from __future__ import annotations

import logging
import time
from typing import Any

from django.core.cache import cache
from django.db import connection, transaction
from django.utils import timezone

from ai import AIError, ChatProvider, get_chat_provider, get_web_search_provider
from apps.catalog.models import Ingredient
from apps.realtime.events import STAFF_ROOM, publish_to
from apps.siteconfig import registry
from apps.siteconfig.registry import prompt_budget_chars

from .drafting import (
    agreement_of,
    draft_recipe,
    reliability_of,
    search_sources,
    verify_source,
    web_rating,
)
from .ingredients import propose_for
from .models import Campaign, CandidateLink, IngredientProposal, SourceSite, SystemDraft
from .publishing import auto_publish

log = logging.getLogger(__name__)

# PostgreSQL channel on which a queued draft wakes the worker up.
CHANNEL = "system_drafts"


# Searches a campaign's draft gets before it fails for want of a source.
MAX_SEARCH_ATTEMPTS = 3
# Shared by the worker's processes, in the cache: when the last search started, and until when
# searches for campaigns are paused.
LAST_SEARCH_KEY = "curation:last_search"
COOLDOWN_KEY = "curation:search_cooldown"


class DraftInterrupted(Exception):
    """The worker is stopping: the draft is abandoned."""


class NoSource(Exception):
    """A campaign's draft found no recipe page: tried again later, never written from memory."""


def cooling_down() -> bool:
    """Whether campaigns' searches are paused (the search engine stopped answering)."""
    return (cache.get(COOLDOWN_KEY) or 0) > time.time()


def start_cooldown() -> None:
    minutes = registry.get("curation.search_cooldown_minutes")
    cache.set(COOLDOWN_KEY, time.time() + minutes * 60, minutes * 60)
    log.warning("web search found nothing: campaigns' searches paused for %s min", minutes)


def wait_to_search(should_stop) -> None:
    """Leave `curation.search_interval_seconds` between two searches: asked too often, the
    search engine stops answering."""
    interval = registry.get("curation.search_interval_seconds")
    while (left := (cache.get(LAST_SEARCH_KEY) or 0) + interval - time.time()) > 0:
        if should_stop():
            raise DraftInterrupted
        time.sleep(min(1.0, left))
    cache.set(LAST_SEARCH_KEY, time.time(), max(interval, 1) * 2)


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
    """Research and draft one recipe: ready for review (published at once if it meets the bar,
    `publishing`), or failed."""

    def checkpoint(phase: str, **extra: Any) -> None:
        if should_stop():
            raise DraftInterrupted
        announce(draft, phase, **extra)

    try:
        checkpoint("searching")
        if search_chat is None:
            search_chat = get_web_search_provider()
        if search_chat is not None and draft.campaign_id is not None:
            wait_to_search(should_stop)
        sources, links = search_sources(
            draft.dish, search_chat, verify, list(SourceSite.objects.all())
        )
        draft.links.all().delete()
        CandidateLink.objects.bulk_create(CandidateLink(draft=draft, **link) for link in links)
        if draft.campaign_id is not None and search_chat is not None and not sources:
            raise NoSource
        checkpoint("drafting", sources=len(sources))
        chat = chat or get_chat_provider()
        recipe = draft_recipe(
            draft.dish, sources, draft.language, chat, prompt_budget_chars(), vocabulary()
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
    except NoSource:
        # Most often the search engine has stopped answering: pause the searches, try later.
        start_cooldown()
        draft.search_attempts += 1
        if draft.search_attempts < MAX_SEARCH_ATTEMPTS:
            draft.status = SystemDraft.Status.QUEUED
            draft.error = "No recipe page found yet: tried again later."
        else:
            draft.status = SystemDraft.Status.FAILED
            draft.error = "No recipe page found for this dish."
    except (AIError, ValueError) as exc:
        log.warning("system draft %s failed: %s", draft.pk, exc)
        draft.status = SystemDraft.Status.FAILED
        draft.error = str(exc)[:2000]
    except Exception as exc:
        log.exception("system draft %s crashed", draft.pk)
        draft.status = SystemDraft.Status.FAILED
        draft.error = f"Unexpected error: {exc}"[:2000]
    draft.finished_at = None if draft.status == SystemDraft.Status.QUEUED else timezone.now()
    draft.save()
    if draft.status == SystemDraft.Status.READY:
        after_ready(draft, chat)
    announce(draft, draft.status)


def vocabulary() -> list[str]:
    """The ingredient names drafts should use: the system catalog's, and those already
    proposed (so a new ingredient keeps one name across drafts)."""
    names = set(Ingredient.objects.system().values_list("name", flat=True))
    names.update(
        IngredientProposal.objects.exclude(status=IngredientProposal.Status.REJECTED)
        .filter(action=IngredientProposal.Action.NEW)
        .values_list("name", flat=True)
    )
    return sorted(names)


def after_ready(draft: SystemDraft, chat: ChatProvider) -> None:
    """Propose the ingredients the catalog lacks, then publish the draft if it meets the bar.
    Neither may cost the draft itself: it stays ready for staff."""
    try:
        propose_for(draft, chat)
        if auto_publish(draft) is not None:
            draft.refresh_from_db()
    except Exception:
        log.exception("after drafting %s", draft.pk)


def claim_next() -> SystemDraft | None:
    queued = (
        SystemDraft.objects.select_for_update(skip_locked=True, of=("self",))
        .filter(status=SystemDraft.Status.QUEUED)
        .exclude(campaign__status=Campaign.Status.PAUSED)
    )
    if cooling_down():
        queued = queued.filter(campaign__isnull=True)
    with transaction.atomic():
        draft = queued.order_by("created_at").first()
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
