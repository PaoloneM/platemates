"""Configure the Keycloak realm from the environment, through Keycloak's admin REST API.

Everything Keycloak needs to know about this application is derived here from `.env`, so a fresh
Keycloak becomes usable with one command (`manage.py setup_keycloak`) and the realm is never
configured by hand. The command is idempotent and convergent: running it again changes nothing,
and running it after editing `.env` brings Keycloak in line, including removing an identity
provider whose credentials were removed. The `*_representation` functions are pure and hold all
the decisions; `KeycloakAdmin` only moves them over HTTP.
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx

LOGIN_THEME = "platemates"
# Identity providers this module owns. Any of them present in Keycloak but no longer configured
# in `.env` is removed; providers added by hand under other aliases are left alone.
MANAGED_IDENTITY_PROVIDERS = ("google", "microsoft", "apple")
SUPPORTED_LOCALES = ["it", "en"]
DEFAULT_LOCALE = "it"


@dataclass(frozen=True)
class SmtpConfig:
    host: str
    port: str
    sender: str
    user: str = ""
    password: str = ""
    starttls: bool = True


@dataclass(frozen=True)
class KeycloakConfig:
    realm: str
    client_id: str
    client_secret: str
    app_urls: list[str]
    smtp: SmtpConfig | None = None
    # alias -> Keycloak identity provider representation (only providers with credentials).
    identity_providers: dict[str, dict[str, Any]] = field(default_factory=dict)


def config_from_env(
    env: dict[str, str] | None = None, repo_root: Path | None = None
) -> KeycloakConfig:
    env = dict(os.environ if env is None else env)
    get = lambda name, default="": (env.get(name) or default).strip()  # noqa: E731

    smtp = None
    if get("SMTP_HOST"):
        smtp = SmtpConfig(
            host=get("SMTP_HOST"),
            port=get("SMTP_PORT", "587"),
            sender=get("SMTP_FROM"),
            user=get("SMTP_USER"),
            password=get("SMTP_PASSWORD"),
            starttls=get("SMTP_STARTTLS", "true").lower() in {"1", "true", "yes", "on"},
        )

    providers: dict[str, dict[str, Any]] = {}
    if get("GOOGLE_CLIENT_ID") and get("GOOGLE_CLIENT_SECRET"):
        providers["google"] = identity_provider_representation(
            "google",
            "Google",
            {"clientId": get("GOOGLE_CLIENT_ID"), "clientSecret": get("GOOGLE_CLIENT_SECRET")},
        )
    if get("MICROSOFT_CLIENT_ID") and get("MICROSOFT_CLIENT_SECRET"):
        providers["microsoft"] = identity_provider_representation(
            "microsoft",
            "Microsoft",
            {
                "clientId": get("MICROSOFT_CLIENT_ID"),
                "clientSecret": get("MICROSOFT_CLIENT_SECRET"),
            },
        )
    apple_key_file = get("APPLE_PRIVATE_KEY_FILE")
    if get("APPLE_CLIENT_ID") and get("APPLE_TEAM_ID") and get("APPLE_KEY_ID") and apple_key_file:
        key_path = Path(apple_key_file)
        if not key_path.is_absolute():
            key_path = (repo_root or Path.cwd()) / key_path
        providers["apple"] = identity_provider_representation(
            "apple",
            "Apple",
            {
                "clientId": get("APPLE_CLIENT_ID"),
                # The community Apple provider takes the raw .p8 key as its client secret.
                "clientSecret": key_path.read_text().strip(),
                "teamId": get("APPLE_TEAM_ID"),
                "keyId": get("APPLE_KEY_ID"),
            },
        )

    secret = get("OIDC_RP_CLIENT_SECRET")
    if not secret:
        raise ValueError("OIDC_RP_CLIENT_SECRET is not set.")
    return KeycloakConfig(
        realm=get("KEYCLOAK_REALM", "platemates"),
        client_id=get("OIDC_RP_CLIENT_ID", "platemates-backend"),
        client_secret=secret,
        app_urls=[u.strip().rstrip("/") for u in get("APP_PUBLIC_URLS").split(",") if u.strip()],
        smtp=smtp,
        identity_providers=providers,
    )


def realm_representation(config: KeycloakConfig) -> dict[str, Any]:
    has_email = config.smtp is not None
    realm: dict[str, Any] = {
        "realm": config.realm,
        "enabled": True,
        "displayName": "PlateMates",
        "loginTheme": LOGIN_THEME,
        "internationalizationEnabled": True,
        "supportedLocales": SUPPORTED_LOCALES,
        "defaultLocale": DEFAULT_LOCALE,
        # Anyone may create an account: getting into a team still takes an invitation, which
        # the application enforces. Registration is what lets an invitee without a Google,
        # Microsoft or Apple account sign up with email and password.
        "registrationAllowed": True,
        "registrationEmailAsUsername": True,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "rememberMe": True,
        # Both need outgoing email; without SMTP they would lock users out.
        "resetPasswordAllowed": has_email,
        "verifyEmail": has_email,
        "bruteForceProtected": True,
    }
    if config.smtp:
        smtp = config.smtp
        realm["smtpServer"] = {
            "host": smtp.host,
            "port": smtp.port,
            "from": smtp.sender,
            "fromDisplayName": "PlateMates",
            "starttls": str(smtp.starttls).lower(),
            "auth": str(bool(smtp.user)).lower(),
            "user": smtp.user,
            "password": smtp.password,
        }
    return realm


def client_representation(config: KeycloakConfig) -> dict[str, Any]:
    return {
        "clientId": config.client_id,
        "name": "PlateMates backend",
        "protocol": "openid-connect",
        "enabled": True,
        "publicClient": False,
        "clientAuthenticatorType": "client-secret",
        "secret": config.client_secret,
        "standardFlowEnabled": True,
        "directAccessGrantsEnabled": False,
        "implicitFlowEnabled": False,
        "serviceAccountsEnabled": False,
        "redirectUris": [f"{url}/oidc/callback/" for url in config.app_urls],
        # The browser never calls Keycloak with JavaScript, so no CORS origins are needed.
        "webOrigins": [],
        "attributes": {
            "pkce.code.challenge.method": "S256",
            "post.logout.redirect.uris": "##".join(f"{url}/" for url in config.app_urls),
        },
    }


def identity_provider_representation(
    provider_id: str, display_name: str, config: dict[str, str]
) -> dict[str, Any]:
    return {
        "alias": provider_id,
        "providerId": provider_id,
        "displayName": display_name,
        "enabled": True,
        # These providers verify email addresses themselves.
        "trustEmail": True,
        "storeToken": False,
        "firstBrokerLoginFlowAlias": "first broker login",
        "config": {"syncMode": "IMPORT", **config},
    }


class KeycloakAdminError(RuntimeError):
    pass


class KeycloakAdmin:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        client: httpx.Client | None = None,
        wait_seconds: float = 90,
        sleep=time.sleep,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(base_url=self._base_url, timeout=30)
        self._headers = {
            "Authorization": f"Bearer {self._login(username, password, wait_seconds, sleep)}"
        }

    def _login(self, username: str, password: str, wait_seconds: float, sleep) -> str:
        """Get an admin token, waiting while Keycloak is still starting.

        Keycloak can pass its readiness check and still answer 503 for a few seconds (seen right
        after a restart), so connection errors and 5xx are retried until `wait_seconds` elapse.
        Wrong credentials (4xx) fail at once.
        """
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                response = self._client.post(
                    "/realms/master/protocol/openid-connect/token",
                    data={
                        "grant_type": "password",
                        "client_id": "admin-cli",
                        "username": username,
                        "password": password,
                    },
                )
                if response.is_success:
                    return response.json()["access_token"]
                if response.status_code < 500:
                    raise KeycloakAdminError(
                        f"Keycloak admin login failed ({response.status_code}): check "
                        "KEYCLOAK_ADMIN and KEYCLOAK_ADMIN_PASSWORD. Keycloak reads them only on "
                        "its very first start; if they changed since, see 'Keycloak admin "
                        "password' in docs/authentication.md."
                    )
                problem = f"Keycloak answered {response.status_code}"
            except httpx.TransportError as exc:
                problem = f"Keycloak not reachable at {self._base_url} ({exc})"
            if time.monotonic() >= deadline:
                raise KeycloakAdminError(f"{problem}; gave up after {wait_seconds:.0f}s.")
            sleep(2)

    def _call(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        response = self._client.request(method, f"/admin{path}", headers=self._headers, **kwargs)
        if response.status_code >= 400 and response.status_code != 404:
            raise KeycloakAdminError(
                f"{method} {path}: {response.status_code} {response.text[:300]}"
            )
        return response

    def apply(self, config: KeycloakConfig) -> list[str]:
        """Create or update everything. Returns a human-readable log of what was done."""
        log: list[str] = []
        realm = config.realm

        if self._call("GET", f"/realms/{realm}").status_code == 404:
            self._call("POST", "/realms", json={"realm": realm, "enabled": True})
            log.append(f"created realm {realm}")
        self._call("PUT", f"/realms/{realm}", json=realm_representation(config))
        log.append(f"configured realm {realm}")

        client = client_representation(config)
        existing = self._call(
            "GET", f"/realms/{realm}/clients", params={"clientId": config.client_id}
        ).json()
        if existing:
            self._call("PUT", f"/realms/{realm}/clients/{existing[0]['id']}", json=client)
            log.append(f"updated client {config.client_id}")
        else:
            self._call("POST", f"/realms/{realm}/clients", json=client)
            log.append(f"created client {config.client_id}")

        path = f"/realms/{realm}/identity-provider/instances"
        for alias in MANAGED_IDENTITY_PROVIDERS:
            exists = self._call("GET", f"{path}/{alias}").status_code != 404
            provider = config.identity_providers.get(alias)
            if provider is None:
                if exists:
                    self._call("DELETE", f"{path}/{alias}")
                    log.append(f"removed identity provider {alias} (no credentials in .env)")
            elif exists:
                self._call("PUT", f"{path}/{alias}", json=provider)
                log.append(f"updated identity provider {alias}")
            else:
                self._call("POST", path, json=provider)
                log.append(f"created identity provider {alias}")
        return log
