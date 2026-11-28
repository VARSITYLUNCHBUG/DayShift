# Developing the bot locally

The whole stack runs on your machine without a Discord server: the real bot talks to a Discord
simulator, a control panel gives you fake players and lets you play every phase of a match, and
the tests run in containers. [../architecture.md](../architecture.md) shows how the services fit.

Everything goes through the Makefile; `make` lists the targets.

## Your machine

- **Linux:** Docker Engine with the compose plugin, make, and [uv](https://docs.astral.sh/uv/)
  (it installs the right Python itself).
- **Windows:** [Multipass](https://canonical.com/multipass) (`winget install Canonical.Multipass`),
  then:
  ```powershell
  scripts\dev-vm.ps1                 # once: makes the dayshift-dev VM and copies this checkout in
  scripts\dev-vm.ps1 make dev        # copy the checkout in again, then run any make target there
  scripts\dev-vm.ps1 shell           # a shell there, in its copy (`sync` first after editing)
  ```
  The VM is Ubuntu 24.04 with Docker, make and uv, and gets half this PC's CPUs and memory and a
  60 GB disk (`-Cpus`, `-MemoryGB`, `-DiskGB` change that when it's made). Before each command
  the script brings the VM's copy in line with this checkout, in about two seconds: every file Git
  tracks or would track, plus `.env`, `.env.dev` and your deploy inventories. The copy lives on
  the VM's own disk, so builds and tests run at native speed and Multipass needs no shared
  folders. The dev stack's ports answer on the VM's address, which the script prints.

  Edit and commit on Windows. `scripts\dev-vm.ps1 make check` runs every hook in the VM before
  you push. Installed on Windows, the hooks run there too, except two that need Linux
  (`compose`, which uses make, and `ansible-lint`): `uv run pre-commit install`, then
  `set SKIP=compose,ansible-lint` in that shell.

Then, once (on Linux):

```bash
make setup          # uv sync, and the pre-commit hooks
```

## The dev stack

```bash
make dev            # build, start, migrate, seed fixtures/dev, print the URLs
make superuser      # an admin login: asks for a Discord ID (a fixture player's gives them the login)
make dev-logs       # follow the logs
make dev-stop       # stop, keeping the data
make dev-reset      # drop the database and start again from the fixtures
```

`make dev` is safe to run again: it rebuilds what changed and keeps your data. It starts Postgres
and the simulator, runs the migrations, `load_presets` and `dev_seed`, then web, the bot, the
edge and the control panel, and waits for each to be healthy.

| What | URL |
|---|---|
| Admin, through the edge | http://localhost:18080/admin/ |
| Control panel | http://localhost:18091 |
| Dev control API | http://localhost:18000/_control/api/ |
| Discord simulator | http://localhost:18090/_sim/state |
| Postgres | `127.0.0.1:15432`, user `dayshift`, password `dev` |

`dev_seed` loads `fixtures/dev/*.json` (a community, a season, staff grants, 14 players, their
dev profiles and a ping), lays the simulator's guild out the way `/setup` would, and seeds the
ratings. `compose.dev.yaml` gives every app service `DEBUG=true` and `DEV_CONTROL=true` (the
`/_control/` API), and `.env.dev` (made from `.env.dev.example`) points the bot at the simulator.
With `DISCORD_SIM_URL` set, deadlock-api calls go to the simulator's stand-in too, so the dev
stack never creates real lobbies. Every host port is a variable (`.env.dev.example` lists them).

**Real Discord.** Copy `.env.example` to `.env`, set `DISCORD_TOKEN` and `DISCORD_GUILD_ID` for
a bot invited to a test server, and run `make dev REAL_DISCORD=1`. No simulator and no seed;
run `/setup` in the server as usual.

## The control panel and scenarios

http://localhost:18091 is a UI over the dev control API ([devtools/README.md](../../devtools/README.md))
and the simulator's ([services/discord-sim/README.md](../../services/discord-sim/README.md)):

1. **Players**: fake players with ratings, DMs open or closed, champion preferences; queue them.
2. **Queue & matches**: **Complete phase** plays the current phase as the players who still have
   to act, through Discord clicks or straight service calls; **Act as…** sends one action as one
   player; pause, resume or fire a match's timer.
3. **Discord view**: the simulated guild as the bot wrote it. Press any button as any user.
4. **Scenarios**: the presets in `devtools/scenarios/` (a full match, a missed ready check, a
   dispute, a sub mid-draft and more), one step at a time or to the end.

From a shell: `docker compose -p dayshift-dev -f compose.yaml -f compose.dev.yaml exec web python
manage.py dev_scenario full_match`. A new scenario needs its end-state check in
`tests/test_devtools_scenarios.py` and `tests/e2e/test_scenarios.py`; both fail without one.

## Checks and tests

```bash
make check                          # every pre-commit hook over the whole tree
make test                           # the unit suite
make test ARGS="tests/test_flow.py -k ready"
make test-fresh                     # new test databases (after editing a migration)
make e2e                            # the browser suite against the whole stack
make sim-test panel-test            # the simulator's and the control panel's own suites
make clean                          # remove everything the dev and test stacks made
```

- **Before each commit** the hooks run what applies to the files you changed: ruff, mypy, the
  migration check, the fixture rule, yamllint, actionlint, hadolint, the compose files and
  ansible-lint. `make check` runs all of them; CI runs exactly that too.
- **`make test`** runs pytest in the Dockerfile's `test` image (the locked dependencies are cached
  layers; only the code is copied each time) against a Postgres on tmpfs that stays up between
  runs, so `--reuse-db` skips creating and migrating a database per xdist worker. Hypothesis
  runs its quick profile; CI uses `HYPOTHESIS_PROFILE=ci` for the thorough one.
- **Tests that need played matches** but aren't about the flow build them with `tests/factories.py`
  (the lobby pops through the real queue, the drafts are written as they'd end, the result is
  reported for real). The flow tests play every phase with `tests/helpers.py`.
- **`make e2e`** takes about five minutes on top of the build; traces, screenshots and videos land
  in `test-results/e2e/`. [tests/e2e/README.md](../../tests/e2e/README.md) says what each test
  proves.

### Models and fixtures

A model change needs its migration (`manage.py makemigrations`; the hook refuses a model without
one). A new model also needs rows in `fixtures/dev`, or an `EXEMPT` entry in
`league/management/commands/check_fixtures.py` saying where its rows come from instead (the
presets, the ledger, or matches being played). `make check`, the hook and `tests/test_fixtures.py`
enforce it. [fixtures/dev/README.md](../../fixtures/dev/README.md) has the files and their pks.

Business rules about one model live on it: `Match.objects.lock()`, `match.mode`,
`match.captain_of()`, `match.record_transition()`, `match.participants.active()` and
`.roster()`, `Season.objects.open_for()`, `season.rating_of()`, `Player.objects.from_discord()`.
`league/services` holds the transactions that span models, and the bot's handlers and commands
only call those.

A release's migrations run while the previous release still serves, so add columns nullable or
with a default, and remove a column one release after the code stops using it.

## Load test

Many matches at once on a real Discord test server, with chat flooding every match channel, to
see how close the bot comes to Discord's limits. Run a dev stack on the real-Discord token
(`.env` with no simulator settings), with the request log on, then:

```bash
LOG_FORMAT=json DISCORD_REQUEST_LOG=1 docker compose -f compose.yaml -f compose.dev.yaml up -d
docker compose -f compose.yaml -f compose.dev.yaml exec web python manage.py dev_loadtest --matches 12
docker compose -f compose.yaml -f compose.dev.yaml logs bot --since 15m --no-log-prefix \
  | python devtools/loadtest_report.py
```

- **`dev_loadtest`** makes stand-in players as needed, pops `--matches` matches at once, pauses
  their timers and plays every phase through the services, `--moves` moves per match each
  `--tick` seconds. Chat comes from two webhooks per match channel at `--chat-rate` messages a
  second of `--chat-lines` lines each; Discord lets webhooks post about 30 a minute in a channel.
- **The report** gives the busiest second against Discord's 50, every 429 by route and scope, the
  refused requests Discord counts towards its ban, each bucket by how close it came to running
  out, and latency by route.
- Stand-ins have made-up Discord IDs, so their DMs, voice moves and member permissions come back
  400 or 404. Those don't count towards Discord's ban, but real members would add requests the
  test can't make.

## Debugging

- **What did the bot do?** The Discord view's event log, or
  `curl -s "localhost:18090/_sim/log?kind=rest&limit=50"`; `make dev-logs` for the bot's side.
- **A click did nothing.** A `via: "discord"` action the bot refused answers 409 with the bot's
  words; 504 names the match, its status and the enabled buttons; 503 `bot_offline` means no bot
  is connected to the simulator.
- **An effect is stuck.** The admin's Outbox effects page, filtered to `failed` or `pending`.
- **Timers move on while you look.** Pause them in the panel's header.
- **Fault injection.** `POST /_sim/faults` makes the next matching REST calls fail.
- **A shell.** `make shell`; psql with `docker compose -p dayshift-dev -f compose.yaml -f
  compose.dev.yaml exec db psql -U dayshift`.
