import datetime as dt
import json
from pathlib import Path

import pytest
from django.contrib.auth import get_user_model
from django.test import RequestFactory, override_settings
from django.utils import timezone
from rest_framework.test import APIClient

from apps.accounts.keycloak_admin import (
    client_representation,
    config_from_env,
    realm_representation,
)
from apps.accounts.models import Invitation, OIDCIdentity
from apps.accounts.oidc import (
    KeycloakAuthenticationRequestView,
    KeycloakBackend,
    keycloak_logout_url,
)
from apps.teams.models import Membership, Team

CLAIMS = {"sub": "abc-123", "email": "anna@example.com", "given_name": "Anna"}


# -- OIDC backend -----------------------------------------------------------------------------


def test_first_login_creates_a_user_linked_by_subject(db):
    backend = KeycloakBackend()
    user = backend.create_user(CLAIMS)
    assert user.email == "anna@example.com"
    assert user.first_name == "Anna"
    assert OIDCIdentity.objects.get(user=user).subject == "abc-123"


def test_names_come_from_the_standard_claims(db):
    user = KeycloakBackend().create_user({**CLAIMS, "family_name": "Rossi"})
    assert (user.first_name, user.last_name) == ("Anna", "Rossi")


def test_users_are_matched_by_subject_not_email(db):
    backend = KeycloakBackend()
    backend.create_user(CLAIMS)
    get_user_model().objects.create_user("other", email="anna@example.com")
    assert list(backend.filter_users_by_claims(CLAIMS).values_list("username", flat=True)) == [
        "kc-abc-123"
    ]
    assert not backend.filter_users_by_claims({**CLAIMS, "sub": "different"}).exists()


def test_user_data_comes_from_the_verified_id_token():
    claims = {**CLAIMS, "iss": "https://phone-facing.example:8443/auth/realms/platemates"}
    # No call to Keycloak's userinfo endpoint, which rejects tokens issued for another address.
    assert KeycloakBackend().get_userinfo("access", "id-token", claims) is claims


def test_claims_without_email_are_refused():
    assert not KeycloakBackend().verify_claims({"sub": "x"})


@override_settings(KEYCLOAK_IDENTITY_PROVIDERS={"google": True, "apple": False})
def test_login_request_forwards_language_and_known_providers_only():
    view = KeycloakAuthenticationRequestView()
    request = RequestFactory().get("/oidc/authenticate/", {"lang": "en-GB", "idp": "google"})
    assert view.get_extra_params(request) == {"ui_locales": "en", "kc_idp_hint": "google"}
    request = RequestFactory().get("/oidc/authenticate/", {"idp": "apple"})
    assert "kc_idp_hint" not in view.get_extra_params(request)


def test_signup_opens_the_registration_form():
    request = RequestFactory().get("/oidc/authenticate/", {"signup": "1"})
    assert KeycloakAuthenticationRequestView().get_extra_params(request)["prompt"] == "create"


def test_logout_also_ends_the_keycloak_session():
    request = RequestFactory().get("/oidc/logout/")
    request.session = {"oidc_id_token": "tok"}
    url = keycloak_logout_url(request)
    # Relative: Keycloak is under /auth on the app's own origin, whatever address that is.
    assert url.startswith("/auth/realms/platemates/protocol/openid-connect/logout?")
    assert "id_token_hint=tok" in url
    assert "post_logout_redirect_uri=http%3A%2F%2Ftestserver%2F" in url


# -- /api/me and login options ----------------------------------------------------------------


def test_me_for_anonymous_visitors(db):
    response = APIClient().get("/api/me/")
    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert "csrftoken" in response.cookies


def test_me_lists_the_users_teams(api, team):
    data = api.get("/api/me/").json()
    assert data["authenticated"] is True
    assert data["teams"] == [
        {"id": team.pk, "name": team.name, "role": "owner", "menu_layout": None}
    ]


@override_settings(KEYCLOAK_IDENTITY_PROVIDERS={"google": True, "microsoft": False, "apple": True})
def test_login_options_list_configured_providers(db):
    assert APIClient().get("/api/login-options/").json() == {
        "identity_providers": ["google", "apple"]
    }


# -- invitations ------------------------------------------------------------------------------


@pytest.fixture
def invitee(db):
    user = get_user_model().objects.create_user("bob")
    client = APIClient()
    client.force_authenticate(user)
    return user, client


def test_owner_invites_and_invitee_joins(api, team, invitee):
    user, client = invitee
    created = api.post("/api/invitations/", {"team": team.pk, "note": "Bob"}, format="json")
    assert created.status_code == 201
    token = created.json()["token"]

    preview = client.get(f"/api/invitations/by-token/{token}/").json()
    assert preview == {
        "team_name": team.name,
        "role": "member",
        "state": "pending",
        "expires_at": preview["expires_at"],
    }
    assert client.post(f"/api/invitations/by-token/{token}/").status_code == 200
    assert Membership.objects.filter(user=user, team=team, role="member").exists()
    # Single use.
    assert client.post(f"/api/invitations/by-token/{token}/").status_code == 409


def test_members_cannot_invite(team, invitee):
    user, client = invitee
    Membership.objects.create(user=user, team=team, role=Membership.Role.MEMBER)
    response = client.post("/api/invitations/", {"team": team.pk}, format="json")
    assert response.status_code == 400


def test_cannot_invite_to_someone_elses_team(api, db):
    other = Team.objects.create(name="Other")
    assert api.post("/api/invitations/", {"team": other.pk}, format="json").status_code == 400


def test_expired_and_revoked_invitations_cannot_be_used(api, team, invitee):
    _, client = invitee
    expired = Invitation.objects.create(
        team=team, expires_at=timezone.now() - dt.timedelta(minutes=1)
    )
    assert client.post(f"/api/invitations/by-token/{expired.token}/").json()["state"] == "expired"

    revoked = Invitation.objects.create(team=team)
    assert api.delete(f"/api/invitations/{revoked.pk}/").status_code == 204
    assert client.post(f"/api/invitations/by-token/{revoked.token}/").json()["state"] == "revoked"


def test_unknown_token_is_404(invitee):
    _, client = invitee
    assert client.get("/api/invitations/by-token/nope/").status_code == 404


def test_invitation_tokens_of_other_teams_are_not_listed(api, db):
    Invitation.objects.create(team=Team.objects.create(name="Other"))
    assert api.get("/api/invitations/").json()["count"] == 0


# -- Keycloak configuration -------------------------------------------------------------------

BASE_ENV = {
    "OIDC_RP_CLIENT_SECRET": "s3cret",
    "APP_PUBLIC_URLS": "http://localhost:5173, http://localhost:8080/",
}


def test_only_providers_with_credentials_are_configured(tmp_path: Path):
    (tmp_path / "apple.p8").write_text("-----BEGIN PRIVATE KEY-----\nabc\n")
    config = config_from_env(
        {
            **BASE_ENV,
            "GOOGLE_CLIENT_ID": "g",
            "GOOGLE_CLIENT_SECRET": "gs",
            "MICROSOFT_CLIENT_ID": "m",  # no secret: skipped
            "APPLE_CLIENT_ID": "a",
            "APPLE_TEAM_ID": "t",
            "APPLE_KEY_ID": "k",
            "APPLE_PRIVATE_KEY_FILE": "apple.p8",
        },
        repo_root=tmp_path,
    )
    assert list(config.identity_providers) == ["google", "apple"]
    apple = config.identity_providers["apple"]["config"]
    assert apple["clientSecret"].startswith("-----BEGIN PRIVATE KEY-----")
    assert apple["teamId"] == "t"


def test_client_redirects_to_every_app_url():
    client = client_representation(config_from_env(BASE_ENV))
    assert client["redirectUris"] == [
        "http://localhost:5173/oidc/callback/",
        "http://localhost:8080/oidc/callback/",
    ]
    assert client["publicClient"] is False
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"


def test_email_features_follow_smtp_availability():
    without = realm_representation(config_from_env(BASE_ENV))
    assert without["resetPasswordAllowed"] is False
    assert "smtpServer" not in without
    with_smtp = realm_representation(
        config_from_env({**BASE_ENV, "SMTP_HOST": "smtp.example.com", "SMTP_FROM": "a@b.c"})
    )
    assert with_smtp["resetPasswordAllowed"] is True
    assert with_smtp["verifyEmail"] is True
    assert with_smtp["defaultLocale"] == "it"


def test_missing_client_secret_is_an_error():
    with pytest.raises(ValueError):
        config_from_env({})


# -- per-user language ------------------------------------------------------------------------


def test_language_is_saved_per_user(api):
    assert api.get("/api/me/").json()["user"]["language"] is None
    assert api.patch("/api/me/", {"language": "en-GB"}, format="json").status_code == 200
    assert api.get("/api/me/").json()["user"]["language"] == "en"


def test_theme_is_saved_per_user(api):
    assert api.get("/api/me/").json()["user"]["theme"] == "system"
    assert api.patch("/api/me/", {"theme": "dark"}, format="json").json()["user"]["theme"] == "dark"
    both = api.patch("/api/me/", {"theme": "light", "language": "en"}, format="json").json()
    assert (both["user"]["theme"], both["user"]["language"]) == ("light", "en")


def test_the_menu_layout_is_the_users_then_the_teams(api, team):
    me = api.get("/api/me/").json()
    assert me["user"]["menu_layout"] is None
    assert me["teams"][0]["menu_layout"] is None
    assert me["settings"]["ui.menu_layout"] == "vertical"
    team.menu_layout = "horizontal"
    team.save()
    assert api.get("/api/me/").json()["teams"][0]["menu_layout"] == "horizontal"
    mine = api.patch("/api/me/", {"menu_layout": "vertical"}, format="json").json()
    assert mine["user"]["menu_layout"] == "vertical"
    back = api.patch("/api/me/", {"menu_layout": ""}, format="json").json()
    assert back["user"]["menu_layout"] is None
    assert api.patch("/api/me/", {"menu_layout": "diagonal"}, format="json").status_code == 400


def test_the_shopping_app_is_opt_in_per_user(api):
    assert api.get("/api/me/").json()["user"]["shopping_app"] is None
    chosen = api.patch("/api/me/", {"shopping_app": "listonic"}, format="json").json()
    assert chosen["user"]["shopping_app"] == "listonic"
    none = api.patch("/api/me/", {"shopping_app": ""}, format="json").json()
    assert none["user"]["shopping_app"] is None
    assert api.patch("/api/me/", {"shopping_app": "keep"}, format="json").status_code == 400


@pytest.mark.parametrize("body", [{"theme": "blue"}, {}])
def test_bad_theme_changes_are_rejected(api, body):
    assert api.patch("/api/me/", body, format="json").status_code == 400


def test_unsupported_language_is_rejected(api):
    assert api.patch("/api/me/", {"language": "klingon"}, format="json").status_code == 400


def test_anonymous_cannot_save_a_language(db):
    assert APIClient().patch("/api/me/", {"language": "it"}, format="json").status_code == 403


def test_the_admin_role_follows_the_id_token_at_every_login(db):
    from apps.accounts.oidc import KeycloakBackend

    backend = KeycloakBackend()
    claims = {"sub": "s-1", "email": "ada@example.com", "roles": ["admin", "offline_access"]}
    user = backend.create_user(claims)
    user.profile.refresh_from_db()
    assert user.profile.is_admin is True
    backend.update_user(user, {**claims, "roles": ["offline_access"]})
    user.profile.refresh_from_db()
    assert user.profile.is_admin is False


def test_language_chosen_at_keycloak_is_adopted_on_first_login(db):
    from apps.accounts.models import UserProfile

    user = KeycloakBackend().create_user({**CLAIMS, "locale": "en"})
    assert UserProfile.of(user).language == "en"


# -- repeatable initialization ----------------------------------------------------------------


def test_create_team_is_idempotent(db):
    from django.core.management import call_command

    get_user_model().objects.create_user("owner", email="owner@example.com")
    for _ in range(2):
        call_command("create_team", "Rossi", owner="owner@example.com", staff=True)
    assert Team.objects.filter(name="Rossi").count() == 1
    assert get_user_model().objects.get(username="owner").is_superuser


class FakeKeycloak:
    """Just enough of Keycloak's admin API to check that `apply` converges."""

    def __init__(self, providers=(), users=(), admins=()):
        self.realms = set()
        self.clients = {}
        self.providers = {alias: {} for alias in providers}
        self.mappers = {}
        self.roles = set()
        # email -> id; and the ids holding the admin role.
        self.users = {email: f"u-{email}" for email in users}
        self.admins = {self.users[email] for email in admins}
        self.calls = []
        self.default_role = {"id": "d1", "name": "default-roles-platemates", "composite": True}

    def __call__(self, request):
        import httpx

        method, path = request.method, request.url.path
        self.calls.append((method, path))
        if path.endswith("/openid-connect/token"):
            return httpx.Response(200, json={"access_token": "t"})
        parts = path.removeprefix("/admin/realms").strip("/").split("/")
        body = json.loads(request.read() or "null")
        if parts == [""]:
            self.realms.add("platemates")
            return httpx.Response(201)
        if len(parts) == 1:
            if method == "GET":
                found = parts[0] in self.realms
                return httpx.Response(
                    200 if found else 404, json={"defaultRole": self.default_role}
                )
            return httpx.Response(204)
        if parts[1] == "roles-by-id":
            self.default_role = {**self.default_role, "name": body["name"]}
            return httpx.Response(204)
        if parts[1] == "clients":
            if "protocol-mappers" in parts:
                mappers = self.mappers.setdefault(parts[2], {})
                if method == "GET":
                    return httpx.Response(200, json=list(mappers.values()))
                if method == "POST":
                    mappers[body["name"]] = {**body, "id": f"m-{parts[2]}"}
                    return httpx.Response(201)
                return httpx.Response(204)
            if method == "GET":
                wanted = request.url.params.get("clientId")
                found = [c for c in self.clients.values() if c["clientId"] == wanted]
                return httpx.Response(200, json=found)
            if method == "POST":
                self.clients[body["clientId"]] = {"id": f"id-{body['clientId']}", **body}
                return httpx.Response(201)
            if method == "DELETE":
                self.clients = {k: c for k, c in self.clients.items() if c["id"] != parts[2]}
            return httpx.Response(204)
        if parts[1] == "roles":
            if method == "POST":
                self.roles.add(body["name"])
                return httpx.Response(201)
            if len(parts) == 4 and parts[3] == "users":
                holders = [{"id": i, "email": e} for e, i in self.users.items() if i in self.admins]
                return httpx.Response(200, json=holders)
            exists = parts[2] in self.roles
            return httpx.Response(200 if exists else 404, json={"name": parts[2], "id": "r"})
        if parts[1] == "users":
            if len(parts) == 2:
                email = request.url.params.get("email")
                found = [{"id": self.users[email]}] if email in self.users else []
                return httpx.Response(200, json=found)
            if method == "POST":
                self.admins.add(parts[2])
            elif method == "DELETE":
                self.admins.discard(parts[2])
            return httpx.Response(204)
        alias = parts[-1]
        if method == "GET":
            return httpx.Response(200 if alias in self.providers else 404, json={})
        if method == "POST":
            self.providers[body["alias"]] = {}
            return httpx.Response(201)
        if method == "DELETE":
            self.providers.pop(alias)
        return httpx.Response(204)


def run_setup(fake, env):
    import httpx

    from apps.accounts.keycloak_admin import KeycloakAdmin

    client = httpx.Client(base_url="http://kc", transport=httpx.MockTransport(fake))
    return KeycloakAdmin("http://kc", "admin", "pw", client=client).apply(config_from_env(env))


def test_setup_keycloak_converges(db):
    fake = FakeKeycloak()
    google = {**BASE_ENV, "GOOGLE_CLIENT_ID": "g", "GOOGLE_CLIENT_SECRET": "gs"}

    first = run_setup(fake, google)
    assert "created realm platemates" in first
    assert "created client platemates-backend" in first
    assert "created identity provider google" in first

    second = run_setup(fake, google)
    assert not [line for line in second if line.startswith("created")]
    assert set(fake.providers) == {"google"}

    # Credentials removed from .env: the provider goes away in Keycloak too.
    third = run_setup(fake, BASE_ENV)
    assert "removed identity provider google (no credentials in .env)" in third
    assert fake.providers == {}


def test_setup_keycloak_names_the_default_role_after_the_realm(db):
    fake = FakeKeycloak()
    fake.default_role["name"] = "default-roles-mymenu"  # a realm renamed in place
    assert "renamed role default-roles-mymenu to default-roles-platemates" in run_setup(
        fake, BASE_ENV
    )
    assert fake.default_role["name"] == "default-roles-platemates"
    assert not [line for line in run_setup(fake, BASE_ENV) if line.startswith("renamed")]


def test_setup_keycloak_puts_roles_in_the_id_token(db):
    fake = FakeKeycloak()
    added = "added the realm roles to platemates-backend's tokens"
    assert added in run_setup(fake, BASE_ENV)
    mappers = fake.mappers["id-platemates-backend"]
    assert mappers["realm roles"]["config"]["id.token.claim"] == "true"
    assert added not in run_setup(fake, BASE_ENV)


def test_setup_keycloak_manages_grafana_only_with_a_secret(db):
    fake = FakeKeycloak()
    grafana = {
        **BASE_ENV,
        "GRAFANA_OIDC_CLIENT_SECRET": "gs",
        "GRAFANA_URLS": "https://admin.example.com:9443/grafana/",
    }
    assert "created client platemates-grafana" in run_setup(fake, grafana)
    client = fake.clients["platemates-grafana"]
    assert client["redirectUris"] == ["https://admin.example.com:9443/grafana/login/generic_oauth"]
    assert "realm roles" in fake.mappers["id-platemates-grafana"]
    assert "updated client platemates-grafana" in run_setup(fake, grafana)
    # Its secret removed from .env: the client goes away.
    assert "removed client platemates-grafana (no secret in .env)" in run_setup(fake, BASE_ENV)
    assert set(fake.clients) == {"platemates-backend"}


def test_setup_keycloak_gives_the_admin_role_to_exactly_app_admins(db):
    fake = FakeKeycloak(users=["ada@example.com", "bea@example.com"], admins=["bea@example.com"])
    env = {**BASE_ENV, "APP_ADMINS": " Ada@Example.com , new@example.com"}
    log = run_setup(fake, env)
    assert "created role admin" in log
    assert "gave role admin to ada@example.com" in log
    assert "removed role admin from bea@example.com" in log
    assert any(line.startswith("new@example.com has no account yet") for line in log)
    assert fake.admins == {"u-ada@example.com"}
    again = run_setup(fake, env)
    assert not [line for line in again if "role admin" in line]


def test_init_env_fills_gaps_and_never_overwrites(tmp_path):
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "init_env", Path(__file__).resolve().parents[2] / "scripts" / "init_env.py"
    )
    init_env = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(init_env)

    example = tmp_path / ".env.example"
    target = tmp_path / ".env"
    example.write_text("LLM_API_KEY=\nOIDC_RP_CLIENT_SECRET=\nDJANGO_DEBUG=true\n")

    assert "created .env from .env.example" in init_env.init_env(example, target)
    secret = init_env.parse(target.read_text().splitlines())["OIDC_RP_CLIENT_SECRET"]
    assert len(secret) > 20

    target.write_text(target.read_text().replace("DJANGO_DEBUG=true", "DJANGO_DEBUG=false"))
    example.write_text(example.read_text() + "NEW_SETTING=1\n")
    assert init_env.init_env(example, target) == ["added NEW_SETTING"]
    values = init_env.parse(target.read_text().splitlines())
    assert values["OIDC_RP_CLIENT_SECRET"] == secret
    assert values["DJANGO_DEBUG"] == "false"
    assert values["LLM_API_KEY"] == ""

    assert init_env.init_env(example, target) == []


def test_admin_login_waits_for_keycloak_to_be_ready():
    import httpx

    from apps.accounts.keycloak_admin import KeycloakAdmin

    answers = iter([httpx.ConnectError("down"), 503, 503, 200])

    def handler(request):
        answer = next(answers)
        if isinstance(answer, Exception):
            raise answer
        return httpx.Response(answer, json={"access_token": "t"} if answer == 200 else {})

    client = httpx.Client(base_url="http://kc", transport=httpx.MockTransport(handler))
    sleeps = []
    KeycloakAdmin("http://kc", "admin", "pw", client=client, sleep=sleeps.append)
    assert len(sleeps) == 3


def test_admin_login_fails_fast_on_wrong_credentials():
    import httpx

    from apps.accounts.keycloak_admin import KeycloakAdmin, KeycloakAdminError

    client = httpx.Client(
        base_url="http://kc", transport=httpx.MockTransport(lambda r: httpx.Response(401))
    )
    with pytest.raises(KeycloakAdminError, match="KEYCLOAK_ADMIN_PASSWORD"):
        KeycloakAdmin("http://kc", "admin", "pw", client=client, sleep=lambda s: None)
