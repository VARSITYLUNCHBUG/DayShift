"""Lobby lifecycle before the draft: creation, ready check, the captain vote, voids, subs."""

from __future__ import annotations

import logging
import secrets
from collections.abc import Collection, Sequence

from django.db import transaction
from django.db.models import Max, Q

from league.domain import copy
from league.domain.engine import (
    LIVE,
    TERMINAL,
    CaptainCandidate,
    Status,
    first_pick_team,
    rank_captains,
    tally_captain_votes,
)
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.domain.mode_schema import parse_mode
from league.models import (
    CaptainVote,
    Community,
    Match,
    MatchParticipant,
    MatchResource,
    MatchResult,
    MatchTransition,
    Player,
    QueueEntry,
    Season,
)
from league.models.alerts import AlertKind
from league.models.matches import RemovedReason, ResourceKind, Source
from league.models.moderation import PenaltyKind
from league.models.permissions import Area
from league.models.subs import SubReason
from league.services import alerts, champions, effects, penalties, prio, runtime, standing
from league.services.common import (
    add_effect,
    clear_notices,
    close_subs,
    lock_community,
    now,
    render_board,
    render_queue,
    seconds_from_now,
    transition,
)

logger = logging.getLogger(__name__)


def create_match(community: Community, entries: Sequence[QueueEntry]) -> Match | None:
    """Turn the front of the queue into a lobby. Caller holds the community lock."""
    mode = parse_mode(community.active_mode.body)
    pool = champions.draft_pool(mode)
    if len(pool) < mode.champions_consumed_max:
        logger.error(
            "Queue full but champion pool too small",
            extra={"pool": len(pool), "needed": mode.champions_consumed_max},
        )
        return None

    moment = now()
    match = Match.objects.create(
        community=community,
        season=Season.objects.open_for(community),
        mode_version=community.active_mode,
        status=Status.READY_CHECK,
        deadline_at=seconds_from_now(mode.ready_check.seconds),
        rng_seed=secrets.randbits(62),
        champion_pool=pool,
        created_at=moment,
    )
    MatchTransition.objects.create(
        match=match, to_status=Status.READY_CHECK, source=Source.SYSTEM, created_at=moment
    )
    MatchParticipant.objects.bulk_create(
        MatchParticipant(match=match, player=entry.player, queue_joined_at=entry.joined_at)
        for entry in entries
    )
    QueueEntry.objects.filter(pk__in=[entry.pk for entry in entries]).delete()
    _matched(community, [entry.player for entry in entries])

    add_effect(community, "create_lobby", match=match, dedupe_key=f"create_lobby:{match.pk}")
    # The board goes up straight after the channel and its ping, ahead of the twelve invites and
    # DMs, so nobody sits looking at a ping with no Ready button under it.
    render_board(match)
    for entry in entries:
        _gather(match, entry.player)
    render_queue(community)
    logger.info("Lobby created", extra={"match": match.pk})
    return match


def _matched(community: Community, players: Sequence[Player]) -> None:
    """They're in a match now: off the priority list. Every way into a match calls this."""
    prio.drop_players(community.pk, [player.discord_user_id for player in players])


def _gather(match: Match, player: Player, *, sub: bool = False) -> None:
    """Get them into voice. A sub joins mid-match, so they go to their team's channel if it's up."""
    add_effect(
        match.community,
        "gather_player",
        {"player_id": player.pk, "discord_user_id": player.discord_user_id, "sub": sub},
        match=match,
        dedupe_key=f"gather:{match.pk}:{player.pk}",
    )


# --- Ready check -----------------------------------------------------------------------------


@transaction.atomic
def mark_ready(match_id: int, player: Player) -> None:
    match = Match.objects.lock(match_id)
    if match.status != Status.READY_CHECK:
        raise StaleAction("The ready check has already finished.")
    match.require_not_on_hold()
    participant = match.require_participant(player)
    if participant.ready_at is not None:
        raise InvalidAction(copy.ALREADY_READY)
    participant.ready_at = now()
    participant.save(update_fields=["ready_at"])
    if participant.ready_dm_message_id is not None:
        add_effect(
            match.community,
            "ready_dm_done",
            {
                "discord_user_id": player.discord_user_id,
                "message_id": participant.ready_dm_message_id,
            },
            match=match,
        )
    match.bump()
    if match.participants.active().filter(ready_at__isnull=True).exists():
        # The board shows who's ready. The ping isn't edited: an edit notifies nobody, and
        # twelve of them in seconds only spent the channel's rate limit.
        render_board(match)
    else:
        begin_captain_phase(match)


def on_ready_timeout(match: Match) -> None:
    """Take out everyone who missed it, and offer their spots: the priority list first, then the
    queue. The lobby waits for them; unfilled after `refill_seconds`, it's cancelled."""
    from league.services import subs

    community = lock_community(match.community_id)
    mode = match.mode
    missed = list(match.participants.active().filter(ready_at__isnull=True))
    if not missed:
        begin_captain_phase(match)
        return

    moment = now()
    for participant in missed:
        participant.is_active = False
        participant.removed_reason = RemovedReason.MISSED_READY
        participant.removed_at = moment
        participant.save(update_fields=["is_active", "removed_reason", "removed_at"])
        penalties.issue(
            community,
            participant.player,
            PenaltyKind.MISSED_READY,
            match=match,
            reason=f"Missed the ready check for match #{match.pk}",
        )

    for participant in missed:
        add_effect(
            community,
            "remove_player",
            {"discord_user_id": participant.player.discord_user_id},
            match=match,
        )
    subs.open_openings(match, mode, [participant.player for participant in missed])
    effects.request_ready_ping(match)
    render_queue(community)


def add_player(match: Match, player: Player) -> None:
    """Someone accepted an open spot in the ready check: they're in, and ready. The caller holds
    the match lock and has checked they're free."""
    community = lock_community(match.community_id)
    entry = QueueEntry.objects.filter(community=community, player=player).first()
    MatchParticipant.objects.create(
        match=match,
        player=player,
        queue_joined_at=entry.joined_at if entry else now(),
        ready_at=now(),  # Accepting means they're here.
    )
    QueueEntry.objects.filter(community=community, player=player).delete()
    add_effect(community, "grant_access", {"discord_user_id": player.discord_user_id}, match=match)
    _gather(match, player, sub=True)  # Accepting made them ready: a voice invite, no Ready.
    _matched(community, [player])
    render_queue(community)


# --- Captain vote ----------------------------------------------------------------------------

VOTES_PER_PLAYER = 2


def _eligibility(match: Match, player_ids: Collection[int]) -> dict[int, standing.PlayerStanding]:
    return standing.eligibility(match.community, match.mode, player_ids)


def begin_captain_phase(match: Match) -> None:
    """Everyone is ready: open the captain vote. With Auto Captain on (a runtime setting), or two
    or fewer players able to captain, there is nothing to vote on, so captains are appointed
    straight away: the eligible first, then by experience and rating."""
    mode = match.mode
    transition(
        match,
        Status.CAPTAIN_PHASE,
        source=Source.SYSTEM,
        deadline_at=seconds_from_now(mode.captains.vote_seconds),
    )
    match.save_transition()
    active = list(match.participants.active())
    allowed = _eligibility(match, [p.player_id for p in active])
    auto = runtime.of(match.community_id).auto_captain
    if auto or sum(row.eligibility.ok for row in allowed.values()) <= 2:
        _close_vote(match, Source.SYSTEM)
        return
    ids = [p.player.discord_user_id for p in active]
    note = (
        f" Only players with {mode.captains.min_games} completed matches can captain."
        if mode.captains.min_games
        else ""
    )
    add_effect(
        match.community,
        "ping",
        {
            "user_ids": ids,
            "text": f"everyone's ready. Vote for up to two captains on the board.{note}",
        },
        match=match,
    )
    render_board(match)


@transaction.atomic
def cast_captain_votes(match_id: int, player: Player, candidate_ids: Sequence[int]) -> list[Player]:
    """Replace this player's captain votes. Returns who they voted for."""
    match = Match.objects.lock(match_id)
    if match.status != Status.CAPTAIN_PHASE:
        raise StaleAction("The captain vote has finished.")
    match.require_not_on_hold()
    match.require_participant(player)
    chosen = list(dict.fromkeys(candidate_ids))
    if not chosen:
        raise InvalidAction("Choose at least one player.")
    if len(chosen) > VOTES_PER_PLAYER:
        raise InvalidAction(f"You can vote for up to {VOTES_PER_PLAYER} players.")
    candidates = {p.player_id: p.player for p in match.participants.active()}
    if any(candidate_id not in candidates for candidate_id in chosen):
        raise InvalidAction("You can only vote for players in this lobby.")
    for candidate_id, row in _eligibility(match, chosen).items():
        if not row.eligibility.ok:
            name = candidates[candidate_id].display_name
            raise InvalidAction(f"{name} can't captain yet ({row.eligibility.reason}).")
    match.captain_votes.filter(voter=player).delete()
    moment = now()
    CaptainVote.objects.bulk_create(
        CaptainVote(match=match, voter=player, candidate_id=candidate_id, created_at=moment)
        for candidate_id in chosen
    )
    match.bump()
    advance_captain_phase(match)
    return [candidates[candidate_id] for candidate_id in chosen]


def _everyone_voted(match: Match) -> bool:
    voters = set(match.captain_votes.values_list("voter_id", flat=True))
    return all(p.player_id in voters for p in match.participants.active())


def advance_captain_phase(match: Match) -> None:
    """Close the vote once everyone still in the lobby has voted."""
    if match.on_hold or not _everyone_voted(match):  # A sub picks it up again on arrival.
        render_board(match)
        return
    _close_vote(match, Source.USER)


def on_captain_timeout(match: Match) -> None:
    """Count the votes cast so far. Rating fills any gap."""
    _close_vote(match, Source.TIMEOUT)


def vote_counts(match: Match) -> dict[int, int]:
    """Votes per player, counting only voters and candidates still in the lobby."""
    active = set(match.participants.active().values_list("player_id", flat=True))
    counts: dict[int, int] = {}
    for vote in match.captain_votes.filter(voter_id__in=active, candidate_id__in=active):
        counts[vote.candidate_id] = counts.get(vote.candidate_id, 0) + 1
    return counts


def _candidates(match: Match, participants: Sequence[MatchParticipant]) -> list[CaptainCandidate]:
    allowed = _eligibility(match, [p.player_id for p in participants])
    candidates = []
    for participant in participants:
        _rating, games = match.season.rating_of(participant.player_id)
        row = allowed[participant.player_id]
        candidates.append(
            CaptainCandidate(
                participant.player_id,
                match.season.strength_of(participant.player_id),
                games,
                eligible=row.eligibility.ok,
                experience=row.eligibility.games,
            )
        )
    return candidates


def _close_vote(match: Match, source: str) -> None:
    participants = list(match.participants.active())
    counts = vote_counts(match)
    captain_a, captain_b = tally_captain_votes(
        counts, _candidates(match, participants), match.rng_seed
    )
    for participant in participants:
        if participant.player_id in {captain_a, captain_b}:
            participant.is_captain = True
            participant.team = "A" if participant.player_id == captain_a else "B"
            participant.save(update_fields=["is_captain", "team"])
    begin_captain_checkin(match, source=source)


# --- Captain check-in ------------------------------------------------------------------------


def _captains(match: Match) -> list[MatchParticipant]:
    return list(match.participants.active().filter(is_captain=True).order_by("team"))


def _ping_captains(match: Match, captains: Sequence[MatchParticipant], text: str) -> None:
    add_effect(
        match.community,
        "ping",
        {"user_ids": [p.player.discord_user_id for p in captains], "text": text},
        match=match,
    )


CHECKIN_PING = "you're captain. Press **I'm here** on the board to start the player draft."
# Both captains at once: one line that reads right to two people.
CHECKIN_PING_BOTH = (
    "you're the captains. Each press **I'm here** on the board to start the player draft."
)


def begin_captain_checkin(match: Match, source: str) -> None:
    """Captains are chosen: each confirms they're here before anyone is drafted."""
    mode = match.mode
    transition(
        match,
        Status.CAPTAIN_CHECKIN,
        source=source,
        deadline_at=seconds_from_now(mode.captains.checkin_seconds),
    )
    match.save_transition()
    captains = _captains(match)
    _ping_captains(match, captains, CHECKIN_PING_BOTH if len(captains) > 1 else CHECKIN_PING)
    render_board(match)


@transaction.atomic
def check_in(match_id: int, player: Player) -> None:
    """A captain's I'm here."""
    match = Match.objects.lock(match_id)
    if match.status != Status.CAPTAIN_CHECKIN:
        raise StaleAction("The captain check-in has finished.")
    match.require_not_on_hold()
    participant = match.require_participant(player)
    if not participant.is_captain:
        raise NotAllowed("Only the captains check in. The board shows who they are.")
    if participant.checked_in_at is not None:
        raise InvalidAction("You've already checked in. The draft starts once both captains have.")
    participant.checked_in_at = now()
    participant.save(update_fields=["checked_in_at"])
    match.bump()
    advance_checkin(match)


def advance_checkin(match: Match) -> None:
    """Start the player draft once every captain has checked in."""
    if match.on_hold or any(p.checked_in_at is None for p in _captains(match)):
        render_board(match)
        return
    begin_player_draft(match, source=Source.USER)


def on_checkin_timeout(match: Match) -> None:
    """A captain who didn't check in is replaced by the next eligible player in captain order,
    who gets the full time. With nobody left to ask, the draft starts with the captains it has."""
    participants = list(match.participants.active())
    absent = [p for p in participants if p.is_captain and p.checked_in_at is None]
    taken = {p.player_id for p in participants if p.is_captain or p.missed_checkin}
    pool = [p for p in participants if p.player_id not in taken]
    candidates = [c for c in _candidates(match, pool) if c.eligible]
    order = rank_captains(vote_counts(match), candidates, match.rng_seed)
    by_id = {p.player_id: p for p in pool}
    replaced = []
    for missing in absent:
        if not order:
            break
        heir = by_id[order.pop(0)]
        heir.is_captain = True
        heir.team = missing.team
        heir.save(update_fields=["is_captain", "team"])
        missing.is_captain = False
        missing.team = ""
        missing.missed_checkin = True
        missing.save(update_fields=["is_captain", "team", "missed_checkin"])
        replaced.append((missing, heir))
    if not replaced:
        begin_player_draft(match, source=Source.TIMEOUT)
        return
    match.deadline_at = seconds_from_now(match.mode.captains.checkin_seconds)
    match.bump("deadline_at")
    clear_notices(match)  # The old captains' ping no longer applies.
    for missing, heir in replaced:
        _ping_captains(
            match,
            [heir],
            f"**{missing.player.display_name}** didn't check in, so {CHECKIN_PING}",
        )
    render_board(match)


def begin_player_draft(match: Match, source: str) -> None:
    mode = match.mode
    rating_a = match.season.strength_of(match.captain_of("A").player_id)
    rating_b = match.season.strength_of(match.captain_of("B").player_id)
    match.player_first_pick = first_pick_team(rating_a, rating_b, match.rng_seed)
    match.step_index = 0
    transition(
        match,
        Status.PLAYER_DRAFT,
        source=source,
        deadline_at=seconds_from_now(mode.player_draft.seconds),
    )
    match.save_transition("player_first_pick", "step_index")
    render_board(match)


# --- Voids and substitutes -------------------------------------------------------------------


def next_revision(match: Match) -> int:
    latest = match.results.aggregate(latest=Max("revision"))["latest"]
    return (latest or 0) + 1


def void_live(
    match: Match,
    *,
    source: str,
    reason: str,
    actor: Player | None = None,
    requeue: bool = False,
    skip_requeue: Collection[int] = (),
    cleanup: bool = True,
) -> None:
    """End a live match with no rating change. Caller holds the match lock.

    `skip_requeue` holds player IDs that must not go back in line, such as someone subbing out.
    `cleanup` False leaves its channels alone, for a restart that takes them over.
    """
    community = lock_community(match.community_id)
    moment = now()
    close_subs(match)
    MatchResult.objects.create(
        match=match,
        revision=next_revision(match),
        outcome="void",
        source=source,
        actor=actor,
        reason=reason[:500],
        created_at=moment,
    )
    active = list(match.participants.active())
    if requeue:
        places = []
        for participant in active:
            if participant.ready_at is not None and participant.player_id not in skip_requeue:
                # Keeping the original time puts them ahead of everyone who joined later.
                # They just readied, so the idle clock starts again.
                _entry, created = QueueEntry.objects.get_or_create(
                    community=community,
                    player=participant.player,
                    defaults={"joined_at": participant.queue_joined_at, "active_at": moment},
                )
                if created:
                    places.append((participant.player, participant.queue_joined_at))
        prio.requeued(community.pk, places)
    match.participants.filter(is_active=True).update(is_active=False)
    alerts.settle_for_match(
        match, (AlertKind.DISPUTE, AlertKind.EARLY_LEAVE), actor, f"Voided: {reason}"
    )
    transition(match, Status.VOIDED, source=source, actor=actor)
    match.ended_at = moment
    match.save_transition("ended_at")
    add_effect(community, "ping_lobby", {"text": f"Match cancelled: {reason}"}, match=match)
    if cleanup:
        schedule_cleanup(match)
    render_board(match)
    render_queue(community)
    logger.info("Match voided", extra={"match": match.pk, "reason": reason})


# A restart's successor takes these over; the old match's team voices go back to the lobby.
HANDED_OVER = (
    ResourceKind.TEXT,
    ResourceKind.BOARD_MESSAGE,
    ResourceKind.PICKER_MESSAGE,
    ResourceKind.PICKER_MESSAGE_2,
    ResourceKind.NOTICE,  # So the successor's first status change clears them.
)


def restart(match: Match, *, leaving: Collection[int]) -> Match:
    """Captains were set, then someone left and nobody took their seat before the game. Keep the
    lobby together: a successor match takes over the channels and everyone who stayed, offers the
    empty seats, and runs a fresh captain vote once they're filled. The old match is voided; its
    draft history is append-only and stays exactly as it was. Caller holds the match lock."""
    from league.services import subs

    community = lock_community(match.community_id)
    mode = match.mode
    stayed = [p for p in match.participants.active() if p.player_id not in leaving]
    gone = list(Player.objects.filter(pk__in=list(leaving)))
    names = ", ".join(player.display_name for player in gone)
    void_live(
        match,
        source=Source.TIMEOUT,
        reason=f"Restarting: {names} left before the game",
        cleanup=False,
    )
    successor = Match.objects.create(
        community=community,
        season=match.season,
        mode_version=match.mode_version,
        status=Status.READY_CHECK,
        rng_seed=secrets.randbits(62),
        champion_pool=champions.draft_pool(mode),
        restarted_from=match,
        created_at=now(),
    )
    # The same transaction, so nothing queued for the old match can lose track of a channel.
    MatchResource.objects.filter(match=match, kind__in=HANDED_OVER, deleted_at__isnull=True).update(
        match=successor
    )
    # The old match's pings (such as "the player draft is on") no longer apply: clear them
    # before the successor posts its own.
    clear_notices(successor)
    moment = now()
    for participant in stayed:
        MatchParticipant.objects.create(
            match=successor,
            player=participant.player,
            queue_joined_at=participant.queue_joined_at,
            ready_at=moment,  # They're here: they stayed.
        )
    effects.cancel_voice_setup(match.pk)  # The successor takes the voice over as it is.
    add_effect(community, "restart_voice", {"old_id": match.pk}, match=successor)
    subs.open_openings(successor, mode, gone, reason=SubReason.RESTART)
    _matched(community, [participant.player for participant in stayed])
    logger.info("Match restarted", extra={"match": match.pk, "successor": successor.pk})
    return successor


def schedule_cleanup(match: Match) -> None:
    community = match.community
    effects.queue_voice_cleanup(match)
    add_effect(
        community,
        "delete_text_channel",
        match=match,
        dedupe_key=f"delete_text:{match.pk}",
        # The text channel stays a little while for last words and disputes.
        run_after=seconds_from_now(runtime.of(match.community_id).match_channel_close_minutes * 60),
    )


@transaction.atomic
def staff_void(match_id: int, actor: Player | None, reason: str) -> None:
    match = Match.objects.lock(match_id)
    if match.status in TERMINAL:
        raise InvalidAction(
            "That match has finished. Use /match void or /match rescore to change it."
        )
    void_live(match, source=Source.STAFF, actor=actor, reason=reason)


def check_sub_is_free(match: Match, in_player: Player) -> None:
    if MatchParticipant.objects.filter(player=in_player, is_active=True).exists():
        raise InvalidAction(f"{in_player.display_name} is already in a live match.")
    if match.participants.filter(player=in_player).exists():
        raise InvalidAction(f"{in_player.display_name} was already part of this match.")


def _captaincy_heir(
    match: Match, leaving: MatchParticipant, in_player: Player
) -> MatchParticipant | None:
    """Who takes over from a captain subbing out, when their sub can't captain. The eligible
    teammate with the most completed matches, then rating. None means the sub takes it: either
    they can captain, or nobody else on the team can."""
    teammates = list(
        match.participants.active()
        .filter(team=leaving.team, is_captain=False)
        .exclude(pk=leaving.pk)
        .select_related("player")
    )
    allowed = _eligibility(match, [in_player.pk, *(p.player_id for p in teammates)])
    if allowed[in_player.pk].eligibility.ok:
        return None
    able = [p for p in teammates if allowed[p.player_id].eligibility.ok]
    if not able:
        return None

    def rank(participant: MatchParticipant) -> tuple[int, int, int]:
        strength = match.season.strength_of(participant.player_id)
        return (-allowed[participant.player_id].eligibility.games, -strength, participant.player_id)

    return min(able, key=rank)


def swap_player(match: Match, leaving: MatchParticipant, in_player: Player, *, ready: bool) -> None:
    """Put the substitute in the leaving player's place: team, role, draft slot and the result.

    The caller holds the match lock and has checked the substitute is free.
    """
    moment = now()
    community = lock_community(match.community_id)
    QueueEntry.objects.filter(community=community, player=in_player).delete()
    _matched(community, [in_player])
    heir = _captaincy_heir(match, leaving, in_player) if leaving.is_captain else None
    MatchParticipant.objects.create(
        match=match,
        player=in_player,
        queue_joined_at=leaving.queue_joined_at,
        ready_at=moment if ready else None,
        team=leaving.team,
        is_captain=leaving.is_captain and heir is None,
        draft_pick_number=leaving.draft_pick_number,
    )
    leaving.is_active = False
    leaving.is_captain = False
    leaving.removed_reason = RemovedReason.SUBBED_OUT
    leaving.removed_at = moment
    leaving.save(update_fields=["is_active", "is_captain", "removed_reason", "removed_at"])
    if heir is not None:
        heir.is_captain = True
        heir.save(update_fields=["is_captain"])
        teammates = match.participants.active().filter(team=heir.team).select_related("player")
        add_effect(
            community,
            "ping",
            {
                "user_ids": [p.player.discord_user_id for p in teammates],
                "text": f"**{heir.player.display_name}** is your captain now: "
                f"{in_player.display_name} can't captain yet.",
            },
            match=match,
        )
    # Their votes, and votes for them, no longer count. The sub gets a vote of their own.
    match.captain_votes.filter(
        Q(voter_id=leaving.player_id) | Q(candidate_id=leaving.player_id)
    ).delete()
    if match.lobby_code_host_id == leaving.player_id:
        match.lobby_code_host = in_player
        match.bump("lobby_code_host")
    else:
        match.bump()
    add_effect(
        community, "remove_player", {"discord_user_id": leaving.player.discord_user_id}, match=match
    )
    add_effect(
        community, "grant_access", {"discord_user_id": in_player.discord_user_id}, match=match
    )
    _gather(match, in_player, sub=True)
    render_board(match)
    render_queue(community)


@transaction.atomic
def substitute_live(
    match_id: int, out_player: Player, in_player: Player, actor: Player | None
) -> None:
    """Staff swap a player in a live match. The substitute takes their team, role and the result."""
    from league.services import subs  # Avoids a cycle: subs builds on this module.

    match = Match.objects.lock(match_id)
    if match.status not in LIVE:
        raise InvalidAction("That match isn't live.")
    leaving = match.participants.filter(player=out_player, is_active=True).first()
    if leaving is None:
        raise InvalidAction(f"{out_player.display_name} isn't active in this match.")
    check_sub_is_free(match, in_player)
    swap_player(match, leaving, in_player, ready=leaving.ready_at is not None)
    subs.after_staff_swap(match, out_player)


def fail_lobby_setup(match_id: int, reason: str) -> None:
    """Discord refused to create the lobby for good: cancel and put players back in line."""
    with transaction.atomic():
        match = Match.objects.lock(match_id)
        if match.status in LIVE:
            match.participants.filter(is_active=True, ready_at__isnull=True).update(ready_at=now())
            void_live(match, source=Source.SYSTEM, reason=reason, requeue=True)
            alerts.raise_alert(
                match.community,
                AlertKind.LOBBY_FAILED,
                Area.SETUP,
                f"{reason}, so it was cancelled and its players went back in the queue. Check "
                "the bot can Manage Channels and Manage Roles in the match category.",
                match=match,
                dedupe_key=f"lobby_failed:{match.pk}",
            )
