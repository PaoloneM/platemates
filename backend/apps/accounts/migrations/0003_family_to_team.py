from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("accounts", "0002_userprofile"), ("families", "0002_family_to_team")]
    operations = [migrations.RenameField("invitation", "family", "team")]
