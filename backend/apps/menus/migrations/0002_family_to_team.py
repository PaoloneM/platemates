from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("menus", "0001_initial"), ("families", "0002_family_to_team")]
    operations = [
        migrations.RemoveConstraint(model_name="weeklymenu", name="unique_family_week"),
        migrations.RenameField("weeklymenu", "family", "team"),
        migrations.AddConstraint(
            model_name="weeklymenu",
            constraint=models.UniqueConstraint(fields=("team", "week_start"), name="unique_team_week"),
        ),
    ]
