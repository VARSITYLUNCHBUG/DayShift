# The web UI's end-to-end tests

Playwright (`@playwright/test`) drives the built web UI in Chromium against a real stack: Django
under uvicorn, a throwaway Postgres and the dev fixtures. The browser plays one player, signed in
through the dev login. The dev control API (`/_control/api/`, [devtools/README.md](../../../devtools/README.md))
plays the other eleven, through the same `league.services` calls the Discord buttons make.

These tests run **on your machine only, never in CI**:

| When | What | Hook |
|---|---|---|
| `git commit` touching `services/web/`, `league/web/`, `league/services/` or `config/` | the `@smoke` tests (under a minute) | `web-e2e-smoke` |
| `git push`, same paths | the full suite: the `desktop` and `phone` projects | `web-e2e` |
| `git commit` touching `services/web/` | typecheck (app and e2e), lint and Vitest, no browser | `web-check` |

CI runs the unit checks in a job of its own and SKIPs `web-e2e-smoke` and `web-check` in its
pre-commit step; `scripts/web-e2e.sh` also exits at once when `CI` is set.

## Setup, once

```sh
make setup                                      # installs the pre-commit and pre-push hooks
cd services/web && npm ci && npx playwright install chromium
```

Docker must be running: each run starts its own Postgres container and removes it afterwards.

## Running

```sh
bash scripts/web-e2e.sh --smoke                 # what the commit hook runs
bash scripts/web-e2e.sh --full                  # what the push hook runs
bash scripts/web-e2e.sh --full -- -g "swap"     # anything after -- goes to playwright test
bash scripts/web-e2e.sh --smoke --headed        # watch it
bash scripts/web-e2e.sh --serve                 # just the stack, for writing tests (Ctrl-C stops it)
```

With `--serve` running, point Playwright at it yourself, for instance with the UI mode:

```sh
cd services/web && BASE_URL=http://127.0.0.1:<port> npx playwright test --project=desktop --ui
```

The script:

1. exits 0 when `CI` is set;
2. starts `postgres` (the image and digest `compose.yaml` pins) on a free port, on tmpfs with
   fsync off, and waits for `pg_isready`;
3. runs `migrate`, `load_presets` and `dev_seed` with `DEBUG`, `DEV_CONTROL` and `WEB_DEV_LOGIN`
   on and no simulator, so every control API action goes through the services and no bot runs:
   nothing times out unless a test fires a deadline;
4. runs `npm ci` if `node_modules` is missing or older than the lockfile, and `npm run build` if
   anything the build reads changed since the last one (`--no-build` skips it);
5. starts uvicorn on a free port and waits for `/readyz`;
6. runs `npx playwright test` with `BASE_URL` set, and tears everything down on exit.

To skip a hook once: `SKIP=web-e2e-smoke git commit …` or `SKIP=web-e2e git push`.

## Results

Everything goes to `services/web/test-results/` (gitignored):

- `artifacts/`: per failed test, a trace (`npx playwright show-trace <zip>`), a screenshot and
  the page's accessibility snapshot (`error-context.md`)
- `report/`: the HTML report (`npx playwright show-report test-results/report`)
- `server.log`, `setup.log` and `build.log`: the stack's own output

## Projects

| Project | Runs | Browser |
|---|---|---|
| `smoke` | tests tagged `@smoke` | desktop Chromium, 1440×900 |
| `desktop` | everything not tagged `@phone` | desktop Chromium, 1440×900 |
| `phone` | tests tagged `@phone` | Pixel-like, 390×844, touch |

## What's covered

| File | Covers |
|---|---|
| `smoke.e2e.ts` (`@smoke`) | The built app renders with no page errors. Sign-in and the dev login. Join and leave the queue, live. The 404. axe on sign-in and Play. |
| `match-captain.e2e.ts` | A whole ranked match as captain: the queue, Ready Up, the check-in, the player draft, the coinflip and a wish, the hero draft (Random, ban, lock in), the lobby code fallback, the report with a match ID, the confirm, the result. axe on each step. |
| `match-live.e2e.ts` | The other captain's pick shows without a reload. A dropped socket shows the banner and catches up. |
| `match-teams.e2e.ts` | Wishes and the team chat reach teammates and not the other team. The lobby chat reaches everyone. Each player has their own browser context. |
| `match-changes.e2e.ts` | A swap both ways. A sub through the queue. An early leave reported and agreed (void). |
| `pages.e2e.ts` | The postgame tabs (Summary, Timeline, Replay scrubbing, Advanced). Privacy (Me, the ladder, the API). The share card (toggles, PNG download). axe on the main pages. |
| `phone.e2e.ts` (`@phone`) | The sticky room action. The full-screen chat. No sideways scroll at 390 and 320 px. |
| `layout.e2e.ts` (`@phone`) | Every page, the finished match's record and postgame, and the room through each phase to the game, each loaded once and checked at 320, 390, 768 and 1280 px: no sideways scroll, nothing past the screen's edge (a scroller's content aside), and every control at least 24 px square (WCAG 2.5.8). Each page's screenshot is attached to the report. `LAYOUT_WIDTHS=320,360,414` checks other widths. |

Captains: new players can't be voted for (they need five matches), so `support/match.ts` gives the
browser player and one rival the top two ratings, and the captains are appointed by rating.

The postgame test reports a match with the Deadlock match ID of
`tests/fixtures/deadlock/match_140328807_metadata.json.gz` and builds its postgame from that file
with `manage.py build_postgames --match <id> --metadata-file <file>`, so nothing goes to
deadlock-api. That runs in the stack's environment, which `web-e2e.sh` exports. Against
`--serve`, export what it prints first.

Dropping the connection: Chromium's offline mode keeps an open websocket, so
`support/network.ts` routes `/ws/` through Playwright and closes it on demand.

## Writing tests

- Import `test` and `expect` from `./support/fixtures`, not from `@playwright/test`. Each test then:
  - starts from a reset league (`POST /_control/api/reset`): the dev fixtures, an empty queue, no
    matches;
  - fails if the page throws an uncaught error.
- The league is one per stack, so the suite runs one worker. Don't share players or matches
  between tests; make what the test needs.
- Fixtures and helpers:
  - `me`: a new player, signed in on `page`.
  - `control` (`support/control.ts`): the typed control API client. Make players, fill the queue,
    `advance` a match to a status, `act` as any player, `script` the autopilot, `fire` a deadline.
  - `signInAs(page, player)` and `openAs(browser, player, path)` (`support/auth.ts`): sign a
    context in through the dev login. Use `openAs` for a second player in their own context.
  - `expectNoA11yViolations(page)` (`support/axe.ts`): axe-core, WCAG 2.2 A and AA. Serious and
    critical violations fail the test, and the full results are attached to it.
- Find elements by role and accessible name (`getByRole("button", { name: "Join queue" })`), the
  way a screen reader would. Don't use CSS classes or test ids.
- Wait with web-first assertions (`await expect(locator).toBeVisible()`), and for server state
  with `expect.poll` or `control.waitForMatch`. Never use `waitForTimeout` or fixed sleeps.
- Tag a test `@smoke` only if it is quick and covers something every change could break. Tag
  `@phone` for the phone layout.
- Test files end in `.e2e.ts`, so Vitest doesn't pick them up.
