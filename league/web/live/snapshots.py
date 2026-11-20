"""The snapshots the websocket sends: whole state, never a diff.

Each builder reads in one REPEATABLE READ, READ ONLY transaction, so a snapshot is one consistent
view even while the bot writes. They call the same read models the Discord boards use
(`league.services.boards`), so the web and Discord never disagree.

A match is built once per change (`build_match`) and projected per viewer (`project_match`),
which fills in `viewer`, hides the lobby code from anyone not on the roster, and adds whatever
only the viewer's team may see (`MatchBody.by_team`).
"""

from __future__ import annotations

import importlib
from collections.abc import Callable, Iterable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, cast

from django.conf import settings
from django.db import connection, transaction
from django.db.models import F, Q

from league.domain.engine import SCRIM_LIVE, TIMED, Status, draft_name
from league.domain.mode_schema import parse_mode
from league.models import (
    CaptainVote,
    Champion,
    Community,
    Match,
    MatchParticipant,
    MatchResult,
    Player,
    PlayerMatchStat,
    QueueEntry,
    ResultSubmission,
    SteamAccount,
)
from league.models.matches import MatchKind
from league.models.subs import UNRESOLVED, OfferSource, OfferStatus, SubOffer, SubRequest, SubStatus
from league.services import (
    boards,
    community,
    leaderboards,
    lobby,
    ocr,
    penalties,
    prio,
    queue,
    runtime,
    standing,
)
from league.web import heroes
from league.web.live import schema as s
from league.web.text import plain

AVATAR_SIZE = 64  # Pixels. Every face the web shows is small; the CDN scales.
# A match a player has reported in is over for them (they can queue again), but it's still
# theirs until the result is settled.
SETTLING = frozenset({Status.AWAITING_CONFIRMATION, Status.DISPUTED})


@contextmanager
def consistent() -> Iterator[None]:
    """One snapshot, one view of the database.

    Inside a transaction someone else opened (a test, say) the isolation level can no longer be
    set, so the snapshot shares that transaction's view instead.
    """
    if connection.in_atomic_block:
        with transaction.atomic():
            yield
        return
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        yield


def web_community_id() -> int | None:
    """The server the web serves (`WEB_GUILD_ID`), if the bot has set it up."""
    row = community.get(settings.WEB_GUILD_ID)
    return row.pk if row else None


def _ensure_runtime(community_id: int) -> None:
    """`runtime.of` creates the settings row on first use, which a read-only transaction can't,
    so make sure it exists before opening one."""
    runtime.of(community_id)


def _sid(value: int | None) -> str | None:
    return None if value is None else str(value)


def _team(value: str) -> s.Team | None:
    return cast(s.Team, value) if value in {"A", "B"} else None


def _avatar_function() -> Callable[[Player, int], str | None]:
    """`league.web.avatars.avatar_url`, which serves Discord avatars from our own origin. Until
    that module is there, every face shows initials."""
    try:
        module = importlib.import_module("league.web.avatars")
    except ImportError:
        return lambda player, size: None
    return cast(Callable[[Player, int], str | None], module.avatar_url)


def avatar_of(player: Player, size: int = AVATAR_SIZE) -> str | None:
    return _avatar_function()(player, size)


def _avatars(player_ids: Iterable[int], size: int = AVATAR_SIZE) -> dict[int, str | None]:
    url = _avatar_function()
    rows = Player.objects.filter(pk__in=set(player_ids))
    return {player.pk: url(player, size) for player in rows}


def champion_refs(champion_ids: Iterable[int]) -> dict[int, s.ChampionRef]:
    """Each champion as the wire names it, by ID, with its art. Unknown IDs are left out."""
    ids = set(champion_ids)
    if not ids:
        return {}
    return {
        row.pk: s.ChampionRef(
            id=str(row.pk),
            name=row.name,
            slug=row.slug,
            icon_url=heroes.icon_url(row.slug, row.icon_url),
        )
        for row in Champion.objects.filter(pk__in=ids)
    }


# --- me ---------------------------------------------------------------------------------------


def build_me(player_id: int, community_id: int | None = None) -> s.MeSnap | None:
    """This player's own state in the web's server. None if the player no longer exists."""
    community_id = community_id or web_community_id()
    if community_id is None:
        raise LookupError("The web's server (WEB_GUILD_ID) hasn't been set up.")
    _ensure_runtime(community_id)
    with consistent():
        player = Player.objects.filter(pk=player_id).first()
        if player is None:
            return None
        server = Community.objects.select_related("active_mode").get(pk=community_id)
        return _me(server, player)


def own_match(server: Community, player: Player) -> MatchParticipant | None:
    """The player's ranked match in this server: the one they're active in, else one they
    reported in or were reported for, until its result is settled. Not one they left."""
    live = (
        MatchParticipant.objects.filter(player=player, is_active=True, match__community=server)
        .select_related("match")
        .order_by("-match_id")
        .first()
    )
    if live is not None:
        return live
    return (
        MatchParticipant.objects.filter(
            player=player,
            removed_reason="",
            match__community=server,
            match__kind=MatchKind.RANKED,
            match__status__in=SETTLING,
        )
        .exclude(team="")
        .select_related("match")
        .order_by("-match_id")
        .first()
    )


def _me(server: Community, player: Player) -> s.MeSnap:
    entry = QueueEntry.objects.filter(community=server, player=player).first()
    position = queue.status(server, player).position
    # This player's place only: the list itself is private.
    place = prio.place_of(server.pk, player.discord_user_id)
    penalty = penalties.active_penalty(server, player)
    now_standing = standing.standing(server, player)
    cooldown = None
    if penalty is not None:
        cooldown = s.Cooldown(
            until=penalty.expires_at,
            text=plain(penalties.refusal_text(server, player, penalty)),
            kind=cast(s.PenaltyKind, penalty.kind),
            strikes=now_standing.strikes,
            games_to_next=(
                None
                if now_standing.clean
                else now_standing.games_to_next or standing.strike_policy(server).games_per_strike
            ),
        )
    mine = own_match(server, player)
    scrim = (
        MatchParticipant.objects.filter(
            player=player,
            is_captain=True,
            match__community=server,
            match__kind=MatchKind.SCRIM,
            match__status__in=SCRIM_LIVE,
        )
        .select_related("match")
        .order_by("-match_id")
        .first()
    )
    flags = runtime.of(server)
    return s.MeSnap(
        player=s.MePlayer(
            id=str(player.pk),
            name=player.display_name,
            avatar_url=avatar_of(player),
            steam=[
                s.SteamLink(
                    account_id=str(account.account_id),
                    name=account.steam_name,
                    proven=account.proven_at is not None,
                    verified=account.verified_at is not None,
                )
                for account in SteamAccount.objects.filter(player=player).order_by(
                    "linked_at", "pk"
                )
            ],
        ),
        queue=s.MeQueue(
            in_queue=entry is not None,
            position=position,
            joined_at=entry.joined_at if entry else None,
            place=(
                s.QueuePlace(
                    position=place.position, total=place.total, held_until=place.held_until
                )
                if place
                else None
            ),
        ),
        cooldown=cooldown,
        match=(
            s.MeMatch(
                id=str(mine.match_id),
                status=cast(s.MatchStatus, mine.match.status),
                kind=cast(s.MatchKind, mine.match.kind),
                team=_team(mine.team),
                is_captain=mine.is_captain,
            )
            if mine
            else None
        ),
        scrim=(
            s.MeMatch(
                id=str(scrim.match_id),
                status=cast(s.MatchStatus, scrim.match.status),
                kind="scrim",
                team=_team(scrim.team),
                is_captain=True,
            )
            if scrim
            else None
        ),
        offers=_offers(server, player),
        last_offer=_last_offer(server, player),
        strikes=now_standing.strikes,
        flags=s.Flags(
            auto_captain=flags.auto_captain,
            api_results=flags.api_results,
            score_ocr=cast(s.ScoreOcr, flags.score_ocr),
            rating_label=leaderboards.label(server),
        ),
    )


def _offers(server: Community, player: Player) -> list[s.Offer]:
    rows = SubOffer.objects.filter(
        player=player,
        status=OfferStatus.PENDING,
        request__status=SubStatus.OPEN,
        request__match__community=server,
    ).select_related("request__leaving", "request__match", "invited_by")
    offers = []
    for offer in rows:
        request = offer.request
        match = request.match
        team, team_name = _slot_team(request)
        offers.append(
            s.Offer(
                id=str(offer.pk),
                match_id=str(request.match_id),
                deadline_at=offer.deadline_at,
                source=cast(s.OfferSource, offer.source),
                team=team,
                team_name=team_name,
                leaving_name=request.leaving.display_name,
                invited_by_name=offer.invited_by.display_name if offer.invited_by else None,
                match_status=cast(s.MatchStatus, match.status),
                started_at=match.api_started_at or match.started_at,
            )
        )
    return offers


def _slot_team(request: SubRequest) -> tuple[s.Team | None, str | None]:
    """The team a sub spot is on, and its name, once the leaver has one."""
    team = (
        MatchParticipant.objects.filter(match_id=request.match_id, player_id=request.leaving_id)
        .values_list("team", flat=True)
        .first()
    )
    captain = boards.captain_names(request.match).get(team or "")
    return _team(team or ""), boards.team_name(captain) if captain else None


def _last_offer(server: Community, player: Player) -> s.OfferEnd | None:
    offer = (
        SubOffer.objects.filter(player=player, request__match__community=server)
        .exclude(status=OfferStatus.PENDING)
        .select_related("request__match")
        .order_by(F("resolved_at").desc(nulls_last=True), "-pk")
        .first()
    )
    if offer is None:
        return None
    _, team_name = _slot_team(offer.request)
    return s.OfferEnd(
        id=str(offer.pk),
        match_id=str(offer.request.match_id),
        status=cast(s.OfferEndStatus, offer.status),
        team_name=team_name,
    )


# --- queue and live ---------------------------------------------------------------------------


def build_queue(community_id: int) -> s.QueueSnap:
    _ensure_runtime(community_id)
    with consistent():
        server = Community.objects.select_related("active_mode").get(pk=community_id)
        view = boards.queue_view(server)
        avatars = _avatars(view.player_ids)
        limit = runtime.of(server).max_concurrent_matches
        return s.QueueSnap(
            size=view.capacity,
            count=view.size,
            players=[
                s.PlayerRef(id=str(pk), name=name, avatar_url=avatars.get(pk))
                for pk, name in zip(view.player_ids, view.players, strict=True)
            ],
            mode_name=view.mode_name,
            max_concurrent=limit,
            live_matches=view.live_matches,
            open=view.live_matches < limit,
        )


def build_live(community_id: int) -> s.LiveSnap:
    """Every match being played or drafted in this server, ranked and scrims."""
    with consistent():
        matches = list(
            Match.objects.filter(community_id=community_id, status__in=TIMED)
            .select_related("mode_version")
            .order_by("-id")
        )
        captains: dict[int, dict[str, str]] = {}
        rows = (
            MatchParticipant.objects.filter(match__in=matches, is_captain=True, removed_reason="")
            .exclude(team="")
            .values_list("match_id", "team", "player__display_name")
        )
        for match_id, team, name in rows:
            captains.setdefault(match_id, {})[team] = name
        mode_names: dict[int, str] = {}
        out = []
        for match in matches:
            if match.mode_version_id not in mode_names:
                mode_names[match.mode_version_id] = parse_mode(match.mode_version.body).name
            names = captains.get(match.pk, {})
            out.append(
                s.LiveMatch(
                    id=str(match.pk),
                    status=cast(s.MatchStatus, match.status),
                    kind=cast(s.MatchKind, match.kind),
                    mode_name=mode_names[match.mode_version_id],
                    draft_name=draft_name(match.rng_seed),
                    captains=s.ByTeam(A=names.get("A"), B=names.get("B")),
                    sides=sides_of(match.hidden_king_team),
                    started_at=match.api_started_at or match.started_at,
                )
            )
        return s.LiveSnap(matches=out)


# --- match:{id} -------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MatchBody:
    """One build of a match, shared by every viewer. `snap` holds the real lobby code and a blank
    viewer; never send it without `project_match`."""

    snap: s.MatchSnap
    participants: frozenset[int]  # On the roster: these players get the lobby code.
    community_id: int
    version: int
    can_request_sub: bool  # The match allows sub requests now, for anyone on its roster.
    leaving: frozenset[int]  # Players with a sub request still in play.
    # Each voter's captain votes, as candidate IDs. Secret: a viewer only ever gets their own.
    votes: dict[int, tuple[str, ...]]
    # Whom each team's captain could offer in a swap, and whom they could ask for, while swaps
    # are open and none is waiting.
    swap_choices: dict[str, list[s.SwapChoice]] = field(default_factory=dict)
    # MatchSnap fields only a team's own players see (its chat, its hero wishes), by team.
    by_team: dict[str, dict[str, Any]] = field(default_factory=dict)


_NO_VIEWER = s.Viewer(
    is_player=False,
    team=None,
    is_captain=False,
    is_acting=False,
    has_voted=False,
    votes=[],
    checked_in=False,
    can_request_sub=False,
    swap_give=[],
    swap_take=[],
)


def build_match(match_id: int) -> MatchBody | None:
    """None if there's no such match."""
    community_id = Match.objects.filter(pk=match_id).values_list("community_id", flat=True).first()
    if community_id is None:
        return None
    _ensure_runtime(community_id)
    with consistent():
        if not Match.objects.filter(pk=match_id).exists():
            return None
        state = boards.board_state(match_id)
        return _body(
            state,
            _votes(state),
            responses=_responses(match_id),
            void_reason=_void_reason(match_id) if state.status == Status.VOIDED else None,
            scoreboard=_scoreboard(match_id),
            subs_done=_subs_done(match_id),
            rating_label=leaderboards.label(community_id),
        )


def _subs_done(match_id: int) -> list[s.SubDone]:
    """The match's sub requests that have ended, so the page can say who came in for whom."""
    rows = (
        SubRequest.objects.filter(match_id=match_id)
        .exclude(status__in=UNRESOLVED)
        .select_related("leaving", "filled_by")
        .order_by("resolved_at", "pk")
    )
    teams = dict(
        MatchParticipant.objects.filter(match_id=match_id).values_list("player_id", "team")
    )
    return [
        s.SubDone(
            id=str(row.pk),
            status=cast(s.SubDoneStatus, row.status),
            reason=cast(s.SubReason, row.reason),
            leaving_id=str(row.leaving_id),
            leaving_name=row.leaving.display_name,
            # The leaver's row keeps its team; a refilled ready-check seat takes the newcomer's.
            team=_team(teams.get(row.leaving_id) or teams.get(row.filled_by_id or 0) or ""),
            joined_id=_sid(row.filled_by_id),
            joined_name=row.filled_by.display_name if row.filled_by else None,
        )
        for row in rows
    ]


def _votes(state: boards.BoardState) -> dict[int, tuple[str, ...]]:
    """Votes for players still in the lobby, while the vote is open."""
    if state.status != Status.CAPTAIN_PHASE:
        return {}
    active = {line.player_id for line in state.players}
    rows = CaptainVote.objects.filter(
        match_id=state.match_id, voter_id__in=active, candidate_id__in=active
    ).values_list("voter_id", "candidate_id")
    votes: dict[int, tuple[str, ...]] = {}
    for voter_id, candidate_id in rows.order_by("id"):
        votes[voter_id] = (*votes.get(voter_id, ()), str(candidate_id))
    return votes


def _responses(match_id: int) -> list[s.ResultResponse]:
    rows = ResultSubmission.objects.filter(match_id=match_id).select_related("captain")
    return [
        s.ResultResponse(
            player_id=str(row.captain_id),
            name=row.captain.display_name,
            verdict=cast(s.Verdict, row.verdict),
            winner=_team(row.claimed_winner),
        )
        for row in rows.order_by("id")
    ]


def _void_reason(match_id: int) -> str | None:
    row = MatchResult.objects.filter(match_id=match_id).order_by("-id").first()
    if row is None or row.outcome != "void" or not row.reason:
        return None
    return plain(row.reason)


def _scoreboard(match_id: int) -> s.Scoreboard | None:
    """The latest read's unmatched names, each with the players who could be them: the same
    choices the Discord name picker offers."""
    read = ocr.latest_read(Match.objects.get(pk=match_id))
    if read is None or not read.stats.filter(player__isnull=True).exists():
        return None
    rows = [row for row in ocr.unmapped_rows(read.pk) if row.team in {"A", "B"} and row.options]
    if not rows:
        return None
    heroes_by_row = dict(
        PlayerMatchStat.objects.filter(read=read, player__isnull=True).values_list("row", "hero_id")
    )
    art = champion_refs(hero for hero in heroes_by_row.values() if hero is not None)
    players: dict[int, s.ScoreboardPlayer] = {}
    for row in rows:
        for player_id, name in row.options:
            players[player_id] = s.ScoreboardPlayer(
                id=str(player_id), name=name, team=cast(s.Team, row.team)
            )
    return s.Scoreboard(
        read_id=str(read.pk),
        rows=[
            s.ScoreboardRow(
                row=row.row,
                name=row.ocr_name,
                team=cast(s.Team, row.team),
                hero=art.get(heroes_by_row.get(row.row) or 0),
                hero_name=row.hero_name,
            )
            for row in rows
        ],
        players=sorted(players.values(), key=lambda p: (p.team, p.name.casefold())),
    )


def _lobby_state(state: boards.BoardState) -> s.LobbyState:
    if state.api_started:
        return "started"
    if state.api_lobby:
        return "ready"
    if state.api_lobby_failed:
        return "failed"
    if state.status == Status.LOBBY_CODE:
        return "making"
    return "none"


def _body(
    state: boards.BoardState,
    votes: dict[int, tuple[str, ...]],
    *,
    responses: list[s.ResultResponse],
    void_reason: str | None,
    scoreboard: s.Scoreboard | None,
    subs_done: list[s.SubDone],
    rating_label: str,
) -> MatchBody:
    ids = [line.player_id for line in state.players]
    avatars = _avatars(ids)
    champion_ids = {line.champion_id for line in state.actions if line.champion_id is not None}
    art = champion_refs(champion_ids)
    captain_ids = {line.team: line.player_id for line in state.players if line.is_captain}
    players = [
        s.MatchPlayer(
            id=str(line.player_id),
            name=line.name,
            avatar_url=avatars.get(line.player_id),
            rating=line.rating,
            team=_team(line.team),
            is_captain=line.is_captain,
            is_ready=line.is_ready,
            has_voted=line.player_id in state.voted_ids,
            captain_ok=line.captain_ok,
            captain_note=line.captain_note,
            checked_in=line.player_id in state.checked_in_ids,
        )
        for line in state.players
    ]
    names = {"A": state.captains.get("A"), "B": state.captains.get("B")}
    turn = None
    if state.step_action:
        turn = s.Turn(
            team=cast(s.Team, state.acting_team),
            captain_id=_sid(captain_ids.get(state.acting_team)),
            captain_name=state.acting_captain_name,
            action=cast(s.DraftActionKind, state.step_action),
            position=state.turn_position,
            total=state.turn_total,
            next_captain_name=state.next_captain_name or None,
            next_action=cast(s.DraftActionKind, state.next_action) if state.next_action else None,
        )
    swap = state.swap
    snap = s.MatchSnap(
        id=str(state.match_id),
        status=cast(s.MatchStatus, state.status),
        kind=cast(s.MatchKind, state.kind),
        mode_name=state.mode_name,
        rating_label=rating_label,
        deadline_at=state.deadline_at,
        closes_at=state.closes_at,
        started_at=state.game_started_at,
        players=players,
        captains=s.ByTeam(**names),
        team_names=s.ByTeam(
            A=boards.team_name(names["A"]) if names["A"] else None,
            B=boards.team_name(names["B"]) if names["B"] else None,
        ),
        sides=_sides(state),
        draft=[
            s.DraftEntry(
                action=cast(s.DraftActionKind, line.action),
                team=_team(line.team),
                label=line.label,
                auto=line.auto,
                random=line.random_choice,
                player_id=_sid(line.player_id),
                champion=art.get(line.champion_id) if line.champion_id is not None else None,
            )
            for line in state.actions
        ],
        turn=turn,
        step_index=state.step_index,
        player_draft_order=[
            s.PlayerDraftStep(step_index=index, team=cast(s.Team, team))
            for index, team in enumerate(state.player_draft_order)
        ],
        champion_steps=[
            s.ChampionStep(action=cast(s.ChampionAction, action), side=cast(s.Side, side))
            for action, side in state.champion_steps
        ],
        champion_step=state.champion_step,
        champions=[
            s.ChampionChoice(
                id=str(option.id),
                name=option.name,
                slug=option.slug,
                icon_url=heroes.icon_url(option.slug, option.icon_url),
                taken=option.taken,
            )
            for option in state.champions
        ],
        coinflip=_coinflip(state, captain_ids),
        host=(
            s.Host(id=str(state.host_id), name=state.host_name)
            if state.host_id is not None
            else None
        ),
        lobby_code=state.lobby_code or None,
        lobby=s.Lobby(
            state=_lobby_state(state),
            api_lobby=state.api_lobby,
            api_started=state.api_started,
            api_leaves_at=state.api_leaves_at,
        ),
        swap=s.Swap(
            open=state.can_swap,
            pending=(
                s.SwapOffer(
                    id=str(swap.id),
                    requested_by_id=_sid(swap.requested_by_id),
                    requested_by_name=swap.requested_by_name,
                    give_id=_sid(swap.give_id),
                    give_name=swap.give_name,
                    take_id=_sid(swap.take_id),
                    take_name=swap.take_name,
                    deadline_at=swap.deadline_at,
                )
                if swap is not None
                else None
            ),
        ),
        result=s.Result(
            winner=_team(state.winner),
            reported_winner=_team(state.reported_winner),
            reported_by_id=_sid(state.reported_by_id),
            reported_by_name=state.reported_by or None,
            deltas={str(pk): delta for pk, delta in state.deltas.items()},
            responses=responses,
            void_reason=void_reason,
        ),
        subs=[_sub(line) for line in state.subs],
        subs_done=subs_done,
        on_hold=state.on_hold,
        hold_until=state.hold_until,
        early_leave=s.EarlyLeave(
            open=state.early_leave_open,
            minutes=state.early_leave_minutes,
            pending=(
                s.EarlyLeaveClaim(
                    leaver_id=_sid(state.early_leave_player_id),
                    leaver_name=state.early_leave_name,
                    by_id=_sid(state.early_leave_by_id),
                    by_name=state.early_leave_by,
                    deadline_at=state.early_leave_deadline_at,
                )
                if state.early_leave_name and state.early_leave_deadline_at
                else None
            ),
        ),
        win_chance_a=state.win_chance_a,
        captain_min_games=state.captain_min_games,
        votes_per_player=lobby.VOTES_PER_PLAYER,
        draft_name=state.draft_name,
        gif_url=state.gif_url,
        restarted_from=_sid(state.restarted_from),
        scoreboard=scoreboard,
        viewer=_NO_VIEWER,
    )
    return MatchBody(
        snap=snap,
        participants=frozenset(ids),
        community_id=state.community_id,
        version=state.version,
        can_request_sub=state.can_request_sub,
        leaving=frozenset(line.leaving_id for line in state.subs if line.leaving_id is not None),
        votes=votes,
        swap_choices=_swap_choices(state) if state.can_swap and swap is None else {},
    )


def _swap_choices(state: boards.BoardState) -> dict[str, list[s.SwapChoice]]:
    """Each team's players a swap can move: everyone but the captain (`swaps.own_options`)."""
    choices: dict[str, list[s.SwapChoice]] = {"A": [], "B": []}
    for line in sorted(state.players, key=lambda line: line.player_id):
        if line.team in choices and not line.is_captain:
            choices[line.team].append(s.SwapChoice(player_id=str(line.player_id), name=line.name))
    return choices


def sides_of(hidden_king_team: str) -> s.Sides:
    """Each team's side, from the team that plays The Hidden King (blank before the coinflip)."""
    if hidden_king_team not in {"A", "B"}:
        return s.Sides(A=None, B=None)
    return s.Sides(
        A="hk" if hidden_king_team == "A" else "am",
        B="hk" if hidden_king_team == "B" else "am",
    )


def _sides(state: boards.BoardState) -> s.Sides:
    return sides_of(state.hidden_king_team)


def _coinflip(state: boards.BoardState, captain_ids: dict[str, int]) -> s.Coinflip | None:
    if not state.coinflip_winner:
        return None
    chooser = ""
    if state.status == Status.COINFLIP:
        loser = "B" if state.coinflip_winner == "A" else "A"
        if not state.coinflip_winner_choice:
            chooser = state.coinflip_winner
        elif state.kind == MatchKind.SCRIM and not state.coinflip_loser_choice:
            chooser = loser
    return s.Coinflip(
        winner=_team(state.coinflip_winner),
        winner_choice=cast(s.CoinflipChoice, state.coinflip_winner_choice or None),
        loser_choice=cast(s.CoinflipChoice, state.coinflip_loser_choice or None),
        options=[cast(s.CoinflipChoice, option) for option in state.coinflip_options],
        chooser_team=_team(chooser),
        chooser_id=_sid(captain_ids.get(chooser)) if chooser else None,
    )


def _sub(line: boards.SubLine) -> s.SubEntry:
    offer = None
    if line.offer_player_id is not None:
        source = (
            OfferSource.QUEUE
            if line.offer_from_queue
            else OfferSource.PRIO
            if line.offer_from_prio
            else OfferSource.INVITE
        )
        offer = s.SubOfferRef(
            player_id=str(line.offer_player_id),
            name=line.offer_name,
            source=cast(s.OfferSource, source.value),
            deadline_at=line.offer_deadline_at,
        )
    return s.SubEntry(
        id=str(line.id),
        status=cast(s.SubStatus, line.status),
        reason=cast(s.SubReason, line.reason),
        leaving_id=_sid(line.leaving_id),
        leaving_name=line.leaving_name,
        team=_team(line.team),
        requested_by_id=_sid(line.requested_by_id),
        requested_by_name=line.requested_by_name or None,
        is_self=line.is_self,
        deadline_at=line.deadline_at,
        name_until=line.name_until,
        offer=offer,
    )


def project_match(body: MatchBody, viewer_player_id: int | None) -> s.MatchSnap:
    """The match as this viewer sees it. Pure: no database."""
    snap = body.snap
    if viewer_player_id is None or viewer_player_id not in body.participants:
        return snap.model_copy(
            update={"lobby_code": None, "scoreboard": None, "viewer": _NO_VIEWER}
        )
    viewer = str(viewer_player_id)
    me = next(line for line in snap.players if line.id == viewer)
    give: list[s.SwapChoice] = []
    take: list[s.SwapChoice] = []
    if me.is_captain and me.team is not None and body.swap_choices:
        other = "B" if me.team == "A" else "A"
        give, take = body.swap_choices.get(me.team, []), body.swap_choices.get(other, [])
    return snap.model_copy(
        update={
            # Matching names is for captains (`ocr.can_map`); nobody else gets the names.
            "scoreboard": snap.scoreboard if me.is_captain else None,
            **(body.by_team.get(me.team, {}) if me.team is not None else {}),
            "viewer": s.Viewer(
                is_player=True,
                team=me.team,
                is_captain=me.is_captain,
                is_acting=_is_acting(snap, me),
                has_voted=me.has_voted,
                votes=list(body.votes.get(viewer_player_id, ())),
                checked_in=me.checked_in,
                can_request_sub=body.can_request_sub and viewer_player_id not in body.leaving,
                swap_give=give,
                swap_take=take,
            ),
        }
    )


def _is_acting(snap: s.MatchSnap, me: s.MatchPlayer) -> bool:
    """Whether the match is waiting on this player right now."""
    if snap.on_hold:
        return False
    status = snap.status
    pending = snap.swap.pending
    if pending is not None and me.is_captain and pending.requested_by_id != me.id:
        return True  # The other captain's swap offer waits for their answer.
    if status == Status.READY_CHECK:
        return not me.is_ready
    if status == Status.CAPTAIN_PHASE:
        return not me.has_voted
    if status == Status.CAPTAIN_CHECKIN:
        return me.is_captain and not me.checked_in
    if status in {Status.PLAYER_DRAFT, Status.CHAMPION_DRAFT}:
        return snap.turn is not None and snap.turn.captain_id == me.id
    if status == Status.COINFLIP:
        return snap.coinflip is not None and snap.coinflip.chooser_id == me.id
    if status == Status.LOBBY_CODE:
        # The bot makes the lobby; only if it couldn't does the host enter a code.
        return snap.lobby.state == "failed" and snap.host is not None and snap.host.id == me.id
    if status == Status.READY_TO_DRAFT:
        return me.is_captain
    if status == Status.AWAITING_CONFIRMATION:
        return me.is_captain and snap.result.reported_by_id != me.id
    if status == Status.IN_PROGRESS:
        claim = snap.early_leave.pending
        if claim is not None:
            return me.is_captain and claim.by_id != me.id
        return me.is_captain and snap.lobby.state == "ready"  # Press Start in the bot's lobby.
    return False


def roster_of(match_id: int) -> frozenset[int]:
    """Players whose `me` can show the match: those active in it, and its roster while its
    result is settled (the first report makes everyone inactive). A scrim's captains are on its
    roster too, though inactive so they can play ranked meanwhile."""
    return frozenset(
        MatchParticipant.objects.filter(match_id=match_id)
        .filter(Q(is_active=True) | (Q(removed_reason="") & ~Q(team="")))
        .values_list("player_id", flat=True)
    )
