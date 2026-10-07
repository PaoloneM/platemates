"""Replace the per-meal default diners with a typical week (per weekday, breakfast included).

Existing teams keep their counts: every day active, the old lunch and dinner values, nobody at
breakfast.
"""

from django.db import migrations, models

import apps.teams.models


def to_typical_week(apps, schema_editor):
    Team = apps.get_model("families", "Team")
    for team in Team.objects.all():
        old = team.default_people or {}
        day = {
            "active": True,
            "breakfast": 0,
            "lunch": int(old.get("lunch", 2)),
            "dinner": int(old.get("dinner", 3)),
        }
        team.typical_week = [dict(day) for _weekday in range(7)]
        team.save(update_fields=["typical_week"])


def to_default_people(apps, schema_editor):
    Team = apps.get_model("families", "Team")
    for team in Team.objects.all():
        monday = team.typical_week[0]
        team.default_people = {"lunch": monday.get("lunch", 2), "dinner": monday.get("dinner", 3)}
        team.save(update_fields=["default_people"])


class Migration(migrations.Migration):
    dependencies = [("families", "0003_alter_member_options_alter_team_options_and_more")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="typical_week",
            field=models.JSONField(default=apps.teams.models.default_typical_week),
        ),
        migrations.RunPython(to_typical_week, to_default_people),
        migrations.RemoveField(model_name="team", name="default_people"),
    ]
