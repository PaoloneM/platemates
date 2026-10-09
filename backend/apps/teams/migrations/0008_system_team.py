"""Create the system team, "PlateMates", owner of the curated community recipes.

Idempotent: it is created only if no system team exists, and an existing one is left untouched
(its name included). It has no members: staff edit its recipes.
"""

from django.db import migrations


def create(apps, schema_editor):
    Team = apps.get_model("families", "Team")
    if not Team.objects.filter(is_system=True).exists():
        Team.objects.create(name="PlateMates", is_system=True, sign_shared_recipes=True)


class Migration(migrations.Migration):
    dependencies = [("families", "0007_community")]

    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
