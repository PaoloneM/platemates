import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.recipes.models import Recipe, Visibility
from apps.teams.models import Membership, RecipeBookEntry, Team


@pytest.fixture
def neighbours(db):
    """Another team, with its own user, its shared and private recipes."""
    user = get_user_model().objects.create_user("bea")
    team = Team.objects.create(name="Famiglia Bianchi")
    Membership.objects.create(user=user, team=team, role=Membership.Role.OWNER)
    client = APIClient()
    client.force_authenticate(user)
    shared = Recipe.objects.create(title="Ribollita", owner_team=team)
    private = Recipe.objects.create(
        title="Segreto di famiglia", owner_team=team, visibility=Visibility.PRIVATE
    )
    for recipe in (shared, private):
        RecipeBookEntry.objects.create(team=team, recipe=recipe, status="approved")
    return team, client, shared, private


@pytest.fixture
def system_recipe(db):
    return Recipe.objects.create(title="Lasagne alla bolognese", owner_team=Team.system())


def new_recipe(team, **extra):
    return {"team": team.pk, "title": "Pasta e ceci", "servings": 2, **extra}


def browse(client, team, **params):
    query = "&".join(f"{k}={v}" for k, v in {"team": team.pk, **params}.items())
    response = client.get(f"/api/recipes/browse/?{query}")
    assert response.status_code == 200, response.json()
    return {r["title"]: r for r in response.json()["results"]}


# -- the system team ---------------------------------------------------------------------------


def test_there_is_one_system_team_and_nobody_is_in_it(db):
    system = Team.system()
    assert system.name == "PlateMates" and system.sign_shared_recipes
    assert not system.memberships.exists()


def test_the_system_team_is_never_one_of_the_users_teams(api, team):
    assert [t["id"] for t in api.get("/api/teams/").json()["results"]] == [team.pk]


def test_only_staff_write_system_recipes(api, user, team):
    body = new_recipe(Team.system(), visibility="shared")
    assert api.post("/api/recipes/", body, format="json").status_code == 400
    user.is_staff = True
    user.save()
    assert api.get("/api/me/").json()["system_team"] == Team.system().pk
    created = api.post("/api/recipes/", body, format="json").json()
    assert created["author"] == {"kind": "system", "name": "PlateMates"}
    private = new_recipe(Team.system(), visibility="private")
    assert api.post("/api/recipes/", private, format="json").status_code == 400


def test_members_do_not_learn_the_system_team(api):
    assert api.get("/api/me/").json()["system_team"] is None


# -- sharing is a choice -----------------------------------------------------------------------


def test_a_new_recipe_needs_a_sharing_choice(api, team):
    assert api.post("/api/recipes/", new_recipe(team), format="json").status_code == 400
    private = api.post("/api/recipes/", new_recipe(team, visibility="private"), format="json")
    assert private.status_code == 201 and private.json()["visibility"] == "private"


def test_editing_keeps_the_sharing_choice_unless_changed(api, team):
    recipe = api.post("/api/recipes/", new_recipe(team, visibility="private"), format="json")
    rid = recipe.json()["id"]
    assert api.patch(f"/api/recipes/{rid}/", {"title": "Pasta e fagioli"}).json()["visibility"] == (
        "private"
    )
    assert api.patch(f"/api/recipes/{rid}/", {"visibility": "shared"}).json()["visibility"] == (
        "shared"
    )


# -- signature ---------------------------------------------------------------------------------


def test_shared_recipes_are_anonymous_unless_the_team_signs_them(api, team, neighbours):
    other, other_client, shared, _ = neighbours
    assert api.get(f"/api/recipes/{shared.pk}/").json()["author"] == {
        "kind": "community",
        "name": None,
    }
    assert (
        other_client.patch(
            f"/api/teams/{other.pk}/", {"sign_shared_recipes": True}, format="json"
        ).status_code
        == 200
    )
    assert api.get(f"/api/recipes/{shared.pk}/").json()["author"] == {
        "kind": "team",
        "name": "Famiglia Bianchi",
    }
    assert other_client.get(f"/api/recipes/{shared.pk}/").json()["author"]["kind"] == "mine"


# -- import and change: variants ---------------------------------------------------------------


def test_importing_makes_an_editable_copy_linked_to_the_original(api, team, neighbours):
    _, _, shared, _ = neighbours
    body = new_recipe(
        team, title="Ribollita della nonna", visibility="shared", derived_from=shared.pk
    )
    copy = api.post("/api/recipes/", body, format="json").json()
    assert copy["derived_from"] == shared.pk and copy["origin"] == {
        "id": shared.pk,
        "title": "Ribollita",
    }
    assert copy["can_edit"] and copy["author"]["kind"] == "mine"
    assert Recipe.objects.get(pk=shared.pk).title == "Ribollita"  # the original is untouched


def test_importing_never_touches_the_original(api, team, neighbours, system_recipe):
    _, _, shared, _ = neighbours
    for original in (shared, system_recipe):
        before = (original.title, original.owner_team_id, original.visibility)
        copy = api.post(
            "/api/recipes/",
            new_recipe(team, title="Mia", visibility="private", derived_from=original.pk),
            format="json",
        ).json()
        # Removing the copy from the book deletes the (private, unused) copy, never the original.
        entry = copy["book_entries"][0]["id"]
        assert api.delete(f"/api/recipe-book/{entry}/").status_code == 204
        assert not Recipe.objects.filter(pk=copy["id"]).exists()
        original.refresh_from_db()
        assert (original.title, original.owner_team_id, original.visibility) == before


def test_staff_importing_a_system_recipe_make_a_copy(api, user, team, system_recipe):
    user.is_staff = True
    user.save()
    assert api.get(f"/api/recipes/{system_recipe.pk}/").json()["can_edit"]  # staff may edit it
    copy = api.post(
        "/api/recipes/",
        new_recipe(team, title="Lasagne mie", visibility="private", derived_from=system_recipe.pk),
        format="json",
    ).json()
    assert copy["author"]["kind"] == "mine" and copy["origin"]["id"] == system_recipe.pk
    system_recipe.refresh_from_db()
    assert system_recipe.title == "Lasagne alla bolognese"


def test_a_version_replaces_the_original_added_as_it_is(api, team, neighbours):
    _, _, shared, _ = neighbours
    api.post("/api/recipe-book/", {"team": team.pk, "recipe": shared.pk, "status": "approved"})
    assert set(browse(api, team)) == {"Ribollita"}
    assert api.get(f"/api/recipes/{shared.pk}/").json()["my_version"] is None
    copy = api.post(
        "/api/recipes/",
        new_recipe(team, title="Ribollita mia", visibility="private", derived_from=shared.pk),
        format="json",
    ).json()
    assert set(browse(api, team)) == {"Ribollita mia"}
    assert api.get(f"/api/recipes/{shared.pk}/").json()["my_version"] == {
        "id": copy["id"],
        "title": "Ribollita mia",
    }
    shared.refresh_from_db()  # the original itself is untouched, still in its author's book
    assert shared.book_entries.filter(team=neighbours[0]).exists()


def test_the_authors_own_book_keeps_the_original_of_its_copy(api, team):
    mine = api.post("/api/recipes/", new_recipe(team, visibility="shared"), format="json").json()
    api.post(
        "/api/recipes/",
        new_recipe(team, title="Pasta e ceci bis", visibility="private", derived_from=mine["id"]),
        format="json",
    )
    assert set(browse(api, team)) == {"Pasta e ceci", "Pasta e ceci bis"}
    assert api.get(f"/api/recipes/{mine['id']}/").json()["my_version"] is None


def test_a_copy_of_a_copy_is_a_variant_of_the_original(api, team, neighbours):
    _, other_client, shared, _ = neighbours
    first = other_client.post(
        "/api/recipes/",
        {**new_recipe(neighbours[0], visibility="shared"), "derived_from": shared.pk},
        format="json",
    ).json()
    second = api.post(
        "/api/recipes/",
        new_recipe(team, visibility="private", derived_from=first["id"]),
        format="json",
    ).json()
    assert second["derived_from"] == shared.pk


def test_nobody_imports_what_they_cannot_see(api, team, neighbours):
    _, _, _, private = neighbours
    body = new_recipe(team, visibility="shared", derived_from=private.pk)
    assert api.post("/api/recipes/", body, format="json").status_code == 400


def test_the_origin_is_set_only_when_importing(api, team, neighbours, system_recipe):
    _, _, shared, _ = neighbours
    copy = api.post(
        "/api/recipes/",
        new_recipe(team, visibility="shared", derived_from=shared.pk),
        format="json",
    ).json()
    api.patch(f"/api/recipes/{copy['id']}/", {"derived_from": system_recipe.pk}, format="json")
    assert Recipe.objects.get(pk=copy["id"]).derived_from_id == shared.pk


def test_variants_are_listed_only_when_shared(api, team, neighbours):
    _, other_client, shared, _ = neighbours
    mine = api.post(
        "/api/recipes/",
        new_recipe(team, visibility="shared", derived_from=shared.pk),
        format="json",
    ).json()
    api.post(
        "/api/recipes/",
        new_recipe(team, title="Copia privata", visibility="private", derived_from=shared.pk),
        format="json",
    )
    seen_by_author = other_client.get(f"/api/recipes/{shared.pk}/variants/").json()
    assert seen_by_author["original"] is None
    assert [v["title"] for v in seen_by_author["variants"]] == ["Pasta e ceci"]
    from_the_variant = api.get(f"/api/recipes/{mine['id']}/variants/").json()
    assert from_the_variant["original"]["id"] == shared.pk
    assert [v["title"] for v in from_the_variant["variants"]] == ["Copia privata"]  # own team


def test_deleting_the_original_keeps_the_copies(api, team, neighbours):
    shared = neighbours[2]
    copy = api.post(
        "/api/recipes/",
        new_recipe(team, visibility="shared", derived_from=shared.pk),
        format="json",
    ).json()
    RecipeBookEntry.objects.filter(recipe=shared).delete()
    shared.delete()
    assert api.get(f"/api/recipes/{copy['id']}/").json()["origin"] is None


# -- the recipe book screen --------------------------------------------------------------------


def test_the_book_the_community_or_both(api, team, neighbours, system_recipe):
    mine = api.post("/api/recipes/", new_recipe(team, visibility="private"), format="json").json()
    assert set(browse(api, team)) == {"Pasta e ceci"}
    community = browse(api, team, mine=0, community=1)
    assert set(community) == {"Ribollita", "Lasagne alla bolognese"}
    assert community["Lasagne alla bolognese"]["author"]["kind"] == "system"
    assert community["Ribollita"]["book"] is None
    both = browse(api, team, community=1)
    assert set(both) == {"Pasta e ceci", "Ribollita", "Lasagne alla bolognese"}
    assert both["Pasta e ceci"]["book"]["id"] and mine["id"]


def test_a_community_recipe_added_as_is_is_in_the_book(api, team, neighbours):
    _, _, shared, _ = neighbours
    api.post("/api/recipe-book/", {"team": team.pk, "recipe": shared.pk, "status": "approved"})
    book = browse(api, team)
    assert set(book) == {"Ribollita"} and book["Ribollita"]["book"] is not None
    assert book["Ribollita"]["author"]["kind"] == "community"


def test_browse_needs_a_team_of_the_user_and_a_scope(api, team, neighbours):
    other = neighbours[0]
    assert api.get(f"/api/recipes/browse/?team={other.pk}").status_code == 400
    assert api.get(f"/api/recipes/browse/?team={team.pk}&mine=0").status_code == 400


def test_browse_filters_by_title(api, team, neighbours, system_recipe):
    found = browse(api, team, mine=0, community=1, search="lasa")
    assert set(found) == {"Lasagne alla bolognese"}
