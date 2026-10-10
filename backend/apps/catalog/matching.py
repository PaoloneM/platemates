"""Match ingredient names from a draft (LLM output, a web page) to the catalog a team can use:
system ingredients and the team's own, system ones first on equal terms."""

from __future__ import annotations

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import F, FloatField, Q
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce, Greatest

from .models import Ingredient, normalize_name

# Below this similarity a catalog entry is not even worth suggesting.
MIN_SIMILARITY = 0.3
# From this similarity up, the best candidate is preselected (the user still sees and can change
# it): "pomodori" -> "pomodoro" scores about 0.5.
PRESELECT_SIMILARITY = 0.45


def match_ingredient(name: str, team=None) -> dict:
    """`{"match": id | None, "candidates": [{id, name, similarity}]}` for one name, among the
    ingredients `team` can use (system ones only without a team, or for the system team)."""
    normalized = normalize_name(name)
    usable = Ingredient.objects.usable_by(team)
    system_first = F("owner_team").asc(nulls_first=True)
    exact = (
        usable.filter(Q(name=normalized) | Q(aliases__contains=[normalized]))
        .order_by(system_first, "name")
        .first()
    )
    if exact:
        return {"match": exact.pk, "exact": True, "candidates": [_option(exact, 1.0)]}
    # The best of the name's and the aliases' similarity: a variant typed differently from the
    # name can still be close to one of the aliases.
    best_alias = RawSQL(
        "SELECT max(similarity(a, %s)) FROM unnest(catalog_ingredient.aliases) AS a",
        (normalized,),
        output_field=FloatField(),
    )
    similar = (
        usable.annotate(
            similarity=Greatest(TrigramSimilarity("name", normalized), Coalesce(best_alias, 0.0))
        )
        .filter(similarity__gte=MIN_SIMILARITY)
        .order_by("-similarity", system_first, "name")[:3]
    )
    candidates = [_option(i, float(i.similarity)) for i in similar]
    best = candidates[0] if candidates else None
    preselect = best and best["similarity"] >= PRESELECT_SIMILARITY
    return {"match": best["id"] if preselect else None, "exact": False, "candidates": candidates}


def _option(ingredient: Ingredient, similarity: float) -> dict:
    return {
        "id": ingredient.pk,
        "name": ingredient.name,
        "category": ingredient.category,
        "default_unit": ingredient.default_unit,
        "season_months": ingredient.season_months,
        "team": ingredient.owner_team_id,
        "similarity": round(similarity, 2),
    }
