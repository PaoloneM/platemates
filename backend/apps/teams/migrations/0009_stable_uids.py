"""A stable `uid` for objects export files refer to (apps/transfer).

In three steps, because a default on a new unique column would give every existing row the same
value: add it empty, give each row its own, then make it unique and required.
"""

import uuid

from django.db import migrations, models

MODELS = ["team", "member"]


def fill(apps, schema_editor):
    for model_name in MODELS:
        model = apps.get_model("families", model_name)
        for pk in model.objects.filter(uid__isnull=True).values_list("pk", flat=True):
            model.objects.filter(pk=pk).update(uid=uuid.uuid4())


class Migration(migrations.Migration):
    dependencies = [("families", "0008_system_team")]

    operations = [
        migrations.AddField(
            model_name="team",
            name="uid",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.AddField(
            model_name="member",
            name="uid",
            field=models.UUIDField(null=True, editable=False),
        ),
        migrations.RunPython(fill, migrations.RunPython.noop),
        migrations.AlterField(
            model_name="team",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
        migrations.AlterField(
            model_name="member",
            name="uid",
            field=models.UUIDField(default=uuid.uuid4, unique=True, editable=False),
        ),
    ]
