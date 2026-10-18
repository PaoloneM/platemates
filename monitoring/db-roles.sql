-- Read-only database roles for monitoring, created or updated on every `up` by the db-roles
-- one-shot service (docker-compose.prod.yml). Idempotent, and convergent: passwords follow .env.
--   grafana_reader  Grafana's PostgreSQL datasource: AI usage, prices, team names, and when
--                   invite requests came and whether they wait (never who asked).
--   monitoring      the PostgreSQL exporter: pg_monitor's statistics, no table data.

SELECT 'CREATE ROLE grafana_reader LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'grafana_reader') \gexec
ALTER ROLE grafana_reader WITH LOGIN PASSWORD :'grafana_password';
GRANT CONNECT ON DATABASE :"dbname" TO grafana_reader;
GRANT USAGE ON SCHEMA public TO grafana_reader;
GRANT SELECT ON usage_aiusage, usage_modelprice TO grafana_reader;
GRANT SELECT (id, name) ON families_team TO grafana_reader;
GRANT SELECT (id, status, created_at) ON accounts_inviterequest TO grafana_reader;

SELECT 'CREATE ROLE monitoring LOGIN'
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'monitoring') \gexec
ALTER ROLE monitoring WITH LOGIN PASSWORD :'monitoring_password';
GRANT pg_monitor TO monitoring;
