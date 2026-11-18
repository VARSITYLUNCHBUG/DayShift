# Phase 2: Diagnosis

Lenses used:
- **Software architecture:** Django layering, coupling and cohesion, testability.
- **Infrastructure:** deploy, CI, observability, and their cost against the stated scale.

The target is a hobby install with at most 50 people at once, long idle stretches, and one
operator.

## Health scores

| Dimension | Score | Key issue |
|---|---:|---|
| Data integrity and concurrency | 8/10 | Row locks, version checks, the outbox and the append-only ledger are solid. Keep them |
| Cohesion (Django layering) | 4/10 | Anemic models. The Match state machine and query helpers live in `services/common.py` |
| Coupling | 5/10 | Bot commands, handlers and the effect executor query the ORM directly, and one writes |
| Testability and test speed | 3/10 | About 150 flush-per-test transactional tests, no factories, 40 subprocess tests, infra tests in the unit suite |
| Developer loop | 3/10 | ~1,100 lines of `.sh` and `.bat` triplets, a tests image that reinstalls every dependency, no Makefile, no Windows VM path |
| CI proportionality | 2/10 | 12+ jobs per PR, 4 image builds, Trivy, the e2e stack, and ~20 min of Molecule on deploy paths |
| Deploy simplicity | 2/10 | 6 roles (~192 tasks), 5 playbooks, nginx + certbot + renew timers, pgbouncer, 3 DB logins |
| Observability proportionality | 2/10 | 8 observability containers against 6 app ones, 22 alerts, 5 dashboards, a 315-line runbook |
| Security posture | 8/10 | Good, but bought with complexity that this scale doesn't need |
| **Overall** | **4.1/10** | The core is sound; everything around it is sized for a much larger platform |

## Findings

| ID | Finding | Severity | Impact | Effort | Unlocks |
|---|---|---|---|---|---|
| F1 | CI runs on every PR what a dev machine should catch: infra-lint (hadolint, shellcheck, actionlint, promtool, amtool), compose checks, 4 image builds, sim and panel suites, Trivy, e2e (`.github/workflows/ci.yml`, 389 lines) | HIGH | Every PR waits on 12+ jobs, and green CI needs ~10 runners | Moderate | – |
| F2 | Molecule (`deploy/ansible/molecule/`, 1,634 lines, a fake Django package, privileged DinD ×2 distros) | HIGH | 20 min in CI and 46 min locally. It is the longest step | Quick | F1 |
| F3 | Deploy has too many moving parts: nginx + certbot + ACME-only site + renew timer + SAN drift checks, pgbouncer config shipped to the host, 6 roles, 5 playbooks, rotate-secrets resyncs | HIGH | ~5,400 lines to maintain for one compose project | Significant | F4, F5 |
| F4 | Observability is bigger than the app: Prometheus, Alertmanager, Grafana, 5 exporters, 22 alerts, 5 dashboards, plus `bot/metrics.py` and `league/observability/` | HIGH | 8 extra containers, about 1 GB of RAM on a small VPS, a monitor DB role, 2 password tasks | Moderate | F3, F5 |
| F5 | DB topology is oversized: pgbouncer for 3 processes using 2–3 connections, 3 connection modes in settings, an unused `direct` alias and `config/db_router.py`, 3 Postgres logins with bootstrap code (`config/app_role.py`, `monitoring_role.py`) | MEDIUM | Every environment carries two URLs, two password tasks and pgbouncer quirks (`DISABLE_SERVER_SIDE_CURSORS`, `SIGINT`) | Moderate | F3, F10 |
| F6 | Dead player-web-UI scaffolding on main: `WEB_GUILD_ID`, `PUBLIC_URL`, `DISCORD_CLIENT_*`, `WEB_DEV_LOGIN` (`config/settings.py:294-305`), Channels' `ProtocolTypeRouter` with HTTP only (`config/asgi.py:30`), and `frontend/` in `.dockerignore` and the CI path filter | MEDIUM | Settings and tests guard features that don't exist | Quick | F5, F10 |
| F7 | Anemic models: only `__str__`, with no Managers or QuerySets. `services/common.py` holds the Match state machine (`transition`, `bump`, `lock_match` with 46 call sites, `mode_of` with 30, `active_participants`, `on_hold`) and one-model helpers are spread across 15 services | HIGH | Business rules for a model are found by grep, not on the model, and literals such as `("completed","voided")` repeat | Significant | F8, F9, F11 |
| F8 | The bot layer reaches into the ORM: a write transaction in `bot/commands/staff.py:570`, reads in commands, handlers and `bot/effects/handlers.py`, and a participant filter re-implemented 4 times | MEDIUM | Views aren't thin; the same rule exists in several places | Moderate | – |
| F9 | Admin actions orchestrate transactions (`league/admin/__init__.py:410-438` `start_next_season`, `:398` `save_model`) | LOW | A second entry point with its own rules | Quick | – |
| F10 | The test suite is slow by construction (details below) | CRITICAL | Baseline: see "Measured baseline" | Significant | F11 |
| F11 | Fixtures aren't enforced: 6 of about 33 concrete models have a row in `fixtures/dev`. There's no factory layer; every test plays the real flow to build state | HIGH | A new model ships without seed data, and tests stay slow | Moderate | F10 |
| F12 | No single control surface: `scripts/{fixture_to_test,test,clean_containers}.{sh,bat}` (~1,100 lines), no Makefile, no Multipass dev VM for Windows | HIGH | Two scripting dialects to maintain; Windows depends on Docker Desktop | Moderate | F13 |
| F13 | Image layers: `scripts/docker/tests.Dockerfile` reinstalls uv and every dependency separately from the app image and copies the whole repo last. The test stacks rebuild with `--build` and tear down on every run | MEDIUM | Each unit run rebuilds; no cache is shared between the app and test images | Quick | F10 |
| F14 | Dev tooling sprawl: `services/control-panel` (React, 4,944 lines), Playwright e2e with a chrome container, and the devtools autopilot (1,010 lines) | MEDIUM | The e2e stack takes 6–7 min and needs the panel; this is your call | – | F1 |
| F15 | Docs sprawl: 8 ops runbooks, 1,060 lines, mostly about the parts F3–F5 remove | LOW | Docs go stale as the stack shrinks | Quick | – |

| F16 | Scorecard gaps. **Packaging:** the publish uses `skopeo copy`, which Scorecard doesn't recognise as packaging; `docker/build-push-action` with `push: true` is recognised. **Signed-Releases:** there are no GitHub releases with signature or provenance assets. **Pinned-Dependencies:** `pip install -r` without hashes in `deploy-lint.yml`, and `certbot/certbot:v5.10.0` is pinned by tag only | MEDIUM | These lose Scorecard points, and the skopeo step exists only because of the scan-then-push design | Quick | F1 |

### Measured baseline (this PC, 12 cores, `scripts/test.sh --local`)

The run took **442 s (7 m 22 s)** of pytest and 476 s end to end: 875 passed, 4 skipped.

| Cost | Seconds |
|---|---:|
| `test_stateful.py::test_match_machine[0-9]` | 74–105 each, about 890 summed |
| `test_rules`, `test_ledger`, `test_ratings_flow`, `test_standing` multi-match tests | 30–76 each. A full match costs about **10 s**, which a flow-built test pays every time |
| Per-worker database creation (the first test's `setup` on each xdist worker) | about **20 s** per worker, every run, because there's no `--reuse-db` |

Because the stateful machine's chunks are each longer than the rest of a worker's queue, they set
the wall-clock time. With the Hypothesis example count and the flow-built fixtures fixed, the suite
should fit inside 1–2 minutes.

### Scorecard alignment (https://scorecard.dev, checks.md)

The slimmer CI must keep or earn these:

| Check | Keep or do |
|---|---|
| CI-Tests | A PR check whose name contains `test` must run and pass: keep a `Tests` job on every PR |
| SAST | CodeQL (default setup) stays on, on every PR |
| Token-Permissions | Top-level `permissions: {}` or `contents: read`, with write granted per job only (publish: `packages: write`) |
| Pinned-Dependencies | Actions by full SHA; every `FROM` and compose image by digest, Caddy included; no unhashed `pip install` in workflows or scripts. Tools run through `uv` from `uv.lock`, or `uvx tool==x.y.z` |
| Packaging | Publish with `docker/build-push-action` and `push: true`, instead of skopeo |
| Signed-Releases | On a `v*` tag, a GitHub Release whose assets include the build's provenance (`*.intoto.jsonl`, or the `*.sigstore.json` bundle from `actions/attest-build-provenance`) and the SBOM |
| SBOM | Keep `sbom: true` and `provenance: mode=max` on the image build |
| Dependency-Update-Tool | Keep Dependabot, trimmed to the ecosystems that remain |
| Vulnerabilities | Dependabot security updates on `uv.lock` and the npm lockfile. A Trivy scan of the published image moves to the push to main, off pull requests |
| Dangerous-Workflow | No `pull_request_target` or `workflow_run` and no untrusted contexts in `run:`. Holds today; keep it |
| Security-Policy, License | `SECURITY.md` and `LICENSE` stay |
| Branch-Protection, Code-Review, Contributors | Capped by one maintainer. Keep: PR required, a required status check, no force push, no deletion, code-owner rule |
| Fuzzing | Hypothesis isn't recognised. Accept the gap; ClusterFuzzLite is out of proportion here |
| Binary-Artifacts | The OCR `.onnx` and `.npz` assets are data, not executables. Nothing is flagged today; keep it that way |

### F10 in detail: why the tests are slow

1. **About 150 transactional tests flush the database.** Each flush re-fires post_migrate:
   - contenttypes and permissions;
   - `db_guards` DROP/CREATE TRIGGER on 10 tables;
   - `tests/parallel.py:40` re-publishing every preset (about 0.4 s).

   They are concentrated in `test_bot.py`, `test_handlers.py`, `test_permissions.py`,
   `test_scrims.py` and `test_alerts.py`.
2. **State is built through the full service flow.** `popped`/`voting` appear in about 149 test
   signatures, `play_full_match` 28×, and `test_ledger`'s ladder plays 4 matches per test.
3. **`test_stateful.py` is the longest item.** It runs about 70 Hypothesis examples, each up to 56
   steps from 15 joins.
4. **About 40 subprocess interpreters** re-import settings: `test_platform_settings` (16),
   `test_web_asgi` (8), `test_platform_scripts` (7), `test_platform_app_role` (5) and
   `test_devtools_settings` (4).
5. **Infrastructure tests in the unit suite.** `test_platform_compose` parses compose and nginx,
   `test_platform_scripts` runs `.sh`/`.bat --help` and `docker info` at collection, and
   `test_devtools_panel_contract` runs a regex over TypeScript.
6. **No `--reuse-db`.** Every run creates and migrates one database per xdist worker.
7. **The ONNX OCR engine loads once per xdist worker.** It also reads images up to 3840 px and
   runs a CLI subprocess with 2 workers.

## Dependency map

```
F6  dead web-UI scaffolding ──unlocks──▶ F5 (one DB URL, no direct alias)
F5  DB topology             ──unlocks──▶ F3 (no pgbouncer or role tasks), F10 (no role/settings subprocess tests)
F4  observability           ──unlocks──▶ F3 (no observability role, exporters or monitor role)
F3  deploy                  ──unlocks──▶ F2 (nothing left for Molecule to verify), F15
F2  Molecule                ──unlocks──▶ F1
F1  CI                      ──with─────▶ F16 (Scorecard: publish action, release provenance, pins)
F13 image layers            ──unlocks──▶ F12 (make targets reuse one cached image), F10
F10 test speed              ◀──needs──── F11 (factories replace flow-built state)
F7  fat models              ──unlocks──▶ F8, F9 (callers use model methods), F11 (factories target models)
F14 dev tooling             ──decides──▶ F1 (whether e2e stays in CI at all)
```

## Refactoring risk

| Finding | Risk | Why |
|---|---|---|
| F7 | **High** | `lock_match` has 46 call sites and `mode_of` 30, and many files are CRLF. Methods are added first, then callers move module by module, with a full suite run per round |
| F5 | **High** | It changes settings, compose and the role bootstrap together, and `db_guards` triggers must keep working under a single owner role |
| F3, F4 | **Critical** (project structure) | They change how production runs. They need your approval and a VM deploy dry run |
| F10 | Medium | Tests are deleted or rewritten. Coverage of behaviour must not drop, so each deleted infra test needs a replacement or a stated reason |
| F12, F13 | Medium | Build config changes |
| F1, F2, F6, F9, F15 | Low | |

## What's working well (keep and extend)

- **Outbox plus lanes:** Discord calls only after commit, with retries per lane. This is the right
  shape.
- **Stateless `custom_id` handlers:** old buttons survive restarts.
- **Races end in the database:** row locks, `version` and `step_index`, and unique constraints.
- **Pure `league/domain`:** ratings, standing, engine tables and mode schema have no Django in them.
- **An append-only rating ledger** with a rebuildable projection and `check_ledger`.
- **I/O-free renderers** (`bot/renderers`).
- **The Discord simulator and devtools seed:** this is what makes a fixture-driven flow test
  possible without a real guild.
- **Pinned images and container hardening:** keep these, since they cost nothing at runtime.

## Decisions (user review, 2026-11-19)

- **Edge:** Caddy replaces nginx + certbot.
- **Health:** Docker healthchecks, `/healthz` and `/readyz`, the bot heartbeat, the Discord error
  channel, a host timer that posts to a Discord webhook, and an optional dead-man ping. The
  Prometheus stack and the app's `/metrics` go.
- **Dev tools:** the simulator, devtools, the control panel and e2e stay. e2e runs locally
  (`make e2e`), and in CI only as a manual run.
- **Database:** no pgbouncer, and one Postgres login.
- **Everything else:** the fix order as proposed, with Scorecard alignment (F16) folded into the CI
  work.
