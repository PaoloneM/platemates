"""Generating a week's menu: the context, one call to the LLM, and the proposal it becomes.

The code decides what can be proposed and the LLM chooses among it (RAG: retrieval first, then
generation). Retrieval is structured for now: the team's recipe book and recipes, plus a few
shared recipes to discover, filtered by kitchen tools and "never propose" preferences, sorted by
season, rating and how long ago they were eaten. Vector similarity (variety, team profiles)
joins when the recipe books grow.

What must hold whatever the model answers is enforced here, not in the prompt: meals that
already have dishes the user chose are left alone, meals with nobody at home get no dishes,
recipes must come from the candidate list, and changes to the people stay proposals until
the user accepts them. Everything the model returns is a proposal (`SlotDish.proposed`,
`MealSlot.proposed_people`) shown for review.

The chat model currently runs with an 8k-token context, so the prompt is kept compact: one
line per meal and per candidate recipe, and a cap on candidates.
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Any

from django.db import transaction
from django.db.models import Max, Q
from django.utils import timezone

from ai import AIError, ChatProvider, get_chat_provider
from apps.recipes.models import Course, Recipe, Visibility
from apps.teams.models import PLANNED_MEALS, Preference, RecipeBookEntry, Team

from .models import MealSlot, MenuGeneration, SlotDish, SystemRule, WeeklyMenu

log = logging.getLogger(__name__)

LANGUAGE_NAMES = {"it": "Italian", "en": "English"}
# Day and meal names in the language the rules are written in, so that "venerdì sera" in a
# rule matches "venerdì cena" in the list of meals.
DAY_NAMES = {
    "it": ["lunedì", "martedì", "mercoledì", "giovedì", "venerdì", "sabato", "domenica"],
    "en": ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"],
}
MEAL_NAMES = {
    "it": {"lunch": "pranzo", "dinner": "cena"},
    "en": {"lunch": "lunch", "dinner": "dinner"},
}
MAX_BOOK_CANDIDATES = 40
MAX_DISCOVER_CANDIDATES = 8
MAX_DISHES_PER_MEAL = 3
MAX_PEOPLE = 50
RECENT_DAYS = 14
# Enough for 14 meals of two dishes with short notes, and the rationale.
MAX_ANSWER_TOKENS = 3000

SYSTEM_PROMPT = """\
You plan a team's weekly menu: the dishes of each open meal (lunch and dinner).

Follow the rules below. Where two rules conflict, the week's instructions win over the team's \
rules, and the team's rules win over the system rules; say in the rationale how you resolved \
any conflict.

- A dish is either a candidate recipe ("recipe_id": its id, e.g. "R12"; "new_title": null) or \
a new dish ("recipe_id": null; "new_title": its common name, with a one-line note on what it \
is). Use each candidate at most once in the week, side dishes included, unless a rule says \
otherwise; when the candidates are fewer than the meals to plan, plan the other meals with \
new dishes, which also lets the team discover something.
- In the answer, "date" is the meal's date (YYYY-MM-DD) and "meal" is "lunch" or "dinner".
- A meal may have more than one dish (e.g. a first course and a side) to make it complete.
- Plan only the meals marked OPEN. Meals marked FIXED already have their dishes: keep them in \
mind for variety and balance, but do not plan them.
- If the week's instructions change how many people eat at a meal (someone away, guests), put \
the change in "people_changes" with a short reason, and plan that meal for the new number; a \
meal with 0 people gets no dishes.
- Start the answer with "rule_plan": one short line per team rule and per instruction of the \
week, saying on which meals (day and lunch or dinner) you apply it. Then plan the meals \
following it exactly. The rationale must describe the plan you give, never one you did not \
give.
- New dishes follow the season too: use ingredients in season in Italy in the week's month.
- A new dish's name is just its common name, without people or quantities.
- Write new dish names, notes, reasons and the rationale in {language}; call dishes by their \
names, never by their ids. Keep the rationale to two or three sentences.
"""

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        # Written first, before any meal: each rule and instruction with the meals it applies
        # to. Without it the model noticed broken rules only in the rationale, after the plan.
        "rule_plan": {"type": "array", "items": {"type": "string"}},
        "people_changes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "meal": {"type": "string", "enum": list(PLANNED_MEALS)},
                    "people": {"type": "integer"},
                    "reason": {"type": "string"},
                },
                "required": ["date", "meal", "people", "reason"],
            },
        },
        "meals": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "date": {"type": "string"},
                    "meal": {"type": "string", "enum": list(PLANNED_MEALS)},
                    "dishes": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "recipe_id": {"type": ["string", "null"]},
                                "new_title": {"type": ["string", "null"]},
                                "course": {
                                    "type": ["string", "null"],
                                    "enum": [*Course.values, None],
                                },
                                "note": {"type": "string"},
                            },
                            "required": ["recipe_id", "new_title", "course", "note"],
                        },
                    },
                },
                "required": ["date", "meal", "dishes"],
            },
        },
        "rationale": {"type": "string"},
    },
    "required": ["rule_plan", "people_changes", "meals", "rationale"],
}


class GenerationError(Exception):
    """The model's answer could not be turned into a proposal."""


@dataclass
class SlotPlan:
    slot: MealSlot
    # Dishes the user chose: the slot is fixed and not planned.
    fixed: list[str]

    @property
    def key(self) -> tuple[str, str]:
        return (self.slot.date.isoformat(), self.slot.meal)


@dataclass
class Context:
    menu: WeeklyMenu
    language: str
    rules: dict[str, Any]
    slots: dict[tuple[str, str], SlotPlan]
    candidates: dict[str, Recipe]
    messages: list[dict[str, Any]] = field(default_factory=list)


# -- rules -------------------------------------------------------------------------------------


def rules_for(menu: WeeklyMenu, use_week_settings: bool, language: str) -> dict[str, Any]:
    """The rules a generation follows, as text: system, team, and the week's instructions."""
    text = "text_it" if language == "it" else "text_en"
    system = [getattr(rule, text) for rule in SystemRule.objects.filter(active=True)]
    team_rules = menu.team.rules.all()
    if use_week_settings:
        if not menu.use_team_rules:
            team_rules = team_rules.none()
        else:
            team_rules = team_rules.exclude(pk__in=menu.excluded_rules.all())
    return {
        "system": system,
        "team": [rule.text for rule in team_rules],
        "week": menu.instructions if use_week_settings else "",
    }


# -- candidates --------------------------------------------------------------------------------


def _avoided(team: Team) -> Q:
    """Recipes the team must never be offered: "never propose" ingredients and cuisines."""
    avoids = Preference.objects.filter(team=team, kind=Preference.Kind.AVOIDS)
    ingredients = [p.ingredient_id for p in avoids if p.ingredient_id]
    cuisines = [p.cuisine_id for p in avoids if p.cuisine_id]
    return Q(ingredients__ingredient__in=ingredients) | Q(cuisine__in=cuisines)


def candidate_recipes(team: Team, week_start: dt.date) -> list[tuple[Recipe, dict[str, Any]]]:
    """The recipes the model may choose from, each with what the prompt says about it."""
    team_tools = set(team.tools.values_list("pk", flat=True))
    months = {(week_start + dt.timedelta(days=n)).month for n in range(7)}
    ratings = dict(
        RecipeBookEntry.objects.filter(team=team, rating__isnull=False).values_list(
            "recipe_id", "rating"
        )
    )
    last_eaten = dict(
        SlotDish.objects.filter(
            slot__menu__team=team, slot__date__lt=week_start, recipe__isnull=False, proposed=False
        )
        .values("recipe_id")
        .annotate(last=Max("slot__date"))
        .values_list("recipe_id", "last")
    )

    def usable(recipe: Recipe) -> bool:
        # A team that never listed its tools is not filtered by them.
        needed = {tool.pk for tool in recipe.tools.all()}
        return not team_tools or needed <= team_tools

    def facts(recipe: Recipe, in_book: bool) -> dict[str, Any]:
        suitable = recipe.suitable_months()
        return {
            "in_season": not suitable or bool(months & suitable),
            "in_book": in_book,
            "rating": ratings.get(recipe.pk),
            "last_eaten": last_eaten.get(recipe.pk),
        }

    base = (
        Recipe.objects.exclude(_avoided(team))
        .exclude(book_entries__team=team, book_entries__status=RecipeBookEntry.Status.REJECTED)
        .select_related("cuisine")
        .prefetch_related("tools", "ingredients__ingredient")
        .distinct()
    )
    book = base.filter(
        Q(book_entries__team=team, book_entries__status=RecipeBookEntry.Status.APPROVED)
        | Q(owner_team=team)
    )
    chosen = [(r, facts(r, True)) for r in book if usable(r)]
    # In season first, then the best rated, then the longest since last eaten (never first).
    chosen.sort(
        key=lambda item: (
            not item[1]["in_season"],
            -(item[1]["rating"] or 3),
            item[1]["last_eaten"] or dt.date.min,
        )
    )
    chosen = chosen[:MAX_BOOK_CANDIDATES]
    in_book = {recipe.pk for recipe, _ in chosen}
    shared = base.filter(visibility=Visibility.SHARED).exclude(pk__in=in_book).order_by("?")
    discover = [(r, facts(r, False)) for r in shared[: MAX_DISCOVER_CANDIDATES * 3] if usable(r)]
    discover = [item for item in discover if item[1]["in_season"]][:MAX_DISCOVER_CANDIDATES]
    return chosen + discover


def _recipe_line(ref: str, recipe: Recipe, facts: dict[str, Any]) -> str:
    parts = [f"{ref} {recipe.title}", recipe.course]
    if recipe.cuisine:
        parts.append(recipe.cuisine.name)
    if recipe.total_minutes:
        parts.append(f"{recipe.total_minutes} min")
    parts.append("in season" if facts["in_season"] else "OUT OF SEASON")
    parts.append("recipe book" if facts["in_book"] else "not in the book yet, to discover")
    if facts["rating"]:
        parts.append(f"rated {facts['rating']}/5")
    if facts["last_eaten"]:
        parts.append(f"last eaten {facts['last_eaten'].isoformat()}")
    return " | ".join(parts)


# -- the prompt --------------------------------------------------------------------------------


def _team_lines(team: Team, week_start: dt.date) -> list[str]:
    lines = []
    ages = [week_start.year - m.birth_year for m in team.members.all() if m.birth_year]
    if ages:
        lines.append(f"People at the table, ages: {', '.join(map(str, sorted(ages)))}.")
    if team.max_weekday_minutes:
        lines.append(
            f"On weekdays, at most {team.max_weekday_minutes} minutes of preparation and cooking."
        )
    labels = {
        Preference.Kind.LOVES: "loves",
        Preference.Kind.LIKES: "likes",
        Preference.Kind.DISLIKES: "dislikes",
        Preference.Kind.AVOIDS: "never wants",
    }
    for pref in Preference.objects.filter(team=team).select_related(
        "member", "ingredient", "cuisine"
    ):
        who = pref.member.name if pref.member and pref.member.name else "The team"
        what = pref.ingredient or pref.cuisine or pref.note
        lines.append(f"{who} {labels[pref.kind]}: {what}.")
    return lines


def _slot_line(plan: SlotPlan, language: str) -> str:
    slot = plan.slot
    days = DAY_NAMES.get(language, DAY_NAMES["en"])
    meals = MEAL_NAMES.get(language, MEAL_NAMES["en"])
    when = f"{slot.date.isoformat()} {days[slot.date.weekday()]} {meals[slot.meal]}"
    if plan.fixed:
        return f"{when}: {slot.people} people, FIXED: {' + '.join(plan.fixed)}"
    if slot.people == 0:
        return f"{when}: nobody at home"
    return f"{when}: {slot.people} people, OPEN"


def build_context(generation: MenuGeneration) -> Context:
    menu = generation.menu
    team = menu.team
    language = generation.language
    rules = rules_for(menu, generation.use_week_settings, language)
    slots = {}
    rows = menu.slots.filter(meal__in=PLANNED_MEALS).prefetch_related("slot_dishes__recipe")
    for slot in sorted(rows, key=lambda s: (s.date, PLANNED_MEALS.index(s.meal))):
        fixed = [d.display_title for d in slot.slot_dishes.all() if not d.proposed]
        plan = SlotPlan(slot=slot, fixed=fixed)
        slots[plan.key] = plan
    candidates = {}
    recipe_lines = []
    for index, (recipe, facts) in enumerate(candidate_recipes(team, menu.week_start), start=1):
        ref = f"R{index}"
        candidates[ref] = recipe
        recipe_lines.append(_recipe_line(ref, recipe, facts))

    recent = (
        SlotDish.objects.filter(
            slot__menu__team=team,
            proposed=False,
            slot__date__range=(menu.week_start - dt.timedelta(days=RECENT_DAYS), menu.week_start),
        )
        .exclude(slot__date=menu.week_start)
        .select_related("recipe")
    )
    recent_titles = sorted({dish.display_title for dish in recent})

    def section(title: str, lines: list[str]) -> str:
        return f"## {title}\n" + ("\n".join(f"- {line}" for line in lines) if lines else "(none)")

    week_end = menu.week_start + dt.timedelta(days=6)
    open_count = sum(1 for plan in slots.values() if not plan.fixed and plan.slot.people > 0)
    user = "\n\n".join(
        [
            f"Week from {menu.week_start.isoformat()} to {week_end.isoformat()}: "
            f"{open_count} open meals to plan, {len(candidates)} candidate recipes.",
            section("System rules", rules["system"]),
            section("Team rules", rules["team"]),
            "## This week's instructions\n" + (rules["week"] or "(none)"),
            section("The team", _team_lines(team, menu.week_start)),
            section("Meals", [_slot_line(plan, language) for plan in slots.values()]),
            section("Eaten in the last two weeks", recent_titles),
            section("Candidate recipes", recipe_lines),
        ]
    )
    language_name = LANGUAGE_NAMES.get(language, "English")
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT.format(language=language_name)},
        {"role": "user", "content": user},
    ]
    return Context(
        menu=menu,
        language=language,
        rules=rules,
        slots=slots,
        candidates=candidates,
        messages=messages,
    )


# -- the answer --------------------------------------------------------------------------------


def _text(value: Any, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _named(context: Context, text: str) -> str:
    """Candidate ids ("R4") in free text replaced by the recipes' titles: users never see ids."""

    def title(match: re.Match) -> str:
        recipe = context.candidates.get(match.group(0).upper())
        return f"«{recipe.title}»" if recipe else match.group(0)

    return re.sub(r"\bR\d+\b", title, text)


def validate_answer(context: Context, answer: dict[str, Any]) -> dict[str, Any]:
    """Keep only what may be proposed. Returns the proposal, plus what was dropped and why."""
    if not isinstance(answer, dict):
        raise GenerationError("The answer is not an object.")
    dropped: list[str] = []

    people: dict[tuple[str, str], dict[str, Any]] = {}
    for change in answer.get("people_changes") or []:
        key = (str(change.get("date")), str(change.get("meal")))
        plan = context.slots.get(key)
        count = change.get("people")
        if plan is None or type(count) is not int or not 0 <= count <= MAX_PEOPLE:
            dropped.append(f"people change {key}: not a meal of this week, or not a valid count")
            continue
        if count != plan.slot.people:
            people[key] = {"people": count, "reason": _text(change.get("reason"), 200)}

    meals: dict[tuple[str, str], list[dict[str, Any]]] = {}
    for meal in answer.get("meals") or []:
        key = (str(meal.get("date")), str(meal.get("meal")))
        plan = context.slots.get(key)
        if plan is None:
            dropped.append(f"meal {key}: not a meal of this week")
            continue
        if plan.fixed:
            dropped.append(f"meal {key}: fixed by the team")
            continue
        expected = people.get(key, {}).get("people", plan.slot.people)
        if expected == 0:
            continue
        dishes = []
        for dish in (meal.get("dishes") or [])[:MAX_DISHES_PER_MEAL]:
            note = _named(context, _text(dish.get("note"), 200))[:200]
            ref = str(dish.get("recipe_id") or "").strip().upper()
            title = _text(dish.get("new_title"), 200)
            if ref and (ref in context.candidates or not title):
                recipe = context.candidates.get(ref)
                if recipe is None:
                    dropped.append(f"meal {key}: unknown recipe {ref}")
                    continue
                if recipe.pk in {d.get("recipe") for d in dishes}:
                    continue
                dishes.append({"recipe": recipe.pk, "title": recipe.title, "note": note})
                continue
            if not title:
                continue
            course = dish.get("course") if dish.get("course") in Course.values else ""
            if title.casefold() in {d["title"].casefold() for d in dishes}:
                continue
            dishes.append({"recipe": None, "title": title, "course": course, "note": note})
        if dishes:
            meals[key] = dishes

    open_meals = [
        key
        for key, plan in context.slots.items()
        if not plan.fixed and people.get(key, {}).get("people", plan.slot.people) > 0
    ]
    if open_meals and not meals:
        raise GenerationError("The answer planned none of the open meals.")
    unplanned = [key for key in open_meals if key not in meals]
    return {
        "rule_plan": [_text(line, 300) for line in (answer.get("rule_plan") or [])][:20],
        "people": [{"date": d, "meal": m, **v} for (d, m), v in people.items()],
        "meals": [{"date": d, "meal": m, "dishes": v} for (d, m), v in meals.items()],
        "rationale": _named(context, _text(answer.get("rationale"), 1500)),
        "unplanned": [{"date": d, "meal": m} for d, m in unplanned],
        "dropped": dropped,
    }


@transaction.atomic
def apply_proposal(context: Context, proposal: dict[str, Any]) -> None:
    """Replace the week's previous proposals with this one. User decisions stay untouched."""
    menu = context.menu
    SlotDish.objects.filter(slot__menu=menu, proposed=True).delete()
    menu.slots.update(proposed_people=None, people_note="")
    for change in proposal["people"]:
        plan = context.slots[(change["date"], change["meal"])]
        plan.slot.proposed_people = change["people"]
        plan.slot.people_note = change["reason"]
        plan.slot.save(update_fields=["proposed_people", "people_note"])
    for meal in proposal["meals"]:
        slot = context.slots[(meal["date"], meal["meal"])].slot
        SlotDish.objects.bulk_create(
            SlotDish(
                slot=slot,
                recipe_id=dish["recipe"],
                title="" if dish["recipe"] else dish["title"],
                course="" if dish["recipe"] else dish.get("course", ""),
                note=dish["note"],
                proposed=True,
                position=index,
            )
            for index, dish in enumerate(meal["dishes"])
        )
    menu.rationale = proposal["rationale"]
    menu.save(update_fields=["rationale", "updated_at"])


def ask(context: Context, chat: ChatProvider) -> dict[str, Any]:
    """One call to the model, retried once if the answer is not usable."""
    last_error: Exception | None = None
    for _ in range(2):
        result = chat.chat(
            context.messages,
            temperature=0.7,
            max_tokens=MAX_ANSWER_TOKENS,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": "weekly_menu", "schema": ANSWER_SCHEMA},
            },
        )
        try:
            return validate_answer(context, json.loads(result.content or "{}"))
        except (ValueError, GenerationError) as exc:
            log.warning("unusable menu answer (%s): %.300s", exc, result.content)
            last_error = exc
    raise GenerationError(f"The model's answer was not usable: {last_error}")


def run_generation(generation: MenuGeneration, chat: ChatProvider | None = None) -> None:
    """Run a claimed generation to the end: done with a proposal applied, or failed."""
    try:
        context = build_context(generation)
        generation.rules = context.rules
        generation.save(update_fields=["rules"])
        proposal = ask(context, chat or get_chat_provider())
        apply_proposal(context, proposal)
    except (AIError, GenerationError) as exc:
        log.warning("menu generation %s failed: %s", generation.pk, exc)
        generation.status = MenuGeneration.Status.FAILED
        generation.error = str(exc)[:2000]
    except Exception as exc:
        log.exception("menu generation %s crashed", generation.pk)
        generation.status = MenuGeneration.Status.FAILED
        generation.error = f"Unexpected error: {exc}"[:2000]
    else:
        generation.status = MenuGeneration.Status.DONE
        generation.result = proposal
    generation.finished_at = timezone.now()
    generation.save(update_fields=["status", "error", "result", "finished_at"])


def claim_next() -> MenuGeneration | None:
    """Take the oldest queued generation, if any, marking it running."""
    with transaction.atomic():
        generation = (
            MenuGeneration.objects.select_for_update(skip_locked=True)
            .filter(status=MenuGeneration.Status.QUEUED)
            .order_by("created_at")
            .first()
        )
        if generation is None:
            return None
        generation.status = MenuGeneration.Status.RUNNING
        generation.started_at = timezone.now()
        generation.save(update_fields=["status", "started_at"])
        return generation


def fail_interrupted() -> int:
    """Generations left running by a worker that stopped: they will not finish."""
    return MenuGeneration.objects.filter(status=MenuGeneration.Status.RUNNING).update(
        status=MenuGeneration.Status.FAILED,
        error="Interrupted: the worker stopped before finishing.",
        finished_at=timezone.now(),
    )
