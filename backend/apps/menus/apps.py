from django.apps import AppConfig


class MenusConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.menus"

    def ready(self):
        from django.db.models.signals import post_delete, post_save

        from apps.core.cache import cache_manager

        from .models import SystemRule, TeamRule

        def changed(sender, **kwargs):
            cache_manager.clear(by=f"automatic: {sender._meta.verbose_name} changed")

        for model in (SystemRule, TeamRule):
            name = model._meta.model_name
            post_save.connect(changed, sender=model, dispatch_uid=f"{name}-cache-save")
            post_delete.connect(changed, sender=model, dispatch_uid=f"{name}-cache-delete")
