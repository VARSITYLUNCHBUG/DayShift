"""What open testing asked for after the first live matches: the report ends the game for its
players, the report form's required match ID, the stats reply under the result, the draft
board's teams and colours, hero icons in text, and names in any script on the leaderboard."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import discord
import pytest

from bot.effects.gateway import TEXT_PUGS, VOICE_VIEWER, DiscordGateway
from bot.renderers import fonts, leaderboard_image, match_stats, style
from bot.renderers.board import render_board
from league.domain.engine import Status
from league.models import Community, Match, OutboxEffect, Player
from league.models.matches import ResourceKind
from league.services import api_results, boards, effects, queue, results, steam
from league.services.leaderboards import Row
from tests.helpers import fresh, image, to_champion_draft, to_in_progress

FIXTURE = Path(__file__).parent / "fixtures" / "deadlock_api_sample.json"
DEADLOCK_ID = 900000001


def _game_on(league: Community, players: list[Player]) -> Match:
    for player in players:
        queue.join(league.pk, player)
    return to_in_progress(Match.objects.get())


# --- The first report ends the game ----------------------------------------------------------


def test_the_first_report_frees_every_player_and_empties_team_voice(
    league: Community, players: list[Player]
) -> None:
    match = _game_on(league, players)
    status = results.submit_report(match.pk, match.captain_of("A").player, "A", None, DEADLOCK_ID)
    assert status == Status.AWAITING_CONFIRMATION
    assert not match.participants.filter(is_active=True).exists()
    assert OutboxEffect.objects.filter(match=match, kind="cleanup_voice").count() == 1
    assert fresh(match).deadlock_match_id == DEADLOCK_ID  # Recorded on the match.

    # Free to queue while the other captain decides.
    queue.join(league.pk, players[0])

    # The captains can still settle it, and finishing doesn't run the voice cleanup twice.
    results.confirm(match.pk, match.captain_of("B").player)
    assert fresh(match).status == Status.COMPLETED
    assert OutboxEffect.objects.filter(match=match, kind="cleanup_voice").count() == 1


def test_a_reported_match_can_still_be_disputed(league: Community, players: list[Player]) -> None:
    match = _game_on(league, players)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1), DEADLOCK_ID)
    results.dispute(match.pk, match.captain_of("B").player, "We won")
    assert fresh(match).status == Status.DISPUTED


def test_a_reported_match_no_longer_holds_a_queue_slot(
    league: Community, players: list[Player]
) -> None:
    from league.services import runtime

    runtime.update(league, max_concurrent_matches=1)
    match = _game_on(league, players)
    results.submit_report(match.pk, match.captain_of("A").player, "A", None, DEADLOCK_ID)
    for player in players:  # The same twelve, straight back in.
        queue.join(league.pk, player)
    assert Match.objects.filter(status=Status.READY_CHECK).exists()


# --- The stats reply -------------------------------------------------------------------------


def _metadata() -> dict[str, Any]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


@pytest.fixture
def reported(league: Community, players: list[Player]) -> Match:
    """A reported game whose players are linked to the fixture match's accounts."""
    match = _game_on(league, players)
    hk = match.hidden_king_team
    teams: dict[int, list[int]] = {0: [], 1: []}
    for player in _metadata()["match_info"]["players"]:
        teams[player["team"]].append(player["account_id"])
    for team, accounts in ((hk, teams[0]), ("B" if hk == "A" else "A", teams[1])):
        rows = match.participants.filter(team=team).order_by("id")
        for row, account in zip(rows, accounts, strict=True):
            steam.link(row.player, account)
    results.submit_report(match.pk, match.captain_of(hk).player, hk, None, DEADLOCK_ID)
    return fresh(match)


def _post_results(match: Match) -> None:
    effects.record_resource(match.pk, ResourceKind.RESULTS_MESSAGE, 5555)
    api_results.request_stats_for(match.pk)


def test_stats_reply_waits_for_the_results_post(reported: Match) -> None:
    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, _metadata(), {100000004: "Vexa"})
    assert not OutboxEffect.objects.filter(kind="post_api_stats").exists()
    _post_results(reported)
    effect = OutboxEffect.objects.get(kind="post_api_stats")
    assert effect.payload == {"check_id": check.pk}
    _post_results(reported)  # A retry of the post asks again: still one reply.
    assert OutboxEffect.objects.filter(kind="post_api_stats").count() == 1


def test_stats_arriving_after_the_post_reply_at_once(reported: Match) -> None:
    _post_results(reported)
    assert not OutboxEffect.objects.filter(kind="post_api_stats").exists()
    api_results.record_metadata(reported.pk, DEADLOCK_ID, _metadata())
    assert OutboxEffect.objects.filter(kind="post_api_stats").count() == 1


def test_the_stats_reply_reads_like_the_scoreboard(reported: Match) -> None:
    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, _metadata(), {100000004: "Vexa"})
    stats = api_results.match_stats(check.pk)
    assert stats is not None
    assert len(stats.hk) == 6 and len(stats.am) == 6
    assert stats.winner == "hk"  # The fixture's winning_team is 0.
    names = {row.name for row in stats.hk + stats.am}
    assert "Vexa" in names  # Steam's name first, then the name linked here.
    text = "\n".join(block for block in match_stats.blocks(stats) if block)
    assert text.startswith(f"## Deadlock match {DEADLOCK_ID}: {style.HK_EMOJI} The Hidden King")
    assert "Standard match · 36:50 · <t:1793912493:f>" in text
    assert "**Best in the match**" in text
    first_team = text.split("\n")[2]
    assert first_team.startswith(f"🏆 {style.HK_EMOJI} **The Hidden King**")


def test_a_wrong_match_id_posts_no_stats(reported: Match) -> None:
    for row in reported.participants.roster():
        steam.unlink(row.player)
    steam.link(reported.captain_of("A").player, 123)  # In none of the match's slots.
    _post_results(reported)
    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, _metadata())
    assert api_results.match_stats(check.pk) is None
    assert not OutboxEffect.objects.filter(kind="post_api_stats").exists()


@pytest.mark.parametrize(
    ("value", "shown"),
    [(37_000, "37k"), (9_241, "9.2k"), (4_978, "5k"), (797, "797"), (11_690, "12k"), (0, "0")],
)
def test_stats_numbers_round_like_the_scoreboard(value: int, shown: str) -> None:
    assert match_stats.k(value) == shown


# --- The draft board -------------------------------------------------------------------------


def _board_text(match: Match) -> str:
    view = render_board(boards.board_state(match.pk))
    return "\n".join(
        item.content for item in view.walk_children() if isinstance(item, discord.ui.TextDisplay)
    )


def test_the_hero_draft_shows_both_teams(league: Community, players: list[Player]) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = to_champion_draft(Match.objects.get())
    text = _board_text(match)
    for player in match.participants.roster():
        assert player.player.display_name in text
    assert text.count("👑") >= 2  # Each captain marked.


def test_ban_buttons_are_not_red(league: Community, players: list[Player]) -> None:
    from bot.renderers.board import render_pickers

    for player in players:
        queue.join(league.pk, player)
    match = to_champion_draft(Match.objects.get())
    state = boards.board_state(match.pk)
    assert state.step_action == "ban"
    styles = {
        child.style
        for view in render_pickers(state)
        for child in view.walk_children()
        if isinstance(child, discord.ui.Button) and not child.disabled
    }
    assert discord.ButtonStyle.danger not in styles


def test_hero_text_uses_the_custom_icon_when_set() -> None:
    assert style.hero_emoji_text("🔥", 1302512783283191879) == "<:h:1302512783283191879>"
    assert style.hero_emoji_text("🔥", None) == "🔥"
    assert style.hero_emoji_text("", None) == ""


# --- Match channels open to the PUGs role ----------------------------------------------------


def test_the_pugs_role_talks_in_text_but_only_watches_voice() -> None:
    guild = discord.Object(id=1)
    gateway = DiscordGateway.__new__(DiscordGateway)
    gateway.client = type("C", (), {"user": discord.Object(id=2)})()  # type: ignore[assignment]
    fake_guild: Any = type("G", (), {"id": 1, "default_role": "everyone"})()
    overwrites = gateway._overwrites(
        fake_guild, [10], [20], discord.PermissionOverwrite(), discord.PermissionOverwrite(),
        [30], TEXT_PUGS,
    )  # fmt: skip
    viewer = next(v for k, v in overwrites.items() if getattr(k, "id", None) == 30)
    assert viewer.view_channel is True and viewer.send_messages is True
    # No PUGs role: the guild's own ID is @everyone, which can then read.
    overwrites = gateway._overwrites(
        fake_guild, [], [], discord.PermissionOverwrite(), discord.PermissionOverwrite(),
        [guild.id], VOICE_VIEWER,
    )  # fmt: skip
    assert overwrites["everyone"].view_channel is True
    assert overwrites["everyone"].connect is False


# --- Names in any script ---------------------------------------------------------------------

FIGTREE = str(Path(fonts.__file__).resolve().parent.parent / "assets" / "fonts" / "Figtree.ttf")


def test_latin_stays_in_the_brand_font() -> None:
    assert list(fonts.runs("Ñandú jake", FIGTREE)) == [(None, "Ñandú jake")]


def test_a_combining_mark_stays_with_its_letter() -> None:
    chunks = [text for _face, text in fonts.runs("éx", FIGTREE)]
    assert "".join(chunks) == "éx"
    assert not any(chunk.startswith("́") for chunk in chunks)


def test_the_leaderboard_draws_any_name() -> None:
    # Lookalike letters are the point here, so the ambiguous-character lint doesn't apply.
    names = ["SNΞK", "Зоосд", "김치맨", "ゆうき", "黑龙", "𝓡𝓸𝓬𝓴𝓮𝓽", "jake 🔥", "꧁x꧂", "مرحبا", "★"]  # noqa: RUF001
    rows = [Row(i, i, name, 2000 - i, 1, 1) for i, name in enumerate(names, 1)]
    png = leaderboard_image.render(
        rows, season_name="Season Ω", rating_label="Rating", total=10, updated_at=datetime.now(UTC)
    )
    assert png.startswith(b"\x89PNG")


def test_report_open_is_one_trip_to_the_database(league: Community, players: list[Player]) -> None:
    """The form must open inside Discord's 3 seconds, so its checks share one trip."""
    from bot.handlers import results as handlers

    match = _game_on(league, players)
    captain = match.captain_of("A").player
    player, captains, roster = handlers._report_form(
        match.pk, captain.discord_user_id, captain.display_name
    )
    assert player == captain and set(captains) == {"A", "B"} and len(roster) == 12


def test_queue_renders_wait_a_moment_to_fold_bursts(
    league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    from league.services import common

    monkeypatch.setattr(common, "QUEUE_RENDER_DELAY_SECONDS", 1.5)
    for player in [Player.objects.from_discord(20_000_000 + n, f"Q{n}") for n in range(5)]:
        queue.join(league.pk, player)
    renders = OutboxEffect.objects.filter(kind="render_queue")
    assert renders.count() == 1  # Five joins, one edit.
    assert renders.get().run_after > common.now()
