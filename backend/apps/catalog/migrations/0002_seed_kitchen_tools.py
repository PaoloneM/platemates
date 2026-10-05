"""Seed the common kitchen tools. Families pick theirs; the list stays editable in the admin."""

from django.db import migrations

TOOLS = [
    ("air fryer", False),
    ("blender", False),
    ("conventional oven", True),
    ("deep fryer", True),
    ("food processor", False),
    ("gas hob", False),
    ("grill", True),
    ("induction hob", False),
    ("microwave", False),
    ("pressure cooker", False),
    ("slow cooker", False),
    ("steam oven", True),
]


def seed(apps, schema_editor):
    KitchenTool = apps.get_model("catalog", "KitchenTool")
    for name, heats_kitchen in TOOLS:
        KitchenTool.objects.get_or_create(name=name, defaults={"heats_kitchen": heats_kitchen})


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
