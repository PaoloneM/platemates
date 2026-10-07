"""Multi-team access: a user only ever sees the teams they are a member of."""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import serializers

from .models import Team


def user_teams(user) -> QuerySet[Team]:
    return Team.objects.filter(memberships__user=user)


class TeamScopedMixin:
    """For viewsets over objects that belong to a team.

    `team_lookup` is the ORM path from the model to its team.
    """

    team_lookup = "team"

    def get_queryset(self):
        queryset = super().get_queryset()
        return queryset.filter(**{f"{self.team_lookup}__memberships__user": self.request.user})

    def check_team(self, team: Team) -> None:
        if not user_teams(self.request.user).filter(pk=team.pk).exists():
            raise serializers.ValidationError({"team": "Not one of your teams."})

    def perform_create(self, serializer):
        self.check_team(serializer.validated_data["team"])
        serializer.save()

    def perform_update(self, serializer):
        if "team" in serializer.validated_data:
            self.check_team(serializer.validated_data["team"])
        serializer.save()
