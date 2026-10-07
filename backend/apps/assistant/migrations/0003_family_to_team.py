from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("assistant", "0002_attachments"), ("families", "0002_family_to_team")]
    operations = [migrations.RenameField("assistantsession", "family", "team")]
