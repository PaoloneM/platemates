#!/usr/bin/env python3
"""Generate Grafana's alerting provisioning (monitoring/grafana/provisioning/alerting/alerts.json):
the notification policy and the alert rules.

Alerts are code, like the dashboards: change this file and run it
(`python3 monitoring/grafana/make_alerts.py`); provisioned rules cannot be edited in Grafana.
The Telegram contact point the policy sends to is not here: Ansible writes it on the server
(deploy/roles/monitoring), since Grafana turns a numeric chat id passed through an environment
variable into a number its Telegram integration refuses. Standard library only.
"""

from __future__ import annotations

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent / "provisioning" / "alerting" / "alerts.json"
VM = "victoriametrics"
PG = "platemates-db"
# Estimated AI spending in a day (USD) above which Telegram is told.
AI_DAILY_COST_ALERT_USD = 5


def rule(uid, title, summary, query, op, threshold, *, datasource=VM, for_="5m",
         no_data="OK", severity="warning", sql=False):
    """One alert: query (PromQL, or SQL returning a `value` column) compared to threshold."""
    if sql:
        model = {"refId": "A", "rawSql": query, "format": "table", "rawQuery": True,
                 "editorMode": "code"}
    else:
        model = {"refId": "A", "expr": query, "instant": True}
    return {
        "uid": uid,
        "title": title,
        "condition": "C",
        "data": [
            {"refId": "A", "relativeTimeRange": {"from": 900, "to": 0},
             "datasourceUid": datasource, "model": model},
            {"refId": "B", "datasourceUid": "__expr__",
             "model": {"refId": "B", "type": "reduce", "expression": "A", "reducer": "last"}},
            {"refId": "C", "datasourceUid": "__expr__",
             "model": {"refId": "C", "type": "threshold", "expression": "B",
                       "conditions": [{"evaluator": {"type": op, "params": [threshold]}}]}},
        ],
        "noDataState": no_data,
        "execErrState": "Error",
        "for": for_,
        "annotations": {"summary": summary},
        "labels": {"severity": severity},
        "isPaused": False,
    }


COST = """(u.input_tokens * p.input_per_mtok + u.output_tokens * p.output_per_mtok
  + u.cache_read_tokens * p.cache_read_per_mtok + u.cache_write_tokens * p.cache_write_per_mtok)
  / 1000000 + u.web_searches * p.per_thousand_searches / 1000"""

RULES = [
    rule("pm-backup-stale", "Backup older than 26 hours",
         "No successful backup for over 26 hours: check `journalctl -u platemates-backup`.",
         "time() - platemates_backup_last_success_timestamp_seconds", "gt", 26 * 3600,
         no_data="Alerting", severity="critical", for_="10m"),
    rule("pm-wal-archive", "WAL archiving failing",
         "PostgreSQL cannot archive WAL into pgBackRest: restores to a moment are at risk.",
         "increase(pg_stat_archiver_failed_count[15m])", "gt", 0, severity="critical"),
    rule("pm-postgres-down", "PostgreSQL down",
         "The database does not answer the exporter.",
         "pg_up", "lt", 1, no_data="Alerting", severity="critical", for_="2m"),
    rule("pm-disk", "Disk over 85%",
         "The server's disk is filling up.",
         '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
         "gt", 85, for_="10m"),
    rule("pm-memory", "Memory under 10%",
         "Less than 10% of memory available for 10 minutes.",
         "100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "lt", 10, for_="10m"),
    rule("pm-target-down", "A monitored service is down",
         # Annotations are not env-expanded by Grafana: $labels stays as it is, for templating.
         "{{ $labels.job }} ({{ $labels.instance }}) has not answered for 5 minutes.",
         "up", "lt", 1, severity="critical"),
    rule("pm-public-5xx", "Errors on the public site",
         "The public site has been answering with server errors (5xx) for 5 minutes.",
         'sum(rate(traefik_service_requests_total{plane="public",code=~"5.."}[5m]))', "gt", 0.05),
    rule("pm-ai-cost", f"AI spending over {AI_DAILY_COST_ALERT_USD} USD today",
         "Today's estimated AI cost passed the threshold: see Gestione > Consumi.",
         f"""SELECT COALESCE(SUM({COST}), 0) AS value
FROM usage_aiusage u JOIN usage_modelprice p ON p.model = u.model
WHERE u.created_at >= date_trunc('day', now())""",
         "gt", AI_DAILY_COST_ALERT_USD, datasource=PG, sql=True, for_="0s"),
]

PROVISIONING = {
    "apiVersion": 1,
    "policies": [
        {
            "orgId": 1,
            "receiver": "telegram",
            "group_by": ["alertname"],
            "group_wait": "30s",
            "group_interval": "5m",
            # A problem still there is repeated twice a day, not every few minutes.
            "repeat_interval": "12h",
        }
    ],
    "groups": [
        {"orgId": 1, "name": "platemates", "folder": "PlateMates", "interval": "1m",
         "rules": RULES}
    ],
}


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(PROVISIONING, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(OUT.parents[3])} ({len(RULES)} rules)")


if __name__ == "__main__":
    main()
