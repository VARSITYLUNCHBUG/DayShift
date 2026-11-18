"""The preset scenarios (devtools/scenarios/), each run from the Scenarios screen to its last
step, then checked for the end state it promises."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from support.api import JSON, ControlApi
from support.pages import ControlPanel


def players_named(match: JSON, prefix: str) -> list[JSON]:
    return [p for p in match["players"] if p["name"].startswith(prefix)]


def ready_check_miss(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "player_draft"
    missed = [p for p in match["players"] if p["removed_reason"] == "missed_ready"]
    assert len(missed) == 2
    assert not any(p["active"] for p in missed)
    assert [p["active"] for p in players_named(match, "Spare")] == [True, True]
    assert sum(p["active"] for p in match["players"]) == 12
    assert [s["status"] for s in match["sub_requests"]] == ["filled", "filled"]


def sub_mid_draft(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "coinflip"
    (left,) = [p for p in match["players"] if p["removed_reason"] == "subbed_out"]
    (sub,) = players_named(match, "Sub")
    assert sub["active"] and sub["team"] in {"A", "B"}
    assert not left["active"]
    (request,) = match["sub_requests"]
    assert (request["status"], request["leaving"]) == ("filled", left["id"])
    assert all(len(team) == 6 for team in match["teams"].values())


def dispute_result(match: JSON, control: ControlApi) -> None:
    # Team A's captain reported A; staff settled the dispute for B.
    assert (match["status"], match["winner"]) == ("completed", "B")
    recent = control.state()["recent"][0]
    assert (recent["id"], recent["winner"]) == (match["id"], "B")


def restart_after_unfilled_sub(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "player_draft"
    (late,) = players_named(match, "Late")
    assert late["active"]
    (request,) = match["sub_requests"]
    assert (request["reason"], request["status"]) == ("restart", "filled")
    # The restarted lobby is the same players, without the one who left, plus the late one.
    assert request["leaving"] not in {p["id"] for p in match["players"]}
    assert [p["active"] for p in match["players"]] == [True] * 12


def checkin_miss(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "coinflip"
    (missed,) = [p for p in match["players"] if p["missed_checkin"]]
    assert not missed["is_captain"]
    captains = [p for p in match["players"] if p["is_captain"]]
    assert len(captains) == 2 and all(p["checked_in"] for p in captains)


def swap_players(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "completed"
    (swap,) = match["swaps"]
    assert swap["status"] == "accepted"
    team_of = {p["id"]: p["team"] for p in match["players"]}
    # Team A's captain offered `give` from A for `take` from B: they changed sides.
    assert (team_of[swap["give"]], team_of[swap["take"]]) == ("B", "A")


def lobby_code_fallback(match: JSON, control: ControlApi) -> None:
    assert match["status"] == "completed"
    assert match["api_lobby"]["failed"]
    assert match["lobby_code"] == f"DEV{match['id']}"
    assert control.state()["lobbies"] == "create"


CHECKS: dict[str, Callable[[JSON, ControlApi], None]] = {
    check.__name__: check
    for check in (
        ready_check_miss,
        sub_mid_draft,
        dispute_result,
        restart_after_unfilled_sub,
        checkin_miss,
        swap_players,
        lobby_code_fallback,
    )
}


def test_every_scenario_is_covered(control: ControlApi) -> None:
    names = {s["name"] for s in control.call("GET", "scenarios")["scenarios"]}
    # full_match is test_full_match.py, played from the panel instead.
    assert names - {"full_match"} == set(CHECKS)


@pytest.mark.parametrize("name", CHECKS)
def test_scenario(name: str, panel: ControlPanel, control: ControlApi) -> None:
    panel.scenarios().run(name)
    CHECKS[name](control.match("latest"), control)
