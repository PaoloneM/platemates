from django.apps import AppConfig


class TeamsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.teams"
    # The label stays "families", the app's original name: it keys the migration history and
    # the table names (families_team, ...), which renaming would force to rewrite for no gain.
    label = "families"
    verbose_name = "Teams"
