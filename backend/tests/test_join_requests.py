"""A signed-in user without a team asking a team owner to be let in, or the administrators
for a team of their own; and the invitation's own sign-in page."""

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts import team_requests
from apps.accounts.models import AccessRequest, Invitation, InviteRequest, UserProfile
from apps.teams.models import Membership, Team


def signed_in(username, email, *, verified=True, language=""):
    user = get_user_model().objects.create_user(username, email=email, first_name=username.title())
    UserProfile.objects.update_or_create(
        user=user, defaults={"email_verified": verified, "language": language}
    )
    client = APIClient()
    client.force_authenticate(user)
    return user, client


@pytest.fixture
def owner(user, team):
    user.email = "alice@example.com"
    user.save()
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": True})
    return user


@pytest.fixture
def newcomer(db):
    return signed_in("dora", "dora@example.com", language="en")


@pytest.fixture
def admin(user):
    UserProfile.objects.update_or_create(user=user, defaults={"is_admin": True})


def ask_owner(client, email, **extra):
    return client.post("/api/access-requests/", {"owner_email": email, **extra}, format="json")


def ask_team(client, name, **extra):
    return client.post("/api/team-requests/", {"team_name": name, **extra}, format="json")


# -- asking an owner ---------------------------------------------------------------------------


def test_an_owner_receives_the_request_and_accepts_it(api, team, owner, newcomer, mailoutbox):
    dora, client = newcomer
    response = ask_owner(client, " Alice@Example.com ", message="Sono la cugina")
    assert response.status_code == 201 and response.json()["status"] == "pending"
    [mail] = mailoutbox
    assert mail.to == ["alice@example.com"]
    assert "dora@example.com" in mail.body and "Sono la cugina" in mail.body
    [received] = api.get("/api/access-requests/received/").json()
    assert (received["requester_email"], received["message"]) == (
        "dora@example.com",
        "Sono la cugina",
    )
    accepted = api.post(f"/api/access-requests/{received['id']}/accept/", {"team": team.pk})
    assert accepted.status_code == 200
    assert Membership.objects.get(user=dora, team=team).role == "member"
    assert mailoutbox[-1].to == ["dora@example.com"] and "Test team" in mailoutbox[-1].subject
    [mine] = client.get("/api/access-requests/").json()
    assert (mine["status"], mine["team_name"]) == ("accepted", "Test team")
    assert api.get("/api/access-requests/received/").json() == []


def test_an_unknown_address_looks_the_same_to_the_requester(owner, newcomer, mailoutbox):
    _, client = newcomer
    for email in ("nobody@example.com", "alice@example.com"):
        response = ask_owner(client, email)
        assert response.status_code == 201 and response.json()["status"] == "pending"
        assert set(response.json()) == {
            "id",
            "owner_email",
            "message",
            "status",
            "team_name",
            "created_at",
        }
    assert [m.to for m in mailoutbox] == [["alice@example.com"]]
    assert AccessRequest.objects.get(owner_email="nobody@example.com").owner is None


def test_a_member_or_an_unverified_address_is_not_an_owner(team, member, newcomer, mailoutbox):
    signed_in("carl", "carl@example.com", verified=False)
    carl = get_user_model().objects.get(username="carl")
    Membership.objects.create(user=carl, team=Team.objects.create(name="Other"), role="owner")
    _, client = newcomer
    ask_owner(client, "bob@example.com")  # bob is a plain member
    ask_owner(client, "carl@example.com")  # owner, but the address is not verified
    assert mailoutbox == []


def test_the_owner_declines(api, owner, newcomer, mailoutbox):
    _, client = newcomer
    ask_owner(client, "alice@example.com")
    [received] = api.get("/api/access-requests/received/").json()
    assert api.post(f"/api/access-requests/{received['id']}/decline/").status_code == 204
    assert mailoutbox[-1].to == ["dora@example.com"]
    assert "not accepted" in mailoutbox[-1].body  # in the requester's language
    assert client.get("/api/access-requests/").json()[0]["status"] == "declined"


def test_only_the_addressed_owner_answers_into_their_own_team(api, team, owner, newcomer, member):
    _, client = newcomer
    pk = ask_owner(client, "alice@example.com").json()["id"]
    _, bob = member
    assert bob.post(f"/api/access-requests/{pk}/accept/", {"team": team.pk}).status_code == 404
    assert client.post(f"/api/access-requests/{pk}/accept/", {"team": team.pk}).status_code == 404
    elsewhere = Team.objects.create(name="Not hers")
    refused = api.post(f"/api/access-requests/{pk}/accept/", {"team": elsewhere.pk})
    assert refused.status_code == 400


def test_asking_twice_and_withdrawing(owner, newcomer):
    _, client = newcomer
    pk = ask_owner(client, "alice@example.com").json()["id"]
    assert ask_owner(client, "alice@example.com").status_code == 400
    assert client.delete(f"/api/access-requests/{pk}/").status_code == 204
    assert ask_owner(client, "alice@example.com").status_code == 201


def test_requests_have_a_daily_ceiling(newcomer, monkeypatch):
    monkeypatch.setattr(team_requests, "REQUESTS_PER_DAY", 2)
    _, client = newcomer
    assert ask_owner(client, "a@example.com").status_code == 201
    assert ask_team(client, "Casa").status_code == 201
    refused = ask_owner(client, "b@example.com")
    assert refused.status_code == 400 and refused.json()["code"] == "too_many"


# -- asking for a team -------------------------------------------------------------------------


def test_asking_for_a_team_and_the_administrator_creates_it(api, admin, newcomer, mailoutbox):
    dora, client = newcomer
    response = ask_team(client, "  Casa   Dora ", message="Per me e mia sorella")
    assert response.status_code == 201
    assert response.json()["team_name"] == "Casa Dora"
    assert ask_team(client, "Another").status_code == 400  # one waiting at a time
    [row] = api.get("/api/invite-requests/?status=pending").json()["results"]
    assert (row["email"], row["name"], row["team_name"]) == (
        "dora@example.com",
        "Dora",
        "Casa Dora",
    )
    created = api.post(f"/api/invite-requests/{row['id']}/create-team/", {"name": "Casa Dora"})
    assert created.status_code == 201 and created.json()["status"] == "handled"
    team = Team.objects.get(name="Casa Dora")
    assert Membership.objects.get(user=dora, team=team).role == "owner"
    assert mailoutbox[-1].to == ["dora@example.com"] and "Casa Dora" in mailoutbox[-1].subject
    [mine] = client.get("/api/team-requests/").json()
    assert (mine["status"], mine["created_team_name"]) == ("handled", "Casa Dora")
    again = api.post(f"/api/invite-requests/{row['id']}/create-team/")
    assert again.status_code == 400 and Team.objects.filter(name="Casa Dora").count() == 1


def test_a_dismissed_request_tells_the_requester(api, admin, newcomer, mailoutbox):
    _, client = newcomer
    pk = ask_team(client, "Casa").json()["id"]
    api.patch(f"/api/invite-requests/{pk}/", {"status": "dismissed"}, format="json")
    assert mailoutbox[-1].to == ["dora@example.com"] and "Casa" in mailoutbox[-1].body
    assert client.get("/api/team-requests/").json()[0]["status"] == "dismissed"


def test_only_administrators_deal_with_team_requests(api, newcomer):
    _, client = newcomer
    pk = ask_team(client, "Casa").json()["id"]
    assert api.get("/api/invite-requests/").status_code == 403
    assert client.post(f"/api/invite-requests/{pk}/create-team/").status_code == 403
    assert client.patch(f"/api/team-requests/{pk}/", {"team_name": "X"}).status_code == 405


def test_administrators_reopen_and_change_only_the_status(api, admin, newcomer):
    _, client = newcomer
    pk = ask_team(client, "Casa").json()["id"]
    handled = api.patch(f"/api/invite-requests/{pk}/", {"status": "handled"}, format="json")
    assert handled.json()["status"] == "handled" and handled.json()["handled_at"]
    reopened = api.patch(f"/api/invite-requests/{pk}/", {"status": "pending"}, format="json")
    assert reopened.json()["handled_at"] is None
    email = api.patch(f"/api/invite-requests/{pk}/", {"email": "x@y.it"}, format="json")
    assert email.json()["email"] == "dora@example.com"


def test_requesting_needs_signing_in(db):
    assert APIClient().post("/api/team-requests/", {"team_name": "X"}).status_code == 403
    assert APIClient().post("/api/access-requests/", {"owner_email": "a@b.it"}).status_code == 403
    assert APIClient().post("/api/request-invite/", {"email": "a@b.it"}).status_code == 404


# -- the invitation's page ---------------------------------------------------------------------


def test_an_invitation_says_who_and_which_team_before_signing_in(user, team):
    user.first_name, user.last_name = "Paola", "Rossi"
    user.save()
    invitation = Invitation.objects.create(team=team, invited_by=user)
    url = f"/api/invitations/by-token/{invitation.token}/"
    anonymous = APIClient()
    preview = anonymous.get(url).json()
    assert preview["team_name"] == team.name
    assert preview["invited_by_name"] == "Paola Rossi"
    assert preview["state"] == "pending"
    # By name only: nothing else about who sent it.
    assert set(preview) == {
        "team_name",
        "invited_by_name",
        "email_hint",
        "role",
        "state",
        "expires_at",
    }
    assert anonymous.post(url).status_code == 403  # accepting needs signing in


def test_old_anonymous_requests_still_list(api, admin):
    InviteRequest.objects.create(email="old@example.com")
    [row] = api.get("/api/invite-requests/").json()["results"]
    assert (row["email"], row["team_name"]) == ("old@example.com", "")
