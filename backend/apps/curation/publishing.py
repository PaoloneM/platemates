"""Publishing a campaign's drafts without staff, when they meet the bar.

A draft is published automatically when its campaign is set to (`curation.auto_publish`), its
sources are reliable enough (`curation.min_reliability`), the web rates it well on enough votes
(`curation.min_rating`, `curation.min_votes`), every ingredient is in the catalog (known, or a
proposal approved: `ingredients`), and no system recipe has its title yet. Every other draft
waits for staff in Manage > Drafts, as before.

The recipe is the system team's, shared, and everything in it comes from the model: proposed,
never set as a user's decision, so staff's later edits always win. Its season is derived from
the ingredients and its embedding computed as for any saved recipe.
"""

from __future__ import annotations

import logging

from django.db import transaction

from apps.core.provenance import Source
from apps.recipes.models import Cuisine, Recipe, RecipeIngredient, Visibility
from apps.recipes.serializers import RecipeSerializer, announce_recipe
from apps.siteconfig import registry
from apps.teams.models import RecipeBookEntry, Team

from .ingredients import resolve, unresolved
from .models import Reliability, SystemDraft

log = logging.getLogger(__name__)

RELIABILITY_RANK = {Reliability.LOW: 0, Reliability.MEDIUM: 1, Reliability.HIGH: 2}


def blockers(draft: SystemDraft) -> list[str]:
    """Why the draft cannot be published automatically (empty: it can)."""
    reasons = []
    if draft.campaign_id is None:
        reasons.append("not_campaign")
    if draft.status != SystemDraft.Status.READY or not draft.draft:
        reasons.append("not_ready")
        return reasons
    wanted = registry.get("curation.min_reliability")
    if RELIABILITY_RANK.get(draft.reliability, 0) < RELIABILITY_RANK[wanted]:
        reasons.append("reliability")
    if draft.web_rating is None or draft.web_rating * 10 < registry.get("curation.min_rating"):
        reasons.append("rating")
    if (draft.web_rating_count or 0) < registry.get("curation.min_votes"):
        reasons.append("votes")
    if unresolved(draft):
        reasons.append("ingredients")
    if Recipe.objects.filter(
        owner_team__is_system=True, title__iexact=draft.draft["title"]
    ).exists():
        reasons.append("duplicate")
    return reasons


def auto_publish(draft: SystemDraft) -> Recipe | None:
    """Publish the draft if it meets the bar; the recipe, or None."""
    if not registry.get("curation.auto_publish") or blockers(draft):
        return None
    try:
        return publish(draft, automatically=True)
    except Exception:
        log.exception("publishing draft %s failed", draft.pk)
        return None


def _cuisine(name: str) -> Cuisine | None:
    name = " ".join(name.split())
    if not name:
        return None
    existing = Cuisine.objects.filter(name__iexact=name).first()
    return existing or Cuisine.objects.create(name=name[:1].upper() + name[1:])


@transaction.atomic
def publish(draft: SystemDraft, automatically: bool = False) -> Recipe:
    """The draft as a system recipe. Every ingredient must resolve."""
    draft = SystemDraft.objects.select_for_update().get(pk=draft.pk)
    if draft.status != SystemDraft.Status.READY:
        raise ValueError("Only a ready draft is published.")
    data = draft.draft
    lines = [(line, resolve(line["name"])) for line in data["ingredients"]]
    if any(ingredient is None for _line, ingredient in lines):
        raise ValueError("Some ingredients are not in the catalog.")
    system = Team.system()
    recipe = Recipe(
        title=data["title"],
        description=data.get("description") or "",
        steps=data["steps"],
        owner_team=system,
        visibility=Visibility.SHARED,
        servings=data.get("servings") or 2,
        prep_minutes=data.get("prep_minutes"),
        cook_minutes=data.get("cook_minutes"),
        source_url=data.get("source_url") or "",
        web_rating=draft.web_rating,
        web_rating_count=draft.web_rating_count,
    )
    recipe.propose("course", data["course"], Source.LLM)
    recipe.propose("climate_months", data.get("climate_months") or [], Source.LLM)
    if (cuisine := _cuisine(data.get("cuisine") or "")) is not None:
        recipe.propose("cuisine", cuisine, Source.LLM)
    recipe.save()
    RecipeIngredient.objects.bulk_create(
        RecipeIngredient(
            recipe=recipe,
            ingredient=ingredient,
            quantity=line["quantity"],
            unit=line["unit"],
            optional=line["optional"],
            note=line["note"][:200],
            position=position,
        )
        for position, (line, ingredient) in enumerate(lines)
    )
    # Season from the ingredients, and the embedding after commit: as for any saved recipe.
    RecipeSerializer._derive(recipe)
    RecipeBookEntry.objects.get_or_create(
        team=system, recipe=recipe, defaults={"status": RecipeBookEntry.Status.APPROVED}
    )
    draft.status = SystemDraft.Status.PUBLISHED
    draft.recipe = recipe
    draft.published_automatically = automatically
    draft.save(update_fields=["status", "recipe", "published_automatically"])
    transaction.on_commit(lambda: announce_recipe(recipe, "created"))
    return recipe


def publish_waiting(proposal) -> int:
    """After a proposal is approved: publish the drafts that now meet the bar."""
    published = 0
    for draft in proposal.drafts.filter(status=SystemDraft.Status.READY):
        if auto_publish(draft) is not None:
            published += 1
    return published
