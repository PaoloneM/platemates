"""The price list's starting point, in USD (per million tokens; per thousand web searches).

Anthropic's from platform.claude.com/docs/en/about-claude/pricing, checked 2026-10-10; OpenAI's
embedding price from its pricing page. Idempotent: a model already listed is left as it is, so
prices administrators corrected are never overwritten.
"""

from decimal import Decimal as D

from django.db import migrations

WEB_SEARCH = D("10")
PRICES = {
    # model: (input, output, cache read, cache write 5 min, per 1000 searches)
    "claude-sonnet-5-5": (D("2"), D("10"), D("0.10"), D("2.50"), WEB_SEARCH),
    "claude-opus-5-5": (D("4"), D("20"), D("0.20"), D("5"), WEB_SEARCH),
    "claude-haiku-4-5-20251001": (D("1"), D("5"), D("0.10"), D("1.25"), WEB_SEARCH),
    "text-embedding-3-small": (D("0.02"), D("0"), D("0"), D("0"), D("0")),
}


def seed(apps, schema_editor):
    ModelPrice = apps.get_model("usage", "ModelPrice")
    for model, (inp, out, read, write, searches) in PRICES.items():
        ModelPrice.objects.get_or_create(
            model=model,
            defaults={
                "input_per_mtok": inp,
                "output_per_mtok": out,
                "cache_read_per_mtok": read,
                "cache_write_per_mtok": write,
                "per_thousand_searches": searches,
            },
        )


class Migration(migrations.Migration):
    dependencies = [("usage", "0001_initial")]
    operations = [migrations.RunPython(seed, migrations.RunPython.noop)]
