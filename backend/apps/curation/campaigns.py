"""Campaigns: many system recipes at once, planned and drafted in the background.

A campaign's targets are themes, each with how many recipes it should bring. The worker plans
dishes for them a few at a time (MAX_BATCH), only when no draft is waiting, so each round of
planning knows every dish drafted so far and never asks for one twice. A draft that fails is
replaced by another dish at the next round; a target stops after twice its count of attempts,
or when the model finds no new dish for it. The campaign is done when no target needs anything
and none of its drafts is still queued or running.
"""

from __future__ import annotations

import logging

from django.db import transaction
from django.db.models import Count, Q

from ai import AIError, ChatProvider

from .drafting import MAX_BATCH, dishes_for_theme
from .jobs import announce, cooling_down, notify_worker
from .models import Campaign, SystemDraft

log = logging.getLogger(__name__)

# Answers without a new dish after which a target stops.
EMPTY_ROUNDS = 3
# Drafts that no longer count towards a target: they will be replaced.
LOST = (SystemDraft.Status.FAILED, SystemDraft.Status.DISCARDED)


def needs(campaign: Campaign) -> dict[str, int]:
    """How many more dishes each target needs planned, by key (targets that need none left
    out)."""
    rows = campaign.drafts.values("target").annotate(
        planned=Count("pk"), lost=Count("pk", filter=Q(status__in=LOST))
    )
    counts = {row["target"]: row for row in rows}
    missing = {}
    for target in campaign.targets:
        key, wanted = target["key"], int(target["count"])
        row = counts.get(key, {"planned": 0, "lost": 0})
        alive = row["planned"] - row["lost"]
        attempts_left = 2 * wanted - row["planned"]
        if campaign.notes.get(key) == "exhausted":
            continue
        if (need := min(wanted - alive, attempts_left)) > 0:
            missing[key] = need
    return missing


def _waiting(campaign: Campaign) -> bool:
    return campaign.drafts.filter(
        status__in=(SystemDraft.Status.QUEUED, SystemDraft.Status.RUNNING)
    ).exists()


def next_to_plan() -> Campaign | None:
    """The oldest running campaign that needs dishes planned; campaigns with nothing left to
    plan or draft are marked done on the way."""
    if cooling_down():
        # Its drafts wait for the search engine: planning more would only lengthen the queue.
        return None
    for campaign in Campaign.objects.filter(status=Campaign.Status.RUNNING).order_by("created_at"):
        if needs(campaign):
            return campaign
        if not _waiting(campaign):
            campaign.status = Campaign.Status.DONE
            campaign.save(update_fields=["status"])
    return None


def _theme(campaign: Campaign, target: dict) -> str:
    return f"{target['theme']}. {campaign.brief}" if campaign.brief else target["theme"]


def plan(campaign: Campaign, chat: ChatProvider) -> int:
    """Queue dishes for the first target that needs some; how many were queued."""
    missing = needs(campaign)
    if not missing:
        return 0
    key, need = next(iter(missing.items()))
    target = next(t for t in campaign.targets if t["key"] == key)
    planned = list(SystemDraft.objects.values_list("dish", flat=True))
    planned += [
        d["title"]
        for d in SystemDraft.objects.exclude(draft=None).values_list("draft", flat=True)
        if d and d.get("title")
    ]
    try:
        # Warmer after an answer without a new dish, for the model to look further afield.
        empty = int(campaign.notes.get(f"{key}:empty", 0))
        dishes = dishes_for_theme(
            _theme(campaign, target),
            min(need, MAX_BATCH),
            campaign.language,
            chat,
            planned,
            temperature=min(0.5 + 0.25 * empty, 1.0),
        )
    except (AIError, ValueError) as exc:
        log.warning("planning campaign %s failed: %s", campaign.pk, exc)
        return 0
    if not dishes:
        # The model sometimes answers with dishes already done: a target stops only after
        # EMPTY_ROUNDS such answers in a row.
        empty = int(campaign.notes.get(f"{key}:empty", 0)) + 1
        notes = {**campaign.notes, f"{key}:empty": empty}
        if empty >= EMPTY_ROUNDS:
            notes[key] = "exhausted"
        campaign.notes = notes
        campaign.save(update_fields=["notes"])
        return 0
    if campaign.notes.get(f"{key}:empty"):
        campaign.notes = {k: v for k, v in campaign.notes.items() if k != f"{key}:empty"}
        campaign.save(update_fields=["notes"])
    with transaction.atomic():
        drafts = SystemDraft.objects.bulk_create(
            SystemDraft(
                dish=dish,
                language=campaign.language,
                requested_by=campaign.created_by,
                campaign=campaign,
                target=key,
            )
            for dish in dishes
        )
        notify_worker()
        transaction.on_commit(lambda: [announce(d, "queued") for d in drafts])
    return len(drafts)
