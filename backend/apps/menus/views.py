import datetime as dt

from django.db import IntegrityError, transaction
from django.utils import translation
from rest_framework import mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response

from apps.core.permissions import StaffWritesPermission
from apps.teams.permissions import OwnerWritesMixin, TeamScopedMixin

from . import review
from .generation import notify_worker
from .models import MealSlot, MenuGeneration, SystemRule, TeamRule, WeeklyMenu
from .serializers import (
    GenerateSerializer,
    MealSlotSerializer,
    MenuGenerationSerializer,
    ReviewSerializer,
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

    @action(detail=False, methods=["post"])
    def generate(self, request):
        """Queue a generation for a week, creating its menu if needed. Answers 202 with the
        generation; 409 with the running one if the week is already being generated."""
        data = GenerateSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        team = data.validated_data["team"]
        self.check_team(team)
        with transaction.atomic():
            menu, created = WeeklyMenu.objects.get_or_create(
                team=team, week_start=data.validated_data["week_start"]
            )
            if created:
                menu.create_empty_slots()
        active = menu.generations.filter(
            status__in=[MenuGeneration.Status.QUEUED, MenuGeneration.Status.RUNNING]
        ).first()
        if active is None:
            try:
                with transaction.atomic():
                    generation = MenuGeneration.objects.create(
                        menu=menu,
                        requested_by=request.user,
                        use_week_settings=data.validated_data["use_week_settings"],
                        language=(translation.get_language() or "it")[:2],
                    )
                    notify_worker()
                return Response(
                    MenuGenerationSerializer(generation).data, status=status.HTTP_202_ACCEPTED
                )
            except IntegrityError:  # another request queued one in the meantime
                active = menu.generations.filter(
                    status__in=[MenuGeneration.Status.QUEUED, MenuGeneration.Status.RUNNING]
                ).first()
        return Response(MenuGenerationSerializer(active).data, status=status.HTTP_409_CONFLICT)

    @action(detail=True, methods=["post"])
    def review(self, request, pk=None):
        """Accept or reject the generator's proposals, for the given meals or the whole week."""
        menu = self.get_object()
        data = ReviewSerializer(data=request.data)
        data.is_valid(raise_exception=True)
        meals = data.validated_data.get("meals")
        keys = None if meals is None else [(m["date"], m["meal"]) for m in meals]
        (review.accept if data.validated_data["action"] == "accept" else review.reject)(menu, keys)
        return Response(status=status.HTTP_204_NO_CONTENT)

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


class MenuGenerationViewSet(TeamScopedMixin, viewsets.ReadOnlyModelViewSet):
    """Generations, newest first: `?team=&week_start=` for a week's latest."""

    queryset = MenuGeneration.objects.select_related("menu")
    serializer_class = MenuGenerationSerializer
    team_lookup = "menu__team"

    def get_queryset(self):
        queryset = _filter_team(super().get_queryset(), self.request, "menu__team")
        week_start = self.request.query_params.get("week_start")
        if week_start is None:
            return queryset
        try:
            return queryset.filter(menu__week_start=dt.date.fromisoformat(week_start))
        except ValueError:
            return queryset.none()
