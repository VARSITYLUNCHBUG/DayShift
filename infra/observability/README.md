# Observability

Prometheus, Alertmanager, Grafana and the exporters, run by `compose.observability.yaml` on top
of any environment:

```sh
# Once: the overlay's own secrets, in a file only Grafana and Alertmanager read
cp .env.observability.example .env.observability    # then set GRAFANA_ADMIN_PASSWORD

# Local dev
DB_MONITOR_PASSWORD=pick-one \
  docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml -f compose.observability.yaml --profile sim up -d

# A server (DB_MONITOR_PASSWORD is in .env)
docker compose -f compose.yaml -f deploy/compose.prod.yaml -f compose.observability.yaml up -d
```

Where each secret lives, so the app's containers (which get all of `.env`) never see the
overlay's:

| Variable | File | Read by |
|---|---|---|
| `GRAFANA_ADMIN_PASSWORD` (required) | `.env.observability` (`OBSERVABILITY_ENV_FILE`) | grafana (its entrypoint refuses to start without it) |
| `ALERTMANAGER_DISCORD_WEBHOOK_URL` (optional) | `.env.observability` | alertmanager |
| `DB_MONITOR_PASSWORD` (required) | `.env` or the shell: compose needs it | migrate, pgbouncer, postgres-exporter, pgbouncer-exporter. compose.yaml blanks it for migrate, web, bot and scheduler; this overlay hands it back to migrate and pgbouncer |

The exporters log in as `draftbot_monitor`, which can read Postgres's statistics (`pg_monitor`)
and pgbouncer's SHOW output (`stats_users`), and no table. migrate creates it, or resets its
password and attributes, on every start (`league/observability/monitoring_role.py`), so it works
on a new database volume and an existing one alike, and changing `DB_MONITOR_PASSWORD` takes
effect on the next `up`.

Grafana is at http://127.0.0.1:13000 (`GRAFANA_PORT`), Prometheus at http://127.0.0.1:19090
(`PROMETHEUS_PORT`). Both listen on 127.0.0.1 only: on a server, open an SSH tunnel first,
`ssh -L 13000:127.0.0.1:13000 deploy@your-host`. Sign in to Grafana as `admin` with
`GRAFANA_ADMIN_PASSWORD`. Grafana only reads it when it first creates its database: to change
it later, run `docker compose exec grafana grafana cli admin reset-admin-password <new>`.

## What is scraped

| Job | Target | What it tells you |
|---|---|---|
| `web` | `web:8000/metrics` | requests by route and status, latency, and the league gauges: queue, live matches, overdue timers, outbox depth |
| `bot` | `bot:9108` | gateway latency, interactions, effects by kind and outcome, loop heartbeats, errors logged |
| `scheduler` | `scheduler:9108` | deadline passes, deadlines fired, heartbeat |
| `node` | node-exporter | the host: CPU, memory, disks |
| `postgres` | postgres-exporter | connections, transactions, cache hits, size |
| `pgbouncer` | pgbouncer-exporter | pool clients, waits, server connections |
| `nginx` | nginx-exporter | the edge's requests and connections (stub_status on its internal port 8081) |
| `tls` | blackbox-exporter | the edge's certificate expiry (the probe fails without TLS) |

The app's metrics come from `league/observability` (web) and `bot/metrics.py` (bot and
scheduler, on `METRICS_PORT`). The edge never forwards `/metrics`, and web refuses it for any
request that came through a proxy. The nginx and blackbox exporters reach the edge on a network
of their own (`edge-probes`), so the edge network stays the edge's and web's alone (web believes
proxy headers from the edge's fixed address only, `EDGE_IP`).

## Files

- `prometheus/prometheus.yml`: scrape jobs. `prometheus/rules/`: alert rules, each with a
  `runbook` annotation. `prometheus/tests/`: unit tests for the rules.
- `alertmanager/`: set `ALERTMANAGER_DISCORD_WEBHOOK_URL` (a Discord channel's webhook) in
  `.env.observability` to have alerts posted there. Without it, alerts only show in Grafana and Prometheus.
- `grafana/provisioning/`: the Prometheus datasource and the dashboard loader.
  `grafana/dashboards/`: Overview, Bot and scheduler, Postgres and pgbouncer, Edge and web,
  Host. Grafana can't save over a provisioned dashboard: edit the JSON here, or save a copy.
- `blackbox/`: the TLS probe. The edge only completes a handshake for its own name, so set
  `EDGE_SERVER_NAME` (the edge's public domain) wherever the edge has TLS. Without it the probe
  fails and `CertificateProbeFailing` fires, which is expected in dev.

Prometheus keeps 15 days, capped at 5 GB (`PROMETHEUS_RETENTION`, `PROMETHEUS_RETENTION_SIZE`).

## Checking a change

```sh
docker run --rm --entrypoint promtool -v "$PWD/infra/observability/prometheus:/etc/prometheus:ro" \
  prom/prometheus:v3.15.1 check config /etc/prometheus/prometheus.yml
docker run --rm --entrypoint promtool -w /etc/prometheus/tests \
  -v "$PWD/infra/observability/prometheus:/etc/prometheus:ro" prom/prometheus:v3.15.1 test rules rules_test.yml
```
