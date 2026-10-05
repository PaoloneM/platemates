from rest_framework import viewsets

from .models import Cuisine, Recipe
from .serializers import CuisineSerializer, RecipeSerializer


class CuisineViewSet(viewsets.ModelViewSet):
    queryset = Cuisine.objects.all()
    serializer_class = CuisineSerializer


class RecipeViewSet(viewsets.ModelViewSet):
    queryset = Recipe.objects.select_related("cuisine").prefetch_related(
        "tools", "ingredients__ingredient"
    )
    serializer_class = RecipeSerializer

    def get_queryset(self):
        queryset = super().get_queryset()
        search = self.request.query_params.get("search")
        if search:
            queryset = queryset.filter(title__icontains=search.strip())
        return queryset
