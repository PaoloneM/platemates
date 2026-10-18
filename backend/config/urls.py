from django.contrib import admin
from django.urls import include, path
from rest_framework.routers import DefaultRouter

from apps.accounts.access_requests import AccessRequestViewSet
from apps.accounts.team_requests import InviteRequestViewSet, MyTeamRequestViewSet
from apps.accounts.views import InvitationViewSet, login_options, me
from apps.assistant.probe import probe_view
from apps.assistant.views import AssistantSessionViewSet
from apps.audit.views import AuditEventViewSet, stats_view
from apps.catalog.views import IngredientViewSet, KitchenToolViewSet
from apps.core.views import health
from apps.curation.views import SystemDraftViewSet
from apps.menus.shopping_api import ShoppingItemViewSet, ShoppingListViewSet
from apps.menus.views import (
    MealSlotViewSet,
    MenuGenerationViewSet,
    SystemRuleViewSet,
    TeamRuleViewSet,
    WeeklyMenuViewSet,
)
from apps.recipes.views import CuisineViewSet, RecipeViewSet
from apps.siteconfig.views import cache_clear, cache_stats, config_detail, config_list
from apps.teams.views import (
    CalendarDayView,
    CalendarView,
    MembershipViewSet,
    MemberViewSet,
    PreferenceViewSet,
    RecipeBookEntryViewSet,
    TeamViewSet,
)
from apps.transfer.views import choices_view, export_view, import_view
from apps.usage.views import ModelPriceViewSet, usage_view

router = DefaultRouter()
router.register("ingredients", IngredientViewSet, basename="ingredient")
router.register("kitchen-tools", KitchenToolViewSet)
router.register("cuisines", CuisineViewSet)
router.register("recipes", RecipeViewSet, basename="recipe")
router.register("teams", TeamViewSet, basename="team")
router.register("members", MemberViewSet)
router.register("memberships", MembershipViewSet)
router.register("preferences", PreferenceViewSet)
router.register("recipe-book", RecipeBookEntryViewSet)
router.register("menus", WeeklyMenuViewSet)
router.register("team-rules", TeamRuleViewSet)
router.register("menu-generations", MenuGenerationViewSet)
router.register("system-drafts", SystemDraftViewSet)
router.register("system-rules", SystemRuleViewSet, basename="system-rule")
router.register("slots", MealSlotViewSet)
router.register("invitations", InvitationViewSet)
router.register("shopping-lists", ShoppingListViewSet, basename="shopping-list")
router.register("shopping-items", ShoppingItemViewSet, basename="shopping-item")
router.register("audit-events", AuditEventViewSet, basename="audit-event")
router.register("invite-requests", InviteRequestViewSet, basename="invite-request")
router.register("team-requests", MyTeamRequestViewSet, basename="team-request")
router.register("access-requests", AccessRequestViewSet, basename="access-request")
router.register("usage/prices", ModelPriceViewSet)
router.register("assistant/sessions", AssistantSessionViewSet, basename="assistant-session")

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/health/", health),
    path("oidc/", include("mozilla_django_oidc.urls")),
    path("api/me/", me),
    path("api/login-options/", login_options),
    path("api/config/", config_list),
    path("api/cache/", cache_stats),
    path("api/cache/clear/", cache_clear),
    path("api/config/<str:key>/", config_detail),
    path("api/usage/", usage_view),
    path("api/search-probe/", probe_view),
    path("api/audit-stats/", stats_view),
    path("api/transfer/export/", export_view),
    path("api/transfer/import/", import_view),
    path("api/transfer/choices/", choices_view),
    path("api/calendar/", CalendarView.as_view()),
    path("api/calendar/<str:date>/", CalendarDayView.as_view()),
    path("api/", include(router.urls)),
]
