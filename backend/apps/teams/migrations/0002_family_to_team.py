"""Family -> Team: the app serves any group that shares meals, not only families.

Renames only: every row (teams, members, preferences, recipe book entries, embeddings) is kept.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    # After every migration that still refers to the old model names.
    dependencies = [
        ("families", "0001_initial"),
        ("catalog", "0005_seed_common_ingredients"),
        ("accounts", "0002_userprofile"),
        ("assistant", "0002_attachments"),
        ("menus", "0001_initial"),
        ("recipes", "0002_visibility_owner_steps"),
    ]

    operations = [
        migrations.RenameModel("Family", "Team"),
        migrations.RenameModel("FamilyMember", "Member"),
        migrations.RenameModel("FamilyEmbedding", "TeamEmbedding"),
        migrations.RemoveConstraint(model_name="teamembedding", name="unique_family_embedding"),
        migrations.RenameField("membership", "family", "team"),
        migrations.RenameField("member", "family", "team"),
        migrations.RenameField("preference", "family", "team"),
        migrations.RenameField("recipebookentry", "family", "team"),
        migrations.RenameField("teamembedding", "family", "team"),
        migrations.AddConstraint(
            model_name="teamembedding",
            constraint=models.UniqueConstraint(fields=("team", "model"), name="unique_team_embedding"),
        ),
    ]
