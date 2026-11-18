"""The panel loads, every service it watches is healthy, and Reset puts the stack back."""

from __future__ import annotations

import re

import httpx
from playwright.sync_api import expect

from support.api import ControlApi
from support.pages import ControlPanel
from support.stack import WEB_URL


def test_panel_loads_with_every_service_healthy(panel: ControlPanel) -> None:
    panel.expect_healthy()
    expect(
        panel.page.get_by_text(re.compile(r"^Dev League · season 1 · draft_3ban"))
    ).to_be_visible()
    for probe in ("healthz", "readyz"):
        assert httpx.get(f"{WEB_URL}/{probe}").status_code == 200, probe


def test_reset_from_the_header(panel: ControlPanel, control: ControlApi) -> None:
    control.create_players(12, join_queue=True, name_prefix="Gone")
    players = panel.players()
    expect(players.page.get_by_text("Players (26)", exact=True)).to_be_visible()

    panel.reset()

    expect(players.page.get_by_text("Players (14)", exact=True)).to_be_visible()
    expect(players.page.get_by_role("cell", name=re.compile(r"^Gone"))).to_have_count(0)
    state = control.state()
    assert (state["queue"], state["matches"], state["recent"]) == ([], [], [])
    assert [p["name"] for p in control.players()][:2] == ["Ash", "Bex"]
    matches = panel.matches()
    expect(matches.page.get_by_text("No live matches. Fill the queue to pop one.")).to_be_visible()
