"""Adds the base ingredients the first seed skipped.

The seed (0005) left out an entry when one of its aliases was already an ingredient of its
own: "lenticchie secche", "yogurt bianco naturale" and "paprika dolce", created in the editor
before it ran, kept out "lenticchia", "yogurt" and "paprika". They are added here as system
ingredients; an alias that already names an ingredient stays that ingredient (staff merge it
from Manage if they want), and the base name is taken off any other ingredient's aliases.
Idempotent: an ingredient already there is left as it is.
"""

from django.db import migrations

ALL: list[int] = []  # available all year, as in the seed
BASE = [
    ("lenticchia", "legume", "g", ["lenticchie", "lenticchie secche"]),
    ("yogurt", "dairy", "g", ["yogurt bianco", "yogurt bianco naturale"]),
    ("paprika", "herb_spice", "tt", ["paprika dolce", "paprika affumicata"]),
]


def restore(apps, schema_editor):
    Ingredient = apps.get_model("catalog", "Ingredient")
    system = Ingredient.objects.filter(owner_team__isnull=True)
    for name, category, unit, aliases in BASE:
        if system.filter(name=name).exists():
            continue
        names = set(system.values_list("name", flat=True))
        free = sorted(a for a in aliases if a not in names and a != name)
        # Neither the base name nor its aliases may stay aliases of another ingredient.
        for other in system.filter(aliases__overlap=[name, *free]):
            other.aliases = [a for a in other.aliases if a != name and a not in free]
            other.save(update_fields=["aliases"])
        Ingredient.objects.create(
            name=name, category=category, default_unit=unit, season_months=ALL, aliases=free
        )


class Migration(migrations.Migration):
    dependencies = [("catalog", "0006_team_ingredients")]
    operations = [migrations.RunPython(restore, migrations.RunPython.noop)]
