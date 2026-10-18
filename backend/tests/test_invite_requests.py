"""Asking for an invitation from the sign-in page, and the invitation's own sign-in page."""

import pytest
from django.core.cache import cache
from rest_framework.test import APIClient

from apps.accounts import invite_requests
from apps.accounts.models import Invitation, InviteRequest, UserProfile

URL = "/api/request-invite/"


@pytest.fixture(autouse=True)
def fresh_throttle():
    cache.clear()


@pytest.fixture
def anonymous(db):
    return APIClient()


def test_anyone_asks_for_an_invitation(anonymous):
    body = {"email": " Ada@Example.com ", "name": "Ada  Lovelace", "message": "Ciao"}
    response = anonymous.post(URL, body, format="json", HTTP_ACCEPT_LANGUAGE="en-GB")
    assert response.status_code == 204
    request = InviteRequest.objects.get()
    assert (request.email, request.name, request.language) == (
        "ada@example.com",
        "Ada Lovelace",
        "en",
    )
    assert request.status == "pending"


def test_the_same_address_waits_once_and_the_answer_says_nothing(anonymous):
    for _ in range(2):
        assert anonymous.post(URL, {"email": "ada@example.com"}, format="json").status_code == 204
    assert InviteRequest.objects.count() == 1


def test_bots_filling_the_hidden_field_are_dropped(anonymous):
    body = {"email": "bot@example.com", "website": "http://spam"}
    assert anonymous.post(URL, body, format="json").status_code == 204
    assert not InviteRequest.objects.exists()


def test_a_full_queue_takes_no_more(anonymous, monkeypatch):
    monkeypatch.setattr(invite_requests, "MAX_PENDING", 1)
    anonymous.post(URL, {"email": "a@example.com"}, format="json")
    anonymous.post(URL, {"email": "b@example.com"}, format="json")
    assert InviteRequest.objects.count() == 1


def test_requests_are_rate_limited(anonymous):
    for i in range(5):
        anonymous.post(URL, {"email": f"u{i}@example.com"}, format="json")
    assert anonymous.post(URL, {"email": "u9@example.com"}, format="json").status_code == 429


def test_through_cloudflare_each_visitor_has_their_own_limit(anonymous):
    for i in range(5):
        anonymous.post(
            URL, {"email": f"a{i}@example.com"}, format="json", HTTP_CF_CONNECTING_IP="203.0.113.1"
        )
    blocked = anonymous.post(
        URL, {"email": "a9@example.com"}, format="json", HTTP_CF_CONNECTING_IP="203.0.113.1"
    )
    other = anonymous.post(
        URL, {"email": "b9@example.com"}, format="json", HTTP_CF_CONNECTING_IP="203.0.113.2"
    )
    assert (blocked.status_code, other.status_code) == (429, 204)


def test_a_bad_address_is_refused(anonymous):
    assert anonymous.post(URL, {"email": "not-an-email"}, format="json").status_code == 400


def test_administrators_deal_with_the_requests(api, user, anonymous):
    anonymous.post(URL, {"email": "ada@example.com"}, format="json")
    assert api.get("/api/invite-requests/").status_code == 403
    UserProfile.objects.create(user=user, is_admin=True)
    [request] = api.get("/api/invite-requests/?status=pending").json()["results"]
    handled = api.patch(
        f"/api/invite-requests/{request['id']}/", {"status": "handled"}, format="json"
    )
    assert handled.json()["status"] == "handled" and handled.json()["handled_at"]
    assert api.get("/api/invite-requests/?status=pending").json()["results"] == []
    reopened = api.patch(
        f"/api/invite-requests/{request['id']}/", {"status": "pending"}, format="json"
    )
    assert reopened.json()["handled_at"] is None
    email = api.patch(f"/api/invite-requests/{request['id']}/", {"email": "x@y.it"}, format="json")
    assert email.json()["email"] == "ada@example.com"  # only the status changes


def test_an_invitation_says_who_and_which_team_before_signing_in(user, team, anonymous):
    user.first_name, user.last_name = "Paola", "Rossi"
    user.save()
    invitation = Invitation.objects.create(team=team, invited_by=user)
    url = f"/api/invitations/by-token/{invitation.token}/"
    preview = anonymous.get(url).json()
    assert preview["team_name"] == team.name
    assert preview["invited_by_name"] == "Paola Rossi"
    assert preview["state"] == "pending"
    # By name only: nothing else about who sent it.
    assert set(preview) == {"team_name", "invited_by_name", "role", "state", "expires_at"}
    assert anonymous.post(url).status_code == 403  # accepting needs signing in
