from django.db import transaction
from rest_framework import viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.recipes.models import Recipe, Visibility

from .models import Member, Membership, Preference, RecipeBookEntry, Team
from .permissions import TeamScopedMixin
from .serializers import (
    MemberSerializer,
    PreferenceSerializer,
    RecipeBookEntrySerializer,
    TeamSerializer,
)


class TeamViewSet(viewsets.ModelViewSet):
    serializer_class = TeamSerializer

    def get_queryset(self):
        return Team.objects.filter(memberships__user=self.request.user).prefetch_related(
            "members", "preferences", "tools"
        )

    def perform_create(self, serializer):
        # Access is invitation-only: new teams are created by staff, everyone else joins one.
        if not self.request.user.is_staff:
            raise PermissionDenied("Only staff can create teams; ask for an invitation.")
        team = serializer.save()
        Membership.objects.create(user=self.request.user, team=team, role=Membership.Role.OWNER)


class MemberViewSet(TeamScopedMixin, viewsets.ModelViewSet):
    queryset = Member.objects.all()
    serializer_class = MemberSerializer


class PreferenceViewSet(TeamScopedMixin, viewsets.ModelViewSet):
    queryset = Preference.objects.all()
    serializer_class = PreferenceSerializer


class RecipeBookEntryViewSet(TeamScopedMixin, viewsets.ModelViewSet):
    """A team's recipe book. Filters: `?team=`, `?status=`, `?search=`, `?course=`.

    Removing an entry removes the recipe from the book; a private recipe that no team keeps
    any more is deleted with it, since nobody else could ever see it.
    """

    queryset = RecipeBookEntry.objects.select_related("recipe__cuisine").order_by("recipe__title")
    serializer_class = RecipeBookEntrySerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        params = self.request.query_params
        if team := params.get("team"):
            queryset = queryset.filter(team_id=team)
        if status := params.get("status"):
            queryset = queryset.filter(status=status)
        if search := params.get("search", "").strip():
            queryset = queryset.filter(recipe__title__icontains=search)
        if course := params.get("course"):
            queryset = queryset.filter(recipe__course=course)
        return queryset

    def perform_create(self, serializer):
        self.check_team(serializer.validated_data["team"])
        recipe = serializer.validated_data["recipe"]
        if not Recipe.objects.visible_to(self.request.user).filter(pk=recipe.pk).exists():
            raise ValidationError({"recipe": "Recipe not found."})
        serializer.save()

    @transaction.atomic
    def perform_destroy(self, instance):
        recipe = instance.recipe
        instance.delete()
        if (
            recipe.visibility == Visibility.PRIVATE
            and not RecipeBookEntry.objects.filter(recipe=recipe).exists()
        ):
            recipe.delete()
