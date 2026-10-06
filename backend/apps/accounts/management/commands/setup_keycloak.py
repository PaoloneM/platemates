import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.accounts.keycloak_admin import KeycloakAdmin, KeycloakAdminError, config_from_env


class Command(BaseCommand):
    help = "Create or update the Keycloak realm, client and identity providers from .env."

    def handle(self, *args, **options):
        try:
            config = config_from_env(repo_root=settings.REPO_ROOT)
            admin = KeycloakAdmin(
                settings.KEYCLOAK_INTERNAL_URL,
                os.getenv("KEYCLOAK_ADMIN", "admin"),
                os.getenv("KEYCLOAK_ADMIN_PASSWORD", ""),
            )
            for line in admin.apply(config):
                self.stdout.write(line)
        except (KeycloakAdminError, ValueError, OSError) as exc:
            raise CommandError(str(exc)) from exc

        providers = ", ".join(config.identity_providers) or "none (email/password only)"
        self.stdout.write(self.style.SUCCESS(f"Keycloak ready. Social providers: {providers}."))
        if config.smtp is None:
            self.stdout.write(
                self.style.WARNING("No SMTP_HOST: password reset and email verification are off.")
            )
