"""Recipe embeddings: one vector per recipe and embedding model, kept in step with the recipe.

A recipe is embedded from a short "identity card" of the dish: title, course, cuisine, main
ingredients and the start of the description. Basic ingredients (salt, water, oil) and the
method are left out: they are alike in every recipe, and made every recipe look similar to every
request (2026-10-11, text-embedding-3-small: unrelated recipes scored 0.43-0.48).

The document's hash is stored with the vector, so a recipe is re-embedded only when what it
says changed, and `embed_recipes` can bring everything up to date at any time.
Embedding is best effort: when the embedding service is down, saving a recipe still works and
the vector is filled in later.
"""

from __future__ import annotations

import hashlib
import logging

from pgvector.django import CosineDistance

from ai import AIError, EmbeddingProvider, get_embedding_provider
from apps.usage.context import attribute
from apps.usage.models import Feature

from .models import Recipe, RecipeEmbedding

log = logging.getLogger(__name__)

DESCRIPTION_CHARS = 300


def main_ingredients(recipe: Recipe) -> list[str]:
    """The ingredients that make the dish: not optional, not basic."""
    return [
        line.ingredient.name
        for line in recipe.ingredients.select_related("ingredient")
        if not line.optional and not line.ingredient.basic
    ]


def recipe_document(recipe: Recipe) -> str:
    """What the vector stands for. Changing this re-embeds every recipe on the next refresh
    (`embed_recipes`)."""
    lines = [recipe.title, f"Course: {recipe.get_course_display()}"]
    if recipe.cuisine:
        lines.append(f"Cuisine: {recipe.cuisine.name}")
    if names := main_ingredients(recipe):
        lines.append("Main ingredients: " + ", ".join(names))
    if recipe.description:
        lines.append(recipe.description[:DESCRIPTION_CHARS])
    return "\n".join(lines)


def _hash(document: str, model: str) -> str:
    return hashlib.sha256(f"{model}\n{document}".encode()).hexdigest()


def refresh_embedding(recipe: Recipe, provider: EmbeddingProvider | None = None) -> bool:
    """Embed the recipe if its document changed. Returns whether a vector is now up to date."""
    try:
        provider = provider or get_embedding_provider()
        document = recipe_document(recipe)
        content_hash = _hash(document, provider.model)
        current = RecipeEmbedding.objects.filter(recipe=recipe, model=provider.model).first()
        if current and current.content_hash == content_hash:
            return True
        # Billed to the recipe's team, whatever started it (a save, an import, embed_recipes).
        with attribute(team=recipe.owner_team_id, feature=Feature.EMBEDDINGS):
            [vector] = provider.embed([document])
    except AIError as exc:
        log.info("recipe %s not embedded now: %s", recipe.pk, exc)
        return False
    RecipeEmbedding.objects.update_or_create(
        recipe=recipe,
        model=provider.model,
        defaults={"vector": vector, "content_hash": content_hash},
    )
    return True


def refresh_all(provider: EmbeddingProvider | None = None) -> tuple[int, int]:
    """Bring every recipe's vector up to date. Returns (up to date, failed)."""
    provider = provider or get_embedding_provider()
    ok = failed = 0
    for recipe in Recipe.objects.select_related("cuisine"):
        if refresh_embedding(recipe, provider):
            ok += 1
        else:
            failed += 1
    return ok, failed


def similar_recipes(
    user, queries: list[str], limit: int = 8, provider: EmbeddingProvider | None = None
) -> list[tuple[Recipe, float]]:
    """Recipes the user can see, most similar first, each with its best cosine similarity to
    any of `queries` (a request and the dishes it suggests). No threshold: deciding what is
    similar enough is the search's job (`apps.assistant.search`), relative to the best."""
    provider = provider or get_embedding_provider()
    visible = RecipeEmbedding.objects.filter(
        model=provider.model, recipe__in=Recipe.objects.visible_to(user)
    ).select_related("recipe__cuisine")
    best: dict[int, tuple[Recipe, float]] = {}
    for vector in provider.embed(queries):
        rows = visible.annotate(distance=CosineDistance("vector", vector)).order_by("distance")
        for row in rows[:limit]:
            similarity = 1 - row.distance
            if row.recipe_id not in best or similarity > best[row.recipe_id][1]:
                best[row.recipe_id] = (row.recipe, similarity)
    return sorted(best.values(), key=lambda pair: -pair[1])[:limit]
