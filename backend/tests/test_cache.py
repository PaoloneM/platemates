import pytest

from apps.accounts.models import UserProfile
from apps.core.cache import LAST_CLEARED_KEY, CacheManager, cache_manager
from apps.menus import generation as engine
from apps.menus.models import SystemRule, TeamRule
from apps.siteconfig import registry
from apps.siteconfig.models import ConfigVar


def loader(value):
    calls = []

    def load():
        calls.append(1)
        return value

    return load, calls


def test_a_value_is_loaded_once_then_served_from_memory():
    load, calls = loader({"a": 1})
    assert cache_manager.get_or_load("k", load) == {"a": 1}
    assert cache_manager.get_or_load("k", load) == {"a": 1}
    assert len(calls) == 1
    assert cache_manager.counters == {"memory_hits": 1, "shared_hits": 0, "misses": 1, "errors": 0}


def test_a_value_in_redis_is_copied_back_to_memory():
    load, calls = loader("fresh")
    cache_manager.shared.set("k", "shared")
    assert cache_manager.get_or_load("k", load) == "shared"
    assert cache_manager.memory.get("k") == "shared" and calls == []
    assert cache_manager.counters["shared_hits"] == 1


def test_none_is_cached_too():
    load, calls = loader(None)
    cache_manager.get_or_load("k", load)
    cache_manager.get_or_load("k", load)
    assert len(calls) == 1


def test_clearing_empties_both_levels_and_records_who():
    cache_manager.get_or_load("k", loader(1)[0])
    cache_manager.clear(by="Ada")
    assert cache_manager.memory.get("k") is None and cache_manager.shared.get("k") is None
    assert cache_manager.shared.get(LAST_CLEARED_KEY)["by"] == "Ada"


def test_without_redis_values_come_from_the_database(settings):
    settings.CACHES = {
        **settings.CACHES,
        "default": {
            "BACKEND": "django.core.cache.backends.redis.RedisCache",
            "LOCATION": "redis://127.0.0.1:1/0",
        },
    }
    manager = CacheManager()
    load, calls = loader("from db")
    assert manager.get_or_load("k", load) == "from db"
    assert manager.get_or_load("k", load) == "from db"  # kept in memory meanwhile
    assert len(calls) == 1 and manager.counters["errors"] >= 1
    assert manager.stats()["shared"]["available"] is False


def test_settings_are_cached_and_a_change_clears_the_cache(db):
    assert registry.get("menu.thinking") is False
    assert registry.get("menu.thinking") is False
    assert cache_manager.counters["memory_hits"] >= 1
    ConfigVar.objects.create(key="menu.thinking", value=True)  # through the ORM: signals fire
    assert registry.get("menu.thinking") is True
    ConfigVar.objects.filter(key="menu.thinking").delete()
    assert registry.get("menu.thinking") is False


def test_rules_are_cached_and_a_change_clears_the_cache(team):
    assert engine.team_rules(team.pk) == []
    rule = TeamRule.objects.create(team=team, text="Fish twice")
    assert engine.team_rules(team.pk) == [(rule.pk, "Fish twice")]
    before = len(engine.system_rules())
    season = SystemRule.objects.get(code="season")
    season.active = False
    season.save()
    assert len(engine.system_rules()) == before - 1


@pytest.fixture
def admin_api(api, user):
    UserProfile.objects.create(user=user, is_admin=True)
    return api


def test_only_admins_see_and_clear_the_cache(api, user):
    assert api.get("/api/cache/").status_code == 403
    assert api.post("/api/cache/clear/").status_code == 403


def test_admins_see_stats_and_clear_the_cache(admin_api, user):
    cache_manager.get_or_load("k", loader(1)[0])
    stats = admin_api.get("/api/cache/").json()
    assert stats["process"]["misses"] == 1
    assert stats["timeouts"]["memory_seconds"] == 300  # the locmem default in tests
    cleared = admin_api.post("/api/cache/clear/").json()
    assert cache_manager.shared.get("k") is None
    assert cleared["last_cleared"]["by"] == user.email
