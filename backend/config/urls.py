from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.catalog.views import IngredientViewSet, KitchenToolViewSet
from apps.core.views import health
from apps.families.views import (
    FamilyMemberViewSet,
    FamilyViewSet,
    PreferenceViewSet,
    RecipeBookEntryViewSet,
)
from apps.menus.views import MealSlotViewSet, WeeklyMenuViewSet
from apps.recipes.views import CuisineViewSet, RecipeViewSet

router = DefaultRouter()
router.register("ingredients", IngredientViewSet)
router.register("kitchen-tools", KitchenToolViewSet)
router.register("cuisines", CuisineViewSet)
router.register("recipes", RecipeViewSet)
router.register("families", FamilyViewSet, basename="family")
router.register("family-members", FamilyMemberViewSet)
router.register("preferences", PreferenceViewSet)
router.register("recipe-book", RecipeBookEntryViewSet)
router.register("menus", WeeklyMenuViewSet)
router.register("slots", MealSlotViewSet)

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("api/auth/", include("rest_framework.urls")),
    path("api/", include(router.urls)),
]
