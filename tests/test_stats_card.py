"""The /stats card: its numbers, its place on the leaderboard, and a phone's width."""

from __future__ import annotations

from bot.renderers.leaderboard import page_text
from bot.renderers.stats import render_stats
from league.models import Community, Player, Season
from league.services import boards, leaderboards
from league.services.boards import PlayerStats
from tests.factories import played


def _stats(**overrides: object) -> PlayerStats:
    base: dict[str, object] = {
        "name": "Kestrel",
        "rating": 1240,
        "games": 1,
        "wins": 1,
        "losses": 0,
        "rank": 3,
        "ranked": 13,
        "recent": [(4, 56, 1240), (0, 50, 1184)],
        "season": "Season 1",
        "placement": "placing 1/10",
        "mvps": 1,
        "strikes": "No strikes.",
        "captain": "can captain",
    }
    base.update(overrides)
    return PlayerStats(**base)  # type: ignore[arg-type]


def test_the_card_reads_cleanly() -> None:
    text = page_text(render_stats(_stats(), "Steam: **kestrel**, verified in a match."))
    assert text.startswith("## Kestrel\n-# #3 of 13 on the leaderboard · Season 1")
    assert "> **Rating** __1240__\n" in text
    assert "> **Played** 1 match\n" in text  # One match, not "1 matches".
    assert "> **Record** 1-0 · 100% won" in text
    assert "> **Placement** 1/10" in text
    assert "> **Awards** 🏅 1 MVP · ⭐ 0 key" in text
    assert "**Strikes** No strikes.\n**Captain** can captain." in text
    assert "> **+56** · __1240__ · match #4\n> **+50** · __1184__ · staff" in text
    assert "```" not in text  # Quote blocks, like the leaderboard.


def test_someone_off_the_leaderboard_is_told_so() -> None:
    text = page_text(render_stats(_stats(rank=None, games=0, wins=0, recent=[]), ""))
    assert "-# Not on the leaderboard yet · Season 1" in text
    assert "> **Played** 0 matches" in text
    assert "Record" not in text and "Recent changes" not in text


def test_stats_and_the_leaderboard_agree_on_a_players_place(
    league: Community, players: list[Player]
) -> None:
    """One match is enough to be listed on #leaderboard, so /stats ranks them too."""
    played(league, players, "A", 1)
    season = Season.objects.open_for(league)
    for player in players:
        row, total = leaderboards.player_row(season, player)
        stats = boards.player_stats(season, player)
        assert row is not None
        assert (stats.rank, stats.ranked) == (row.rank, total)
