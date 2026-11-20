"""The HTTP API: matches, a match and its postgame, the ladder, seasons, the private profile and
its share card, unlinking Steam, player search and random drafts.

Profiles are private (the user's rule), so a good part of this checks what can't be read: no
other player's profile, no IDs on the ladder, no stats in search, no Steam IDs anywhere.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Callable, Iterator
from functools import cache
from pathlib import Path
from typing import Any

import pytest
from django.test import Client

from league.domain.engine import Status, draft_name
from league.models import (
    Champion,
    Community,
    Match,
    Player,
    PlayerRating,
    Season,
    SteamAccount,
)
from league.models.api import CheckStatus
from league.models.moderation import PenaltyKind
from league.services import (
    api_results,
    community,
    hero_art,
    interim,
    penalties,
    postgame,
    queue,
    results,
    runtime,
    share_card,
    steam,
)
from league.web.api import reads
from league.web.auth.session import SESSION_KEY
from tests.conftest import make_player
from tests.helpers import fresh, image, play_full_match, to_in_progress

pytestmark = pytest.mark.django_db

DEADLOCK_ID = 140328807
FIXTURE = Path(__file__).parent / "fixtures" / "deadlock" / "match_140328807_metadata.json.gz"

READS = [
    "/api/matches/",
    "/api/matches/?status=recent",
    "/api/matches/1/",
    "/api/matches/1/postgame/",
    "/api/ladder/",
    "/api/seasons/",
    "/api/me/",
    "/api/me/share.png",
    "/api/players/search/?q=pl",
]
POSTS = ["/api/tools/random-draft/", "/api/me/steam/1/unlink/"]


@pytest.fixture(autouse=True)
def web(league: Community, settings: Any) -> Iterator[Community]:
    settings.WEB_GUILD_ID = league.discord_guild_id
    yield league


def client_for(player: Player, **kwargs: Any) -> Client:
    client = Client(**kwargs)
    session = client.session
    session[SESSION_KEY] = player.pk
    session.save()
    return client


def csrf_client(player: Player) -> tuple[Client, str]:
    """A client that sends no CSRF token unless told to, and the token it would send."""
    client = client_for(player, enforce_csrf_checks=True)
    client.get("/api/session/")  # Sets the CSRF cookie, as the SPA's first request does.
    return client, client.cookies["csrftoken"].value


def get(client: Client, path: str, status: int = 200) -> Any:
    response = client.get(path)
    assert response.status_code == status, response.content
    return response.json()


def other_league_match() -> Match:
    """A finished match in another server, played by other people."""
    other = community.ensure(guild_id=4242, name="Elsewhere")
    others = [make_player(number) for number in range(201, 213)]
    return play_full_match(other, others, "B", 9)


@pytest.fixture
def art_for(monkeypatch: pytest.MonkeyPatch) -> Callable[[Champion], None]:
    """Only this hero has a file in the art pack."""

    def only(champion: Champion) -> None:
        monkeypatch.setattr(hero_art, "available", lambda: frozenset({champion.slug}))

    return only


# --- Sign-in, caching and CSRF ----------------------------------------------------------------


@pytest.mark.parametrize("path", READS)
def test_every_read_needs_a_signed_in_player(path: str) -> None:
    response = Client().get(path)
    assert response.status_code == 401
    assert response.json() == {"error": "signed-out"}


@pytest.mark.parametrize("path", POSTS)
def test_every_post_needs_a_signed_in_player(path: str) -> None:
    response = Client().post(path)
    assert response.status_code == 401 and response.json() == {"error": "signed-out"}


def test_an_inactive_player_is_signed_out() -> None:
    player = make_player(1)
    client = client_for(player)
    Player.objects.filter(pk=player.pk).update(is_active=False)
    assert client.get("/api/me/").status_code == 401


@pytest.mark.parametrize("path", ["/api/matches/", "/api/ladder/", "/api/me/", "/api/seasons/"])
def test_reads_are_private_and_rechecked(path: str) -> None:
    response = client_for(make_player(1)).get(path)
    assert response.status_code == 200
    assert response["Cache-Control"] == "private, no-cache"


def test_a_server_without_an_open_season_says_so(league: Community) -> None:
    Season.objects.filter(community=league).update(ended_at="2026-11-01T00:00:00Z")
    response = client_for(make_player(1)).get("/api/ladder/")
    assert response.status_code == 503 and response.json() == {"error": "not-set-up"}


def test_a_server_the_bot_never_set_up_says_so(settings: Any) -> None:
    settings.WEB_GUILD_ID = 123
    response = client_for(make_player(1)).get("/api/matches/")
    assert response.status_code == 503 and response.json() == {"error": "not-set-up"}


def test_the_session_is_under_api_too() -> None:
    player = make_player(1)
    response = client_for(player).get("/api/session/")
    assert response.status_code == 200 and response.json()["signed_in"] is True
    assert response.json()["player"]["id"] == str(player.pk)
    assert "csrftoken" in response.cookies


def test_random_draft_needs_the_csrf_token() -> None:
    client, token = csrf_client(make_player(1))
    assert client.post("/api/tools/random-draft/").status_code == 403
    response = client.post("/api/tools/random-draft/", headers={"X-CSRFToken": token})
    assert response.status_code == 200
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("path", POSTS)
def test_posts_are_post_only(path: str) -> None:
    assert client_for(make_player(1)).get(path).status_code == 405


@pytest.mark.parametrize("path", ["/api/matches/", "/api/me/", "/api/ladder/"])
def test_reads_are_get_only(path: str) -> None:
    assert client_for(make_player(1)).post(path).status_code == 405


# --- Matches ----------------------------------------------------------------------------------


def test_matches_lists_live_and_finished_ones_with_the_viewers_team(
    league: Community, players: list[Player]
) -> None:
    done = play_full_match(league, players, "A", 1)
    for player in players:
        queue.join(league.pk, player)
    live = Match.objects.filter(community=league).exclude(pk=done.pk).get()
    viewer = players[0]
    client = client_for(viewer)

    live_rows = get(client, "/api/matches/?status=live")
    assert [row["id"] for row in live_rows["matches"]] == [str(live.pk)]
    assert live_rows["next_cursor"] is None
    row = live_rows["matches"][0]
    assert row["status"] == Status.READY_CHECK and row["kind"] == "ranked"
    assert row["your_team"] is None  # No teams before the draft.

    recent = get(client, "/api/matches/?status=recent")["matches"]
    assert [row["id"] for row in recent] == [str(done.pk)]
    row = recent[0]
    assert row["winner"] == "A" and row["your_team"] == done.participants.get(player=viewer).team
    assert row["captains"]["A"] and row["team_names"]["A"] == f"{row['captains']['A']}'s Team"
    assert row["ended_at"].endswith("Z") and row["mode_name"]
    assert row["draft_name"] == draft_name(done.rng_seed)
    hk = done.hidden_king_team
    assert row["sides"] == {hk: "hk", ("B" if hk == "A" else "A"): "am"}


def test_matches_pages_with_a_cursor(
    league: Community, players: list[Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    first = play_full_match(league, players, "A", 1)
    second = play_full_match(league, players, "B", 2)
    monkeypatch.setattr(reads, "PAGE", 1)
    client = client_for(players[0])
    page = get(client, "/api/matches/?status=recent")
    assert [row["id"] for row in page["matches"]] == [str(second.pk)]
    assert page["next_cursor"] == str(second.pk)
    page = get(client, f"/api/matches/?status=recent&cursor={page['next_cursor']}")
    assert [row["id"] for row in page["matches"]] == [str(first.pk)]
    assert page["next_cursor"] is None


def test_mine_lists_only_the_viewers_matches(league: Community, players: list[Player]) -> None:
    theirs = play_full_match(league, players, "A", 1)
    others = [make_player(number) for number in range(31, 43)]
    other = play_full_match(league, others, "B", 2)
    for path, viewer, wanted in [
        ("/api/matches/?status=recent&mine=1", players[0], [theirs]),
        ("/api/matches/?status=recent&mine=1", others[0], [other]),
        ("/api/matches/?status=recent&mine=0", players[0], [other, theirs]),
    ]:
        rows = get(client_for(viewer), path)["matches"]
        assert [row["id"] for row in rows] == [str(match.pk) for match in wanted], path


@pytest.mark.parametrize(
    "query", ["status=done", "cursor=abc", "cursor=-1", "cursor=0", "mine=yes", "mine=2"]
)
def test_matches_refuses_a_bad_query(query: str) -> None:
    response = client_for(make_player(1)).get(f"/api/matches/?{query}")
    assert response.status_code == 400 and response.json() == {"error": "bad-request"}


def test_matches_and_a_match_stay_in_the_web_server(
    league: Community, players: list[Player]
) -> None:
    elsewhere = other_league_match()
    client = client_for(players[0])
    assert get(client, "/api/matches/?status=recent")["matches"] == []
    assert get(client, f"/api/matches/{elsewhere.pk}/", 404) == {"error": "not-found"}
    assert get(client, f"/api/matches/{elsewhere.pk}/postgame/", 404) == {"error": "not-found"}
    assert get(client, "/api/matches/987654321/", 404) == {"error": "not-found"}
    assert get(client, "/api/matches/99999999999999999999/", 404) == {"error": "not-found"}


def test_a_match_shows_teams_heroes_and_rating_changes(
    league: Community, players: list[Player], art_for: Callable[[Champion], None]
) -> None:
    match = play_full_match(league, players, "A", 1)
    picked = match.draft_actions.filter(action="pick", team="A").order_by("step_index").first()
    assert picked is not None and picked.target_champion is not None
    art_for(picked.target_champion)
    detail = get(client_for(players[3]), f"/api/matches/{match.pk}/")

    assert detail["id"] == str(match.pk) and detail["status"] == Status.COMPLETED
    assert detail["winner"] == "A" and detail["draft_name"] and detail["rated"] is True
    assert detail["rating_label"] == "Rating" and detail["has_postgame"] is False
    assert 0 < detail["win_chance_a"] < 1
    a, b = detail["teams"]
    assert (a["team"], b["team"]) == ("A", "B")
    assert {a["side"], b["side"]} == {"hk", "am"}
    assert len(a["players"]) == len(b["players"]) == 6
    assert sum(1 for p in a["players"] if p["is_captain"]) == 1
    assert all(p["delta"] > 0 for p in a["players"])
    assert all(p["delta"] <= 0 for p in b["players"])  # A shown rating stops at zero.
    assert all(p["rating_after"] - p["rating_before"] == p["delta"] for p in a["players"])
    assert a["picks"][0]["id"] == str(picked.target_champion_id)
    assert a["picks"][0]["icon_url"] == f"/static/hero-art/{picked.target_champion.slug}.webp"
    assert len(a["picks"]) + len(b["picks"]) == 12
    assert a["bans"] and b["bans"]
    order = list(match.draft_actions.exclude(target_champion=None).order_by("step_index"))
    assert [(d["action"], d["team"], d["champion"]["id"]) for d in detail["draft"]] == [
        (action.action, action.team, str(action.target_champion_id)) for action in order
    ]


def test_a_match_is_the_same_shared_record_for_everyone(
    league: Community, players: list[Player]
) -> None:
    """No personal block: a player in it, one who wasn't and the other team see the same."""
    match = play_full_match(league, players, "A", 1)
    path = f"/api/matches/{match.pk}/"
    mine = client_for(match.participants.filter(team="A").first().player).get(path)  # type: ignore[union-attr]
    theirs = client_for(match.participants.filter(team="B").first().player).get(path)  # type: ignore[union-attr]
    stranger = client_for(make_player(99)).get(path)
    assert mine.json() == theirs.json() == stranger.json()
    assert "your_team" not in mine.json()


def test_an_unrated_match_shows_no_change(league: Community, players: list[Player]) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = Match.objects.get()
    detail = get(client_for(players[0]), f"/api/matches/{match.pk}/")
    assert detail["rated"] is False and detail["win_chance_a"] is None
    assert all(p["delta"] == 0 for team in detail["teams"] for p in team["players"])


def test_a_match_shows_interim_points_while_they_are_on(
    league: Community, players: list[Player]
) -> None:
    match = play_full_match(league, players, "A", 1)
    interim.set_enabled(league, True)
    detail = get(client_for(players[0]), f"/api/matches/{match.pk}/")
    assert detail["rating_label"] == "Points"
    a = detail["teams"][0]["players"]
    assert all(p["delta"] > 0 for p in a)


# --- Postgame ---------------------------------------------------------------------------------


@cache
def _raw_metadata() -> str:
    return gzip.decompress(FIXTURE.read_bytes()).decode("utf-8")


def metadata() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_raw_metadata())
    return data


def linked_match(league: Community) -> Match:
    """A match in progress whose players are linked to the fixture match's Steam accounts."""
    match = to_in_progress(Match.objects.get(community=league))
    accounts: dict[int, list[int]] = {0: [], 1: []}
    for line in metadata()["match_info"]["players"]:
        accounts[line["team"]].append(line["account_id"])
    hk = match.hidden_king_team
    am = "B" if hk == "A" else "A"
    for team, ids in ((hk, accounts[0]), (am, accounts[1])):
        rows = match.participants.filter(team=team).order_by("id")
        for row, account in zip(rows, ids, strict=True):
            steam.link(row.player, account)
    return match


def test_the_postgame_waits_for_a_match_id(popped: Match, players: list[Player]) -> None:
    match = to_in_progress(popped)
    client = client_for(players[0])
    path = f"/api/matches/{match.pk}/postgame/"
    assert get(client, path) == {"status": "pending", "reason": "later"}  # Still playing.
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1))
    assert get(client, path) == {"status": "pending", "reason": "no-match-id"}


def test_the_postgame_is_later_while_the_check_retries_then_unavailable(
    league: Community, popped: Match, players: list[Player]
) -> None:
    runtime.update(league, api_results=True)
    match = to_in_progress(popped)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1), DEADLOCK_ID)
    client = client_for(players[0])
    path = f"/api/matches/{match.pk}/postgame/"
    assert get(client, path)["reason"] == "later"
    for _attempt in api_results.BACKOFF_MINUTES:
        api_results.record_miss(match.pk, DEADLOCK_ID, CheckStatus.NOT_FOUND, 404, "not yet")
    assert get(client, path)["reason"] == "unavailable"


def test_the_postgame_is_unavailable_with_checks_off_or_a_voided_match(
    league: Community, popped: Match, players: list[Player]
) -> None:
    runtime.update(league, api_results=False)
    match = to_in_progress(popped)
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1), DEADLOCK_ID)
    client = client_for(players[0])
    assert get(client, f"/api/matches/{match.pk}/postgame/")["reason"] == "unavailable"
    results.dispute(match.pk, match.captain_of("B").player, "No.")
    results.resolve_dispute(match.pk, "void", None, "test")
    assert fresh(match).status == Status.VOIDED
    assert get(client, f"/api/matches/{match.pk}/postgame/")["reason"] == "unavailable"


def test_the_postgame_has_your_night_for_the_roster_only(
    league: Community, players: list[Player]
) -> None:
    for player in players:
        queue.join(league.pk, player)
    match = linked_match(league)
    hk = match.hidden_king_team
    am = "B" if hk == "A" else "A"
    results.submit_report(match.pk, match.captain_of(am).player, am, image(1), DEADLOCK_ID)
    results.confirm(match.pk, match.captain_of(hk).player)
    postgame.save(fresh(match), metadata())
    viewer = match.participants.filter(team=am, is_captain=False).first().player  # type: ignore[union-attr]

    body = get(client_for(viewer), f"/api/matches/{match.pk}/postgame/")
    assert body["status"] == "ready"
    assert body["data"]["deadlock_match_id"] == DEADLOCK_ID
    assert body["data"] == postgame.stored(match).model_dump(mode="json")  # type: ignore[union-attr]
    you = body["you"]
    line = next(p for p in body["data"]["players"] if p["player_id"] == viewer.pk)
    assert you["slot"] == line["slot"] and you["team"] == am and you["side"] == "am"
    assert you["result"] == "win" and you["rating_label"] == "Rating"
    assert you["delta"] > 0 and you["rating_after"] - you["rating_before"] == you["delta"]

    spectator = get(client_for(make_player(99)), f"/api/matches/{match.pk}/postgame/")
    assert spectator["status"] == "ready" and spectator["you"] is None
    assert spectator["data"] == body["data"]
    assert get(client_for(viewer), f"/api/matches/{match.pk}/")["has_postgame"] is True


def test_a_postgame_whose_data_made_no_document_is_unavailable(
    league: Community, players: list[Player]
) -> None:
    """The ID was for a match none of the linked players were in, so no document was kept."""
    for player in players:
        queue.join(league.pk, player)
    match = to_in_progress(Match.objects.get())
    for number, row in enumerate(match.participants.order_by("id")):
        steam.link(row.player, 1_000 + number)  # Accounts that aren't in the fixture match.
    results.submit_report(match.pk, match.captain_of("A").player, "A", image(1), DEADLOCK_ID)
    api_results.record_metadata(match.pk, DEADLOCK_ID, metadata())
    body = get(client_for(players[0]), f"/api/matches/{match.pk}/postgame/")
    assert body == {"status": "pending", "reason": "unavailable"}


# --- Ladder and seasons -----------------------------------------------------------------------


def test_the_ladder_names_players_without_addressing_them(
    league: Community, players: list[Player]
) -> None:
    play_full_match(league, players, "A", 1)
    board = get(client_for(players[0]), "/api/ladder/")
    assert len(board["rows"]) == board["total"] == 12
    assert board["rating_label"] == "Rating" and board["tiers"]
    top = board["rows"][0]
    assert top["rank"] == 1 and top["wins"] + top["losses"] == 1
    assert top["tier"] in board["tiers"]
    # No player ID or profile link: profiles are private.
    assert set(top) == {"rank", "name", "avatar_url", "rating", "tier", "wins", "losses", "is_you"}
    assert [row["is_you"] for row in board["rows"]].count(True) == 1
    assert board["me"]["is_you"] and board["me"]["name"] == players[0].display_name
    assert board["next_offset"] is None
    assert get(client_for(make_player(99)), "/api/ladder/")["me"] is None


def test_the_ladder_pages_and_keeps_the_viewer(
    league: Community, players: list[Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    play_full_match(league, players, "A", 1)
    monkeypatch.setattr(reads, "LADDER_PAGE", 5)
    whole = get(client_for(players[0]), "/api/ladder/?offset=0")
    last = whole["rows"][-1]
    viewer = Player.objects.get(display_name=last["name"])
    client = client_for(viewer)
    first = get(client, "/api/ladder/")
    assert [row["rank"] for row in first["rows"]] == [1, 2, 3, 4, 5]
    assert first["next_offset"] == 5 and first["me"]["rank"] == 5
    assert first["me"]["name"] == viewer.display_name
    second = get(client, "/api/ladder/?offset=5")
    assert [row["rank"] for row in second["rows"]] == [6, 7, 8, 9, 10]
    end = get(client, "/api/ladder/?offset=10")
    assert len(end["rows"]) == 2 and end["next_offset"] is None


def test_the_ladder_shows_points_and_no_tiers_in_the_interim(
    league: Community, players: list[Player]
) -> None:
    play_full_match(league, players, "A", 1)
    interim.set_enabled(league, True)
    board = get(client_for(players[0]), "/api/ladder/")
    assert board["rating_label"] == "Points" and board["tiers"] == []
    assert all(row["tier"] is None for row in board["rows"])


@pytest.mark.parametrize(
    ("query", "status"),
    [
        ("offset=-1", 400),
        ("offset=x", 400),
        ("offset=0", 200),
        ("season=x", 400),
        ("season=987654321", 404),
    ],
)
def test_the_ladder_query_is_checked(query: str, status: int) -> None:
    get(client_for(make_player(1)), f"/api/ladder/?{query}", status)


def past_season(league: Community) -> Season:
    return Season.objects.create(
        community=league,
        number=0,
        name="Preseason",
        started_at="2026-01-01T00:00:00Z",
        ended_at="2026-02-01T00:00:00Z",
    )


def test_seasons_list_newest_first_and_mark_the_open_one(league: Community) -> None:
    old = past_season(league)
    open_season = Season.objects.get(community=league, ended_at__isnull=True)
    seasons = get(client_for(make_player(1)), "/api/seasons/")["seasons"]
    assert seasons == [
        {"id": str(open_season.pk), "name": open_season.name, "is_open": True},
        {"id": str(old.pk), "name": "Preseason", "is_open": False},
    ]
    elsewhere = community.ensure(guild_id=4242, name="Elsewhere")
    theirs = Season.objects.get(community=elsewhere)
    listed = get(client_for(make_player(2)), "/api/seasons/")["seasons"]
    assert str(theirs.pk) not in {row["id"] for row in listed}


def test_a_past_season_has_its_own_ladder_and_profile(
    league: Community, players: list[Player]
) -> None:
    play_full_match(league, players, "A", 1)
    old = past_season(league)
    client = client_for(players[0])
    board = get(client, f"/api/ladder/?season={old.pk}")
    assert board["season"] == "Preseason" and board["season_id"] == str(old.pk)
    me = get(client, f"/api/me/?season={old.pk}")
    assert me["season_id"] == str(old.pk) and me["games"] == 0 and me["recent"] == []
    now = get(client, "/api/me/")
    assert now["season_id"] != str(old.pk) and now["games"] == 1


def test_another_servers_season_is_not_found(league: Community) -> None:
    theirs = Season.objects.get(community=community.ensure(guild_id=4242, name="Elsewhere"))
    client = client_for(make_player(1))
    get(client, f"/api/ladder/?season={theirs.pk}", 404)
    get(client, f"/api/me/?season={theirs.pk}", 404)


# --- The private profile ----------------------------------------------------------------------


def test_my_profile_shows_my_season(league: Community, players: list[Player]) -> None:
    match = play_full_match(league, players, "A", 1)
    me = match.participants.filter(team="B").first().player  # type: ignore[union-attr]
    profile = get(client_for(me), "/api/me/")
    assert profile["player"]["id"] == str(me.pk) and profile["player"]["name"] == me.display_name
    assert profile["games"] == 1 and profile["losses"] == 1 and profile["wins"] == 0
    assert profile["rating_label"] == "Rating" and profile["tier"] in profile["tiers"]
    assert profile["rank"] is not None and profile["ranked"] == 12
    assert profile["placement"]["played"] == 1 and profile["placement"]["total"] > 1
    rated = PlayerRating.objects.get(player=me, season__community=league)
    assert profile["rating"] == rated.rating
    (point,) = profile["history"]
    assert point["match_id"] == str(match.pk) and point["rating_after"] == rated.rating
    (recent,) = profile["recent"]
    assert recent["match_id"] == str(match.pk) and recent["result"] == "loss"
    assert recent["team"] == "B" and recent["side"] in {"hk", "am"}
    assert recent["delta"] == point["delta"] and recent["has_postgame"] is False
    assert profile["captain"]["eligible"] is (profile["captain"]["reason"] == "")
    assert profile["awards"] == {"mvps": 0, "keys": 0}


def test_my_profile_lists_strikes_and_how_they_come_off(league: Community) -> None:
    me = make_player(1)
    penalties.issue(league, me, PenaltyKind.DODGE)
    strikes = get(client_for(me), "/api/me/")["strikes"]
    assert strikes["count"] > 0 and strikes["games_to_next"] is not None
    assert strikes["games_per_strike"] >= 1 and strikes["progress"] == 0
    (entry,) = strikes["log"]
    assert entry["kind"] == "offence" and entry["label"] == "Dodge"
    assert entry["strikes"] == strikes["count"] and entry["waived"] is False


def test_my_profile_shows_points_in_the_interim(league: Community, players: list[Player]) -> None:
    play_full_match(league, players, "A", 1)
    interim.set_enabled(league, True)
    profile = get(client_for(players[0]), "/api/me/")
    assert profile["rating_label"] == "Points" and profile["tier"] is None
    assert profile["tiers"] == [] and profile["placement"] is None
    assert len(profile["history"]) == 1 and profile["recent"][0]["delta"] is not None


def test_my_accounts_name_steam_links_by_handle_never_by_steam_id(league: Community) -> None:
    me = make_player(1)
    steam.link(me, 76543, "Vexa")
    steam.link_proven(me, 98765, "Alt")
    profile = client_for(me).get("/api/me/")
    accounts = profile.json()["accounts"]
    assert accounts["discord_name"] == me.display_name
    rows = {row.steam_name: row for row in SteamAccount.objects.filter(player=me)}
    assert [
        (row["id"], row["name"], row["proven"], row["verified"]) for row in accounts["steam"]
    ] == [
        (str(rows["Vexa"].pk), "Vexa", False, False),
        (str(rows["Alt"].pk), "Alt", True, False),
    ]
    assert b"76543" not in profile.content and b"98765" not in profile.content
    assert str(me.discord_user_id).encode() not in profile.content


def test_no_one_can_read_another_players_profile(league: Community, players: list[Player]) -> None:
    play_full_match(league, players, "A", 1)
    other = players[1]
    steam.link(other, 55555, "Theirs")
    client = client_for(players[0])
    assert client.get(f"/api/players/{other.pk}/").status_code == 404
    assert client.get(f"/api/me/?player={other.pk}").json()["player"]["id"] == str(players[0].pk)
    profile = client.get("/api/me/").content
    assert b"Theirs" not in profile and b"55555" not in profile


def test_my_share_card_is_a_private_png(league: Community, players: list[Player]) -> None:
    play_full_match(league, players, "A", 1)
    response = client_for(players[0]).get("/api/me/share.png")
    assert response.status_code == 200 and response["Content-Type"] == "image/png"
    assert response["Cache-Control"] == "no-store"
    assert response.content.startswith(b"\x89PNG\r\n\x1a\n")


def test_my_share_card_shows_what_i_choose(
    league: Community, monkeypatch: pytest.MonkeyPatch
) -> None:
    me = make_player(1)
    seen: dict[str, Any] = {}

    def render(player: Player, **options: Any) -> bytes:
        seen.update(player=player, **options)
        return b"\x89PNG\r\n\x1a\nfake"

    monkeypatch.setattr(share_card, "render", render)
    client = client_for(me)
    assert client.get("/api/me/share.png?rating=0&award=0").status_code == 200
    open_season = Season.objects.get(community=league, ended_at__isnull=True)
    assert seen == {
        "player": me,
        "show_rating": False,
        "show_place": True,
        "show_award": False,
        "season": open_season,
    }
    assert get(client, "/api/me/share.png?place=yes", 400) == {"error": "bad-request"}


# --- Unlinking Steam --------------------------------------------------------------------------


def test_unlinking_removes_one_of_my_own_accounts(league: Community) -> None:
    me = make_player(1)
    first = steam.link(me, 11111, "Main")
    second = steam.link(me, 22222, "Alt")
    client, token = csrf_client(me)
    path = f"/api/me/steam/{first.pk}/unlink/"
    assert client.post(path).status_code == 403  # No CSRF token.
    response = client.post(path, headers={"X-CSRFToken": token})
    assert response.status_code == 200 and response["Cache-Control"] == "no-store"
    assert [row["id"] for row in response.json()["steam"]] == [str(second.pk)]
    assert list(SteamAccount.objects.filter(player=me)) == [second]
    again = client.post(path, headers={"X-CSRFToken": token})
    assert again.status_code == 404 and again.json() == {"error": "not-found"}


def test_another_players_account_cant_be_unlinked(league: Community) -> None:
    me, them = make_player(1), make_player(2)
    theirs = steam.link(them, 33333, "Theirs")
    response = client_for(me).post(f"/api/me/steam/{theirs.pk}/unlink/")
    assert response.status_code == 404 and response.json() == {"error": "not-found"}
    assert SteamAccount.objects.filter(pk=theirs.pk, player=them).exists()


# --- Player search ----------------------------------------------------------------------------


def test_search_finds_this_servers_players_but_not_the_viewer(
    league: Community, players: list[Player], monkeypatch: pytest.MonkeyPatch
) -> None:
    play_full_match(league, players, "A", 1)
    stranger = make_player(77)  # Never queued or played here.
    viewer = players[0]
    found = get(client_for(viewer), "/api/players/search/?q=p1")["players"]
    names = [row["name"] for row in found]
    assert names == ["P10", "P11", "P12"]  # P1 is the viewer.
    assert stranger.display_name not in names
    # No stats: profiles are private.
    assert set(found[0]) == {"id", "name", "avatar_url", "in_match"}
    monkeypatch.setattr(reads, "SEARCH_LIMIT", 2)
    assert len(get(client_for(viewer), "/api/players/search/?q=p1")["players"]) == 2


def test_search_puts_names_starting_with_the_text_first(league: Community) -> None:
    for name in ("Xavier", "Max", "Maxine"):
        player = make_player(len(name) * 1000 + ord(name[0]))
        player.display_name = name
        player.save()
        queue.join(league.pk, player)
    client = client_for(make_player(1))
    assert [row["name"] for row in get(client, "/api/players/search/?q=ma")["players"]] == [
        "Max",
        "Maxine",
    ]
    assert get(client, "/api/players/search/?q=x")["players"] == []  # Under two characters.
    assert [row["name"] for row in get(client, "/api/players/search/?q=Xi")["players"]] == [
        "Maxine"
    ]


def test_search_flags_players_in_a_match(league: Community, players: list[Player]) -> None:
    for player in players:
        queue.join(league.pk, player)  # Pops a lobby: all twelve are in a live match.
    queue.join(league.pk, make_player(51))  # P51 waits in the queue, free to sub.
    client = client_for(players[0])
    (busy,) = get(client, "/api/players/search/?q=P2")["players"]
    (free,) = get(client, "/api/players/search/?q=P51")["players"]
    assert busy["in_match"] is True and free["in_match"] is False


def test_search_stays_in_the_web_server(league: Community) -> None:
    other_league_match()  # P201 to P212 played elsewhere.
    assert get(client_for(make_player(1)), "/api/players/search/?q=P20")["players"] == []


# --- Random draft -----------------------------------------------------------------------------


def test_random_draft_gives_every_slot_a_hero_with_art(
    league: Community, art_for: Callable[[Champion], None]
) -> None:
    hero = Champion.objects.order_by("pk").first()
    assert hero is not None
    art_for(hero)
    response = client_for(make_player(1)).post("/api/tools/random-draft/")
    assert response.status_code == 200
    draft = response.json()
    heroes = [h for side in ("hk", "am") for kind in ("bans", "picks") for h in draft[side][kind]]
    assert len(draft["hk"]["picks"]) == len(draft["am"]["picks"]) == 6
    assert draft["hk"]["bans"] and draft["am"]["bans"]
    assert len({h["id"] for h in heroes}) == len(heroes)
    assert all(set(h) == {"id", "name", "slug", "icon_url"} for h in heroes)
    art = f"/static/hero-art/{hero.slug}.webp"
    assert all(h["icon_url"] == art for h in heroes if h["id"] == str(hero.pk))
    assert all(h["icon_url"] != art for h in heroes if h["id"] != str(hero.pk))
    assert Match.objects.count() == 0  # Nothing is recorded.


# --- The schema -------------------------------------------------------------------------------


def test_every_body_is_in_the_exported_schema() -> None:
    from league.management.commands.export_ws_schema import render

    document = json.loads(render())
    http = document["$defs"][document["properties"]["http"]["$ref"].rsplit("/", 1)[1]]
    assert set(http["properties"]) == {
        "error",
        "refusal",
        "matches",
        "match",
        "postgame",
        "report",
        "ladder",
        "seasons",
        "me",
        "steam_unlinked",
        "player_search",
        "random_draft",
        "landing",
    }
    assert "Postgame" in document["$defs"] and "MyProfile" in document["$defs"]
