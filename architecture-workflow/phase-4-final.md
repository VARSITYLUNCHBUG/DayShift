# Phase 4: The result

Branch `architecture-cleanup`, 8 commits on `origin/main` (`edfbbb7`): **301 files changed, 3,351
insertions, 18,597 deletions.** The current architecture is in
[../docs/architecture.md](../docs/architecture.md); this page is the before and after.

## Architecture changes

| Area | Before | After |
|---|---|---|
| Production containers | 14 long-running (6 app and infrastructure, 8 observability), plus migrate and certbot | 4 (edge, web, bot, db), plus migrate |
| Edge | nginx with 11 snippets, certbot, a renew timer, an ACME-only site, SAN drift checks | Caddy with a 40-line Caddyfile; HTTPS is automatic when `EDGE_SITE` is a domain |
| Static files | Copied by migrate to a shared volume the edge served | WhiteNoise in web, with hashed names, gzip, immutable caching |
| Database | pgbouncer, 3 logins, `direct` alias and router, 3 connection modes | One `DATABASE_URL`, one login |
| Bot | `gateway` and `scheduler` containers | One `runbot` process: gateway, effects, deadlines, watchdog |
| Health | Prometheus, Alertmanager, Grafana, 5 exporters, 22 alerts, 5 dashboards, `/metrics` | Healthchecks, `/readyz`, the heartbeat, a minute-by-minute watchdog to the operator's channel, an optional dead man's switch, and a host timer to a webhook |
| Django layering | Anemic models; the Match state machine and every one-model query in `services/common.py` | Querysets and methods on `Match`, `MatchParticipant`, `Season` and `Player`; services keep the cross-model transactions; the bot and admin call services |
| Dependencies | 86 locked packages (Channels, Daphne, Twisted, prometheus-client and others) | 65 plus pre-commit's tools |
| Dev control | ~1,100 lines of `.sh` and `.bat` triplets | One Makefile; Windows uses a Multipass VM (`scripts/dev-vm.ps1`) |
| Test image | A separate Dockerfile reinstalling everything | The Dockerfile's `test` target: cached dependency layers, code last (4 s rebuild) |
| Unit suite | 442 s; 40 subprocess settings tests; infrastructure tests; every rating test plays full matches | 191 s with uv on Windows; **121 s** warm on `make test`'s path; in-process settings tests; factories for played matches; quick and thorough Hypothesis profiles |
| Fixtures | 6 of 33 models seeded, nothing required | `check_fixtures`: every model has rows or a written exemption (pre-commit, test) |
| CI | 12+ jobs per PR, 4 image builds, e2e, Molecule (20 min) | Checks (pre-commit) and Unit tests per PR; image build, scan, push, attest and release on main and tags; e2e by hand |
| Deploy | 6 roles, ~190 tasks, 5 playbooks, Molecule | 2 roles (`host`, `app`), 4 playbooks; copy the compose files, template `.env`, pull, `up --wait` |
| Docs | 8 ops runbooks (1,060 lines), plus a 411-line dev guide | One deploy guide, a dev guide around the Makefile, an architecture page |

## Health scores

| Dimension | Before | After | Why |
|---|---:|---:|---|
| Data integrity and concurrency | 8 | 8 | Unchanged on purpose: row locks, version checks, the outbox and the append-only ledger |
| Cohesion (Django layering) | 4 | 7 | Model rules live on models. The large services (`boards`, `subs`, `lobby`, `draft`) are still large |
| Coupling | 5 | 6.5 | The bot's commands and handlers call services; `bot/effects/handlers.py` still reads the ORM for rendering |
| Testability and test speed | 3 | 6.5 | 442 s to 121–191 s. About 150 transactional tests still flush per test |
| Developer loop | 3 | 7.5 | One Makefile, cached layers, a reused test database. The Windows VM script isn't run yet |
| CI proportionality | 2 | 8 | Two PR jobs, both on a dev machine first; Scorecard's checks covered where a solo repo can |
| Deploy simplicity | 2 | 7.5 | Two roles and a template. Not yet run against a server |
| Observability proportionality | 2 | 8 | Healthchecks plus a few signals that each mean "act now" |
| Security posture | 8 | 7.5 | Same hardening and pins, signed provenance added. Lost: the least-privilege app login and nginx's rate limit on the admin login (see R4) |
| **Overall** | **4.1** | **7.4** | |

## Verification summary

| Check | Result |
|---|---|
| ruff, ruff format, mypy (169 files), `makemigrations --check`, `check_fixtures` | Pass |
| Unit suite, final tree | 770 passed, 3 skipped (OCR) |
| Each commit's tree | The model move passed alone (767); the final tree passed (770) |
| Runtime and test images | Built; a code change rebuilds the test image in 4 s |
| Quickstart stack through Caddy | Healthy; `/readyz` and admin 200; static files gzipped and cached; the admin allowlist answers 403 |
| `make help`, `make compose-check` | Pass in a Linux container |
| Every compose combination (`docker compose config`) | Valid |
| ansible-lint (production profile), playbook syntax | Pass on Linux |
| pre-commit, all hooks | Pass, except two that can't run on native Windows (ansible-lint; uv's cache lock for strict e2e mypy). Both passed in Linux containers |
| Browser suite (e2e) on the final stack | 15 passed in 250 s; 329 s with the build and start (was 6–7 min) |

## Remaining work

| ID | Item | Priority |
|---|---|---|
| R1 | ~~Deploy to a test server~~. **Done:** `site.yml` moved bebot-sim from the old 14-container stack in place, a re-run changed nothing, and the upgrade, the restore and the health alerts all worked (phase-3-fixes.md, "On the VMs"). Still to do once: a real domain getting a Let's Encrypt certificate | LOW |
| R2 | ~~Run `scripts\dev-vm.ps1`~~. **Done:** it now copies the checkout into the VM instead of mounting it. `make test` passed 770 in 183 s, `make dev` was reachable from Windows, and `make clean` left nothing | — |
| R3 | The first GitHub Actions run of the new `ci.yml`. Keep `CI OK` as the required check (same name as before); check Scorecard's next result | MEDIUM |
| R4 | Admin login brute force: nginx rate-limited it, and Caddy core has no rate limit. Set `draftbot_admin_cidrs` on servers whose admin is only for known addresses, or add a login throttle in Django if it must be public | MEDIUM |
| R5 | About 150 transactional tests (`test_bot`, `test_handlers`, `test_permissions`) flush and reseed per test, because handlers reach the database from the async `db()` thread. A same-thread `db()` under tests would let most of them roll back instead | MEDIUM |
| R6 | Split the largest services (`boards` 814 lines, `subs` 798, `lobby` 725, `draft` 639). This needs the file-split protocol | LOW |
| R7 | `bot/effects/handlers.py` reads the ORM about 10 times to render; read models in `league/services/boards.py` would finish thinning it | LOW |
| R8 | ~~Restore drill~~. **Done** on bebot-sim. The database there was empty; repeat it on a server with real history | LOW |
| R9 | Scorecard's Branch-Protection and Code-Review stay capped by one maintainer, and Fuzzing doesn't count Hypothesis. Accepted | — |
