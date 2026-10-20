"""Export and import: moving recipes, ingredients, a team or the system data between
installations, without duplicates and without losing links."""

import datetime as dt
import io
import json

import pytest

from apps.accounts.models import UserProfile
from apps.catalog.models import Ingredient, IngredientCategory, KitchenTool
from apps.menus.models import MealSlot, SlotDish, SystemRule, TeamRule, WeeklyMenu
from apps.recipes.models import Cuisine, Recipe, RecipeIngredient, Visibility
from apps.teams.models import CalendarDay, Member, Preference, RecipeBookEntry, Team
from apps.transfer import jobs
from apps.transfer.exporting import export_recipes, export_system, export_team
from apps.transfer.importing import TransferError, import_document
from apps.transfer.models import ImportJob

MONDAY = dt.date(2026, 10, 5)


@pytest.fixture(autouse=True)
def no_embeddings(monkeypatch):
    monkeypatch.setattr("apps.recipes.embeddings.refresh_embedding", lambda recipe: True)


@pytest.fixture
def admin(user):
    UserProfile.objects.create(user=user, is_admin=True)
    return user


@pytest.fixture
def world(team):
    """A team with everything an export carries: people, tastes, rules, a calendar, its own
    recipe with its own ingredient, a version of a system recipe, a menu."""
    tomato = Ingredient.objects.create(name="pomodoro", category=IngredientCategory.VEGETABLE)
    squash = Ingredient.objects.create(name="zucca di casa", owner_team=team)
    oven = KitchenTool.objects.create(name="Forno a legna")
    italian = Cuisine.objects.create(name="Italiana")
    system = Recipe.objects.create(title="Minestrone", owner_team=Team.system())
    RecipeIngredient.objects.create(recipe=system, ingredient=tomato, quantity=200, unit="g")
    own = Recipe.objects.create(
        title="Zuppa di zucca",
        owner_team=team,
        visibility=Visibility.PRIVATE,
        cuisine=italian,
        steps=["Taglia.", "Cuoci."],
        provenance={"season_months": "user"},
    )
    own.tools.set([oven])
    RecipeIngredient.objects.create(recipe=own, ingredient=squash, quantity="500.00", unit="g")
    RecipeIngredient.objects.create(recipe=own, ingredient=tomato, quantity=None, unit="tt")
    version = Recipe.objects.create(title="Minestrone nostro", owner_team=team, derived_from=system)
    for recipe in (own, version, system):
        RecipeBookEntry.objects.create(team=team, recipe=recipe, status="approved", rating=4)
    anna = Member.objects.create(team=team, name="Anna", birth_year=1990)
    Preference.objects.create(team=team, member=anna, kind="avoids", ingredient=squash)
    Preference.objects.create(team=team, kind="loves", cuisine=italian)
    rule = TeamRule.objects.create(team=team, text="Pesce il venerdì")
    CalendarDay.objects.create(team=team, date=MONDAY, people={"lunch": 1}, note="gita")
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY, rationale="varietà")
    menu.excluded_rules.set([rule])
    slot = MealSlot.objects.create(menu=menu, date=MONDAY, meal="dinner", people=3, rating=5)
    SlotDish.objects.create(slot=slot, recipe=own, position=0)
    SlotDish.objects.create(slot=slot, title="Pane", position=1)
    return {"team": team, "own": own, "version": version, "system": system, "squash": squash}


def forget_team(team: Team) -> None:
    """As if on another installation: the team's data is gone, the shared data is there."""
    WeeklyMenu.objects.filter(team=team).delete()  # its dishes protect the recipes they use
    Recipe.objects.filter(owner_team=team).delete()
    Ingredient.objects.filter(owner_team=team).delete()
    team.delete()


def created(report):
    return dict(report.created)


# -- a whole team ------------------------------------------------------------------------------


def test_a_team_moves_with_everything_it_has(user, world):
    document = json.loads(json.dumps(export_team(world["team"])))  # through a real file
    forget_team(world["team"])

    report = import_document(document, user=user)

    team = Team.objects.get(name="Test team")
    assert report.teams == [{"file": "Test team", "into": "Test team", "new": True}]
    assert team.memberships.get().user == user
    own = Recipe.objects.get(title="Zuppa di zucca")
    assert own.owner_team == team and own.visibility == "private"
    assert own.cuisine.name == "Italiana" and own.steps == ["Taglia.", "Cuoci."]
    assert own.provenance == {"season_months": "user"}
    assert [t.name for t in own.tools.all()] == ["Forno a legna"]
    lines = {line.ingredient.name: line for line in own.ingredients.all()}
    assert lines["zucca di casa"].ingredient.owner_team == team
    assert str(lines["zucca di casa"].quantity) == "500.00"
    assert lines["pomodoro"].ingredient.owner_team is None and lines["pomodoro"].quantity is None
    # The version is linked again to the system recipe it came from.
    assert Recipe.objects.get(title="Minestrone nostro").derived_from == world["system"]
    assert set(team.recipe_book.values_list("recipe__title", "rating")) == {
        ("Zuppa di zucca", 4),
        ("Minestrone nostro", 4),
        ("Minestrone", 4),
    }
    anna = team.members.get()
    assert (anna.name, anna.birth_year) == ("Anna", 1990)
    assert team.preferences.get(member=anna).ingredient.name == "zucca di casa"
    assert team.preferences.get(member=None).cuisine.name == "Italiana"
    assert team.calendar_days.get().note == "gita"
    menu = team.menus.get()
    assert menu.rationale == "varietà" and [r.text for r in menu.excluded_rules.all()] == [
        "Pesce il venerdì"
    ]
    slot = menu.slots.get()
    assert (slot.people, slot.rating) == (3, 5)
    assert [
        (d.recipe and d.recipe.title, d.title) for d in slot.slot_dishes.order_by("position")
    ] == [
        ("Zuppa di zucca", ""),
        (None, "Pane"),
    ]
    assert report.warnings == []


def test_importing_the_same_file_again_changes_nothing(user, world):
    document = export_team(world["team"])
    forget_team(world["team"])
    import_document(document, user=user)
    counts = (Recipe.objects.count(), Ingredient.objects.count(), Team.objects.count())

    again = import_document(document, user=user)

    assert created(again) == {}
    assert (Recipe.objects.count(), Ingredient.objects.count(), Team.objects.count()) == counts


def test_a_team_can_go_into_an_existing_one(user, world):
    document = export_team(world["team"])
    forget_team(world["team"])
    # On the new server, the team was created for the same people before the import.
    target = Team.objects.create(name="The Morgan's")

    report = import_document(document, user=user, target_team=target)

    assert report.teams == [{"file": "Test team", "into": "The Morgan's", "new": False}]
    assert Recipe.objects.get(title="Zuppa di zucca").owner_team == target
    assert Ingredient.objects.get(name="zucca di casa").owner_team == target
    assert target.members.count() == 1 and target.menus.count() == 1


def test_the_preview_changes_nothing_and_says_what_would_happen(user, world):
    document = export_team(world["team"])
    forget_team(world["team"])

    report = import_document(document, user=user, dry_run=True)

    assert report.dry_run is True
    assert created(report)["recipes"] == 2 and created(report)["teams"] == 1
    assert not Team.objects.filter(name="Test team").exists()
    assert not Recipe.objects.filter(title="Zuppa di zucca").exists()


def test_existing_objects_are_skipped_unless_asked_to_update(user, world):
    document = export_team(world["team"])
    own = world["own"]
    own.title = "Zuppa cambiata qui"
    own.save()

    skipped = import_document(document, user=user)
    assert skipped.skipped["recipes"] == 2
    assert Recipe.objects.get(pk=own.pk).title == "Zuppa cambiata qui"

    updated = import_document(document, user=user, mode="update")
    assert updated.updated["recipes"] == 2
    assert Recipe.objects.get(pk=own.pk).title == "Zuppa di zucca"
    assert Recipe.objects.get(pk=own.pk).ingredients.count() == 2


def test_book_recipes_missing_here_are_reported(user, world):
    document = export_team(world["team"])
    forget_team(world["team"])
    world["system"].delete()

    report = import_document(document, user=user)

    assert any("Minestrone" in w and "not here" in w for w in report.warnings)
    assert Recipe.objects.get(title="Minestrone nostro").derived_from is None


# -- the shared catalog ------------------------------------------------------------------------


def test_catalog_entries_are_matched_by_name_not_duplicated(user, world):
    document = export_system()
    # The other installation seeded the same catalog with its own identities.
    Ingredient.objects.filter(name="pomodoro").update(uid="00000000-0000-0000-0000-000000000001")

    report = import_document(document, user=user)

    assert Ingredient.objects.filter(name="pomodoro").count() == 1
    assert report.skipped["ingredients"] >= 1 and "ingredients" not in report.created


def test_system_data_moves_to_an_empty_installation(user, world):
    SystemRule.objects.create(text_it="Niente fritti", text_en="No fried food", position=9)
    Ingredient.objects.filter(name="pomodoro").update(basic=True)
    document = json.loads(json.dumps(export_system()))
    forget_team(world["team"])
    Recipe.objects.filter(owner_team__is_system=True).delete()
    RecipeIngredient.objects.all().delete()
    Ingredient.objects.all().delete()
    SystemRule.objects.filter(text_it="Niente fritti").delete()

    report = import_document(document, user=user)

    minestrone = Recipe.objects.get(title="Minestrone")
    assert minestrone.owner_team.is_system
    assert minestrone.ingredients.get().ingredient.name == "pomodoro"
    assert minestrone.ingredients.get().ingredient.basic
    assert SystemRule.objects.filter(text_it="Niente fritti").exists()
    assert report.created["recipes"] == 1


def test_a_foreign_file_is_refused(user):
    with pytest.raises(TransferError):
        import_document({"format": "something-else"}, user=user)
    with pytest.raises(TransferError):
        import_document({"format": "platemates-export", "version": 99}, user=user)


# -- the API -----------------------------------------------------------------------------------


def test_only_administrators_export_and_import(api, world):
    assert api.get(f"/api/transfer/export/?scope=team&team={world['team'].pk}").status_code == 403
    assert api.post("/api/transfer/import/", {}).status_code == 403
    assert api.get("/api/transfer/choices/").status_code == 403


def run_queued():
    while (job := jobs.claim_next()) is not None:
        jobs.run_job(job)


def test_administrators_download_and_preview_through_the_api(api, admin, world):
    response = api.get(f"/api/transfer/export/?scope=team&team={world['team'].pk}")
    assert response.status_code == 200
    assert 'filename="platemates-team-test-team-' in response["Content-Disposition"]
    upload = io.BytesIO(json.dumps(response.json()).encode())
    upload.name = "team.json"

    queued = api.post(
        "/api/transfer/import/", {"file": upload, "dry_run": "true"}, format="multipart"
    )
    assert queued.status_code == 202 and queued.json()["status"] == "queued"
    run_queued()
    preview = api.get(f"/api/transfer/jobs/{queued.json()['id']}/").json()

    assert preview["status"] == "done" and preview["report"]["dry_run"] is True
    assert preview["report"]["skipped"]["recipes"] == 2
    assert preview["report"]["document"]["scope"] == "team"
    choices = api.get("/api/transfer/choices/?search=zucca").json()
    assert [t["name"] for t in choices["teams"]] == ["Test team"]
    assert [r["title"] for r in choices["recipes"]] == ["Zuppa di zucca"]


def test_a_preview_is_imported_for_real_in_the_worker_with_its_progress(
    api, admin, world, realtime_events
):
    lone = Recipe.objects.create(
        title="Pappa al pomodoro", owner_team=Team.system(), visibility=Visibility.SHARED
    )
    document = export_recipes([lone.pk])
    lone.delete()
    upload = io.BytesIO(json.dumps(document).encode())
    upload.name = "recipes.json"
    preview = api.post("/api/transfer/import/", {"file": upload}, format="multipart").json()
    run_queued()
    real = api.post(f"/api/transfer/jobs/{preview['id']}/confirm/")
    assert real.status_code == 202 and real.json()["dry_run"] is False
    run_queued()
    job = ImportJob.objects.get(pk=real.json()["id"])
    assert job.status == "done" and job.report["created"]["recipes"] == 1
    assert job.document == {}  # imported for real: the file is not kept
    phases = [d["phase"] for room, event, d in realtime_events if event == "transfer"]
    assert "recipes" in phases and {
        room for room, event, _ in realtime_events if event == "transfer"
    } == {"admin"}
    # A preview already confirmed and emptied cannot be confirmed again; a real import never.
    assert api.post(f"/api/transfer/jobs/{real.json()['id']}/confirm/").status_code == 400


def test_a_file_that_is_not_an_export_is_refused_at_once(api, admin):
    upload = io.BytesIO(json.dumps({"format": "other"}).encode())
    upload.name = "x.json"
    response = api.post("/api/transfer/import/", {"file": upload}, format="multipart")
    assert response.status_code == 400 and not ImportJob.objects.exists()


def test_an_import_the_worker_dropped_is_marked_failed(admin):
    job = ImportJob.objects.create(status=ImportJob.Status.RUNNING, document={})
    assert jobs.fail_interrupted() == 1
    job.refresh_from_db()
    assert job.status == "failed"


def test_a_browser_opening_the_export_link_gets_the_file(api, admin, world):
    """A plain link asks for HTML: it must still get the JSON document, not DRF's page."""
    response = api.get(
        f"/api/transfer/export/?scope=team&team={world['team'].pk}",
        HTTP_ACCEPT="text/html,application/xhtml+xml,*/*;q=0.8",
    )
    assert response["Content-Type"] == "application/json"
    assert json.loads(response.content)["format"] == "platemates-export"
