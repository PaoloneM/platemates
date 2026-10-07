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
