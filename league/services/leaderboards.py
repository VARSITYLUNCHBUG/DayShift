"""The rating players see: NeatQueue's points during the interim, OpenSkill's rating after.

The #leaderboard channel lists every player in the league with their rating and win rate, and
/leaderboard shows a player their own line of it. Both read from here, as do the boards and
results.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from league.models import (
    Community,
    InterimRating,
    MatchParticipant,
    Player,
    PlayerRating,
    Season,
)
from league.services import interim
from league.services.common import request_render


@dataclass(frozen=True, slots=True)
class Shown:
    rating: int
    wins: int
    losses: int

    @property
    def games(self) -> int:
        return self.wins + self.losses

    @property
    def win_rate(self) -> float | None:
        return self.wins / self.games if self.games else None


def shown(season: Season, player_ids: Collection[int]) -> dict[int, Shown]:
    """What players see as each player's rating and record."""
    ids = list(player_ids)
    if interim.enabled(season.community_id):
        found = interim.standings(season, ids)
        start = interim.start_points(season)
        return {
            pid: Shown(found[pid].points, found[pid].wins, found[pid].losses)
            if pid in found
            else Shown(start, 0, 0)
            for pid in ids
        }
    rows = {
        row.player_id: row for row in PlayerRating.objects.filter(season=season, player_id__in=ids)
    }
    return {
        pid: Shown(rows[pid].rating, rows[pid].wins, rows[pid].losses)
        if pid in rows
        else Shown(season.start_rating, 0, 0)
        for pid in ids
    }


@dataclass(frozen=True, slots=True)
class Row:
    rank: int
    player_id: int
    name: str
    rating: int
    wins: int
    losses: int

    @property
    def win_rate(self) -> float | None:
        games = self.wins + self.losses
        return self.wins / games if games else None


def members(season: Season) -> set[int]:
    """Everyone in the league this season: a rating this season (played or seeded), a NeatQueue
    import, or any match on this server. An admin login that never joined isn't one."""
    ids = set(PlayerRating.objects.filter(season=season).values_list("player_id", flat=True))
    ids |= set(InterimRating.objects.filter(season=season).values_list("player_id", flat=True))
    ids |= set(
        MatchParticipant.objects.filter(match__community_id=season.community_id).values_list(
            "player_id", flat=True
        )
    )
    return ids


def table(season: Season) -> list[Row]:
    """Everyone in the league, best first, those who haven't played at the start rating. Ties
    share the order of their names."""
    ids = members(season)
    names = dict(
        Player.objects.filter(pk__in=ids, is_active=True).values_list("pk", "display_name")
    )
    records = shown(season, list(names))
    entries = [
        (pid, names[pid], record.rating, record.wins, record.losses)
        for pid, record in records.items()
    ]
    entries.sort(key=lambda entry: (-entry[2], entry[1].lower(), entry[0]))
    return [
        Row(index + 1, player_id, name, rating, wins, losses)
        for index, (player_id, name, rating, wins, losses) in enumerate(entries)
    ]


def player_row(season: Season, player: Player) -> tuple[Row | None, int]:
    """This player's line of the table, if they're on it, and how many players are."""
    rows = table(season)
    return next((row for row in rows if row.player_id == player.pk), None), len(rows)


def label(community: Community | int) -> str:
    """What the shown number is called."""
    return "Points" if interim.enabled(community) else "Rating"


LANE = "leaderboard:{}"


def request(community: Community) -> None:
    """Refresh the #leaderboard channel. Requests coalesce, so call it as often as needed."""
    request_render(community, "render_leaderboard", lane=LANE.format(community.pk))


REFRESH_SECONDS = 3600


def request_all() -> int:
    """The hourly refresh: redraw every server's leaderboard. Returns how many were asked for."""
    communities = list(Community.objects.exclude(leaderboard_channel_id=None))
    for community in communities:
        request(community)
    return len(communities)


def save_messages(community_id: int, message_ids: list[int]) -> None:
    Community.objects.filter(pk=community_id).update(leaderboard_message_ids=message_ids)
