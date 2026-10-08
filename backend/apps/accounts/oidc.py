"""Django as an OIDC client of Keycloak (backend-for-frontend).

The browser never holds a token: Django runs the authorization code flow (with PKCE), keeps only
the ID token in the server-side session for logout, and authenticates the SPA with its ordinary
session cookie.
"""

from __future__ import annotations

from urllib.parse import urlencode

from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone, translation
from mozilla_django_oidc.auth import OIDCAuthenticationBackend
from mozilla_django_oidc.views import OIDCAuthenticationRequestView

from .keycloak_admin import ADMIN_ROLE
from .models import OIDCIdentity, UserProfile, supported_language


class KeycloakBackend(OIDCAuthenticationBackend):
    def get_userinfo(self, access_token, id_token, payload):
        """Use the ID token's claims instead of calling Keycloak's userinfo endpoint.

        Keycloak issues tokens for the address the browser used (`https://<lan host>:8443/auth`,
        `http://localhost:8080/auth`, ...), while the backend calls it on its internal address,
        and userinfo refuses a token issued for another address. The ID token was just received
        from Keycloak and its signature verified (`verify_token`), and with the `email` and
        `profile` scopes it carries everything needed: sub, email, names, locale.
        """
        return payload

    def verify_claims(self, claims) -> bool:
        return bool(claims.get("sub")) and bool(claims.get("email"))

    def filter_users_by_claims(self, claims):
        return get_user_model().objects.filter(oidc_identity__subject=claims["sub"])

    @transaction.atomic
    def create_user(self, claims):
        user = get_user_model().objects.create_user(
            username=f"kc-{claims['sub']}"[:150], email=claims["email"]
        )
        OIDCIdentity.objects.create(user=user, subject=claims["sub"])
        # Keycloak's `locale` claim is the language picked on its pages (e.g. while registering).
        UserProfile.objects.create(user=user, language=supported_language(claims.get("locale")))
        return self.update_user(user, claims)

    def update_user(self, user, claims):
        # Keycloak is the source of truth for profile data; refresh it on every login.
        user.email = claims.get("email", user.email)
        user.first_name = claims.get("given_name", "")[:150]
        # `family_name` is the standard OIDC claim for the surname (not a PlateMates team).
        user.last_name = claims.get("family_name", "")[:150]
        user.save(update_fields=["email", "first_name", "last_name"])
        OIDCIdentity.objects.filter(user=user).update(last_login_at=timezone.now())
        # Roles are Keycloak's: granted or taken away there, they apply from the next login.
        UserProfile.objects.update_or_create(
            user=user, defaults={"is_admin": ADMIN_ROLE in (claims.get("roles") or [])}
        )
        return user


class KeycloakAuthenticationRequestView(OIDCAuthenticationRequestView):
    """Start the login, forwarding the interface language and an optional provider shortcut.

    `?lang=it` shows Keycloak's pages in that language (`ui_locales`). `?idp=google` skips
    Keycloak's own page and goes straight to that identity provider (`kc_idp_hint`), which is
    what the provider buttons on the SPA's login screen use. `?signup=1` opens Keycloak's
    registration form instead of the login form (`prompt=create`).
    """

    def get_extra_params(self, request):
        params = dict(super().get_extra_params(request))
        lang = request.GET.get("lang") or translation.get_language()
        if lang:
            params["ui_locales"] = lang.split("-")[0]
        idp = request.GET.get("idp")
        if idp in enabled_identity_providers():
            params["kc_idp_hint"] = idp
        if request.GET.get("signup"):
            params["prompt"] = "create"
        return params


def keycloak_logout_url(request) -> str:
    """RP-initiated logout: end the Keycloak session too, then come back to the app."""
    query = {
        "client_id": settings.OIDC_RP_CLIENT_ID,
        "post_logout_redirect_uri": request.build_absolute_uri(settings.LOGOUT_REDIRECT_URL),
    }
    id_token = request.session.get("oidc_id_token")
    if id_token:
        query["id_token_hint"] = id_token
    return f"{settings.OIDC_OP_LOGOUT_ENDPOINT}?{urlencode(query)}"


def enabled_identity_providers() -> list[str]:
    """Identity providers configured in Keycloak, in display order. Derived from the same
    environment `setup_keycloak` reads, so the SPA only shows buttons that work."""
    return [
        alias for alias, configured in settings.KEYCLOAK_IDENTITY_PROVIDERS.items() if configured
    ]
