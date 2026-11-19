"""Scrims: Bebot's /startdraft and /captains_coinflip, as matches of their own kind.

A scrim is a Match with kind=scrim, run in the public channel it was started in. It goes through
the same engine as a ranked match: the same captain coinflip, the same champion draft, the same
row lock, append-only draft rows and timers. Only the way in differs (two captains claim a side,
or a coinflip settles it and a captain presses Start Draft), and it ends at GLHF. It's recorded,
never rated: scrims never complete, and their captains are inactive participants, so they can
queue and play ranked at the same time.
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import timedelta

from django.db import IntegrityError, transaction

from league.domain import copy
from league.domain.draft_plan import champion_plan, player_draft_length, team_for_role
from league.domain.engine import SCRIM_LIVE, SIDE_LABELS, Status, seeded_rng
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import parse_mode
from league.models import Champion, Community, Match, MatchParticipant, OutboxEffect, Player, Season
from league.models.matches import MatchKind, ResourceKind, Source
from league.models.outbox import EffectStatus
from league.services import champions, draft
from league.services.common import (
    add_effect,
    lock_community,
    now,
    render_board,
    transition,
)

logger = logging.getLogger(__name__)

# A server can have this many scrims going at once, across all its channels.
MAX_LIVE_SCRIMS = 10
# A scrim nobody starts (captains unclaimed, coinflip unanswered) frees its channel after this.
IDLE_SECONDS = 15 * 60
# The first render posts the board. One still without a board after this never got posted (the
# channel refused it, say), so it frees the channel.
UNPOSTED_SECONDS = 5 * 60
# Each side's team: The Hidden King is always team A in a scrim.
SIDE_TEAM = {"hk": "A", "am": "B"}
DELETE_KIND = "delete_board"


def live_in_channel(channel_id: int) -> Match | None:
    return Match.objects.filter(
        kind=MatchKind.SCRIM, host_channel_id=channel_id, status__in=SCRIM_LIVE
    ).first()


def is_host_channel(channel_id: int) -> bool:
    """A public channel a scrim was run in. The bot never deletes one."""
    return Match.objects.filter(kind=MatchKind.SCRIM, host_channel_id=channel_id).exists()


def _lock_scrim(match_id: int) -> Match:
    match = Match.objects.lock(match_id)
    if match.kind != MatchKind.SCRIM:
        raise StaleAction("That isn't a scrim.")
    return match


# --- Starting -------------------------------------------------------------------------------


def _create(
    community_id: int,
    channel_id: int,
    starter: Player,
    *,
    status: str,
    custom_emojis: bool,
    **fields: object,
) -> Match:
    community = lock_community(community_id)  # Serialises the per-server cap.
    if live_in_channel(channel_id) is not None:
        raise InvalidAction(copy.DRAFT_RUNNING_HERE)
    live = Match.objects.filter(
        community=community, kind=MatchKind.SCRIM, status__in=SCRIM_LIVE
    ).count()
    if live >= MAX_LIVE_SCRIMS:
        raise InvalidAction(
            f"This server already has {MAX_LIVE_SCRIMS} drafts running. Finish or stop one first."
        )
    mode_version = community.active_mode
    mode = parse_mode(mode_version.body)
    pool = champions.draft_pool(mode)
    if len(pool) < len(champion_plan(mode)):
        raise InvalidAction("Not enough heroes are enabled to run a draft.")
    moment = now()
    try:
        with transaction.atomic():
            match = Match.objects.create(
                community=community,
                season=Season.objects.open_for(community),
                mode_version=mode_version,
                kind=MatchKind.SCRIM,
                status=status,
                host_channel_id=channel_id,
                custom_emojis=custom_emojis,
                started_by=starter,
                # Scrims skip the player draft: the champion draft's steps follow on from it.
                step_index=player_draft_length(mode),
                rng_seed=secrets.randbits(62),
                champion_pool=pool,
                deadline_at=moment + timedelta(seconds=IDLE_SECONDS),
                created_at=moment,
                **fields,
            )
    except IntegrityError as exc:  # Another /startdraft in this channel won the race.
        raise InvalidAction(copy.DRAFT_RUNNING_HERE) from exc
    render_board(match)
    logger.info("Scrim started", extra={"match": match.pk, "channel": channel_id})
    return match


def _add_captain(match: Match, player: Player, team: str) -> None:
    # Not active: a scrim never holds anyone, so its captains can still queue for ranked.
    MatchParticipant.objects.create(
        match=match,
        player=player,
        queue_joined_at=now(),
        team=team,
        is_captain=True,
        is_active=False,
    )


@transaction.atomic
def start_claim(
    community_id: int, channel_id: int, starter: Player, *, custom_emojis: bool = True
) -> Match:
    """/startdraft: two Become Captain buttons. The Hidden King bans and picks first."""
    return _create(
        community_id,
        channel_id,
        starter,
        status=Status.CAPTAIN_CLAIM,
        custom_emojis=custom_emojis,
        hidden_king_team="A",
        champion_first_pick="A",
    )


@transaction.atomic
def start_coinflip(
    community_id: int,
    channel_id: int,
    starter: Player,
    first: Player,
    second: Player,
    *,
    custom_emojis: bool = True,
) -> Match:
    """/captains_coinflip: flip between two captains. The winner chooses first, then a captain
    presses Start Draft."""
    if first.pk == second.pk:
        raise InvalidAction(copy.SAME_PLAYER_COINFLIP)
    match = _create(
        community_id,
        channel_id,
        starter,
        status=Status.COINFLIP,
        custom_emojis=custom_emojis,
        coinflip_winner="A" if secrets.randbelow(2) == 0 else "B",
    )
    _add_captain(match, first, "A")
    _add_captain(match, second, "B")
    return match


# --- Captains and Start Draft -------------------------------------------------------------------


@transaction.atomic
def claim_captain(match_id: int, player: Player, side: str) -> str:
    """A Become Captain button. Returns the side's name. Both claimed starts the draft."""
    match = _lock_scrim(match_id)
    if match.status != Status.CAPTAIN_CLAIM:
        raise StaleAction(copy.CAPTAINS_CHOSEN)
    if side not in SIDE_TEAM:
        raise InvalidAction("That isn't a side.")
    team, label = SIDE_TEAM[side], SIDE_LABELS[side]
    captains = {row.team: row.player_id for row in match.participants.filter(is_captain=True)}
    if captains.get(team) == player.pk:
        raise InvalidAction(copy.already_captain(label))
    if player.pk in captains.values():
        raise InvalidAction(copy.CANT_CAPTAIN_BOTH)
    if team in captains:
        raise InvalidAction(copy.has_captain(label))
    _add_captain(match, player, team)
    if len(captains) + 1 == 2:
        _begin(match, source=Source.USER, actor=player)
    else:
        match.bump()
        render_board(match)
    return label


@transaction.atomic
def start_draft(match_id: int, player: Player) -> None:
    """Bebot's Start Draft button, once both captains have made their coinflip choices."""
    match = _lock_scrim(match_id)
    if match.status != Status.READY_TO_DRAFT:
        raise StaleAction("This draft has already started.")
    if not match.participants.filter(player=player, is_captain=True).exists():
        raise NotAllowed(copy.ONLY_CAPTAINS_START)
    _begin(match, source=Source.USER, actor=player)


def _begin(match: Match, *, source: str, actor: Player | None) -> None:
    draft.begin_champion_draft(match, match.mode, source=source, actor=actor)


# --- Timers, the end and stopping ------------------------------------------------------------


def on_timeout(match: Match) -> None:
    """A turn ran out (a random hero), or nobody got the scrim going (it frees the channel)."""
    if match.status == Status.CHAMPION_DRAFT:
        draft.on_champion_draft_timeout(match)
        return
    _end(match, Status.VOIDED, source=Source.TIMEOUT)
    logger.info("Scrim expired unstarted", extra={"match": match.pk})


def finish(match: Match) -> None:
    """The last ban or pick is in: GLHF. Called by the champion draft, under the match lock."""
    _end(match, Status.DRAFTED, source=Source.SYSTEM)


def _end(match: Match, status: str, *, source: str, actor: Player | None = None) -> None:
    transition(match, status, source=source, actor=actor, deadline_at=None)
    match.ended_at = now()
    match.save_transition("ended_at", "step_index")
    if status == Status.VOIDED:
        # Bebot removed a stopped draft. This runs in the match's lane after any render in
        # flight, and reads the message IDs then, so a message that render posts goes too.
        add_effect(match.community, DELETE_KIND, match=match)
    else:
        render_board(match)


@transaction.atomic
def stop(channel_id: int, actor: Player) -> None:
    """/stopdraft. Its messages are deleted."""
    found = live_in_channel(channel_id)
    if found is None:
        raise InvalidAction(copy.NO_DRAFT_HERE)
    match = _lock_scrim(found.pk)
    if match.status not in SCRIM_LIVE:
        raise InvalidAction(copy.NO_DRAFT_HERE)
    _end(match, Status.VOIDED, source=Source.STAFF, actor=actor)


@transaction.atomic
def close_gone(match_id: int) -> None:
    """The scrim can't be shown (its channel is gone, or refused the bot): free the channel
    rather than leave it blocked."""
    match = Match.objects.lock(match_id)
    if match.kind == MatchKind.SCRIM and match.status in SCRIM_LIVE:
        _end(match, Status.VOIDED, source=Source.SYSTEM)
        logger.info("Scrim closed: its board is gone", extra={"match": match.pk})


def tick() -> int:
    """Free channels held by scrims whose first post never landed. Only once nothing is left to
    post it: a first render still queued or retrying (after a restart, or a Discord outage) gets
    its chance, and one that fails for good closes the scrim itself."""
    cutoff = now() - timedelta(seconds=UNPOSTED_SECONDS)
    waiting = OutboxEffect.objects.filter(
        kind="render_board", status=EffectStatus.PENDING, match__kind=MatchKind.SCRIM
    ).values_list("match_id", flat=True)
    unposted = (
        Match.objects.filter(kind=MatchKind.SCRIM, status__in=SCRIM_LIVE, created_at__lt=cutoff)
        .exclude(resources__kind=ResourceKind.BOARD_MESSAGE)
        .exclude(pk__in=list(waiting))
    )
    closed = 0
    for match_id in unposted.values_list("pk", flat=True):
        try:
            close_gone(match_id)
            logger.warning("Closed a scrim that was never posted", extra={"match": match_id})
            closed += 1
        except Exception:
            logger.exception("Couldn't close an unposted scrim", extra={"match": match_id})
    return closed


# --- /randomdraft ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RandomHero:
    name: str
    unicode_emoji: str


@dataclass(slots=True)
class RandomDraft:
    bans: dict[str, list[RandomHero]]
    picks: dict[str, list[RandomHero]]


def random_draft(community: Community) -> RandomDraft:
    """Bebot's /randomdraft: every ban and pick in the mode's order, chosen at random. Nothing
    is recorded."""
    mode = parse_mode(community.active_mode.body)
    rows = {row.pk: row for row in Champion.objects.filter(pk__in=champions.draft_pool(mode))}
    pool = sorted(rows)
    rng = seeded_rng(secrets.randbits(62), "random-draft")
    result = RandomDraft(bans={"hk": [], "am": []}, picks={"hk": [], "am": []})
    for step in champion_plan(mode):
        if not pool:
            break
        row = rows[pool.pop(rng.randrange(len(pool)))]
        side = "hk" if team_for_role(step.role, "A") == "A" else "am"
        hero = RandomHero(row.name, row.unicode_emoji)
        (result.bans if step.action == "ban" else result.picks)[side].append(hero)
    return result
