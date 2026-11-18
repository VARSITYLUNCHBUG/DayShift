# Metrics, dashboards, alerts and logs

A client install runs Prometheus, Alertmanager, Grafana and five exporters next to the app
(`draftbot_observability: true`, the default). They are configured in `infra/observability`
(its [README](../../infra/observability/README.md) lists every file) and started from
`compose.observability.yaml`. Nothing of theirs is reachable from the internet.

## Getting to Grafana and Prometheus

Both listen on the server's 127.0.0.1 only. Open an SSH tunnel, then use your browser:

```bash
ssh -L 13000:127.0.0.1:13000 -L 19090:127.0.0.1:19090 deploy@<server>
```

- Grafana: http://127.0.0.1:13000, user `admin`, the password in `vault_grafana_admin_password`
  (on the server, in `.env.observability`, which only Grafana and Alertmanager read). The
  Overview dashboard is the home page.
- Prometheus: http://127.0.0.1:19090. **Alerts** shows what is firing or pending, **Status >
  Targets** whether every scrape works.
- Alertmanager has no port of its own on the host; its state shows in Grafana's alert list and in
  Prometheus.

To put Grafana on the web as well, set `draftbot_grafana_domain` (for example
`grafana.play.example.com`), point its DNS at the server, add `{username, password}` entries to
`vault_grafana_basic_auth_users` (the edge hashes them on the server), and run `site.yml`. The edge serves it on the same certificate
behind a password prompt, then Grafana's own login; `edge_grafana_allow_cidrs` can limit it to
your addresses.

## Dashboards

All five are in the **Draft bot** folder. They're provisioned from
`infra/observability/grafana/dashboards/`, so Grafana won't save over them: edit the JSON in the
repo and deploy, or save a copy under another name.

| Dashboard | What to read on it |
|---|---|
| **Overview** | Services up, live matches, players in the queue, overdue timers, the outbox's oldest due effect, firing alerts. Then web requests by status and latency, Discord effects by outcome, interactions, live matches by status and errors logged. Start here |
| **Bot and scheduler** | Heartbeat age, gateway latency, due and failed effects, deadlines fired. Effects by kind, retries and failures by kind, effect duration, the outbox, interactions by type, the scheduler's passes and their duration, each process's memory and CPU |
| **Postgres and pgbouncer** | Both up, connections used, the pool's longest client wait, database size and cache hit ratio. pgbouncer's clients, server connections, queries and query time; Postgres's connections by state, transactions, rows, deadlocks and size |
| **Edge and web** | The edge up, requests, open connections, web 5xx, days left on the certificate. nginx's requests, connections and drops; web's requests, p95 latency and errors by route |
| **Host** | CPU, load, memory, disk use and I/O, uptime, Prometheus's own storage, memory by process |

A quiet league looks like this: every service up, heartbeat age under a few seconds, overdue
timers 0, the outbox's oldest due effect near 0, no failed effects, the pool's client wait at 0.

## What is measured

| Job | Target | Source |
|---|---|---|
| `web` | `web:8000/metrics` | `league/observability`: requests by route and status, latency, and the league gauges (queue, live matches by status, overdue deadlines, outbox depth by state, where `failed` counts effects that failed for good in the last 24 hours, and its oldest due effect) |
| `bot` | `bot:9108` | `bot/metrics.py`: gateway latency, interactions by type, effects by kind and outcome, effect duration, loop heartbeats, errors logged by logger |
| `scheduler` | `scheduler:9108` | `bot/metrics.py`: deadline passes and their duration, deadlines fired, heartbeat |
| `node` | `node-exporter` | The host: CPU, memory, disks, network |
| `postgres` | `postgres-exporter` | Connections, transactions, cache hits, size |
| `pgbouncer` | `pgbouncer-exporter` | Pools, client waits, server connections, queries |
| `nginx` | `nginx-exporter` | stub_status on the edge's internal port 8081 |
| `tls` | `blackbox-exporter` | A TLS handshake with the edge, for the certificate's expiry |
| `prometheus`, `alertmanager` | Themselves | Their own health, so `ExporterDown` covers them too |

The league gauges are read with three small queries at most every 10 seconds, however often
Prometheus scrapes, so watching never loads the database. Only `web` exports them, so each exists
once. The edge never forwards `/metrics`, and `web` refuses it for any request that came through a
proxy. Prometheus keeps 15 days, capped at 5 GB.

## Alerts

21 alerts and the always-firing `Watchdog`, in `infra/observability/prometheus/rules/`
(`app.yml` and `infra.yml`), each with a `summary` and a `description`, and each alert a `runbook`
annotation. [alerts.md](alerts.md) has a section for each, under its name.

Alertmanager groups alerts by name and job, waits 30 seconds before the first notice, and repeats
an alert that is still firing every 4 hours. A critical alert holds back the same job's warnings.
With `vault_alertmanager_discord_webhook_url` set (a Discord channel's webhook), it posts each
alert and its resolution there. Without it, alerts only show in Prometheus and Grafana: check
them, or set the webhook. `Watchdog` goes to `ALERTMANAGER_WATCHDOG_URL` instead, never to
Discord ([alerts.md](alerts.md#watchdog)).

The rules have unit tests (`infra/observability/prometheus/tests/rules_test.yml`), run in CI and
with `promtool test rules` (see the observability README).

## Failure notices outside Prometheus

Some failures happen where no scrape can see them: a nightly backup, a certificate renewal, or the
unit that starts the stack at boot. Each of those systemd units has `OnFailure=draftbot-notify@`,
which logs a line and, with `vault_notify_discord_webhook_url` set, posts to that webhook (it can
be the same one as the alerts):

```bash
sudo journalctl -t draftbot-notify
```

None of this can tell you the server itself is down. For that, point an outside uptime check at
`https://<domain>/readyz` (it answers 200 only when web reaches the database through pgbouncer),
and, on the quickstart, set `ALERTMANAGER_WATCHDOG_URL` ([alerts.md](alerts.md#watchdog)).

## Logs

Every service writes JSON lines to stdout, one object per line: the app with `ts`, `level`,
`logger`, `msg`, the `service` and `role`, and the guild, match, interaction or effect it was
working on; the edge with one line per request. Docker keeps them, rotated (10 MB, 5 files per
container), and `docker compose logs` reads them:

```bash
sudo docker compose logs -f bot scheduler
sudo docker compose logs --since 1h web | grep '"level": "ERROR"'
sudo docker compose logs bot scheduler | grep '"match": 12'
sudo docker compose logs edge | grep '"status":5'
```

The edge sends each request's ID to `web` as `X-Request-ID`, and its access line carries it as
`request_id`, so you can follow one request from the edge into the app. The edge logs the path
without its query string, and the app logs a request as its method and path, so sign-in codes
never reach a log.

There is no log store: at one server per client, the container logs and the journal are enough.
Ship them elsewhere (Docker's logging drivers, or a collector reading `docker logs`) if you need
them kept longer.

## In dev

`compose.observability.yaml` goes on top of the dev stack too; see
[../dev/README.md](../dev/README.md#metrics-and-dashboards-in-dev).
