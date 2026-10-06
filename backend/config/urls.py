from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.views import InvitationViewSet, login_options, me
from apps.assistant.views import AssistantSessionViewSet
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
router.register("recipes", RecipeViewSet, basename="recipe")
router.register("families", FamilyViewSet, basename="family")
router.register("family-members", FamilyMemberViewSet)
router.register("preferences", PreferenceViewSet)
router.register("recipe-book", RecipeBookEntryViewSet)
router.register("menus", WeeklyMenuViewSet)
router.register("slots", MealSlotViewSet)
router.register("invitations", InvitationViewSet)
router.register("assistant/sessions", AssistantSessionViewSet, basename="assistant-session")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("api/me/", me),
    path("api/login-options/", login_options),
    path("api/", include(router.urls)),
]
