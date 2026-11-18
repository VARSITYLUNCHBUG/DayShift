# Alert runbook

One section per alert in `infra/observability/prometheus/rules/`, under the alert's own name.
Each rule's `runbook` annotation is the first thing to try; this page says what the alert means,
what to check, and what to do.

Run the commands on the server in `/opt/draftbot` (the self-host quickstart: in your checkout),
with `sudo` on a client install. `.env` sets `COMPOSE_FILE`, so a plain `docker compose` there
uses every compose file the install has. Open Grafana and Prometheus through an SSH tunnel
first (see [observability.md](observability.md)).

**Severity.** `critical` means players can't play or will soon notice: act now. `warning` means
something is degraded or about to be: look today. While a critical alert fires for a job,
Alertmanager holds back that job's warnings, so the root cause is the one you see.

| Alert | Severity | In short |
|---|---|---|
| [AppServiceDown](#appservicedown) | critical | `web`, `bot` or `scheduler` can't be scraped |
| [BotHeartbeatStale](#botheartbeatstale) | critical | A loop in the bot or scheduler stopped going round |
| [DeadlinesOverdue](#deadlinesoverdue) | critical | Match timers aren't firing |
| [PostgresDown](#postgresdown) | critical | The database is down |
| [PgbouncerDown](#pgbouncerdown) | critical | The pooler is down |
| [EdgeDown](#edgedown) | critical | nginx isn't answering |
| [OutboxBacklog](#outboxbacklog) | warning | Discord updates are queuing up |
| [EffectsFailing](#effectsfailing) | warning | Discord changes failed for good |
| [EffectRetryRateHigh](#effectretryratehigh) | warning | Over 20% of Discord calls retry or fail |
| [WebErrorRateHigh](#weberrorratehigh) | warning | Over 5% of web requests answer 5xx |
| [BotErrorsLogged](#boterrorslogged) | warning | Many errors in the bot's logs |
| [GatewayLatencyHigh](#gatewaylatencyhigh) | warning | Discord's gateway is slow to answer |
| [LeagueMetricsUnavailable](#leaguemetricsunavailable) | warning | The league gauges can't be read |
| [ExporterDown](#exporterdown) | warning | An exporter's metrics are missing |
| [BlackboxExporterDown](#blackboxexporterdown) | warning | The certificate probe itself isn't answering |
| [PostgresConnectionsHigh](#postgresconnectionshigh) | warning | Postgres is near its connection limit |
| [PgbouncerClientsWaiting](#pgbouncerclientswaiting) | warning | Queries wait for a database connection |
| [DiskSpaceLow](#diskspacelow) | warning | A disk is over 85% full |
| [ClockNotSynchronised](#clocknotsynchronised) | warning | The server's clock has drifted or lost sync |
| [CertificateExpiringSoon](#certificateexpiringsoon) | warning | The TLS certificate expires in under 14 days |
| [CertificateProbeFailing](#certificateprobefailing) | warning | The certificate can't be checked |
| [Watchdog](#watchdog) | none | Always firing: proves alerting works end to end |

## AppServiceDown

Prometheus hasn't scraped `web`, `bot` or `scheduler` (the `job` label) for 2 minutes: the
container is down, restarting, or not answering on its metrics port.

1. `docker compose ps <job>` shows whether it's running, restarting or unhealthy.
2. `docker compose logs --tail 200 <job>`. At start, a crash loop is usually the database
   (look for `PostgresDown` or `PgbouncerDown` too) or a bad `.env` value; the app names the
   setting it refuses (for example `DJANGO_SECRET_KEY must be set`).
3. For `bot`: an invalid token stops it at login (`Improper token`). Reset it and rotate it
   ([secrets.md](secrets.md)).
4. Start it again with `docker compose up -d <job>`. If a new image won't start, roll back
   ([upgrades.md](upgrades.md)).

Pending work is safe while a service is down: clicks fail in Discord ("This interaction failed"),
but timers and Discord changes are rows in the database and resume when it's back.

## BotHeartbeatStale

The process is up and scraped, but one of its loops (the `loop` label: `deadlines` in the
scheduler, `effects` in the bot) hasn't gone round for over a minute. It normally goes round
every second. The container's healthcheck fails on the same heartbeat, so Docker marks it
unhealthy at about the same time.

1. `docker compose logs --tail 200 <job>` for `Deadline loop error` or `Effect loop error` and the
   traceback after it. A repeating error is logged in full once, then at most once a minute with a
   `failures` count, and `...: recovered` when it stops. Right after a start, `Startup recovery
   failed, retrying` means the bot is waiting for the database before it starts its loops
   ([PostgresDown](#postgresdown), [PgbouncerDown](#pgbouncerdown)); it starts them by itself once
   it answers (`Startup recovery done after retries`).
2. `docker compose restart <job>`. Pending work resumes from the database; the scheduler gives
   past-due timers 60 seconds of grace first.
3. If it comes back stuck, the database is the usual cause: check the Postgres and pgbouncer
   dashboard for a long transaction or waiting clients.

## DeadlinesOverdue

Live matches have a deadline more than 30 seconds past that hasn't fired, so they won't move on
by themselves (a ready check never closes, a draft turn never auto-picks).

1. `docker compose ps scheduler`. If it's down or unhealthy, see
   [AppServiceDown](#appservicedown) or [BotHeartbeatStale](#botheartbeatstale).
2. `docker compose logs --tail 200 scheduler` for errors from `deadlines.tick`.
3. `docker compose restart scheduler`. Its startup grace gives everyone 60 seconds to act before
   the late timers fire.

If only one match is stuck and the scheduler is healthy, its timer may be failing every time it
fires. The log line names the match; staff can `/match void` it in Discord.

## PostgresDown

The Postgres exporter can't connect. Nothing works without the database.

1. `docker compose ps db` and `docker compose logs --tail 200 db`.
2. A full disk stops Postgres: `df -h` (and see [DiskSpaceLow](#diskspacelow)).
3. `PANIC` or checksum errors in the log mean damaged data: stop here, don't restart in a loop,
   and restore the newest good backup ([backups.md](backups.md)).
4. Otherwise `docker compose up -d db`, then check `pgbouncer`, `web`, `bot` and `scheduler`
   come back healthy (`docker compose ps`).

## PgbouncerDown

The pgbouncer exporter can't reach pgbouncer. `web`, `bot` and `scheduler` reach the database
only through it, so the app is down too.

1. `docker compose ps pgbouncer` and `docker compose logs --tail 200 pgbouncer`.
2. `POSTGRES_PASSWORD must be set` means `.env` lost it. `SASL authentication failed` means a
   password pgbouncer has (the superuser's, `draftbot_app`'s or `draftbot_monitor`'s, all from
   `.env`) isn't the one Postgres has: run `rotate-secrets.yml`, which sets both sides
   ([secrets.md](secrets.md)).
3. `docker compose up -d pgbouncer`. The app reconnects by itself.

## EdgeDown

The nginx exporter can't read the edge's status page. Nobody can reach the web UI or the admin.
Discord play continues: the bot doesn't go through the edge.

1. `docker compose ps edge` and `docker compose logs --tail 100 edge`.
2. `docker compose exec edge nginx -t` checks the configuration. A missing certificate file
   means the certificate directory changed; run `site.yml --tags edge`.
3. `docker compose up -d edge`.

## OutboxBacklog

The oldest due Discord effect has waited over 2 minutes: boards, DMs and channel changes are
late. The bot's effect worker is stuck, or Discord is rate-limiting it.

1. The Bot dashboard: effects by outcome (lots of `retried` means Discord is refusing), gateway
   latency, and the Outbox panel.
2. `docker compose logs --tail 200 bot` for rate limits (`429`) or Discord errors.
3. https://discordstatus.com for an outage. If Discord is fine and nothing is moving,
   `docker compose restart bot`.

## EffectsFailing

Discord effects of one kind (the `kind` label) gave up after their retries in the last 15
minutes. The change they stood for never reached Discord: a board not updated, a channel not
made, a DM not sent.

1. In the admin, **Outbox effects**, filtered to status `failed`, shows each one with its last
   error. `docker compose logs bot` has them under `Effect failed for good`.
2. A `403` (`Missing Permissions`, code 50013) is a Discord permission the bot lacks on that
   server: check its role and the channel's overwrites. A `404` (`Unknown Channel` or
   `Unknown Message`) is usually something deleted by hand.
3. The match itself is fine: its state is in the database. Once the cause is fixed, the next
   change to that match redraws its board.

The alert clears 15 minutes after the last failure.

## EffectRetryRateHigh

Over a fifth of effect runs retried or failed for 10 minutes. Usually Discord itself or rate
limits.

1. https://discordstatus.com.
2. The Bot dashboard's retries and failures by kind: one kind points at one feature (or one
   missing permission), all kinds at Discord or the network.
3. `docker compose logs bot` shows the errors.

## WebErrorRateHigh

Over 5% of web requests answered 5xx for 5 minutes.

1. `docker compose logs --tail 200 web` for the tracebacks.
2. If every request fails, check the Postgres and pgbouncer dashboard first: `/readyz` answers
   503 when the database doesn't.
3. The Edge and web dashboard's errors by route shows whether it's one page.
4. Match the edge's log line to the app's by its `request_id`:
   `docker compose logs edge | grep '"status":5'`.

## BotErrorsLogged

More than 10 errors from one logger (the `logger` label) in 10 minutes. `bot.routing` errors are
failed clicks and commands; `bot.client` errors are loop and gateway problems. A loop that keeps
failing the same way logs at most once a minute, so an outage of the database alone rarely trips
this: `PostgresDown`, `PgbouncerDown` and `BotHeartbeatStale` cover that.

1. `docker compose logs bot scheduler | grep '"level": "ERROR"'`. Each line carries the guild,
   match and interaction it happened in.
2. The operator's error channel (`ERROR_LOG_CHANNEL_ID`) has the full tracebacks, and each
   server's `/seterrorchannel` channel its own summaries.
3. One error repeating for one match usually means that match is in a state the code didn't
   expect: report it with the traceback, and staff can `/match void` it if it blocks play.

## GatewayLatencyHigh

The Discord gateway's heartbeat round trip has been over a second for 10 minutes. Clicks feel
slow and may time out ("This interaction failed").

1. https://discordstatus.com.
2. The Host dashboard: CPU busy or load high means the server is short of CPU (see
   [capacity.md](capacity.md)).
3. Otherwise it's the network between the host and Discord; it passes on its own.

## LeagueMetricsUnavailable

The web process can't read the queue, match and outbox gauges, so `DeadlinesOverdue` and
`OutboxBacklog` can't fire while this lasts.

1. `docker compose logs web | grep "Couldn't read the league gauges"` for the error.
2. Usually the database: check `PgbouncerDown`, `PostgresDown` and
   [PgbouncerClientsWaiting](#pgbouncerclientswaiting).

## ExporterDown

Prometheus can't scrape one of the exporters (`node`, `postgres`, `pgbouncer`, `nginx`) or
itself and Alertmanager. The thing it watches may be fine, but its alerts can't fire.

1. `docker compose ps` for the exporter of that job (`node-exporter`, `postgres-exporter`,
   `pgbouncer-exporter`, `nginx-exporter`, `alertmanager`).
2. Its logs: `docker compose logs --tail 100 <exporter>`. The Postgres and pgbouncer exporters
   log in as `draftbot_monitor` with `DB_MONITOR_PASSWORD`, which migrate sets inside Postgres:
   `password authentication failed` means the two differ. Run `rotate-secrets.yml` (or, on the
   quickstart, `docker compose up -d`, which runs migrate again).
3. `docker compose up -d <exporter>`.

## BlackboxExporterDown

Prometheus hasn't been able to run the TLS probe for 10 minutes: the blackbox exporter itself is
down, so neither certificate alert can fire.

1. `docker compose ps blackbox-exporter` and `docker compose logs --tail 100 blackbox-exporter`.
2. `docker compose up -d blackbox-exporter`. Its configuration is `infra/observability/blackbox/`;
   a bad edit there stops it at start.

## PostgresConnectionsHigh

Postgres has used over 80% of its 100 connections for 10 minutes. pgbouncer opens at most 30, so
something is connecting around it, or many `manage.py` sessions are open.

1. The Postgres and pgbouncer dashboard, connections by state.
2. Who is connected:
   `docker compose exec db psql -U draftbot -c "select application_name, client_addr, state, count(*) from pg_stat_activity group by 1, 2, 3 order by 4 desc"`.
   pgbouncer's address should hold nearly all of them.
3. Close stray `psql` or `manage.py shell` sessions. Everything but migrate and backups should go
   through pgbouncer.

## PgbouncerClientsWaiting

A client has waited over a second for a server connection for 2 minutes: pgbouncer's pool is
exhausted and queries queue behind each other.

1. A long transaction holding connections:
   `docker compose exec db psql -U draftbot -c "select pid, now() - xact_start as age, state, left(query, 80) from pg_stat_activity where xact_start is not null order by age desc limit 10"`.
   `idle_in_transaction_session_timeout` ends idle ones after 5 minutes.
2. The pool itself (`cl_waiting`, `maxwait`, `sv_active`), from pgbouncer's console, which only
   its stats user `draftbot_monitor` may open (it exists with the observability overlay, on by
   default on a client install):
   `docker compose exec pgbouncer sh -c 'PGPASSWORD=$DB_MONITOR_PASSWORD psql -h 127.0.0.1 -p 6432 -U draftbot_monitor pgbouncer -c "SHOW POOLS"'`.
3. If the load is real rather than one stuck query, raise the pool (see
   [capacity.md](capacity.md)).

## DiskSpaceLow

A filesystem has been over 85% full for 10 minutes. Postgres stops writing when the disk fills.

1. `df -h`, then `sudo docker system df` for images, containers and volumes.
2. Old images from past upgrades: `sudo docker image prune` (unused images only; the running
   ones stay).
3. Old dumps in `/var/backups/draftbot`: lower `backups_retention_days` in the inventory and run
   `site.yml --tags backups`.
4. Prometheus keeps at most 5 GB (`PROMETHEUS_RETENTION_SIZE`); container logs at most 50 MB per
   container.
5. If it's the database itself, the server needs a bigger disk.

## ClockNotSynchronised

For 10 minutes the kernel has reported the clock as unsynchronised, or more than 0.5 s off. Match
timers, ready-check deadlines and certificate checks all trust the clock.

1. `timedatectl status`: "System clock synchronized: yes" and "NTP service: active" are what you
   want. The base role installs and enables `systemd-timesyncd` unless chrony, ntpsec, ntp or
   openntpd is already there.
2. `sudo systemctl restart systemd-timesyncd`, then `journalctl -u systemd-timesyncd` for why it
   can't reach a server. The firewall must allow outbound UDP 123; some providers block it and
   offer their own NTP server instead.

## CertificateExpiringSoon

The edge's certificate expires in under 14 days. certbot renews 30 days ahead, so renewal has been
failing for two weeks.

1. `sudo journalctl -u draftbot-certbot-renew` for the renewal runs and their errors. (certbot
   runs as a one-shot container, so `docker compose logs certbot` usually shows nothing.)
2. Usually DNS no longer points at the server, or port 80 is blocked by the provider's firewall:
   `dig +short <domain>` and `curl -I http://<domain>/.well-known/acme-challenge/x` from outside
   (a 404 from nginx is right).
3. Try it now: `sudo systemctl start draftbot-certbot-renew`, or
   `sudo /usr/local/sbin/draftbot-certbot-renew --dry-run` to test without renewing.
4. If the renewal configuration is broken, `site.yml --tags edge` gets a new certificate.

## CertificateProbeFailing

The blackbox exporter couldn't complete a TLS handshake with the edge for 30 minutes, so
`CertificateExpiringSoon` can't fire. Without TLS (dev, the self-host quickstart) this always
fires: ignore it there.

1. `docker compose logs blackbox-exporter` for the handshake error.
2. `unrecognized name` means `EDGE_SERVER_NAME` in `.env` isn't the edge's server name (the app
   role writes it from `draftbot_domain`; run `site.yml --tags app`).
3. `connection refused` means the edge isn't listening on 8443: see [EdgeDown](#edgedown).

## Watchdog

Always firing, on purpose: it proves Prometheus evaluates rules and Alertmanager sends what they
find. It is never posted to Discord. With `ALERTMANAGER_WATCHDOG_URL` set in `.env.observability`
(a dead man's switch such as a healthchecks.io check), Alertmanager pings that URL every minute,
and the service tells you when the pings stop: the host, Prometheus or Alertmanager is down, which
no alert from this server could say. The Ansible roles don't write that setting yet, so on a
client install this is a check by eye: Watchdog missing from Prometheus's **Alerts** page means
alerting is broken.

1. If the switch says the pings stopped: `docker compose ps prometheus alertmanager`, then their
   logs. `ALERTMANAGER_WATCHDOG_URL is unset` in Alertmanager's log means it never had one.
2. If the host is unreachable, go to your provider's console.
