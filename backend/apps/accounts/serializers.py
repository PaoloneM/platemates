from rest_framework import serializers

from apps.teams.permissions import is_owner

from .models import Invitation


def mask_email(email: str) -> str:
    """ "paola.rossi@gmail.com" -> "p***i@gmail.com": enough to recognise one's own address."""
    if "@" not in email:
        return ""
    name, domain = email.split("@", 1)
    return f"{name[0]}***{name[-1] if len(name) > 1 else ''}@{domain}"


def _display_name(user) -> str | None:
    if user is None:
        return None
    return " ".join(filter(None, [user.first_name, user.last_name])) or user.email or user.username


class InvitationSerializer(serializers.ModelSerializer):
    state = serializers.CharField(read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    invited_by_name = serializers.SerializerMethodField()
    accepted_by_name = serializers.SerializerMethodField()

    def get_invited_by_name(self, invitation) -> str | None:
        return _display_name(invitation.invited_by)

    def get_accepted_by_name(self, invitation) -> str | None:
        return _display_name(invitation.accepted_by)

    def to_representation(self, invitation):
        data = super().to_representation(invitation)
        # The token is the invitation, and the address someone's: only owners, who hand them
        # out, ever see them.
        if not is_owner(self.context["request"].user, invitation.team):
            data.pop("token")
            data.pop("email")
        return data

    def validate_email(self, email: str) -> str:
        return email.strip().lower()

    class Meta:
        model = Invitation
        fields = [
            "id",
            "team",
            "team_name",
            "token",
            "role",
            "note",
            "email",
            "state",
            "created_at",
            "expires_at",
            "accepted_at",
            "invited_by_name",
            "accepted_by_name",
        ]
        read_only_fields = ["token", "created_at", "expires_at", "accepted_at"]


class InvitationPreviewSerializer(serializers.ModelSerializer):
    """What someone holding the link may see before accepting: no token, no other members."""

    state = serializers.CharField(read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)
    # Who sent it, by name only (never their email): it is shown before signing in.
    invited_by_name = serializers.SerializerMethodField()
    # Sent to an address: which one, masked ("p***i@gmail.com"), so the right account is used.
    email_hint = serializers.SerializerMethodField()

    class Meta:
        model = Invitation
        fields = ["team_name", "invited_by_name", "email_hint", "role", "state", "expires_at"]

    def get_email_hint(self, invitation) -> str | None:
        return mask_email(invitation.email) if invitation.email else None

    def get_invited_by_name(self, invitation) -> str | None:
        user = invitation.invited_by
        return (user.get_full_name() or user.first_name or None) if user else None
