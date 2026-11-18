"""Timers from the panel: pause, resume and fire one match's clock, and freeze every clock."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from playwright.sync_api import expect

from support.api import JSON, ControlApi, SimApi, text_of, wait_for
from support.boards import board
from support.pages import ControlPanel


def until_deadline(match: JSON) -> timedelta:
    return datetime.fromisoformat(match["deadline_at"]) - datetime.now(UTC)


def clock(seconds: int) -> str:
    return f"{seconds // 60}:{seconds % 60:02d}"


def test_pause_resume_and_fire_one_match(
    panel: ControlPanel, control: ControlApi, sim: SimApi
) -> None:
    matches = panel.matches()
    matches.fill_queue()
    match_id = wait_for(lambda: control.state()["matches"], "a lobby")[0]["id"]
    control.advance(match_id, "player_draft")
    card = matches.card(match_id)
    card.expect_status("player_draft")

    card.pause()
    frozen = control.match(match_id)
    assert frozen["frozen"]
    assert until_deadline(frozen) > timedelta(days=365), "a frozen deadline is pushed years out"
    left = frozen["seconds_left"]
    assert 0 < left <= 45
    expect(card.timer()).to_have_attribute("aria-label", f"time left {clock(left)}")

    card.resume()
    resumed = control.match(match_id)
    assert not resumed["frozen"]
    assert timedelta(0) < until_deadline(resumed) <= timedelta(seconds=left + 1)

    step = resumed["step_index"]
    card.fire()
    fired = control.wait_match(match_id, lambda m: m["step_index"] == step + 1, "the auto-pick")
    pick = max(fired["picks"], key=lambda p: p["step"])
    assert (pick["action"], pick["step"]) == ("player_pick", step)
    assert pick["source"] != "user"
    picked = next(p for p in fired["players"] if p["id"] == pick["player_id"])
    assert picked["team"] == pick["team"]

    def on_a_team() -> bool:
        # On the board's team list, and their pick button greyed out.
        shown = board(sim, fired["text_channel_id"], match_id)
        return (
            shown is not None
            and picked["name"] in text_of(shown)
            and any(
                c["disabled"] and (c["label"] or "").startswith(f"{picked['name']} (")
                for c in shown["components"]
            )
        )

    wait_for(on_a_team, f"the board to show {picked['name']} drafted")


def test_pause_and_resume_every_timer(panel: ControlPanel, control: ControlApi) -> None:
    first = control.lobby_match()
    matches = panel.matches()
    panel.pause_timers()
    expect(panel.page.get_by_text("timers paused", exact=True)).to_be_visible()
    expect(matches.card(first["id"]).root.get_by_text("frozen", exact=True)).to_be_visible()
    assert control.state()["timers"] == {"paused_all": True, "frozen_matches": [first["id"]]}

    # A lobby that pops while every timer is paused starts frozen.
    second = control.lobby_match()
    assert second["frozen"]
    expect(matches.card(second["id"]).root.get_by_text("frozen", exact=True)).to_be_visible()

    panel.resume_timers()
    expect(panel.page.get_by_text("timers paused", exact=True)).to_be_hidden()
    assert control.state()["timers"] == {"paused_all": False, "frozen_matches": []}
    for match in (first, second):
        assert timedelta(0) < until_deadline(control.match(match["id"])) <= timedelta(minutes=3)
