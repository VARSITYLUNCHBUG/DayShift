"""The standalone draft (/startdraft, /captains_coinflip): service rules, then the outbox on a
fake gateway."""

from __future__ import annotations

import itertools
from typing import Any

import discord
import pytest
from django.db import IntegrityError, transaction

from bot.renderers.quick_draft import render_draft, render_grid, render_random_draft
from league.domain import engine
from league.domain.draft_plan import champion_plan
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import parse_mode
from league.models import Community, OutboxEffect, QuickDraft, QuickDraftAction
from league.models.outbox import EffectStatus
from league.models.quick_drafts import QuickDraftStatus, Side
from league.services import deadlines, effects, quick_drafts
from tests.conftest import Clock, activate
from tests.test_bot import (
    FakeGateway,
    _http_error,
    all_buttons,
    assert_within_limits,
    drain,
    wired,  # noqa: F401  (a fixture)
)

CHANNEL = 8100
HK, AM, STARTER, STRANGER = 1111, 2222, 3333, 4444


def _fresh(draft: QuickDraft) -> QuickDraft:
    return QuickDraft.objects.get(pk=draft.pk)


def _start(community: Community, channel: int = CHANNEL) -> QuickDraft:
    return quick_drafts.start(community.pk, channel, STARTER)


def _captained(community: Community, channel: int = CHANNEL) -> QuickDraft:
    draft = _start(community, channel)
    quick_drafts.claim_captain(draft.pk, Side.HIDDEN_KING, HK, "Hidden", allow_both=False)
    quick_drafts.claim_captain(draft.pk, Side.ARCHMOTHER, AM, "Mother", allow_both=False)
    return _fresh(draft)


def _on_turn(draft: QuickDraft) -> int:
    step = champion_plan(parse_mode(draft.mode_version.body))[draft.step_index]
    side = quick_drafts.side_for_role(step.role, draft.first_side)
    captain = draft.captain_id(side)
    assert captain is not None
    return captain


def _run_draft(draft: QuickDraft) -> QuickDraft:
    while draft.status == QuickDraftStatus.DRAFTING:
        hero = quick_drafts.available(draft)[0]
        quick_drafts.choose_hero(draft.pk, _on_turn(draft), draft.step_index, hero)
        draft = _fresh(draft)
    return draft


# --- Service ----------------------------------------------------------------------------------


@pytest.mark.django_db
def test_a_draft_runs_the_modes_bans_and_picks_in_order(league: Community) -> None:
    draft = _captained(league)
    assert draft.status == QuickDraftStatus.DRAFTING
    assert draft.first_side == Side.HIDDEN_KING  # /startdraft: the Hidden King goes first.
    draft = _run_draft(draft)
    plan = champion_plan(parse_mode(draft.mode_version.body))
    assert draft.status == QuickDraftStatus.COMPLETED
    assert draft.deadline_at is None and draft.ended_at is not None
    actions = list(draft.actions.order_by("step_index"))
    assert [a.action for a in actions] == [step.action for step in plan]
    assert len({a.champion_id for a in actions}) == len(actions)
    # Every change asked for a render in the draft's own lane, coalesced.
    renders = OutboxEffect.objects.filter(kind=quick_drafts.RENDER_KIND)
    assert {row.lane for row in renders} == {draft.lane}
    assert renders.filter(status=EffectStatus.PENDING, started_at__isnull=True).count() == 1


@pytest.mark.django_db
@pytest.mark.parametrize("slug", ["bebot_2ban", "threeban_1win_2026"])
def test_every_preset_mode_runs_to_the_end(league: Community, slug: str) -> None:
    activate(league, slug)
    draft = _run_draft(_captained(league))
    assert draft.status == QuickDraftStatus.COMPLETED
    assert draft.actions.count() == len(champion_plan(parse_mode(draft.mode_version.body)))


@pytest.mark.django_db
def test_only_the_captain_on_turn_can_choose(league: Community) -> None:
    draft = _captained(league)
    waiting = AM if _on_turn(draft) == HK else HK
    hero = quick_drafts.available(draft)[0]
    with pytest.raises(NotAllowed):
        quick_drafts.choose_hero(draft.pk, waiting, draft.step_index, hero)
    with pytest.raises(NotAllowed):
        quick_drafts.choose_hero(draft.pk, STRANGER, draft.step_index, hero)


@pytest.mark.django_db
def test_a_double_click_or_stale_step_takes_one_turn(league: Community) -> None:
    draft = _captained(league)
    captain, step = _on_turn(draft), draft.step_index
    first, second = quick_drafts.available(draft)[:2]
    quick_drafts.choose_hero(draft.pk, captain, step, first, interaction_id=77)
    with pytest.raises(StaleAction):  # The same click, delivered twice.
        quick_drafts.choose_hero(draft.pk, captain, step, second, interaction_id=77)
    with pytest.raises(StaleAction):  # A click on the old grid.
        quick_drafts.choose_hero(draft.pk, captain, step, second)
    assert draft.actions.count() == 1


@pytest.mark.django_db
def test_a_taken_hero_is_refused(league: Community) -> None:
    draft = _captained(league)
    hero = quick_drafts.available(draft)[0]
    quick_drafts.choose_hero(draft.pk, _on_turn(draft), draft.step_index, hero)
    draft = _fresh(draft)
    with pytest.raises(InvalidAction):
        quick_drafts.choose_hero(draft.pk, _on_turn(draft), draft.step_index, hero)


@pytest.mark.django_db
def test_random_marks_the_choice(league: Community) -> None:
    draft = _captained(league)
    champion = quick_drafts.choose_random(draft.pk, _on_turn(draft), draft.step_index)
    action = QuickDraftAction.objects.get(draft=draft)
    assert action.champion_id == champion and action.random_choice and action.source == "user"
    assert "(random choice)" in str(render_draft(quick_drafts.state(draft.pk)).to_components())


@pytest.mark.django_db
def test_a_turn_that_runs_out_picks_at_random(league: Community, clock: Clock) -> None:
    draft = _captained(league)
    seconds = champion_plan(parse_mode(draft.mode_version.body))[0].seconds
    clock.advance(seconds - 1)
    assert deadlines.tick() == 0
    clock.advance(2)
    assert deadlines.tick() == 1
    action = QuickDraftAction.objects.get(draft=draft)
    assert action.source == "timeout" and action.actor_id is None
    assert _fresh(draft).step_index == 1
    assert "(randomed)" in str(render_draft(quick_drafts.state(draft.pk)).to_components())


@pytest.mark.django_db
def test_a_draft_nobody_starts_frees_the_channel(league: Community, clock: Clock) -> None:
    draft = _start(league)
    quick_drafts.record_board(draft.pk, 1)  # Posted, so only the idle timer applies.
    clock.advance(quick_drafts.IDLE_SECONDS + 1)
    assert deadlines.tick() == 1
    assert _fresh(draft).status == QuickDraftStatus.STOPPED
    assert OutboxEffect.objects.filter(kind=quick_drafts.DELETE_KIND, lane=draft.lane).exists()
    _start(league)  # The channel is free again.


@pytest.mark.django_db
def test_a_draft_never_posted_frees_the_channel(league: Community, clock: Clock) -> None:
    draft = _start(league)
    # Its render ran but never recorded a message: say the bot stopped in between.
    OutboxEffect.objects.filter(lane=draft.lane).update(status=EffectStatus.DONE)
    clock.advance(quick_drafts.UNPOSTED_SECONDS + 1)
    deadlines.tick()
    assert _fresh(draft).status == QuickDraftStatus.STOPPED


@pytest.mark.django_db
def test_startup_grace_extends_a_turn_on_the_clock(league: Community, clock: Clock) -> None:
    draft = _captained(league)
    quick_drafts.record_board(draft.pk, 1)
    clock.advance(3600)
    assert deadlines.extend_past_due() >= 1
    assert deadlines.tick() == 0  # The grace holds the auto-pick off.
    draft = _fresh(draft)
    assert draft.status == QuickDraftStatus.DRAFTING and draft.step_index == 0


@pytest.mark.django_db
def test_one_draft_per_channel_and_a_cap_per_server(league: Community) -> None:
    _start(league)
    with pytest.raises(InvalidAction, match="already running"):
        _start(league)
    for offset in range(1, quick_drafts.MAX_LIVE_DRAFTS):
        _start(league, CHANNEL + offset)
    with pytest.raises(InvalidAction, match="drafts running"):
        _start(league, CHANNEL + 999)


@pytest.mark.django_db
def test_the_database_allows_one_live_draft_per_channel(league: Community) -> None:
    draft = _start(league)
    with pytest.raises(IntegrityError), transaction.atomic():
        QuickDraft.objects.create(
            community=league,
            mode_version=draft.mode_version,
            channel_id=CHANNEL,
            status=QuickDraftStatus.CAPTAINS,
            started_by_id=STRANGER,
            rng_seed=1,
            created_at=draft.created_at,
        )


@pytest.mark.django_db
def test_who_can_stop_a_draft(league: Community) -> None:
    draft = _captained(league)
    with pytest.raises(NotAllowed):
        quick_drafts.stop(CHANNEL, STRANGER, staff=False)
    quick_drafts.stop(CHANNEL, AM, staff=False)  # A captain can.
    assert _fresh(draft).status == QuickDraftStatus.STOPPED
    with pytest.raises(InvalidAction):
        quick_drafts.stop(CHANNEL, AM, staff=False)
    _start(league)
    quick_drafts.stop(CHANNEL, STRANGER, staff=True)  # Staff can stop anyone's.
    _start(league)
    quick_drafts.stop(CHANNEL, STARTER, staff=False)  # So can whoever started it.


@pytest.mark.django_db
def test_captain_claims(league: Community) -> None:
    draft = _start(league)
    quick_drafts.claim_captain(draft.pk, Side.HIDDEN_KING, HK, "Hidden", allow_both=False)
    with pytest.raises(InvalidAction, match="already the captain"):
        quick_drafts.claim_captain(draft.pk, Side.HIDDEN_KING, HK, "Hidden", allow_both=False)
    with pytest.raises(InvalidAction, match="both sides"):
        quick_drafts.claim_captain(draft.pk, Side.ARCHMOTHER, HK, "Hidden", allow_both=False)
    with pytest.raises(InvalidAction, match="already has a captain"):
        quick_drafts.claim_captain(draft.pk, Side.HIDDEN_KING, STRANGER, "X", allow_both=False)
    # With DEBUG on, one person can test both sides.
    quick_drafts.claim_captain(draft.pk, Side.ARCHMOTHER, HK, "Hidden", allow_both=True)
    assert _fresh(draft).status == QuickDraftStatus.DRAFTING
    with pytest.raises(StaleAction):
        quick_drafts.claim_captain(draft.pk, Side.ARCHMOTHER, AM, "Mother", allow_both=False)


@pytest.mark.django_db
def test_a_captains_coinflip_runs_to_a_draft(league: Community) -> None:
    draft = quick_drafts.start_coinflip(league.pk, CHANNEL, STARTER, (HK, "One"), (AM, "Two"))
    winner, loser = draft.coinflip_winner_id, draft.coinflip_loser_id
    assert {winner, loser} == {HK, AM}
    with pytest.raises(NotAllowed):
        quick_drafts.coinflip_choose(draft.pk, loser, engine.FIRST_PICK)
    quick_drafts.coinflip_choose(draft.pk, winner, engine.LAST_PICK)
    with pytest.raises(InvalidAction):  # The loser chooses from the other kind.
        quick_drafts.coinflip_choose(draft.pk, loser, engine.FIRST_PICK)
    quick_drafts.coinflip_choose(draft.pk, loser, engine.ARCHMOTHER)
    draft = _fresh(draft)
    assert draft.status == QuickDraftStatus.READY
    assert draft.am_captain_id == loser and draft.hk_captain_id == winner
    assert draft.first_side == Side.ARCHMOTHER  # The winner chose to pick last.
    with pytest.raises(NotAllowed):
        quick_drafts.start_after_coinflip(draft.pk, STRANGER)
    quick_drafts.start_after_coinflip(draft.pk, loser)
    draft = _fresh(draft)
    assert draft.status == QuickDraftStatus.DRAFTING
    assert _on_turn(draft) == loser  # The Archmother goes first.
    with pytest.raises(InvalidAction):
        quick_drafts.start_coinflip(league.pk, CHANNEL + 1, STARTER, (HK, "A"), (HK, "A"))


@pytest.mark.django_db
def test_draft_actions_are_append_only(league: Community) -> None:
    draft = _captained(league)
    quick_drafts.choose_random(draft.pk, _on_turn(draft), draft.step_index)
    with pytest.raises(Exception, match="append-only"), transaction.atomic():
        QuickDraftAction.objects.filter(draft=draft).update(random_choice=False)


@pytest.mark.django_db
def test_random_draft_fills_every_slot_once(league: Community) -> None:
    result = quick_drafts.random_draft(league)
    plan = champion_plan(parse_mode(league.active_mode.body))
    chosen = [hero.id for side in result.bans.values() for hero in side]
    chosen += [hero.id for side in result.picks.values() for hero in side]
    assert len(chosen) == len(plan) == len(set(chosen))
    assert_within_limits(render_random_draft(result))


# --- Rendering --------------------------------------------------------------------------------


@pytest.mark.django_db
def test_every_stage_renders_within_discords_limits(league: Community) -> None:
    draft = _start(league)
    views = [render_draft(quick_drafts.state(draft.pk))]
    draft = _captained(league, CHANNEL + 1)
    state = quick_drafts.state(draft.pk)
    views += [render_draft(state), *render_grid(state)]
    flip = quick_drafts.start_coinflip(league.pk, CHANNEL + 2, STARTER, (HK, "A"), (AM, "B"))
    views.append(render_draft(quick_drafts.state(flip.pk)))
    views.append(render_draft(quick_drafts.state(_run_draft(draft).pk)))
    for view in views:
        assert_within_limits(view)


@pytest.mark.django_db
def test_the_grid_keeps_taken_heroes_in_place(league: Community) -> None:
    draft = _captained(league)
    before = [
        b["label"] for view in render_grid(quick_drafts.state(draft.pk)) for b in _buttons(view)
    ]
    hero = quick_drafts.available(draft)[0]
    quick_drafts.choose_hero(draft.pk, _on_turn(draft), draft.step_index, hero)
    after_buttons = [
        b for view in render_grid(quick_drafts.state(draft.pk)) for b in _buttons(view)
    ]
    assert [b["label"] for b in after_buttons] == before
    assert sum(1 for b in after_buttons if b.get("disabled")) == 1
    assert before[-1] == "Random"


@pytest.mark.django_db
def test_custom_emojis_are_left_out_where_the_bot_cant_use_them(league: Community) -> None:
    from league.models import Champion

    Champion.objects.update(discord_emoji_id=123456789012345678)
    with_custom = quick_drafts.start(league.pk, CHANNEL, STARTER, custom_emojis=True)
    without = quick_drafts.start(league.pk, CHANNEL + 1, STARTER, custom_emojis=False)
    for draft in (with_custom, without):
        quick_drafts.claim_captain(draft.pk, "hk", HK, "H", allow_both=False)
        quick_drafts.claim_captain(draft.pk, "am", AM, "A", allow_both=False)

    def custom_ids(draft: QuickDraft) -> set[Any]:
        buttons = [b for v in render_grid(quick_drafts.state(draft.pk)) for b in _buttons(v)]
        return {b["emoji"].get("id") for b in buttons if b.get("emoji")}

    assert "123456789012345678" in {str(i) for i in custom_ids(with_custom)}
    assert custom_ids(without) <= {None}


def _buttons(view: discord.ui.LayoutView) -> list[dict[str, Any]]:
    return all_buttons(view.to_components())


# --- Outbox, on a fake gateway ------------------------------------------------------------------


def _messages(draft: QuickDraft) -> quick_drafts.Messages:
    return quick_drafts.messages(draft.pk)


@pytest.mark.django_db(transaction=True)
def test_the_draft_posts_then_keeps_its_grid_below(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _start(wired)
    drain(gateway)
    posted = _messages(draft)
    assert posted.board_id is not None and posted.grid_ids == ()  # Captains first: no grid.
    quick_drafts.claim_captain(draft.pk, "hk", HK, "H", allow_both=False)
    quick_drafts.claim_captain(draft.pk, "am", AM, "A", allow_both=False)
    drain(gateway)
    drafting = _messages(draft)
    assert drafting.board_id == posted.board_id  # Still at the bottom: edited in place.
    assert drafting.board_id in gateway.edited
    assert len(drafting.grid_ids) == 2
    assert gateway.messages[CHANNEL] == [drafting.board_id, *drafting.grid_ids]
    # A pick reposts the grid, so nothing in the channel is ever "(edited)" but the draft.
    draft = _fresh(draft)
    quick_drafts.choose_hero(
        draft.pk, _on_turn(draft), draft.step_index, quick_drafts.available(draft)[0]
    )
    drain(gateway)
    after = _messages(draft)
    assert after.board_id == drafting.board_id
    assert not set(after.grid_ids) & set(drafting.grid_ids)
    assert gateway.messages[CHANNEL] == [after.board_id, *after.grid_ids]


@pytest.mark.django_db(transaction=True)
def test_chat_moves_the_draft_back_to_the_bottom(wired: Community, clock: Clock) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _captained(wired)
    drain(gateway)
    before = _messages(draft)
    for _ in range(effects.QUICK_DRAFT_MOVE.after_messages):
        gateway.chat(CHANNEL)
    drain(gateway)
    assert _messages(draft).board_id == before.board_id  # It waits for a quiet moment.
    clock.advance(effects.QUICK_DRAFT_MOVE.quiet_seconds + 1)
    drain(gateway)
    moved = _messages(draft)
    assert moved.board_id != before.board_id
    assert gateway.messages[CHANNEL][-3:] == [moved.board_id, *moved.grid_ids]


@pytest.mark.django_db(transaction=True)
def test_stopping_deletes_every_message(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _captained(wired)
    drain(gateway)
    quick_drafts.stop(CHANNEL, STARTER, staff=False)
    drain(gateway)
    assert gateway.messages[CHANNEL] == []
    gone = _messages(draft)
    assert gone.board_id is None and gone.grid_ids == ()


@pytest.mark.django_db(transaction=True)
def test_a_vanished_channel_closes_the_draft(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _start(wired)
    gateway.deleted.append(CHANNEL)
    drain(gateway)
    assert _fresh(draft).status == QuickDraftStatus.STOPPED


@pytest.mark.django_db(transaction=True)
def test_a_channel_that_refuses_the_bot_closes_the_draft(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _start(wired)
    gateway.fail_next["send_view"] = _http_error(403, 50013)
    drain(gateway)
    assert _fresh(draft).status == QuickDraftStatus.STOPPED
    effect = OutboxEffect.objects.get(kind=quick_drafts.RENDER_KIND, lane=draft.lane)
    assert effect.status == EffectStatus.FAILED


@pytest.mark.django_db(transaction=True)
def test_a_stuck_draft_does_not_hold_up_the_next(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    stuck = _start(wired)
    gateway.fail_next["send_view"] = _http_error(500, 0)  # Retried later, in its own lane.
    drain(gateway)
    other = _start(wired, CHANNEL + 1)
    drain(gateway)
    assert _messages(other).board_id is not None
    assert _fresh(stuck).status == QuickDraftStatus.CAPTAINS


def test_settle_needs_a_side() -> None:
    for first, second in itertools.product(engine.ORDER_CHOICES, repeat=2):
        with pytest.raises(ValueError):
            quick_drafts.settle_coinflip(first, second)


# --- Review fixes -------------------------------------------------------------------------------


@pytest.mark.django_db(transaction=True)
def test_a_finished_draft_forgets_its_whole_grid(wired: Community) -> None:  # noqa: F811
    """Clearing both grid slots used to shift the second into the first and keep its ID."""
    gateway = FakeGateway()
    draft = _captained(wired)
    drain(gateway)
    assert len(_messages(draft).grid_ids) == 2
    _run_draft(_fresh(draft))
    drain(gateway)
    done = _messages(draft)
    assert done.grid_ids == ()
    assert gateway.messages[CHANNEL] == [done.board_id]


@pytest.mark.django_db
def test_clearing_a_grid_slot_keeps_the_others_in_place(league: Community) -> None:
    draft = _start(league)
    quick_drafts.record_grid(draft.pk, 0, 11)
    quick_drafts.record_grid(draft.pk, 1, 22)
    quick_drafts.record_grid(draft.pk, 0, None)
    assert _fresh(draft).grid_message_ids == [None, 22]
    quick_drafts.record_grid(draft.pk, 1, None)
    assert _fresh(draft).grid_message_ids == []


@pytest.mark.django_db(transaction=True)
def test_a_failed_delete_is_retried_on_its_own(wired: Community) -> None:  # noqa: F811
    gateway = FakeGateway()
    draft = _captained(wired)
    drain(gateway)
    old_grid = _messages(draft).grid_ids
    draft = _fresh(draft)
    gateway.fail_next["delete_message"] = _http_error(500, 0)
    quick_drafts.choose_hero(
        draft.pk, _on_turn(draft), draft.step_index, quick_drafts.available(draft)[0]
    )
    drain(gateway)
    retried = OutboxEffect.objects.filter(kind="delete_message", lane=draft.lane)
    assert retried.count() == 1 and retried.get().status == EffectStatus.DONE
    assert not set(old_grid) & set(gateway.messages[CHANNEL])  # Nothing left behind.


@pytest.mark.django_db
def test_a_draft_still_waiting_for_its_first_post_is_kept(league: Community, clock: Clock) -> None:
    draft = _start(league)  # Its first render is still queued, as after a restart.
    clock.advance(quick_drafts.UNPOSTED_SECONDS + 1)
    deadlines.tick()
    assert _fresh(draft).status == QuickDraftStatus.CAPTAINS
    OutboxEffect.objects.filter(lane=draft.lane).update(status=EffectStatus.FAILED)
    deadlines.tick()  # Nothing left to post it: now it frees the channel.
    assert _fresh(draft).status == QuickDraftStatus.STOPPED


@pytest.mark.django_db
def test_startup_grace_also_covers_drafts_waiting_for_captains(
    league: Community, clock: Clock
) -> None:
    draft = _start(league)
    quick_drafts.record_board(draft.pk, 1)
    clock.advance(quick_drafts.IDLE_SECONDS + 600)
    deadlines.extend_past_due()
    deadlines.tick()
    assert _fresh(draft).status == QuickDraftStatus.CAPTAINS


@pytest.mark.django_db(transaction=True)
def test_a_failed_chat_move_leaves_the_draft_running(wired: Community) -> None:  # noqa: F811
    from bot.effects.worker import EffectWorker

    draft = _captained(wired)
    effect = OutboxEffect.objects.create(
        community=wired,
        kind=quick_drafts.MOVE_KIND,
        lane=draft.lane,
        payload={"draft_id": draft.pk},
        run_after=draft.created_at,
        created_at=draft.created_at,
    )
    import asyncio

    asyncio.run(EffectWorker(FakeGateway())._on_failed(effect, "403"))
    assert _fresh(draft).status == QuickDraftStatus.DRAFTING


@pytest.mark.django_db
def test_draft_text_never_uses_custom_emojis(league: Community) -> None:
    """Discord only draws a custom emoji in text for a bot in the server that owns it; found in a
    live run, where Bebot's hero emojis showed as bare ":mina:". Buttons keep them."""
    from league.models import Champion

    Champion.objects.update(discord_emoji_id=123456789012345678)
    draft = _captained(league)
    quick_drafts.choose_hero(draft.pk, _on_turn(draft), 0, quick_drafts.available(draft)[0])
    state = quick_drafts.state(draft.pk)
    assert "<:" not in str(render_draft(state).to_components())
    assert "<:" not in str(render_random_draft(quick_drafts.random_draft(league)).to_components())
    buttons = [b for view in render_grid(state) for b in _buttons(view)]
    assert any((b.get("emoji") or {}).get("id") for b in buttons)
