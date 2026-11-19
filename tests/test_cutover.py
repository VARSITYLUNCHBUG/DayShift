"""The cutover flow: captain check-in, automatic lobbies, player swaps, the NeatQueue interim
and the leaderboard."""

from __future__ import annotations

import pytest
from django.utils import timezone

from bot.renderers.board import render_board
from bot.renderers.leaderboard import own_text, page_text, pages
from league.domain.engine import Status
from league.domain.errors import InvalidAction, NotAllowed, StaleAction
from league.models import Community, InterimRating, Match, OutboxEffect, Player, PlayerSwap, Season
from league.models.swaps import SwapStatus
from league.services import (
    boards,
    deadlines,
    draft,
    interim,
    leaderboards,
    lobby,
    queue,
    runtime,
    swaps,
)
from tests.conftest import Clock, make_player
from tests.factories import played
from tests.helpers import (
    check_in_captains,
    fail_api_lobby,
    finish,
    fresh,
    ready_all,
    run_champion_draft,
    run_player_draft,
    settle_coinflip_for,
    to_champion_draft,
    to_in_progress,
    vote_only,
)

pytestmark = pytest.mark.django_db


def _texts(view: object) -> str:
    """Every TextDisplay's content in a rendered view, joined."""
    out = []

    def walk(item: object) -> None:
        content = getattr(item, "content", None)
        if isinstance(content, str):
            out.append(content)
        for child in getattr(item, "children", []) or []:
            walk(child)

    for child in view.children:  # type: ignore[attr-defined]
        walk(child)
    return "\n".join(out)


def _custom_ids(view: object) -> list[str]:
    ids = []

    def walk(item: object) -> None:
        custom_id = getattr(item, "custom_id", None)
        if isinstance(custom_id, str):
            ids.append(custom_id)
        for child in getattr(item, "children", []) or []:
            walk(child)

    for child in view.children:  # type: ignore[attr-defined]
        walk(child)
    return ids


# --- Captain check-in ------------------------------------------------------------------------


def test_the_vote_leads_to_a_check_in_not_the_draft(voting: Match) -> None:
    match = vote_only(voting)
    assert match.status == Status.CAPTAIN_CHECKIN
    assert match.participants.filter(is_captain=True).count() == 2
    assert match.deadline_at is not None
    pings = OutboxEffect.objects.filter(match=match, kind="ping")
    assert any("I'm here" in str(effect.payload["text"]) for effect in pings)


def test_both_captains_checking_in_starts_the_player_draft(voting: Match) -> None:
    match = vote_only(voting)
    first = match.captain_of("A").player
    lobby.check_in(match.pk, first)
    assert fresh(match).status == Status.CAPTAIN_CHECKIN
    with pytest.raises(InvalidAction):
        lobby.check_in(match.pk, first)
    lobby.check_in(match.pk, match.captain_of("B").player)
    assert fresh(match).status == Status.PLAYER_DRAFT


def test_only_a_captain_can_check_in(voting: Match) -> None:
    match = vote_only(voting)
    player = match.participants.filter(is_captain=False).first().player
    with pytest.raises(NotAllowed):
        lobby.check_in(match.pk, player)


def test_a_captain_who_misses_check_in_is_replaced(voting: Match, clock: Clock) -> None:
    match = vote_only(voting)
    stays = match.captain_of("A")
    gone = match.captain_of("B")
    lobby.check_in(match.pk, stays.player)
    clock.advance(61)
    deadlines.tick()
    match = fresh(match)
    assert match.status == Status.CAPTAIN_CHECKIN
    heir = match.captain_of("B")
    assert heir.player_id != gone.player_id
    gone.refresh_from_db()
    assert gone.missed_checkin and not gone.is_captain and gone.team == ""
    assert match.captain_of("A").checked_in_at is not None
    lobby.check_in(match.pk, heir.player)
    assert fresh(match).status == Status.PLAYER_DRAFT


def test_with_nobody_left_to_ask_the_draft_starts(voting: Match, clock: Clock) -> None:
    match = vote_only(voting)
    # Everyone who isn't captain has already missed it once, so there's no one to ask.
    match.participants.filter(is_captain=False).update(missed_checkin=True)
    clock.advance(61)
    deadlines.tick()
    assert fresh(match).status == Status.PLAYER_DRAFT


def test_the_board_shows_the_check_in(voting: Match) -> None:
    match = vote_only(voting)
    lobby.check_in(match.pk, match.captain_of("A").player)
    view = render_board(boards.board_state(match.pk))
    text = _texts(view)
    assert "I'm here" in text and "✅" in text and "⏳" in text
    assert any(":checkin:" in custom_id for custom_id in _custom_ids(view))


# --- Coinflip ------------------------------------------------------------------------------------


def test_the_hidden_king_always_bans_first(voting: Match) -> None:
    match = run_player_draft(check_in_captains(vote_only(voting)))
    loser = "B" if match.coinflip_winner == "A" else "A"
    match = settle_coinflip_for(match, hk_team=loser)
    assert match.hidden_king_team == loser
    assert match.champion_first_pick == loser


# --- Automatic lobbies ---------------------------------------------------------------------------


def test_the_bot_always_asks_deadlock_api_for_the_lobby(popped: Match) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    assert match.status == Status.LOBBY_CODE
    assert OutboxEffect.objects.filter(match=match, kind="create_api_lobby").exists()
    with pytest.raises(StaleAction, match="creating the lobby"):
        draft.submit_lobby_code(match.pk, match.lobby_code_host, "ABC123")
    ids = _custom_ids(render_board(boards.board_state(match.pk)))
    assert not any(":code_open:" in custom_id for custom_id in ids)


def test_an_api_lobby_starts_the_game(popped: Match) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    assert draft.accept_api_lobby(match.pk, "party-1", "XYZ999")
    match = fresh(match)
    assert match.status == Status.IN_PROGRESS
    assert match.lobby_code == "XYZ999"
    # Found in the live run: the lobby came back before the board showed the draft's end, so
    # nobody saw its name and GLHF. They stay up until a captain starts the match.
    from league.domain.engine import draft_name

    text = _texts(render_board(boards.board_state(match.pk)))
    assert draft_name(match.rng_seed) in text and "# GLHF" in text
    draft.mark_api_started(match.pk, match.captain_of("A").player)
    assert "# GLHF" not in _texts(render_board(boards.board_state(match.pk)))


def test_a_failed_api_lobby_asks_the_host_with_a_fresh_clock(popped: Match, clock: Clock) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    clock.advance(100)
    match = fail_api_lobby(match)
    assert match.api_lobby_failed
    assert (match.deadline_at - clock.now()).total_seconds() > 170
    assert any(":code_open:" in i for i in _custom_ids(render_board(boards.board_state(match.pk))))
    # A late answer from the API no longer replaces the host's lobby.
    assert not draft.accept_api_lobby(match.pk, "party-1", "LATE01")
    draft.submit_lobby_code(match.pk, match.lobby_code_host, "ABC123")
    assert fresh(match).status == Status.IN_PROGRESS


def test_no_api_answer_in_time_counts_as_a_failure(popped: Match, clock: Clock) -> None:
    match = run_champion_draft(to_champion_draft(popped))
    host = match.lobby_code_host
    clock.advance(181)
    deadlines.tick()
    match = fresh(match)
    assert match.status == Status.LOBBY_CODE
    assert match.api_lobby_failed
    assert match.lobby_code_host == host


# --- Player swaps --------------------------------------------------------------------------------


def _at_champion_draft(popped: Match) -> Match:
    match = to_champion_draft(popped)
    assert match.status == Status.CHAMPION_DRAFT
    return match


def _non_captain(match: Match, team: str) -> Player:
    return match.participants.filter(team=team, is_captain=False).order_by("id").first().player


def test_captains_can_swap_two_players(popped: Match) -> None:
    match = _at_champion_draft(popped)
    a, b = match.captain_of("A").player, match.captain_of("B").player
    give, take = _non_captain(match, "A"), _non_captain(match, "B")
    swap = swaps.propose(match.pk, a, give.pk, take.pk)
    with pytest.raises(NotAllowed):
        swaps.answer(match.pk, a, swap.pk, True)  # The one who asked can't accept.
    swaps.answer(match.pk, b, swap.pk, True)
    assert match.participants.get(player=give).team == "B"
    assert match.participants.get(player=take).team == "A"
    assert PlayerSwap.objects.get(pk=swap.pk).status == SwapStatus.ACCEPTED
    assert OutboxEffect.objects.filter(match=match, kind="swap_team_voice").exists()


def test_a_swap_can_be_declined_and_lapses(popped: Match, clock: Clock) -> None:
    match = _at_champion_draft(popped)
    a, b = match.captain_of("A").player, match.captain_of("B").player
    give, take = _non_captain(match, "A"), _non_captain(match, "B")
    first = swaps.propose(match.pk, a, give.pk, take.pk)
    with pytest.raises(InvalidAction):
        swaps.propose(match.pk, b, take.pk, give.pk)  # One at a time.
    swaps.answer(match.pk, b, first.pk, False)
    assert PlayerSwap.objects.get(pk=first.pk).status == SwapStatus.DECLINED
    second = swaps.propose(match.pk, b, take.pk, give.pk)
    clock.advance(61)
    deadlines.tick()
    assert PlayerSwap.objects.get(pk=second.pk).status == SwapStatus.EXPIRED
    assert match.participants.get(player=give).team == "A"


def test_captains_and_strangers_cant_be_swapped(popped: Match) -> None:
    match = _at_champion_draft(popped)
    a = match.captain_of("A").player
    with pytest.raises(InvalidAction):
        swaps.propose(match.pk, a, _non_captain(match, "A").pk, match.captain_of("B").player_id)
    with pytest.raises(NotAllowed):
        swaps.propose(match.pk, _non_captain(match, "A"), 1, 2)


def test_swaps_close_once_the_game_starts(popped: Match) -> None:
    match = to_in_progress(popped)
    with pytest.raises(StaleAction):
        swaps.own_options(match.pk, match.captain_of("A").player)
    assert not boards.board_state(match.pk).can_swap


def test_the_board_offers_and_shows_a_swap(popped: Match) -> None:
    match = _at_champion_draft(popped)
    assert any(":swap_open:" in i for i in _custom_ids(render_board(boards.board_state(match.pk))))
    swaps.propose(
        match.pk,
        match.captain_of("A").player,
        _non_captain(match, "A").pk,
        _non_captain(match, "B").pk,
    )
    view = render_board(boards.board_state(match.pk))
    assert "offers" in _texts(view)
    assert any(":swap_yes:" in i for i in _custom_ids(view))


# --- NeatQueue interim ---------------------------------------------------------------------------


def test_points_change_is_elo_on_team_averages() -> None:
    assert interim.points_change(True, 1000, 1000, 32) == 16
    assert interim.points_change(False, 1000, 1000, 32) == -16
    assert interim.points_change(True, 1000, 1200, 32) > 16  # An upset pays more.
    assert interim.points_change(True, 1200, 1000, 32) < 16


def test_the_csv_reads_with_or_without_a_header() -> None:
    parsed = interim.parse_csv(
        "Name,Discord ID,MMR,Wins,Losses\nKestrel,111,1240,40,22\nPike,222,980,5,9\n"
    )
    assert [(r.discord_user_id, r.points, r.wins, r.losses, r.name) for r in parsed.rows] == [
        (111, 1240, 40, 22, "Kestrel"),
        (222, 980, 5, 9, "Pike"),
    ]
    plain = interim.parse_csv("333,1100,1,2\nbad,line\n")
    assert [(r.discord_user_id, r.points) for r in plain.rows] == [(333, 1100)]
    assert plain.problems


def test_the_csv_reads_neatqueues_own_leaderboard_export() -> None:
    # The header and cell shapes of NeatQueue's "player_stats_alltime_leaderboard.csv": IDs
    # wrapped as ="..." so spreadsheets keep every digit, MMR with decimals, extra columns.
    parsed = interim.parse_csv(
        "Rank,Player Name,IGN,MMR,Wins,Losses,Total Games,Win Rate,Streak,Peak MMR,"
        "Peak Streak,Player ID,Stats Key,Row Version\n"
        '1,"Kestrel",,1545.6,78,48,126,61.9%,3,1545.6,12,"=""308000000000000001""",'
        '"player_stats","v48582eb3"\n'
        '2,"Pike",,980.2,5,9,14,35.7%,-1,1010.0,2,"=""1025000000000000002""",'
        '"player_stats","v986ca6c7"\n'
    )
    assert not parsed.problems
    assert [(r.discord_user_id, r.points, r.wins, r.losses, r.name) for r in parsed.rows] == [
        (308000000000000001, 1546, 78, 48, "Kestrel"),
        (1025000000000000002, 980, 5, 9, "Pike"),
    ]


def test_import_carries_points_and_matches_move_them(
    league: Community, players: list[Player]
) -> None:
    rows = [interim.ImportRow(p.discord_user_id, 1500, 10, 5) for p in players[:6]]
    assert interim.apply_import(league, rows) == 6
    assert runtime.of(league).interim_points
    season = Season.objects.open_for(league)
    assert interim.standings(season)[players[0].pk] == interim.Standing(1500, 10, 5)

    match = played(league, players, "A", 1)
    changes = interim.match_changes(match)
    assert len(changes) == 12
    winners = set(match.participants.filter(team="A").values_list("player_id", flat=True))
    for player_id, (before, after) in changes.items():
        assert (after > before) == (player_id in winners)
    shown = leaderboards.shown(season, [p.pk for p in players])
    for player in players:
        before, after = changes[player.pk]
        assert shown[player.pk].rating == after
        assert shown[player.pk].games == (16 if player in players[:6] else 1)


def test_a_rescore_rebuilds_the_points(league: Community, players: list[Player]) -> None:
    from league.services import corrections

    interim.set_enabled(league, True)
    match = played(league, players, "A", 1)
    winner = match.participants.filter(team="A").first().player_id
    season = Season.objects.open_for(league)
    assert interim.standings(season)[winner].points > 1000
    corrections.apply_outcome_correction(match.pk, "B", None, "wrong team")
    assert interim.standings(season)[winner].points < 1000


def test_the_interim_off_shows_openskill(league: Community, players: list[Player]) -> None:
    interim.apply_import(league, [interim.ImportRow(players[0].discord_user_id, 1500, 1, 1)])
    season = Season.objects.open_for(league)
    assert leaderboards.shown(season, [players[0].pk])[players[0].pk].rating == 1500
    interim.set_enabled(league, False)
    assert leaderboards.shown(season, [players[0].pk])[players[0].pk].rating == season.start_rating


# --- Leaderboard ---------------------------------------------------------------------------------


def test_the_leaderboard_lists_everyone_with_a_record(
    league: Community, players: list[Player]
) -> None:
    played(league, players, "A", 1)
    season = Season.objects.open_for(league)
    rows = leaderboards.table(season)
    assert len(rows) == 12
    assert [row.rank for row in rows] == list(range(1, 13))
    assert all(row.win_rate in (0.0, 1.0) for row in rows)
    assert OutboxEffect.objects.filter(community=league, kind="render_leaderboard").exists()
    row, total = leaderboards.player_row(season, players[0])
    assert row is not None and total == 12
    assert "of 12" in own_text(row, total, "Rating", 55)
    assert "<#55>" in own_text(None, total, "Rating", 55)


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG")
    return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")


def test_the_leaderboard_shares_players_evenly_over_same_size_images() -> None:
    rows = [leaderboards.Row(i, i, f"Player number {i}", 2000 - i, i, 3) for i in range(1, 24)]
    out = pages(rows, "Points", "Season 1", timezone.now())
    names = [image[0] for _view, image in out]
    assert names == ["leaderboard-1.png", "leaderboard-2.png", "leaderboard-3.png"]
    sizes = set()
    for view, (name, png) in out:
        assert f"attachment://{name}" in str(view.to_components())
        sizes.add(_png_size(png))
    assert sizes == {(2200, 1320)}  # One size for every image, wider than tall.
    assert "`/stats`" in page_text(out[-1][0])
    assert page_text(out[0][0]) == ""  # Only the last message has the footer.


@pytest.mark.parametrize(
    ("players", "groups"),
    [(0, [0]), (7, [7]), (10, [10]), (11, [6, 5]), (13, [7, 6]), (23, [8, 8, 7]), (30, [10] * 3)],
)
def test_players_are_shared_out_as_evenly_as_ten_an_image_allows(
    players: int, groups: list[int]
) -> None:
    from bot.renderers.leaderboard_image import split

    rows = [leaderboards.Row(i, i, f"P{i}", 2000 - i, 1, 1) for i in range(1, players + 1)]
    parts = split(rows)
    assert [len(part) for part in parts] == groups
    assert [row for part in parts for row in part] == rows  # Everyone, in order, once.


def test_an_empty_leaderboard_is_still_one_image() -> None:
    ((_view, (name, png)),) = pages([], "Rating", "Season 1", timezone.now())
    assert name == "leaderboard-1.png" and _png_size(png) == (2200, 1320)


def test_the_leaderboard_lists_everyone_in_the_league(
    league: Community, players: list[Player]
) -> None:
    """Players who haven't played yet are on it at the start rating, highest first; a login that
    never joined the league isn't."""
    played(league, players[:12], "A", 1)
    season = Season.objects.open_for(league)
    newcomer = make_player(40)
    Player.objects.create_superuser("admin", password="pw", discord_user_id=900_000_000_000_000_009)
    from league.services import ratings

    ratings.seed_player(season, newcomer, "mid", actor=None)  # Seeded by staff, not yet played.
    rows = leaderboards.table(season)
    by_id = {row.player_id: row for row in rows}
    assert newcomer.pk in by_id and (by_id[newcomer.pk].wins, by_id[newcomer.pk].losses) == (0, 0)
    assert not Player.objects.filter(username="admin", pk__in=by_id).exists()
    assert [row.rating for row in rows] == sorted((row.rating for row in rows), reverse=True)


def test_the_hourly_refresh_asks_for_every_leaderboard(league: Community) -> None:
    from league.services import community as community_service

    community_service.save_wiring(league.pk, leaderboard_channel_id=4_444)
    OutboxEffect.objects.filter(kind="render_leaderboard").delete()
    assert leaderboards.request_all() == 1
    assert OutboxEffect.objects.filter(community=league, kind="render_leaderboard").exists()
    assert leaderboards.REFRESH_SECONDS == 3600


def test_a_pug_role_guards_the_leaderboard_command() -> None:
    from types import SimpleNamespace

    import discord

    from bot.handlers.permissions import has_pug_role

    community = SimpleNamespace(pug_role_id=42)
    guild = SimpleNamespace(owner_id=1)

    class Member(discord.Member):
        def __init__(self, roles: list[int]) -> None:
            self._roles_list = [SimpleNamespace(id=r) for r in roles]

        @property
        def roles(self) -> list:  # type: ignore[override]
            return self._roles_list

        @property
        def id(self) -> int:  # type: ignore[override]
            return 7

        @property
        def guild_permissions(self) -> discord.Permissions:  # type: ignore[override]
            return discord.Permissions.none()

    def interaction(roles: list[int]) -> SimpleNamespace:
        return SimpleNamespace(user=Member(roles), guild=guild)

    assert has_pug_role(interaction([42]), community)  # type: ignore[arg-type]
    assert not has_pug_role(interaction([5]), community)  # type: ignore[arg-type]
    community.pug_role_id = None
    assert has_pug_role(interaction([]), community)  # type: ignore[arg-type]


def test_queue_still_pops_with_the_new_flow(league: Community) -> None:
    for number in range(1, 13):
        queue.join(league.pk, make_player(number))
    match = Match.objects.get()
    match = ready_all(match)
    assert match.status == Status.CAPTAIN_PHASE
    finished = finish(to_in_progress(match))
    assert finished.status == Status.COMPLETED
    assert InterimRating.objects.count() == 0  # The interim is off by default.
