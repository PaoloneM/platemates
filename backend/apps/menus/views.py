from django.db import transaction
from rest_framework import mixins, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.teams.permissions import TeamScopedMixin

from .models import MealSlot, WeeklyMenu
from .serializers import MealSlotSerializer, WeeklyMenuSerializer
from .shopping import build_shopping_list, group_by_category


class WeeklyMenuViewSet(TeamScopedMixin, viewsets.ModelViewSet):
    queryset = WeeklyMenu.objects.prefetch_related("slots__slot_dishes")
    serializer_class = WeeklyMenuSerializer

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
