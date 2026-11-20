"""Freezing, resuming and firing match timers without the league's own sub hold."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone

from devtools import api, timers
from devtools.models import FrozenTimer
from league.domain.engine import Status
from league.models import Community, Match, Penalty, Player, SubRequest
from league.services import deadlines, queue

pytestmark = pytest.mark.django_db


def ok(method: str, path: str, body: Any = None) -> dict[str, Any]:
    status, response = api.call(method, path, body)
    assert status == 200, response
    return response


def fresh(match: Match) -> Match:
    return Match.objects.get(pk=match.pk)


def seconds_left(match: Match) -> float:
    deadline = fresh(match).deadline_at
    assert deadline is not None
    return (deadline - timezone.now()).total_seconds()


def far_off(match: Match) -> bool:
    deadline = fresh(match).deadline_at
    return deadline is not None and deadline > timezone.now() + timedelta(days=365)


def test_pause_parks_the_deadline_and_keeps_every_action_working(popped: Match) -> None:
    body = ok("POST", f"matches/{popped.pk}/pause")
    assert body["frozen"]
    assert 170 <= body["seconds_left"] <= 180
    assert far_off(popped)
    assert fresh(popped).held_seconds is None  # The league's sub hold is never used.
    # Nothing fires, however long the bot's loop runs.
    assert not deadlines.fire_match_deadline(popped.pk)
    assert deadlines.extend_past_due() == 0
    # Players can still act: the ready check finishes and the captain vote starts, frozen too.
    body = ok("POST", "matches/latest/advance", {"via": "service"})
    assert body["to"] == "captain_phase"
    assert body["match"]["frozen"]
    assert 40 <= body["match"]["seconds_left"] <= 45
    assert far_off(popped)


def test_resume_restores_the_time_that_was_left(popped: Match) -> None:
    Match.objects.filter(pk=popped.pk).update(deadline_at=timezone.now() + timedelta(seconds=90))
    ok("POST", f"matches/{popped.pk}/pause")
    body = ok("POST", f"matches/{popped.pk}/resume")
    assert not body["frozen"]
    left = seconds_left(popped)
    assert 85 <= left <= 90
    assert not FrozenTimer.objects.exists()


def test_fire_runs_out_the_ready_check(popped: Match) -> None:
    everyone = list(popped.participants.order_by("pk"))
    for participant in everyone[:10]:
        ok("POST", "matches/latest/act", {"action": "ready", "player_id": participant.player_id})
    body = ok("POST", f"matches/{popped.pk}/fire")
    assert body["fired"]
    match = body["match"]
    assert match["on_hold"]
    gone = {p["id"] for p in match["players"] if p["removed_reason"] == "missed_ready"}
    assert gone == {everyone[10].player_id, everyone[11].player_id}
    assert Penalty.objects.filter(player_id__in=gone).count() == 2


def test_fire_on_a_frozen_draft_auto_picks_one_step_and_stays_frozen(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "player_draft", "via": "service"})
    ok("POST", f"matches/{popped.pk}/pause")
    body = ok("POST", f"matches/{popped.pk}/fire")
    assert body["fired"]
    match = body["match"]
    assert match["step_index"] == 1
    assert match["picks"][0]["source"] == "timeout"
    assert match["frozen"]
    # The next step's full time, waiting: the other captain's first pick, which has double.
    assert match["seconds_left"] == 90
    assert far_off(popped)
    ok("POST", f"matches/{popped.pk}/resume")
    left = seconds_left(popped)
    assert 85 <= left <= 90


def test_fire_on_a_match_on_hold_runs_the_sub_timer(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "player_draft", "via": "service"})
    ok("POST", "matches/latest/act", {"action": "request_sub", "player_id": "non_captain:1"})
    ok("POST", "matches/latest/act", {"action": "offer_queue", "player_id": "requester"})
    ok("POST", f"matches/{popped.pk}/pause")
    body = ok("POST", f"matches/{popped.pk}/fire")
    assert body["fired"]
    # Nobody took the seat: the lobby restarts as a new match, which takes over the players.
    assert fresh(popped).status == Status.VOIDED
    assert SubRequest.objects.get(match=popped).status == "expired"
    assert Match.objects.get(restarted_from=popped).status == Status.READY_CHECK


def test_a_sub_hold_that_starts_while_frozen_keeps_the_real_time(popped: Match) -> None:
    ok("POST", "matches/latest/advance", {"until": "player_draft", "via": "service"})
    Match.objects.filter(pk=popped.pk).update(deadline_at=timezone.now() + timedelta(seconds=30))
    ok("POST", f"matches/{popped.pk}/pause")
    ok("POST", "matches/latest/act", {"action": "request_sub", "player_id": "non_captain:1"})
    held = fresh(popped).held_seconds
    assert held is not None and 25 <= held <= 30
    body = ok("POST", "matches/latest/act", {"action": "cancel_sub", "player_id": "requester"})
    assert not body["match"]["on_hold"]
    assert body["match"]["frozen"]
    ok("POST", f"matches/{popped.pk}/resume")
    left = seconds_left(popped)
    assert 10 <= left <= 30


def test_pausing_every_timer_covers_matches_that_start_later(
    league: Community, popped: Match, players: list[Player]
) -> None:
    body = ok("POST", "timers/pause")
    assert body == {"paused_all": True, "frozen_matches": [popped.pk]}
    status, _ = api.call("POST", f"matches/{popped.pk}/resume")
    assert status == 409
    created = ok("POST", "players", {"count": 12})["players"]
    for player in created:
        queue.join(league.pk, Player.objects.get(pk=player["id"]))
    second = Match.objects.exclude(pk=popped.pk).get()
    state = ok("GET", "state")  # Any request sweeps.
    assert state["timers"]["frozen_matches"] == [popped.pk, second.pk]
    assert far_off(second)
    body = ok("POST", "timers/resume")
    assert body == {"paused_all": False, "frozen_matches": []}
    assert not far_off(second) and not far_off(popped)


def test_a_finished_match_drops_its_freeze(popped: Match) -> None:
    ok("POST", f"matches/{popped.pk}/pause")
    ok("POST", "matches/latest/act", {"action": "void"})
    assert ok("GET", "state")["timers"]["frozen_matches"] == []
    status, _ = api.call("POST", f"matches/{popped.pk}/pause")
    assert status == 409
    status, _ = api.call("POST", f"matches/{popped.pk}/fire")
    assert status == 409


def test_freezing_twice_keeps_the_first_time_left(popped: Match) -> None:
    timers.freeze(popped.pk)
    first = timers.frozen_seconds_left(popped.pk)
    timers.freeze(popped.pk)
    timers.sweep()
    assert timers.frozen_seconds_left(popped.pk) == first
