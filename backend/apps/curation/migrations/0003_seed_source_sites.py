"""The recipe sites a campaign's web search starts from: trusted ones it prefers, blocked ones
it never uses. Added if missing, never changed: staff may edit them (Manage > Campaigns)."""

from django.db import migrations

TRUSTED = [
    ("giallozafferano.it", "Ricette italiane di tutti i giorni, molto votate"),
    ("cucchiaio.it", "Il Cucchiaio d'Argento"),
    ("misya.info", "Ricette casalinghe semplici"),
    ("fattoincasadabenedetta.it", "Ricette casalinghe, spesso veloci"),
    ("lacucinaitaliana.it", "La Cucina Italiana"),
    ("salepepe.it", "Sale&Pepe"),
    ("buttalapasta.it", "Ricette semplici"),
    ("cookist.it", "Ricette veloci, anche internazionali"),
]
BLOCKED = [
    ("pinterest.com", "Raccolte di link, non ricette"),
    ("pinterest.it", "Raccolte di link, non ricette"),
    ("facebook.com", "Social"),
    ("instagram.com", "Social"),
    ("youtube.com", "Video"),
    ("tiktok.com", "Video"),
]


def seed(apps, schema_editor):
    SourceSite = apps.get_model("curation", "SourceSite")
    for sites, trusted in ((TRUSTED, True), (BLOCKED, False)):
        for domain, note in sites:
            SourceSite.objects.get_or_create(
                domain=domain, defaults={"trusted": trusted, "note": note}
            )


class Migration(migrations.Migration):
    dependencies = [("curation", "0002_campaigns")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
