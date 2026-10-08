from django.apps import AppConfig


class SiteConfigConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.siteconfig"

    def ready(self):
        from django.db.models.signals import post_delete, post_migrate, post_save

        from apps.core.cache import cache_manager

        from .models import ConfigVar

        def changed(sender, **kwargs):
            cache_manager.clear(by=f"automatic: {sender._meta.verbose_name} changed")

        post_save.connect(changed, sender=ConfigVar, dispatch_uid="siteconfig-cache-save")
        post_delete.connect(changed, sender=ConfigVar, dispatch_uid="siteconfig-cache-delete")

        # The backend migrates at every start: data seeded by migrations, or changed while the
        # app was down, must not stay hidden behind the cache.
        def migrated(sender, **kwargs):
            cache_manager.clear(by="automatic: start-up")

        post_migrate.connect(migrated, sender=self, dispatch_uid="siteconfig-cache-migrate")
