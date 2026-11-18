"""The preset scenarios load and run to the state their titles promise, step by step if asked."""

from __future__ import annotations

from collections.abc import Callable
from io import StringIO
from typing import Any

import pytest
from django.core.management import CommandError, call_command

from devtools import api, control, scenarios
from league.domain.engine import Status
from league.models import Match, PlayerSwap, SubRequest

pytestmark = pytest.mark.django_db


@pytest.fixture
def presets(db: None) -> None:
    call_command("load_presets", stdout=StringIO())


def latest() -> Match:
    match = Match.objects.order_by("-pk").first()
    assert match is not None
    return match


def full_match() -> None:
    match = latest()
    assert (match.status, match.winner) == (Status.COMPLETED, "A")


def ready_check_miss() -> None:
    match = latest()
    assert match.status == Status.PLAYER_DRAFT
    missed = match.participants.filter(removed_reason="missed_ready").count()
    spares = match.participants.filter(is_active=True, player__display_name__startswith="Spare")
    assert (missed, spares.count()) == (2, 2)


def sub_mid_draft() -> None:
    match = latest()
    assert match.status == Status.COINFLIP
    request = SubRequest.objects.get(match=match)
    assert request.status == "filled"
    assert request.filled_by is not None and request.filled_by.display_name.startswith("Sub")


def dispute_result() -> None:
    match = latest()
    assert (match.status, match.winner) == (Status.COMPLETED, "B")
    assert match.transitions.filter(to_status=Status.DISPUTED).exists()


def restart_after_unfilled_sub() -> None:
    match = latest()
    assert match.restarted_from is not None
    assert match.restarted_from.status == Status.VOIDED
    assert match.status == Status.PLAYER_DRAFT
    assert match.participants.filter(
        is_active=True, player__display_name__startswith="Late"
    ).exists()


def checkin_miss() -> None:
    match = latest()
    assert match.status == Status.COINFLIP
    [missed] = match.participants.filter(missed_checkin=True)
    assert not missed.is_captain and missed.team in {"A", "B"}
    assert match.participants.filter(is_captain=True, checked_in_at__isnull=False).count() == 2


def swap_players() -> None:
    match = latest()
    assert (match.status, match.winner) == (Status.COMPLETED, "A")
    swap = PlayerSwap.objects.get(match=match)
    assert swap.status == "accepted"
    give = match.participants.get(player=swap.give)
    take = match.participants.get(player=swap.take)
    assert (give.team, take.team) == ("B", "A")


def lobby_code_fallback() -> None:
    match = latest()
    assert (match.status, match.api_lobby_failed) == (Status.COMPLETED, True)
    assert (match.lobby_code, match.api_party_id) == (f"DEV{match.pk}", "")
    assert control.lobbies() == control.CREATE


CHECKS: dict[str, Callable[[], None]] = {
    "checkin_miss": checkin_miss,
    "swap_players": swap_players,
    "lobby_code_fallback": lobby_code_fallback,
    "full_match": full_match,
    "ready_check_miss": ready_check_miss,
    "sub_mid_draft": sub_mid_draft,
    "dispute_result": dispute_result,
    "restart_after_unfilled_sub": restart_after_unfilled_sub,
}


def test_every_preset_is_listed(db: None) -> None:
    status, body = api.call("GET", "scenarios")
    assert status == 200
    listed = {scenario["name"]: scenario for scenario in body["scenarios"]}
    assert set(listed) == set(CHECKS)
    assert all(scenario["description"] and scenario["steps"] for scenario in listed.values())


@pytest.mark.parametrize("name", sorted(CHECKS))
def test_each_preset_runs_to_its_end_state(presets: None, name: str) -> None:
    status, body = api.call("POST", "scenarios/run", {"name": name})
    assert status == 200
    assert body["ok"], body["ran"][-1]
    assert body["next"] == body["total"] == len(scenarios.load(name).steps)
    assert all(step["status"] == 200 for step in body["ran"])
    CHECKS[name]()


def test_a_scenario_can_be_stepped_through(presets: None) -> None:
    body = api.call("POST", "scenarios/run", {"name": "full_match", "count": 2})[1]
    assert [step["index"] for step in body["ran"]] == [0, 1]
    assert body["next"] == 2
    body = api.call("POST", "scenarios/run", {"name": "full_match", "from": 2, "count": 1})[1]
    assert [step["title"] for step in body["ran"]] == ["Everyone readies up"]
    assert latest().status == Status.CAPTAIN_PHASE


def test_steps_can_be_sent_inline_and_stop_at_the_first_error(presets: None) -> None:
    steps: list[dict[str, Any]] = [
        {"path": "reset"},
        {"path": "matches/latest/advance"},
        {"method": "GET", "path": "state"},
    ]
    status, body = api.call("POST", "scenarios/run", {"steps": steps})
    assert status == 200
    assert not body["ok"]
    assert body["next"] == 1
    assert body["ran"][-1]["status"] == 404
    assert len(body["ran"]) == 2


def test_bad_scenarios_are_refused(db: None) -> None:
    assert api.call("POST", "scenarios/run", {"name": "nope"})[0] == 404
    assert api.call("POST", "scenarios/run", {"name": "../secrets"})[0] == 404
    assert api.call("POST", "scenarios/run", {"steps": []})[0] == 400
    assert api.call("POST", "scenarios/run", {"steps": [{"method": "BREW", "path": "x"}]})[0] == 400
    assert api.call("POST", "scenarios/run", {"name": "full_match", "from": 99})[0] == 400


def test_the_dev_scenario_command(presets: None) -> None:
    out = StringIO()
    call_command("dev_scenario", "--list", stdout=out)
    assert "full_match:" in out.getvalue()
    out = StringIO()
    call_command("dev_scenario", "dispute_result", stdout=out)
    assert "Done: 6 of 6 steps." in out.getvalue()
    with pytest.raises(CommandError, match="No scenario"):
        call_command("dev_scenario", "nope", stdout=StringIO())
