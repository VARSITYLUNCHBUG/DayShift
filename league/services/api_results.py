"""Checking results against deadlock-api, by Deadlock match ID.

Once a match has a Deadlock match ID (from the API lobby, a captain's report or the scoreboard)
and a result has been reported, its metadata is fetched. deadlock-api only has a custom match once
someone's client has sent it in, so a miss is retried with backoff for a few hours.

When the metadata arrives:

- **Winner.** Team 0 is Hidden King. A different winner disputes an unconfirmed result, or asks
  staff about a confirmed one. Nothing is overturned automatically.
- **Roster.** A player may link several Steam accounts, and plays on one of them. A linked account
  seen on its player's team becomes verified. A player seen on the other team, or with none of
  their accounts in the match, goes to staff.
- **Awards.** The game's `mvp_rank` 1, 2 and 3 are the MVP and the two key players. When all three
  are linked players on the roster, they become the match's awards.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from django.conf import settings
from django.db import transaction
from django.db.models import Count

from league.domain.engine import Status
from league.models import ApiMatchCheck, Community, Match, MatchParticipant, SteamAccount
from league.models.alerts import AlertKind
from league.models.api import CheckStatus
from league.models.permissions import Area
from league.models.scoreboards import AwardSource
from league.services import alerts, runtime, steam
from league.services.common import add_effect, now

logger = logging.getLogger(__name__)

# Minutes to wait before each fetch. About four hours in all.
BACKOFF_MINUTES = (0, 2, 5, 15, 30, 60, 60, 60)
CHECKABLE = frozenset({Status.AWAITING_CONFIRMATION, Status.DISPUTED, Status.COMPLETED})
HIDDEN_KING_TEAM = 0  # In match metadata, team 0 is Hidden King and team 1 the Archmother.


def status_lines(community: Community) -> list[str]:
    """Lobby and result-check settings, with counts, for the admin."""
    settings_ = runtime.of(community)
    checks = ApiMatchCheck.objects.filter(match__community=community)
    by_status = dict(checks.values("status").annotate(n=Count("id")).values_list("status", "n"))
    linked = SteamAccount.objects.all()
    verified = linked.exclude(verified_at=None).count()
    lines = [
        "Lobbies: deadlock-api's bot creates each one; the host enters a code if it can't "
        f"(region: {settings_.lobby_region or 'automatic'}).",
        f"Result checks: {'on' if settings_.api_results else 'off'}.",
        f"Steam links: {linked.count()}, {verified} verified.",
    ]
    if by_status:
        lines.append(
            "Checks so far: "
            + ", ".join(f"{CheckStatus(s).label}: {n}" for s, n in sorted(by_status.items()))
        )
    if not settings.DEADLOCK_API_KEY:
        lines.append("Without an API key, lobbies are limited to 10 an hour.")
    return lines


def schedule(match: Match, attempt: int = 1) -> bool:
    """Queue a fetch, if the match has an ID, a result to check and the server wants checks."""
    if not runtime.of(match.community_id).api_results or match.deadlock_match_id is None:
        return False
    if match.status not in CHECKABLE or attempt > len(BACKOFF_MINUTES):
        return False
    add_effect(
        match.community,
        "check_match_api",
        {"attempt": attempt, "deadlock_match_id": match.deadlock_match_id},
        match=match,
        dedupe_key=f"check_match_api:{match.pk}:{match.deadlock_match_id}:{attempt}",
        run_after=now() + timedelta(minutes=BACKOFF_MINUTES[attempt - 1]),
    )
    return True


@transaction.atomic
def correct_deadlock_match_id(match_id: int, deadlock_match_id: int) -> None:
    """Staff set or correct a match's Deadlock ID (/deadlock check), and check it at once. This is
    the one place an ID that is already set gets replaced."""
    match = Match.objects.lock(match_id)
    if match.deadlock_match_id not in (None, deadlock_match_id):
        match.deadlock_match_id = None
        match.save(update_fields=["deadlock_match_id"])
    if not set_deadlock_match_id(match, deadlock_match_id):
        schedule(match, attempt=match.api_checks.count() + 1)


def set_deadlock_match_id(match: Match, deadlock_match_id: int) -> bool:
    """Record Deadlock's match ID, first one wins, and check it once there's a result. The caller
    holds the match lock."""
    if match.deadlock_match_id is not None or deadlock_match_id <= 0:
        return False
    match.deadlock_match_id = deadlock_match_id
    match.version += 1
    match.save(update_fields=["deadlock_match_id", "version"])
    schedule(match)
    return True


# --- Reading metadata ------------------------------------------------------------------------


def summarise(data: dict[str, Any]) -> dict[str, Any]:
    """The few fields kept from a 1 MB metadata response."""
    info = data.get("match_info") or {}
    players = []
    for player in info.get("players") or []:
        if not isinstance(player, dict) or "account_id" not in player:
            continue
        stats = (player.get("stats") or [{}])[-1] or {}
        players.append(
            {
                "account_id": int(player["account_id"]),
                "team": player.get("team"),
                "hero_id": player.get("hero_id"),
                "kills": player.get("kills"),
                "deaths": player.get("deaths"),
                "assists": player.get("assists"),
                "net_worth": player.get("net_worth"),
                "player_damage": stats.get("player_damage"),
                "healing": stats.get("player_healing"),
                "mvp_rank": player.get("mvp_rank"),
                # Seconds into the match the player abandoned it. 0 or missing: they didn't.
                "abandoned_s": player.get("abandon_match_time_s") or 0,
            }
        )
    return {
        "match_id": info.get("match_id"),
        "duration_s": info.get("duration_s"),
        "winning_team": info.get("winning_team"),
        "players": players,
    }


def _team_letters(match: Match) -> dict[int, str]:
    hk = match.hidden_king_team
    if hk not in {"A", "B"}:
        return {}
    return {HIDDEN_KING_TEAM: hk, 1 - HIDDEN_KING_TEAM: "B" if hk == "A" else "A"}


def _claimed_winner(match: Match) -> str:
    if match.status == Status.COMPLETED:
        return match.winner
    report = match.submissions.filter(verdict="report").order_by("id").first()
    return report.claimed_winner if report else ""


def _next_attempt(match: Match) -> int:
    return ApiMatchCheck.objects.filter(match=match).count() + 1


@transaction.atomic
def record_miss(match_id: int, deadlock_match_id: int, status: str, http_status: int | None,
                reason: str) -> ApiMatchCheck:  # fmt: skip
    """Not in deadlock-api yet, or the request failed: note it and try again later."""
    match = Match.objects.lock(match_id)
    attempt = _next_attempt(match)
    check = ApiMatchCheck.objects.create(
        match=match,
        deadlock_match_id=deadlock_match_id,
        attempt=attempt,
        status=status,
        http_status=http_status,
        problems=[reason[:300]] if reason else [],
        created_at=now(),
    )
    schedule(match, attempt + 1)
    return check


@transaction.atomic
def record_metadata(match_id: int, deadlock_match_id: int, data: dict[str, Any]) -> ApiMatchCheck:
    """Compare deadlock-api's match with ours, store the comparison, and act on it."""
    from league.services import corrections, results

    match = Match.objects.lock(match_id)
    summary = summarise(data)
    letters = _team_letters(match)
    api_players = {p["account_id"]: p for p in summary["players"]}
    api_winner = (
        letters.get(summary["winning_team"], "") if summary["winning_team"] is not None else ""
    )

    rows = list(match.participants.roster().select_related("player"))
    by_player = {row.player_id: row for row in rows}
    # Every linked account of the roster. A player with several is in the match on whichever
    # one deadlock-api shows; they're missing only if it shows none of them.
    linked = {
        account_id: by_player[player_id]
        for account_id, player_id in steam.accounts_of(by_player).items()
    }
    wrong_team: list[int] = []
    seen_right: list[int] = []
    present: set[int] = set()
    for account_id, row in linked.items():
        found = api_players.get(int(account_id))
        if found is None:
            continue
        present.add(row.player_id)
        if letters.get(found["team"]) != row.team:
            wrong_team.append(row.player_id)
        else:
            seen_right.append(account_id)
    missing = sorted({row.player_id for row in linked.values()} - present)
    unlinked = sorted(a for a in api_players if a not in linked)
    _note_abandons(match, api_players, linked)

    problems = []
    claimed = _claimed_winner(match)
    if api_winner and claimed and api_winner != claimed:
        problems.append("deadlock-api shows the other team won")
    if linked and not present:
        problems.append(f"none of the linked players were in Deadlock match {deadlock_match_id}")
    if wrong_team:
        problems.append(f"{len(wrong_team)} linked player(s) were on the other team")
    status = CheckStatus.MISMATCH if problems else CheckStatus.OK
    check = ApiMatchCheck.objects.create(
        match=match,
        deadlock_match_id=deadlock_match_id,
        attempt=_next_attempt(match),
        status=status,
        http_status=200,
        api_winner=api_winner,
        duration_s=summary["duration_s"] if isinstance(summary["duration_s"], int) else None,
        wrong_team=wrong_team,
        missing=missing,
        unlinked_accounts=unlinked,
        summary=summary,
        problems=problems,
        created_at=now(),
    )
    if status == CheckStatus.OK:
        steam.mark_verified(seen_right)
        awards = _awards(api_players, linked)
        if awards and match.status in CHECKABLE:
            corrections.apply_award_correction(
                match.pk, awards, AwardSource.API, None, "From deadlock-api's match data"
            )
        return check

    text = f"The result doesn't match deadlock-api ({deadlock_match_id}): {'; '.join(problems)}."
    if (
        api_winner
        and claimed
        and api_winner != claimed
        and match.status == Status.AWAITING_CONFIRMATION
    ):
        results._dispute(
            match, None, f"Deadlock's match history shows the other team won ({deadlock_match_id})."
        )
    else:
        alerts.raise_alert(
            match.community,
            AlertKind.API_MISMATCH,
            Area.DISPUTES,
            text,
            match=match,
            dedupe_key=f"api_mismatch:{match.pk}:{deadlock_match_id}",
        )
    return check


def _note_abandons(
    match: Match, api_players: dict[int, dict[str, Any]], linked: dict[int, MatchParticipant]
) -> None:
    """Linked players deadlock-api shows abandoning the match are marked as having left early.
    An abandon inside the early-leave window is put to staff, who can void it."""

    window = match.mode.results.early_leave_minutes * 60
    for account_id, row in linked.items():
        abandoned = int(api_players.get(int(account_id), {}).get("abandoned_s") or 0)
        if abandoned <= 0:
            continue
        MatchParticipant.objects.filter(pk=row.pk).update(left_early=True)
        if abandoned <= window and match.status in CHECKABLE:
            minutes, seconds = divmod(abandoned, 60)
            alerts.raise_alert(
                match.community,
                AlertKind.API_ABANDON,
                Area.DISPUTES,
                f"deadlock-api shows {row.player.display_name} abandoning at "
                f"{minutes}:{seconds:02d}. If that's an early leave, `/match early_leave` "
                "voids it.",
                match=match,
                dedupe_key=f"api_abandon:{match.pk}:{row.player_id}",
            )


def _awards(
    api_players: dict[int, dict[str, Any]], linked: dict[int, MatchParticipant]
) -> dict[int, str]:
    """mvp_rank 1 is the MVP and 2 and 3 the key players, when every one is a linked player."""
    ranked = {p.get("mvp_rank"): account for account, p in api_players.items() if p.get("mvp_rank")}
    if not all(rank in ranked for rank in (1, 2, 3)):
        return {}
    picks: dict[int, str] = {}
    for rank, kind in ((1, "mvp"), (2, "key"), (3, "key")):
        row = linked.get(ranked[rank])
        if row is None:
            return {}
        picks[row.player_id] = kind
    return picks


def latest_ok(match: Match) -> ApiMatchCheck | None:
    return (
        ApiMatchCheck.objects.filter(match=match, status__in=(CheckStatus.OK, CheckStatus.MISMATCH))
        .order_by("-id")
        .first()
    )


def api_stat_lines(match: Match) -> dict[int, str]:
    """Per player, a line from deadlock-api's data, for linked players: "Mirage 12/8/13, 38k"."""
    from league.models import Champion
    from league.services.boards import _compact

    check = latest_ok(match)
    if check is None:
        return {}
    heroes = dict(Champion.objects.values_list("pk", "name"))
    by_account = {p["account_id"]: p for p in check.summary.get("players", [])}
    lines = {}
    roster = match.participants.roster().values_list("player_id", flat=True)
    for account_id, player_id in steam.accounts_of(roster).items():
        p = by_account.get(account_id)
        if p is None or player_id in lines:
            continue
        hero = heroes.get(p.get("hero_id"), "")
        kda = f"{p.get('kills', '?')}/{p.get('deaths', '?')}/{p.get('assists', '?')}"
        lines[player_id] = f"{hero} {kda}, {_compact(p.get('player_damage'))} damage".strip()
    return lines
