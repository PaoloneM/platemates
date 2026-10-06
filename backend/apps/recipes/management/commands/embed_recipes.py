from django.core.management.base import BaseCommand, CommandError

from ai import AIError, get_embedding_provider
from apps.recipes.embeddings import refresh_all


class Command(BaseCommand):
    help = (
        "Embed every recipe whose vector is missing or out of date for the configured embedding "
        "model. Idempotent: up-to-date recipes are skipped. Run it after changing EMBEDDINGS_MODEL."
    )

    def handle(self, *args, **options):
        provider = get_embedding_provider()
        health = provider.health()
        if not health.get("ok"):
            raise CommandError(f"Embedding service not available: {health.get('error')}")
        try:
            ok, failed = refresh_all(provider)
        except AIError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(self.style.SUCCESS(f"{ok} recipes up to date with {provider.model}."))
        if failed:
            self.stdout.write(self.style.WARNING(f"{failed} could not be embedded; run again."))
