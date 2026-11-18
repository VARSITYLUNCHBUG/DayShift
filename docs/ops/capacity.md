# Capacity

One server runs one community. The defaults below fit a 2 GB, 2 CPU VPS with room to spare; this
page says where the limits are, how the database connections add up, and what to watch before
changing anything.

## Memory and CPU

Every service has a CPU, memory and process limit in `compose.yaml` and
`compose.observability.yaml`. A limit is a ceiling, not a reservation: an idle stack uses far
less.

| Service | CPU | Memory limit | Idle, measured |
|---|---|---|---|
| `db` | 2 | 1 GB (`shared_buffers` 256 MB) | ~75 MB |
| `bot` | 1 | 1 GB (score OCR loads its model here) | ~80 MB |
| `web` | 1 | 768 MB | ~90 MB |
| `scheduler` | 0.5 | 384 MB | ~75 MB |
| `edge` | 1 | 256 MB (160 MB of it for upload buffers) | ~6 MB |
| `pgbouncer` | 1 | 64 MB | ~10 MB |
| `migrate` (one-shot) | 1 | 512 MB | |
| `prometheus` | 1 | 1 GB | ~40 MB, growing with its data |
| `grafana` | 0.5 | 512 MB | ~160 MB |
| `alertmanager` and five exporters | 0.25 each | 128 MB each | under 10 MB each |

That is about 600 MB for the whole stack at rest. Watch the Host dashboard's memory by process,
and the Bot and scheduler dashboard's memory panel: a service that reaches its limit is killed
and restarted by Docker. To change a limit, add your own override file to
`app_compose_extra_files` in the inventory rather than editing `compose.yaml`.

Postgres's `shared_buffers` and `effective_cache_size` are sized for its 1 GB limit; on a bigger
server raise `POSTGRES_SHARED_BUFFERS` (a quarter of what you give Postgres) and
`POSTGRES_EFFECTIVE_CACHE_SIZE` (three quarters) through `app_env_extra`, together with the limit.

## Database connections

There are two kinds of connection, and only one of them is scarce:

- **Client connections**, from the app to pgbouncer. Cheap: pgbouncer takes up to 200
  (`max_client_conn`). The bot and the scheduler keep theirs for up to 60 seconds
  (`DB_CONN_MAX_AGE`), health-checked before reuse; `web` closes each at the end of its request
  (`DB_CONN_MAX_AGE=0` in `compose.yaml`).
- **Server connections**, from pgbouncer to Postgres. Each is a Postgres backend process. In
  transaction pooling, a client holds one only while a transaction runs, then hands it back.

How many clients each service holds:

| Service | Client connections | Why |
|---|---|---|
| `bot` | 1 | Every database call goes through one shared thread (`league.asyncdb`) |
| `scheduler` | 1 | The same |
| `web` | 1 per request in flight | Under ASGI each request runs its database work on a thread of its own, and closes its connection when it ends. A kept connection would be stranded with its thread, which is why `web` keeps none |
| exporters, healthchecks | 1 to 2 | The Postgres exporter connects to `db` directly, not through pgbouncer |

Measured on a prod-shaped stack: bursts of 200 and 400 requests, 80 at a time, left 2 client
connections open afterwards, and pgbouncer used 2 server connections throughout. About 190 web
requests in flight at once would reach `max_client_conn`; further connections are refused until
some finish.

And the server side, in `infra/pgbouncer/pgbouncer.ini` and `compose.yaml`:

| Setting | Value | Meaning |
|---|---|---|
| `default_pool_size` | 20 | Server connections pgbouncer keeps for the app |
| `reserve_pool_size`, `reserve_pool_timeout` | 5, 3 s | Five more for a client that has waited 3 seconds |
| `max_db_connections` | 30 | The most pgbouncer ever opens to Postgres |
| `query_wait_timeout` | 30 s | A client waiting longer gets an error instead of hanging |
| Postgres `max_connections` | 100 | 30 for pgbouncer, the rest for migrate, the web UI's live-update listener once it ships (`DATABASE_DIRECT_URL`), backups, the exporter (at most 5, `draftbot_monitor`'s limit), a restore check and `psql` |

The math: a transaction here takes a few milliseconds, and the bot and scheduler each run at most
one at a time. A full match played as fast as the simulator can drive it was about 5,200
transactions in 11 to 16 seconds, a few hundred a second, and pgbouncer opened 3 server
connections for it. Twelve live
matches played by people make a few transactions a second. So 20 server connections leave a wide
margin: they run out only when transactions get long (a stuck query, a lock wait).
`infra/pgbouncer/pgbouncer.ini` has the same reasoning beside the settings.

`WEB_DB_THREADS` (default 8) sizes psycopg's own pool, `WEB_DB_THREADS + 2`, when you run
without pgbouncer (`DB_POOL=true`). Behind pgbouncer it changes nothing; pgbouncer's
`default_pool_size` is the number that matters.

### When to change the pool

`PgbouncerClientsWaiting` fires when a client waits over a second. First look for a long
transaction (the alert's runbook has the query): one stuck transaction can hold a connection
until `idle_in_transaction_session_timeout` (5 minutes) ends it, and raising the pool doesn't
help. If the load is real, raise `default_pool_size` and `max_db_connections` in
`infra/pgbouncer/pgbouncer.ini`, keeping `max_db_connections` well under Postgres's
`max_connections`, and deploy; the app role restarts pgbouncer when its configuration changes.

## The web process

uvicorn runs one worker, on purpose: it will hold every player's websocket and fan live updates
out from one `LISTEN` connection, so more workers would each need their own. One worker on one CPU
serves the admin, the dashboard and a community's players comfortably. If the Edge and web
dashboard's p95 latency climbs while the Host dashboard shows `web` pegged at its CPU limit, give
it more CPU before anything else.

## The bot

The gateway process is one Discord connection (no sharding), which Discord allows for up to 2,500
servers; this bot serves one. Effects run in parallel across matches (one lane each), so twelve
live matches don't wait on each other. Discord's rate limits are the real ceiling: watch
`EffectRetryRateHigh` and the effects-by-outcome panel.

## Disk

| What | Grows with | Bound |
|---|---|---|
| The database | Matches, ratings, the effect outbox (finished effects are pruned daily) | The disk; the Postgres dashboard shows its size |
| Backups in `/var/backups/draftbot` | One dump a night | `backups_retention_days` (14) dumps |
| Prometheus | Time | 15 days or 5 GB, whichever comes first |
| Container logs | Traffic | 10 MB × 5 files per container |
| Old images | Upgrades | `sudo docker image prune` |

`DiskSpaceLow` fires at 85%. 20 GB is plenty for a season or several.
