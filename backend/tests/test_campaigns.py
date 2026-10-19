"""Campaigns: planning dishes in bulk, the links found, ingredient proposals, and publishing
the drafts that meet the bar without staff."""

from decimal import Decimal

import pytest
from django.core.management import call_command

from ai import AIError
from apps.catalog.models import Ingredient
from apps.curation import campaigns, drafting, ingredients, jobs, publishing
from apps.curation.models import Campaign, IngredientProposal, SourceSite, SystemDraft
from apps.recipes.models import Recipe
from apps.siteconfig.models import ConfigVar
from apps.teams.models import RecipeBookEntry, Team
from tests.test_curation import DRAFT, FakeChat, source


@pytest.fixture
def staff(api, user):
    user.is_staff = True
    user.save()
    return api


@pytest.fixture
def cavolo(db):
    return Ingredient.objects.create(name="cavolo nero", category="vegetable")


@pytest.fixture
def campaign(db):
    return Campaign.objects.create(
        name="Autunno",
        brief="Ricette semplici di tutti i giorni.",
        targets=[
            {"key": "primi", "theme": "primi piatti autunnali", "count": 2},
            {"key": "zuppe", "theme": "zuppe", "count": 1},
        ],
    )


def campaign_draft(of, **extra):
    values = {
        "dish": "ribollita",
        "status": SystemDraft.Status.READY,
        "draft": DRAFT,
        "reliability": "high",
        "web_rating": Decimal("4.40"),
        "web_rating_count": 55,
        "campaign": of,
        "target": "zuppe",
        **extra,
    }
    return SystemDraft.objects.create(**values)


# -- sources and links -------------------------------------------------------------------------


def test_trusted_sites_go_first_and_blocked_ones_are_never_used(db):
    sites = [
        SourceSite.objects.get(domain="giallozafferano.it"),
        SourceSite.objects.get(domain="pinterest.it"),
    ]
    chat = FakeChat(
        "https://www.pinterest.it/pin/1 https://blog.it/r https://ricette.giallozafferano.it/r "
        "https://blog.it/r2 https://altro.it/r https://ultimo.it/r"
    )
    pages = {
        "https://blog.it/r": source("blog.it", ["cavolo"]),
        "https://ricette.giallozafferano.it/r": source("ricette.giallozafferano.it", ["cavolo"]),
    }
    found, links = drafting.search_sources("ribollita", chat, pages.get, sites)
    assert [s.site for s in found] == ["ricette.giallozafferano.it", "blog.it"]
    assert "giallozafferano.it" in chat.calls[0][0]["content"]
    assert [(link["site"], link["outcome"]) for link in links] == [
        ("ricette.giallozafferano.it", "used"),
        ("pinterest.it", "blocked"),
        ("blog.it", "used"),
        ("blog.it", "not_checked"),
        ("altro.it", "not_checked"),
        ("ultimo.it", "not_checked"),
    ]
    assert links[0]["trusted"] and not links[2]["trusted"]


def test_a_draft_keeps_the_links_it_was_offered(db):
    draft = SystemDraft.objects.create(dish="ribollita", status=SystemDraft.Status.RUNNING)
    search = FakeChat("https://a.it/r https://b.it/r")
    jobs.run_draft(
        draft,
        chat=FakeChat(DRAFT, {"ingredients": []}),
        search_chat=search,
        verify={"https://a.it/r": source("a.it", ["cavolo nero"])}.get,
    )
    assert list(draft.links.values_list("site", "outcome")) == [
        ("a.it", "used"),
        ("b.it", "rejected"),
    ]


# -- ingredient proposals ----------------------------------------------------------------------


def test_unknown_ingredients_become_proposals_once(campaign, cavolo):
    pomodoro = Ingredient.objects.create(name="pomodoro", category="vegetable")
    draft = campaign_draft(
        campaign,
        draft={
            **DRAFT,
            "ingredients": [
                {**DRAFT["ingredients"][0]},
                {**DRAFT["ingredients"][0], "name": "pomodori"},
                {**DRAFT["ingredients"][0], "name": "lemongrass", "category": "other"},
            ],
        },
    )
    chat = FakeChat(
        {
            "ingredients": [
                {
                    "name": "pomodori",
                    "action": "alias",
                    "alias_of": pomodoro.pk,
                    "category": "vegetable",
                    "default_unit": "g",
                    "basic": False,
                },
                {
                    "name": "lemongrass",
                    "action": "new",
                    "category": "vegetable",
                    "season_months": [6, 7, 8],
                    "default_unit": "pc",
                    "basic": False,
                },
            ]
        }
    )
    ingredients.propose_for(draft, chat)
    alias = IngredientProposal.objects.get(name="pomodori")
    new = IngredientProposal.objects.get(name="lemongrass")
    assert (alias.action, alias.alias_of) == ("alias", pomodoro)
    assert (new.action, new.category, new.season_months, new.default_unit) == (
        "new",
        "vegetable",
        [6, 7, 8],
        "pc",
    )
    # Another draft using the same names: no new question to the model.
    other = campaign_draft(campaign, draft=draft.draft, dish="altra")
    ingredients.propose_for(other, FakeChat())
    assert IngredientProposal.objects.count() == 2
    assert set(other.ingredient_proposals.values_list("name", flat=True)) == {
        "pomodori",
        "lemongrass",
    }
    assert ingredients.unresolved(other) == ["pomodori", "lemongrass"]


def test_an_alias_must_be_one_of_the_offered_entries_and_the_model_may_fail(campaign):
    draft = campaign_draft(campaign)
    ingredients.propose_for(draft, FakeChat(AIError("down")))
    proposal = IngredientProposal.objects.get()
    # The draft's own guess: a new vegetable in season in winter.
    assert (proposal.name, proposal.action, proposal.category, proposal.season_months) == (
        "cavolo nero",
        "new",
        "vegetable",
        [1, 2, 11, 12],
    )


def test_approving_puts_the_proposal_in_the_catalog(user):
    pomodoro = Ingredient.objects.create(name="pomodoro", category="vegetable")
    alias = IngredientProposal.objects.create(name="pomodori", action="alias", alias_of=pomodoro)
    new = IngredientProposal.objects.create(
        name="zenzero",
        category="vegetable",
        default_unit="g",
        season_months=[],
        edited=["category"],
        basic=False,
    )
    assert ingredients.approve(alias, user) == pomodoro
    pomodoro.refresh_from_db()
    assert "pomodori" in pomodoro.aliases
    ginger = ingredients.approve(new, user)
    assert ginger.owner_team is None and ginger.category == "vegetable"
    assert ginger.provenance == {"category": "user", "season_months": "llm", "default_unit": "llm"}
    new.refresh_from_db()
    assert (new.status, new.ingredient, new.decided_by) == ("approved", ginger, user)


# -- publishing automatically ------------------------------------------------------------------


def test_a_draft_that_meets_the_bar_is_published(
    campaign, cavolo, django_capture_on_commit_callbacks
):
    draft = campaign_draft(campaign)
    with django_capture_on_commit_callbacks(execute=True):
        recipe = publishing.auto_publish(draft)
    assert recipe is not None and recipe.owner_team == Team.system()
    assert recipe.title == "Ribollita" and recipe.web_rating == Decimal("4.40")
    assert recipe.provenance["course"] == "llm" and recipe.cuisine.name == "Toscana"
    assert [line.ingredient for line in recipe.ingredients.all()] == [cavolo]
    assert RecipeBookEntry.objects.filter(team=Team.system(), recipe=recipe).exists()
    draft.refresh_from_db()
    assert (draft.status, draft.recipe, draft.published_automatically) == (
        "published",
        recipe,
        True,
    )


@pytest.mark.parametrize(
    "change,reason",
    [
        ({"reliability": "medium"}, "reliability"),
        ({"web_rating": Decimal("3.90")}, "rating"),
        ({"web_rating": None, "web_rating_count": None}, "rating"),
        ({"web_rating_count": 2}, "votes"),
        ({"campaign": None}, "not_campaign"),
    ],
)
def test_a_draft_below_the_bar_waits_for_staff(campaign, cavolo, change, reason):
    draft = campaign_draft(campaign, **change)
    assert reason in publishing.blockers(draft)
    assert publishing.auto_publish(draft) is None
    draft.refresh_from_db()
    assert draft.status == "ready"


def test_the_bar_is_a_setting(campaign, cavolo):
    ConfigVar.objects.create(key="curation.min_reliability", value="medium")
    assert publishing.blockers(campaign_draft(campaign, reliability="medium")) == []
    ConfigVar.objects.create(key="curation.auto_publish", value=False)
    assert publishing.auto_publish(campaign_draft(campaign, reliability="medium")) is None


def test_a_title_already_published_is_not_published_twice(campaign, cavolo):
    publishing.auto_publish(campaign_draft(campaign))
    assert publishing.blockers(campaign_draft(campaign)) == ["duplicate"]


def test_approving_the_last_ingredient_publishes_the_waiting_draft(staff, campaign):
    draft = campaign_draft(campaign)
    ingredients.propose_for(draft, FakeChat(AIError("down")))
    assert publishing.blockers(draft) == ["ingredients"]
    proposal = IngredientProposal.objects.get()
    response = staff.post(
        "/api/ingredient-proposals/approve/", {"ids": [proposal.pk]}, format="json"
    )
    assert response.json() == {"published": 1}
    draft.refresh_from_db()
    assert draft.status == "published"
    assert Recipe.objects.get(pk=draft.recipe_id).ingredients.get().ingredient.name == "cavolo nero"


# -- planning ----------------------------------------------------------------------------------


def test_planning_fills_targets_and_never_asks_twice_for_a_dish(campaign):
    SystemDraft.objects.create(dish="Ribollita")
    chat = FakeChat({"dishes": ["Pasta e zucca", "ribollita", "Risotto ai funghi"]})
    assert campaigns.plan(campaign, chat) == 2
    assert "Ribollita" in chat.calls[0][0]["content"]
    assert "Ricette semplici" in chat.calls[0][0]["content"]
    assert set(campaign.drafts.values_list("dish", "target")) == {
        ("Pasta e zucca", "primi"),
        ("Risotto ai funghi", "primi"),
    }
    assert campaigns.needs(campaign) == {"zuppe": 1}


def test_failed_drafts_are_replaced_up_to_twice_the_count(campaign):
    for n in range(3):
        campaign_draft(campaign, dish=f"zuppa {n}", status=SystemDraft.Status.FAILED)
    assert campaigns.needs(campaign) == {"primi": 2}  # zuppe: 3 of 2 attempts used
    campaign_draft(campaign, dish="primo 1", target="primi", status=SystemDraft.Status.FAILED)
    assert campaigns.needs(campaign) == {"primi": 2}


def test_a_target_without_new_dishes_stops_and_a_campaign_ends(campaign):
    campaigns.plan(campaign, FakeChat({"dishes": []}))
    assert campaign.notes == {"primi": "exhausted"}
    campaigns.plan(campaign, FakeChat({"dishes": ["Minestrone"]}))
    assert campaigns.needs(campaign) == {}
    assert campaigns.next_to_plan() is None
    campaign.refresh_from_db()
    assert campaign.status == "running"  # its draft is still queued
    campaign.drafts.update(status=SystemDraft.Status.READY)
    assert campaigns.next_to_plan() is None
    campaign.refresh_from_db()
    assert campaign.status == "done"


def test_a_paused_campaigns_drafts_wait(campaign):
    draft = SystemDraft.objects.create(dish="minestrone", campaign=campaign, target="zuppe")
    campaign.status = Campaign.Status.PAUSED
    campaign.save()
    assert jobs.claim_next() is None
    campaign.status = Campaign.Status.RUNNING
    campaign.save()
    assert jobs.claim_next() == draft


def test_the_worker_plans_when_no_draft_waits(campaign, monkeypatch):
    planned = []
    monkeypatch.setattr(campaigns, "plan", lambda c, chat: planned.append(c.pk) or 0)
    monkeypatch.setattr("apps.menus.management.commands.worker.get_chat_provider", lambda: None)
    call_command("worker", "--once")
    assert planned == [campaign.pk]


# -- API ---------------------------------------------------------------------------------------


def test_only_staff_run_campaigns(api, db):
    assert api.get("/api/campaigns/").status_code == 403
    assert api.get("/api/ingredient-proposals/").status_code == 403
    assert api.get("/api/source-sites/").status_code == 403


def test_staff_start_and_follow_a_campaign(staff, cavolo):
    body = {
        "name": "Catalogo",
        "brief": "Semplici",
        "targets": [{"key": "Primi", "theme": "primi", "count": 3}],
    }
    response = staff.post("/api/campaigns/", body, format="json")
    assert response.status_code == 201
    campaign = Campaign.objects.get()
    assert campaign.targets == [{"key": "primi", "theme": "primi", "count": 3}]
    publishing.auto_publish(campaign_draft(campaign, target="primi"))
    campaign_draft(campaign, target="primi", dish="x", status=SystemDraft.Status.FAILED)
    detail = staff.get(f"/api/campaigns/{campaign.pk}/").json()
    assert detail["progress"]["primi"]["published"] == 1
    assert detail["progress"]["primi"]["automatic"] == 1
    assert detail["progress"]["primi"]["failed"] == 1
    assert len(detail["recipe_ids"]) == 1
    assert staff.post(f"/api/campaigns/{campaign.pk}/pause/").json()["status"] == "paused"
    assert staff.post(f"/api/campaigns/{campaign.pk}/resume/").json()["status"] == "running"


@pytest.mark.parametrize(
    "targets",
    [
        [],
        [{"key": "a", "theme": "", "count": 1}],
        [{"key": "a", "theme": "x", "count": 0}],
        [{"key": "a", "theme": "x", "count": 1}, {"key": "a", "theme": "y", "count": 1}],
    ],
)
def test_campaign_targets_are_validated(staff, targets):
    body = {"name": "x", "targets": targets}
    assert staff.post("/api/campaigns/", body, format="json").status_code == 400


def test_staff_edit_a_proposal_before_approving(staff):
    proposal = IngredientProposal.objects.create(name="zenzero", category="other", default_unit="g")
    response = staff.patch(
        f"/api/ingredient-proposals/{proposal.pk}/",
        {"category": "vegetable", "default_unit": "g"},
        format="json",
    )
    assert response.json()["edited"] == ["category"]
    alias = staff.patch(
        f"/api/ingredient-proposals/{proposal.pk}/", {"action": "alias"}, format="json"
    )
    assert alias.status_code == 400  # an alias of what?
    staff.post("/api/ingredient-proposals/reject/", {"ids": [proposal.pk]}, format="json")
    assert staff.get("/api/ingredient-proposals/").json() == []
    assert staff.get("/api/ingredient-proposals/?status=rejected").json()[0]["name"] == "zenzero"


def test_staff_manage_the_sites(staff):
    response = staff.post(
        "/api/source-sites/", {"domain": "https://www.Ricette.it/x", "trusted": True}, format="json"
    )
    assert response.json()["domain"] == "ricette.it"
    domains = [s["domain"] for s in staff.get("/api/source-sites/").json()]
    assert "giallozafferano.it" in domains and "ricette.it" in domains
