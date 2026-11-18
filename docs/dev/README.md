# Developing the bot locally

You can run the whole stack on your machine without a Discord server: the real bot talks to a
Discord simulator, a control panel gives you fake players and lets you play every phase of a
match, and the test suites run in throwaway containers. [../architecture.md](../architecture.md)
shows how the services fit together.

You need Docker (Docker Desktop on Windows and macOS, Docker Engine with the compose plugin 2.24
or newer on Linux). For the fast unit test loop, linting and type checks you also need
[uv](https://docs.astral.sh/uv/); it installs the right Python itself. Node 22 or newer only if
you work on the control panel.

Every script has a POSIX shell version (`.sh`, for Linux, macOS and Git Bash) and a Windows
version (`.bat`, for cmd.exe and PowerShell) with the same flags and output. Run them from
anywhere; they find the repo themselves. `--help` lists the flags.

## Start the dev stack

```bash
scripts/fixture_to_test.sh          # Windows: scripts\fixture_to_test.bat
```

From nothing, this:

1. Checks that Docker is running.
2. Creates `.env.dev` from `.env.dev.example` if you don't have one.
3. Builds and starts `db`, `pgbouncer` and `discord-sim`, and waits until they're healthy.
4. Runs the migrations and `load_presets`.
5. Runs `manage.py dev_seed`: loads `fixtures/dev/*.json` (a community, a season, staff grants,
   14 players), lays the simulator's guild out the way `/setup` would (the PUGS role, the
   Deadlock category, the Waiting Room, queue, results, leaderboard, scoreboard-archive and
   staff-alerts) and wires it into the community, and seeds the ratings.
6. Starts `web`, `bot`, `scheduler`, `edge` and `control-panel`, and waits until they're healthy.
7. Prints the URLs.

It's safe to run again: it rebuilds what changed and keeps your data. Run it again after a code
change to rebuild and restart. Each health check waits up to 300 seconds
(`DRAFTBOT_WAIT_TIMEOUT`). If one fails, the script shows `docker compose ps` and the last log
lines of the services involved, and exits non-zero.

| Flag | What it does |
|---|---|
| `--fresh` | Drops the dev stack and its database volume first, so you start from empty |
| `--no-build` | Uses the images you already built |
| `--real-discord` | Skips the simulator and the dev seed, and uses `.env` (see [Real-Discord mode](#real-discord-mode)) |

When it's up:

| What | URL |
|---|---|
| Web, through the edge (as players reach it) | http://localhost:18080 |
| Admin | http://localhost:18080/admin/ |
| Control panel | http://localhost:18091 |
| Web, direct (what the panel and the e2e suite use) | http://localhost:18000 |
| Dev control API | http://localhost:18000/_control/api/ |
| Discord simulator | http://localhost:18090/_sim/state |
| Postgres | `127.0.0.1:15432`, user `draftbot`, password `dev` (`DEV_DB_PASSWORD`; the app itself goes through pgbouncer) |

For the admin, create a superuser once:

```bash
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim exec web python manage.py createsuperuser
```

Everything else is plain compose with the same `-p`, `-f` and `--profile` flags (the script
prints them at the end). Without `--profile sim`, `stop` and `down` leave the simulator running:

```bash
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim ps
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim logs -f bot scheduler
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim exec web python manage.py shell
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim stop
```

To skip typing them, set `COMPOSE_PROJECT_NAME=draftbot-dev`,
`COMPOSE_FILE=compose.yaml:compose.dev.yaml` (`;` instead of `:` on Windows) and
`COMPOSE_PROFILES=sim` in your shell. The rest of this guide writes `dc` for
`docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml --profile sim`.

### What the dev stack sets

`compose.dev.yaml` gives every app service `DEBUG=true`, `DEV_CONTROL=true` (the `/_control/`
API), `WEB_DEV_LOGIN=true` (for the player web UI, once it lands: sign in as any player without
Discord), `LOG_FORMAT=text` and its own database volume (`dev-pgdata`). The bot and the
scheduler log in as `draftbot_app` (`DEV_DB_APP_PASSWORD`, default `dev-app`) as in production;
`web` logs in as the superuser, because the dev reset empties the tables with `TRUNCATE`, which
only their owner may do. The services keep the production hardening: read-only, no
capabilities, pgbouncer in front of Postgres, the image's `dev` target (the published one plus
`devtools/` and `fixtures/`). `.env.dev` points the bot at the simulator:

```
DISCORD_TOKEN=sim-token
DISCORD_GUILD_ID=1100000000000000001
DISCORD_API_BASE=http://discord-sim:8090/api/v10
DISCORD_GATEWAY_URL=ws://discord-sim:8090/gateway
DISCORD_SIM_URL=http://discord-sim:8090
```

With `DISCORD_SIM_URL` set, deadlock-api calls go to the simulator's stand-in too, so the dev
stack never creates real lobbies. `.env.dev` is yours: it's git-ignored, and the script never
overwrites it. To pick up a newer template, delete it and run the script again.
`SIM_SEED_USERS=5 scripts/fixture_to_test.sh` starts the simulator with five extra members.

The dev stack doesn't use your `.env`, the base project's `pgdata` volume or its ports, so it
runs side by side with a `docker compose up` of the base `compose.yaml`.

### Two dev stacks at once

Every host port is a variable, so a second checkout (another branch, say) can run its own stack
under another project name. It needs an edge network of its own as well: a subnet, the edge's
fixed address inside it, and the range Docker hands every other address out of, also inside it
and not holding the edge's:

```bash
DRAFTBOT_DEV_PROJECT=draftbot-dev2 DEV_EDGE_PORT=28080 DEV_WEB_PORT=28000 DEV_SIM_PORT=28090 \
  DEV_PANEL_PORT=28091 DEV_DB_PORT=25432 \
  DEV_EDGE_SUBNET=10.203.150.0/28 DEV_EDGE_IP=10.203.150.2 DEV_EDGE_IP_RANGE=10.203.150.8/29 \
  scripts/fixture_to_test.sh
```

Changing only the subnet fails late, at the last step, with `invalid ip-range` above `A service
didn't become healthy`. Keep the same variables set for every `docker compose` command against
the stack (with `-p draftbot-dev2`), and always clean it up with
`scripts/clean_containers.sh --project draftbot-dev2` ([Cleaning up](#cleaning-up)).

## The control panel

http://localhost:18091 is a UI over the dev control API
([devtools/README.md](../../devtools/README.md)) and the simulator's control API
([services/discord-sim/README.md](../../services/discord-sim/README.md)). It only ever talks
to its own origin: nginx in the container proxies `/_control/` to `web` and `/_sim/` to
`discord-sim`. Keys `1` to `4` switch screens.

The header has the **DEV ONLY** badge, the loaded community, season and draft mode, health dots
for web, the simulator and the bot's gateway session, **Pause timers** / **Resume timers** for
every match, and **Reset…**, which puts the league back to the fixtures and the simulator back to
its seed.

1. **Players.** Add fake players with a rating or a rating range, DMs open or closed, straight
   into the queue. Edit a rating in place, flip DMs, give each player the champions they prefer
   and ban (the autopilot uses them), queue or unqueue a selection, delete.
2. **Queue & matches.** The queue, **Fill to 12**, and a card per live match: status, whose turn
   it is, teams, picks and bans, check-ins, swaps and a live countdown.
   - **Complete phase** plays out the current phase as the players who still have to act;
     **Advance to ▸** keeps going until a status.
   - The selector at the top picks how: **Discord clicks** (the bot's own handlers run, through
     the simulator), **league services** (direct calls, faster), or **Auto** (clicks while the bot
     is connected).
   - **Pause timer**, **Resume timer** and **Fire now** for that match.
   - **Act as…** sends one action as one player: only the actions the phase allows, with their
     arguments filled in (check-in, swap, sub, report, dispute and so on).
   - **Script…** stores a plan the autopilot follows: draft order, champion steps, captain votes,
     the coinflip side, the lobby code and the winner.
3. **Discord view.** The simulated guild as the bot wrote it. Pick a channel, or a user's DMs, to
   see messages with their buttons and selects, and press any of them as any fake user. A button
   that opens a form (the report, say) shows it, with a file picker for the screenshot. Type a
   message to chat as someone. **raw** shows the Discord payload. On the right, the simulator's
   live log of every REST call, gateway event and control call.
4. **Scenarios.** See below.

Screenshots of each screen are a good start for a runbook: take them at the pauses of a scenario.

## Scenarios and the runbook mode

A scenario is a list of control API calls in `devtools/scenarios/<name>.json`:

| Scenario | What it shows |
|---|---|
| `full_match` | A whole ranked match, from an empty queue to the posted result, one phase per step |
| `ready_check_miss` | Two players miss the ready check: cooldowns, and their seats offered to the queue and filled |
| `checkin_miss` | A captain misses the check-in, the next player in the vote takes over |
| `sub_mid_draft` | A player subs out during the player draft, and the next in the queue takes the spot |
| `swap_players` | After the draft, one captain offers a swap and the other accepts |
| `lobby_code_fallback` | deadlock-api can't make the lobby, so the host creates one and enters its code |
| `dispute_result` | The captains disagree on the result, and staff settle it |
| `restart_after_unfilled_sub` | Nobody takes a seat left during the draft, so the lobby restarts with a fresh captain vote |

On the **Scenarios** screen, pick one, then:

- **Next step** (`N`) runs one step and stops: the runbook mode. At each stop, look at the match in
  **Discord view** (what players see), **Queue & matches** (what the league thinks), or the
  admin at http://localhost:18080/admin/.
- **Run** (`P`) goes on to the end; **Pause** (`P`) stops before the next step. Click a step's
  number to set a breakpoint, so a run pauses before it. **Seconds between steps** slows a run
  down for watching or recording.
- **Rewind** (`R`) starts over. Each step's result shows what it did against what it expected;
  **Stop when a step doesn't do what it expects** turns a surprise into a pause.
- The steps are editable JSON, and **Custom steps…** starts from an empty list.

Freeze the timers (**Pause timers**) whenever you need longer than a phase allows.

The same from a shell:

```bash
curl -s -X POST localhost:18000/_control/api/reset
curl -s -X POST localhost:18000/_control/api/queue/fill
curl -s -X POST localhost:18000/_control/api/matches/latest/advance -d '{"until": "champion_draft"}'
dc exec web python manage.py dev_scenario --list
dc exec web python manage.py dev_scenario full_match
dc exec web python manage.py dev_scenario full_match --from 2 --count 3
```

### Adding a scenario

1. Write `devtools/scenarios/<name>.json`: `{"description": "...", "steps": [...]}`, each step
   `{"title": "...", "method": "POST", "path": "matches/latest/advance", "body": {...}}`. Start
   from a reset, and end each step at a state you can name (`advance` with `until`).
2. Run it: `dc exec web python manage.py dev_scenario <name>` prints each step's status and time.
   The panel lists it straight away.
3. Add its end-state check to `CHECKS` in `tests/test_devtools_scenarios.py` (the service path)
   and `tests/e2e/test_scenarios.py` (through the panel and the bot). Both suites fail on a
   scenario that has no check.

## Real-Discord mode

To try the bot on a real test server instead of the simulator:

1. Copy `.env.example` to `.env` and set `DISCORD_TOKEN` and `DISCORD_GUILD_ID` for a bot you
   invited to that server (see the main README's [Run it](../../README.md#run-it)).
2. Run `scripts/fixture_to_test.sh --real-discord`.

That starts the same dev stack with `.env` as the app's env file, without the simulator, and
skips the dev seed (fake players can't exist on a real server). The dev settings still apply, so
`/_control/` is there, but its `via: "discord"` actions need the simulator. Run `/setup` in your
server as usual. Switch back with a plain `scripts/fixture_to_test.sh`. deadlock-api is the real
one in this mode, so the bot's lobbies are real lobbies.

## Metrics and dashboards in dev

Prometheus, Grafana and the exporters are opt-in. Two secrets first:

- Grafana's admin password, in a file only Grafana and Alertmanager read:
  `cp .env.observability.example .env.observability` and set `GRAFANA_ADMIN_PASSWORD` there.
- The exporters' database password, `DB_MONITOR_PASSWORD` (16 or more letters and digits), in
  your shell. compose needs it for every command that includes the overlay, `stop`, `logs` and
  `down` too, and refuses to run without it.

Then add the overlay to the dev stack:

```bash
export DB_MONITOR_PASSWORD=devmonitor1234567
DRAFTBOT_OBSERVABILITY=1 scripts/fixture_to_test.sh
# or, with the stack already up:
docker compose -p draftbot-dev -f compose.yaml -f compose.dev.yaml -f compose.observability.yaml \
  --profile sim up -d
```

Once the overlay runs, `fixture_to_test` keeps it on every later run. Grafana is at
http://127.0.0.1:13000 (user `admin`) and Prometheus at http://127.0.0.1:19090 (`GRAFANA_PORT`
and `PROMETHEUS_PORT` move them). `Watchdog` always fires, on purpose
([../ops/alerts.md](../ops/alerts.md#watchdog)), and the TLS probe fails without TLS, so
`CertificateProbeFailing` fires after 30 minutes: ignore both in dev. `scripts/clean_containers.sh`
removes the overlay with the rest of the stack. [../ops/observability.md](../ops/observability.md)
describes the dashboards, and [infra/observability/README.md](../../infra/observability/README.md)
its files.

## Tests

```bash
scripts/test.sh --local         # the unit suite with uv on this machine: the fastest loop, and CI's
scripts/test.sh                 # the unit suite in a clean container stack
scripts/test.sh e2e             # the browser suite against the whole stack
scripts/test.sh all             # unit, then e2e
scripts/test.sh --local -- tests/test_flow.py -k ready    # anything after -- goes to pytest
```

On Windows use `scripts\test.bat` with the same arguments. The exit code is the test result, and
every stack is torn down afterwards, pass or fail.

- **`--local`** starts `compose.test.yaml`'s Postgres (the pinned image, on tmpfs, with the test
  settings) as project `draftbot-test-local` on `127.0.0.1:15433` (`DRAFTBOT_TEST_PG_PORT`), runs
  `uv run pytest -n auto` against it, and removes it. Run `uv sync` once first. It ignores the
  database in your `.env`. Each xdist worker gets its own test database, so `-n auto` uses every
  core. It refuses to start while another `--local` run of the same project holds that Postgres.
- **unit** builds `scripts/docker/tests.Dockerfile` (the locked dependencies with the dev group,
  and the repo with its tests), starts Postgres on tmpfs in the `draftbot-test` project and runs
  `pytest -n auto`. Nothing touches your machine's Python.
- **e2e** starts the whole graph in `draftbot-test` (the app behind pgbouncer with `dev_seed`,
  the simulator, the control panel and a Playwright server in `chrome`), waits for it to be
  healthy, then runs `tests/e2e` in the `e2e` container. It takes about five minutes on top of the
  build. Traces, screenshots and videos land in `test-results/e2e/`; on failure the script also
  prints the last log lines of `web`, `bot`, `scheduler` and `discord-sim`.
  [tests/e2e/README.md](../../tests/e2e/README.md) has what each test proves and how to run them
  against your dev stack.

To run beside another test stack, give this one its own project and edge network, as for
[two dev stacks](#two-dev-stacks-at-once): `DRAFTBOT_TEST_PROJECT=draftbot-test2
TEST_EDGE_SUBNET=10.203.151.0/28 TEST_EDGE_IP=10.203.151.2 TEST_EDGE_IP_RANGE=10.203.151.8/29`,
and `DRAFTBOT_TEST_PG_PORT` for `--local`.

The simulator and the control panel have their own suites:

```bash
cd services/discord-sim && uv run pytest && uv run mypy
cd services/control-panel && npm ci && npm run typecheck && npm run lint && npm test && npm run build
```

### Lint and type checks

```bash
uv run ruff check . && uv run ruff format --check .
DEBUG=true DJANGO_SECRET_KEY=dev uv run mypy bot league config devtools
DEBUG=true DEV_CONTROL=true DJANGO_SECRET_KEY=dev DATABASE_URL=sqlite:///:memory: \
  uv run python manage.py makemigrations --check --dry-run
MYPYPATH=tests/e2e uv run --no-project --python 3.12 --with-requirements tests/e2e/requirements.txt \
  --with mypy==2.4.1 mypy --config-file= --strict --python-version 3.12 --explicit-package-bases tests/e2e
```

`uvx pre-commit install` runs the quick ones (ruff, yamllint, shellcheck, actionlint, hadolint,
whitespace and JSON checks) before each commit; `uvx pre-commit run --all-files` runs them over
everything. The Docker hooks need Docker running.

CI runs the same. `.github/workflows/ci.yml` has a job each for lint, the unit suite
(`test.sh --local`), the simulator, the panel, the compose files and the images, and calls
`e2e.yml` (`scripts/test.sh e2e`) on every push and on pull requests that touch the stack. Its
`CI OK` job passes only when all of them did, so it's the one check branch protection requires.
A push to `main` (or a `v*` tag) that passes publishes the app image it scanned. `deploy-lint.yml`
(the Ansible checks and Molecule) runs on its own, for changes under `deploy/`, `infra/` and the
compose files.

### Writing a migration

A release's migrations run while the previous release is still serving: `deploy.yml` runs the
migrate job with the new image, then recreates the services one at a time
([../ops/upgrades.md](../ops/upgrades.md#upgrade)). So a migration must work with both the old
code and the new:

- Add columns nullable or with a database default, and tables before the code that uses them.
- Remove or rename a column or table one release after the code stops using it.
- If a change can't be split like that, say so in the release notes: the operator stops `bot` and
  `scheduler` before deploying it.

## Debugging

- **What did the bot do?** The Discord view's event log, or `curl -s
  "localhost:18090/_sim/log?kind=rest&limit=50"`, lists every REST call with its status and body.
  `dc logs -f bot` has the bot's side.
- **A click did nothing.** A `via: "discord"` action that the bot refused answers 409 with the
  bot's words; one the bot never acted on answers 504 naming the match, its status and the
  enabled buttons; 503 `bot_offline` means no bot is connected to the simulator at all. Check
  `dc logs bot` for a handler error. The control API's errors are listed in
  [devtools/README.md](../../devtools/README.md#conventions).
- **403 from `/_control/` or `/_sim/`.** Both refuse state changes from a browser page on another
  origin, so a site you visit can't reset your database. Pages on localhost, 127.0.0.1 or the host
  being called get through, and clients that send no `Origin` header (curl, the e2e suite, the
  bot) aren't affected.
- **An effect is stuck.** The admin's Outbox effects page, filtered to `failed` or `pending`,
  shows the last error. `GET /_control/api/state` shows the match as the league sees it.
- **Timers move on while you look.** Pause them in the panel's header, or
  `curl -s -X POST localhost:18000/_control/api/timers/pause`.
- **Fault injection.** `POST /_sim/faults` makes the next matching REST calls fail (429, 500 and
  so on) to exercise retries; see the simulator's README.
- **A Python shell with the dev settings.** `dc exec web python manage.py shell`.
- **psql.** `dc exec db psql -U draftbot`, or any client on `127.0.0.1:15432`. pgbouncer's
  console only lets in its stats user, `draftbot_monitor`, so it needs the
  [observability overlay](#metrics-and-dashboards-in-dev) (add `-f compose.observability.yaml`
  to `dc`): `dc exec pgbouncer sh -c 'PGPASSWORD=$DB_MONITOR_PASSWORD psql -h 127.0.0.1 -p 6432
  -U draftbot_monitor pgbouncer -c "SHOW POOLS"'`.
- **Logs as JSON.** `LOG_FORMAT=json scripts/fixture_to_test.sh` gives the production format.
- **Windows.** If the local unit suite stalls connecting to Postgres, use `127.0.0.1` rather than
  `localhost` in any `DATABASE_URL` you set yourself; the scripts already do.
- **Ports in use.** Every host port is a variable (see [Ports](#ports)).

## Cleaning up

```bash
scripts/clean_containers.sh     # Windows: scripts\clean_containers.bat
```

With no `--project`, this removes everything the dev and test projects left behind:
`draftbot-dev`, `draftbot-test`, and `DRAFTBOT_DEV_PROJECT`'s and `DRAFTBOT_TEST_PROJECT`'s if
they're set. That is their containers, volumes (your dev database too), networks and the images
they built, the `--local` test Postgres, and the `staticfiles/` and `test-results/` folders. It
prints each thing it removes. Other compose projects, including the base `dl-mm-discord`, and
images you pulled are left alone; it never prunes.

So with a second stack's `DRAFTBOT_DEV_PROJECT` exported, a bare run removes the first stack too:
pass `--project` whenever you mean one stack.

| Flag | What it does |
|---|---|
| `--project NAME` | Cleans only this project (repeat for more), and leaves the `--local` Postgres and the output folders alone |
| `--local-pg` | With `--project`: also each project's `--local` Postgres (`NAME-local`) |
| `--outputs` | With `--project`: also `staticfiles/` and `test-results/` |
| `--keep-images` | Keeps the built images, so the next start is quicker |
| `--dry-run` | Only prints what it would remove |

## Ports

Everything binds to 127.0.0.1 only. The test stack publishes nothing.

| Port | Variable | Service |
|---|---|---|
| 18080 | `DEV_EDGE_PORT` | dev edge (the web UI and admin as players reach them) |
| 18000 | `DEV_WEB_PORT` | dev web, direct |
| 18090 | `DEV_SIM_PORT` | dev Discord simulator |
| 18091 | `DEV_PANEL_PORT` | dev control panel |
| 15432 | `DEV_DB_PORT` | dev Postgres |
| 13000 | `GRAFANA_PORT` | Grafana, with `compose.observability.yaml` |
| 19090 | `PROMETHEUS_PORT` | Prometheus, with `compose.observability.yaml` |
| 15433 | `DRAFTBOT_TEST_PG_PORT` | `scripts/test.sh --local` Postgres |
| 5174 | | control panel Vite dev server (`npm run dev` in `services/control-panel/`) |
| 18099 | | control panel mock APIs (`npm run mock`) |
| 8000 | `EDGE_PORT` | the base `compose.yaml` edge (not the dev stack) |
| 55432 | `DB_PORT` | the base `compose.yaml` Postgres (not the dev stack) |

The dev stack's edge network is `DEV_EDGE_SUBNET` (default `10.203.140.16/28`), with the edge at
`DEV_EDGE_IP` (`10.203.140.18`) and every other address from `DEV_EDGE_IP_RANGE`
(`10.203.140.24/29`); the test stack's are `TEST_EDGE_*` (`10.203.140.32/28`, `.34`,
`.40/29`). Change all three together, as in [two dev stacks](#two-dev-stacks-at-once).
`.env.dev.example` lists every compose variable and its default.
