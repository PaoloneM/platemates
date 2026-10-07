from rest_framework import serializers

from apps.teams.permissions import is_owner

from .models import Invitation


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
        # The token is the invitation: only owners, who hand it out, ever see it.
        if not is_owner(self.context["request"].user, invitation.team):
            data.pop("token")
        return data

    class Meta:
        model = Invitation
        fields = [
            "id",
            "team",
            "team_name",
            "token",
            "role",
            "note",
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

    class Meta:
        model = Invitation
        fields = ["team_name", "role", "state", "expires_at"]
