"""The NeatQueue interim: NeatQueue's points carried over at the cutover, kept moving here.

The host imports each player's NeatQueue points, wins and losses from a CSV, on the admin's
Interim ratings page. While the interim is on (a runtime setting), every completed match moves
the points Elo-style on the two teams' average points, and the leaderboards, /stats, boards and
results show the points instead of the OpenSkill rating. OpenSkill keeps rating every match
underneath, and still drives captain tie-breaks, the first pick and auto-picks, so turning the
interim off is the whole cutover.

The points are a projection, rebuilt in full from the imported values and the season's completed
matches in the order they ended. So a rescore, a void or a late sub corrects them by itself.
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from dataclasses import dataclass

from django.db import transaction

from league.domain.errors import InvalidAction
from league.models import (
    Community,
    InterimPointsChange,
    InterimRating,
    Match,
    MatchParticipant,
    Player,
    Season,
)
from league.models.matches import MatchKind
from league.services import runtime
from league.services.common import lock_community, now, open_season


def enabled(community: Community | int) -> bool:
    return runtime.of(community).interim_points


def expected(own_average: float, other_average: float) -> float:
    """Elo's chance that a team with `own_average` beats one with `other_average`."""
    return 1 / (1 + 10 ** ((other_average - own_average) / 400))


def points_change(won: bool, own_average: float, other_average: float, k: int) -> int:
    """Points each player on a team gains (or loses, negative) from one match."""
    return round(k * ((1.0 if won else 0.0) - expected(own_average, other_average)))


@dataclass(frozen=True, slots=True)
class Standing:
    points: int
    wins: int
    losses: int

    @property
    def games(self) -> int:
        return self.wins + self.losses


def rebuild(season: Season) -> int:
    """Recompute every player's points for the season. Returns the matches folded in.

    The caller holds the community lock, as finalising and correcting a result do, so two
    rebuilds never interleave."""
    settings = runtime.of(season.community_id)
    start, k = settings.interim_start_points, settings.interim_k_factor
    rows = {row.player_id: row for row in InterimRating.objects.filter(season=season)}
    points = {
        pid: row.imported_points if row.imported_points is not None else start
        for pid, row in rows.items()
    }
    wins = {pid: row.imported_wins for pid, row in rows.items()}
    losses = {pid: row.imported_losses for pid, row in rows.items()}
    games: dict[int, int] = defaultdict(int)

    matches = list(
        Match.objects.filter(
            season=season, kind=MatchKind.RANKED, status="completed", winner__in=("A", "B")
        )
        .order_by("ended_at", "id")
        .values_list("pk", "winner")
    )
    rosters: dict[int, dict[str, list[int]]] = defaultdict(lambda: {"A": [], "B": []})
    on_roster = MatchParticipant.objects.filter(
        match_id__in=[pk for pk, _ in matches], removed_reason=""
    ).exclude(team="")
    for match_id, player_id, team in on_roster.values_list("match_id", "player_id", "team"):
        rosters[match_id][team].append(player_id)

    changes = []
    for match_id, winner in matches:
        teams = rosters[match_id]
        if not teams["A"] or not teams["B"]:
            continue
        averages = {
            team: sum(points.get(p, start) for p in ids) / len(ids) for team, ids in teams.items()
        }
        for team, ids in teams.items():
            other = "B" if team == "A" else "A"
            won = team == winner
            delta = points_change(won, averages[team], averages[other], k)
            for player_id in ids:
                before = points.get(player_id, start)
                points[player_id] = before + delta
                wins[player_id] = wins.get(player_id, 0) + (1 if won else 0)
                losses[player_id] = losses.get(player_id, 0) + (0 if won else 1)
                games[player_id] += 1
                changes.append(
                    InterimPointsChange(
                        season=season,
                        match_id=match_id,
                        player_id=player_id,
                        before=before,
                        after=points[player_id],
                    )
                )

    InterimPointsChange.objects.filter(season=season).delete()
    InterimPointsChange.objects.bulk_create(changes)
    for player_id, value in points.items():
        fields = {
            "points": value,
            "wins": wins.get(player_id, 0),
            "losses": losses.get(player_id, 0),
            "games": games.get(player_id, 0),
        }
        row = rows.get(player_id)
        if row is None:
            InterimRating.objects.create(season=season, player_id=player_id, **fields)
            continue
        if any(getattr(row, name) != wanted for name, wanted in fields.items()):
            for name, wanted in fields.items():
                setattr(row, name, wanted)
            row.save(update_fields=list(fields))
    return len(matches)


def rebuild_if_enabled(season: Season) -> None:
    if enabled(season.community_id):
        rebuild(season)


def standings(season: Season, player_ids: list[int] | None = None) -> dict[int, Standing]:
    """Points, wins and losses per player, from the projection."""
    rows = InterimRating.objects.filter(season=season)
    if player_ids is not None:
        rows = rows.filter(player_id__in=player_ids)
    return {
        row.player_id: Standing(row.points, row.wins, row.losses)
        for row in rows.only("player_id", "points", "wins", "losses")
    }


def start_points(season: Season) -> int:
    return runtime.of(season.community_id).interim_start_points


def match_changes(match: Match) -> dict[int, tuple[int, int]]:
    """(before, after) points per player for one match."""
    rows = InterimPointsChange.objects.filter(match=match)
    return {row.player_id: (row.before, row.after) for row in rows}


def recent(season: Season, player: Player, limit: int = 10) -> list[tuple[int, int, int]]:
    """(match ID, change, points after), newest first."""
    rows = InterimPointsChange.objects.filter(season=season, player=player).order_by("-id")[:limit]
    return [(row.match_id, row.after - row.before, row.after) for row in rows]


# --- Import ------------------------------------------------------------------------------------

ID_COLUMNS = ("discord_id", "discord_user_id", "user_id", "id", "discord")
POINTS_COLUMNS = ("rating", "points", "mmr", "elo")
NAME_COLUMNS = ("name", "username", "display_name", "player")
MAX_ROWS = 20000


@dataclass(frozen=True, slots=True)
class ImportRow:
    discord_user_id: int
    points: int
    wins: int
    losses: int
    name: str = ""


@dataclass(frozen=True, slots=True)
class ParsedImport:
    rows: list[ImportRow]
    problems: list[str]


def _number(value: str) -> int:
    cleaned = value.strip().replace(",", "")
    return int(float(cleaned)) if cleaned else 0


def _column(header: list[str], names: tuple[str, ...]) -> int | None:
    lowered = [cell.strip().lower().replace(" ", "_").replace("-", "_") for cell in header]
    for name in names:
        if name in lowered:
            return lowered.index(name)
    return None


def parse_csv(text: str) -> ParsedImport:
    """Rows of discord ID, points, wins and losses. A header row may name the columns (any of
    `ID_COLUMNS`, `POINTS_COLUMNS`, wins, losses and optionally a name); without one, they're
    read in that order."""
    lines = list(csv.reader(io.StringIO(text.lstrip("﻿"))))
    lines = [line for line in lines if any(cell.strip() for cell in line)]
    if not lines:
        raise InvalidAction("That file is empty.")
    if len(lines) > MAX_ROWS:
        raise InvalidAction(f"That file has more than {MAX_ROWS} rows.")
    header = lines[0]
    columns = {
        "id": _column(header, ID_COLUMNS),
        "points": _column(header, POINTS_COLUMNS),
        "wins": _column(header, ("wins", "win", "w")),
        "losses": _column(header, ("losses", "loss", "l")),
        "name": _column(header, NAME_COLUMNS),
    }
    if columns["id"] is not None and columns["points"] is not None:
        body = lines[1:]
    else:
        columns = {"id": 0, "points": 1, "wins": 2, "losses": 3, "name": None}
        body = lines

    rows: dict[int, ImportRow] = {}
    problems: list[str] = []
    for number, line in enumerate(body, start=2 if body is not lines else 1):

        def cell(key: str, line: list[str] = line) -> str:
            index = columns[key]
            return line[index] if index is not None and index < len(line) else ""

        try:
            discord_id = int(cell("id").strip().strip("<@!>"))
            points = _number(cell("points"))
            wins, losses = _number(cell("wins")), _number(cell("losses"))
        except ValueError:
            problems.append(f"Line {number}: couldn't read it.")
            continue
        if discord_id <= 0 or wins < 0 or losses < 0:
            problems.append(f"Line {number}: an ID, wins or losses isn't valid.")
            continue
        if discord_id in rows:
            problems.append(f"Line {number}: {discord_id} is listed twice; the later line counts.")
        rows[discord_id] = ImportRow(discord_id, points, wins, losses, cell("name").strip()[:100])
    return ParsedImport(list(rows.values()), problems)


def preview_lines(community: Community, parsed: ParsedImport) -> list[str]:
    """What an import would do, for the host to confirm."""
    known = set(
        Player.objects.filter(
            discord_user_id__in=[row.discord_user_id for row in parsed.rows]
        ).values_list("discord_user_id", flat=True)
    )
    lines = [
        f"Import NeatQueue points for {len(parsed.rows)} players "
        f"({len(known)} have used this bot already).",
        "This replaces any earlier import for this season, turns the interim on, and rebuilds "
        "everyone's points from these plus the matches played here. Players not listed start "
        f"at {runtime.of(community).interim_start_points}.",
    ]
    top = sorted(parsed.rows, key=lambda row: -row.points)[:5]
    if top:
        lines.append(
            "Highest: "
            + ", ".join(f"{row.name or row.discord_user_id} {row.points}" for row in top)
        )
    return lines


def encode_rows(rows: list[ImportRow]) -> list[list[object]]:
    return [[r.discord_user_id, r.points, r.wins, r.losses, r.name] for r in rows]


def decode_rows(data: list[list[object]]) -> list[ImportRow]:
    return [
        ImportRow(int(str(i)), int(str(p)), int(str(w)), int(str(lo)), str(n))
        for i, p, w, lo, n in data
    ]


@transaction.atomic
def apply_import(community: Community, rows: list[ImportRow]) -> int:
    """Replace the season's imported NeatQueue values with these, turn the interim on and
    rebuild the points. Players not listed start at the default. Returns players imported."""
    lock_community(community.pk)
    season = open_season(community)
    moment = now()
    InterimRating.objects.filter(season=season).update(
        imported_points=None, imported_wins=0, imported_losses=0, imported_at=None
    )
    for row in rows:
        player, _created = Player.objects.get_or_create(
            discord_user_id=row.discord_user_id,
            defaults={"display_name": row.name or str(row.discord_user_id)},
        )
        InterimRating.objects.update_or_create(
            season=season,
            player=player,
            defaults={
                "imported_points": row.points,
                "imported_wins": row.wins,
                "imported_losses": row.losses,
                "imported_at": moment,
                "points": row.points,
            },
        )
    runtime.update(community, interim_points=True)
    rebuild(season)
    from league.services import leaderboards

    leaderboards.request(community)
    return len(rows)


@transaction.atomic
def set_enabled(community: Community, on: bool) -> None:
    lock_community(community.pk)
    runtime.update(community, interim_points=on)
    if on:
        rebuild(open_season(community))
    from league.services import leaderboards

    leaderboards.request(community)
