import datetime as dt

import pytest

from apps.menus.models import WeeklyMenu
from apps.recipes.models import Visibility
from apps.teams.calendar import calendar
from apps.teams.models import CalendarDay, Membership, Team

MONDAY = dt.date(2026, 10, 5)


@pytest.fixture
def week(team):
    """Typical week: 2 at lunch and 3 at dinner every day, Sunday off."""
    team.typical_week[6]["active"] = False
    team.save()
    return team


def day_url(date, team):
    return f"/api/calendar/{date.isoformat()}/?team={team.pk}"


def test_calendar_follows_the_typical_week(api, week):
    days = api.get(f"/api/calendar/?team={week.pk}&start={MONDAY}&days=7").json()
    assert [d["date"] for d in days] == [str(MONDAY + dt.timedelta(n)) for n in range(7)]
    assert days[0]["people"] == {"breakfast": 0, "lunch": 2, "dinner": 3}
    assert days[0]["overridden"] == []
    assert days[6]["active"] is False
    assert days[6]["people"] == {"breakfast": 0, "lunch": 0, "dinner": 0}


def test_owners_set_exceptions_on_a_date(api, week):
    saturday = MONDAY + dt.timedelta(5)
    response = api.put(
        day_url(saturday, week),
        {"people": {"dinner": 6, "lunch": 2}, "note": "  Guests  for dinner "},
        format="json",
    )
    assert response.status_code == 200
    day = response.json()
    assert day["people"] == {"breakfast": 0, "lunch": 2, "dinner": 6}
    # Lunch equals the typical week: not an exception.
    assert day["overridden"] == ["dinner"]
    assert day["note"] == "Guests for dinner"
    assert CalendarDay.objects.get(team=week, date=saturday).people == {"dinner": 6}


def test_an_exception_can_open_a_day_off(api, week):
    sunday = MONDAY + dt.timedelta(6)
    day = api.put(day_url(sunday, week), {"people": {"lunch": 4}}, format="json").json()
    assert day["active"] is False
    assert day["people"]["lunch"] == 4


def test_back_to_the_typical_week(api, week):
    tuesday = MONDAY + dt.timedelta(1)
    api.put(day_url(tuesday, week), {"people": {"lunch": 0}}, format="json")
    assert CalendarDay.objects.filter(team=week).count() == 1
    # Setting the usual values without a note removes the row.
    api.put(day_url(tuesday, week), {"people": {"lunch": 2}}, format="json")
    assert not CalendarDay.objects.filter(team=week).exists()
    api.put(day_url(tuesday, week), {"people": {"lunch": 0}, "note": "Out"}, format="json")
    day = api.delete(day_url(tuesday, week)).json()
    assert day["overridden"] == [] and day["note"] == ""
    assert not CalendarDay.objects.filter(team=week).exists()


def test_members_read_the_calendar_but_do_not_change_it(week, member):
    _, client = member
    assert client.get(f"/api/calendar/?team={week.pk}&start={MONDAY}").status_code == 200
    response = client.put(day_url(MONDAY, week), {"people": {"lunch": 5}}, format="json")
    assert response.status_code == 403
    assert client.delete(day_url(MONDAY, week)).status_code == 403


def test_other_teams_calendars_are_not_found(week, member):
    membership, client = member
    membership.delete()
    assert client.get(f"/api/calendar/?team={week.pk}&start={MONDAY}").status_code == 404
    response = client.put(day_url(MONDAY, week), {"people": {"lunch": 5}}, format="json")
    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"people": {"brunch": 2}},
        {"people": {"lunch": -1}},
        {"people": {"lunch": 51}},
        {"people": {"lunch": "two"}},
        {"note": "x" * 201},
    ],
)
def test_exceptions_are_validated(api, week, body):
    assert api.put(day_url(MONDAY, week), body, format="json").status_code == 400


@pytest.mark.parametrize(
    "query", ["start=2026-13-01", "start=", "days=0", "days=63", "days=x", "team=x"]
)
def test_calendar_queries_are_validated(api, week, query):
    params = {"team": week.pk, "start": MONDAY, "days": 7}
    key, value = query.split("=")
    params[key] = value
    query_string = "&".join(f"{k}={v}" for k, v in params.items())
    assert api.get(f"/api/calendar/?{query_string}").status_code == 400


def test_menus_start_from_the_calendar(week):
    CalendarDay.objects.create(team=week, date=MONDAY, people={"dinner": 6, "breakfast": 4})
    CalendarDay.objects.create(team=week, date=MONDAY + dt.timedelta(6), people={"lunch": 4})
    menu = WeeklyMenu.objects.create(team=week, week_start=MONDAY)
    menu.create_empty_slots()
    people = {(s.date.weekday(), s.meal): s.people for s in menu.slots.all()}
    assert people[0, "dinner"] == 6
    assert people[0, "lunch"] == 2
    assert people[6, "lunch"] == 4
    assert people[6, "dinner"] == 0


def test_calendar_ignores_unknown_meals_in_stored_rows(week):
    CalendarDay.objects.create(team=week, date=MONDAY, people={"brunch": 9, "lunch": 1})
    assert calendar(week, MONDAY, 1)[0].people == {"breakfast": 0, "lunch": 1, "dinner": 3}


def test_owner_role_is_required_even_for_a_team_member(api, week, user):
    Membership.objects.filter(user=user).update(role=Membership.Role.MEMBER)
    assert api.put(day_url(MONDAY, week), {"people": {}}, format="json").status_code == 403


def test_changing_one_meal_keeps_the_other_exceptions(api, week):
    api.put(day_url(MONDAY, week), {"people": {"dinner": 6}, "note": "Guests"}, format="json")
    day = api.put(day_url(MONDAY, week), {"people": {"lunch": 0}}, format="json").json()
    assert day["people"] == {"breakfast": 0, "lunch": 0, "dinner": 6}
    assert day["note"] == "Guests"


def test_dishes_are_set_per_meal_and_create_the_weeks_menu(api, week, pasta_recipe):
    response = api.put(
        day_url(MONDAY, week), {"dishes": {"dinner": [pasta_recipe.pk]}}, format="json"
    )
    assert response.status_code == 200
    day = response.json()
    assert day["dishes"]["dinner"] == [
        {
            "recipe": pasta_recipe.pk,
            "title": pasta_recipe.title,
            "course": pasta_recipe.course,
            "proposed": False,
            "note": "",
        }
    ]
    assert day["dishes"]["lunch"] == []
    assert "breakfast" not in day["dishes"]
    menu = WeeklyMenu.objects.get(team=week, week_start=MONDAY)
    assert menu.slots.count() == 14
    # The week shows them too.
    days = api.get(f"/api/calendar/?team={week.pk}&start={MONDAY}").json()
    assert [d["title"] for d in days[0]["dishes"]["dinner"]] == [pasta_recipe.title]


def test_clearing_a_meal_sets_nobody_and_removes_its_dishes(api, week, pasta_recipe):
    api.put(day_url(MONDAY, week), {"dishes": {"dinner": [pasta_recipe.pk]}}, format="json")
    cleared = {"people": {"dinner": 0}, "dishes": {"dinner": []}}
    day = api.put(day_url(MONDAY, week), cleared, format="json").json()
    assert day["people"]["dinner"] == 0 and day["dishes"]["dinner"] == []
    slot = WeeklyMenu.objects.get(team=week).slots.get(date=MONDAY, meal="dinner")
    assert slot.people == 0
    # Undo: the client sends back what it had.
    restored = {"people": {"dinner": 3}, "dishes": {"dinner": [pasta_recipe.pk]}}
    day = api.put(day_url(MONDAY, week), restored, format="json").json()
    assert day["overridden"] == [] and len(day["dishes"]["dinner"]) == 1
    slot.refresh_from_db()
    assert slot.people == 3


def test_resetting_a_day_keeps_its_dishes_and_updates_the_menu(api, week, pasta_recipe):
    body = {"people": {"lunch": 5}, "dishes": {"lunch": [pasta_recipe.pk]}}
    api.put(day_url(MONDAY, week), body, format="json")
    day = api.delete(day_url(MONDAY, week)).json()
    assert day["people"]["lunch"] == 2 and len(day["dishes"]["lunch"]) == 1
    assert WeeklyMenu.objects.get(team=week).slots.get(date=MONDAY, meal="lunch").people == 2


@pytest.mark.parametrize(
    "dishes", [{"breakfast": []}, {"lunch": [999999]}, {"lunch": "x"}, {"lunch": ["x"]}]
)
def test_dishes_are_validated(api, week, dishes):
    response = api.put(day_url(MONDAY, week), {"dishes": dishes}, format="json")
    assert response.status_code == 400


def test_another_teams_private_recipe_cannot_be_planned(api, week, pasta_recipe):
    other = Team.objects.create(name="Other")
    pasta_recipe.owner_team = other
    pasta_recipe.visibility = Visibility.PRIVATE
    pasta_recipe.save()
    body = {"dishes": {"lunch": [pasta_recipe.pk]}}
    assert api.put(day_url(MONDAY, week), body, format="json").status_code == 400


def test_a_dish_can_be_a_title_without_a_recipe(api, week, pasta_recipe):
    body = {
        "dishes": {"dinner": [{"title": "  Pizza  fuori ", "course": "single"}, pasta_recipe.pk]}
    }
    day = api.put(day_url(MONDAY, week), body, format="json").json()
    assert [(d["recipe"], d["title"]) for d in day["dishes"]["dinner"]] == [
        (None, "Pizza fuori"),
        (pasta_recipe.pk, pasta_recipe.title),
    ]


@pytest.mark.parametrize("dish", [{"title": "  "}, {"title": "Pizza", "course": "x"}, {"x": 1}])
def test_title_dishes_are_validated(api, week, dish):
    response = api.put(day_url(MONDAY, week), {"dishes": {"dinner": [dish]}}, format="json")
    assert response.status_code == 400
