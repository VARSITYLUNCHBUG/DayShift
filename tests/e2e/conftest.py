"""Fixtures for the browser suite.

One Chromium for the run (the chrome service's Playwright server, or a local one without
PW_WS_ENDPOINT), a fresh browser context and page per test (pytest-playwright), clients for the
control API and the simulator, and a reset of the whole stack before every test. When a test
fails, the control API's state and the simulator's log go next to its trace and screenshot.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from playwright.sync_api import Page, expect

from support.api import ControlApi, SimApi, text_of, wait_for
from support.pages import ControlPanel
from support.stack import CONTROL_API_URL, CONTROL_PANEL_URL, DISCORD_SIM_URL, PW_WS_ENDPOINT

# The panel polls every 1.5 to 3 s, and a phase played through the bot takes a few more.
expect.set_options(timeout=20_000)

FAILED = pytest.StashKey[bool]()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_makereport(item: pytest.Item, call: pytest.CallInfo[None]) -> Any:
    report = yield
    if report.failed:
        item.stash[FAILED] = True
    return report


@pytest.fixture(scope="session")
def connect_options() -> dict[str, str] | None:
    """Drive the chrome service's browser when there is one (pytest-playwright's hook)."""
    return {"endpoint": PW_WS_ENDPOINT} if PW_WS_ENDPOINT else None


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args: dict[str, Any]) -> dict[str, Any]:
    # Wide enough for the panel's desktop layout (its lg and 2xl breakpoints).
    return {
        **browser_context_args,
        "base_url": CONTROL_PANEL_URL,
        "viewport": {"width": 1600, "height": 1000},
    }


@pytest.fixture(scope="session")
def control() -> Iterator[ControlApi]:
    client = ControlApi(CONTROL_API_URL)
    yield client
    client.close()


@pytest.fixture(scope="session")
def sim() -> Iterator[SimApi]:
    client = SimApi(DISCORD_SIM_URL)
    yield client
    client.close()


@pytest.fixture(autouse=True)
def fresh_stack(control: ControlApi, sim: SimApi) -> None:
    """Reset the simulator and the league to the dev fixtures, and wait until the bot is back.

    The simulator drops the bot's gateway session on reset; the bot identifies again a few seconds
    later. A test starts once that new session is up and the queue panel is posted.
    """
    before = sim.last_seq()
    control.reset()
    wait_for(lambda: sim.reconnected_since(before), "the bot's new gateway session")
    queue = control.state()["community"]["channels"]["queue"]
    wait_for(
        lambda: any(text_of(m).startswith("## Queue: 0/") for m in sim.messages(queue, 5)),
        "the bot to post the empty queue panel",
    )


@pytest.fixture(autouse=True)
def stack_dump(
    request: pytest.FixtureRequest, output_path: str, control: ControlApi, sim: SimApi
) -> Iterator[None]:
    """On failure, keep what the APIs saw next to the trace: state.json and sim-log.json."""
    yield
    if not request.node.stash.get(FAILED, False):
        return
    folder = Path(output_path)
    folder.mkdir(parents=True, exist_ok=True)
    for name, read in (("state.json", control.state), ("sim-log.json", sim.log_tail)):
        try:
            data: Any = read()
        except Exception as exc:  # The stack may be what broke; keep what can be kept.
            data = {"error": repr(exc)}
        (folder / name).write_text(json.dumps(data, indent=2), encoding="utf-8")


@pytest.fixture
def panel(page: Page) -> ControlPanel:
    """The control panel, open on its first screen."""
    page.set_default_timeout(20_000)
    return ControlPanel(page).open()
