import datetime as dt
import importlib

from django.contrib.auth import get_user_model
from rest_framework.test import APIClient

from apps.menus.models import SystemRule, TeamRule, WeeklyMenu
from apps.teams.models import Membership, Team

MONDAY = dt.date(2026, 10, 5)


def other_team_rule():
    stranger = get_user_model().objects.create_user("carol", password="pw")
    team = Team.objects.create(name="Other team")
    Membership.objects.create(user=stranger, team=team, role=Membership.Role.OWNER)
    return TeamRule.objects.create(team=team, text="Always soup")


def seed_system_rules():
    from django.apps import apps

    module = importlib.import_module("apps.menus.migrations.0007_seed_system_rules")
    module.seed(apps, None)
    return module


def test_shipped_system_rules_are_seeded(db):
    module = seed_system_rules()
    codes = [code for code, _, _ in module.RULES]
    assert list(SystemRule.objects.values_list("code", flat=True)) == codes
    assert "healthy_plate" in codes


def test_seeding_again_keeps_live_changes(db):
    rule = SystemRule.objects.get(code="season")
    rule.text_it = "Solo ingredienti di stagione."
    rule.active = False
    rule.save()
    SystemRule.objects.filter(code="discover").delete()
    seed_system_rules()
    rule.refresh_from_db()
    assert (rule.text_it, rule.active) == ("Solo ingredienti di stagione.", False)
    assert SystemRule.objects.filter(code="discover").count() == 1
    assert SystemRule.objects.filter(code="variety").count() == 1


def test_users_read_the_active_system_rules(api, db):
    SystemRule.objects.filter(code="season").update(active=False)
    codes = [rule["code"] for rule in api.get("/api/system-rules/").json()]
    assert "season" not in codes and "variety" in codes


def test_only_staff_change_system_rules(api, user):
    rule = SystemRule.objects.get(code="season")
    assert api.patch(f"/api/system-rules/{rule.pk}/", {"active": False}).status_code == 403
    assert api.post("/api/system-rules/", {"text_it": "x", "text_en": "x"}).status_code == 403
    user.is_staff = True
    user.save()
    assert api.patch(f"/api/system-rules/{rule.pk}/", {"active": False}).status_code == 200
    # Staff see the switched-off rules too, to switch them back on.
    assert rule.code in [r["code"] for r in api.get("/api/system-rules/").json()]


def test_staff_add_and_delete_their_own_rules(api, user):
    user.is_staff = True
    user.save()
    created = api.post(
        "/api/system-rules/",
        {"text_it": " Niente  fritti ", "text_en": "No fried food", "position": 75, "code": "x"},
        format="json",
    )
    assert created.status_code == 201
    assert (created.json()["text_it"], created.json()["code"]) == ("Niente fritti", None)
    assert api.delete(f"/api/system-rules/{created.json()['id']}/").status_code == 204


def test_shipped_system_rules_are_not_deleted(api, user):
    user.is_staff = True
    user.save()
    rule = SystemRule.objects.get(code="variety")
    assert api.delete(f"/api/system-rules/{rule.pk}/").status_code == 400
    assert SystemRule.objects.filter(pk=rule.pk).exists()


def test_a_system_rule_needs_both_texts(api, user):
    user.is_staff = True
    user.save()
    response = api.post("/api/system-rules/", {"text_it": "Niente fritti", "text_en": "  "})
    assert response.status_code == 400


def test_owners_write_team_rules(api, team):
    created = api.post(
        "/api/team-rules/", {"team": team.pk, "text": "  Fish   twice a week "}, format="json"
    )
    assert created.status_code == 201
    assert created.json()["text"] == "Fish twice a week"
    rule_id = created.json()["id"]
    assert api.patch(f"/api/team-rules/{rule_id}/", {"text": "Fish once"}).status_code == 200
    assert [r["text"] for r in api.get(f"/api/team-rules/?team={team.pk}").json()["results"]] == [
        "Fish once"
    ]
    assert api.delete(f"/api/team-rules/{rule_id}/").status_code == 204


def test_a_rule_needs_text(api, team):
    response = api.post("/api/team-rules/", {"team": team.pk, "text": "   "}, format="json")
    assert response.status_code == 400


def test_members_read_team_rules_but_do_not_write_them(team, member):
    _, client = member
    rule = TeamRule.objects.create(team=team, text="Pizza on friday")
    assert [r["id"] for r in client.get(f"/api/team-rules/?team={team.pk}").json()["results"]] == [
        rule.pk
    ]
    assert client.post("/api/team-rules/", {"team": team.pk, "text": "x"}).status_code == 403
    assert client.patch(f"/api/team-rules/{rule.pk}/", {"text": "x"}).status_code == 403
    assert client.delete(f"/api/team-rules/{rule.pk}/").status_code == 403


def test_another_teams_rules_are_invisible(api, team):
    rule = other_team_rule()
    assert api.get("/api/team-rules/").json()["results"] == []
    assert api.get(f"/api/team-rules/{rule.pk}/").status_code == 404


def test_a_rule_stays_with_its_team(api, team, user):
    other = Team.objects.create(name="Second team")
    Membership.objects.create(user=user, team=other, role=Membership.Role.OWNER)
    rule = TeamRule.objects.create(team=team, text="Pizza on friday")
    response = api.patch(f"/api/team-rules/{rule.pk}/", {"team": other.pk}, format="json")
    assert response.status_code == 400


def test_week_settings_create_the_menu(api, team):
    rule = TeamRule.objects.create(team=team, text="Pizza on friday")
    response = api.post(
        "/api/menus/",
        {
            "team": team.pk,
            "week_start": MONDAY.isoformat(),
            "instructions": "  Thursday dinner we are five  ",
            "use_team_rules": True,
            "excluded_rules": [rule.pk],
        },
        format="json",
    )
    assert response.status_code == 201
    menu = WeeklyMenu.objects.get(team=team, week_start=MONDAY)
    assert menu.instructions == "Thursday dinner we are five"
    assert list(menu.excluded_rules.all()) == [rule]
    assert menu.slots.count() == 14


def test_menus_are_found_by_team_and_week(api, team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    found = api.get(f"/api/menus/?team={team.pk}&week_start={MONDAY}").json()["results"]
    assert [m["id"] for m in found] == [menu.pk]
    next_week = MONDAY + dt.timedelta(7)
    assert api.get(f"/api/menus/?team={team.pk}&week_start={next_week}").json()["results"] == []
    assert api.get(f"/api/menus/?team={team.pk}&week_start=nonsense").json()["results"] == []


def test_members_change_the_week_settings(team, member):
    _, client = member
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    response = client.patch(
        f"/api/menus/{menu.pk}/", {"use_team_rules": False, "instructions": "No fish"}
    )
    assert response.status_code == 200
    menu.refresh_from_db()
    assert (menu.use_team_rules, menu.instructions) == (False, "No fish")


def test_a_week_cannot_exclude_another_teams_rule(api, team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    rule = other_team_rule()
    response = api.patch(f"/api/menus/{menu.pk}/", {"excluded_rules": [rule.pk]}, format="json")
    assert response.status_code == 400


def test_a_menu_stays_on_its_week(api, team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    next_week = MONDAY + dt.timedelta(7)
    response = api.patch(f"/api/menus/{menu.pk}/", {"week_start": next_week.isoformat()})
    assert response.status_code == 400


def test_week_instructions_have_a_limit(api, team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    response = api.patch(f"/api/menus/{menu.pk}/", {"instructions": "x" * 2001})
    assert response.status_code == 400


def test_the_rationale_is_not_written_through_the_api(api, team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    api.patch(f"/api/menus/{menu.pk}/", {"rationale": "made up"})
    menu.refresh_from_db()
    assert menu.rationale == ""


def test_another_teams_client_cannot_see_the_menu(team):
    menu = WeeklyMenu.objects.create(team=team, week_start=MONDAY)
    stranger = get_user_model().objects.create_user("dave", password="pw")
    client = APIClient()
    client.force_authenticate(stranger)
    assert client.get(f"/api/menus/{menu.pk}/").status_code == 404
