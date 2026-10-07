from django.db import transaction
from rest_framework import mixins, status, viewsets
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.recipes.models import Recipe, Visibility

from .models import Member, Membership, Preference, RecipeBookEntry, Team
from .permissions import OwnerWritesMixin, TeamScopedMixin, require_owner
from .serializers import (
    MemberSerializer,
    MembershipSerializer,
    PreferenceSerializer,
    RecipeBookEntrySerializer,
    TeamSerializer,
)


class TeamViewSet(
    mixins.ListModelMixin,
    mixins.RetrieveModelMixin,
    mixins.CreateModelMixin,
    mixins.UpdateModelMixin,
    viewsets.GenericViewSet,
):
    """The user's teams. Owners change a team's profile; there is no deleting a team from the
    app (it would take every member's recipe book and menus with it)."""

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

    def perform_update(self, serializer):
        require_owner(self.request.user, serializer.instance)
        serializer.save()


class MembershipViewSet(
    TeamScopedMixin,
    mixins.ListModelMixin,
    mixins.UpdateModelMixin,
    mixins.DestroyModelMixin,
    viewsets.GenericViewSet,
):
    """Users with access to a team (`?team=`). Owners change roles and remove users; anyone can
    remove themselves (leave). A team always keeps at least one owner."""

    queryset = Membership.objects.select_related("user").order_by("user__first_name", "user__email")
    serializer_class = MembershipSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        if team := self.request.query_params.get("team"):
            queryset = queryset.filter(team_id=team)
        return queryset

    def _last_owner(self, membership: Membership) -> bool:
        return (
            membership.role == Membership.Role.OWNER
            and not Membership.objects.filter(team=membership.team, role=Membership.Role.OWNER)
            .exclude(pk=membership.pk)
            .exists()
        )

    def perform_update(self, serializer):
        membership = serializer.instance
        require_owner(self.request.user, membership.team)
        if serializer.validated_data.get("role") == Membership.Role.MEMBER and self._last_owner(
            membership
        ):
            raise ValidationError({"role": "A team needs at least one owner."})
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        membership = self.get_object()
        if membership.user_id != request.user.pk:
            require_owner(request.user, membership.team)
        if self._last_owner(membership):
            return Response(
                {"detail": "A team needs at least one owner: make someone else owner first."},
                status=status.HTTP_409_CONFLICT,
            )
        membership.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class MemberViewSet(OwnerWritesMixin, viewsets.ModelViewSet):
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
