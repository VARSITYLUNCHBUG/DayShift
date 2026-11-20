"""What the HTTP API answers with, built from the same read models as Discord's boards.

Everything is scoped to the web's server (`WEB_GUILD_ID`) and, unless a season is asked for, its
open season. A single match stays readable after its season ends, so old links keep working.

Profiles are private: `my_profile` is only ever built for the signed-in player, the ladder's rows
carry no player ID, and search carries no stats.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal, cast

from django.conf import settings
from django.db.models import Case, Exists, IntegerField, OuterRef, Q, Value, When
from django.db.models.functions import Lower

from league.domain.engine import TIMED, Status, draft_name, pick_gif
from league.domain.errors import InvalidAction
from league.domain.mode_schema import parse_mode
from league.domain.openskill_v1 import in_placement, tier
from league.models import (
    ApiMatchCheck,
    Champion,
    Community,
    InterimPointsChange,
    InterimRating,
    Match,
    MatchParticipant,
    MatchPostgame,
    Penalty,
    Player,
    PlayerMatchStat,
    PlayerRating,
    PrioEntry,
    QueueEntry,
    RatingEvent,
    Season,
    SteamAccount,
    StrikeAdjustment,
)
from league.models.api import CheckStatus
from league.models.matches import MatchKind
from league.models.moderation import PenaltyKind
from league.services import (
    api_results,
    boards,
    interim,
    leaderboards,
    postgame,
    ratings,
    runtime,
    scrims,
    share_card,
    standing,
)
from league.services import community as community_service
from league.services.gifs import draft_gifs
from league.web import heroes
from league.web.api import schema as a
from league.web.avatars import avatar_url
from league.web.live import schema as s

PAGE = 20  # Matches per page.
LADDER_PAGE = 50
AVATAR_SIZE = 64  # Pixels, as on the websocket.
PROFILE_AVATAR_SIZE = 128
HISTORY = 200  # Rating changes on a profile.
RECENT = 20  # Matches on a profile.
TOP_HEROES = 5
STRIKE_LOG = 50
SEARCH_LIMIT = 10
SEARCH_MIN = 2  # Characters; fewer match too many people to be useful.
SEARCH_MAX = 50
# Finished matches the Matches list shows: rated ones and drafted scrims.
FINISHED = (Status.COMPLETED, Status.VOIDED, Status.DRAFTED)

type MatchFilter = Literal["live", "recent"]


@dataclass(frozen=True, slots=True)
class Scope:
    community: Community
    season: Season


def scope() -> Scope | None:
    """The web's server and its open season, or None before the bot has set them up."""
    server = community_service.get(settings.WEB_GUILD_ID)
    if server is None:
        return None
    try:
        season = Season.objects.open_for(server)
    except InvalidAction:
        return None
    return Scope(server, season)


def season_of(where: Scope, season_id: int | None) -> Season | None:
    """The server's season with this ID, the open one for None, or None if there's no such
    season here."""
    if season_id is None:
        return where.season
    return Season.objects.filter(community=where.community, pk=season_id).first()


def in_server(where: Scope, match_id: int) -> Match | None:
    return (
        Match.objects.filter(pk=match_id, community=where.community)
        .select_related("mode_version", "season")
        .first()
    )


def _team(value: str) -> s.Team | None:
    return cast(s.Team, value) if value in {"A", "B"} else None


def _side(hidden_king_team: str, team: str) -> s.Side | None:
    if hidden_king_team not in {"A", "B"} or team not in {"A", "B"}:
        return None
    return "hk" if hidden_king_team == team else "am"


def _sides(hidden_king_team: str) -> s.Sides:
    return s.Sides(A=_side(hidden_king_team, "A"), B=_side(hidden_king_team, "B"))


def _award(kind: str) -> a.LeagueAward | None:
    return cast(a.LeagueAward, kind) if kind in {"mvp", "key"} else None


def _outcome(status: str, winner: str, team: str) -> a.Outcome | None:
    if status == Status.VOIDED:
        return "void"
    if status == Status.COMPLETED and winner in {"A", "B"} and team in {"A", "B"}:
        return "win" if winner == team else "loss"
    return None


def _avatars(player_ids: Iterable[int], size: int = AVATAR_SIZE) -> dict[int, str | None]:
    rows = Player.objects.filter(pk__in=set(player_ids))
    return {player.pk: avatar_url(player, size) for player in rows}


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


def _postgame_ids(match_ids: Iterable[int]) -> set[int]:
    return set(
        MatchPostgame.objects.filter(
            match_id__in=list(match_ids), schema_version=postgame.SCHEMA_VERSION
        ).values_list("match_id", flat=True)
    )


def heroes_played(
    match_ids: Iterable[int], player_ids: Iterable[int]
) -> dict[tuple[int, int], int]:
    """(match ID, player ID) to the champion they played: from the postgame where the match has
    one, else the latest scoreboard read that placed them."""
    ids, players = list(match_ids), set(player_ids)
    played: dict[tuple[int, int], int] = {}
    docs = MatchPostgame.objects.filter(match_id__in=ids).values_list("match_id", "data")
    for match_id, data in docs:
        lines = data.get("players", []) if isinstance(data, dict) else []
        for line in lines:
            if not isinstance(line, dict):
                continue
            player_id, hero_id = line.get("player_id"), line.get("hero_id")
            if player_id in players and isinstance(hero_id, int):
                played[(match_id, player_id)] = hero_id
    stats = (
        PlayerMatchStat.objects.filter(match_id__in=ids, player_id__in=players, hero__isnull=False)
        .order_by("match_id", "read_id")
        .values_list("match_id", "player_id", "hero_id")
    )
    for match_id, player_id, hero_id in stats:  # The latest read of a match wins.
        if player_id is not None and hero_id is not None:
            played.setdefault((match_id, player_id), hero_id)
    return played


def _tiers(season: Season) -> list[str]:
    return [str(label) for label, _floor in ratings.params_for(season)["tiers"]]


# --- Matches ----------------------------------------------------------------------------------


def match_list(
    where: Scope, viewer: Player, kind: MatchFilter, before: int | None, *, mine: bool = False
) -> a.MatchList:
    """Live matches in the server, or finished ones this season. Newest first, a page at a time:
    `before` is the last match ID of the previous page. `mine`: only those the viewer played in
    (and wasn't subbed out of)."""
    if kind == "live":
        rows = Match.objects.filter(community=where.community, status__in=TIMED)
    else:
        rows = Match.objects.filter(
            community=where.community, season=where.season, status__in=FINISHED
        )
    if mine:
        rows = rows.filter(
            Exists(
                MatchParticipant.objects.filter(
                    match=OuterRef("pk"), player=viewer, removed_reason=""
                )
            )
        )
    if before is not None:
        rows = rows.filter(pk__lt=before)
    page = list(rows.select_related("mode_version").order_by("-id")[: PAGE + 1])
    more = len(page) > PAGE
    page = page[:PAGE]
    roster = MatchParticipant.objects.filter(match__in=page, removed_reason="").exclude(team="")
    captains: dict[int, dict[str, str]] = {}
    for match_id, team, name in roster.filter(is_captain=True).values_list(
        "match_id", "team", "player__display_name"
    ):
        captains.setdefault(match_id, {})[team] = name
    yours = dict(roster.filter(player=viewer).values_list("match_id", "team"))
    mode_names: dict[int, str] = {}
    out = []
    for match in page:
        if match.mode_version_id not in mode_names:
            mode_names[match.mode_version_id] = parse_mode(match.mode_version.body).name
        names = captains.get(match.pk, {})
        out.append(
            a.MatchRow(
                id=str(match.pk),
                status=cast(s.MatchStatus, match.status),
                kind=cast(s.MatchKind, match.kind),
                mode_name=mode_names[match.mode_version_id],
                draft_name=draft_name(match.rng_seed),
                captains=s.ByTeam(A=names.get("A"), B=names.get("B")),
                team_names=s.ByTeam(
                    A=boards.team_name(names["A"]) if "A" in names else None,
                    B=boards.team_name(names["B"]) if "B" in names else None,
                ),
                sides=_sides(match.hidden_king_team),
                winner=_team(match.winner),
                started_at=match.api_started_at or match.started_at,
                ended_at=match.ended_at,
                your_team=_team(yours.get(match.pk, "")),
            )
        )
    return a.MatchList(matches=out, next_cursor=str(page[-1].pk) if more else None)


def _rated(match: Match) -> bool:
    return match.status == Status.COMPLETED and match.kind == MatchKind.RANKED


def match_detail(where: Scope, match_id: int) -> a.MatchDetail | None:
    """A match's public record. None for an unknown match or another server's."""
    match = in_server(where, match_id)
    if match is None:
        return None
    view = boards.results_view(match.pk)
    rows = {"A": view.team_a, "B": view.team_b}
    player_ids = [row.player_id for row in view.team_a + view.team_b]
    avatars = _avatars(player_ids)
    draft = list(
        match.draft_actions.filter(target_champion__isnull=False, action__in=("ban", "pick"))
        .exclude(team="")
        .order_by("step_index")
        .values_list("action", "team", "target_champion_id")
    )
    played = heroes_played([match.pk], player_ids)
    art = champion_refs(
        [champion_id for _action, _team, champion_id in draft] + list(played.values())
    )
    rated = _rated(match)
    averages = {"A": view.avg_a, "B": view.avg_b}

    def champions(team: str, action: str) -> list[s.ChampionRef]:
        return [
            art[champion_id]
            for kind, by, champion_id in draft
            if kind == action and by == team and champion_id in art
        ]

    def hero(player_id: int) -> s.ChampionRef | None:
        champion_id = played.get((match.pk, player_id))
        return art.get(champion_id) if champion_id is not None else None

    teams = [
        a.TeamResult(
            team=cast(s.Team, team),
            name=view.team_name(team) if team in view.captains else None,
            side=_side(match.hidden_king_team, team),
            average_rating=averages[team] if rated and averages[team] else None,
            players=[
                a.ResultPlayer(
                    id=str(row.player_id),
                    name=row.name,
                    avatar_url=avatars.get(row.player_id),
                    is_captain=row.is_captain,
                    rating_before=row.before,
                    rating_after=row.after if rated else row.before,
                    delta=row.delta if rated else 0,
                    award=_award(row.award),
                    hero=hero(row.player_id),
                    stat_line=row.stat_line or None,
                )
                for row in rows[team]
            ],
            picks=champions(team, "pick"),
            bans=champions(team, "ban"),
        )
        for team in ("A", "B")
    ]
    return a.MatchDetail(
        id=str(match.pk),
        status=cast(s.MatchStatus, match.status),
        kind=cast(s.MatchKind, match.kind),
        mode_name=parse_mode(match.mode_version.body).name,
        draft_name=draft_name(match.rng_seed),
        gif_url=pick_gif(match.rng_seed, draft_gifs()),
        rating_label=leaderboards.label(match.community_id),
        rated=rated,
        winner=_team(match.winner),
        started_at=match.api_started_at or match.started_at,
        ended_at=match.ended_at,
        duration_s=view.duration_s,
        teams=teams,
        draft=[
            a.DraftPick(
                action=cast(s.ChampionAction, action),
                team=cast(s.Team, by),
                champion=art[champion_id],
            )
            for action, by, champion_id in draft
            if champion_id in art
        ],
        win_chance_a=view.expected_a if rated else None,
        deadlock_match_id=str(view.deadlock_match_id) if view.deadlock_match_id else None,
        has_postgame=bool(_postgame_ids([match.pk])),
    )


# --- Postgame ---------------------------------------------------------------------------------


# A match in one of these never gets checked against deadlock-api.
UNCHECKED = frozenset({Status.VOIDED, Status.DRAFTED})


def _pending_reason(match: Match) -> a.PendingReason:
    """Why a match has no postgame document (yet)."""
    if match.status in UNCHECKED:
        return "unavailable"
    if match.status not in api_results.CHECKABLE:
        return "later"  # Still being played.
    if match.deadlock_match_id is None:
        return "no-match-id"
    checks = ApiMatchCheck.objects.filter(match=match)
    if checks.filter(status__in=(CheckStatus.OK, CheckStatus.MISMATCH)).exists():
        # The data came but made no document: the wrong match, or one it couldn't read.
        return "unavailable"
    if not runtime.of(match.community_id).api_results:
        return "unavailable"
    if checks.count() >= len(api_results.BACKOFF_MINUTES):
        return "unavailable"  # Every retry missed.
    return "later"


def _your_night(match: Match, viewer: Player, doc: postgame.Postgame) -> a.YourNight | None:
    participant = match.participants.roster().filter(player=viewer).first()
    if participant is None:
        return None
    view = boards.results_view(match.pk)
    row = next((r for r in view.team_a + view.team_b if r.player_id == viewer.pk), None)
    rated = _rated(match) and row is not None
    slot = next((line.slot for line in doc.players if line.player_id == viewer.pk), None)
    return a.YourNight(
        team=_team(participant.team),
        side=_side(match.hidden_king_team, participant.team),
        slot=slot,
        result=_outcome(match.status, match.winner, participant.team),
        rating_label=leaderboards.label(match.community_id),
        rating_before=row.before if rated and row else None,
        rating_after=row.after if rated and row else None,
        delta=row.delta if rated and row else None,
        award=_award(row.award) if row else None,
    )


def match_postgame(
    where: Scope, viewer: Player, match_id: int
) -> a.PostgameReady | a.PostgamePending | None:
    """The match's postgame, with the viewer's own night when they played in it. None for an
    unknown match or another server's."""
    match = in_server(where, match_id)
    if match is None:
        return None
    doc = postgame.stored(match)
    if doc is None:
        return a.PostgamePending(status="pending", reason=_pending_reason(match))
    return a.PostgameReady(status="ready", data=doc, you=_your_night(match, viewer, doc))


# --- Ladder and seasons -----------------------------------------------------------------------


def seasons(where: Scope) -> a.SeasonList:
    rows = Season.objects.filter(community=where.community).order_by("-number")
    return a.SeasonList(
        seasons=[
            a.SeasonRef(id=str(row.pk), name=row.name, is_open=row.pk == where.season.pk)
            for row in rows
        ]
    )


def _tiers_of(season: Season, player_ids: Iterable[int]) -> dict[int, str]:
    """Each player's OpenSkill tier this season; the start tier for anyone unrated."""
    ids = set(player_ids)
    params = ratings.params_for(season)
    found = {
        row.player_id: row for row in PlayerRating.objects.filter(season=season, player_id__in=ids)
    }
    out = {}
    for player_id in ids:
        state = ratings.state_of(season, found.get(player_id))
        out[player_id] = tier(state.mu, state.sigma, params)
    return out


def ladder(where: Scope, viewer: Player, season: Season, offset: int) -> a.Ladder:
    """A page of the season's table, as the #leaderboard channel lists it, and the viewer's own
    row."""
    table = leaderboards.table(season)
    page = table[offset : offset + LADDER_PAGE]
    mine = next((row for row in table if row.player_id == viewer.pk), None)
    shown = page + ([mine] if mine is not None and mine not in page else [])
    points = interim.enabled(where.community)
    tiers = {} if points else _tiers_of(season, (row.player_id for row in shown))
    avatars = _avatars(row.player_id for row in shown)

    def line(row: leaderboards.Row) -> a.LadderRow:
        return a.LadderRow(
            rank=row.rank,
            name=row.name,
            avatar_url=avatars.get(row.player_id),
            rating=row.rating,
            tier=tiers.get(row.player_id),
            wins=row.wins,
            losses=row.losses,
            is_you=row.player_id == viewer.pk,
        )

    more = offset + LADDER_PAGE < len(table)
    return a.Ladder(
        season=season.name,
        season_id=str(season.pk),
        rating_label=leaderboards.label(where.community),
        tiers=[] if points else _tiers(season),
        total=len(table),
        rows=[line(row) for row in page],
        me=line(mine) if mine is not None else None,
        next_offset=offset + LADDER_PAGE if more else None,
    )


# --- The private profile ----------------------------------------------------------------------


def steam_rows(player: Player) -> list[a.SteamRow]:
    return [
        a.SteamRow(
            id=str(row.pk),
            name=row.steam_name,
            proven=row.proven_at is not None,
            verified=row.verified_at is not None,
            linked_at=row.linked_at,
        )
        for row in SteamAccount.objects.filter(player=player).order_by("linked_at", "pk")
    ]


def _strike_log(community: Community, player: Player) -> list[a.StrikeEntry]:
    entries: list[a.StrikeEntry] = []
    offences = Penalty.objects.filter(community=community, player=player, strikes__gt=0)
    for row in offences.order_by("-starts_at", "-pk")[:STRIKE_LOG]:
        entries.append(
            a.StrikeEntry(
                at=row.starts_at,
                kind="offence",
                label=str(PenaltyKind(row.kind).label) if row.kind in PenaltyKind else row.kind,
                strikes=row.strikes,
                reason=row.reason,
                match_id=str(row.match_id) if row.match_id else None,
                waived=row.strikes_waived,
            )
        )
    adjustments = StrikeAdjustment.objects.filter(community=community, player=player)
    for adjustment in adjustments.order_by("-created_at", "-pk")[:STRIKE_LOG]:
        entries.append(
            a.StrikeEntry(
                at=adjustment.created_at,
                kind="adjustment",
                label="Staff adjustment",
                strikes=adjustment.delta,
                reason=adjustment.reason,
                match_id=None,
                waived=False,
            )
        )
    entries.sort(key=lambda entry: entry.at, reverse=True)
    return entries[:STRIKE_LOG]


def _strikes(community: Community, player: Player) -> a.Strikes:
    now_standing = standing.standing(community, player)
    policy = standing.strike_policy(community)
    return a.Strikes(
        count=now_standing.strikes,
        progress=now_standing.progress,
        games_per_strike=policy.games_per_strike,
        games_to_next=now_standing.games_to_next,
        next_decay_at=now_standing.next_decay_at,
        log=_strike_log(community, player),
    )


def _captain(community: Community, player: Player) -> a.CaptainStatus:
    mode = parse_mode(community.active_mode.body)
    eligible = standing.eligibility(community, mode, [player.pk])[player.pk].eligibility
    return a.CaptainStatus(eligible=eligible.ok, reason="" if eligible.ok else eligible.reason)


def _history(season: Season, player: Player, points: bool) -> list[a.RatingPoint]:
    if points:
        changes = list(
            InterimPointsChange.objects.filter(season=season, player=player)
            .select_related("match")
            .order_by("-id")[:HISTORY]
        )
        return [
            a.RatingPoint(
                at=change.match.ended_at,
                match_id=str(change.match_id),
                delta=change.delta,
                rating_after=change.after,
            )
            for change in reversed(changes)
        ]
    events = list(
        RatingEvent.objects.filter(season=season, player=player).order_by("-id")[:HISTORY]
    )
    return [
        a.RatingPoint(
            at=event.created_at,
            match_id=str(event.match_id) if event.match_id else None,
            delta=event.delta,
            rating_after=event.rating_after,
        )
        for event in reversed(events)
    ]


def _changes(
    season: Season, player: Player, match_ids: list[int], points: bool
) -> dict[int, tuple[int, int]]:
    """(net change, rating after) per match, corrections included."""
    out: dict[int, tuple[int, int]] = {}
    if points:
        for match_id, before, after in InterimPointsChange.objects.filter(
            season=season, player=player, match_id__in=match_ids
        ).values_list("match_id", "before", "after"):
            out[match_id] = (after - before, after)
        return out
    net: dict[int, int] = defaultdict(int)
    for match_id, delta, after in (
        RatingEvent.objects.filter(season=season, player=player, match_id__in=match_ids)
        .order_by("id")
        .values_list("match_id", "delta", "rating_after")
    ):
        if match_id is None:
            continue
        net[match_id] += delta
        out[match_id] = (net[match_id], after)
    return out


def _recent(where: Scope, season: Season, player: Player, points: bool) -> list[a.RecentMatch]:
    rows = list(
        MatchParticipant.objects.filter(
            player=player,
            removed_reason="",
            match__community=where.community,
            match__season=season,
            match__status__in=FINISHED,
        )
        .exclude(team="")
        .select_related("match")
        .order_by("-match_id")[:RECENT]
    )
    ids = [row.match_id for row in rows]
    changes = _changes(season, player, ids, points)
    played = heroes_played(ids, [player.pk])
    art = champion_refs(played.values())
    awards = ratings.awards_by_match(ids)
    docs = _postgame_ids(ids)
    out = []
    for row in rows:
        match = row.match
        change = changes.get(match.pk)
        hero_id = played.get((match.pk, player.pk))
        out.append(
            a.RecentMatch(
                match_id=str(match.pk),
                draft_name=draft_name(match.rng_seed),
                status=cast(s.MatchStatus, match.status),
                ended_at=match.ended_at,
                team=_team(row.team),
                side=_side(match.hidden_king_team, row.team),
                result=_outcome(match.status, match.winner, row.team),
                hero=art.get(hero_id) if hero_id is not None else None,
                delta=change[0] if change else None,
                rating_after=change[1] if change else None,
                award=_award(awards.get(match.pk, {}).get(player.pk, "")),
                has_postgame=match.pk in docs,
            )
        )
    return out


def _top_heroes(where: Scope, season: Season, player: Player) -> list[a.HeroGames]:
    completed = MatchParticipant.objects.filter(
        player=player,
        removed_reason="",
        match__community=where.community,
        match__season=season,
        match__status=Status.COMPLETED,
    ).values_list("match_id", flat=True)
    counts = share_card.hero_counts(player, completed)
    top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP_HEROES]
    art = champion_refs(hero_id for hero_id, _games in top)
    return [a.HeroGames(hero=art[hero_id], games=games) for hero_id, games in top if hero_id in art]


def my_profile(where: Scope, viewer: Player, season: Season) -> a.MyProfile:
    """The signed-in player's own profile. Never call it for anyone but the viewer."""
    stats = boards.player_stats(season, viewer, history=1)
    points = interim.enabled(where.community)
    placement = None
    if not points:
        params = ratings.params_for(season)
        if in_placement(stats.games, params):
            placement = a.Placement(played=stats.games, total=int(params["placement_games"]))
    return a.MyProfile(
        player=s.PlayerRef(
            id=str(viewer.pk),
            name=viewer.display_name,
            avatar_url=avatar_url(viewer, PROFILE_AVATAR_SIZE),
        ),
        season=season.name,
        season_id=str(season.pk),
        rating_label=stats.rating_label,
        rating=stats.rating,
        tier=None if points else stats.tier or None,
        tiers=[] if points else _tiers(season),
        rank=stats.rank,
        ranked=stats.ranked,
        games=stats.games,
        wins=stats.wins,
        losses=stats.losses,
        placement=placement,
        strikes=_strikes(where.community, viewer),
        captain=_captain(where.community, viewer),
        history=_history(season, viewer, points),
        recent=_recent(where, season, viewer, points),
        heroes=_top_heroes(where, season, viewer),
        awards=a.Awards(mvps=stats.mvps, keys=stats.keys),
        accounts=a.Accounts(
            discord_name=viewer.display_name,
            avatar_url=avatar_url(viewer, PROFILE_AVATAR_SIZE),
            steam=steam_rows(viewer),
        ),
    )


# --- Player search ----------------------------------------------------------------------------


def search_players(where: Scope, viewer: Player, text: str) -> a.PlayerSearch:
    """Players of this server whose name contains the text, names starting with it first.

    "Of this server": anyone who has been on a match roster here, is in its queue or on its
    priority list now, has a rating or imported points in one of its seasons, or a penalty here.
    Never the viewer.
    """
    text = text.strip()[:SEARCH_MAX]
    if len(text) < SEARCH_MIN:
        return a.PlayerSearch(players=[])
    server = where.community
    here = (
        Q(Exists(MatchParticipant.objects.filter(player=OuterRef("pk"), match__community=server)))
        | Q(Exists(QueueEntry.objects.filter(player=OuterRef("pk"), community=server)))
        | Q(
            Exists(
                PrioEntry.objects.filter(
                    discord_user_id=OuterRef("discord_user_id"), community=server
                )
            )
        )
        | Q(Exists(PlayerRating.objects.filter(player=OuterRef("pk"), season__community=server)))
        | Q(Exists(InterimRating.objects.filter(player=OuterRef("pk"), season__community=server)))
        | Q(Exists(Penalty.objects.filter(player=OuterRef("pk"), community=server)))
    )
    found = list(
        Player.objects.filter(here, is_active=True, display_name__icontains=text)
        .exclude(pk=viewer.pk)
        .annotate(
            starts=Case(
                When(display_name__istartswith=text, then=Value(0)),
                default=Value(1),
                output_field=IntegerField(),
            )
        )
        .order_by("starts", Lower("display_name"), "pk")[:SEARCH_LIMIT]
    )
    busy = set(
        MatchParticipant.objects.filter(
            player__in=found, is_active=True, match__status__in=TIMED
        ).values_list("player_id", flat=True)
    )
    return a.PlayerSearch(
        players=[
            a.SearchPlayer(
                id=str(player.pk),
                name=player.display_name,
                avatar_url=avatar_url(player, AVATAR_SIZE),
                in_match=player.pk in busy,
            )
            for player in found
        ]
    )


# --- Tools ------------------------------------------------------------------------------------


def random_draft(where: Scope) -> a.RandomDraft:
    """Bebot's /randomdraft. Its heroes come back by name, so they're matched to champions by
    name, as the draft pool holds each name once."""
    draft = scrims.random_draft(where.community)
    names = {hero.name for side in (*draft.bans.values(), *draft.picks.values()) for hero in side}
    by_name = {row.name: row.pk for row in Champion.objects.filter(name__in=names)}
    art = champion_refs(by_name.values())

    def refs(chosen: list[scrims.RandomHero]) -> list[s.ChampionRef]:
        return [art[by_name[hero.name]] for hero in chosen if by_name.get(hero.name) in art]

    def side(key: str) -> a.DraftSide:
        return a.DraftSide(bans=refs(draft.bans[key]), picks=refs(draft.picks[key]))

    return a.RandomDraft(hk=side("hk"), am=side("am"))
