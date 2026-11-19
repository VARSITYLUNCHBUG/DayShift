"""The JSON the control API answers with (see README, read models). Snowflakes are strings."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from django.conf import settings

from devtools import control, lookup, sim_client, timers
from devtools.models import DevProfile, MatchScript
from league.domain.draft_plan import build_plan, team_for_role
from league.domain.engine import LIVE, Status
from league.domain.mode_schema import parse_mode
from league.models import (
    Champion,
    Community,
    DraftAction,
    Match,
    MatchParticipant,
    MatchResource,
    Player,
    PlayerRating,
    QueueEntry,
    Season,
)
from league.models.matches import ResourceKind
from league.services import draft, lobby, runtime, swaps
from league.services.common import now

PUBLIC_DISCORD_API = "https://discord.com/api/v10"

JSON = dict[str, Any]


def snowflake(value: int | None) -> str | None:
    return None if value is None else str(value)


def stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat().replace("+00:00", "Z")


def _ratings(season: Season | None, player_ids: list[int]) -> dict[int, PlayerRating]:
    if season is None:
        return {}
    rows = PlayerRating.objects.filter(season=season, player_id__in=player_ids)
    return {row.player_id: row for row in rows}


def players(rows: list[Player]) -> list[JSON]:
    """Player read models, with as few queries as a list needs."""
    league = lookup.community_or_none()
    season = (
        Season.objects.filter(community=league, ended_at__isnull=True).first() if league else None
    )
    ids = [row.pk for row in rows]
    ratings = _ratings(season, ids)
    profiles = {p.player_id: p for p in DevProfile.objects.filter(player_id__in=ids)}
    queue = [e.player_id for e in QueueEntry.objects.order_by("joined_at", "pk")]
    live = dict(
        MatchParticipant.objects.filter(player_id__in=ids, is_active=True).values_list(
            "player_id", "match_id"
        )
    )
    slugs = dict(Champion.objects.values_list("pk", "slug"))
    out = []
    for row in rows:
        rating = ratings.get(row.pk)
        profile = profiles.get(row.pk)
        out.append(
            {
                "id": row.pk,
                "discord_user_id": snowflake(row.discord_user_id),
                "name": row.display_name,
                "rating": rating.rating if rating else None,
                "mu": str(rating.mu) if rating else None,
                "sigma": str(rating.sigma) if rating else None,
                "games": rating.games if rating else 0,
                "queued": row.pk in queue,
                "queue_position": queue.index(row.pk) + 1 if row.pk in queue else None,
                "match_id": live.get(row.pk),
                "dm_open": profile.dm_open if profile else None,
                "sim_user": profile.sim_user if profile else False,
                "retired": profile.retired if profile else False,
                "picks": {
                    "prefer": [slugs.get(pk, pk) for pk in (profile.prefer if profile else [])],
                    "ban": [slugs.get(pk, pk) for pk in (profile.ban if profile else [])],
                },
            }
        )
    return out


def player(row: Player) -> JSON:
    return players([row])[0]


def queue(league: Community) -> list[JSON]:
    entries = list(
        QueueEntry.objects.filter(community=league)
        .select_related("player")
        .order_by("joined_at", "pk")
    )
    models = players([entry.player for entry in entries])
    return [
        {"position": index + 1, "joined_at": stamp(entry.joined_at), "player": model}
        for index, (entry, model) in enumerate(zip(entries, models, strict=True))
    ]


def _turn(match: Match) -> JSON:
    status = match.status
    active = match.participants.filter(is_active=True)
    if status == Status.READY_CHECK:
        unready = active.filter(ready_at__isnull=True).values_list("player_id", flat=True)
        return {"action": "ready", "team": None, "player_ids": list(unready)}
    if status == Status.CAPTAIN_PHASE:
        voters = set(match.captain_votes.values_list("voter_id", flat=True))
        waiting = [pk for pk in active.values_list("player_id", flat=True) if pk not in voters]
        return {"action": "vote", "team": None, "player_ids": waiting}
    if status == Status.CAPTAIN_CHECKIN:
        captains = active.filter(is_captain=True, checked_in_at__isnull=True).order_by("team")
        return {
            "action": "checkin",
            "team": None,
            "player_ids": list(captains.values_list("player_id", flat=True)),
        }
    if status in {Status.PLAYER_DRAFT, Status.CHAMPION_DRAFT}:
        step = build_plan(match.mode)[match.step_index]
        first = (
            match.player_first_pick if step.action == "player_pick" else match.champion_first_pick
        )
        team = team_for_role(step.role, first)
        return {
            "action": step.action,
            "team": team,
            "player_ids": [lookup.acting_captain(match).pk],
            "step": match.step_index,
        }
    if status == Status.COINFLIP:
        team, _ = draft.coinflip_turn(match)
        captain = active.filter(team=team, is_captain=True).values_list("player_id", flat=True)
        return {"action": "coinflip", "team": team, "player_ids": list(captain)}
    if status == Status.LOBBY_CODE:
        if not match.api_lobby_failed:
            # deadlock-api is making the lobby: nobody's turn until it answers.
            return {"action": "api_lobby", "team": None, "player_ids": []}
        host = [match.lobby_code_host_id] if match.lobby_code_host_id else []
        return {"action": "lobby_code", "team": None, "player_ids": host}
    if status == Status.IN_PROGRESS and match.api_party_id and match.api_started_at is None:
        captains = active.filter(is_captain=True).order_by("team")
        return {
            "action": "start_match",
            "team": None,
            "player_ids": list(captains.values_list("player_id", flat=True)),
        }
    if status in {Status.IN_PROGRESS, Status.AWAITING_CONFIRMATION}:
        reported = set(match.submissions.values_list("captain_id", flat=True))
        captains = active.filter(is_captain=True).order_by("team")
        waiting = [pk for pk in captains.values_list("player_id", flat=True) if pk not in reported]
        action = "report" if status == Status.IN_PROGRESS else "confirm"
        return {"action": action, "team": None, "player_ids": waiting}
    if status == Status.DISPUTED:
        return {"action": "resolve", "team": None, "player_ids": []}
    return {"action": None, "team": None, "player_ids": []}


def _picks(match: Match) -> list[JSON]:
    rows = DraftAction.objects.filter(match=match).select_related("target_champion")
    return [
        {
            "step": row.step_index,
            "action": row.action,
            "team": row.team,
            "player_id": row.target_player_id,
            "champion": (
                {
                    "id": row.target_champion.pk,
                    "slug": row.target_champion.slug,
                    "name": row.target_champion.name,
                }
                if row.target_champion
                else None
            ),
            "source": row.source,
            "random": row.random_choice,
        }
        for row in rows.order_by("step_index")
    ]


def _sub_requests(match: Match) -> list[JSON]:
    return [
        {
            "id": request.pk,
            "status": request.status,
            "reason": request.reason,
            "leaving": request.leaving_id,
            "requested_by": request.requested_by_id,
            "deadline_at": stamp(request.deadline_at),
            "name_until": stamp(request.name_until),
            "offers": [
                {
                    "id": offer.pk,
                    "player_id": offer.player_id,
                    "status": offer.status,
                    "deadline_at": stamp(offer.deadline_at),
                }
                for offer in request.offers.order_by("pk")
            ],
        }
        for request in match.sub_requests.order_by("pk")
    ]


def _swaps(match: Match) -> list[JSON]:
    return [
        {
            "id": swap.pk,
            "status": swap.status,
            "requested_by": swap.requested_by_id,
            "give": swap.give_id,
            "take": swap.take_id,
            "deadline_at": stamp(swap.deadline_at),
            "resolved_by": swap.resolved_by_id,
        }
        for swap in match.swaps.order_by("pk")
    ]


def match(row: Match) -> JSON:
    row = lookup.match(row.pk)  # Fresh: every service call changes it.
    participants = list(row.participants.select_related("player").order_by("pk"))
    ratings = _ratings(row.season, [p.player_id for p in participants])
    frozen = timers.is_frozen(row.pk)
    if frozen:
        left = timers.frozen_seconds_left(row.pk)
        seconds_left = None if left is None else round(left)
    elif row.deadline_at is not None:
        seconds_left = max(0, round((row.deadline_at - now()).total_seconds()))
    else:
        seconds_left = None
    text = MatchResource.objects.filter(
        match=row, kind=ResourceKind.TEXT, deleted_at__isnull=True
    ).first()
    script = MatchScript.objects.filter(match=row).first()
    live = row.status in LIVE
    return {
        "id": row.pk,
        "status": row.status,
        "kind": row.kind,
        "mode": {"slug": row.mode_version.slug, "version": row.mode_version.version},
        "version": row.version,
        "step_index": row.step_index,
        "deadline_at": stamp(row.deadline_at),
        "seconds_left": seconds_left,
        "frozen": frozen,
        "on_hold": row.held_seconds is not None,
        "held_seconds": row.held_seconds,
        "turn": _turn(row) if live else {"action": None, "team": None, "player_ids": []},
        "captains": {
            p.team: p.player_id for p in participants if p.is_captain and not p.removed_reason
        },
        "teams": {
            team: [p.player_id for p in participants if p.team == team and not p.removed_reason]
            for team in ("A", "B")
        },
        "players": [
            {
                "id": p.player_id,
                "discord_user_id": snowflake(p.player.discord_user_id),
                "name": p.player.display_name,
                "rating": ratings[p.player_id].rating if p.player_id in ratings else None,
                "team": p.team,
                "is_captain": p.is_captain,
                "ready": p.ready_at is not None,
                "checked_in": p.checked_in_at is not None,
                "missed_checkin": p.missed_checkin,
                "active": p.is_active,
                "removed_reason": p.removed_reason,
            }
            for p in participants
        ],
        "picks": _picks(row),
        "coinflip_winner": row.coinflip_winner,
        "hidden_king_team": row.hidden_king_team,
        "champion_first_pick": row.champion_first_pick,
        "lobby_code": row.lobby_code,
        "lobby_code_host": row.lobby_code_host_id,
        "api_lobby": {
            "failed": row.api_lobby_failed,
            "party_id": row.api_party_id or None,
            "started": row.api_started_at is not None,
        },
        "winner": row.winner,
        "votes": (
            {str(k): v for k, v in lobby.vote_counts(row).items()}
            if row.status == Status.CAPTAIN_PHASE
            else {}
        ),
        "sub_requests": _sub_requests(row),
        "swap_open": row.status in swaps.SWAPPABLE and live,
        "swaps": _swaps(row),
        "text_channel_id": snowflake(text.discord_id if text else None),
        "script": script.body if script else {},
        "created_at": stamp(row.created_at),
        "ended_at": stamp(row.ended_at),
    }


def state() -> JSON:
    league = lookup.community_or_none()
    sim = {
        "configured": sim_client.configured(),
        "reachable": sim_client.reachable(),
        "url": sim_client.url(),
        # False when the bot talks to real Discord: the simulator (kept for the deadlock-api
        # stand-in) can't see its gateway session, so the panel mustn't call it down.
        "bot_on_sim": settings.DISCORD_API_BASE != PUBLIC_DISCORD_API,
    }
    timer_state = {"paused_all": timers.paused_all(), "frozen_matches": timers.frozen_ids()}
    if league is None:
        return {
            "community": None,
            "season": None,
            "lobby_size": None,
            "queue": [],
            "matches": [],
            "recent": [],
            "timers": timer_state,
            "lobbies": control.lobbies(),
            "sim": sim,
        }
    season = Season.objects.filter(community=league, ended_at__isnull=True).first()
    mode = league.active_mode
    live = Match.objects.filter(community=league, status__in=LIVE).order_by("pk")
    recent = Match.objects.filter(community=league).exclude(status__in=LIVE).order_by("-pk")[:10]
    return {
        "community": {
            "id": league.pk,
            "guild_id": snowflake(league.discord_guild_id),
            "name": league.name,
            "active_mode": {"id": mode.pk, "slug": mode.slug, "version": mode.version},
            "channels": {
                "queue": snowflake(league.queue_channel_id),
                "waiting_room": snowflake(league.waiting_room_channel_id),
                "results": snowflake(league.results_channel_id),
                "archive": snowflake(league.archive_channel_id),
                "match_category": snowflake(league.match_category_id),
                "staff": snowflake(league.staff_channel_id),
                "leaderboard": snowflake(league.leaderboard_channel_id),
            },
            "pug_role_id": snowflake(league.pug_role_id),
            "settings": _settings(league),
        },
        "season": {"id": season.pk, "number": season.number} if season else None,
        "lobby_size": parse_mode(mode.body).lobby_size,
        "queue": queue(league),
        "matches": [match(row) for row in live],
        "recent": [
            {
                "id": row.pk,
                "status": row.status,
                "winner": row.winner,
                "ended_at": stamp(row.ended_at),
            }
            for row in recent
        ],
        "timers": timer_state,
        "lobbies": control.lobbies(),
        "sim": sim,
    }


def _settings(league: Community) -> JSON:
    """The runtime settings the admin changes, as far as a dev run cares."""
    row = runtime.of(league)
    return {
        "max_concurrent_matches": row.max_concurrent_matches,
        "auto_captain": row.auto_captain,
        "score_ocr": row.score_ocr,
        "api_results": row.api_results,
        "lobby_region": row.lobby_region,
        "interim_points": row.interim_points,
    }
