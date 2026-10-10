import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.models import Ingredient
from apps.teams.models import Team
from apps.transfer.exporting import (
    SCOPES,
    export_ingredients,
    export_recipes,
    export_system,
    export_team,
)


def find_team(value: str) -> Team:
    teams = Team.objects.filter(is_system=False)
    team = teams.filter(pk=value).first() if value.isdigit() else teams.filter(name=value).first()
    if team is None:
        raise CommandError(f"No team {value!r}.")
    return team


class Command(BaseCommand):
    help = "Export recipes, ingredients, a team or the system data as a PlateMates JSON file."

    def add_arguments(self, parser):
        parser.add_argument("scope", choices=SCOPES)
        parser.add_argument("--team", help="team id or name (scope team)")
        parser.add_argument("--ids", default="", help="comma-separated ids (recipes, ingredients)")
        parser.add_argument("--system-ingredients", action="store_true")
        parser.add_argument("-o", "--output", help="file to write (default: standard output)")

    def handle(self, scope, team, ids, system_ingredients, output, **options):
        id_list = [int(v) for v in ids.split(",") if v.strip()]
        if scope == "team":
            if not team:
                raise CommandError("--team is required.")
            document = export_team(find_team(team))
        elif scope == "recipes":
            document = export_recipes(id_list)
        elif scope == "ingredients":
            if system_ingredients:
                id_list = list(Ingredient.objects.system().values_list("pk", flat=True))
            document = export_ingredients(id_list)
        else:
            document = export_system()
        text = json.dumps(document, ensure_ascii=False, indent=1)
        if output:
            Path(output).write_text(text)
            self.stderr.write(f"Written {output}.")
        else:
            self.stdout.write(text)
