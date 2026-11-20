"""The profile's highlight card: a 1200 x 630 PNG, drawn from the league's own data."""

from __future__ import annotations

import gzip
import io
import json
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from league.models import Community, Match, Player, SteamAccount
from league.services import api_results, results, share_card, steam
from tests.conftest import make_player
from tests.helpers import fresh, image, to_in_progress

FIXTURE = Path(__file__).parent / "fixtures" / "deadlock" / "match_140328807_metadata.json.gz"
DEADLOCK_ID = 140328807
MVP_ACCOUNT = 135518586  # mvp_rank 1 in the fixture, on the Archmother's side.

FULL = share_card.CardData(
    name="Mothball",
    season="Season 2",
    rating=1562,
    tier="Gold II",
    wins=14,
    losses=9,
    place=4,
    ranked=57,
    heroes=[
        share_card.HeroLine("Abrams", "abrams", 9),
        share_card.HeroLine("Mo & Krill", "mo-and-krill", 5),
        share_card.HeroLine("Lady Geist", "lady-geist", 3),
    ],
    award="MVP",
)


def _metadata() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(gzip.decompress(FIXTURE.read_bytes()))
    return data


def _png(data: bytes) -> Image.Image:
    picture = Image.open(io.BytesIO(data))
    picture.load()
    return picture


def _texts(
    data: share_card.CardData, rating: bool = True, place: bool = True, award: bool = True
) -> list[str]:
    _picture, texts = share_card.compose(share_card.shown(data, rating, place, award))
    return texts


# --- Drawing ---------------------------------------------------------------------------------


def test_the_card_is_a_1200_by_630_png() -> None:
    picture, _texts = share_card.compose(share_card.shown(FULL, True, True, True))
    data = share_card.to_png(picture)
    assert data.startswith(b"\x89PNG")
    opened = _png(data)
    assert opened.format == "PNG" and opened.size == (1200, 630) and opened.mode == "RGB"
    colours = opened.getcolors(maxcolors=1_000_000)
    assert colours is None or len(colours) > 100  # Art and type, not an empty ground.


def test_everything_shows_by_default() -> None:
    texts = _texts(FULL)
    assert "Mothball" in texts and "DAYSHIFT" in texts
    assert "1,562" in texts and "Gold II" in texts
    assert "14\u20139" in texts
    assert "#4 of 57" in texts
    assert "Last award: MVP" in texts
    assert [t for t in texts if t in {"Abrams", "Mo & Krill", "Lady Geist"}] == [
        "Abrams",
        "Mo & Krill",
        "Lady Geist",
    ]
    assert share_card.CREDIT in texts


@pytest.mark.parametrize(
    ("hide", "gone"),
    [
        ("rating", {"1,562", "Gold II"}),
        ("place", {"#4 of 57"}),
        ("award", {"Last award: MVP"}),
    ],
)
def test_a_hidden_field_is_not_drawn(hide: str, gone: set[str]) -> None:
    flags = {"rating": True, "place": True, "award": True, hide: False}
    texts = _texts(FULL, flags["rating"], flags["place"], flags["award"])
    assert not gone & set(texts)
    assert "Mothball" in texts and "14\u20139" in texts  # The rest stays.
    shown_png = share_card.to_png(share_card.compose(share_card.shown(FULL, True, True, True))[0])
    hidden_png = share_card.to_png(
        share_card.compose(share_card.shown(FULL, flags["rating"], flags["place"], flags["award"]))[
            0
        ]
    )
    assert shown_png != hidden_png


def test_points_stand_in_for_a_tier_in_the_interim() -> None:
    interim = share_card.CardData(name="Rook", rating=31, rating_label="Points", wins=3, losses=1)
    texts = _texts(interim)
    assert "31" in texts and "Points" in texts


@pytest.mark.parametrize(
    "name",
    [
        "SN\u039eK",
        "\u5149\u306e\u6226\u58eb",
        "\u0412\u0430\u0441\u044f \U0001f525",
        "\U0001d4d0\U0001d4f8\U0001d4fb\U0001d4ea",
        "x" * 200,
    ],
)
def test_any_name_draws(name: str) -> None:
    data = share_card.CardData(name=name)
    picture, texts = share_card.compose(share_card.shown(data, True, True, True))
    assert picture.size == (1200, 630)
    drawn = texts[1]  # After the wordmark.
    assert drawn == name or (drawn.endswith("\u2026") and name.startswith(drawn[:-1]))
    if len(name) == 200:
        assert drawn.endswith("\u2026")  # Cut to fit, never over the art.


def test_a_card_with_nothing_yet_still_draws() -> None:
    data = share_card.CardData(name="New")
    picture, texts = share_card.compose(share_card.shown(data, True, True, True))
    assert picture.size == (1200, 630)
    assert "0\u20130" in texts
    assert share_card.CREDIT not in texts  # No hero art on it, so no credit for it.
    assert not any(t.startswith(("#", "Last award")) for t in texts)


# --- From the league -------------------------------------------------------------------------


@pytest.fixture
def played(league: Community, players: list[Player]) -> Match:
    """A completed match with deadlock-api's data in: postgame heroes and its awards."""
    from league.services import queue

    for player in players:
        queue.join(league.pk, player)
    match = to_in_progress(Match.objects.get())
    hk = match.hidden_king_team
    am = "B" if hk == "A" else "A"
    teams: dict[int, list[int]] = {0: [], 1: []}
    for line in _metadata()["match_info"]["players"]:
        teams[line["team"]].append(line["account_id"])
    for team, accounts in ((hk, teams[0]), (am, teams[1])):
        rows = match.participants.filter(team=team).order_by("id")
        for row, account in zip(rows, accounts, strict=True):
            steam.link(row.player, account)
    results.submit_report(match.pk, match.captain_of(am).player, am, image(1), DEADLOCK_ID)
    api_results.record_metadata(match.pk, DEADLOCK_ID, _metadata())
    results.confirm(match.pk, match.captain_of(hk).player)
    return fresh(match)


def test_card_data_reads_the_league(played: Match) -> None:
    mvp = SteamAccount.objects.get(account_id=MVP_ACCOUNT).player
    data = share_card.card_data(mvp)
    assert data.name == mvp.display_name
    assert data.rating is not None and data.season
    assert (data.wins, data.losses) == (1, 0)
    assert data.place is not None and data.ranked >= 12
    assert data.award == "MVP"
    assert len(data.heroes) == 1 and data.heroes[0].games == 1
    assert data.heroes[0].slug  # The pack has its art.


def test_render_gives_the_png(played: Match) -> None:
    mvp = SteamAccount.objects.get(account_id=MVP_ACCOUNT).player
    full = share_card.render(mvp)
    bare = share_card.render(mvp, show_rating=False, show_place=False, show_award=False)
    assert _png(full).size == _png(bare).size == (1200, 630)
    assert full != bare


def test_a_player_who_never_played_gets_a_plain_card(league: Community) -> None:
    newcomer = make_player(99)
    data = share_card.card_data(newcomer)
    assert data.heroes == [] and data.award == "" and (data.wins, data.losses) == (0, 0)
    assert _png(share_card.render(newcomer)).size == (1200, 630)
