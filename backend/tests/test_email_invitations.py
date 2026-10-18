import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.accounts import views
from apps.accounts.models import Invitation, UserProfile
from apps.accounts.serializers import mask_email
from apps.teams.models import Membership


def signed_in(username, email, verified=True):
    user = get_user_model().objects.create_user(username, email=email, first_name=username.title())
    UserProfile.objects.update_or_create(user=user, defaults={"email_verified": verified})
    client = APIClient()
    client.force_authenticate(user)
    return user, client


@pytest.fixture
def owner(user):
    user.first_name, user.last_name, user.email = "Alice", "Rossi", "alice@example.com"
    user.save()
    return user


def invite(api, team, email, **extra):
    return api.post("/api/invitations/", {"team": team.pk, "email": email, **extra}, format="json")


def test_an_invitation_by_email_says_who_invites_to_which_team(api, team, owner, mailoutbox):
    response = invite(api, team, " Dora@Example.com ", message="Vieni a cena!")
    assert response.status_code == 201
    assert response.json()["email_sent"] is True
    assert response.json()["email"] == "dora@example.com"
    [mail] = mailoutbox
    assert mail.to == ["dora@example.com"]
    html = mail.alternatives[0][0]
    token = response.json()["token"]
    for text in ("Alice Rossi", "alice@example.com", "Test team", f"/invite/{token}", "cena"):
        assert text in mail.body and text in html


def test_a_plain_link_sends_nothing(api, team, mailoutbox):
    response = api.post("/api/invitations/", {"team": team.pk}, format="json")
    assert response.status_code == 201 and response.json()["email_sent"] is None
    assert mailoutbox == []


def test_members_see_neither_token_nor_address(api, team, member):
    invite(api, team, "dora@example.com")
    _, client = member
    [row] = client.get(f"/api/invitations/?team={team.pk}").json()["results"]
    assert "token" not in row and "email" not in row


def test_members_cannot_invite_by_email(team, member, mailoutbox):
    _, client = member
    assert invite(client, team, "dora@example.com").status_code == 400
    assert mailoutbox == []


def test_emailed_invitations_have_a_daily_ceiling(api, team, monkeypatch, mailoutbox):
    monkeypatch.setattr(views, "INVITATION_EMAILS_PER_DAY", 2)
    assert invite(api, team, "a@example.com").status_code == 201
    assert invite(api, team, "b@example.com").status_code == 201
    refused = invite(api, team, "c@example.com")
    assert refused.status_code == 400 and len(mailoutbox) == 2
    # Links to hand out are not mail, so not counted.
    assert api.post("/api/invitations/", {"team": team.pk}, format="json").status_code == 201


def test_resend(api, team, member, mailoutbox):
    pk = invite(api, team, "dora@example.com").json()["id"]
    response = api.post(f"/api/invitations/{pk}/resend/")
    assert response.status_code == 200 and response.json() == {"email_sent": True}
    assert len(mailoutbox) == 2
    _, client = member
    assert client.post(f"/api/invitations/{pk}/resend/").status_code in (400, 403)
    link = api.post("/api/invitations/", {"team": team.pk}, format="json").json()["id"]
    assert api.post(f"/api/invitations/{link}/resend/").status_code == 400


def test_only_the_addressee_accepts(api, team):
    token = invite(api, team, "dora@example.com").json()["token"]
    _, stranger = signed_in("eve", "eve@example.com")
    refused = stranger.post(f"/api/invitations/by-token/{token}/")
    assert refused.status_code == 409
    assert refused.json() == {"code": "wrong_account", "email_hint": "d***a@example.com"}
    # The right address, not yet verified, is not enough either.
    _, unverified = signed_in("dora2", "DORA@example.com", verified=False)
    assert unverified.post(f"/api/invitations/by-token/{token}/").status_code == 409
    dora, client = signed_in("dora", "Dora@Example.com")
    assert client.post(f"/api/invitations/by-token/{token}/").status_code in (200, 201)
    assert Membership.objects.filter(user=dora, team=team).exists()


def test_the_preview_hints_at_the_address(api, team):
    token = invite(api, team, "dora@example.com").json()["token"]
    preview = APIClient().get(f"/api/invitations/by-token/{token}/").json()
    assert preview["email_hint"] == "d***a@example.com"
    assert "dora@example.com" not in str(preview)


def test_mine_lists_pending_invitations_to_my_verified_address(api, team, owner):
    invite(api, team, "dora@example.com")
    api.post("/api/invitations/", {"team": team.pk}, format="json")
    revoked = Invitation.objects.create(team=team, email="dora@example.com")
    api.delete(f"/api/invitations/{revoked.pk}/")
    _, client = signed_in("dora", "dora@example.com")
    [row] = client.get("/api/invitations/mine/").json()
    assert (row["team_name"], row["invited_by_name"]) == ("Test team", "Alice Rossi")
    assert row["token"]
    _, unverified = signed_in("dora2", "dora@example.com", verified=False)
    assert unverified.get("/api/invitations/mine/").json() == []


@pytest.mark.parametrize(
    ("email", "masked"),
    [("paola.rossi@gmail.com", "p***i@gmail.com"), ("x@a.it", "x***@a.it"), ("nope", "")],
)
def test_mask_email(email, masked):
    assert mask_email(email) == masked
