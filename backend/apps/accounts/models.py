"""Who users are (an identity at Keycloak) and how they get into a team (an invitation).

Access is invitation-only: anyone can authenticate at Keycloak, but a user sees nothing until they
accept an invitation to a team. Teams themselves are created by staff.
"""

from __future__ import annotations

import datetime as dt
import secrets

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.teams.models import Membership, Team

INVITATION_VALIDITY = dt.timedelta(days=14)


class UserProfile(models.Model):
    """Per-user preferences that must follow the user across browsers and devices."""

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile"
    )
    # Interface language. Blank until known: the SPA then adopts the browser's language and
    # saves it here, so the first device a user signs in from decides the default.
    language = models.CharField(max_length=8, choices=settings.LANGUAGES, blank=True)

    def __str__(self) -> str:
        return f"{self.user} profile"

    @classmethod
    def of(cls, user) -> UserProfile:
        profile, _created = cls.objects.get_or_create(user=user)
        return profile


def supported_language(code: str | None) -> str:
    """Map a locale such as "it-IT" or "en_GB" to a supported language code, or ""."""
    base = (code or "").replace("_", "-").split("-")[0].lower()
    return base if base in dict(settings.LANGUAGES) else ""


class OIDCIdentity(models.Model):
    """Links a Django user to the Keycloak account that authenticates them.

    Users are matched on the OIDC `sub` claim, never on email: emails change and are not unique
    across identity providers, while `sub` is Keycloak's stable id for the account. Keycloak itself
    links a Google, Microsoft or Apple login to an existing account with the same email.
    """

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="oidc_identity"
    )
    subject = models.CharField(max_length=255, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "OIDC identity"
        verbose_name_plural = "OIDC identities"

    def __str__(self) -> str:
        return f"{self.user} ({self.subject})"


def new_token() -> str:
    return secrets.token_urlsafe(24)


def default_expiry() -> dt.datetime:
    return timezone.now() + INVITATION_VALIDITY


class Invitation(models.Model):
    """A single-use link that adds whoever accepts it to a team."""

    class State(models.TextChoices):
        PENDING = "pending", _("Pending")
        ACCEPTED = "accepted", _("Accepted")
        EXPIRED = "expired", _("Expired")
        REVOKED = "revoked", _("Revoked")

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="invitations")
    token = models.CharField(max_length=64, unique=True, default=new_token, editable=False)
    role = models.CharField(
        max_length=10, choices=Membership.Role.choices, default=Membership.Role.MEMBER
    )
    # Who the link is meant for. Informational only: the token is what grants access.
    note = models.CharField(max_length=200, blank=True)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=default_expiry)
    revoked_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="accepted_invitations",
    )

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"Invitation to {self.team} ({self.state})"

    @property
    def state(self) -> str:
        if self.accepted_at:
            return self.State.ACCEPTED
        if self.revoked_at:
            return self.State.REVOKED
        if self.expires_at <= timezone.now():
            return self.State.EXPIRED
        return self.State.PENDING

    def accept(self, user) -> Membership:
        """Add `user` to the team. Raises `ValueError` if the invitation is no longer usable."""
        if self.state != self.State.PENDING:
            raise ValueError(f"Invitation is {self.state}.")
        membership, _created = Membership.objects.get_or_create(
            user=user, team=self.team, defaults={"role": self.role}
        )
        self.accepted_at = timezone.now()
        self.accepted_by = user
        self.save(update_fields=["accepted_at", "accepted_by"])
        return membership
