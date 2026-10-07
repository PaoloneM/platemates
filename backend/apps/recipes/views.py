from rest_framework import status, viewsets
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response

from apps.core.permissions import CatalogPermission
from apps.teams.models import RecipeBookEntry

from .models import Cuisine, Recipe
from .serializers import CuisineSerializer, RecipeSerializer


class CuisineViewSet(viewsets.ModelViewSet):
    queryset = Cuisine.objects.all()
    serializer_class = CuisineSerializer
    permission_classes = [CatalogPermission]
    pagination_class = None


class RecipeViewSet(viewsets.ModelViewSet):
    """Recipes visible to the user: shared ones, plus their teams' private ones.

    Creating a recipe puts it in the given team's recipe book. Only the owner team edits it;
    deleting is possible only while no other team keeps it in its recipe book.
    """

    serializer_class = RecipeSerializer

    def get_queryset(self):
        queryset = (
            Recipe.objects.visible_to(self.request.user)
            .select_related("cuisine")
            .prefetch_related("tools", "ingredients__ingredient")
        )
        params = self.request.query_params
        if search := params.get("search", "").strip():
            queryset = queryset.filter(title__icontains=search)
        if course := params.get("course"):
            queryset = queryset.filter(course=course)
        return queryset

    def _check_editable(self, recipe):
        if not Recipe.objects.editable_by(self.request.user).filter(pk=recipe.pk).exists():
            raise PermissionDenied("Only the team that owns this recipe can change it.")

    def perform_update(self, serializer):
        self._check_editable(serializer.instance)
        serializer.save()

    def destroy(self, request, *args, **kwargs):
        recipe = self.get_object()
        self._check_editable(recipe)
        others = RecipeBookEntry.objects.filter(recipe=recipe).exclude(team_id=recipe.owner_team_id)
        if others.exists():
            return Response(
                {"detail": "Other teams keep this recipe in their recipe book."},
                status=status.HTTP_409_CONFLICT,
            )
        recipe.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)
