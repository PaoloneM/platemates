#!/usr/bin/env python3
"""Generate the PlateMates Grafana dashboards (monitoring/grafana/dashboards/*.json).

Dashboards are code: change this file and run it (`python3 monitoring/grafana/make_dashboards.py`),
never edit them in Grafana (provisioned read-only). Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "dashboards"
VM = {"type": "prometheus", "uid": "victoriametrics"}
PG = {"type": "grafana-postgresql-datasource", "uid": "platemates-db"}


class Layout:
    """Places panels left to right, two per row by default."""

    def __init__(self) -> None:
        self.x = self.y = 0
        self.row_height = 0

    def place(self, w: int, h: int) -> dict:
        if self.x + w > 24:
            self.x, self.y = 0, self.y + self.row_height
            self.row_height = 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.row_height = max(self.row_height, h)
        return pos


def metric(title, exprs, unit="short", w=12, h=8, kind="timeseries", stack=False, instant=False):
    """A panel on VictoriaMetrics: exprs is a list of (PromQL, legend). `instant`: one value
    per series, at the end of the range (rankings)."""
    panel = {
        "type": kind,
        "title": title,
        "datasource": VM,
        "targets": [
            {"refId": chr(65 + i), "expr": expr, "legendFormat": legend, "datasource": VM,
             **({"instant": True, "range": False} if instant else {})}
            for i, (expr, legend) in enumerate(exprs)
        ],
        "fieldConfig": {"defaults": {"unit": unit}, "overrides": []},
        "_size": (w, h),
    }
    if kind == "bargauge":
        panel["options"] = {"orientation": "horizontal", "displayMode": "basic",
                            "reduceOptions": {"calcs": ["lastNotNull"], "values": False}}
    if kind == "timeseries":
        panel["fieldConfig"]["defaults"]["custom"] = {
            "fillOpacity": 15,
            "lineWidth": 1,
            "stacking": {"mode": "normal" if stack else "none"},
        }
        panel["options"] = {"legend": {"displayMode": "table", "placement": "bottom",
                                       "calcs": ["lastNotNull", "max"]}}
    return panel


def sql(title, query, unit="short", w=12, h=8, kind="timeseries", fmt="time_series"):
    """A panel on the application database (read-only role)."""
    return {
        "type": kind,
        "title": title,
        "datasource": PG,
        "targets": [
            {"refId": "A", "datasource": PG, "rawQuery": True, "editorMode": "code",
             "format": fmt, "rawSql": query}
        ],
        "fieldConfig": {"defaults": {"unit": unit, "custom": {"fillOpacity": 30, "stacking": {"mode": "normal"}}}, "overrides": []},
        "_size": (w, h),
    }


def dashboard(uid: str, title: str, panels: list[dict], time_from="now-24h") -> dict:
    layout = Layout()
    for i, panel in enumerate(panels, 1):
        w, h = panel.pop("_size")
        panel["id"] = i
        panel["gridPos"] = layout.place(w, h)
    return {
        "uid": uid,
        "title": title,
        "tags": ["platemates"],
        "timezone": "browser",
        "schemaVersion": 39,
        "refresh": "1m",
        "time": {"from": time_from, "to": "now"},
        "panels": panels,
    }


# -- dashboards -------------------------------------------------------------------------------

server = dashboard("pm-server", "Server", [
    metric("CPU used", [('100 * (1 - avg(rate(node_cpu_seconds_total{mode="idle"}[5m])))', "CPU")],
           unit="percent", w=8, kind="stat"),
    metric("Memory used", [("100 * (1 - node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes)", "memory")],
           unit="percent", w=8, kind="stat"),
    metric("Disk used (/)", [('100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})', "disk")],
           unit="percent", w=8, kind="stat"),
    metric("CPU by mode", [('sum by (mode) (rate(node_cpu_seconds_total{mode!="idle"}[5m]))', "{{mode}}")],
           unit="short", stack=True),
    metric("Load", [("node_load1", "1 min"), ("node_load5", "5 min"), ("node_load15", "15 min")]),
    metric("Memory", [("node_memory_MemTotal_bytes - node_memory_MemAvailable_bytes", "used"),
                      ("node_memory_SwapTotal_bytes - node_memory_SwapFree_bytes", "swap used")],
           unit="bytes"),
    metric("Disk free (/)", [('node_filesystem_avail_bytes{mountpoint="/"}', "free")], unit="bytes"),
])

containers = dashboard("pm-containers", "Containers", [
    metric("CPU by container", [("sum by (name) (rate(platemates_container_cpu_seconds_total[5m]))", "{{name}}")],
           unit="short", w=24, h=10, stack=True),
    metric("Memory by container", [("sum by (name) (platemates_container_memory_bytes)", "{{name}}")],
           unit="bytes", w=24, h=10, stack=True),
])

traffic = dashboard("pm-traffic", "Traffic", [
    metric("Requests per second, by service", [('sum by (service) (rate(traefik_service_requests_total[5m]))', "{{service}}")],
           unit="reqps", w=12),
    metric("Server errors (5xx) per second", [('sum by (service) (rate(traefik_service_requests_total{code=~"5.."}[5m]))', "{{service}}")],
           unit="reqps", w=12),
    metric("Latency, 95th percentile", [('histogram_quantile(0.95, sum by (service, le) (rate(traefik_service_request_duration_seconds_bucket[5m])))', "{{service}}")],
           unit="s", w=12),
    metric("Client errors (4xx) per second", [('sum by (service) (rate(traefik_service_requests_total{code=~"4.."}[5m]))', "{{service}}")],
           unit="reqps", w=12),
])

# By endpoint (the view's name), from the backend itself (apps/core/metrics.py): what the user
# waits for, without Cloudflare's or the network's share.
API_SLOW = 'topk(15, histogram_quantile(0.95, sum by (view, method, le) (rate(platemates_http_request_duration_seconds_bucket[$__range]))))'
api = dashboard("pm-api", "API", [
    metric("95th percentile by endpoint (slowest 15, over the range)", [(API_SLOW, "{{method}} {{view}}")],
           unit="s", w=24, h=10, kind="bargauge", instant=True),
    metric("Latency, 95th percentile, by endpoint", [('histogram_quantile(0.95, sum by (view, method, le) (rate(platemates_http_request_duration_seconds_bucket[15m])))', "{{method}} {{view}}")],
           unit="s", w=12),
    metric("Requests per minute, by endpoint", [('60 * sum by (view, method) (rate(platemates_http_request_duration_seconds_count[15m]))', "{{method}} {{view}}")],
           unit="short", w=12),
    metric("Database time, 95th percentile, by endpoint", [('histogram_quantile(0.95, sum by (view, method, le) (rate(platemates_http_db_duration_seconds_bucket[15m])))', "{{method}} {{view}}")],
           unit="s", w=12),
    metric("Queries per request, 95th percentile, by endpoint", [('histogram_quantile(0.95, sum by (view, method, le) (rate(platemates_http_db_queries_bucket[15m])))', "{{method}} {{view}}")],
           unit="short", w=12),
    metric("Server errors (5xx) per minute, by endpoint", [('60 * sum by (view, method) (rate(platemates_http_request_duration_seconds_count{status="5xx"}[15m]))', "{{method}} {{view}}")],
           unit="short", w=24),
], time_from="now-24h")

database = dashboard("pm-database", "Database and backups", [
    metric("Last successful backup", [("time() - platemates_backup_last_success_timestamp_seconds", "age")],
           unit="s", w=8, kind="stat"),
    metric("WAL archiving failures (24 h)", [("increase(pg_stat_archiver_failed_count[24h])", "failures")],
           w=8, kind="stat"),
    metric("PostgreSQL up", [("pg_up", "up")], w=8, kind="stat"),
    metric("WAL segments archived per hour", [("increase(pg_stat_archiver_archived_count[1h])", "archived")]),
    metric("Connections by database", [("sum by (datname) (pg_stat_database_numbackends)", "{{datname}}")]),
    metric("Database size", [('pg_database_size_bytes{datname!~"template.*"}', "{{datname}}")], unit="bytes"),
    metric("Backup duration", [("platemates_backup_last_duration_seconds", "seconds")], unit="s"),
], time_from="now-7d")

keycloak = dashboard("pm-keycloak", "Keycloak", [
    metric("Requests per second", [("sum by (uri) (rate(http_server_requests_seconds_count[5m]))", "{{uri}}")],
           unit="reqps", w=24, h=10),
    metric("Server errors (5xx)", [('sum(rate(http_server_requests_seconds_count{status=~"5.."}[5m]))', "5xx")],
           unit="reqps"),
    metric("JVM memory used", [('sum by (area) (jvm_memory_used_bytes)', "{{area}}")], unit="bytes"),
])

COST = """(u.input_tokens * p.input_per_mtok + u.output_tokens * p.output_per_mtok
  + u.cache_read_tokens * p.cache_read_per_mtok + u.cache_write_tokens * p.cache_write_per_mtok) / 1000000
  + u.web_searches * p.per_thousand_searches / 1000"""
ai = dashboard("pm-ai", "AI usage and costs", [
    sql("Estimated cost per day, by team (USD)", f"""
SELECT date_trunc('day', u.created_at) AS time, COALESCE(t.name, 'no team') AS metric,
  SUM({COST}) AS value
FROM usage_aiusage u
JOIN usage_modelprice p ON p.model = u.model
LEFT JOIN families_team t ON t.id = u.team_id
WHERE $__timeFilter(u.created_at)
GROUP BY 1, 2 ORDER BY 1""", unit="currencyUSD", w=24, h=10, kind="barchart"),
    sql("Estimated cost per day, by feature (USD)", f"""
SELECT date_trunc('day', u.created_at) AS time, u.feature AS metric, SUM({COST}) AS value
FROM usage_aiusage u JOIN usage_modelprice p ON p.model = u.model
WHERE $__timeFilter(u.created_at)
GROUP BY 1, 2 ORDER BY 1""", unit="currencyUSD", kind="barchart"),
    sql("Calls per hour, by model", """
SELECT date_trunc('hour', created_at) AS time, model AS metric, COUNT(*) AS value
FROM usage_aiusage WHERE $__timeFilter(created_at)
GROUP BY 1, 2 ORDER BY 1"""),
    sql("By team and model", f"""
SELECT COALESCE(t.name, 'no team') AS team, u.model, COUNT(*) AS calls,
  SUM(u.input_tokens) AS input_tokens, SUM(u.output_tokens) AS output_tokens,
  SUM(u.web_searches) AS web_searches, ROUND(SUM({COST})::numeric, 4) AS cost_usd
FROM usage_aiusage u
LEFT JOIN usage_modelprice p ON p.model = u.model
LEFT JOIN families_team t ON t.id = u.team_id
WHERE $__timeFilter(u.created_at)
GROUP BY 1, 2 ORDER BY cost_usd DESC NULLS LAST""", w=24, h=10, kind="table", fmt="table"),
], time_from="now-30d")


def main() -> None:
    OUT.mkdir(exist_ok=True)
    for board in (server, containers, traffic, api, database, keycloak, ai):
        path = OUT / f"{board['uid']}.json"
        path.write_text(json.dumps(board, indent=1) + "\n")
        print(f"wrote {path.relative_to(OUT.parent.parent.parent)}")


if __name__ == "__main__":
    main()
