import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts.models import Invitation
from apps.teams.models import Member, Membership


@pytest.fixture
def member(team):
    """A second user of the team, with the plain member role."""
    user = get_user_model().objects.create_user("bob", email="bob@example.com", first_name="Bob")
    membership = Membership.objects.create(user=user, team=team, role=Membership.Role.MEMBER)
    client = APIClient()
    client.force_authenticate(user)
    return membership, client


# -- team profile -----------------------------------------------------------------------------


def test_owners_edit_the_profile_members_only_read_it(api, team, member):
    _, client = member
    url = f"/api/teams/{team.pk}/"
    payload = {"name": "Calcetto", "default_people": {"lunch": 1, "dinner": 4}}
    assert client.get(url).json()["my_role"] == "member"
    assert client.patch(url, payload, format="json").status_code == 403
    response = api.patch(url, payload, format="json")
    assert response.status_code == 200
    assert response.json()["default_people"] == {"lunch": 1, "dinner": 4}
    assert response.json()["my_role"] == "owner"


@pytest.mark.parametrize(
    "people", [{"lunch": -1, "dinner": 2}, {"lunch": 2, "brunch": 1}, {"lunch": "two"}, [2, 3]]
)
def test_default_people_are_validated(api, team, people):
    response = api.patch(f"/api/teams/{team.pk}/", {"default_people": people}, format="json")
    assert response.status_code == 400


def test_teams_cannot_be_deleted_from_the_app(api, team):
    assert api.delete(f"/api/teams/{team.pk}/").status_code == 405


def test_only_owners_edit_the_people_at_the_table(api, team, member):
    _, client = member
    assert (
        client.post("/api/members/", {"team": team.pk, "name": "Leo"}, format="json").status_code
        == 403
    )
    created = api.post(
        "/api/members/", {"team": team.pk, "name": "Leo", "birth_year": 2015}, format="json"
    )
    assert created.status_code == 201
    leo = created.json()["id"]
    assert client.get("/api/members/").json()["count"] == 1  # members can read
    assert client.delete(f"/api/members/{leo}/").status_code == 403
    assert api.delete(f"/api/members/{leo}/").status_code == 204
    assert not Member.objects.exists()


# -- users and roles --------------------------------------------------------------------------


def test_memberships_list_names_roles_and_me(api, team, member):
    rows = api.get(f"/api/memberships/?team={team.pk}").json()["results"]
    assert {(r["name"], r["role"], r["is_me"]) for r in rows} == {
        ("alice", "owner", True),
        ("Bob", "member", False),
    }


def test_owners_change_roles_members_cannot(api, member):
    membership, client = member
    url = f"/api/memberships/{membership.pk}/"
    assert client.patch(url, {"role": "owner"}, format="json").status_code == 403
    assert api.patch(url, {"role": "owner"}, format="json").status_code == 200
    membership.refresh_from_db()
    assert membership.role == "owner"


def test_the_last_owner_cannot_step_down_or_leave(api, user, team):
    mine = Membership.objects.get(user=user, team=team)
    url = f"/api/memberships/{mine.pk}/"
    assert api.patch(url, {"role": "member"}, format="json").status_code == 400
    assert api.delete(url).status_code == 409


def test_members_can_leave_and_owners_can_remove(api, team, member):
    membership, client = member
    assert client.delete(f"/api/memberships/{membership.pk}/").status_code == 204
    other = Membership.objects.create(user=get_user_model().objects.create_user("carl"), team=team)
    assert api.delete(f"/api/memberships/{other.pk}/").status_code == 204
    assert Membership.objects.filter(team=team).count() == 1


def test_members_cannot_remove_someone_else(api, user, team, member):
    _, client = member
    mine = Membership.objects.get(user=user, team=team)
    assert client.delete(f"/api/memberships/{mine.pk}/").status_code == 403


# -- invitations ------------------------------------------------------------------------------


def test_only_owners_see_invitation_tokens(api, team, member):
    _, client = member
    Invitation.objects.create(team=team, note="Nonna")
    [as_owner] = api.get(f"/api/invitations/?team={team.pk}").json()["results"]
    [as_member] = client.get(f"/api/invitations/?team={team.pk}").json()["results"]
    assert as_owner["token"] and as_owner["invited_by_name"] is None
    assert "token" not in as_member and as_member["note"] == "Nonna"


def test_invitation_shows_who_invited_and_who_joined(api, team):
    token = api.post("/api/invitations/", {"team": team.pk}, format="json").json()["token"]
    guest = get_user_model().objects.create_user("dora", first_name="Dora")
    client = APIClient()
    client.force_authenticate(guest)
    client.post(f"/api/invitations/by-token/{token}/")
    [row] = api.get(f"/api/invitations/?team={team.pk}").json()["results"]
    assert (row["state"], row["invited_by_name"], row["accepted_by_name"]) == (
        "accepted",
        "alice",
        "Dora",
    )
