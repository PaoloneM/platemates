from django.db.models import Count, Q
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.permissions import IsAdminUser
from rest_framework.response import Response

from apps.core.permissions import CatalogPermission

from .models import Ingredient, KitchenTool, normalize_name
from .serializers import IngredientSerializer, KitchenToolSerializer
from .services import merge_ingredients, recompute_recipes

ORDERINGS = {"name": "name", "-usage": "-usage_count", "category": "category"}


class IngredientViewSet(viewsets.ModelViewSet):
    """The shared ingredient catalog.

    `?search=` matches the name or, exactly, one of the aliases ("pomodori" -> "pomodoro");
    `?category=` filters; `?ordering=name|-usage|category`. Everyone can read and add; changing,
    deleting and merging are for staff (the management section).
    """

    serializer_class = IngredientSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        queryset = Ingredient.objects.annotate(usage_count=Count("uses__recipe", distinct=True))
        params = self.request.query_params
        if search := normalize_name(params.get("search", "")):
            queryset = queryset.filter(Q(name__icontains=search) | Q(aliases__contains=[search]))
        if category := params.get("category"):
            queryset = queryset.filter(category=category)
        return queryset.order_by(ORDERINGS.get(params.get("ordering", ""), "name"), "name")

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

    @action(detail=True, methods=["post"], permission_classes=[IsAdminUser])
    def merge(self, request, pk=None):
        """Fold this ingredient into `into`: its recipes move over and its name becomes an alias."""
        source = self.get_object()
        target = Ingredient.objects.filter(pk=request.data.get("into")).first()
        if target is None or target.pk == source.pk:
            raise serializers.ValidationError({"into": "Choose another existing ingredient."})
        result = merge_ingredients(source, target)
        data = IngredientSerializer(self.get_queryset().get(pk=target.pk)).data
        return Response({**result, "ingredient": data})


class KitchenToolViewSet(viewsets.ModelViewSet):
    queryset = KitchenTool.objects.all()
    serializer_class = KitchenToolSerializer
    permission_classes = [CatalogPermission]
    pagination_class = None
