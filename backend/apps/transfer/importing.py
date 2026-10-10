"""Import: bring an export document (`exporting.py`) into this installation.

- **Identity.** Objects are matched by their `uid`; created objects keep the file's, so importing
  the same file again finds them and changes nothing. Ingredients, kitchen tools, cuisines and
  system rules are also matched by name (code for shipped tools and rules): two installations
  seeded the same catalog separately, with different uids, and must not end up with two
  "pomodoro".
- **Existing objects.** Left as they are (`mode="skip"`, the default), or overwritten with the
  file's values (`mode="update"`). What is missing is always added.
- **Teams.** A team in the file goes into `target_team` when given (e.g. the team created on a
  new server for the same people), else into the team with its uid, else into a new team owned
  by the importing user. Users are never imported.
- **Preview.** `dry_run=True` runs the whole import and rolls it back: the report is exactly what
  a real import would do.

Imported values are restored as stored, provenance included: they are data moved, not decisions
taken here. Embeddings are recomputed after the import.
"""

from __future__ import annotations

import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from django.db import transaction
from django.db.models import Q

from apps.catalog.models import Ingredient, KitchenTool, normalize_name
from apps.menus.models import MealSlot, SlotDish, SystemRule, TeamRule, WeeklyMenu
from apps.recipes.models import Cuisine, Recipe, RecipeIngredient
from apps.teams.models import CalendarDay, Member, Membership, Preference, RecipeBookEntry, Team

from .exporting import FORMAT, VERSION

MODES = ("skip", "update")


class TransferError(ValueError):
    """The document cannot be imported at all (wrong format, unknown target)."""


@dataclass
class Report:
    dry_run: bool
    created: Counter = field(default_factory=Counter)
    updated: Counter = field(default_factory=Counter)
    skipped: Counter = field(default_factory=Counter)
    warnings: list[str] = field(default_factory=list)
    # Where each team of the file went: {"file": name, "into": name, "new": bool}.
    teams: list[dict[str, Any]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "dry_run": self.dry_run,
            "created": dict(self.created),
            "updated": dict(self.updated),
            "skipped": dict(self.skipped),
            "warnings": self.warnings,
            "teams": self.teams,
        }


def _decimal(value) -> Decimal | None:
    return Decimal(value) if value not in (None, "") else None


class Importer:
    def __init__(
        self,
        document: dict[str, Any],
        *,
        user,
        mode: str = "skip",
        target_team: Team | None = None,
        dry_run: bool = False,
    ) -> None:
        if not isinstance(document, dict) or document.get("format") != FORMAT:
            raise TransferError("Not a PlateMates export file.")
        if document.get("version") != VERSION:
            raise TransferError(f"Unsupported export version {document.get('version')!r}.")
        if mode not in MODES:
            raise TransferError(f"Unknown mode {mode!r}.")
        self.doc = document
        self.user = user
        self.update = mode == "update"
        self.target_team = target_team
        self.report = Report(dry_run=dry_run)
        self.tools: dict[tuple, KitchenTool] = {}
        self.teams: dict[str, Team] = {}
        self.ingredients: dict[str, Ingredient] = {}
        self.recipes: dict[str, Recipe] = {}
        self.touched_recipes: list[Recipe] = []
        # Book entries this import created with a recipe: completed from the file's book.
        self.new_entries: set[int] = set()

    # -- entry point -----------------------------------------------------------------------------

    def run(self) -> Report:
        with transaction.atomic():
            self._tools()
            self._cuisines()
            self._teams()
            self._ingredients()
            self._system_rules()
            self._recipes()
            for data in self.doc.get("teams") or []:
                self._team_contents(self.teams[data["uid"]], data)
            if self.report.dry_run:
                transaction.set_rollback(True)
            else:
                transaction.on_commit(self._embed)
        return self.report

    def _embed(self) -> None:
        from apps.recipes.embeddings import refresh_embedding

        for recipe in self.touched_recipes:
            refresh_embedding(recipe)

    def _count(self, outcome: str, kind: str) -> None:
        getattr(self.report, outcome)[kind] += 1

    # -- shared catalogs -------------------------------------------------------------------------

    def _tool(self, ref: dict[str, Any]) -> KitchenTool | None:
        key = (ref.get("code"), ref.get("name"))
        if key in self.tools:
            return self.tools[key]
        tool = None
        if ref.get("code"):
            tool = KitchenTool.objects.filter(code=ref["code"]).first()
        if tool is None and ref.get("name"):
            tool = KitchenTool.objects.filter(name__iexact=ref["name"]).first()
        self.tools[key] = tool
        return tool

    def _tools(self) -> None:
        for data in self.doc.get("kitchen_tools") or []:
            tool = self._tool(data)
            if tool is None:
                tool = KitchenTool.objects.create(
                    name=data["name"], code=data.get("code"), heats_kitchen=data["heats_kitchen"]
                )
                self.tools[(data.get("code"), data.get("name"))] = tool
                self._count("created", "kitchen_tools")
            elif self.update and tool.heats_kitchen != data["heats_kitchen"]:
                tool.heats_kitchen = data["heats_kitchen"]
                tool.save(update_fields=["heats_kitchen"])
                self._count("updated", "kitchen_tools")
            else:
                self._count("skipped", "kitchen_tools")

    def _cuisine(self, name: str | None) -> Cuisine | None:
        if not name:
            return None
        cuisine = Cuisine.objects.filter(name__iexact=name).first()
        return cuisine or Cuisine.objects.create(name=name)

    def _cuisines(self) -> None:
        for name in self.doc.get("cuisines") or []:
            if Cuisine.objects.filter(name__iexact=name).exists():
                self._count("skipped", "cuisines")
            else:
                Cuisine.objects.create(name=name)
                self._count("created", "cuisines")

    # -- teams -----------------------------------------------------------------------------------

    def _teams(self) -> None:
        files = self.doc.get("teams") or []
        if self.target_team is not None and len(files) > 1:
            raise TransferError("A target team takes a file with one team.")
        for data in files:
            team, new = self.target_team, False
            if team is None:
                team = Team.objects.filter(uid=data["uid"], is_system=False).first()
            if team is None:
                team = Team.objects.create(uid=data["uid"], name=data["name"])
                Membership.objects.create(user=self.user, team=team, role=Membership.Role.OWNER)
                new = True
                self._count("created", "teams")
            if new or self.update:
                team.name = data["name"] if new else team.name
                team.typical_week = data["typical_week"]
                team.max_weekday_minutes = data["max_weekday_minutes"]
                team.notes = data["notes"]
                team.sign_shared_recipes = data["sign_shared_recipes"]
                team.save()
                team.tools.set([t for t in map(self._tool, data["tools"]) if t])
                if not new:
                    self._count("updated", "teams")
            else:
                self._count("skipped", "teams")
            self.teams[data["uid"]] = team
            self.report.teams.append({"file": data["name"], "into": team.name, "new": new})

    def _owner(self, ref: dict[str, Any] | None) -> Team | None:
        """Where a recipe or ingredient of the file belongs here. None: nowhere (warned)."""
        if ref is None:
            return None
        if ref.get("system"):
            return Team.system()
        if ref["uid"] in self.teams:
            return self.teams[ref["uid"]]
        team = Team.objects.filter(uid=ref["uid"]).first() or self.target_team
        if team is not None:
            self.teams[ref["uid"]] = team
        return team

    # -- ingredients -----------------------------------------------------------------------------

    def _find_ingredient(self, ref: dict[str, Any]) -> Ingredient | None:
        if ref["uid"] in self.ingredients:
            return self.ingredients[ref["uid"]]
        ingredient = Ingredient.objects.filter(uid=ref["uid"]).first()
        if ingredient is None:
            owner = self._owner({"uid": ref["team"]}) if ref.get("team") else None
            name = normalize_name(ref["name"])
            ingredient = (
                Ingredient.objects.usable_by(owner)
                .filter(Q(name=name) | Q(aliases__contains=[name]))
                .order_by("owner_team")
                .first()
            )
        if ingredient is not None:
            self.ingredients[ref["uid"]] = ingredient
        return ingredient

    def _ingredients(self) -> None:
        for data in self.doc.get("ingredients") or []:
            ingredient = self._find_ingredient(data)
            if ingredient is not None:
                if self.update and str(ingredient.uid) == data["uid"]:
                    self._set_ingredient(ingredient, data)
                    ingredient.save()
                    self._count("updated", "ingredients")
                else:
                    self._count("skipped", "ingredients")
                continue
            owner = None
            if data.get("team"):
                owner = self._owner({"uid": data["team"]})
                if owner is None:
                    self.report.warnings.append(
                        f"Ingredient «{data['name']}» belongs to a team not in this import: "
                        "added as a system ingredient."
                    )
            ingredient = Ingredient(uid=data["uid"], owner_team=owner)
            self._set_ingredient(ingredient, data)
            ingredient.save()
            self.ingredients[data["uid"]] = ingredient
            self._count("created", "ingredients")

    @staticmethod
    def _set_ingredient(ingredient: Ingredient, data: dict[str, Any]) -> None:
        ingredient.name = data["name"]
        ingredient.aliases = data["aliases"]
        ingredient.category = data["category"]
        ingredient.default_unit = data["default_unit"]
        ingredient.season_months = data["season_months"]
        ingredient.provenance = data["provenance"]

    # -- system rules ----------------------------------------------------------------------------

    def _system_rules(self) -> None:
        for data in self.doc.get("system_rules") or []:
            rule = SystemRule.objects.filter(uid=data["uid"]).first()
            if rule is None and data.get("code"):
                rule = SystemRule.objects.filter(code=data["code"]).first()
            if rule is None:
                rule = SystemRule.objects.filter(text_it=data["text_it"]).first()
            if rule is not None and not self.update:
                self._count("skipped", "system_rules")
                continue
            new = rule is None
            rule = rule or SystemRule(uid=data["uid"], code=data.get("code"))
            for key in ("text_it", "text_en", "position", "active"):
                setattr(rule, key, data[key])
            rule.save()  # through save(): rules are cached and cleared by their signals
            self._count("created" if new else "updated", "system_rules")

    # -- recipes ---------------------------------------------------------------------------------

    def _find_recipe(self, ref: dict[str, Any] | None) -> Recipe | None:
        if ref is None:
            return None
        if ref["uid"] in self.recipes:
            return self.recipes[ref["uid"]]
        recipe = Recipe.objects.filter(uid=ref["uid"]).first()
        if recipe is not None:
            self.recipes[ref["uid"]] = recipe
        return recipe

    def _recipes(self) -> None:
        files = self.doc.get("recipes") or []
        for data in files:
            recipe = self._find_recipe(data)
            if recipe is not None and not self.update:
                self._count("skipped", "recipes")
                continue
            owner = self._owner(data["team"])
            if owner is None:
                self.report.warnings.append(
                    f"Recipe «{data['title']}» belongs to a team not in this import: "
                    "choose a target team to import it."
                )
                continue
            new = recipe is None
            recipe = recipe or Recipe(uid=data["uid"], owner_team=owner)
            self._set_recipe(recipe, data)
            recipe.save()
            recipe.tools.set([t for t in map(self._tool, data["tools"]) if t])
            self._set_lines(recipe, data)
            if new and not owner.is_system:
                # A team's own recipe is in its book, as when it is created in the editor.
                entry, made = RecipeBookEntry.objects.get_or_create(
                    team=owner, recipe=recipe, defaults={"status": RecipeBookEntry.Status.APPROVED}
                )
                if made:
                    self.new_entries.add(entry.pk)
            self.recipes[data["uid"]] = recipe
            self.touched_recipes.append(recipe)
            self._count("created" if new else "updated", "recipes")
        # Second pass: an original may come later in the file, or already be here.
        for data in files:
            recipe = self.recipes.get(data["uid"])
            if recipe is None or recipe not in self.touched_recipes:
                continue
            original = self._find_recipe(data["derived_from"])
            if data["derived_from"] and original is None:
                self.report.warnings.append(
                    f"«{data['title']}» is a version of «{data['derived_from']['title']}», "
                    "which is not here: imported without the link to it."
                )
            if recipe.derived_from_id != (original.pk if original else None):
                recipe.derived_from = original
                recipe.save(update_fields=["derived_from"])

    def _set_recipe(self, recipe: Recipe, data: dict[str, Any]) -> None:
        recipe.title = data["title"]
        recipe.description = data["description"]
        recipe.steps = data["steps"]
        recipe.visibility = data["visibility"]
        recipe.course = data["course"]
        recipe.cuisine = self._cuisine(data["cuisine"])
        recipe.servings = data["servings"]
        recipe.prep_minutes = data["prep_minutes"]
        recipe.cook_minutes = data["cook_minutes"]
        recipe.season_months = data["season_months"]
        recipe.climate_months = data["climate_months"]
        recipe.source_url = data["source_url"]
        recipe.web_rating = _decimal(data["web_rating"])
        recipe.web_rating_count = data["web_rating_count"]
        recipe.provenance = data["provenance"]

    def _set_lines(self, recipe: Recipe, data: dict[str, Any]) -> None:
        recipe.ingredients.all().delete()
        lines = []
        for line in data["ingredients"]:
            ingredient = self._find_ingredient(line["ingredient"])
            if ingredient is None:
                self.report.warnings.append(
                    f"«{recipe.title}»: ingredient «{line['ingredient']['name']}» not found, "
                    "line left out."
                )
                continue
            lines.append(
                RecipeIngredient(
                    recipe=recipe,
                    ingredient=ingredient,
                    quantity=_decimal(line["quantity"]),
                    unit=line["unit"],
                    optional=line["optional"],
                    note=line["note"],
                    position=line["position"],
                )
            )
        RecipeIngredient.objects.bulk_create(lines)

    # -- a team's own data -----------------------------------------------------------------------

    def _team_contents(self, team: Team, data: dict[str, Any]) -> None:
        members = self._members(team, data["members"])
        self._preferences(team, data["preferences"], members)
        self._calendar(team, data["calendar"])
        rules = self._rules(team, data["rules"])
        self._book(team, data["book"])
        self._menus(team, data["menus"], rules)

    def _members(self, team: Team, rows) -> dict[str, Member]:
        found = {}
        for row in rows:
            member = Member.objects.filter(uid=row["uid"]).first()
            if member is None:
                member = Member.objects.create(
                    uid=row["uid"], team=team, name=row["name"], birth_year=row["birth_year"]
                )
                self._count("created", "members")
            elif self.update:
                member.name, member.birth_year = row["name"], row["birth_year"]
                member.save()
                self._count("updated", "members")
            else:
                self._count("skipped", "members")
            found[row["uid"]] = member
        return found

    def _preferences(self, team: Team, rows, members: dict[str, Member]) -> None:
        for row in rows:
            ingredient = self._find_ingredient(row["ingredient"]) if row["ingredient"] else None
            if row["ingredient"] and ingredient is None:
                self.report.warnings.append(
                    f"Preference on «{row['ingredient']['name']}»: ingredient not found, left out."
                )
                continue
            values = {
                "team": team,
                "member": members.get(row["member"]) if row["member"] else None,
                "kind": row["kind"],
                "ingredient": ingredient,
                "cuisine": self._cuisine(row["cuisine"]),
                "note": row["note"],
            }
            if Preference.objects.filter(**values).exists():
                self._count("skipped", "preferences")
            else:
                Preference.objects.create(**values)
                self._count("created", "preferences")

    def _calendar(self, team: Team, rows) -> None:
        for row in rows:
            day = CalendarDay.objects.filter(team=team, date=row["date"]).first()
            if day is not None and not self.update:
                self._count("skipped", "calendar_days")
                continue
            new = day is None
            day = day or CalendarDay(team=team, date=row["date"])
            day.people, day.note = row["people"], row["note"]
            day.save()
            self._count("created" if new else "updated", "calendar_days")

    def _rules(self, team: Team, rows) -> dict[str, TeamRule]:
        found = {}
        for row in rows:
            rule = TeamRule.objects.filter(uid=row["uid"]).first()
            if rule is None:
                rule = TeamRule.objects.create(uid=row["uid"], team=team, text=row["text"])
                self._count("created", "team_rules")
            elif self.update and rule.text != row["text"]:
                rule.text = row["text"]
                rule.save()
                self._count("updated", "team_rules")
            else:
                self._count("skipped", "team_rules")
            found[row["uid"]] = rule
        return found

    def _book(self, team: Team, rows) -> None:
        for row in rows:
            recipe = self._find_recipe(row["recipe"])
            if recipe is None:
                self.report.warnings.append(
                    f"Recipe book: «{row['recipe']['title']}» is not here (import the system "
                    "data, or the team it comes from, first): left out."
                )
                continue
            entry = RecipeBookEntry.objects.filter(team=team, recipe=recipe).first()
            if entry is not None and entry.pk in self.new_entries:
                entry.status, entry.rating, entry.notes = row["status"], row["rating"], row["notes"]
                entry.save()
                continue  # counted with its recipe
            if entry is not None and not self.update:
                self._count("skipped", "book_entries")
                continue
            new = entry is None
            entry = entry or RecipeBookEntry(team=team, recipe=recipe)
            entry.status, entry.rating, entry.notes = row["status"], row["rating"], row["notes"]
            entry.save()
            self._count("created" if new else "updated", "book_entries")

    def _menus(self, team: Team, rows, rules: dict[str, TeamRule]) -> None:
        for row in rows:
            menu = WeeklyMenu.objects.filter(team=team, week_start=row["week_start"]).first()
            if menu is not None and not self.update:
                self._count("skipped", "menus")
                continue
            new = menu is None
            menu = menu or WeeklyMenu(team=team, week_start=row["week_start"])
            for key in ("status", "rationale", "instructions", "use_team_rules"):
                setattr(menu, key, row[key])
            menu.save()
            menu.excluded_rules.set([rules[u] for u in row["excluded_rules"] if u in rules])
            menu.slots.all().delete()
            for slot_row in row["slots"]:
                self._slot(menu, slot_row)
            self._count("created" if new else "updated", "menus")

    def _slot(self, menu: WeeklyMenu, row: dict[str, Any]) -> None:
        slot = MealSlot.objects.create(
            menu=menu,
            date=dt.date.fromisoformat(row["date"]),
            meal=row["meal"],
            people=row["people"],
            proposed_people=row["proposed_people"],
            people_note=row["people_note"],
            outcome=row["outcome"],
            eaten_instead_note=row["eaten_instead_note"],
            rating=row["rating"],
            comment=row["comment"],
        )
        slot.eaten_instead.set([r for r in map(self._find_recipe, row["eaten_instead"]) if r])
        for dish in row["dishes"]:
            recipe = self._find_recipe(dish["recipe"])
            if dish["recipe"] and recipe is None:
                # Kept as a free-text dish: the menu still says what was planned.
                self.report.warnings.append(
                    f"Menu of {menu.week_start}: «{dish['recipe']['title']}» is not here, kept "
                    "as a dish name."
                )
            title = dish["title"]
            if recipe is None and not title:
                title = (dish["recipe"] or {}).get("title", "")
            SlotDish.objects.create(
                slot=slot,
                recipe=recipe,
                title=title,
                course=dish["course"],
                note=dish["note"],
                proposed=dish["proposed"],
                position=dish["position"],
            )


def import_document(document, *, user, mode="skip", target_team=None, dry_run=False) -> Report:
    return Importer(document, user=user, mode=mode, target_team=target_team, dry_run=dry_run).run()
