"""Multi-team access: a user only ever sees the teams they are a member of.

Within a team, owners manage it (profile, people, users and roles, invitations); members see
everything and can leave.
"""

from __future__ import annotations

from django.db.models import QuerySet
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .models import Team


def user_teams(user) -> QuerySet[Team]:
    return Team.objects.filter(memberships__user=user)


def is_owner(user, team: Team) -> bool:
    from .models import Membership

    return Membership.objects.filter(user=user, team=team, role=Membership.Role.OWNER).exists()


def require_owner(user, team: Team) -> None:
    if not is_owner(user, team):
        raise PermissionDenied("Only the team's owners can do this.")


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


class OwnerWritesMixin(TeamScopedMixin):
    """Team-owned objects every member reads but only owners create, change or delete."""

    def perform_create(self, serializer):
        self.check_team(serializer.validated_data["team"])
        require_owner(self.request.user, serializer.validated_data["team"])
        serializer.save()

    def perform_update(self, serializer):
        require_owner(self.request.user, serializer.instance.team)
        if "team" in serializer.validated_data:
            require_owner(self.request.user, serializer.validated_data["team"])
        serializer.save()

    def perform_destroy(self, instance):
        require_owner(self.request.user, instance.team)
        instance.delete()
