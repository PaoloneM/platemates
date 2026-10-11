"""The public and the admin plane: staff and administrator powers exist only on the admin one."""

import pytest

from apps.accounts.models import UserProfile
from apps.catalog.models import Ingredient
from apps.menus.models import SystemRule
from apps.teams.models import Team

PUBLIC = {"HTTP_X_PLATEMATES_PLANE": "public"}
ADMIN = {"HTTP_X_PLATEMATES_PLANE": "admin"}


@pytest.fixture
def staff_admin(user):
    user.is_staff = True
    user.save()
    UserProfile.objects.create(user=user, is_admin=True)
    return user


@pytest.mark.parametrize(("plane", "powers"), [(PUBLIC, False), (ADMIN, True)])
def test_me_reports_powers_not_roles(api, staff_admin, plane, powers):
    me = api.get("/api/me/", **plane).json()
    assert me["user"]["is_staff"] is powers
    assert me["user"]["is_admin"] is powers
    assert me["plane"] == ("admin" if powers else "public")
    assert (me["system_team"] is not None) is powers


@pytest.mark.parametrize(
    "path",
    [
        "/admin/",
        "/api/config/",
        "/api/cache/",
        "/api/usage/",
        "/api/transfer/choices/",
        "/api/system-drafts/",
        "/api/search-probe/",
    ],
)
def test_admin_paths_do_not_exist_on_the_public_plane(api, staff_admin, path):
    assert api.get(path, **PUBLIC).status_code == 404
    assert api.get(path, **ADMIN).status_code != 404


def test_staff_curate_the_catalog_only_on_the_admin_plane(api, staff_admin, team):
    salt = Ingredient.objects.create(name="sale")
    url = f"/api/ingredients/{salt.pk}/"
    assert api.patch(url, {"category": "condiment"}, format="json", **PUBLIC).status_code == 403
    assert api.patch(url, {"category": "condiment"}, format="json", **ADMIN).status_code == 200
    mine = Ingredient.objects.create(name="zucca", owner_team=team)
    promote = f"/api/ingredients/{mine.pk}/promote/"
    assert api.post(promote, **PUBLIC).status_code == 403
    assert api.post(promote, **ADMIN).status_code == 200


def test_system_recipes_and_rules_are_written_only_on_the_admin_plane(api, staff_admin):
    recipe = {
        "team": Team.system().pk,
        "title": "Minestrone",
        "servings": 2,
        "visibility": "shared",
    }
    assert api.post("/api/recipes/", recipe, format="json", **PUBLIC).status_code == 400
    assert api.post("/api/recipes/", recipe, format="json", **ADMIN).status_code == 201
    rule = {"text_it": "Niente fritti", "text_en": "No fried food"}
    assert api.post("/api/system-rules/", rule, format="json", **PUBLIC).status_code == 403
    assert api.post("/api/system-rules/", rule, format="json", **ADMIN).status_code == 201
    SystemRule.objects.update(active=False)
    assert api.get("/api/system-rules/", **PUBLIC).json() == []
    assert api.get("/api/system-rules/", **ADMIN).json() != []


def test_without_the_header_the_default_plane_applies(api, staff_admin, settings):
    settings.DEFAULT_PLANE = "public"
    assert api.get("/api/me/").json()["user"]["is_staff"] is False
    assert api.get("/api/config/").status_code == 404
    # An unknown value is not a plane: the default applies.
    assert api.get("/api/me/", HTTP_X_PLATEMATES_PLANE="root").json()["plane"] == "public"


def test_ordinary_users_are_the_same_on_both_planes(api, user, team):
    for plane in (PUBLIC, ADMIN):
        me = api.get("/api/me/", **plane).json()
        assert (me["user"]["is_staff"], me["user"]["is_admin"]) == (False, False)
        assert api.get("/api/config/", **plane).status_code in (403, 404)
