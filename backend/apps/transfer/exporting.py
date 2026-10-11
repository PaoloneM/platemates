"""Export: recipes, ingredients, a whole team or the system data, as one portable JSON document.

The document never carries database ids, which differ between installations. Objects are named
by their stable `uid` and, for what is matched by name on import (ingredients, kitchen tools,
cuisines), by name too. A reference to a recipe or ingredient outside the document (a community
recipe in a team's book) carries enough to recognise it on the other side.

Never exported: users, accounts and invitations (identities live in Keycloak and differ between
installations), embeddings (recomputed), assistant conversations, menu generation logs.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from apps.catalog.models import Ingredient, KitchenTool
from apps.menus.models import SystemRule
from apps.recipes.models import Cuisine, Recipe
from apps.teams.models import Team

FORMAT = "platemates-export"
VERSION = 1
SCOPES = ("recipes", "ingredients", "team", "system")


# -- references ---------------------------------------------------------------------------------


def team_ref(team: Team | None) -> dict[str, Any] | None:
    if team is None:
        return None
    return {"uid": str(team.uid), "name": team.name, "system": team.is_system}


def ingredient_ref(ingredient: Ingredient) -> dict[str, Any]:
    return {
        "uid": str(ingredient.uid),
        "name": ingredient.name,
        "team": str(ingredient.owner_team.uid) if ingredient.owner_team_id else None,
    }


def tool_ref(tool: KitchenTool) -> dict[str, Any]:
    return {"code": tool.code, "name": tool.name}


def recipe_ref(recipe: Recipe | None) -> dict[str, Any] | None:
    if recipe is None:
        return None
    return {"uid": str(recipe.uid), "title": recipe.title, "team": team_ref(recipe.owner_team)}


# -- objects ------------------------------------------------------------------------------------


def ingredient_data(ingredient: Ingredient) -> dict[str, Any]:
    return {
        **ingredient_ref(ingredient),
        "aliases": ingredient.aliases,
        "category": ingredient.category,
        "default_unit": ingredient.default_unit,
        "season_months": ingredient.season_months,
        "basic": ingredient.basic,
        "provenance": ingredient.provenance,
    }


def tool_data(tool: KitchenTool) -> dict[str, Any]:
    return {**tool_ref(tool), "heats_kitchen": tool.heats_kitchen}


def recipe_data(recipe: Recipe) -> dict[str, Any]:
    return {
        **recipe_ref(recipe),
        "description": recipe.description,
        "steps": recipe.steps,
        "visibility": recipe.visibility,
        "course": recipe.course,
        "cuisine": recipe.cuisine.name if recipe.cuisine_id else None,
        "servings": recipe.servings,
        "prep_minutes": recipe.prep_minutes,
        "cook_minutes": recipe.cook_minutes,
        "tools": [tool_ref(t) for t in recipe.tools.all()],
        "season_months": recipe.season_months,
        "climate_months": recipe.climate_months,
        "source_url": recipe.source_url,
        "derived_from": recipe_ref(recipe.derived_from),
        "web_rating": str(recipe.web_rating) if recipe.web_rating is not None else None,
        "web_rating_count": recipe.web_rating_count,
        "provenance": recipe.provenance,
        "ingredients": [
            {
                "ingredient": ingredient_ref(line.ingredient),
                "quantity": str(line.quantity) if line.quantity is not None else None,
                "unit": line.unit,
                "optional": line.optional,
                "note": line.note,
                "position": line.position,
            }
            for line in recipe.ingredients.select_related("ingredient__owner_team")
        ],
    }


def system_rule_data(rule: SystemRule) -> dict[str, Any]:
    return {
        "uid": str(rule.uid),
        "code": rule.code,
        "text_it": rule.text_it,
        "text_en": rule.text_en,
        "position": rule.position,
        "active": rule.active,
    }


def team_data(team: Team) -> dict[str, Any]:
    menus = []
    for menu in team.menus.prefetch_related("excluded_rules", "slots__slot_dishes__recipe"):
        menus.append(
            {
                "week_start": menu.week_start.isoformat(),
                "status": menu.status,
                "rationale": menu.rationale,
                "instructions": menu.instructions,
                "use_team_rules": menu.use_team_rules,
                "excluded_rules": [str(r.uid) for r in menu.excluded_rules.all()],
                "slots": [
                    {
                        "date": slot.date.isoformat(),
                        "meal": slot.meal,
                        "people": slot.people,
                        "proposed_people": slot.proposed_people,
                        "people_note": slot.people_note,
                        "outcome": slot.outcome,
                        "eaten_instead": [recipe_ref(r) for r in slot.eaten_instead.all()],
                        "eaten_instead_note": slot.eaten_instead_note,
                        "rating": slot.rating,
                        "comment": slot.comment,
                        "dishes": [
                            {
                                "recipe": recipe_ref(dish.recipe),
                                "title": dish.title,
                                "course": dish.course,
                                "note": dish.note,
                                "proposed": dish.proposed,
                                "position": dish.position,
                            }
                            for dish in slot.slot_dishes.all()
                        ],
                    }
                    for slot in menu.slots.all()
                ],
            }
        )
    return {
        **team_ref(team),
        "typical_week": team.typical_week,
        "max_weekday_minutes": team.max_weekday_minutes,
        "notes": team.notes,
        "sign_shared_recipes": team.sign_shared_recipes,
        "tools": [tool_ref(t) for t in team.tools.all()],
        "members": [
            {"uid": str(m.uid), "name": m.name, "birth_year": m.birth_year}
            for m in team.members.all()
        ],
        "preferences": [
            {
                "member": str(p.member.uid) if p.member_id else None,
                "kind": p.kind,
                "ingredient": ingredient_ref(p.ingredient) if p.ingredient_id else None,
                "cuisine": p.cuisine.name if p.cuisine_id else None,
                "note": p.note,
            }
            for p in team.preferences.select_related("member", "ingredient", "cuisine")
        ],
        "calendar": [
            {"date": d.date.isoformat(), "people": d.people, "note": d.note}
            for d in team.calendar_days.all()
        ],
        "rules": [{"uid": str(r.uid), "text": r.text} for r in team.rules.all()],
        "book": [
            {
                "recipe": recipe_ref(e.recipe),
                "status": e.status,
                "rating": e.rating,
                "notes": e.notes,
            }
            for e in team.recipe_book.select_related("recipe__owner_team")
        ],
        "menus": menus,
    }


# -- documents ----------------------------------------------------------------------------------


def _document(
    scope: str,
    *,
    recipes=(),
    ingredients=(),
    teams=(),
    system_rules=(),
    tools=None,
) -> dict[str, Any]:
    recipes = list(recipes)
    ingredients = {i.pk: i for i in ingredients}
    # A recipe's ingredients travel with it, so the other side can create what it lacks.
    for recipe in recipes:
        for line in recipe.ingredients.select_related("ingredient__owner_team"):
            ingredients.setdefault(line.ingredient_id, line.ingredient)
    if tools is None:
        tools = {t.pk: t for r in recipes for t in r.tools.all()}
        for team in teams:
            tools.update({t.pk: t for t in team.tools.all()})
        tools = tools.values()
    cuisines = sorted({r.cuisine.name for r in recipes if r.cuisine_id})
    return {
        "format": FORMAT,
        "version": VERSION,
        "scope": scope,
        "exported_at": timezone.now().isoformat(),
        "kitchen_tools": [tool_data(t) for t in tools],
        "cuisines": cuisines,
        "ingredients": [ingredient_data(i) for i in ingredients.values()],
        "system_rules": [system_rule_data(r) for r in system_rules],
        "teams": [team_data(t) for t in teams],
        "recipes": [recipe_data(r) for r in recipes],
    }


def _recipes(queryset):
    return queryset.select_related("cuisine", "owner_team", "derived_from__owner_team").order_by(
        "pk"
    )


def export_recipes(recipes) -> dict[str, Any]:
    return _document("recipes", recipes=_recipes(Recipe.objects.filter(pk__in=recipes)))


def export_ingredients(ingredients) -> dict[str, Any]:
    return _document(
        "ingredients", ingredients=Ingredient.objects.filter(pk__in=ingredients), tools=[]
    )


def export_team(team: Team) -> dict[str, Any]:
    """The team, its own recipes (versions included) and ingredients. Recipes it only keeps in
    its book (system, community) are referenced, not copied: export the system data too."""
    return _document(
        "team",
        teams=[team],
        recipes=_recipes(Recipe.objects.filter(owner_team=team)),
        ingredients=Ingredient.objects.filter(owner_team=team),
    )


def export_system() -> dict[str, Any]:
    """What every installation shares: system ingredients, kitchen tools, cuisines, system rules
    and the system team's recipes."""
    document = _document(
        "system",
        recipes=_recipes(Recipe.objects.filter(owner_team__is_system=True)),
        ingredients=Ingredient.objects.system(),
        system_rules=SystemRule.objects.order_by("position", "pk"),
        tools=KitchenTool.objects.order_by("pk"),
    )
    document["cuisines"] = sorted(Cuisine.objects.values_list("name", flat=True))
    return document
