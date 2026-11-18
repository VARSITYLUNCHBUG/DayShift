"""Scrims (/startdraft, /captains_coinflip): matches of their own kind, through the same engine.
Service rules first, then the guards that keep scrims out of ranked, then the outbox."""

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any

import pytest
from django.db import IntegrityError, connections, transaction

from bot.db import db
from bot.renderers.board import render_board, render_pickers
from bot.renderers.random_draft import render_random_draft
from league.domain import engine
from league.domain.draft_plan import champion_plan
from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import parse_mode
from league.models import (
    Community,
    DraftAction,
    Match,
    MatchResource,
    MatchResult,
    OutboxEffect,
    Player,
    QueueEntry,
    RatingEvent,
)
from league.models.matches import MatchKind, ResourceKind
from league.models.outbox import EffectStatus
from league.services import boards, community, deadlines, draft, effects, queue, scrims
from tests.conftest import Clock, activate, make_player
from tests.helpers import acting_captain
from tests.test_bot import FakeGateway, _http_error, all_buttons, assert_within_limits, drain

CHANNEL = 8100


def _fresh(match: Match) -> Match:
    return Match.objects.select_related("mode_version", "community").get(pk=match.pk)


def _people() -> tuple[Player, Player, Player, Player]:
    """The Hidden King's captain, The Archmother's, whoever starts it, and a stranger."""
    return make_player(1), make_player(2), make_player(3), make_player(4)


def _start(league: Community, channel: int = CHANNEL, **kwargs: Any) -> Match:
    return scrims.start_claim(league.pk, channel, make_player(3), **kwargs)


def _captained(league: Community, channel: int = CHANNEL) -> Match:
    match = _start(league, channel)
    scrims.claim_captain(match.pk, make_player(1), "hk")
    scrims.claim_captain(match.pk, make_player(2), "am")
    return _fresh(match)


def _run_draft(match: Match) -> Match:
    while match.status == Status.CHAMPION_DRAFT:
        champion = draft.available_champions(match)[0]
        draft.choose_champion(match.pk, acting_captain(match), match.step_index, champion)
        match = _fresh(match)
    return match


def _text(match: Match) -> str:
    return str(render_board(boards.board_state(match.pk)).to_components())


def _grid_buttons(match: Match) -> list[dict[str, Any]]:
    views = render_pickers(boards.board_state(match.pk))
    return [b for view in views for b in all_buttons(view.to_components())]


# --- Service ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_scrim_runs_the_modes_bans_and_picks_in_order(league: Community) -> None:
    match = _captained(league)
    assert match.kind == MatchKind.SCRIM and match.status == Status.CHAMPION_DRAFT
    # /startdraft: The Hidden King (team A) bans and picks first.
    assert match.hidden_king_team == match.champion_first_pick == "A"
    assert acting_captain(match) == make_player(1)
    match = _run_draft(match)
    plan = champion_plan(parse_mode(match.mode_version.body))
    assert match.status == Status.DRAFTED
    assert match.deadline_at is None and match.ended_at is not None
    actions = list(match.draft_actions.order_by("step_index"))
    assert [a.action for a in actions] == [step.action for step in plan]
    assert len({a.target_champion_id for a in actions}) == len(actions)
    # Every change asked for a render in the match's own lane, coalesced.
    renders = OutboxEffect.objects.filter(kind="render_board", match=match)
    assert renders.filter(status=EffectStatus.PENDING, started_at__isnull=True).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("slug", ["bebot_2ban", "draft_3ban"])
def test_every_preset_mode_runs_to_the_end(league: Community, slug: str) -> None:
    activate(league, slug)
    match = _run_draft(_captained(league))
    assert match.status == Status.DRAFTED
    assert match.draft_actions.count() == len(champion_plan(parse_mode(match.mode_version.body)))


@pytest.mark.django_db
def test_only_the_captain_on_turn_can_choose(league: Community) -> None:
    match = _captained(league)
    hk, am, _starter, stranger = _people()
    champion = draft.available_champions(match)[0]
    for player in (am, stranger):
        with pytest.raises(NotAllowed):
            draft.choose_champion(match.pk, player, match.step_index, champion)
    draft.choose_champion(match.pk, hk, match.step_index, champion)


@pytest.mark.django_db
def test_a_double_click_or_stale_step_takes_one_turn(league: Community) -> None:
    match = _captained(league)
    captain, step = acting_captain(match), match.step_index
    first, second = draft.available_champions(match)[:2]
    draft.choose_champion(match.pk, captain, step, first, interaction_id=77)
    with pytest.raises(StaleAction):  # The same click, delivered twice.
        draft.choose_champion(match.pk, captain, step, second, interaction_id=77)
    with pytest.raises(StaleAction):  # A click on the old grid.
        draft.choose_champion(match.pk, captain, step, second)
    assert match.draft_actions.count() == 1


@pytest.mark.django_db
def test_random_and_a_timeout_are_marked_as_bebot_did(league: Community, clock: Clock) -> None:
    match = _captained(league)
    draft.choose_random_champion(match.pk, acting_captain(match), match.step_index)
    assert "(random choice)" in _text(match)
    seconds = champion_plan(parse_mode(match.mode_version.body))[1].seconds
    clock.advance(seconds - 1)
    assert deadlines.tick() == 0
    clock.advance(2)
    assert deadlines.tick() == 1
    timed_out = match.draft_actions.order_by("step_index").last()
    assert timed_out is not None and timed_out.source == "timeout" and timed_out.actor_id is None
    assert "(randomed)" in _text(match)


@pytest.mark.django_db
def test_a_scrim_nobody_starts_frees_the_channel(league: Community, clock: Clock) -> None:
    match = _start(league)
    effects.record_resource(match.pk, ResourceKind.BOARD_MESSAGE, 1)  # Posted: only idle applies.
    clock.advance(scrims.IDLE_SECONDS + 1)
    assert deadlines.tick() == 1
    assert _fresh(match).status == Status.VOIDED
    assert OutboxEffect.objects.filter(kind=scrims.DELETE_KIND, match=match).exists()
    _start(league)  # The channel is free again.


@pytest.mark.django_db
def test_a_scrim_never_posted_frees_the_channel(league: Community, clock: Clock) -> None:
    match = _start(league)
    # Its render ran but never recorded a board: say the bot stopped in between.
    OutboxEffect.objects.filter(match=match).update(status=EffectStatus.DONE)
    clock.advance(scrims.UNPOSTED_SECONDS + 1)
    deadlines.tick()
    assert _fresh(match).status == Status.VOIDED


@pytest.mark.django_db
def test_one_still_waiting_for_its_first_post_is_kept(league: Community, clock: Clock) -> None:
    match = _start(league)  # Its first render is still queued, as after a restart.
    clock.advance(scrims.UNPOSTED_SECONDS + 1)
    deadlines.tick()
    assert _fresh(match).status == Status.CAPTAIN_CLAIM
    OutboxEffect.objects.filter(match=match).update(status=EffectStatus.FAILED)
    deadlines.tick()  # Nothing left to post it: now it frees the channel.
    assert _fresh(match).status == Status.VOIDED


@pytest.mark.django_db
def test_startup_grace_covers_a_turn_and_a_scrim_waiting_for_captains(
    league: Community, clock: Clock
) -> None:
    drafting = _captained(league)
    waiting = _start(league, CHANNEL + 1)
    for match in (drafting, waiting):
        effects.record_resource(match.pk, ResourceKind.BOARD_MESSAGE, 1)
    clock.advance(scrims.IDLE_SECONDS + 600)
    assert deadlines.extend_past_due() >= 2
    assert deadlines.tick() == 0  # The grace holds the auto-pick and the idle close off.
    assert _fresh(drafting).step_index == drafting.step_index
    assert _fresh(waiting).status == Status.CAPTAIN_CLAIM


@pytest.mark.django_db
def test_one_scrim_per_channel_and_a_cap_per_server(league: Community) -> None:
    _start(league)
    with pytest.raises(InvalidAction, match="already running"):
        _start(league)
    for offset in range(1, scrims.MAX_LIVE_SCRIMS):
        _start(league, CHANNEL + offset)
    with pytest.raises(InvalidAction, match="drafts running"):
        _start(league, CHANNEL + 999)


@pytest.mark.django_db
def test_the_database_allows_one_live_scrim_per_channel(league: Community) -> None:
    match = _start(league)
    with pytest.raises(IntegrityError), transaction.atomic():
        Match.objects.create(
            community=league,
            season=match.season,
            mode_version=match.mode_version,
            kind=MatchKind.SCRIM,
            status=Status.CAPTAIN_CLAIM,
            host_channel_id=CHANNEL,
            rng_seed=1,
            created_at=match.created_at,
        )


@pytest.mark.django_db
def test_stopping_a_scrim(league: Community) -> None:
    match = _captained(league)
    stranger = make_player(4)
    scrims.stop(CHANNEL, stranger)  # The command checks the Scrims area; the service just stops.
    assert _fresh(match).status == Status.VOIDED
    with pytest.raises(InvalidAction, match="No draft"):
        scrims.stop(CHANNEL, stranger)
    _start(league)


@pytest.mark.django_db
def test_captain_claims(league: Community) -> None:
    match = _start(league)
    hk, am, _starter, stranger = _people()
    assert scrims.claim_captain(match.pk, hk, "hk") == "The Hidden King"
    with pytest.raises(InvalidAction, match="already the captain"):
        scrims.claim_captain(match.pk, hk, "hk")
    with pytest.raises(InvalidAction, match="both sides"):
        scrims.claim_captain(match.pk, hk, "am")
    with pytest.raises(InvalidAction, match="already has a captain"):
        scrims.claim_captain(match.pk, stranger, "hk")
    scrims.claim_captain(match.pk, am, "am")
    assert _fresh(match).status == Status.CHAMPION_DRAFT
    with pytest.raises(StaleAction):
        scrims.claim_captain(match.pk, stranger, "am")


@pytest.mark.django_db
def test_a_captains_coinflip_runs_to_a_draft(league: Community) -> None:
    one, two, starter, stranger = _people()
    match = scrims.start_coinflip(league.pk, CHANNEL, starter, one, two)
    winner_team = match.coinflip_winner
    loser_team = "B" if winner_team == "A" else "A"
    winner = match.participants.get(team=winner_team).player
    loser = match.participants.get(team=loser_team).player
    with pytest.raises(NotAllowed, match="coinflip winner"):
        draft.choose_coinflip(match.pk, loser, engine.FIRST_PICK)
    draft.choose_coinflip(match.pk, winner, engine.LAST_PICK)
    assert _fresh(match).deadline_at == match.deadline_at  # No turn timer, as in Bebot.
    with pytest.raises(InvalidAction):  # The loser chooses from the other kind.
        draft.choose_coinflip(match.pk, loser, engine.FIRST_PICK)
    draft.choose_coinflip(match.pk, loser, engine.ARCHMOTHER)
    match = _fresh(match)
    assert match.status == Status.READY_TO_DRAFT
    assert match.hidden_king_team == winner_team
    assert match.champion_first_pick == loser_team  # The winner chose to pick last.
    assert "Ready to start the draft!" in _text(match)
    with pytest.raises(NotAllowed):
        scrims.start_draft(match.pk, stranger)
    scrims.start_draft(match.pk, loser)
    match = _fresh(match)
    assert match.status == Status.CHAMPION_DRAFT
    assert acting_captain(match) == loser  # The Archmother goes first.
    with pytest.raises(InvalidAction):
        scrims.start_coinflip(league.pk, CHANNEL + 1, starter, one, one)


@pytest.mark.django_db
def test_draft_actions_are_append_only(league: Community) -> None:
    match = _captained(league)
    draft.choose_random_champion(match.pk, acting_captain(match), match.step_index)
    with pytest.raises(Exception, match="append-only"), transaction.atomic():
        DraftAction.objects.filter(match=match).update(random_choice=False)


@pytest.mark.django_db
def test_random_draft_fills_every_slot_once(league: Community) -> None:
    result = scrims.random_draft(league)
    plan = champion_plan(parse_mode(league.active_mode.body))
    chosen = [hero.name for side in result.bans.values() for hero in side]
    chosen += [hero.name for side in result.picks.values() for hero in side]
    assert len(chosen) == len(plan) == len(set(chosen))
    assert_within_limits(render_random_draft(result))


# --- Kept out of ranked ---------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_scrim_never_touches_ratings_or_the_queue(league: Community) -> None:
    match = _captained(league)
    hk = make_player(1)
    queue.join(league.pk, hk)  # A scrim captain can queue for ranked meanwhile.
    assert QueueEntry.objects.filter(player=hk).exists()
    assert not match.participants.filter(is_active=True).exists()
    _run_draft(_fresh(match))
    assert not RatingEvent.objects.exists() and not MatchResult.objects.exists()
    assert not Match.objects.filter(kind=MatchKind.SCRIM, status=Status.COMPLETED).exists()
    view = boards.queue_view(league)
    assert view.live_matches == 0  # Scrims don't take ranked capacity.


@pytest.mark.django_db
def test_a_scrim_board_has_no_ranked_extras(league: Community) -> None:
    match = _captained(league)
    text = _text(match)
    assert f"🏆 Draft #{match.pk}" in text and "👑 **Captains**" in text
    assert "to win" not in text and "Request a sub" not in text


# --- Rendering --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_stage_renders_within_discords_limits(league: Community) -> None:
    one, two, starter, _stranger = _people()
    claim = _start(league)
    captained = _captained(league, CHANNEL + 1)
    flip = scrims.start_coinflip(league.pk, CHANNEL + 2, starter, one, two)
    views = [render_board(boards.board_state(m.pk)) for m in (claim, captained, flip)]
    views += render_pickers(boards.board_state(captained.pk))
    views.append(render_board(boards.board_state(_run_draft(captained).pk)))
    for view in views:
        assert_within_limits(view)
    labels = [b["label"] for b in all_buttons(views[0].to_components())]
    assert labels == ["Become The Hidden King Captain", "Become The Archmother Captain"]


@pytest.mark.django_db
def test_the_grid_keeps_taken_heroes_in_place(league: Community) -> None:
    match = _captained(league)
    before = [b["label"] for b in _grid_buttons(match)]
    draft.choose_champion(
        match.pk, acting_captain(match), match.step_index, draft.available_champions(match)[0]
    )
    after = _grid_buttons(_fresh(match))
    assert [b["label"] for b in after] == before
    assert sum(1 for b in after if b.get("disabled")) == 1
    assert before[-1] == "Random"


@pytest.mark.django_db
def test_custom_emojis_only_on_buttons_and_only_where_allowed(league: Community) -> None:
    from league.models import Champion

    Champion.objects.update(discord_emoji_id=123456789012345678)
    with_custom = _start(league, custom_emojis=True)
    without = _start(league, CHANNEL + 1, custom_emojis=False)
    for match in (with_custom, without):
        scrims.claim_captain(match.pk, make_player(1), "hk")
        scrims.claim_captain(match.pk, make_player(2), "am")

    def emoji_ids(match: Match) -> set[Any]:
        return {(b.get("emoji") or {}).get("id") for b in _grid_buttons(_fresh(match))}

    assert "123456789012345678" in {str(i) for i in emoji_ids(with_custom)}
    assert emoji_ids(without) <= {None}
    # Discord only draws a custom emoji in text for a bot in the server that owns it.
    draft.choose_champion(
        with_custom.pk,
        make_player(1),
        _fresh(with_custom).step_index,
        draft.available_champions(_fresh(with_custom))[0],
    )
    assert "<:" not in _text(with_custom)
    assert "<:" not in str(render_random_draft(scrims.random_draft(league)).to_components())


# --- Outbox, on a fake gateway ------------------------------------------------------------------


@pytest.fixture
def server(transactional_db: None) -> Iterator[Community]:
    row = community.ensure(guild_id=999, name="Test")
    yield row
    asyncio.run(db(connections.close_all))


def _board_id(match: Match) -> int | None:
    return effects.resource_id(match.pk, ResourceKind.BOARD_MESSAGE)


def _grid_ids(match: Match) -> list[int]:
    kinds = (ResourceKind.PICKER_MESSAGE, ResourceKind.PICKER_MESSAGE_2)
    return [m for kind in kinds if (m := effects.resource_id(match.pk, kind)) is not None]


@pytest.mark.django_db(transaction=True)
def test_the_board_posts_then_keeps_its_grid_below(server: Community) -> None:
    gateway = FakeGateway()
    match = _start(server)
    drain(gateway)
    posted = _board_id(match)
    assert posted is not None and _grid_ids(match) == []  # Captains first: no grid.
    scrims.claim_captain(match.pk, make_player(1), "hk")
    scrims.claim_captain(match.pk, make_player(2), "am")
    drain(gateway)
    assert _board_id(match) == posted and posted in gateway.edited  # Edited in place.
    grid = _grid_ids(match)
    assert len(grid) == 2
    assert gateway.messages[CHANNEL] == [posted, *grid]
    # A pick reposts the grid, so nothing in the channel is ever "(edited)" but the board.
    match = _fresh(match)
    draft.choose_champion(
        match.pk, acting_captain(match), match.step_index, draft.available_champions(match)[0]
    )
    drain(gateway)
    assert _board_id(match) == posted
    assert not set(_grid_ids(match)) & set(grid)
    assert gateway.messages[CHANNEL] == [posted, *_grid_ids(match)]
    # A scrim posts no notices and never gets channels of its own.
    assert not MatchResource.objects.filter(match=match, kind=ResourceKind.TEXT).exists()
    assert gateway.texts == []


@pytest.mark.django_db(transaction=True)
def test_chat_moves_the_scrim_back_to_the_bottom(server: Community, clock: Clock) -> None:
    gateway = FakeGateway()
    match = _captained(server)
    drain(gateway)
    before = _board_id(match)
    for _ in range(effects.SCRIM_MOVE.after_messages):
        gateway.chat(CHANNEL)
    drain(gateway)
    assert _board_id(match) == before  # It waits for a quiet moment.
    clock.advance(effects.SCRIM_MOVE.quiet_seconds + 1)
    drain(gateway)
    moved = _board_id(match)
    assert moved != before
    assert gateway.messages[CHANNEL][-3:] == [moved, *_grid_ids(match)]


@pytest.mark.django_db(transaction=True)
def test_stopping_deletes_every_message_but_never_the_channel(server: Community) -> None:
    gateway = FakeGateway()
    match = _captained(server)
    drain(gateway)
    scrims.stop(CHANNEL, make_player(3))
    drain(gateway)
    assert gateway.messages[CHANNEL] == []
    assert _board_id(match) is None and _grid_ids(match) == []
    assert CHANNEL not in gateway.deleted


@pytest.mark.django_db(transaction=True)
def test_a_finished_scrim_keeps_its_board_and_drops_the_grid(server: Community) -> None:
    gateway = FakeGateway()
    match = _captained(server)
    drain(gateway)
    match = _run_draft(_fresh(match))
    drain(gateway)
    assert _grid_ids(match) == []
    assert gateway.messages[CHANNEL] == [_board_id(match)]
    assert "# GLHF" in str(gateway.views[_board_id(match)].to_components())
    assert CHANNEL not in gateway.deleted


@pytest.mark.django_db(transaction=True)
def test_a_vanished_channel_closes_the_scrim(server: Community) -> None:
    gateway = FakeGateway()
    match = _start(server)
    gateway.deleted.append(CHANNEL)
    drain(gateway)
    assert _fresh(match).status == Status.VOIDED


@pytest.mark.django_db(transaction=True)
def test_a_channel_that_refuses_the_bot_closes_the_scrim(server: Community) -> None:
    gateway = FakeGateway()
    match = _start(server)
    gateway.fail_next["send_view"] = _http_error(403, 50013)
    drain(gateway)
    assert _fresh(match).status == Status.VOIDED
    effect = OutboxEffect.objects.filter(kind="render_board", match=match).first()
    assert effect is not None and effect.status == EffectStatus.FAILED


@pytest.mark.django_db(transaction=True)
def test_a_stuck_scrim_does_not_hold_up_the_next(server: Community) -> None:
    gateway = FakeGateway()
    stuck = _start(server)
    gateway.fail_next["send_view"] = _http_error(500, 0)  # Retried later, in its own lane.
    drain(gateway)
    other = _start(server, CHANNEL + 1)
    drain(gateway)
    assert _board_id(other) is not None
    assert _fresh(stuck).status == Status.CAPTAIN_CLAIM


@pytest.mark.django_db(transaction=True)
def test_a_failed_delete_is_retried_on_its_own(server: Community) -> None:
    gateway = FakeGateway()
    match = _captained(server)
    drain(gateway)
    old_grid = _grid_ids(match)
    match = _fresh(match)
    gateway.fail_next["delete_message"] = _http_error(500, 0)
    draft.choose_champion(
        match.pk, acting_captain(match), match.step_index, draft.available_champions(match)[0]
    )
    drain(gateway)
    retried = OutboxEffect.objects.filter(kind="delete_message", match=match)
    assert retried.count() == 1 and retried.get().status == EffectStatus.DONE
    assert not set(old_grid) & set(gateway.messages[CHANNEL])  # Nothing left behind.


@pytest.mark.django_db(transaction=True)
def test_a_failed_chat_move_leaves_the_scrim_running(server: Community) -> None:
    from bot.effects.worker import EffectWorker

    match = _captained(server)
    effect = OutboxEffect.objects.create(
        community=server,
        match=match,
        kind="move_board",
        payload={},
        run_after=match.created_at,
        created_at=match.created_at,
    )
    asyncio.run(EffectWorker(FakeGateway())._on_failed(effect, "403"))
    assert _fresh(match).status == Status.CHAMPION_DRAFT


@pytest.mark.django_db(transaction=True)
def test_the_bot_never_deletes_a_channel_a_scrim_ran_in(server: Community) -> None:
    """Even if a ranked match somehow recorded that channel as its own."""
    from league.services.common import add_effect
    from tests.test_bot import popped_match

    gateway = FakeGateway()
    ranked = popped_match(server, gateway)
    scrim = _start(server)
    MatchResource.objects.filter(match=ranked, kind=ResourceKind.TEXT).update(discord_id=CHANNEL)
    add_effect(server, "delete_text_channel", match=ranked)
    drain(gateway)
    assert CHANNEL not in gateway.deleted
    assert _fresh(scrim).kind == MatchKind.SCRIM
