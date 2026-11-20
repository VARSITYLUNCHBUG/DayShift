"""Live notifications: what the web process hears, heard the way it hears it, over LISTEN."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
import pytest
from django.db import connection, transaction

from league.domain.engine import Status
from league.models import Community, Match, OutboxEffect, Player
from league.models.moderation import PenaltyKind
from league.services import (
    common,
    community,
    deadlines,
    live,
    lobby,
    ocr,
    penalties,
    prio,
    queue,
    results,
    standing,
    subs,
    swaps,
)
from tests.conftest import Clock, make_player
from tests.helpers import fresh, image, ready_all, to_champion_draft, to_in_progress, vote_only
from tests.web_helpers import read_scoreboard

pytestmark = pytest.mark.django_db(transaction=True)

END = "end-of-test-batch"


class Listener:
    """A second connection LISTENing on the live channel, like the web process's."""

    def __init__(self, conn: psycopg.Connection) -> None:
        self.conn = conn

    def heard(self) -> list[str]:
        """Everything delivered since the last call. Postgres delivers in commit order, so a
        marker sent now arrives after everything already committed: no sleeping."""
        self.conn.execute("SELECT pg_notify(%s, %s)", [live.CHANNEL, END])
        topics = []
        for notify in self.conn.notifies(timeout=10):
            if notify.payload == END:
                return topics
            topics.append(notify.payload)
        raise AssertionError("The end marker never arrived.")


@contextmanager
def listening() -> Iterator[Listener]:
    settings = connection.settings_dict
    params = {
        "host": settings["HOST"],
        "port": settings["PORT"],
        "dbname": settings["NAME"],
        "user": settings["USER"],
        "password": settings["PASSWORD"],
    }
    conn = psycopg.connect(autocommit=True, **{k: v for k, v in params.items() if v})
    try:
        conn.execute(f"LISTEN {live.CHANNEL}")
        yield Listener(conn)
    finally:
        conn.close()


@pytest.fixture
def listener() -> Iterator[Listener]:
    with listening() as heard:
        yield heard


# --- publish ---------------------------------------------------------------------------------


def test_a_topic_arrives_once_its_transaction_commits(listener: Listener) -> None:
    with transaction.atomic():
        live.publish("match:1")
        assert listener.heard() == []
    assert listener.heard() == ["match:1"]


def test_a_rolled_back_change_sends_nothing(listener: Listener) -> None:
    with pytest.raises(RuntimeError), transaction.atomic():
        live.publish("match:1")
        raise RuntimeError
    assert listener.heard() == []


def test_a_topic_published_twice_in_one_transaction_arrives_once(listener: Listener) -> None:
    with transaction.atomic():
        live.publish("match:1", "queue:2", "match:1")
        live.publish("queue:2")
    assert listener.heard() == ["match:1", "queue:2"]


def test_publishing_nothing_sends_nothing(listener: Listener) -> None:
    live.publish()
    assert listener.heard() == []


# --- Matches and the queue ---------------------------------------------------------------------


def test_a_lobby_popping_notifies_its_match_and_the_queue(
    league: Community, players: list[Player], listener: Listener
) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = Match.objects.get()
    heard = listener.heard()
    assert live.match_topic(match.pk) in heard
    assert live.queue_topic(league.pk) in heard


def test_readying_up_notifies_the_match(popped: Match, listener: Listener) -> None:
    listener.heard()
    player = popped.participants.select_related("player").first().player
    lobby.mark_ready(popped.pk, player)
    assert listener.heard() == [live.match_topic(popped.pk)]


def test_a_render_that_coalesces_still_notifies(popped: Match, listener: Listener) -> None:
    listener.heard()
    OutboxEffect.objects.filter(kind="render_board").delete()
    for _ in range(2):
        with transaction.atomic():
            common.render_board(fresh(popped))
    assert OutboxEffect.objects.filter(kind="render_board", match=popped).count() == 1
    assert listener.heard() == [live.match_topic(popped.pk)] * 2


def test_a_queue_render_notifies_the_queue(league: Community, listener: Listener) -> None:
    common.render_queue(league)
    assert listener.heard() == [live.queue_topic(league.pk)]


def test_every_bump_and_transition_notifies_without_a_render(
    popped: Match, listener: Listener
) -> None:
    """Changes made straight on the model still reach the web."""
    listener.heard()
    with transaction.atomic():
        match = Match.objects.lock(popped.pk)
        match.bump()
    assert listener.heard() == [live.match_topic(popped.pk)]
    with transaction.atomic():
        match = Match.objects.lock(popped.pk)
        common.transition(match, Status.VOIDED, source="staff")
        match.save_transition()
    assert listener.heard() == [live.match_topic(popped.pk)]


def test_a_timeout_in_the_bot_process_notifies(
    popped: Match, clock: Clock, listener: Listener
) -> None:
    """The ready check runs out with nobody ready: the poller voids it."""
    listener.heard()
    clock.advance(popped.mode.ready_check.seconds + 1)
    deadlines.tick()
    clock.advance(popped.mode.ready_check.refill_seconds + 1)
    deadlines.tick()
    assert fresh(popped).status == Status.VOIDED
    assert live.match_topic(popped.pk) in listener.heard()


def test_extending_deadlines_after_downtime_notifies_each_match(
    popped: Match, clock: Clock, listener: Listener
) -> None:
    clock.advance(popped.mode.ready_check.seconds + 5)
    listener.heard()
    assert deadlines.extend_past_due() >= 1
    assert listener.heard() == [live.match_topic(popped.pk)]


def test_the_captain_check_in_notifies(popped: Match, listener: Listener) -> None:
    match = vote_only(ready_all(popped))
    assert match.status == Status.CAPTAIN_CHECKIN
    listener.heard()
    lobby.check_in(match.pk, match.captain_of("A").player)
    assert listener.heard() == [live.match_topic(match.pk)]


def test_swaps_notify(popped: Match, listener: Listener) -> None:
    match = to_champion_draft(popped)
    captain = match.captain_of("A").player
    give = match.participants.filter(team="A", is_captain=False).first()
    take = match.participants.filter(team="B", is_captain=False).first()
    assert give is not None and take is not None
    listener.heard()
    swap = swaps.propose(match.pk, captain, give.player_id, take.player_id)
    assert listener.heard() == [live.match_topic(match.pk)]
    swaps.answer(match.pk, match.captain_of("B").player, swap.pk, accept=True)
    assert listener.heard() == [live.match_topic(match.pk)]


def test_a_reported_result_notifies_the_match_and_each_player(
    popped: Match, listener: Listener
) -> None:
    """The first report ends the game: everyone leaves the match, and their page shows it."""
    match = to_in_progress(popped)
    roster = set(match.participants.filter(is_active=True).values_list("player_id", flat=True))
    listener.heard()
    results.submit_report(match.pk, match.captain_of("A").player, "A", image())
    heard = listener.heard()
    assert live.match_topic(match.pk) in heard
    assert {live.player_topic(pk) for pk in roster} <= set(heard)


def test_a_dispute_left_unanswered_notifies(
    popped: Match, clock: Clock, listener: Listener
) -> None:
    match = to_in_progress(popped)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image())
    results.dispute(match.pk, match.captain_of("B").player, "No.")
    listener.heard()
    results.on_disputed_timeout(fresh(match))
    assert listener.heard() == [live.match_topic(match.pk)]


def test_a_scoreboard_read_and_each_matched_name_notify_the_match(
    popped: Match, listener: Listener
) -> None:
    """Neither bumps the match's version, but the captains' page shows the names to match."""
    match = to_in_progress(popped)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image())
    listener.heard()
    read = read_scoreboard(match, strangers=1)
    assert listener.heard() == [live.match_topic(match.pk)]
    row = ocr.unmapped_rows(read.pk)[0]
    ocr.map_row(read.pk, row.row, row.options[0][0], match.captain_of("A").player, is_staff=False)
    assert listener.heard() == [live.match_topic(match.pk)]


# --- The priority list -------------------------------------------------------------------------


def test_priority_list_changes_notify_the_queue(league: Community, listener: Listener) -> None:
    player = make_player(50)
    topic = live.queue_topic(league.pk)

    with transaction.atomic():
        prio.joined_queue(league.pk, player)
    assert listener.heard() == [topic]

    with transaction.atomic():
        prio.left_queue(league.pk, [player.discord_user_id])
    assert listener.heard() == [topic]

    with transaction.atomic():
        prio.requeued(league.pk, [(player, common.now())])
    assert listener.heard() == [topic]

    with transaction.atomic():
        prio.drop_players(league.pk, [player.discord_user_id])
    assert listener.heard() == [topic]

    with transaction.atomic():
        prio.joined_queue(league.pk, player)
        prio.drop_all(league.pk)
    assert listener.heard() == [topic]


def test_removing_someone_not_on_the_list_sends_nothing(
    league: Community, listener: Listener
) -> None:
    player = make_player(50)
    with transaction.atomic():
        prio.joined_queue(league.pk, player)
    listener.heard()
    assert prio.remove(league.pk, player.discord_user_id)
    assert listener.heard() == [live.queue_topic(league.pk)]
    assert not prio.remove(league.pk, player.discord_user_id)
    assert listener.heard() == []


def test_a_hold_running_out_notifies_only_that_servers_queue(
    league: Community, clock: Clock, listener: Listener
) -> None:
    other = community.ensure(guild_id=998, name="Other")
    with transaction.atomic():
        prio.joined_queue(league.pk, make_player(50))
        prio.joined_queue(other.pk, make_player(51))
        prio.left_queue(league.pk, [make_player(50).discord_user_id])
    listener.heard()

    assert prio.tick(clock.now()) == 0
    assert listener.heard() == []

    clock.advance(prio.GRACE_SECONDS + 1)
    assert prio.tick(clock.now()) == 1
    assert listener.heard() == [live.queue_topic(league.pk)]


# --- One player's own state --------------------------------------------------------------------


def sub_offer(match: Match, leaver: Player, sub: Player) -> int:
    request = subs.request_sub_out(match.pk, leaver, leaver.pk)
    return subs.invite_sub(request.pk, leaver, sub.discord_user_id, sub.display_name).pk


def non_captain(match: Match) -> Player:
    return (
        match.participants.filter(is_active=True, is_captain=False)
        .select_related("player")
        .first()
        .player
    )


def test_an_offer_and_its_answer_notify_the_player_asked(popped: Match, listener: Listener) -> None:
    sub = make_player(77)
    listener.heard()
    offer_id = sub_offer(popped, non_captain(popped), sub)
    assert live.player_topic(sub.pk) in listener.heard()

    subs.answer_offer(offer_id, sub, False)
    assert live.player_topic(sub.pk) in listener.heard()


def test_a_result_withdrawing_an_offer_notifies_the_player_asked(
    popped: Match, listener: Listener
) -> None:
    match = to_in_progress(popped)
    sub = make_player(77)
    sub_offer(match, non_captain(match), sub)
    listener.heard()

    results.submit_report(match.pk, match.captain_of("A").player, "A", image())
    assert live.player_topic(sub.pk) in listener.heard()


def test_extending_offer_deadlines_notifies_the_player_asked(
    popped: Match, clock: Clock, listener: Listener
) -> None:
    sub = make_player(77)
    sub_offer(popped, non_captain(popped), sub)
    clock.advance(3600)  # Past the offer's deadline and the request's.
    listener.heard()
    subs.extend_past_due(clock.now())
    heard = listener.heard()
    assert live.player_topic(sub.pk) in heard
    assert live.match_topic(popped.pk) in heard


def test_cooldowns_notify_the_player(league: Community, listener: Listener) -> None:
    player = make_player(50)
    penalties.issue(league, player, PenaltyKind.DODGE)
    assert listener.heard() == [live.player_topic(player.pk)]

    assert penalties.revoke_active(league, player) == 1
    assert listener.heard() == [live.player_topic(player.pk)]

    assert penalties.revoke_active(league, player) == 0
    assert listener.heard() == []


def test_a_strike_change_notifies_the_player(league: Community, listener: Listener) -> None:
    player = make_player(50)
    standing.adjust_strikes(league, player, 1, None, "Test")
    assert listener.heard() == [live.player_topic(player.pk)]
