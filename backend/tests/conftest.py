import datetime as dt
from decimal import Decimal

import pytest
from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.catalog.models import Ingredient, IngredientCategory, Unit
from apps.recipes.models import Recipe, RecipeIngredient
from apps.teams.models import Membership, Team

MONDAY = dt.date(2026, 10, 5)


@pytest.fixture(autouse=True)
def empty_ingredient_catalog(request):
    """Database tests start from an empty ingredient catalog, not the seeded one, so they can
    create the ingredients they need. Tests about the seed opt out with @pytest.mark.seeded."""
    if "db" in request.fixturenames and not request.node.get_closest_marker("seeded"):
        request.getfixturevalue("db")  # autouse fixtures run first: make sure the db is set up
        Ingredient.objects.all().delete()


@pytest.fixture(autouse=True)
def isolated_caches(settings):
    """Tests never touch the running app's Redis: both cache levels live in this process."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "t-shared",
        },
        "local": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "t-memory",
        },
    }
    from apps.core.cache import cache_manager

    cache_manager.memory.clear()
    cache_manager.shared.clear()
    cache_manager.reset_counters()
    yield


@pytest.fixture(autouse=True)
def no_real_models(settings):
    """Tests never reach a real model or search engine (Unsloth Studio, SearXNG may be running
    on the machine): a provider a test did not replace points at a closed port and fails at
    once."""
    from ai import factory

    nowhere = "http://127.0.0.1:9"
    # Nor our SearXNG, whatever the developer's .env says.
    settings.RECIPE_SEARCH = "studio"
    settings.SEARXNG_URL = nowhere
    settings.AI = {
        **settings.AI,
        "CHAT": {**settings.AI["CHAT"], "BASE_URL": nowhere},
        "EMBEDDINGS": {**settings.AI["EMBEDDINGS"], "BASE_URL": nowhere},
    }
    cached = [getattr(factory, name) for name in dir(factory) if name.startswith("get_")]
    for function in cached:
        if hasattr(function, "cache_clear"):
            function.cache_clear()
    yield
    for function in cached:
        if hasattr(function, "cache_clear"):
            function.cache_clear()


@pytest.fixture(autouse=True)
def realtime_events(monkeypatch):
    """Real-time events are recorded instead of sent: tests never reach Redis."""
    sent = []
    monkeypatch.setattr(
        "apps.realtime.events._emit", lambda event, data, room: sent.append((room, event, data))
    )
    return sent


@pytest.fixture
def user(db):
    return get_user_model().objects.create_user("alice", password="pw")


@pytest.fixture
def team(user):
    team = Team.objects.create(name="Test team")
    Membership.objects.create(user=user, team=team, role=Membership.Role.OWNER)
    return team


@pytest.fixture
def api(user):
    client = APIClient()
    client.force_authenticate(user)
    return client


@pytest.fixture
def pasta_recipe(db):
    pasta = Ingredient.objects.create(name="Spaghetti", category=IngredientCategory.CEREAL)
    tomato = Ingredient.objects.create(
        name="tomato", category=IngredientCategory.VEGETABLE, season_months=[6, 7, 8, 9]
    )
    salt = Ingredient.objects.create(name="salt", category=IngredientCategory.CONDIMENT)
    recipe = Recipe.objects.create(title="Spaghetti al pomodoro", servings=2)
    RecipeIngredient.objects.create(recipe=recipe, ingredient=pasta, quantity=Decimal("160"))
    RecipeIngredient.objects.create(recipe=recipe, ingredient=tomato, quantity=Decimal("300"))
    RecipeIngredient.objects.create(recipe=recipe, ingredient=salt, unit=Unit.TO_TASTE)
    return recipe


@pytest.fixture
def member(team):
    """A second user of the team, with the plain member role."""
    user = get_user_model().objects.create_user("bob", email="bob@example.com", first_name="Bob")
    membership = Membership.objects.create(user=user, team=team, role=Membership.Role.MEMBER)
    client = APIClient()
    client.force_authenticate(user)
    return membership, client
