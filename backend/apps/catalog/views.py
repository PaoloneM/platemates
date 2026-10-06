from django.db.models import Q
from rest_framework import viewsets

from apps.core.permissions import CatalogPermission

from .models import Ingredient, KitchenTool, normalize_name
from .serializers import IngredientSerializer, KitchenToolSerializer


class IngredientViewSet(viewsets.ModelViewSet):
    """`?search=` matches the name or, exactly, one of the aliases ("pomodori" -> "pomodoro")."""

    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer
    permission_classes = [CatalogPermission]

    def get_queryset(self):
        queryset = super().get_queryset()
        search = normalize_name(self.request.query_params.get("search", ""))
        if search:
            queryset = queryset.filter(Q(name__icontains=search) | Q(aliases__contains=[search]))
        return queryset


class KitchenToolViewSet(viewsets.ModelViewSet):
    queryset = KitchenTool.objects.all()
    serializer_class = KitchenToolSerializer
    permission_classes = [CatalogPermission]
    pagination_class = None
