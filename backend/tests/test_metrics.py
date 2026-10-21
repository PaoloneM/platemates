"""Request metrics (apps/core/metrics.py): labelled by view, never by path."""

from rest_framework.test import APIClient


def test_every_response_says_its_times(api, team):
    response = api.get(f"/api/teams/{team.pk}/")
    timing = response["Server-Timing"]
    assert timing.startswith("app;dur=") and "db;dur=" in timing and "queries" in timing


def test_metrics_are_by_view_with_no_id_in_them(api, team):
    api.get(f"/api/teams/{team.pk}/")
    body = APIClient().get("/metrics").content.decode()
    assert (
        'platemates_http_request_duration_seconds_count{method="GET",status="2xx",view="team-detail"}'
        in body
    )
    assert "platemates_http_db_queries_bucket" in body
    assert f"/api/teams/{team.pk}" not in body
