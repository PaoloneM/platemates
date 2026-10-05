from rest_framework import viewsets

from .models import Ingredient, KitchenTool
from .serializers import IngredientSerializer, KitchenToolSerializer


class IngredientViewSet(viewsets.ModelViewSet):
    queryset = Ingredient.objects.all()
    serializer_class = IngredientSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(name__icontains=search.strip().lower())
        return queryset


class KitchenToolViewSet(viewsets.ModelViewSet):
    queryset = KitchenTool.objects.all()
    serializer_class = KitchenToolSerializer
