"""Bebot's standalone draft: /startdraft and /captains_coinflip, in any channel.

Two captains ban and pick heroes in the active mode's order. Nothing here touches ratings. It
keeps the match flow's guarantees: every change takes the draft's row lock, each step is one
append-only row (so a double click can't take two turns), timers are rows the poller fires, and
Discord changes go through the outbox in the draft's own lane.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from django.db import IntegrityError, transaction

from league import log_context
from league.domain import copy
from league.domain.draft_plan import PlanStep, champion_plan
from league.domain.engine import (  # The coinflip rules are the ranked flow's.
    auto_champion,
    coinflip_options,
    draft_name,
    other_side,
    pick_gif,
    seeded_rng,
    settle_coinflip,
)
from league.domain.errors import DomainError, InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import DraftMode, parse_mode
from league.models import Champion, Community, OutboxEffect, QuickDraft, QuickDraftAction
from league.models.outbox import EffectStatus
from league.models.quick_drafts import QUICK_DRAFT_LIVE, QuickDraftStatus, Side
from league.services import champions
from league.services.common import add_effect, lock_community, now, request_render
from league.services.gifs import draft_gifs

logger = logging.getLogger(__name__)

# A server can have this many drafts going at once, across all its channels.
MAX_LIVE_DRAFTS = 10
# A draft nobody starts (captains unclaimed, coinflip unanswered) frees its channel after this.
IDLE_SECONDS = 15 * 60
# The first render posts the draft message. One still without a message after this never got
# posted (the channel refused it, say), so it frees the channel.
UNPOSTED_SECONDS = 5 * 60

RENDER_KIND = "render_quick_draft"
MOVE_KIND = "move_quick_draft"
DELETE_KIND = "delete_quick_draft"


def side_for_role(role: str, first_side: str) -> str:
    return first_side if role == "first" else other_side(first_side)


def _mode(draft: QuickDraft) -> DraftMode:
    return parse_mode(draft.mode_version.body)


def _lock(draft_id: int) -> QuickDraft:
    """Take the row lock every change goes through. Call inside transaction.atomic()."""
    draft = (
        QuickDraft.objects.select_for_update(of=("self",))
        .select_related("mode_version", "community")
        .filter(pk=draft_id)
        .first()
    )
    if draft is None:
        raise StaleAction("That draft no longer exists.")
    return draft


def _save(draft: QuickDraft, *fields: str) -> None:
    draft.version += 1
    draft.save(update_fields=[*fields, "version"])
    render(draft)


def render(draft: QuickDraft) -> None:
    """Ask for a re-render. Renders read the latest state, so pending ones coalesce."""
    request_render(draft.community, RENDER_KIND, lane=draft.lane, payload={"draft_id": draft.pk})


def live_in_channel(channel_id: int) -> QuickDraft | None:
    return QuickDraft.objects.filter(channel_id=channel_id, status__in=QUICK_DRAFT_LIVE).first()


# --- Starting -------------------------------------------------------------------------------


def _create(
    community_id: int,
    channel_id: int,
    started_by_id: int,
    *,
    custom_emojis: bool,
    **fields: object,
) -> QuickDraft:
    community = lock_community(community_id)  # Serialises the per-server cap.
    if live_in_channel(channel_id) is not None:
        raise InvalidAction(copy.DRAFT_RUNNING_HERE)
    live = QuickDraft.objects.filter(community=community, status__in=QUICK_DRAFT_LIVE).count()
    if live >= MAX_LIVE_DRAFTS:
        raise InvalidAction(
            f"This server already has {MAX_LIVE_DRAFTS} drafts running. Finish or stop one first."
        )
    mode_version = community.active_mode
    mode = parse_mode(mode_version.body)
    pool = champions.draft_pool(mode)
    if len(pool) < len(champion_plan(mode)):
        raise InvalidAction("Not enough heroes are enabled to run a draft.")
    moment = now()
    try:
        with transaction.atomic():
            draft = QuickDraft.objects.create(
                community=community,
                mode_version=mode_version,
                channel_id=channel_id,
                started_by_id=started_by_id,
                rng_seed=secrets.randbits(62),
                champion_pool=pool,
                custom_emojis=custom_emojis,
                deadline_at=moment + timedelta(seconds=IDLE_SECONDS),
                created_at=moment,
                **fields,
            )
    except IntegrityError as exc:  # Another /startdraft in this channel won the race.
        raise InvalidAction("A draft is already running in this channel.") from exc
    render(draft)
    logger.info("Quick draft started", extra={"draft": draft.pk, "channel": channel_id})
    return draft


@transaction.atomic
def start(
    community_id: int, channel_id: int, started_by_id: int, *, custom_emojis: bool = True
) -> QuickDraft:
    """/startdraft: post the two Become Captain buttons. The Hidden King bans and picks first."""
    return _create(
        community_id,
        channel_id,
        started_by_id,
        custom_emojis=custom_emojis,
        status=QuickDraftStatus.CAPTAINS,
    )


@transaction.atomic
def start_coinflip(
    community_id: int,
    channel_id: int,
    started_by_id: int,
    first: tuple[int, str],
    second: tuple[int, str],
    *,
    custom_emojis: bool = True,
) -> QuickDraft:
    """/captains_coinflip: flip between two captains. The winner chooses first."""
    if first[0] == second[0]:
        raise InvalidAction(copy.SAME_PLAYER_COINFLIP)
    winner, loser = (first, second) if secrets.randbelow(2) == 0 else (second, first)
    return _create(
        community_id,
        channel_id,
        started_by_id,
        custom_emojis=custom_emojis,
        status=QuickDraftStatus.COINFLIP,
        coinflip_winner_id=winner[0],
        coinflip_winner_name=winner[1][:100],
        coinflip_loser_id=loser[0],
        coinflip_loser_name=loser[1][:100],
    )


# --- Captains -------------------------------------------------------------------------------


@transaction.atomic
def claim_captain(draft_id: int, side: str, user_id: int, name: str, *, allow_both: bool) -> str:
    """A Become Captain button. Returns the side's name. Both claimed starts the hero draft."""
    draft = _lock(draft_id)
    if draft.status != QuickDraftStatus.CAPTAINS:
        raise StaleAction(copy.CAPTAINS_CHOSEN)
    if side not in Side.values:
        raise InvalidAction("That isn't a side.")
    label = Side(side).label
    if draft.captain_id(side) == user_id:
        raise InvalidAction(copy.already_captain(label))
    if not allow_both and draft.captain_id(other_side(side)) == user_id:
        raise InvalidAction(copy.CANT_CAPTAIN_BOTH)
    if draft.captain_id(side) is not None:
        raise InvalidAction(copy.has_captain(label))
    if side == Side.HIDDEN_KING:
        draft.hk_captain_id, draft.hk_captain_name = user_id, name[:100]
    else:
        draft.am_captain_id, draft.am_captain_name = user_id, name[:100]
    fields = ["hk_captain_id", "hk_captain_name", "am_captain_id", "am_captain_name"]
    if draft.hk_captain_id is not None and draft.am_captain_id is not None:
        fields += _begin(draft)
    _save(draft, *fields)
    return label


# --- Coinflip -------------------------------------------------------------------------------


@transaction.atomic
def coinflip_choose(draft_id: int, user_id: int, choice: str) -> None:
    draft = _lock(draft_id)
    if draft.status != QuickDraftStatus.COINFLIP:
        raise StaleAction("The coinflip choices are already made.")
    winner_turn = not draft.winner_choice
    chooser = draft.coinflip_winner_id if winner_turn else draft.coinflip_loser_id
    if user_id != chooser:
        who = "winner" if winner_turn else "loser"
        raise NotAllowed(copy.coinflip_only(who))
    if choice not in coinflip_options(draft.winner_choice):
        raise InvalidAction("That choice isn't available.")
    if winner_turn:
        draft.winner_choice = choice
        _save(draft, "winner_choice")
        return
    draft.loser_choice = choice
    winner_side, _loser_side, first = settle_coinflip(draft.winner_choice, choice)
    winner = (draft.coinflip_winner_id, draft.coinflip_winner_name)
    loser = (draft.coinflip_loser_id, draft.coinflip_loser_name)
    hk, am = (winner, loser) if winner_side == Side.HIDDEN_KING else (loser, winner)
    draft.hk_captain_id, draft.hk_captain_name = hk
    draft.am_captain_id, draft.am_captain_name = am
    draft.first_side = first
    draft.status = QuickDraftStatus.READY
    _save(
        draft,
        "loser_choice",
        "hk_captain_id",
        "hk_captain_name",
        "am_captain_id",
        "am_captain_name",
        "first_side",
        "status",
    )


@transaction.atomic
def start_after_coinflip(draft_id: int, user_id: int) -> None:
    """The Start Draft button, once both captains have chosen."""
    draft = _lock(draft_id)
    if draft.status != QuickDraftStatus.READY:
        raise StaleAction("This draft has already started.")
    if user_id not in (draft.hk_captain_id, draft.am_captain_id):
        raise NotAllowed(copy.ONLY_CAPTAINS_START)
    _save(draft, *_begin(draft))


# --- Hero draft -----------------------------------------------------------------------------


def _begin(draft: QuickDraft) -> list[str]:
    """Start the bans and picks. Returns the fields it changed, for the caller's save."""
    steps = champion_plan(_mode(draft))
    draft.status = QuickDraftStatus.DRAFTING
    draft.step_index = 0
    draft.deadline_at = now() + timedelta(seconds=steps[0].seconds)
    return ["status", "step_index", "deadline_at"]


def _current(draft: QuickDraft, step_index: int | None) -> PlanStep:
    if draft.status != QuickDraftStatus.DRAFTING:
        raise StaleAction(copy.NOT_TAKING_SELECTIONS)
    steps = champion_plan(_mode(draft))
    if step_index is not None and step_index != draft.step_index:
        raise StaleAction(copy.STEP_TAKEN)
    if draft.step_index >= len(steps):
        raise StaleAction(copy.NOT_TAKING_SELECTIONS)
    return steps[draft.step_index]


def _require_turn(draft: QuickDraft, step: PlanStep, user_id: int) -> str:
    side = side_for_role(step.role, draft.first_side)
    if draft.captain_id(side) != user_id:
        raise NotAllowed(copy.not_your_turn(step.action))
    return side


def available(draft: QuickDraft) -> list[int]:
    used = set(draft.actions.values_list("champion_id", flat=True))
    return [champion for champion in draft.champion_pool if champion not in used]


def _record(
    draft: QuickDraft,
    step: PlanStep,
    side: str,
    champion_id: int,
    *,
    actor_id: int | None,
    source: str,
    random_choice: bool = False,
    interaction_id: int | None = None,
) -> None:
    try:
        with transaction.atomic():
            QuickDraftAction.objects.create(
                draft=draft,
                step_index=step.index,
                action=step.action,
                side=side,
                champion_id=champion_id,
                actor_id=actor_id,
                source=source,
                random_choice=random_choice,
                interaction_id=interaction_id,
                created_at=now(),
            )
    except IntegrityError as exc:
        raise StaleAction(copy.STEP_TAKEN) from exc


def _advance(draft: QuickDraft) -> None:
    steps = champion_plan(_mode(draft))
    draft.step_index += 1
    fields = ["step_index", "deadline_at"]
    if draft.step_index >= len(steps):
        draft.status = QuickDraftStatus.COMPLETED
        draft.deadline_at = None
        draft.ended_at = now()
        fields += ["status", "ended_at"]
    else:
        draft.deadline_at = now() + timedelta(seconds=steps[draft.step_index].seconds)
    _save(draft, *fields)


@transaction.atomic
def choose_hero(
    draft_id: int,
    user_id: int,
    step_index: int,
    champion_id: int,
    interaction_id: int | None = None,
) -> None:
    draft = _lock(draft_id)
    step = _current(draft, step_index)
    side = _require_turn(draft, step, user_id)
    if champion_id not in available(draft):
        name = Champion.objects.filter(pk=champion_id).values_list("name", flat=True).first()
        raise InvalidAction(copy.hero_taken(name) if name else "That hero isn't available.")
    _record(
        draft,
        step,
        side,
        champion_id,
        actor_id=user_id,
        source="user",
        interaction_id=interaction_id,
    )
    _advance(draft)


@transaction.atomic
def choose_random(
    draft_id: int, user_id: int, step_index: int, interaction_id: int | None = None
) -> int:
    """The 🎲 Random button: the captain on turn takes a random available hero. Returns it."""
    draft = _lock(draft_id)
    step = _current(draft, step_index)
    side = _require_turn(draft, step, user_id)
    champion = auto_champion(available(draft), draft.rng_seed, step.index)
    _record(
        draft,
        step,
        side,
        champion,
        actor_id=user_id,
        source="user",
        random_choice=True,
        interaction_id=interaction_id,
    )
    _advance(draft)
    return champion


def _on_turn_timeout(draft: QuickDraft) -> None:
    """A turn ran out: a random hero, shown as "(randomed)"."""
    step = _current(draft, None)
    side = side_for_role(step.role, draft.first_side)
    champion = auto_champion(available(draft), draft.rng_seed, step.index)
    _record(draft, step, side, champion, actor_id=None, source="timeout")
    _advance(draft)


# --- Timers ---------------------------------------------------------------------------------


def fire_deadline(draft_id: int) -> bool:
    """A due turn picks at random; a draft that never started frees its channel."""
    with transaction.atomic():
        draft = _lock(draft_id)
        if (
            draft.status not in QUICK_DRAFT_LIVE
            or draft.deadline_at is None
            or draft.deadline_at > now()
        ):
            return False
        if draft.status == QuickDraftStatus.DRAFTING:
            _on_turn_timeout(draft)
        else:
            _close(draft)
            logger.info("Quick draft expired unstarted", extra={"draft": draft.pk})
        return True


def tick(moment: datetime) -> int:
    """Run due turn timers and free channels held by drafts that never got going."""
    fired = 0
    due = QuickDraft.objects.filter(status__in=QUICK_DRAFT_LIVE, deadline_at__lte=moment)
    # Only once nothing is left to post it: a first render still queued or retrying (after a
    # restart, or a Discord outage) gets its chance, and one that fails for good closes the
    # draft itself.
    waiting_renders = OutboxEffect.objects.filter(
        kind=RENDER_KIND, status=EffectStatus.PENDING, lane__startswith="quick_draft:"
    ).values_list("lane", flat=True)
    unposted = QuickDraft.objects.filter(
        status__in=QUICK_DRAFT_LIVE,
        board_message_id__isnull=True,
        created_at__lt=moment - timedelta(seconds=UNPOSTED_SECONDS),
    ).exclude(pk__in=[int(lane.split(":", 1)[1]) for lane in waiting_renders])
    for draft_id, guild_id in due.values_list("pk", "community__discord_guild_id"):
        with log_context.bind(guild=guild_id, draft=draft_id):
            fired += _fire_one(draft_id)
    for draft_id in unposted.values_list("pk", flat=True):
        try:
            close_gone(draft_id)
            logger.warning("Closed a draft that was never posted", extra={"draft": draft_id})
            fired += 1
        except Exception:
            logger.exception("Couldn't close an unposted draft", extra={"draft": draft_id})
    return fired


def _fire_one(draft_id: int) -> int:
    try:
        return 1 if fire_deadline(draft_id) else 0
    except DomainError as exc:
        logger.info("Quick draft deadline skipped", extra={"draft": draft_id, "why": exc.message})
    except Exception:
        logger.exception("Quick draft deadline failed", extra={"draft": draft_id})
    return 0


def extend_past_due(new_deadline: datetime) -> int:
    """After downtime, give a turn on the clock, or a draft waiting for captains, the same
    grace a match gets."""
    return QuickDraft.objects.filter(
        status__in=QUICK_DRAFT_LIVE, deadline_at__lt=new_deadline
    ).update(deadline_at=new_deadline)


# --- Stopping -------------------------------------------------------------------------------


@transaction.atomic
def stop(channel_id: int, user_id: int, *, staff: bool) -> None:
    """/stopdraft: the captains, whoever started it, or staff. Its messages are deleted."""
    found = live_in_channel(channel_id)
    if found is None:
        raise InvalidAction(copy.NO_DRAFT_HERE)
    draft = _lock(found.pk)
    if draft.status not in QUICK_DRAFT_LIVE:
        raise InvalidAction(copy.NO_DRAFT_HERE)
    allowed = {draft.started_by_id, draft.hk_captain_id, draft.am_captain_id}
    allowed |= {draft.coinflip_winner_id, draft.coinflip_loser_id}
    if not staff and user_id not in allowed:
        raise NotAllowed("Only the captains, whoever started it, or staff can stop this draft.")
    _close(draft)


def _close(draft: QuickDraft) -> None:
    draft.status = QuickDraftStatus.STOPPED
    draft.deadline_at = None
    draft.ended_at = now()
    draft.version += 1
    draft.save(update_fields=["status", "deadline_at", "ended_at", "version"])
    # Runs in the draft's lane after any render in flight, and reads the message IDs then, so
    # a message that render posts is deleted too.
    add_effect(draft.community, DELETE_KIND, {"draft_id": draft.pk}, lane=draft.lane)


@transaction.atomic
def close_gone(draft_id: int) -> None:
    """The draft can't be shown (its message was deleted, or the channel refused it): free the
    channel rather than leave it blocked."""
    draft = _lock(draft_id)
    if draft.status in QUICK_DRAFT_LIVE:
        _close(draft)
        logger.info("Quick draft closed: its message is gone", extra={"draft": draft.pk})


# --- Discord message bookkeeping (called by the effects) ---------------------------------------


@dataclass(frozen=True, slots=True)
class Messages:
    channel_id: int
    status: str
    board_id: int | None
    grid_ids: tuple[int | None, ...]  # One per slot, None where the slot is empty.


def messages(draft_id: int) -> Messages:
    row = QuickDraft.objects.values(
        "channel_id", "status", "board_message_id", "grid_message_ids"
    ).get(pk=draft_id)
    return Messages(
        row["channel_id"], row["status"], row["board_message_id"], tuple(row["grid_message_ids"])
    )


def record_board(draft_id: int, message_id: int | None) -> None:
    QuickDraft.objects.filter(pk=draft_id).update(board_message_id=message_id)


@transaction.atomic
def record_grid(draft_id: int, index: int, message_id: int | None) -> None:
    """Record grid message `index`, or that it's gone. Messages are kept top to bottom."""
    draft = QuickDraft.objects.select_for_update().get(pk=draft_id)
    ids: list[int | None] = list(draft.grid_message_ids)
    while len(ids) <= index:
        ids.append(None)
    ids[index] = message_id
    while ids and ids[-1] is None:
        ids.pop()  # Slots keep their places; only empty ones at the end are dropped.
    draft.grid_message_ids = ids
    draft.save(update_fields=["grid_message_ids"])


# --- Read model -----------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class HeroOption:
    id: int
    name: str
    emoji_id: int | None
    unicode_emoji: str
    taken: bool = False


@dataclass(frozen=True, slots=True)
class HeroChoice:
    action: str
    side: str
    name: str
    emoji_id: int | None
    unicode_emoji: str
    random_choice: bool
    auto: bool


@dataclass(slots=True)
class QuickDraftState:
    id: int
    status: str
    channel_id: int
    hk_captain_id: int | None
    hk_captain_name: str
    am_captain_id: int | None
    am_captain_name: str
    first_side: str
    step_index: int
    deadline_at: datetime | None
    draft_name: str
    gif_url: str | None
    custom_emojis: bool
    steps: list[tuple[str, str]] = field(default_factory=list)  # (action, side)
    actions: list[HeroChoice] = field(default_factory=list)
    # Every hero in the pool by name, taken ones marked: the grid keeps them all in place.
    heroes: list[HeroOption] = field(default_factory=list)
    coinflip_winner_id: int | None = None
    coinflip_winner_name: str = ""
    coinflip_loser_id: int | None = None
    coinflip_loser_name: str = ""
    winner_choice: str = ""
    loser_choice: str = ""
    options: tuple[str, ...] = ()

    @property
    def acting_side(self) -> str:
        if self.status != QuickDraftStatus.DRAFTING or self.step_index >= len(self.steps):
            return ""
        return self.steps[self.step_index][1]

    @property
    def step_action(self) -> str:
        if self.status != QuickDraftStatus.DRAFTING or self.step_index >= len(self.steps):
            return ""
        return self.steps[self.step_index][0]

    @property
    def available(self) -> list[HeroOption]:
        return [hero for hero in self.heroes if not hero.taken]

    def captain(self, side: str) -> tuple[int | None, str]:
        if side == Side.HIDDEN_KING:
            return self.hk_captain_id, self.hk_captain_name
        return self.am_captain_id, self.am_captain_name


def state(draft_id: int) -> QuickDraftState:
    draft = QuickDraft.objects.select_related("mode_version").get(pk=draft_id)
    steps = champion_plan(_mode(draft))
    rows = {row.pk: row for row in Champion.objects.filter(pk__in=draft.champion_pool)}
    result = QuickDraftState(
        id=draft.pk,
        status=draft.status,
        channel_id=draft.channel_id,
        hk_captain_id=draft.hk_captain_id,
        hk_captain_name=draft.hk_captain_name,
        am_captain_id=draft.am_captain_id,
        am_captain_name=draft.am_captain_name,
        first_side=draft.first_side,
        step_index=draft.step_index,
        deadline_at=draft.deadline_at,
        draft_name=draft_name(draft.rng_seed),
        gif_url=pick_gif(draft.rng_seed, draft_gifs()),
        custom_emojis=draft.custom_emojis,
        steps=[(step.action, side_for_role(step.role, draft.first_side)) for step in steps],
        coinflip_winner_id=draft.coinflip_winner_id,
        coinflip_winner_name=draft.coinflip_winner_name,
        coinflip_loser_id=draft.coinflip_loser_id,
        coinflip_loser_name=draft.coinflip_loser_name,
        winner_choice=draft.winner_choice,
        loser_choice=draft.loser_choice,
    )
    if draft.status == QuickDraftStatus.COINFLIP:
        result.options = coinflip_options(draft.winner_choice)
    used: set[int] = set()
    for action in draft.actions.order_by("step_index"):
        used.add(action.champion_id)
        row = rows.get(action.champion_id)
        result.actions.append(
            HeroChoice(
                action=action.action,
                side=action.side,
                name=row.name if row else str(action.champion_id),
                emoji_id=row.discord_emoji_id if row else None,
                unicode_emoji=row.unicode_emoji if row else "",
                random_choice=action.random_choice,
                auto=action.source == "timeout",
            )
        )
    result.heroes = sorted(
        (
            HeroOption(row.pk, row.name, row.discord_emoji_id, row.unicode_emoji, row.pk in used)
            for row in rows.values()
        ),
        key=lambda hero: hero.name,
    )
    return result


# --- /randomdraft ---------------------------------------------------------------------------


@dataclass(slots=True)
class RandomDraft:
    bans: dict[str, list[HeroOption]]
    picks: dict[str, list[HeroOption]]


def random_draft(community: Community) -> RandomDraft:
    """Bebot's /randomdraft: every ban and pick in the mode's order, chosen at random."""
    mode = parse_mode(community.active_mode.body)
    rows = {row.pk: row for row in Champion.objects.filter(pk__in=champions.draft_pool(mode))}
    pool = sorted(rows)
    rng = seeded_rng(secrets.randbits(62), "random-draft")
    result = RandomDraft(
        bans={Side.HIDDEN_KING: [], Side.ARCHMOTHER: []},
        picks={Side.HIDDEN_KING: [], Side.ARCHMOTHER: []},
    )
    for step in champion_plan(mode):
        if not pool:
            break
        row = rows[pool.pop(rng.randrange(len(pool)))]
        side = side_for_role(step.role, Side.HIDDEN_KING)
        option = HeroOption(row.pk, row.name, row.discord_emoji_id, row.unicode_emoji)
        (result.bans if step.action == "ban" else result.picks)[side].append(option)
    return result
