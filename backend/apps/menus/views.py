import datetime as dt

from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import StaffWritesPermission
from apps.teams.permissions import OwnerWritesMixin, TeamScopedMixin

from .models import MealSlot, SystemRule, TeamRule, WeeklyMenu
from .serializers import (
    MealSlotSerializer,
    SystemRuleSerializer,
    TeamRuleSerializer,
    WeeklyMenuSerializer,
)
from .shopping import build_shopping_list, group_by_category


def _filter_team(queryset, request, lookup="team"):
    """Narrow to `?team=` when given (the querysets are already limited to the user's teams)."""
    team = request.query_params.get("team")
    return queryset.filter(**{lookup: team}) if team and team.isdigit() else queryset


class SystemRuleViewSet(viewsets.ModelViewSet):
    """The rules every team's menus follow. Everyone reads the active ones; staff see all of
    them and change them live. Shipped rules (with a code) are switched off, not deleted."""

    serializer_class = SystemRuleSerializer
    permission_classes = [StaffWritesPermission]
    pagination_class = None

    def get_queryset(self):
        rules = SystemRule.objects.all()
        return rules if self.request.user.is_staff else rules.filter(active=True)

    def perform_destroy(self, instance):
        if instance.code:
            raise ValidationError("Rules the app ships with are switched off, not deleted.")
        instance.delete()


class TeamRuleViewSet(OwnerWritesMixin, viewsets.ModelViewSet):
    """The team's standing rules: every member reads them, owners write them."""

    queryset = TeamRule.objects.all()
    serializer_class = TeamRuleSerializer

    def get_queryset(self):
        return _filter_team(super().get_queryset(), self.request)


class WeeklyMenuViewSet(TeamScopedMixin, viewsets.ModelViewSet):
    queryset = WeeklyMenu.objects.prefetch_related("slots__slot_dishes", "excluded_rules")
    serializer_class = WeeklyMenuSerializer

    def get_queryset(self):
        queryset = _filter_team(super().get_queryset(), self.request)
        week_start = self.request.query_params.get("week_start")
        if week_start is None:
            return queryset
        try:
            return queryset.filter(week_start=dt.date.fromisoformat(week_start))
        except ValueError:
            return queryset.none()

    @transaction.atomic
    def perform_create(self, serializer):
        self.check_team(serializer.validated_data["team"])
        menu = serializer.save()
        menu.create_empty_slots()

    @action(detail=True, url_path="shopping-list")
    def shopping_list(self, request, pk=None):
        menu = self.get_object()
        return Response({"menu": menu.pk, "items": group_by_category(build_shopping_list(menu))})


class MealSlotViewSet(
    TeamScopedMixin,
    mixins.RetrieveModelMixin,
    mixins.UpdateModelMixin,
    mixins.ListModelMixin,
    viewsets.GenericViewSet,
):
    """Slots are created with their menu; here they are only read and edited."""

    queryset = MealSlot.objects.prefetch_related("slot_dishes")
    serializer_class = MealSlotSerializer
    team_lookup = "menu__team"
