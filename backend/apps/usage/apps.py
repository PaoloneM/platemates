from django.apps import AppConfig


class UsageConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.usage"

    def ready(self):
        from ai.usage import set_recorder

        from .recorder import record

        # Every process running Django (backend, worker, commands) records what it consumes.
        set_recorder(record)
