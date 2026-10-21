"""Request metrics: how long each API endpoint takes, and how much of it is the database.

`MetricsMiddleware` times every request and labels it by the view it reached (`recipe-detail`,
never the path: paths carry ids and invitation tokens), its method and status class. Each
response also says its own times in a `Server-Timing` header (app, db), which the browser's
developer tools show. `/metrics` exposes them for VictoriaMetrics; the public Traefik does not
route it (`docker-compose.yml`), the scrape reaches the backend inside Docker's network.

Gunicorn runs several processes: with `PROMETHEUS_MULTIPROC_DIR` set (the backend container),
each one writes its numbers there and `/metrics` adds them up.
"""

from __future__ import annotations

import os
import time

from django.db import connection
from django.http import HttpResponse
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Histogram,
    generate_latest,
    multiprocess,
)

SECONDS = (0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30, 60, 120)
QUERIES = (1, 2, 5, 10, 20, 50, 100, 250, 500)

REQUEST_SECONDS = Histogram(
    "platemates_http_request_duration_seconds",
    "Time to answer a request, by view, method and status class.",
    ["view", "method", "status"],
    buckets=SECONDS,
)
DB_SECONDS = Histogram(
    "platemates_http_db_duration_seconds",
    "Time spent in SQL queries during a request, by view and method.",
    ["view", "method"],
    buckets=SECONDS,
)
DB_QUERIES = Histogram(
    "platemates_http_db_queries",
    "SQL queries run by a request, by view and method.",
    ["view", "method"],
    buckets=QUERIES,
)


class _QueryTimer:
    def __init__(self) -> None:
        self.seconds = 0.0
        self.count = 0

    def __call__(self, execute, sql, params, many, context):
        start = time.perf_counter()
        try:
            return execute(sql, params, many, context)
        finally:
            self.seconds += time.perf_counter() - start
            self.count += 1


def view_name(request) -> str:
    match = getattr(request, "resolver_match", None)
    if match is None:
        return "unmatched"
    return match.view_name or match.route or "unnamed"


class MetricsMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.path == "/metrics":
            # Answered here, before Django checks the Host: the scrape asks for `backend:8000`,
            # which is no public host name. Only Docker's network reaches this path.
            return metrics_view(request)
        timer = _QueryTimer()
        start = time.perf_counter()
        with connection.execute_wrapper(timer):
            response = self.get_response(request)
        seconds = time.perf_counter() - start
        view, method = view_name(request), request.method
        REQUEST_SECONDS.labels(view, method, f"{response.status_code // 100}xx").observe(seconds)
        DB_SECONDS.labels(view, method).observe(timer.seconds)
        DB_QUERIES.labels(view, method).observe(timer.count)
        response["Server-Timing"] = (
            f"app;dur={seconds * 1000:.1f}, "
            f'db;dur={timer.seconds * 1000:.1f};desc="{timer.count} queries"'
        )
        return response


def metrics_view(request):
    if os.environ.get("PROMETHEUS_MULTIPROC_DIR"):
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        from prometheus_client import REGISTRY as registry
    return HttpResponse(generate_latest(registry), content_type=CONTENT_TYPE_LATEST)
