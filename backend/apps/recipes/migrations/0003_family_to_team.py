from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("recipes", "0002_visibility_owner_steps"), ("families", "0002_family_to_team")]
    operations = [migrations.RenameField("recipe", "owner_family", "owner_team")]
