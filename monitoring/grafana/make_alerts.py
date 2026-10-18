#!/usr/bin/env python3
"""Generate Grafana's alerting provisioning (monitoring/grafana/provisioning/alerting/alerts.json):
the notification policy and the alert rules.

Alerts are code, like the dashboards: change this file and run it
(`python3 monitoring/grafana/make_alerts.py`); provisioned rules cannot be edited in Grafana.
The message template is here too; the Telegram contact point the policy sends to is not: Ansible writes it on the server
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
# Where an alert's link leads: the app's own pages on the admin host (Manage, Monitoring),
# which open from a phone too, through Cloudflare's tunnel behind Access.
ADMIN_URL = "https://admin.platemates.cloud"
MONITORING = f"{ADMIN_URL}/monitoring"


def rule(uid, title, summary, query, op, threshold, *, datasource=VM, for_="5m",
         no_data="OK", severity="warning", sql=False, action="", link=MONITORING):
    """One alert: query (PromQL, or SQL returning a `value` column) compared to threshold.
    `summary` says what is wrong (with the value), `action` what to do about it, `link` the
    app's page to look at."""
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
        "annotations": {"summary": summary, "link": link, **({"action": action} if action else {})},
        "labels": {"severity": severity},
        "isPaused": False,
    }


COST = """(u.input_tokens * p.input_per_mtok + u.output_tokens * p.output_per_mtok
  + u.cache_read_tokens * p.cache_read_per_mtok + u.cache_write_tokens * p.cache_write_per_mtok)
  / 1000000 + u.web_searches * p.per_thousand_searches / 1000"""

# What Telegram shows (Grafana's own message lists labels and query values): per alert an icon
# by severity, the rule's title, its summary with the measured value, what to do, and a link.
# The texts are Italian: they are read by the administrator, like the interface.
# Telegram reads the message as HTML and refuses it whole (400) on a stray "<": every value
# that is not ours is escaped. An evaluation error (DatasourceError, e.g. the database restarting
# during a deploy) carries the rule's summary unrendered ("<no value>"): it gets its own text.
TELEGRAM_TEMPLATE = """\
{{ define "platemates.telegram" -}}
{{ range .Alerts.Firing -}}
{{ if .Annotations.Error -}}
⚠️ <b>Dati non leggibili: {{ or .Labels.rulename .Labels.alertname | html }}</b>
La regola non riesce a interrogare i suoi dati (succede mentre il database si riavvia, per esempio durante un deploy).
<i>{{ .Annotations.Error | html }}</i>
{{ else -}}
{{ if eq .Labels.severity "critical" }}🚨{{ else if eq .Labels.severity "info" }}🔔{{ else }}⚠️{{ end }} <b>{{ .Labels.alertname | html }}</b>
{{ .Annotations.summary | html }}
{{ if .Annotations.action }}👉 {{ .Annotations.action | html }}
{{ end }}{{ end -}}
<a href="{{ or .Annotations.link .GeneratorURL | html }}">Apri in PlateMates</a>

{{ end -}}
{{ range .Alerts.Resolved -}}
✅ <b>Risolto: {{ or .Labels.rulename .Labels.alertname | html }}</b>

{{ end -}}
{{- end }}"""

# Values in summaries: $values.B is the reduced query (the value compared to the threshold).
VALUE = "$values.B.Value"

RULES = [
    rule("pm-backup-stale", "Backup fermo da più di 26 ore",
         f"L'ultimo backup riuscito è di {{{{ humanizeDuration {VALUE} }}}} fa.",
         "time() - platemates_backup_last_success_timestamp_seconds", "gt", 26 * 3600,
         no_data="Alerting", severity="critical", for_="10m",
         action="Controlla sul server: journalctl -u platemates-backup"),
    rule("pm-wal-archive", "Archiviazione del WAL in errore",
         f"PostgreSQL non riesce a salvare il WAL in pgBackRest ({{{{ printf \"%.0f\" {VALUE} }}}} "
         "errori in 15 minuti): il ripristino a un istante preciso è a rischio.",
         "increase(pg_stat_archiver_failed_count[15m])", "gt", 0, severity="critical",
         action="Controlla i log del servizio db sul server."),
    rule("pm-postgres-down", "Database non raggiungibile",
         "PostgreSQL non risponde da 2 minuti.",
         "pg_up", "lt", 1, no_data="Alerting", severity="critical", for_="2m",
         action="Controlla il servizio db sul server."),
    rule("pm-disk", "Disco quasi pieno",
         f"Disco del server al {{{{ printf \"%.0f\" {VALUE} }}}}%.",
         '100 * (1 - node_filesystem_avail_bytes{mountpoint="/"} / node_filesystem_size_bytes{mountpoint="/"})',
         "gt", 85, for_="10m",
         action="Libera spazio (immagini Docker vecchie, log) o ingrandisci il disco."),
    rule("pm-memory", "Memoria quasi esaurita",
         f"Memoria libera al {{{{ printf \"%.0f\" {VALUE} }}}}% da 10 minuti.",
         "100 * node_memory_MemAvailable_bytes / node_memory_MemTotal_bytes", "lt", 10, for_="10m",
         action="Guarda la dashboard Containers per capire chi la usa."),
    rule("pm-target-down", "Servizio non raggiungibile",
         # Annotations are not env-expanded by Grafana: $labels stays as it is, for templating.
         "{{ $labels.job }} ({{ $labels.instance }}) non risponde da 5 minuti.",
         "up", "lt", 1, severity="critical",
         action="Controlla quel servizio sul server."),
    rule("pm-public-5xx", "Errori sul sito pubblico",
         f"Il sito risponde con errori del server (5xx): {{{{ printf \"%.2f\" {VALUE} }}}} al "
         "secondo negli ultimi 5 minuti.",
         'sum(rate(traefik_service_requests_total{plane="public",code=~"5.."}[5m]))', "gt", 0.05,
         action="Guarda i log del backend e la dashboard Traffic."),
    rule("pm-invite-requests", "Richieste di nuovi team in attesa",
         f"Richieste in attesa: {{{{ printf \"%.0f\" {VALUE} }}}}.",
         "SELECT COUNT(*) AS value FROM accounts_inviterequest WHERE status = 'pending'",
         "gt", 0, datasource=PG, sql=True, for_="0s", severity="info",
         action="Vedi Gestione → Richieste di team.", link=f"{ADMIN_URL}/manage/invite-requests"),
    rule("pm-ai-cost", f"Spesa AI oltre {AI_DAILY_COST_ALERT_USD} USD oggi",
         f"Spesa AI stimata di oggi: {{{{ printf \"%.2f\" {VALUE} }}}} USD.",
         f"""SELECT COALESCE(SUM({COST}), 0) AS value
FROM usage_aiusage u JOIN usage_modelprice p ON p.model = u.model
WHERE u.created_at >= date_trunc('day', now())""",
         "gt", AI_DAILY_COST_ALERT_USD, datasource=PG, sql=True, for_="0s",
         action="Vedi Gestione → Consumi.", link=f"{ADMIN_URL}/manage/usage"),
]

PROVISIONING = {
    "apiVersion": 1,
    # The contact point (written by Ansible) uses it: {{ template "platemates.telegram" . }}.
    "templates": [{"orgId": 1, "name": "platemates", "template": TELEGRAM_TEMPLATE}],
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
    # Characters as they are: Grafana reads the file with a YAML parser, which refuses the
    # surrogate-pair escapes json.dumps writes for emoji by default.
    OUT.write_text(json.dumps(PROVISIONING, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {OUT.relative_to(OUT.parents[3])} ({len(RULES)} rules)")


if __name__ == "__main__":
    main()
