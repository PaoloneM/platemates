from rest_framework import serializers

from .models import Invitation


class InvitationSerializer(serializers.ModelSerializer):
    state = serializers.CharField(read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)

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
        ]
        read_only_fields = ["token", "created_at", "expires_at", "accepted_at"]


class InvitationPreviewSerializer(serializers.ModelSerializer):
    """What someone holding the link may see before accepting: no token, no other members."""

    state = serializers.CharField(read_only=True)
    team_name = serializers.CharField(source="team.name", read_only=True)

    class Meta:
        model = Invitation
        fields = ["team_name", "role", "state", "expires_at"]
