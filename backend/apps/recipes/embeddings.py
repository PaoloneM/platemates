"""Recipe embeddings: one vector per recipe and embedding model, kept in step with the recipe.

A recipe is embedded from a short text document (title, course, cuisine, ingredients, the start
of the method). The document's hash is stored with the vector, so a recipe is re-embedded only
when what it says changed, and `embed_recipes` can bring everything up to date at any time.
Embedding is best effort: when the embedding service is down, saving a recipe still works and
the vector is filled in later.
"""

from __future__ import annotations

import hashlib
import logging

from pgvector.django import CosineDistance

from ai import AIError, EmbeddingProvider, get_embedding_provider

from .models import Recipe, RecipeEmbedding

log = logging.getLogger(__name__)

# Below this cosine similarity a recipe is not offered as a match. Measured with multilingual
# MiniLM on real recipes: good matches 0.45-0.6, loosely related 0.35-0.45, unrelated up to 0.31
# ("un dolce al cioccolato" vs a leek soup). Short keyword queries score low even when right
# ("porri" vs the leek soup: 0.34), which is why search also matches keywords.
MIN_SIMILARITY = 0.4


def recipe_document(recipe: Recipe) -> str:
    """What the vector stands for. Changing this re-embeds every recipe on the next refresh."""
    lines = [recipe.title, f"Course: {recipe.get_course_display()}"]
    if recipe.cuisine:
        lines.append(f"Cuisine: {recipe.cuisine.name}")
    names = [line.ingredient.name for line in recipe.ingredients.select_related("ingredient")]
    if names:
        lines.append("Ingredients: " + ", ".join(names))
    if recipe.description:
        lines.append(recipe.description)
    if recipe.steps:
        lines.append(" ".join(recipe.steps)[:400])
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
    user, query: str, limit: int = 8, provider: EmbeddingProvider | None = None
) -> list[tuple[Recipe, float]]:
    """Recipes the user can see, most similar to `query` first, with their cosine similarity."""
    provider = provider or get_embedding_provider()
    [vector] = provider.embed([query])
    rows = (
        RecipeEmbedding.objects.filter(
            model=provider.model, recipe__in=Recipe.objects.visible_to(user)
        )
        .annotate(distance=CosineDistance("vector", vector))
        .select_related("recipe__cuisine")
        .order_by("distance")[:limit]
    )
    return [(row.recipe, 1 - row.distance) for row in rows if 1 - row.distance >= MIN_SIMILARITY]
