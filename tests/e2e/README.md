# Browser end-to-end tests

The whole stack, driven the way you drive it by hand: a clean headless Chromium opens the
control panel and plays matches through the real bot, which talks to the Discord simulator.
Each test then checks what the bot posted in the simulated guild and what the league stored.

| File | What it proves |
|---|---|
| `test_smoke.py` | The panel loads, web, the simulator and the bot are healthy, Reset puts the stack back |
| `test_full_match.py` | Twelve rated players made and queued on the Players screen, then every phase played with Complete phase through Discord clicks: the match channel shows the right board after each phase, and #results posts the rating changes |
| `test_scripted_draft.py` | Champion plans and a match script set in the panel: captains, draft order, champion picks and bans, coinflip side and winner all follow them |
| `test_scenarios.py` | Every preset in `devtools/scenarios/` run from the Scenarios screen, and its end state |
| `test_timers.py` | Pause, resume and fire one match's timer; pause every timer, including a lobby that pops while paused |
| `test_discord_view.py` | In the Discord view, a captain presses the bot's report button and submits its form with a real screenshot, which the bot archives |

## Running it

```
scripts/test.sh e2e                    # build, start the test stack, run, tear down
scripts/test.sh e2e -- -k timers       # arguments after -- go to pytest
scripts/test.sh e2e --no-build         # reuse the images already built
```

`scripts/test.sh e2e` starts the `draftbot-test` stack from `compose.test.yaml` (the app
behind pgbouncer, the bot and scheduler, the simulator, the control panel and a `chrome`
service running a Playwright server), runs this folder in the `e2e` container, and removes
everything afterwards, pass or fail. Nothing is published on the host.

Against your dev stack (`scripts/fixture_to_test.sh`) instead, with Python 3.12 or later:

```
pip install --require-hashes -r tests/e2e/requirements.txt
playwright install chromium
cd tests/e2e && pytest
```

The tests reset the stack before each test, so don't run them against data you want to keep.
`support/stack.py` has the URLs and the environment variables that move them.

## When a test fails

Its folder under `test-results/e2e/` (the repo root, mounted into the container) gets:

- `trace.zip`: open it with `playwright show-trace` or at <https://trace.playwright.dev>
- `test-failed-1.png` and `video.webm`: the page at the end, and the whole test
- `state.json` and `sim-log.json`: the control API's state and the simulator's last 500 log
  entries (every REST call the bot made, every gateway event)

`scripts/test.sh` also prints the last log lines of web, bot, scheduler and the simulator.

## How the tests are built

- One browser per run, a fresh browser context and page per test (pytest-playwright).
- A reset before every test: the simulator and the league go back to the dev fixtures, and the
  test waits until the bot has a new gateway session and has posted the queue panel.
- No sleeps. Pages wait with Playwright's `expect`; the APIs are polled with a bound
  (`support.api.wait_for`), on state such as a match's status or a board's title.
- Actions in the panel wait for their success toast and fail on their error toast
  (`support/pages.py`), so a failure says what the panel said.
- The tests run one at a time. They share one stack whose reset wipes everything, so they
  can't run in parallel against it. A full run takes about five minutes on top of building
  and starting the stack, most of it the bot playing matches.

`support/api.py` has the control API and simulator clients, `support/boards.py` reads the bot's
boards and result posts, and `support/pages.py` has a page object per screen of the panel.

## Dependencies

`requirements.in` lists them; `requirements.txt` is the lock, with hashes, that the
`Dockerfile` installs. `playwright` must match the Playwright image in the `Dockerfile`. To
update, change both, then:

```
cd tests/e2e
uv pip compile requirements.in --universal --python-version 3.12 --generate-hashes -o requirements.txt
```
