"""dev_seed: the dev fixtures, then what fixtures can't hold (see README, commands).

Against the simulator it also lays out the guild the way `/setup` does, so a dev stack works
from the first click without anyone running `/setup`: the PUG role, the category, the Waiting
Room, the queue, results, leaderboard, archive and staff-alerts channels with `/setup`'s access
rules, wired into the community as `/setup` wires them. `/setup` run later keeps them: it only
fills in what is missing.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import discord
from django.conf import settings
from django.core import serializers
from django.core.management.color import no_style
from django.db import connection, models, transaction

from bot.effects.gateway import MEMBER_OVERWRITE as MEMBER
from bot.effects.gateway import SELF_TEXT, SELF_VOICE
from devtools import lookup, sim_client
from devtools.errors import Conflict
from devtools.models import DevProfile
from devtools.rating import seed_ratings
from league.models import CaptainOverride, Community, DraftModeVersion, Player, PlayerRating
from league.services import common, leaderboards, permissions, standing
from league.services import community as community_service
from league.services.community import DEFAULT_MODE_SLUG

FIXTURES = settings.BASE_DIR / "fixtures" / "dev"
PUG_ROLE = "PUGS"
# Discord's channel types and the permission bits /setup's overwrites use.
CATEGORY, TEXT, VOICE = 4, 0, 2
VIEW, SEND, HISTORY, CONNECT = 1 << 10, 1 << 11, 1 << 16, 1 << 20
ROLE = 0


@dataclass(frozen=True, slots=True)
class Room:
    """One of the channels /setup makes, and who sees it."""

    field: str
    name: str
    type: int
    access: str  # "pug_voice", "pug_text" (the PUG role's), "match_staff" or "staff"


ROOMS = (
    Room("waiting_room_channel_id", "Waiting Room", VOICE, "pug_voice"),
    Room("queue_channel_id", "queue", TEXT, "pug_text"),
    Room("results_channel_id", "results", TEXT, "pug_text"),
    Room("leaderboard_channel_id", "leaderboard", TEXT, "pug_text"),
    Room("archive_channel_id", "scoreboard-archive", TEXT, "match_staff"),
    Room("staff_channel_id", "staff-alerts", TEXT, "staff"),
)
WIRED_FIELDS = ("match_category_id", "pug_role_id", *(room.field for room in ROOMS))


@dataclass(slots=True)
class SeedReport:
    fixtures_loaded: bool = False
    players: int = 0
    ratings_seeded: int = 0
    captains_allowed: int = 0
    sim: bool = False
    guild_id: str | None = None
    channels_created: list[str] = field(default_factory=list)
    channels_wired: bool = False

    def as_json(self) -> dict[str, Any]:
        return asdict(self)


def fixture_files(*, players: bool = True) -> list[Path]:
    files = sorted(FIXTURES.glob("*.json"))
    if players:
        return files
    return [path for path in files if path.name < "30_"]


def fixture_player_ids() -> list[int]:
    rows = json.loads((FIXTURES / "30_players.json").read_text(encoding="utf-8"))
    return [row["pk"] for row in rows if row["model"] == "league.player"]


def load_fixtures(files: list[Path]) -> None:
    """What loaddata does, except that the community's draft mode is the latest draft_3ban
    whatever its pk: the fixture's pk is only right on a fresh database."""
    mode = DraftModeVersion.objects.filter(slug=DEFAULT_MODE_SLUG).order_by("-version").first()
    if mode is None:
        raise Conflict("There are no draft modes yet. Run manage.py load_presets first.")
    loaded: set[type[models.Model]] = set()
    with transaction.atomic():
        for path in files:
            for row in serializers.deserialize("json", path.read_text(encoding="utf-8")):
                if isinstance(row.object, Community):
                    row.object.active_mode_id = mode.pk
                row.save()
                loaded.add(type(row.object))
        with connection.cursor() as cursor:
            for sql in connection.ops.sequence_reset_sql(no_style(), list(loaded)):
                cursor.execute(sql)


def wired(league: Community) -> bool:
    """Whether the community has every channel and the role /setup sets."""
    return all(getattr(league, name) for name in WIRED_FIELDS)


def _name(row: dict[str, Any]) -> str:
    return str(row.get("name") or row.get("username") or row.get("global_name") or "")


def _own(bot_id: int, overwrite: discord.PermissionOverwrite) -> dict[str, Any]:
    """The bot's own member overwrite on a channel it made, from /setup's own constants."""
    allow, deny = overwrite.pair()
    return {"id": str(bot_id), "type": MEMBER, "allow": str(allow.value), "deny": str(deny.value)}


def _overwrites(
    access: str, guild_id: int, pug_role_id: int, bot_id: int, league: Community
) -> list[Any]:
    """/setup's access rules: players' channels for the PUG role alone, read-only for text; the
    archive for match staff and staff-alerts for all staff, hidden from everyone else. Each also
    grants the bot its own access (SELF_TEXT or SELF_VOICE), as every channel the bot makes does."""
    hidden = {"id": str(guild_id), "type": ROLE, "deny": str(VIEW)}
    if access == "pug_voice":
        return [
            hidden,
            {"id": str(pug_role_id), "type": ROLE, "allow": str(VIEW | CONNECT)},
            _own(bot_id, SELF_VOICE),
        ]
    if access == "pug_text":
        return [
            hidden,
            {"id": str(pug_role_id), "type": ROLE, "allow": str(VIEW), "deny": str(SEND)},
            _own(bot_id, SELF_TEXT),
        ]
    areas = permissions.MATCH_STAFF_AREAS if access == "match_staff" else permissions.ALL_AREAS
    staff = permissions.role_ids_with(league.pk, areas)
    allow, deny = (VIEW | HISTORY, SEND) if access == "match_staff" else (VIEW | HISTORY, 0)
    return [
        hidden,
        *({"id": str(r), "type": ROLE, "allow": str(allow), "deny": str(deny)} for r in staff),
        _own(bot_id, SELF_TEXT),
    ]


def _wire_guild(sim: sim_client.SimClient, league: Community, state: dict[str, Any]) -> list[str]:
    """Make whatever role and channels the community is missing in the simulator, as /setup
    would, and wire them. Returns the names of the channels made."""
    guild_id = int(state["guild"]["id"])
    bot_id = int(state["bot"]["user_id"])
    live = {int(c["id"]) for c in state.get("channels") or []}
    roles = {int(r["id"]): str(r["name"]) for r in state.get("roles") or []}
    wiring: dict[str, Any] = {}
    pug_role_id = league.pug_role_id
    if pug_role_id not in roles:
        found = [pk for pk, name in roles.items() if name == PUG_ROLE]
        pug_role_id = found[0] if found else int(sim.create_role(PUG_ROLE)["id"])
        wiring["pug_role_id"] = pug_role_id
    category = league.match_category_id
    if category not in live:
        body = {
            "name": "Deadlock",
            "type": CATEGORY,
            "permission_overwrites": [_own(bot_id, SELF_VOICE)],
        }
        category = int(sim.create_channel(body)["id"])
        wiring["match_category_id"] = category
    made = []
    for room in ROOMS:
        if getattr(league, room.field) in live:
            continue
        channel = sim.create_channel(
            {
                "name": room.name,
                "type": room.type,
                "parent_id": str(category),
                "permission_overwrites": _overwrites(
                    room.access, guild_id, pug_role_id, bot_id, league
                ),
            }
        )
        wiring[room.field] = int(channel["id"])
        made.append(room.name)
    if "queue_channel_id" in wiring:
        wiring["queue_message_id"] = None
    if "leaderboard_channel_id" in wiring:
        wiring["leaderboard_message_ids"] = []
    if wiring:
        community_service.save_wiring(league.pk, **wiring)
    if guild_id != league.discord_guild_id:
        Community.objects.filter(pk=league.pk).update(discord_guild_id=guild_id)
    return made


def _wire_members(
    sim: sim_client.SimClient, state: dict[str, Any], pug_role_id: int, player_ids: list[int]
) -> None:
    """Make every fixture player a simulator member with the fixture's name and the PUG role."""
    members = {int(m["id"]): m for m in state.get("members") or []}
    fixture = list(Player.objects.filter(pk__in=player_ids).order_by("pk"))
    for player in fixture:
        member = members.get(player.discord_user_id)
        if member is None:
            continue
        roles = [int(r) for r in member.get("roles") or []]
        changes: dict[str, Any] = {}
        if _name(member) != player.display_name:
            changes["name"] = player.display_name
        if pug_role_id not in roles:
            changes["roles"] = [str(role) for role in (*roles, pug_role_id)]
        if changes:
            sim.update_user(player.discord_user_id, **changes)
    missing = [player for player in fixture if player.discord_user_id not in members]
    if missing:
        users = sim.create_users(
            len(missing), names=[p.display_name for p in missing], roles=[pug_role_id]
        )
        for player, user in zip(missing, users, strict=True):
            Player.objects.filter(pk=player.pk).update(discord_user_id=int(user["id"]))
    DevProfile.objects.filter(player_id__in=player_ids).update(sim_user=True)


def _wire_sim(league: Community, player_ids: list[int], report: SeedReport) -> None:
    with sim_client.client() as sim:
        state = sim.state()
        report.channels_created = _wire_guild(sim, league, state)
        league.refresh_from_db()
        assert league.pug_role_id is not None
        _wire_members(sim, state, league.pug_role_id, player_ids)
    if report.channels_created:
        # What /setup does last: the bot posts the queue panel and the leaderboard.
        common.render_queue(league)
        leaderboards.request(league)
    report.guild_id = str(league.discord_guild_id)
    report.sim = True


def run(*, reload: bool = False, players: bool = True) -> SeedReport:
    """Load the fixtures into an empty database (or always, with `reload`), lay out and wire
    the simulator's guild, and seed what fixtures can't hold. Safe to run again."""
    report = SeedReport()
    if reload or not Community.objects.exists():
        load_fixtures(fixture_files(players=players))
        report.fixtures_loaded = True
    league = lookup.community()
    player_ids = fixture_player_ids() if players else []
    player_ids = list(Player.objects.filter(pk__in=player_ids).values_list("pk", flat=True))
    report.players = len(player_ids)
    if sim_client.reachable():
        _wire_sim(league, player_ids, report)
    league.refresh_from_db()
    report.channels_wired = wired(league)
    report.guild_id = report.guild_id or str(league.discord_guild_id)

    season = lookup.open_season(league)
    seeded = set(
        PlayerRating.objects.filter(season=season, player_id__in=player_ids).values_list(
            "player_id", flat=True
        )
    )
    todo = [
        (profile.player, profile.seed_rating)
        for profile in DevProfile.objects.filter(player_id__in=player_ids)
        .exclude(player_id__in=seeded)
        .exclude(seed_rating__isnull=True)
        .select_related("player")
        .order_by("player_id")
    ]
    seed_ratings(season, [(player, rating) for player, rating in todo if rating is not None])
    report.ratings_seeded = len(todo)

    with transaction.atomic():
        allowed = set(
            CaptainOverride.objects.filter(community=league).values_list("player_id", flat=True)
        )
        for player in Player.objects.filter(pk__in=player_ids).exclude(pk__in=allowed):
            standing.set_override(league, player, "allow", None, "dev fixture player")
            report.captains_allowed += 1
    return report
