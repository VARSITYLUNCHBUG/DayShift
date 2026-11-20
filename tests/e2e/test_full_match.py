"""A whole match driven from the panel, every phase played by the bot's own buttons.

Twelve rated players come from the Players screen and queue up there (pressing Join in the
simulator). Each phase is one press of Complete phase with "Discord clicks" chosen, so every
action is a fake user clicking in the simulator and the bot's handlers running. After every
phase the match channel must show the board for the new status, and at the end #results must
post the rating changes.
"""

from __future__ import annotations

from playwright.sync_api import expect

from support.api import JSON, ControlApi, SimApi, text_of, wait_for
from support.boards import rating_lines, result_post, wait_board
from support.pages import ControlPanel

FLOW = [
    "ready_check",
    "captain_phase",
    "captain_checkin",
    "player_draft",
    "coinflip",
    "team_confirm",
    "champion_draft",
    "lobby_code",
    "in_progress",
    "awaiting_confirmation",
    "completed",
]


def labels(message: JSON) -> set[str]:
    """The labels of the message's buttons and selects you can still press."""
    return {c["label"] for c in message["components"] if c["label"] and not c["disabled"]}


def check_board(match: JSON, board: JSON) -> None:
    """What the board must offer in each status, beyond its title."""
    status, text, buttons = match["status"], text_of(board), labels(board)
    captains = [p for p in match["players"] if p["is_captain"]]
    if status == "ready_check":
        assert "Ready" in buttons
    elif status == "captain_checkin":
        assert "I'm here" in buttons
        for captain in captains:
            assert f"<@{captain['discord_user_id']}>" in text
    elif status == "player_draft":
        # One button per player still to draft: "Name (rating)".
        undrafted = {p["name"] for p in match["players"] if not p["team"]}
        assert {label.rsplit(" (", 1)[0] for label in buttons if label.endswith(")")} == undrafted
    elif status == "coinflip":
        assert {"Hidden King", "Archmother"} <= buttons
    elif status == "team_confirm":
        assert {"Teams ready", "Swap players"} <= buttons
    elif status == "champion_draft":
        assert "**Bans**" in text
    elif status == "in_progress":
        assert f"Lobby code: `{match['lobby_code']}`" in text
        assert "Start match" in buttons
    elif status == "awaiting_confirmation":
        assert {"Confirm", "Dispute"} <= buttons


def test_full_match_through_discord(panel: ControlPanel, control: ControlApi, sim: SimApi) -> None:
    players = panel.players()
    players.add_players(12, 800, 1900, prefix="Rated")
    players.queue_matching("Rated", 12)
    match_id = wait_for(lambda: control.state()["matches"], "a lobby")[0]["id"]
    match = control.match(match_id)
    rating_before = {p["discord_user_id"]: p["rating"] for p in match["players"]}
    assert sorted(rating_before.values()) == list(range(800, 2000, 100))
    matches = panel.matches()

    matches.act_via("Act via Discord clicks")
    card = matches.card(match_id)
    status = match["status"]
    seen = [status]
    while status != "completed":
        match, board = wait_board(sim, control, match_id)
        status = match["status"]
        if status != seen[-1]:
            seen.append(status)
        if status == "lobby_code" and not match["api_lobby"]["failed"]:
            # deadlock-api makes the lobby and the bot moves the match on: nobody presses
            # anything, so there is no phase to complete here.
            control.wait_match(match_id, lambda m: m["status"] != "lobby_code", "the api lobby")
            continue
        check_board(match, board)
        card.expect_status(status)
        seq = sim.last_seq()
        card.complete_phase(status)
        assert "INTERACTION_CREATE" in sim.gateway_events(seq), "the phase went past the bot"
        status = control.match(match_id)["status"]
        assert FLOW.index(status) > FLOW.index(seen[-1]), f"{seen[-1]} went to {status}"
    seen.append(status)
    assert {"ready_check", "player_draft", "champion_draft", "in_progress"} <= set(seen)
    assert seen == sorted(seen, key=FLOW.index)

    finished = control.match(match_id)
    winners = {p["discord_user_id"] for p in finished["players"] if p["team"] == finished["winner"]}
    lines = rating_lines(
        result_post(sim, control.state()["community"]["channels"]["results"], match_id)
    )
    assert set(lines) == set(rating_before)
    rating_after = {p["discord_user_id"]: p["rating"] for p in control.players()}
    for user, (change, rating) in lines.items():
        assert rating == rating_before[user] + change
        assert rating_after[user] == rating
        assert (change > 0) == (user in winners), user
    recent = matches.recent()
    expect(recent).to_contain_text(f"#{match_id}")
    expect(recent).to_contain_text(f"team {finished['winner']} won")
