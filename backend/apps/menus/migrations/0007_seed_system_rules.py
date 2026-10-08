"""Seed the system rules the app ships with.

Idempotent and never destructive: a rule is created only when no rule has its code yet, and
existing rules are left untouched, so changes staff make live are never overwritten. A later
change to a shipped rule goes in a new data migration.
"""

from django.db import migrations

# (code, Italian, English); positions go in steps of 10 so staff can slot rules in between.
RULES = [
    (
        "keep_fixed",
        "Mantieni i piatti già scelti dal team; pianifica solo i pasti liberi.",
        "Keep the dishes the team has already set; plan only the open meals.",
    ),
    (
        "people",
        "Pianifica ogni pasto per le persone previste; nessun piatto per i pasti senza nessuno "
        "a casa.",
        "Plan each meal for the number of people expected; plan nothing for a meal with nobody "
        "at home.",
    ),
    (
        "variety",
        "Non ripetere una ricetta nella stessa settimana e varia ingredienti principali, cucine "
        "e cotture da un pasto all'altro.",
        "Do not repeat a recipe within the week, and vary main ingredients, cuisines and cooking "
        "methods from one meal to the next.",
    ),
    (
        "healthy_plate",
        "Componi ogni pasto all'incirca come il «piatto sano» di Harvard: metà verdura, un "
        "quarto cereali (meglio integrali), un quarto proteine; se una ricetta da sola non "
        "basta, completala con un contorno o un altro piatto.",
        "Compose each meal roughly like Harvard's Healthy Eating Plate: half vegetables, a "
        "quarter grains (whole grains preferred), a quarter protein; when a recipe alone does "
        "not cover it, complete it with a side or another dish.",
    ),
    (
        "balance",
        "Settimana equilibrata: verdura ogni giorno, legumi e pesce più di una volta, carne "
        "rossa e salumi con moderazione.",
        "Keep the week balanced: vegetables every day, legumes and fish more than once, red and "
        "processed meat in moderation.",
    ),
    (
        "season",
        "Preferisci ricette con ingredienti di stagione.",
        "Prefer recipes whose ingredients are in season.",
    ),
    (
        "discover",
        "Attingi soprattutto al ricettario del team e proponi qualche ricetta nuova da scoprire.",
        "Draw mostly on the team's recipe book, and propose a few new recipes to discover.",
    ),
]


def seed(apps, schema_editor):
    SystemRule = apps.get_model("menus", "SystemRule")
    existing = set(SystemRule.objects.exclude(code=None).values_list("code", flat=True))
    SystemRule.objects.bulk_create(
        SystemRule(code=code, text_it=text_it, text_en=text_en, position=(index + 1) * 10)
        for index, (code, text_it, text_en) in enumerate(RULES)
        if code not in existing
    )


class Migration(migrations.Migration):
    dependencies = [("menus", "0006_system_rules")]

    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
