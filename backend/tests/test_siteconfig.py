import pytest

from apps.accounts.models import UserProfile
from apps.siteconfig import registry
from apps.siteconfig.models import ConfigVar


@pytest.fixture
def admin(user):
    UserProfile.objects.create(user=user, is_admin=True)
    return user


def test_settings_have_their_defaults(db):
    assert registry.get("menu.thinking") is False
    assert registry.get("llm.context_tokens") == 8192
    assert registry.prompt_budget_chars() == 9000


def test_a_stored_value_wins_unless_it_no_longer_fits(db):
    ConfigVar.objects.create(key="llm.context_tokens", value=65536)
    assert registry.get("llm.context_tokens") == 65536
    assert registry.prompt_budget_chars() == 72000
    row = ConfigVar.objects.get(key="llm.context_tokens")
    row.value = "lots"
    row.save()
    assert registry.get("llm.context_tokens") == 8192


def test_only_admins_see_and_change_settings(api, user):
    assert api.get("/api/config/").status_code == 403
    assert api.put("/api/config/menu.thinking/", {"value": True}, format="json").status_code == 403
    assert api.get("/api/me/").json()["user"]["is_admin"] is False


def test_admins_change_and_reset_settings(api, admin):
    listed = {s["key"]: s for s in api.get("/api/config/").json()}
    assert listed["menu.thinking"]["value"] is False and listed["menu.thinking"]["is_default"]
    changed = api.put("/api/config/menu.thinking/", {"value": True}, format="json").json()
    assert changed["value"] is True and changed["is_default"] is False
    assert registry.get("menu.thinking") is True
    assert ConfigVar.objects.get(key="menu.thinking").updated_by == admin
    reset = api.delete("/api/config/menu.thinking/").json()
    assert reset["is_default"] is True and not ConfigVar.objects.exists()
    assert api.get("/api/me/").json()["user"]["is_admin"] is True


def test_setting_the_default_value_stores_nothing(api, admin):
    api.put("/api/config/llm.context_tokens/", {"value": 8192}, format="json")
    assert not ConfigVar.objects.exists()


@pytest.mark.parametrize(
    "key,value",
    [
        ("menu.thinking", "yes"),
        ("menu.thinking", 1),
        ("llm.context_tokens", 1000),
        ("llm.context_tokens", 10**7),
        ("llm.context_tokens", "64k"),
        ("llm.context_tokens", True),
        ("ui.compact_actions", "sometimes"),
        ("ui.compact_actions", True),
    ],
)
def test_values_are_validated(api, admin, key, value):
    assert api.put(f"/api/config/{key}/", {"value": value}, format="json").status_code == 400


def test_unknown_settings_are_not_found(api, admin):
    assert api.put("/api/config/nope/", {"value": 1}, format="json").status_code == 404


def test_public_settings_reach_every_user(api, user):
    assert api.get("/api/me/").json()["settings"] == {
        "ui.compact_actions": "off",
        "ui.menu_layout": "vertical",
    }
    ConfigVar.objects.create(key="ui.compact_actions", value="mobile")
    assert api.get("/api/me/").json()["settings"]["ui.compact_actions"] == "mobile"
    # Read by all, changed by administrators only.
    answer = api.put("/api/config/ui.compact_actions/", {"value": "off"}, format="json")
    assert answer.status_code == 403
