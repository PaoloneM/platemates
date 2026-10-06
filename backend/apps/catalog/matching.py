"""Match ingredient names from a draft (LLM output, a web page) to the shared catalog."""

from __future__ import annotations

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import Q

from .models import Ingredient, normalize_name

# Below this similarity a catalog entry is not even worth suggesting.
MIN_SIMILARITY = 0.3
# From this similarity up, the best candidate is preselected (the user still sees and can change
# it): "pomodori" -> "pomodoro" scores about 0.5.
PRESELECT_SIMILARITY = 0.45


def match_ingredient(name: str) -> dict:
    """`{"match": id | None, "candidates": [{id, name, similarity}]}` for one name."""
    normalized = normalize_name(name)
    exact = Ingredient.objects.filter(
        Q(name=normalized) | Q(aliases__contains=[normalized])
    ).first()
    if exact:
        return {"match": exact.pk, "exact": True, "candidates": [_option(exact, 1.0)]}
    similar = (
        Ingredient.objects.annotate(similarity=TrigramSimilarity("name", normalized))
        .filter(similarity__gte=MIN_SIMILARITY)
        .order_by("-similarity")[:3]
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
        "similarity": round(similarity, 2),
    }
