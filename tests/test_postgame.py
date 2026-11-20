"""The postgame document, built from a real deadlock-api match (tests/fixtures/deadlock/).

Nothing here calls deadlock-api: the metadata comes from the fixture, and the rebuild command's
fetch is swapped for it.
"""

from __future__ import annotations

import gzip
import itertools
import json
from functools import cache
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from django.core.management import call_command

from league.integrations import deadlock_api
from league.models import ApiMatchCheck, Community, Match, MatchPostgame, Player
from league.models.api import CheckStatus
from league.services import api_results, hero_art, postgame, queue, results, steam
from tests.helpers import fresh, image, to_in_progress

FIXTURE = Path(__file__).parent / "fixtures" / "deadlock" / "match_140328807_metadata.json.gz"
SAMPLE = Path(__file__).parent / "fixtures" / "deadlock_api_sample.json"
DEADLOCK_ID = 140328807


@cache
def _raw() -> str:
    return gzip.decompress(FIXTURE.read_bytes()).decode("utf-8")


def metadata() -> dict[str, Any]:
    data: dict[str, Any] = json.loads(_raw())
    return data


@pytest.fixture(scope="module")
def doc() -> postgame.Postgame:
    return postgame.document(metadata())


def _info() -> dict[str, Any]:
    info: dict[str, Any] = metadata()["match_info"]
    return info


# --- The document, on its own ----------------------------------------------------------------


def test_the_timeline_runs_minute_by_minute_to_the_end(doc: postgame.Postgame) -> None:
    times = doc.timeline.t
    assert times[0] == 0 and times[-1] == doc.duration_s == _info()["duration_s"]
    assert all(a < b for a, b in itertools.pairwise(times))
    assert all(b - a <= 60 for a, b in itertools.pairwise(times))
    assert len(doc.timeline.souls) == len(doc.timeline.kills) == len(times)
    assert doc.timeline.souls[0] == 0 and doc.timeline.kills[0] == 0


def test_the_end_of_the_leads_is_the_final_score(doc: postgame.Postgame) -> None:
    hk = [p for p in doc.players if p.team == "hk"]
    am = [p for p in doc.players if p.team == "am"]
    assert doc.timeline.kills[-1] == sum(p.kills for p in hk) - sum(p.kills for p in am)
    assert doc.timeline.souls[-1] == sum(p.souls for p in hk) - sum(p.souls for p in am)
    assert doc.winner == "am"  # The fixture's winning_team is 1, the Archmother.


def test_team_totals_are_the_sums_of_their_players(doc: postgame.Postgame) -> None:
    for side, line in (("hk", doc.teams.hk), ("am", doc.teams.am)):
        mine = [p for p in doc.players if p.team == side]
        assert len(mine) == 6
        assert line.kills == sum(p.kills for p in mine)
        assert line.souls == sum(p.souls for p in mine)
    raw = _info()["players"]
    assert sum(p.kills for p in doc.players) == sum(p["kills"] for p in raw)
    assert sum(p.souls for p in doc.players) == sum(p["net_worth"] for p in raw)


def test_damage_per_enemy_adds_up_to_hero_damage(doc: postgame.Postgame) -> None:
    sides = {p.slot: p.team for p in doc.players}
    for player in doc.players:
        assert player.damage > 0
        assert sum(d.damage for d in player.damage_to) == player.damage
        assert {sides[d.slot] for d in player.damage_to} == {"am" if player.team == "hk" else "hk"}
        values = [d.damage for d in player.damage_to]
        assert values == sorted(values, reverse=True)


def test_positions_are_sampled_every_ten_seconds(doc: postgame.Postgame) -> None:
    replay = doc.replay
    assert replay.step_s == 10
    assert replay.frames == doc.duration_s // 10 + 1
    assert len(replay.positions) == len(doc.players)
    for flat in replay.positions:
        assert len(flat) == 2 * replay.frames
        assert all(0 <= value <= doc.map.scale for value in flat)
    # Far fewer points than the game's one a second.
    assert replay.frames < len(_info()["match_paths"]["paths"][0]["x_pos"]) / 5


def test_deaths_are_sorted_and_complete(doc: postgame.Postgame) -> None:
    times = [d.t for d in doc.deaths]
    assert times == sorted(times)
    assert len(doc.deaths) == sum(p.deaths for p in doc.players)
    slots = {p.slot for p in doc.players}
    for death in doc.deaths:
        assert death.victim in slots and death.killer in slots
        assert death.respawn_s >= 0
    for player in doc.players:
        mine = [d for d in doc.deaths if d.victim == player.slot]
        assert player.time_dead_s == sum(d.respawn_s for d in mine)
    assert doc.first_blood is not None and doc.first_blood.t == times[0]


def test_objectives_and_structures(doc: postgame.Postgame) -> None:
    assert [o.t for o in doc.objectives] == sorted(o.t for o in doc.objectives)
    assert len(doc.structures) == len(_info()["objectives"])
    assert all(o.by != o.team for o in doc.objectives)
    patron = [o for o in doc.objectives if o.kind == "patron"]
    assert len(patron) == 1 and patron[0].team == "hk" and patron[0].t == doc.duration_s
    standing = [s for s in doc.structures if s.falls_t is None]
    assert standing and all(s.team == "am" for s in standing)
    assert doc.mid_boss == [postgame.MidBoss(t=1773, by="am", killed_by="am")]
    # Each side's objectives: the other side's structures it took, less the Patron's shield,
    # and the Mid-Bosses it claimed.
    am_took = [o for o in doc.objectives if o.by == "am" and o.kind != "patron_shield"]
    assert doc.teams.am.objectives == len(am_took) + 1


def test_events_and_fights(doc: postgame.Postgame) -> None:
    assert [e.t for e in doc.events] == sorted(e.t for e in doc.events)
    assert doc.events[0].type == "first_blood"
    assert sum(1 for e in doc.events if e.type == "fight") == len(doc.fights)
    for fight in doc.fights:
        assert fight.start <= fight.end
        assert fight.hk + fight.am >= postgame.FIGHT_MIN_DEATHS
    beat_types = [b.type for b in doc.beats]
    assert {"first_walker", "mid_boss", "biggest_fight", "patron"} == set(beat_types)
    assert [b.t for b in doc.beats] == sorted(b.t for b in doc.beats)


def test_six_awards(doc: postgame.Postgame) -> None:
    kinds = [a.kind for a in doc.awards]
    assert kinds == ["mvp", "wrecking_ball", "first_blood", "the_wall", "field_medic", "dead_eye"]
    by_slot = {p.slot: p for p in doc.players}
    mvp = next(a for a in doc.awards if a.kind == "mvp")
    assert by_slot[mvp.slot].mvp_rank == 1
    wrecker = next(a for a in doc.awards if a.kind == "wrecking_ball")
    assert by_slot[wrecker.slot].objective_damage == max(p.objective_damage for p in doc.players)


def test_builds_leave_out_abilities(doc: postgame.Postgame) -> None:
    raw = {p["player_slot"]: p for p in _info()["players"]}
    for player in doc.players:
        abilities = {i["item_id"] for i in raw[player.slot]["items"] if i["upgrade_id"] == 0}
        assert len(abilities) == 4
        assert player.build
        assert not {item.item_id for item in player.build} & abilities
        assert [item.t for item in player.build] == sorted(item.t for item in player.build)
        assert all(item.sold_t is None or item.sold_t >= item.t for item in player.build)
    assert doc.item_names == {}  # Names come in a later schema.


def test_unmatched_players_keep_their_hero_and_a_number(doc: postgame.Postgame) -> None:
    assert [p.name for p in doc.players] == [f"Player {n}" for n in range(1, 13)]
    assert all(p.player_id is None for p in doc.players)
    assert [p.team for p in doc.players] == ["hk"] * 6 + ["am"] * 6
    assert all(p.hero == f"Hero {p.hero_id}" and p.hero_slug == "" for p in doc.players)


def test_the_document_fits_the_size_budget(doc: postgame.Postgame) -> None:
    size = len(json.dumps(doc.model_dump(mode="json"), separators=(",", ":")))
    assert size < 200_000
    assert size < len(_raw()) / 10


def test_the_document_round_trips(doc: postgame.Postgame) -> None:
    dumped = doc.model_dump(mode="json")
    assert postgame.Postgame.model_validate(json.loads(json.dumps(dumped))) == doc
    assert dumped["schema_version"] == postgame.SCHEMA_VERSION == 1


def test_thin_metadata_still_builds() -> None:
    """deadlock-api's data for some matches lacks paths, items and the damage matrix."""
    sample = json.loads(SAMPLE.read_text(encoding="utf-8"))
    thin = postgame.document(sample)
    assert len(thin.players) == len(sample["match_info"]["players"])
    assert thin.replay.positions == [[] for _ in thin.players]
    assert thin.deaths == [] and thin.fights == [] and thin.first_blood is None
    assert all(p.damage_to == [] and p.build == [] for p in thin.players)


def test_metadata_with_no_players_is_refused() -> None:
    with pytest.raises(ValueError):
        postgame.document({"match_info": {"match_id": 1, "players": []}})
    with pytest.raises(ValueError):
        postgame.document({})


@pytest.mark.parametrize(
    ("x", "y", "expected"),
    [
        (0, 0, (500, 500)),
        (-postgame.MAP_RADIUS, postgame.MAP_RADIUS, (0, 0)),
        (1e9, -1e9, (1000, 1000)),
    ],
)
def test_positions_project_onto_the_minimap(x: float, y: float, expected: tuple[int, int]) -> None:
    assert postgame.project(x, y) == expected


# --- With the league: mapping players and storing the document --------------------------------


def _accounts_by_team() -> dict[int, list[int]]:
    teams: dict[int, list[int]] = {0: [], 1: []}
    for player in _info()["players"]:
        teams[player["team"]].append(player["account_id"])
    return teams


@pytest.fixture
def reported(league: Community, players: list[Player]) -> Match:
    """A reported game, the Archmother's side winning, whose players are linked to the fixture
    match's accounts."""
    for player in players:
        queue.join(league.pk, player)
    match = to_in_progress(Match.objects.get())
    hk = match.hidden_king_team
    am = "B" if hk == "A" else "A"
    teams = _accounts_by_team()
    for team, accounts in ((hk, teams[0]), (am, teams[1])):
        rows = match.participants.filter(team=team).order_by("id")
        for row, account in zip(rows, accounts, strict=True):
            steam.link(row.player, account)
    results.submit_report(match.pk, match.captain_of(am).player, am, image(1), DEADLOCK_ID)
    return fresh(match)


def _stored(match: Match) -> dict[str, Any]:
    data: dict[str, Any] = MatchPostgame.objects.get(match=match).data
    return data


def test_the_result_check_stores_the_postgame(reported: Match) -> None:
    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    assert check.status == CheckStatus.OK
    row = MatchPostgame.objects.get(match=reported)
    assert row.deadlock_match_id == DEADLOCK_ID and row.schema_version == postgame.SCHEMA_VERSION
    doc = postgame.stored(reported)
    assert doc is not None
    hk = reported.hidden_king_team
    assert doc.teams.hk.letter == hk and doc.teams.am.letter == ("B" if hk == "A" else "A")
    # Every player is matched by Steam account, on their own side, with their league name.
    rows = {r.player_id: r for r in reported.participants.roster().select_related("player")}
    sides = {hk: "hk", doc.teams.am.letter: "am"}
    for line in doc.players:
        assert line.player_id is not None
        assert line.name == rows[line.player_id].player.display_name
        assert sides[rows[line.player_id].team] == line.team
    # Heroes are the league's champions, with art keys from the pack.
    assert all(line.hero_slug in hero_art.available() for line in doc.players)


def test_an_account_on_the_wrong_side_stays_unmatched(reported: Match) -> None:
    hk = reported.hidden_king_team
    am = "B" if hk == "A" else "A"
    p = reported.participants.filter(team=hk).order_by("id").select_related("player").first()
    q = reported.participants.filter(team=am).order_by("id").select_related("player").first()
    assert p is not None and q is not None
    x = next(iter(steam.accounts_of([p.player_id])))
    y = next(iter(steam.accounts_of([q.player_id])))
    steam.unlink(p.player)
    steam.unlink(q.player)
    steam.link(p.player, y)  # Each one's account is now seen on the other side.
    steam.link(q.player, x)

    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    assert check.status == CheckStatus.MISMATCH  # Staff hear about it; the postgame is kept.
    data = _stored(reported)
    ids = [line["player_id"] for line in data["players"]]
    assert p.player_id not in ids and q.player_id not in ids
    unmatched = [line for line in data["players"] if line["player_id"] is None]
    assert sorted(line["team"] for line in unmatched) == ["am", "hk"]
    assert all(line["name"].startswith("Player ") for line in unmatched)
    assert sum(1 for i in ids if i is not None) == 10


def test_a_failed_build_never_breaks_the_result_check(
    reported: Match, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*args: Any, **kwargs: Any) -> postgame.Postgame:
        raise RuntimeError("boom")

    monkeypatch.setattr(postgame, "document", broken)
    check = api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    assert check.status == CheckStatus.OK
    assert ApiMatchCheck.objects.filter(match=reported).count() == 1
    assert not MatchPostgame.objects.filter(match=reported).exists()


def test_a_wrong_match_id_stores_no_postgame(reported: Match) -> None:
    other = metadata()
    for player in other["match_info"]["players"]:
        player["account_id"] += 1  # Nobody linked played in it.
    api_results.record_metadata(reported.pk, DEADLOCK_ID, other)
    assert not MatchPostgame.objects.filter(match=reported).exists()


def test_a_new_check_replaces_the_postgame(reported: Match) -> None:
    api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    api_results.record_metadata(reported.pk, DEADLOCK_ID, metadata())
    assert MatchPostgame.objects.filter(match=reported).count() == 1


def test_build_postgames_fetches_the_metadata_again(
    reported: Match, monkeypatch: pytest.MonkeyPatch
) -> None:
    asked: list[int] = []

    def fetch(match_id: int) -> dict[str, Any] | None:
        asked.append(match_id)
        return metadata()

    monkeypatch.setattr(deadlock_api, "match_metadata", fetch)
    out = StringIO()
    call_command("build_postgames", stdout=out)
    assert asked == [DEADLOCK_ID]
    assert "1 built" in out.getvalue()
    assert postgame.stored(reported) is not None

    # Already built: only --match rebuilds it.
    call_command("build_postgames", stdout=StringIO())
    assert asked == [DEADLOCK_ID]
    call_command("build_postgames", "--match", str(reported.pk), stdout=StringIO())
    assert asked == [DEADLOCK_ID, DEADLOCK_ID]


def test_build_postgames_reports_a_match_deadlock_api_lacks(
    reported: Match, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(deadlock_api, "match_metadata", lambda match_id: None)
    out = StringIO()
    call_command("build_postgames", "--match", str(reported.pk), stdout=out)
    assert "1 with no data" in out.getvalue()
    assert not MatchPostgame.objects.filter(match=reported).exists()
