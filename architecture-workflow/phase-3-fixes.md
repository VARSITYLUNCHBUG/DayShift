# Phase 3: Fix log

Every fix traces to a finding in [phase-2-diagnosis.md](phase-2-diagnosis.md). The baseline was
`origin/main` at `edfbbb7`: 875 passed and 4 skipped in **442 s** of pytest (476 s end to end),
on this PC (12 cores, Windows, Docker Desktop, `scripts/test.sh --local`).

Gates after each fix:
- ruff check and format;
- mypy on `bot league config devtools`;
- `makemigrations --check`;
- the full unit suite;
- for the platform changes, real image builds and a live stack.

Fixes that touch the same files went into the same commit, which says which findings it covers.

## F4, F5, F6 and the edge half of F3: the runtime

- **Risk:** Critical (project structure), approved in the Phase 2 review.
- **Commit:** "Shrink the runtime to Caddy, web, one bot process and Postgres".
- **What changed:**
  - **F4:** Removed Prometheus, Alertmanager, Grafana, the five exporters, the 22 alert rules, the
    five dashboards, `bot/metrics.py` and `league/observability/`. They're replaced by a
    watchdog in the bot: `bot.client.Watchdog`, with its checks in `league/services/health.py`
    and the queries as `Match.objects.overdue()` and `OutboxEffect.objects.due()`. Every minute it
    checks for timers more than a minute late and for Discord work waiting more than 5 minutes. It
    logs a change once, which the error log posts to the operator's channel, and pings an optional
    `HEALTHCHECK_PING_URL`.
  - **F4:** The scheduler container is gone. `runbot` runs the deadline loop in the bot and has no
    roles.
  - **F5:** pgbouncer, the `direct` alias and `config/db_router.py` are gone, along with the
    `DB_POOL`/`DB_PGBOUNCER` modes, the `draftbot_app` and `draftbot_monitor` logins, and
    `config/app_role.py` and `monitoring_role.py`. There is now one `DATABASE_URL` and one login.
  - **F6:** The player-web-UI settings and Channels are gone, and with them 21 locked packages.
    `frontend/` is out of `.dockerignore`.
  - **F3 (edge):** Caddy replaces nginx and certbot. `EDGE_SITE` set to a domain turns on
    automatic HTTPS, and `EDGE_ADMIN_CIDRS` fences off `/admin/`. web serves its own static
    files through WhiteNoise, so the shared static volume is gone.
  - **F13 (part):** The Dockerfile's `test` target replaces `scripts/docker/tests.Dockerfile`.
- **Tests:**
  - **Added:**
    - `test_health_reports_late_timers_and_a_backlog`;
    - `test_the_watchdog_logs_changes_and_pings`;
    - `test_the_bot_runs_every_loop`;
    - `tests/test_settings.py`: 12 in-process settings tests, replacing 28 that each started a
      fresh interpreter.
  - **Rewritten:** the web probes, on Django's `AsyncClient`.
  - **Removed:**
    - the metrics suites;
    - the app-role and monitoring-role suites;
    - `test_platform_compose` and `test_platform_scripts`, which tested compose and shell files.
      Their job is now the `compose` pre-commit hook.
- **Verified:**
  - 767 passed in 260 s (from 442 s).
  - The runtime image built in 29 s and the test image in 28 s. After a code change the test
    image rebuilt in 4 s: only `COPY . .` reran.
  - The quickstart stack came up healthy (edge, web, migrate, db). `/readyz` and the admin login
    returned 200 through Caddy. Hashed CSS was served gzipped with
    `Cache-Control: max-age=315360000, public, immutable`.
  - `EDGE_ADMIN_CIDRS=10.99.0.0/16` turned the admin into a 403 while `/readyz` stayed 200.

## F12, F13: the Makefile and the Windows VM

- **Risk:** Medium (build config).
- **Commit:** "Drive every dev, test and deploy task from one Makefile".
- **What changed:**
  - 1,100 lines of `.sh`/`.bat` triplets became one Makefile with these targets: `setup`, `dev`,
    `dev-logs`, `dev-stop`, `dev-reset`, `superuser`, `shell`, `check`, `test`, `test-fresh`,
    `e2e`, `ci`, `compose-check`, `sim-test`, `panel-test`, `clean`, `deploy-tools`, `site`,
    `deploy` and `backup`.
  - `scripts/dev-vm.ps1` makes a Multipass Ubuntu VM with Docker, make and uv. It gets half the
    PC's CPUs and memory and a 60 GB disk, mounts the checkout, and runs make there with
    `DEV_BIND=0.0.0.0`, so the browser on Windows reaches the dev stack.
  - `pre-commit` joins the locked dev tools.
- **Verified:**
  - `make help` and `make compose-check` ran in a Linux container against Docker; every compose
    combination is valid.
  - The `make test` path (the test image plus a Postgres kept up for `--reuse-db`) ran
    **121–129 s** warm. The first runs had 13 errors from the panel contract test, whose two
    TypeScript files weren't in the build context; `.dockerignore` now lets them in.
  - **Not verified here:** `scripts/dev-vm.ps1` itself. Multipass's service is stopped on this PC
    and needs an elevated shell to start.

## F3, F2: Ansible and Molecule

- **Risk:** Critical (deploy), approved in review.
- **Commit:** "Deploy with two Ansible roles that pull the image and template .env".
- **What changed:**
  - Six roles became two:
    - `host`: the deploy user, SSH hardening, ufw, unattended upgrades and Docker. It keeps the
      docker.io replacement fix from `6607c56`.
    - `app`: copies the compose files and the Caddyfile, templates `.env`, pulls the image,
      brings the stack up `--wait`, checks `https://<domain>/readyz`, and installs the backup,
      health and notify scripts with their timers.
  - The playbooks are `site`, `deploy`, `backup` and `restore`. `rotate-secrets` became "edit the
    vault, run site".
  - Molecule is removed: 1,634 lines, 20 min in CI and 46 min locally.
- **Verified:** ansible-lint's production profile passed (0 failures, 0 warnings, 26 files), and
  the syntax check passed for all four playbooks, on Linux (ansible-core 2.22.0, ansible-lint
  26.11.0).
- **Not verified here:** a real run against a server. The bebot-sim Multipass VM is the natural
  target once the Multipass service is running.

## F10, F11: test speed, factories and the fixture rule

- **Risk:** Medium (tests rewritten, behaviour kept).
- **What changed:**
  - **Factories:** `tests/factories.py` adds `in_progress()` and `played()`. Twelve real joins pop
    the lobby. The ready check, vote, drafts and coinflip are then written as they'd end, and the
    game starts through the app's own `draft._start_game`, so reporting, confirming, ratings and
    corrections run the real code.
  - **Where the factories are used:** the multi-match rating tests in `test_ledger`, `test_rules`,
    `test_ratings_flow`, `test_standing`, `test_cutover` and `test_openskill`. Tests about the
    draft itself, such as the DraftAction history test, keep the real flow.
  - **Hypothesis profiles:** `dev`, the default with 20 examples, and `ci` with 100; the
    stateful machine runs 20 or 60 examples. The "every status reached" guard runs on the
    thorough profile, because a dispute takes a long path that 20 examples don't promise.
  - **The fixture rule:** every model must have rows in `fixtures/dev` or an `EXEMPT` entry with a
    reason. `manage.py check_fixtures` enforces it, with `tests/test_fixtures.py` and a pre-commit
    hook behind it. `fixtures/dev/50_pings.json` adds the first new fixture (a staff ping).
- **Tests:**
  - **Added:** 3 in `tests/test_fixtures.py`: the rule holds, a new model without fixtures is
    refused, and the fixtures name real models.
  - **Made faster:** the rating and ledger tests now finish in **53 s**, down from about 240 s.
- **Verified:** full suite 767 passed in **199 s** with uv on Windows, and 121 s on the `make test`
  path.

## F7, F8, F9: fat models, thin bot and admin

- **Risk:** High (406 call sites in about 40 files, several CRLF).
- **What changed:**
  - **F7, model methods:**
    - `Match.objects.lock()`, `.timed()` and `.overdue()`;
    - `match.mode`, `.on_hold`, `.require_not_on_hold()`, `.record_transition()`,
      `.save_transition()`, `.bump()`, `.captain_of()` and `.require_participant()`;
    - `match.participants.active()` and `.roster()`;
    - `Season.objects.open_for()`, `season.rating_of()` and `season.strength_of()`;
    - `Player.objects.from_discord()`.
  - **F7, the services:** `services/common.py` keeps only what spans models: the clock, outbox
    writes, `transition()` (the model's record plus clearing notices), and `close_subs`. A
    scripted migration moved 406 call sites, checking for balanced parentheses.
  - **F7, literals:** strings such as `"completed"`, `"voided"`, `"ranked"` and `"scrim"` became
    the enums.
  - **F8:** The `/deadlock check` write transaction moved from `bot/commands/staff.py` into
    `api_results.correct_deadlock_match_id`. The staff roster lookup and devtools' active
    participants use the model querysets.
  - **F9:** The admin's season start and `manage.py start_season` both go through
    `community.start_next_season`: lock, start, and redraw the queue and leaderboard.
    `modes.activate` redraws the queue itself, so the admin's `save_model` does nothing extra.
- **Verified:**
  - After F7: 770 passed in 197 s.
  - After F8 and F9: see the integration gate below.
  - mypy is clean on 169 files, and ruff is clean.
  - Line endings match the index for every file. One file had flipped and was repaired.

## F1, F16 and F15: CI, Scorecard and docs

- **Risk:** Low.
- **What changed:**
  - **F1, `ci.yml`:**
    - `Checks` runs `uv run pre-commit run --all-files`, with pre-commit's cache kept between
      runs.
    - `Unit tests` runs pytest on the runner against a Postgres service container, with
      `HYPOTHESIS_PROFILE=ci`.
    - `CI OK` sums up the two.
    - On a push to main or a tag, `Image` builds once, scans with Trivy, pushes with
      `docker/build-push-action` (with SBOM and provenance), and attests the build provenance. A
      `v*` tag also gets a GitHub release carrying the signed provenance bundle
      (`*.sigstore.json`).
  - **F1, removed:** `deploy-lint.yml`, `publish.yml`, the skopeo step, the four-image matrix,
    the compose, simulator and panel jobs, and the path filter. `e2e.yml` is manual only.
  - **F1, pre-commit:** gained mypy, strict mypy on `tests/e2e`, mypy on the simulator, the
    migration check, the fixture rule, the compose check and ansible-lint.
  - **F16, Scorecard:**
    - CI-Tests is covered by the "Unit tests" check name.
    - Packaging is covered by `docker/build-push-action` with `push: true`.
    - Signed-Releases: the `*.sigstore.json` asset on each release.
    - Token-Permissions: `contents: read` at the top, and write per job.
    - Pinned-Dependencies: actions by SHA, images by digest (Caddy included), and no unhashed
      `pip install` left in any workflow.
    - SAST (CodeQL default setup), Dependabot (trimmed to what remains), the SBOM, `SECURITY.md`
      and the license are unchanged.
  - **F15:** `docs/ops/` (8 runbooks) is folded into a shorter `deploy/README.md`. The developer
    guide is rewritten around the Makefile, `docs/architecture.md` describes the stack as it is
    now, and the README, CONTRIBUTING, SECURITY, the e2e, devtools and panel READMEs, and the
    issue templates point at the new paths.
- **Verified:**
  - `pre-commit run --all-files` on Windows: every hook passed except two that fail only on
    native Windows. Both pass on Linux:
    - ansible-lint (no `os.register_at_fork` on Windows), which passed in a Linux container;
    - strict mypy on `tests/e2e`, hit by a Windows file lock in uv's cache, which passed in a
      Linux container ("no issues found in 12 source files").
  - **Not verified here:** GitHub Actions itself. The workflows passed actionlint, but have not
    run on GitHub.

## Phase 3 integration gate

- The final tree is identical to the pre-split snapshot (`backup/architecture-cleanup-snapshot`,
  local only) apart from this log.
- Unit suite: 770 passed, 3 skipped (the OCR group isn't installed).
- Browser suite, on the final stack (web, the bot, Postgres, the simulator, the control panel and
  Playwright, with no pgbouncer or scheduler): **15 passed in 250 s**. The stack was healthy in
  75 s, and the whole run took 329 s, against 6–7 min before.
- Diff from `origin/main`: 301 files, +3,351 / −18,597.
