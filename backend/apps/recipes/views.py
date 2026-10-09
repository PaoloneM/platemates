from django.db.models import Prefetch, Q
from rest_framework import status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.permissions import CatalogPermission
from apps.teams.models import RecipeBookEntry
from apps.teams.permissions import user_teams

from .models import Cuisine, Recipe, Visibility
from .serializers import (
    CuisineSerializer,
    RecipeCardSerializer,
    RecipeSerializer,
    author_of,
    user_team_ids,
)


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

    @action(detail=False)
    def browse(self, request):
        """The recipe book screen: `?team=` and `mine=1` (the team's recipe book) and/or
        `community=1` (recipes shared by the system and other teams), with `?search=` and
        `?course=`. Each recipe says where it comes from and whether it is in the book."""
        try:
            team = user_teams(request.user).get(pk=int(request.query_params.get("team", "")))
        except (ValueError, Exception):
            raise ValidationError({"team": "One of your teams."}) from None
        params = request.query_params
        mine, community = params.get("mine", "1") == "1", params.get("community") == "1"
        if not (mine or community):
            raise ValidationError({"detail": "Choose the recipe book, the community, or both."})
        approved = RecipeBookEntry.Status.APPROVED
        scope = Q()
        if mine:
            scope |= Q(book_entries__team=team, book_entries__status=approved)
        if community:
            scope |= Q(visibility=Visibility.SHARED) & ~Q(owner_team=team)
        recipes = (
            Recipe.objects.visible_to(request.user)
            .filter(scope)
            .select_related("cuisine", "owner_team", "derived_from")
            .prefetch_related(
                Prefetch(
                    "book_entries",
                    queryset=RecipeBookEntry.objects.filter(team=team, status=approved),
                    to_attr="team_book",
                )
            )
            .distinct()
            .order_by("title", "pk")
        )
        if search := params.get("search", "").strip():
            recipes = recipes.filter(title__icontains=search)
        if course := params.get("course"):
            recipes = recipes.filter(course=course)
        page = self.paginate_queryset(recipes)
        return self.get_paginated_response(
            RecipeCardSerializer(page, many=True, context=self.get_serializer_context()).data
        )

    @action(detail=True)
    def variants(self, request, pk=None):
        """The original of a variant, and the other variants of the same original, as far as
        the user can see them (a copy nobody shared stays with its team)."""
        recipe = self.get_object()
        root = recipe.derived_from or recipe
        visible = Recipe.objects.visible_to(request.user).select_related("owner_team")
        teams = user_team_ids(self.get_serializer_context())

        def item(r):
            return {"id": r.pk, "title": r.title, "author": author_of(r, teams)}

        original = visible.filter(pk=root.pk).first() if root.pk != recipe.pk else None
        others = visible.filter(derived_from=root).exclude(pk=recipe.pk).order_by("title")
        return Response(
            {
                "original": item(original) if original else None,
                "variants": [item(r) for r in others],
            }
        )

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
