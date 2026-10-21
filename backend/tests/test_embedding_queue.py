"""Embeddings are computed by the worker, never while a save waits."""

from django.core.management import call_command

from apps.catalog.services import recompute_recipes
from apps.curation.models import SystemDraft
from apps.recipes import embeddings
from apps.recipes.models import PendingEmbedding, RecipeEmbedding
from apps.recipes.serializers import RecipeSerializer


class FakeEmbeddings:
    model = "fake-embed"

    def __init__(self):
        self.calls = 0

    def embed(self, texts):
        self.calls += 1
        return [[0.1] * 1536 for _ in texts]


def test_saving_a_recipe_only_queues_it(
    pasta_recipe, monkeypatch, django_capture_on_commit_callbacks
):
    monkeypatch.setattr(
        embeddings,
        "get_embedding_provider",
        lambda: (_ for _ in ()).throw(AssertionError("called")),
    )
    with django_capture_on_commit_callbacks(execute=True):
        RecipeSerializer._derive(pasta_recipe)
        RecipeSerializer._derive(pasta_recipe)
    assert list(PendingEmbedding.objects.values_list("recipe_id", flat=True)) == [pasta_recipe.pk]


def test_an_ingredient_change_queues_its_recipes(pasta_recipe, django_capture_on_commit_callbacks):
    tomato = pasta_recipe.ingredients.get(ingredient__name="tomato").ingredient
    with django_capture_on_commit_callbacks(execute=True):
        recompute_recipes(tomato)
    assert PendingEmbedding.objects.filter(recipe=pasta_recipe).exists()


def test_the_worker_embeds_the_queue(pasta_recipe, monkeypatch, django_capture_on_commit_callbacks):
    provider = FakeEmbeddings()
    monkeypatch.setattr(embeddings, "get_embedding_provider", lambda: provider)
    with django_capture_on_commit_callbacks(execute=True):
        embeddings.queue([pasta_recipe])
    assert embeddings.embed_pending() == 1
    assert provider.calls == 1 and not PendingEmbedding.objects.exists()
    assert RecipeEmbedding.objects.filter(recipe=pasta_recipe, model="fake-embed").exists()
    assert embeddings.embed_pending() == 0


def test_an_unavailable_service_empties_the_queue_without_failing(
    pasta_recipe, django_capture_on_commit_callbacks
):
    # The configured provider points nowhere in tests (conftest): the call fails, quietly.
    with django_capture_on_commit_callbacks(execute=True):
        embeddings.queue([pasta_recipe])
    assert embeddings.embed_pending() == 1
    assert not RecipeEmbedding.objects.exists() and not PendingEmbedding.objects.exists()


def test_the_worker_embeds_before_drafting(
    pasta_recipe, monkeypatch, django_capture_on_commit_callbacks
):
    order = []
    SystemDraft.objects.create(dish="ribollita")
    with django_capture_on_commit_callbacks(execute=True):
        embeddings.queue([pasta_recipe])
    monkeypatch.setattr(
        embeddings,
        "embed_pending",
        lambda: order.append("embed") or (PendingEmbedding.objects.all().delete()[0]),
    )
    monkeypatch.setattr("apps.curation.jobs.run_draft", lambda d, **kw: order.append("draft"))
    call_command("worker", "--once")
    assert order.index("embed") < order.index("draft")
