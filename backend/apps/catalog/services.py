"""Catalog maintenance: keeping recipes consistent when an ingredient changes or is merged."""

from __future__ import annotations

from django.db import transaction

from apps.core.provenance import Source

from .models import Ingredient


def recompute_recipes(ingredient: Ingredient) -> int:
    """Re-derive the season of every recipe using `ingredient` (unless the user set it), and
    refresh their embeddings. Returns how many recipes changed season."""
    from apps.recipes.embeddings import refresh_embedding
    from apps.recipes.models import Recipe

    changed = 0
    recipes = list(Recipe.objects.filter(ingredients__ingredient=ingredient).distinct())
    for recipe in recipes:
        if recipe.propose("season_months", recipe.derive_season_months(), Source.DERIVED):
            recipe.save(update_fields=["season_months", "provenance"])
            changed += 1
    transaction.on_commit(lambda: [refresh_embedding(r) for r in recipes])
    return changed


@transaction.atomic
def merge_ingredients(source: Ingredient, target: Ingredient) -> dict[str, int]:
    """Fold `source` into `target`: recipes and preferences move over, the source's name and
    aliases become aliases of the target, and the source is deleted.

    A recipe that already uses both keeps the target's line; when both are measured in the same
    unit, the quantities are added up.
    """
    from apps.menus.models import ShoppingItem
    from apps.recipes.models import RecipeIngredient
    from apps.teams.models import Preference

    if source.pk == target.pk:
        raise ValueError("An ingredient cannot be merged into itself.")
    moved = combined = 0
    for line in RecipeIngredient.objects.filter(ingredient=source).select_related("recipe"):
        existing = RecipeIngredient.objects.filter(recipe=line.recipe, ingredient=target).first()
        if existing is None:
            line.ingredient = target
            line.save(update_fields=["ingredient"])
            moved += 1
            continue
        if (
            existing.unit == line.unit
            and existing.quantity is not None
            and line.quantity is not None
        ):
            existing.quantity += line.quantity
            existing.save(update_fields=["quantity"])
        line.delete()
        combined += 1
    preferences = Preference.objects.filter(ingredient=source).update(ingredient=target)
    # Shopping lists keep their items' names and amounts; they now point at the target.
    ShoppingItem.objects.filter(ingredient=source).update(ingredient=target)

    target.aliases = [*target.aliases, source.name, *source.aliases]
    target.save()  # normalizes and de-duplicates the aliases
    source.delete()
    recompute_recipes(target)
    return {"moved": moved, "combined": combined, "preferences": preferences}
