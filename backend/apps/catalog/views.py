from django.db.models import Count, Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.permissions import CatalogPermission, IngredientPermission, IsStaffHere
from apps.core.planes import staff_powers
from apps.recipes.models import Visibility
from apps.teams.models import Team
from apps.teams.permissions import user_teams

from .models import Ingredient, KitchenTool, normalize_name
from .serializers import IngredientSerializer, KitchenToolSerializer
from .services import merge_ingredients, recompute_recipes

ORDERINGS = {
    "name": "name",
    "-usage": "-usage_count",
    "-shared": "-shared_usage_count",
    "category": "category",
}


class IngredientViewSet(viewsets.ModelViewSet):
    """The ingredient catalog: system ingredients, and those teams add for themselves.

    A user sees system ingredients and their teams' own; staff also see every team's additions.
    `?team=` narrows to what that team's recipes can use (the editor's picker); `?owner=system`
    or `?owner=teams` splits the catalog (Manage). `?search=` matches the name or, exactly, one
    of the aliases ("pomodori" -> "pomodoro"); `?category=` filters;
    `?ordering=name|-usage|-shared|category`. Team ingredients are changed by their team,
    system ones by staff; promoting and merging are for staff.
    """

    serializer_class = IngredientSerializer
    permission_classes = [IngredientPermission]

    def get_queryset(self):
        user = self.request.user
        queryset = (
            Ingredient.objects.visible_to(user)
            .select_related("owner_team")
            .annotate(
                usage_count=Count("uses__recipe", distinct=True),
                shared_usage_count=Count(
                    "uses__recipe",
                    filter=Q(uses__recipe__visibility=Visibility.SHARED),
                    distinct=True,
                ),
            )
        )
        params = self.request.query_params
        if team_id := params.get("team"):
            team = self._team(team_id)
            queryset = queryset.filter(pk__in=Ingredient.objects.usable_by(team).values("pk"))
        owner = params.get("owner")
        if owner == "system":
            queryset = queryset.filter(owner_team__isnull=True)
        elif owner == "teams":
            queryset = queryset.filter(owner_team__isnull=False)
        if search := normalize_name(params.get("search", "")):
            queryset = queryset.filter(Q(name__icontains=search) | Q(aliases__contains=[search]))
        if category := params.get("category"):
            queryset = queryset.filter(category=category)
        return queryset.order_by(ORDERINGS.get(params.get("ordering", ""), "name"), "name")

    def _team(self, team_id) -> Team:
        """One of the user's teams (staff: also the system team)."""
        teams = user_teams(self.request.user)
        if staff_powers(self.request.user):
            teams = teams | Team.objects.filter(is_system=True)
        team = teams.filter(pk=team_id).first()
        if team is None:
            raise serializers.ValidationError({"team": "Not one of your teams."})
        return team

    def perform_create(self, serializer):
        owner = serializer.validated_data.get("owner_team")
        if owner is None:
            if not staff_powers(self.request.user):
                raise PermissionDenied("Only staff add system ingredients.")
        elif not user_teams(self.request.user).filter(pk=owner.pk).exists():
            raise serializers.ValidationError({"team": "Not one of your teams."})
        serializer.save()

    def perform_update(self, serializer):
        before = serializer.instance.season_months
        ingredient = serializer.save()
        if ingredient.season_months != before:
            recompute_recipes(ingredient)

    def destroy(self, request, *args, **kwargs):
        ingredient = self.get_object()
        recipes = list(ingredient.uses.values_list("recipe__title", flat=True).distinct()[:20])
        if recipes or ingredient.preference_set.exists():
            return Response(
                {
                    "detail": "This ingredient is in use; merge it into another instead.",
                    "recipes": recipes,
                },
                status=status.HTTP_409_CONFLICT,
            )
        ingredient.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=True, methods=["post"], permission_classes=[IsStaffHere])
    def promote(self, request, pk=None):
        """Make a team's ingredient a system one, for every team. Refused when a system
        ingredient already has its name (merge into it instead); aliases other system
        ingredients hold are dropped."""
        ingredient = self.get_object()
        if ingredient.is_system:
            raise serializers.ValidationError({"detail": "Already a system ingredient."})
        system = Ingredient.objects.system()
        same = system.filter(Q(name=ingredient.name) | Q(aliases__contains=[ingredient.name]))
        if clash := same.first():
            return Response(
                {
                    "detail": "A system ingredient already has this name: merge into it.",
                    "into": clash.pk,
                },
                status=status.HTTP_409_CONFLICT,
            )
        taken = set(system.values_list("name", flat=True))
        for aliases in system.values_list("aliases", flat=True):
            taken.update(aliases)
        ingredient.aliases = [a for a in ingredient.aliases if a not in taken]
        ingredient.owner_team = None
        ingredient.save()
        return Response(IngredientSerializer(self.get_queryset().get(pk=ingredient.pk)).data)

    @action(detail=True, methods=["post"], permission_classes=[IsStaffHere])
    def merge(self, request, pk=None):
        """Fold this ingredient into `into`: its recipes move over and its name becomes an alias.
        The target is a system ingredient, or one of the same team."""
        source = self.get_object()
        target = Ingredient.objects.filter(pk=request.data.get("into")).first()
        if target is None or target.pk == source.pk:
            raise serializers.ValidationError({"into": "Choose another existing ingredient."})
        if not target.is_system and target.owner_team_id != source.owner_team_id:
            raise serializers.ValidationError(
                {"into": "Merge into a system ingredient or one of the same team."}
            )
        if source.is_system and not target.is_system:
            raise serializers.ValidationError(
                {"into": "A system ingredient is merged into another system ingredient."}
            )
        result = merge_ingredients(source, target)
        data = IngredientSerializer(self.get_queryset().get(pk=target.pk)).data
        return Response({**result, "ingredient": data})


class KitchenToolViewSet(viewsets.ModelViewSet):
    queryset = KitchenTool.objects.all()
    serializer_class = KitchenToolSerializer
    permission_classes = [CatalogPermission]
    pagination_class = None
