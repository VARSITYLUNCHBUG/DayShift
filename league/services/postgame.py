"""The postgame screens' data: a compact document drawn from deadlock-api's match metadata.

The bot already fetches a finished match's full metadata (about 1 MB) to check the result
(league/services/api_results.py). When it arrives, `save` turns it into a `Postgame` document of
a few tens of KB and keeps it in `MatchPostgame`, for the web's four postgame tabs: Summary,
Timeline, Replay and Advanced. Only the summary of the metadata is kept otherwise, so a match
whose document is missing can only be rebuilt by fetching the metadata again (`build`).

Everything here is in the game's own terms:

- **Sides.** Team 0 is the Hidden King (`"hk"`), team 1 the Archmother (`"am"`). Leads are
  Hidden King minus Archmother: positive means the Hidden King is ahead.
- **Players** are referred to by their Deadlock `slot` everywhere in the document. Each one
  maps to a league player by a linked Steam account on the right team; anyone else keeps their
  hero and a "Player N" name, so the document never shows a Steam ID.
- **Positions** are on the minimap, 0 to 1000 across and down from its top-left corner.
- **Items** are deadlock-api's item IDs. The stored document carries no names: `stored` adds
  them from the shop catalogue as it's served (league/services/items.py), and the web shows
  "Item <id>" for one the catalogue doesn't know yet.

`document()` and the helpers it uses are pure: metadata in, document out. `save`, `build` and
`league_players` read and write the database.
"""

from __future__ import annotations

import itertools
import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal

from django.db import transaction
from pydantic import BaseModel, ConfigDict

from league.models import Champion, Match, MatchPostgame
from league.services import items, live, steam

logger = logging.getLogger(__name__)

SCHEMA_VERSION = 1

Side = Literal["hk", "am"]
SIDES: dict[int, Side] = {0: "hk", 1: "am"}

# deadlock-api's /v1/assets/map radius (checked: 10752): the minimap spans -radius to +radius on
# both axes. The minimap itself is league/static/postgame/minimap.png, from the same endpoint.
MAP_RADIUS = 10752.0
MAP_SCALE = 1000  # Positions are 0..MAP_SCALE across and down the minimap.
REPLAY_STEP_S = 10  # One replay frame every 10 seconds of game time.
# Deaths no more than this far apart are one fight, and a fight needs this many.
FIGHT_GAP_S = 20
FIGHT_MIN_DEATHS = 3
# Players with fewer shots than this aren't up for the accuracy award.
DEAD_EYE_MIN_SHOTS = 200

ObjectiveKind = Literal[
    "guardian", "walker", "base_guardian", "shrine", "patron_shield", "patron", "objective"
]
# team_objective_id, as Deadlock numbers them (Tier1 = Guardian, Tier2 = Walker, BarrackBoss =
# Base Guardian, TitanShieldGenerator = Shrine, Titan and Core = the Patron's two phases), to
# what it is and its lane, 1 to 3 across the map. The game's enum has four lanes; the map uses
# its first, third and fourth.
OBJECTIVES: dict[int, tuple[ObjectiveKind, int | None]] = {
    1: ("guardian", 1), 3: ("guardian", 2), 4: ("guardian", 3),
    5: ("walker", 1), 7: ("walker", 2), 8: ("walker", 3),
    12: ("base_guardian", 1), 14: ("base_guardian", 2), 15: ("base_guardian", 3),
    10: ("shrine", None), 11: ("shrine", None),
    9: ("patron_shield", None), 0: ("patron", None),
}  # fmt: skip
# Kinds that count as an objective taken, in the result's score. The shield falls with the
# Patron, so it isn't one of its own.
SCORED_KINDS = frozenset({"guardian", "walker", "base_guardian", "shrine", "patron"})

AwardKind = Literal["mvp", "wrecking_ball", "first_blood", "the_wall", "field_medic", "dead_eye"]


# --- The document ----------------------------------------------------------------------------


class _Doc(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SoulSources(_Doc):
    """Where a player's souls came from. Orbs count with what dropped them."""

    players: int
    troopers: int
    neutrals: int
    bosses: int
    treasure: int


class DamageTo(_Doc):
    """Hero damage to one enemy. A player's list adds up to their `damage`."""

    slot: int
    damage: int


class Purchase(_Doc):
    """An item bought, by deadlock-api's item ID, and when it was sold, if it was."""

    t: int
    item_id: int
    sold_t: int | None


class PlayerLine(_Doc):
    slot: int
    team: Side
    player_id: int | None  # The league player, when one is matched; None otherwise.
    name: str  # The league player's name, or "Player N".
    hero_id: int  # The champion ID.
    hero: str  # The hero's name, or "Hero <id>" for one the league doesn't know.
    hero_slug: str  # The hero art key (league/static/hero-art/<slug>.webp); "" when unknown.
    level: int
    kills: int
    deaths: int
    assists: int
    kda: float  # (kills + assists) / max(1, deaths), to one decimal.
    souls: int  # Net worth at the end.
    souls_per_min: int
    last_hits: int
    denies: int
    damage: int  # Hero damage.
    damage_per_min: int
    taken: int  # Damage taken from heroes and everything else.
    mitigated: int
    healing: int  # Heals and barriers given, as the game's scoreboard counts them.
    objective_damage: int
    accuracy: float | None  # Shots hit over shots fired, 0..1; None with no shots.
    crit_rate: float | None  # Headshots (crits) over hero bullets hit, 0..1.
    shots: int
    time_dead_s: int
    abandoned_s: int | None  # Seconds in when they abandoned the match; None if they didn't.
    mvp_rank: int | None  # The game's MVP 1 and key players 2 and 3.
    sources: SoulSources
    worth: list[int]  # Net worth at each `timeline.t`.
    damage_to: list[DamageTo]  # Each enemy, most damaged first.
    build: list[Purchase]  # Items in the order bought. Abilities aren't items.


class TeamLine(_Doc):
    letter: str  # "A" or "B": the league team on this side; "" when the match has none set.
    kills: int
    souls: int
    objectives: int  # Enemy structures destroyed, and Mid-Bosses claimed.


class Teams(_Doc):
    hk: TeamLine
    am: TeamLine


class Timeline(_Doc):
    """Leads at each minute, and at the end. `souls` is interpolated between the game's stat
    snapshots (every few minutes); `kills` is exact."""

    t: list[int]
    souls: list[int]
    kills: list[int]


class Death(_Doc):
    t: int
    victim: int  # Slot.
    killer: int | None  # Slot; None when no player got it.
    x: int
    y: int
    respawn_s: int  # How long they were dead.


class Objective(_Doc):
    """A structure that fell."""

    t: int
    kind: ObjectiveKind
    lane: int | None
    team: Side  # Whose it was.
    by: Side  # Who took it.


class Structure(_Doc):
    """Every structure, standing or not, for the replay's map. Positions are the web's: the
    metadata doesn't place them."""

    id: int  # team_objective_id.
    kind: ObjectiveKind
    lane: int | None
    team: Side
    falls_t: int | None  # None: still standing at the end.


class MidBoss(_Doc):
    t: int
    by: Side  # Who claimed it (took the Rejuvenator).
    killed_by: Side | None


class Fight(_Doc):
    start: int
    end: int
    hk: int  # Kills by the Hidden King in it.
    am: int
    winner: Side | None  # None for an even trade.
    x: int  # Where it was: the middle of its deaths.
    y: int


class FirstBlood(_Doc):
    t: int
    killer: int | None
    victim: int


EventType = Literal["first_blood", "fight", "objective", "mid_boss"]


class Event(_Doc):
    """The timeline's list, in time order. `ref` indexes `fights`, `objectives` or `mid_boss`
    by `type`; it's 0 for first blood."""

    t: int
    type: EventType
    team: Side | None  # Who it went to.
    ref: int


BeatType = Literal["first_walker", "mid_boss", "biggest_fight", "patron"]


class Beat(_Doc):
    """A story beat for the Summary's soul-lead line."""

    t: int
    type: BeatType
    team: Side | None
    soul_lead: int  # Hidden King minus Archmother, then.
    ref: int  # Into `fights`, `objectives` or `mid_boss`, as for events.


class Award(_Doc):
    """One of the six postgame awards. `stats` holds the numbers its line quotes:
    mvp: kills, souls, damage. wrecking_ball: objective_damage. first_blood: t, victim.
    the_wall: taken, mitigated. field_medic: healing. dead_eye: accuracy, crit_rate."""

    kind: AwardKind
    slot: int
    stats: dict[str, int | float]


class MapFrame(_Doc):
    radius: float  # In game units: the minimap's half-width.
    scale: int  # Positions run 0..scale across and down from the minimap's top-left.


class Replay(_Doc):
    step_s: int
    frames: int
    # Per player, in `players` order: x0, y0, x1, y1, ... for frames 0, step_s, 2 * step_s, ...
    # Empty when the game recorded no path. Whether they're alive comes from `deaths`.
    positions: list[list[int]]


class Postgame(_Doc):
    schema_version: int
    deadlock_match_id: int
    duration_s: int
    start_time: int | None  # Unix seconds.
    winner: Side | None
    teams: Teams
    players: list[PlayerLine]  # Hidden King first, each side in slot order.
    timeline: Timeline
    deaths: list[Death]  # In time order.
    first_blood: FirstBlood | None
    fights: list[Fight]
    objectives: list[Objective]  # In time order.
    structures: list[Structure]
    mid_boss: list[MidBoss]
    events: list[Event]
    beats: list[Beat]
    awards: list[Award]
    map: MapFrame
    replay: Replay
    # Item ID to name. Empty as stored; `stored` fills it from the shop catalogue. The web shows
    # "Item <id>" for any missing.
    item_names: dict[str, str]


# --- League players and heroes ---------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class LeaguePlayer:
    player_id: int
    name: str
    side: Side | None  # Their team's side in this match; None when the match has no sides set.


@dataclass(frozen=True, slots=True)
class Hero:
    name: str
    slug: str


def league_players(match: Match) -> dict[int, LeaguePlayer]:
    """Steam account ID to the roster player who linked it, with their side in this match."""
    rows = list(match.participants.roster().select_related("player"))
    hk = match.hidden_king_team
    sides: dict[str, Side] = {}
    if hk in {"A", "B"}:
        sides = {hk: "hk", ("B" if hk == "A" else "A"): "am"}
    by_player = {row.player_id: row for row in rows}
    out: dict[int, LeaguePlayer] = {}
    for account_id, player_id in steam.accounts_of(by_player).items():
        row = by_player[player_id]
        out[int(account_id)] = LeaguePlayer(
            player_id=player_id, name=row.player.display_name, side=sides.get(row.team)
        )
    return out


def heroes() -> dict[int, Hero]:
    return {
        pk: Hero(name, slug)
        for pk, name, slug in Champion.objects.values_list("pk", "name", "slug")
    }


# --- Reading the metadata --------------------------------------------------------------------


def _int(value: Any) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and math.isfinite(value):
        return round(value)
    return 0


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def _side(team: Any) -> Side | None:
    return SIDES.get(team) if isinstance(team, int) else None


def _other(side: Side) -> Side:
    return "am" if side == "hk" else "hk"


def project(x: float, y: float, radius: float = MAP_RADIUS) -> tuple[int, int]:
    """Game units to the minimap: 0..MAP_SCALE across, and down from the top."""
    px = (x + radius) / (2 * radius) * MAP_SCALE
    py = (radius - y) / (2 * radius) * MAP_SCALE
    return (
        max(0, min(MAP_SCALE, round(px))),
        max(0, min(MAP_SCALE, round(py))),
    )


def interpolate(points: Sequence[tuple[int, int]], t: int) -> float:
    """The value at `t` along straight lines between `points`, sorted by time. Before the first
    point and after the last, the nearest point's value."""
    if not points:
        return 0.0
    if t <= points[0][0]:
        return float(points[0][1])
    for (t0, v0), (t1, v1) in itertools.pairwise(points):
        if t0 <= t <= t1:
            return v0 if t1 == t0 else v0 + (v1 - v0) * (t - t0) / (t1 - t0)
    return float(points[-1][1])


def minute_marks(duration: int) -> list[int]:
    """0, 60, 120, ... and the end, strictly increasing."""
    marks = list(range(0, max(0, duration) + 1, 60))
    if not marks or marks[-1] != duration:
        marks.append(max(0, duration))
    return marks


def _worth_points(player: Mapping[str, Any], duration: int) -> list[tuple[int, int]]:
    """Net worth over time: the stat snapshots, ending on the player's final net worth (the
    last snapshot can be a soul or two off it)."""
    points = {0: 0}
    for snap in _dicts(player.get("stats")):
        points[_int(snap.get("time_stamp_s"))] = _int(snap.get("net_worth"))
    if isinstance(player.get("net_worth"), int):
        points[max(duration, *points)] = _int(player.get("net_worth"))
    return sorted(points.items())


def _last_stats(player: Mapping[str, Any]) -> dict[str, Any]:
    stats = _dicts(player.get("stats"))
    return stats[-1] if stats else {}


def _sources(last: Mapping[str, Any]) -> SoulSources:
    def total(*keys: str) -> int:
        return sum(_int(last.get(key)) for key in keys)

    return SoulSources(
        players=total("gold_player", "gold_player_orbs"),
        troopers=total("gold_lane_creep", "gold_lane_creep_orbs"),
        neutrals=total("gold_neutral_creep", "gold_neutral_creep_orbs"),
        bosses=total("gold_boss", "gold_boss_orb"),
        treasure=total("gold_treasure"),
    )


def builds(items: Iterable[Mapping[str, Any]]) -> list[Purchase]:
    """The items a player bought, in order. The metadata's `items` holds abilities too: each
    ability's first entry has upgrade_id 0, and its upgrades reuse its ID."""
    entries = [item for item in items if isinstance(item, Mapping)]
    abilities = {_int(e.get("item_id")) for e in entries if _int(e.get("upgrade_id")) == 0}
    out = []
    for entry in sorted(entries, key=lambda e: _int(e.get("game_time_s"))):
        item_id = _int(entry.get("item_id"))
        if item_id in abilities or item_id <= 0:
            continue
        sold = _int(entry.get("sold_time_s"))
        out.append(Purchase(t=_int(entry.get("game_time_s")), item_id=item_id, sold_t=sold or None))
    return out


def split_damage(
    info: Mapping[str, Any], teams: Mapping[int, Side], totals: Mapping[int, int]
) -> dict[int, list[DamageTo]]:
    """Each player's hero damage, enemy by enemy, from the damage matrix. The matrix counts some
    damage under more than one source, so its shares are scaled to the player's own total."""
    matrix = info.get("damage_matrix") or {}
    if not isinstance(matrix, Mapping):
        return {}
    details = matrix.get("source_details") or {}
    stat_types = details.get("stat_type") if isinstance(details, Mapping) else None
    stat_types = stat_types if isinstance(stat_types, list) else []
    raw: dict[int, dict[int, int]] = {}
    for dealer in _dicts(matrix.get("damage_dealers")):
        slot = _int(dealer.get("dealer_player_slot"))
        side = teams.get(slot)
        if side is None:
            continue
        mine = raw.setdefault(slot, {})
        for source in _dicts(dealer.get("damage_sources")):
            index = _int(source.get("source_details_index"))
            if index < len(stat_types) and stat_types[index] != 0:  # 0 is damage dealt.
                continue
            for target in _dicts(source.get("damage_to_players")):
                victim = _int(target.get("target_player_slot"))
                if victim in teams and teams[victim] != side:
                    series = target.get("damage")
                    values = [_int(v) for v in series] if isinstance(series, list) else []
                    mine[victim] = mine.get(victim, 0) + (max(values) if values else 0)
    return {slot: _scaled(shares, totals.get(slot, 0)) for slot, shares in raw.items()}


def _scaled(shares: Mapping[int, int], total: int) -> list[DamageTo]:
    """`shares` scaled to add up to `total` exactly (largest remainders), most first."""
    whole = sum(shares.values())
    if whole <= 0 or total <= 0:
        return [DamageTo(slot=slot, damage=0) for slot in sorted(shares)]
    exact = {slot: value * total / whole for slot, value in shares.items()}
    floors = {slot: math.floor(value) for slot, value in exact.items()}
    left = total - sum(floors.values())
    for slot in sorted(exact, key=lambda s: (floors[s] - exact[s], s))[:left]:
        floors[slot] += 1
    return sorted(
        (DamageTo(slot=slot, damage=value) for slot, value in floors.items()),
        key=lambda d: (-d.damage, d.slot),
    )


def _paths(info: Mapping[str, Any], duration: int) -> tuple[int, dict[int, list[int]]]:
    """Frames, and each slot's sampled positions on the minimap."""
    frames = duration // REPLAY_STEP_S + 1 if duration > 0 else 0
    found = info.get("match_paths") or {}
    if not isinstance(found, Mapping):
        return frames, {}
    interval = found.get("interval_s") or 1.0
    interval = float(interval) if isinstance(interval, int | float) and interval > 0 else 1.0
    x_res = _int(found.get("x_resolution")) or 1
    y_res = _int(found.get("y_resolution")) or 1
    out: dict[int, list[int]] = {}
    for path in _dicts(found.get("paths")):
        xs, ys = path.get("x_pos"), path.get("y_pos")
        if not isinstance(xs, list) or not isinstance(ys, list) or not xs or not ys:
            continue
        count = min(len(xs), len(ys))
        x_min, x_max = float(path.get("x_min") or 0), float(path.get("x_max") or 0)
        y_min, y_max = float(path.get("y_min") or 0), float(path.get("y_max") or 0)
        flat: list[int] = []
        for frame in range(frames):
            index = min(count - 1, round(frame * REPLAY_STEP_S / interval))
            x = x_min + _int(xs[index]) / x_res * (x_max - x_min)
            y = y_min + _int(ys[index]) / y_res * (y_max - y_min)
            flat.extend(project(x, y))
        out[_int(path.get("player_slot"))] = flat
    return frames, out


def fights_from(deaths: Sequence[Death], teams: Mapping[int, Side]) -> list[Fight]:
    """Runs of deaths no more than FIGHT_GAP_S apart, of FIGHT_MIN_DEATHS or more."""
    groups: list[list[Death]] = []
    for death in deaths:
        if groups and death.t - groups[-1][-1].t <= FIGHT_GAP_S:
            groups[-1].append(death)
        else:
            groups.append([death])
    out = []
    for group in groups:
        if len(group) < FIGHT_MIN_DEATHS:
            continue
        hk = sum(1 for d in group if teams.get(d.victim) == "am")
        am = sum(1 for d in group if teams.get(d.victim) == "hk")
        winner: Side | None = "hk" if hk > am else "am" if am > hk else None
        out.append(
            Fight(
                start=group[0].t,
                end=group[-1].t,
                hk=hk,
                am=am,
                winner=winner,
                x=round(sum(d.x for d in group) / len(group)),
                y=round(sum(d.y for d in group) / len(group)),
            )
        )
    return out


def _best(players: Sequence[PlayerLine], key: Any) -> PlayerLine | None:
    """The player with the highest positive `key`, the first one on a tie."""
    best = None
    for player in players:
        value = key(player)
        if value is not None and value > 0 and (best is None or value > key(best)):
            best = player
    return best


def awards_for(players: Sequence[PlayerLine], first_blood: FirstBlood | None) -> list[Award]:
    out: list[Award] = []
    mvp = next((p for p in players if p.mvp_rank == 1), None)
    if mvp is not None:
        out.append(
            Award(
                kind="mvp",
                slot=mvp.slot,
                stats={"kills": mvp.kills, "souls": mvp.souls, "damage": mvp.damage},
            )
        )
    wrecker = _best(players, lambda p: p.objective_damage)
    if wrecker is not None:
        out.append(
            Award(
                kind="wrecking_ball",
                slot=wrecker.slot,
                stats={"objective_damage": wrecker.objective_damage},
            )
        )
    if first_blood is not None and first_blood.killer is not None:
        out.append(
            Award(
                kind="first_blood",
                slot=first_blood.killer,
                stats={"t": first_blood.t, "victim": first_blood.victim},
            )
        )
    wall = _best(players, lambda p: p.taken)
    if wall is not None:
        out.append(
            Award(
                kind="the_wall",
                slot=wall.slot,
                stats={"taken": wall.taken, "mitigated": wall.mitigated},
            )
        )
    medic = _best(players, lambda p: p.healing)
    if medic is not None:
        out.append(Award(kind="field_medic", slot=medic.slot, stats={"healing": medic.healing}))
    shooters = [p for p in players if p.shots >= DEAD_EYE_MIN_SHOTS]
    eye = _best(shooters, lambda p: p.accuracy)
    if eye is not None and eye.accuracy is not None:
        stats: dict[str, int | float] = {"accuracy": eye.accuracy}
        if eye.crit_rate is not None:
            stats["crit_rate"] = eye.crit_rate
        out.append(Award(kind="dead_eye", slot=eye.slot, stats=stats))
    return out


def _ratio(top: int, bottom: int) -> float | None:
    return round(top / bottom, 4) if bottom > 0 else None


def document(
    metadata: Mapping[str, Any],
    *,
    league: Mapping[int, LeaguePlayer] | None = None,
    hero_list: Mapping[int, Hero] | None = None,
    letters: Mapping[Side, str] | None = None,
) -> Postgame:
    """The postgame document for one match's metadata. `league` maps Steam account IDs to league
    players (a player whose side doesn't match stays unmatched), `hero_list` champion IDs to
    names and art keys, and `letters` each side to its league team letter.

    Raises ValueError when the metadata has no players."""
    info = metadata.get("match_info")
    if not isinstance(info, Mapping):
        raise ValueError("no match_info in the metadata")
    raw_players = [p for p in _dicts(info.get("players")) if _side(p.get("team")) is not None]
    if not raw_players:
        raise ValueError("no players in the metadata")
    league = league or {}
    hero_list = hero_list or {}
    letters = letters or {}
    duration = max(0, _int(info.get("duration_s")))
    minutes = max(duration / 60, 1 / 60)
    raw_players.sort(key=lambda p: (_int(p.get("team")), _int(p.get("player_slot"))))
    teams: dict[int, Side] = {}
    for p in raw_players:
        side = _side(p.get("team"))
        if side is not None:
            teams[_int(p.get("player_slot"))] = side
    marks = minute_marks(duration)

    deaths: list[Death] = []
    for p in raw_players:
        victim = _int(p.get("player_slot"))
        for d in _dicts(p.get("death_details")):
            found_pos = d.get("death_pos")
            pos: Mapping[str, Any] = found_pos if isinstance(found_pos, Mapping) else {}
            x, y = project(float(_int(pos.get("x"))), float(_int(pos.get("y"))))
            killer = d.get("killer_player_slot")
            deaths.append(
                Death(
                    t=_int(d.get("game_time_s")),
                    victim=victim,
                    killer=killer if isinstance(killer, int) and killer in teams else None,
                    x=x,
                    y=y,
                    respawn_s=max(0, _int(d.get("death_duration_s"))),
                )
            )
    deaths.sort(key=lambda d: (d.t, d.victim))
    first = deaths[0] if deaths else None
    first_blood = FirstBlood(t=first.t, killer=first.killer, victim=first.victim) if first else None

    totals = {
        _int(p.get("player_slot")): _int(_last_stats(p).get("player_damage")) for p in raw_players
    }
    damage_to = split_damage(info, teams, totals)
    frames, paths = _paths(info, duration)

    players: list[PlayerLine] = []
    positions: list[list[int]] = []
    claimed: set[int] = set()
    for number, p in enumerate(raw_players, start=1):
        slot = _int(p.get("player_slot"))
        side = teams[slot]
        last = _last_stats(p)
        found = league.get(_int(p.get("account_id")))
        if found is not None and found.side not in (None, side):
            found = None  # Their account, on the other team: staff look at it, not us.
        if found is not None and found.player_id in claimed:
            found = None
        if found is not None:
            claimed.add(found.player_id)
        hero_id = _int(p.get("hero_id"))
        hero = hero_list.get(hero_id)
        kills, deaths_n, assists = (
            _int(p.get("kills")),
            _int(p.get("deaths")),
            _int(p.get("assists")),
        )
        souls, damage = _int(p.get("net_worth")), _int(last.get("player_damage"))
        hit, missed = _int(last.get("shots_hit")), _int(last.get("shots_missed"))
        worth = _worth_points(p, duration)
        abandoned = _int(p.get("abandon_match_time_s"))
        mvp_rank = p.get("mvp_rank")
        players.append(
            PlayerLine(
                slot=slot,
                team=side,
                player_id=found.player_id if found else None,
                name=found.name if found else f"Player {number}",
                hero_id=hero_id,
                hero=hero.name if hero else f"Hero {hero_id}",
                hero_slug=hero.slug if hero else "",
                level=_int(p.get("level")),
                kills=kills,
                deaths=deaths_n,
                assists=assists,
                kda=round((kills + assists) / max(1, deaths_n), 1),
                souls=souls,
                souls_per_min=round(souls / minutes),
                last_hits=_int(p.get("last_hits")),
                denies=_int(p.get("denies")),
                damage=damage,
                damage_per_min=round(damage / minutes),
                taken=_int(last.get("player_damage_taken")),
                mitigated=_int(last.get("damage_mitigated")),
                healing=_int(last.get("player_healing")) + _int(last.get("player_barriering")),
                objective_damage=_int(last.get("boss_damage")),
                accuracy=_ratio(hit, hit + missed),
                crit_rate=_ratio(
                    _int(last.get("hero_bullets_hit_crit")), _int(last.get("hero_bullets_hit"))
                ),
                shots=hit + missed,
                time_dead_s=sum(d.respawn_s for d in deaths if d.victim == slot),
                abandoned_s=abandoned if abandoned > 0 else None,
                mvp_rank=mvp_rank if isinstance(mvp_rank, int) and mvp_rank > 0 else None,
                sources=_sources(last),
                worth=[round(interpolate(worth, t)) for t in marks],
                damage_to=damage_to.get(slot, []),
                build=builds(_dicts(p.get("items"))),
            )
        )
        positions.append(paths.get(slot, []))

    worth_by_side = {
        side: [
            _worth_points(p, duration)
            for p in raw_players
            if teams[_int(p.get("player_slot"))] == side
        ]
        for side in ("hk", "am")
    }
    soul_lead = [
        round(
            sum(interpolate(points, t) for points in worth_by_side["hk"])
            - sum(interpolate(points, t) for points in worth_by_side["am"])
        )
        for t in marks
    ]

    def kill_lead(t: int) -> int:
        return sum(1 if teams.get(d.victim) == "am" else -1 for d in deaths if d.t <= t)

    timeline = Timeline(t=marks, souls=soul_lead, kills=[kill_lead(t) for t in marks])

    structures: list[Structure] = []
    for o in _dicts(info.get("objectives")):
        side = _side(o.get("team"))
        if side is None:
            continue
        objective_id = _int(o.get("team_objective_id"))
        kind, lane = OBJECTIVES.get(objective_id, ("objective", None))
        falls = _int(o.get("destroyed_time_s"))
        structures.append(
            Structure(id=objective_id, kind=kind, lane=lane, team=side, falls_t=falls or None)
        )
    structures.sort(key=lambda s: (s.team != "hk", s.id))
    objectives = sorted(
        (
            Objective(t=s.falls_t, kind=s.kind, lane=s.lane, team=s.team, by=_other(s.team))
            for s in structures
            if s.falls_t is not None
        ),
        key=lambda o: (o.t, o.team, o.kind),
    )
    mid_boss: list[MidBoss] = []
    for boss in _dicts(info.get("mid_boss")):
        by = _side(boss.get("team_claimed"))
        t = _int(boss.get("destroyed_time_s"))
        if by is not None and t > 0:
            mid_boss.append(MidBoss(t=t, by=by, killed_by=_side(boss.get("team_killed"))))
    mid_boss.sort(key=lambda b: b.t)
    fights = fights_from(deaths, teams)

    events: list[Event] = []
    if first_blood is not None:
        killer_side = teams.get(first_blood.killer) if first_blood.killer is not None else None
        events.append(Event(t=first_blood.t, type="first_blood", team=killer_side, ref=0))
    events += [Event(t=f.start, type="fight", team=f.winner, ref=i) for i, f in enumerate(fights)]
    events += [Event(t=o.t, type="objective", team=o.by, ref=i) for i, o in enumerate(objectives)]
    events += [Event(t=b.t, type="mid_boss", team=b.by, ref=i) for i, b in enumerate(mid_boss)]
    events.sort(key=lambda e: (e.t, e.type, e.ref))

    lead_points = list(zip(marks, soul_lead, strict=True))

    def beat(t: int, type_: BeatType, team: Side | None, ref: int) -> Beat:
        return Beat(
            t=t, type=type_, team=team, soul_lead=round(interpolate(lead_points, t)), ref=ref
        )

    beats: list[Beat] = []
    walker = next((i for i, o in enumerate(objectives) if o.kind == "walker"), None)
    if walker is not None:
        beats.append(beat(objectives[walker].t, "first_walker", objectives[walker].by, walker))
    if mid_boss:
        beats.append(beat(mid_boss[0].t, "mid_boss", mid_boss[0].by, 0))
    if fights:
        biggest = max(range(len(fights)), key=lambda i: (fights[i].hk + fights[i].am, -i))
        beats.append(beat(fights[biggest].start, "biggest_fight", fights[biggest].winner, biggest))
    patron = next((i for i, o in enumerate(objectives) if o.kind == "patron"), None)
    if patron is not None:
        beats.append(beat(objectives[patron].t, "patron", objectives[patron].by, patron))
    beats.sort(key=lambda b: b.t)

    def team_line(side: Side) -> TeamLine:
        mine = [p for p in players if p.team == side]
        taken = sum(1 for o in objectives if o.by == side and o.kind in SCORED_KINDS)
        taken += sum(1 for b in mid_boss if b.by == side)
        return TeamLine(
            letter=letters.get(side, ""),
            kills=sum(p.kills for p in mine),
            souls=sum(p.souls for p in mine),
            objectives=taken,
        )

    start = info.get("start_time")
    return Postgame(
        schema_version=SCHEMA_VERSION,
        deadlock_match_id=_int(info.get("match_id")),
        duration_s=duration,
        start_time=start if isinstance(start, int) else None,
        winner=_side(info.get("winning_team")),
        teams=Teams(hk=team_line("hk"), am=team_line("am")),
        players=players,
        timeline=timeline,
        deaths=deaths,
        first_blood=first_blood,
        fights=fights,
        objectives=objectives,
        structures=structures,
        mid_boss=mid_boss,
        events=events,
        beats=beats,
        awards=awards_for(players, first_blood),
        map=MapFrame(radius=MAP_RADIUS, scale=MAP_SCALE),
        replay=Replay(step_s=REPLAY_STEP_S, frames=frames, positions=positions),
        item_names={},
    )


# --- Storing it ------------------------------------------------------------------------------


def letters_of(match: Match) -> dict[Side, str]:
    hk = match.hidden_king_team
    if hk not in {"A", "B"}:
        return {}
    return {"hk": hk, "am": "B" if hk == "A" else "A"}


def save(match: Match, metadata: Mapping[str, Any]) -> MatchPostgame:
    """Build the document from this metadata and keep it, replacing any older one, and tell
    open pages. Raises ValueError for metadata with no players."""
    doc = document(
        metadata, league=league_players(match), hero_list=heroes(), letters=letters_of(match)
    )
    row, _created = MatchPostgame.objects.update_or_create(
        match=match,
        defaults={
            "deadlock_match_id": doc.deadlock_match_id or match.deadlock_match_id or 0,
            "schema_version": SCHEMA_VERSION,
            "data": doc.model_dump(mode="json"),
        },
    )
    live.publish(live.match_topic(match.pk))
    return row


def save_quietly(match: Match, metadata: Mapping[str, Any]) -> MatchPostgame | None:
    """`save`, for the result check: a failure is logged and rolled back on its own, and never
    breaks the check it's part of."""
    try:
        with transaction.atomic():
            return save(match, metadata)
    except Exception:
        logger.exception("Couldn't build the postgame for match %s", match.pk)
        return None


def build(match: Match, metadata: Mapping[str, Any] | None = None) -> MatchPostgame | None:
    """The match's postgame, built from `metadata`, or from deadlock-api's when none is given.
    Fetching is a network request: call it outside a transaction. None when the match has no
    Deadlock ID or deadlock-api has no data for it. Raises deadlock_api.ApiError when the fetch
    fails, and ValueError for metadata with no players."""
    if metadata is None:
        from league.integrations import deadlock_api

        if match.deadlock_match_id is None:
            return None
        metadata = deadlock_api.match_metadata(match.deadlock_match_id)
        if metadata is None:
            return None
    with transaction.atomic():
        return save(match, metadata)


def stored(match: Match) -> Postgame | None:
    """The match's document, when it has one in this schema, with the names of the items in
    its builds from the shop catalogue. Older ones need a rebuild."""
    row = MatchPostgame.objects.filter(match=match, schema_version=SCHEMA_VERSION).first()
    if row is None:
        return None
    doc = Postgame.model_validate(row.data)
    bought = {buy.item_id for line in doc.players for buy in line.build}
    return doc.model_copy(update={"item_names": items.names(bought)})
