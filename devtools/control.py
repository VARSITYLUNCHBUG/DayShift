"""What the control API does for players, the queue, plans and resets. Views stay thin over it."""

from __future__ import annotations

import random
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from django.apps import apps
from django.db import OperationalError, connection, transaction
from django.db.models import ProtectedError
from psycopg.errors import LockNotAvailable, QueryCanceled

from devtools import lookup, seed, sim_client
from devtools.errors import BadRequest, BotBusy, Conflict
from devtools.models import DevFlag, DevProfile, MatchScript
from devtools.rating import seed_ratings
from league.domain.engine import RANKED_COINFLIP_CHOICES
from league.domain.mode_schema import parse_mode
from league.models import (
    Community,
    Match,
    MatchParticipant,
    Player,
    PlayerRating,
    QueueEntry,
    RatingEvent,
)
from league.models.outbox import EffectStatus, OutboxEffect
from league.services import queue
from league.services.common import now

# Discord IDs for fake players when there is no simulator: clear of the simulator's range, the
# stand-ins under 1000 and the test suite's.
LOCAL_ID_BASE = 1_190_000_000_000_000_000
MAX_NEW_PLAYERS = 50
# Kept by a reset: what load_presets wrote.
KEEP_TABLES = frozenset({"champions", "draft_mode_versions"})
# How long a reset waits for the bot to finish the effects it is running.
QUIESCE_SECONDS = 5.0
# How long one try at locking the league tables may wait: under Postgres's deadlock_timeout.
LOCK_TRY_MS = 500
# How long a reset keeps trying for the tables before it gives up (503).
RESET_SECONDS = 30.0
LOBBY_CODE = re.compile(r"^[A-Za-z0-9-]{3,32}$")
# Whether deadlock-api makes lobbies: the simulator's stand-in, and the service path, follow it.
LOBBIES = "lobbies"
CREATE = "create"
FAIL = "fail"


# --- Ratings ---------------------------------------------------------------------------------


def _spread(rating: Any, count: int) -> list[int | None]:
    if rating is None:
        return [None] * count
    if isinstance(rating, bool) or not isinstance(rating, int | float | dict):
        raise BadRequest("rating must be a number or {min, max}.")
    if not isinstance(rating, dict):
        return [int(rating)] * count
    try:
        low, high = int(rating["min"]), int(rating["max"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BadRequest("A rating range needs numbers min and max.") from exc
    if low > high:
        raise BadRequest("The rating range's min is above its max.")
    if count == 1:
        return [low]
    return [round(low + (high - low) * index / (count - 1)) for index in range(count)]


# --- Players ---------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class NewUser:
    discord_user_id: int
    name: str
    sim_user: bool


def _new_users(count: int, prefix: str, dm_open: bool, pug_role_id: int | None) -> list[NewUser]:
    if sim_client.configured():
        roles = [pug_role_id] if pug_role_id else None
        with sim_client.client() as sim:
            users = sim.create_users(count, name_prefix=prefix, dm_open=dm_open, roles=roles)
        return [
            NewUser(
                int(user["id"]),
                str(user.get("name") or user.get("username") or f"{prefix} {user['id']}"),
                True,
            )
            for user in users
        ]
    highest = (
        Player.objects.filter(discord_user_id__gte=LOCAL_ID_BASE)
        .order_by("-discord_user_id")
        .values_list("discord_user_id", flat=True)
        .first()
    )
    start = (highest or LOCAL_ID_BASE) + 1
    number = Player.objects.count() + 1
    return [NewUser(start + index, f"{prefix} {number + index}", False) for index in range(count)]


def create_players(
    count: int,
    *,
    rating: Any = None,
    name_prefix: str = "Dev",
    join_queue: bool = False,
    dm_open: bool = True,
) -> tuple[list[Player], int | None]:
    """Make fake players (simulator users when there is one), seed their ratings, and join
    them to the queue in order. Returns them and the match a full queue popped, if any."""
    if not 1 <= count <= MAX_NEW_PLAYERS:
        raise BadRequest(f"count must be between 1 and {MAX_NEW_PLAYERS}.")
    values = _spread(rating, count)
    league = lookup.community()
    season = lookup.open_season(league)
    users = _new_users(count, name_prefix[:40] or "Dev", dm_open, league.pug_role_id)
    with transaction.atomic():
        created = []
        for user in users:
            player = Player.objects.from_discord(user.discord_user_id, user.name)
            DevProfile.objects.update_or_create(
                player=player, defaults={"dm_open": dm_open, "sim_user": user.sim_user}
            )
            created.append(player)
        seed_ratings(
            season,
            [(p, value) for p, value in zip(created, values, strict=True) if value is not None],
        )
    match_id = join_queue_players(league, created) if join_queue else None
    return created, match_id


def free_players(count: int) -> list[Player]:
    """The first players by id who could join the queue now."""
    if count < 1:
        raise BadRequest("count must be at least 1.")
    busy = MatchParticipant.objects.filter(is_active=True).values("player_id")
    rows = list(
        Player.objects.exclude(pk__in=busy)
        .exclude(pk__in=QueueEntry.objects.values("player_id"))
        .exclude(dev_profile__retired=True)
        .order_by("pk")[:count]
    )
    if len(rows) < count:
        raise Conflict(f"Only {len(rows)} players are free to join. Add more first.")
    return rows


def join_queue_players(league: Community, players: Sequence[Player]) -> int | None:
    match_id = None
    for player in players:
        status = queue.join(league.pk, player)
        match_id = status.match_id or match_id
    return match_id


def leave_queue(league: Community, players: Sequence[Player]) -> None:
    for player in players:
        queue.leave(league.pk, player)


def fill_queue(*, rating: Any = None) -> tuple[list[Player], int | None]:
    league = lookup.community()
    size = parse_mode(league.active_mode.body).lobby_size
    need = size - QueueEntry.objects.filter(community=league).count()
    if need <= 0:
        popped = queue.pop_if_ready(league.pk)
        return [], popped.pk if popped else None
    return create_players(need, rating=rating, name_prefix="Fill", join_queue=True)


def update_player(
    player: Player, *, rating: int | None, name: str | None, dm_open: bool | None
) -> None:
    if name is not None and not name.strip():
        raise BadRequest("A name can't be empty.")
    profile, _ = DevProfile.objects.get_or_create(player=player)
    if profile.sim_user and (name is not None or dm_open is not None):
        fields = {
            key: value for key, value in (("name", name), ("dm_open", dm_open)) if value is not None
        }
        with sim_client.client() as sim:
            sim.update_user(player.discord_user_id, **fields)
    if name is not None:
        Player.objects.from_discord(player.discord_user_id, name.strip())
    if dm_open is not None:
        profile.dm_open = dm_open
        profile.save(update_fields=["dm_open"])
    if rating is not None:
        seed_ratings(lookup.open_season(lookup.community()), [(player, rating)])


def delete_player(player: Player) -> str:
    """Delete a player with no history; retire one the ledger or a match still refers to."""
    live = MatchParticipant.objects.filter(player=player, is_active=True).first()
    if live is not None:
        raise Conflict(f"{player.display_name} is in match #{live.match_id}. Finish it first.")
    league = lookup.community_or_none()
    if league is not None:
        queue.kick(league.pk, player)
    profile, _ = DevProfile.objects.get_or_create(player=player)
    if profile.sim_user:
        with sim_client.client() as sim:
            sim.delete_user(player.discord_user_id)
    has_history = (
        RatingEvent.objects.filter(player=player).exists()
        or MatchParticipant.objects.filter(player=player).exists()
    )
    if not has_history:
        try:
            with transaction.atomic():
                PlayerRating.objects.filter(player=player).delete()
                player.delete()
            return "hard"
        except ProtectedError:
            pass
    profile.retired = True
    profile.sim_user = False
    profile.save(update_fields=["retired", "sim_user"])
    return "retired"


# --- Plans -----------------------------------------------------------------------------------


def _champion_ids(refs: Any, what: str) -> list[int]:
    if not isinstance(refs, list):
        raise BadRequest(f"{what} must be a list of champion slugs.")
    return list(dict.fromkeys(lookup.champion(ref).pk for ref in refs))


def set_picks(player: Player, *, prefer: Any, ban: Any) -> None:
    DevProfile.objects.update_or_create(
        player=player,
        defaults={
            "prefer": _champion_ids(prefer or [], "prefer"),
            "ban": _champion_ids(ban or [], "ban"),
        },
    )


def _int_list(value: Any, what: str) -> list[int]:
    if not isinstance(value, list) or not all(
        isinstance(item, int) and not isinstance(item, bool) for item in value
    ):
        raise BadRequest(f"{what} must be a list of player ids.")
    return value


# What a match script may say (see README). The control panel's MatchScript has the same keys.
SCRIPT_KEYS = frozenset({"draft", "champions", "captain_votes", "coinflip", "lobby_code", "winner"})


def clean_script(body: dict[str, Any]) -> dict[str, Any]:
    """Check a match script (see README) and normalise champion references to ids."""
    unknown = set(body) - SCRIPT_KEYS
    if unknown:
        raise BadRequest(f"Unknown script keys: {', '.join(sorted(unknown))}.")
    script: dict[str, Any] = {}
    if "draft" in body:
        script["draft"] = _int_list(body["draft"], "draft")
    if "champions" in body:
        if not isinstance(body["champions"], list):
            raise BadRequest("champions must be a list of {step, slug, team?}.")
        steps = []
        for entry in body["champions"]:
            if not isinstance(entry, dict) or not isinstance(entry.get("step"), int):
                raise BadRequest("Each champion entry needs a step number and a slug.")
            team = entry.get("team")
            if team not in {None, "A", "B"}:
                raise BadRequest("A champion entry's team is A or B.")
            champion = lookup.champion(str(entry.get("slug") or entry.get("champion") or ""))
            steps.append({"step": entry["step"], "team": team, "champion": champion.pk})
        script["champions"] = steps
    if "captain_votes" in body:
        votes = body["captain_votes"]
        if not isinstance(votes, dict):
            raise BadRequest("captain_votes maps a voter id (or *) to a list of candidates.")
        script["captain_votes"] = {
            str(voter): _int_list(candidates, "captain_votes")[:2]
            for voter, candidates in votes.items()
        }
    if "coinflip" in body:
        if body["coinflip"] not in RANKED_COINFLIP_CHOICES:
            raise BadRequest(f"coinflip is one of {', '.join(RANKED_COINFLIP_CHOICES)}.")
        script["coinflip"] = body["coinflip"]
    if "lobby_code" in body:
        if not isinstance(body["lobby_code"], str) or not LOBBY_CODE.match(body["lobby_code"]):
            raise BadRequest("lobby_code is 3 to 32 letters, digits or dashes.")
        script["lobby_code"] = body["lobby_code"]
    if "winner" in body:
        if body["winner"] not in {"A", "B"}:
            raise BadRequest("winner is A or B.")
        script["winner"] = body["winner"]
    return script


def set_script(match: Match, body: dict[str, Any]) -> None:
    MatchScript.objects.update_or_create(match=match, defaults={"body": clean_script(body)})


def script_of(match: Match) -> dict[str, Any]:
    row = MatchScript.objects.filter(match=match).first()
    return dict(row.body) if row else {}


# --- deadlock-api lobbies ---------------------------------------------------------------------


def lobbies() -> str:
    """Whether deadlock-api makes the next lobbies ("create") or refuses them ("fail")."""
    flag = DevFlag.objects.filter(key=LOBBIES).first()
    return str(flag.value.get("mode", CREATE)) if flag else CREATE


def set_lobbies(mode: str) -> None:
    """Set it for the simulator's deadlock-api stand-in and for the service path alike. A match
    already in its lobby step keeps the answer it got."""
    if mode not in {CREATE, FAIL}:
        raise BadRequest(f'lobby is "{CREATE}" or "{FAIL}".')
    if sim_client.reachable():
        with sim_client.client() as sim:
            sim.set_lobbies(mode)
    DevFlag.objects.update_or_create(key=LOBBIES, defaults={"value": {"mode": mode}})


# --- Reset -----------------------------------------------------------------------------------


def _tables() -> list[str]:
    """Every table a reset empties: the league's and devtools' own, and any other that refers to
    one of them (TRUNCATE ... CASCADE empties those too, so the reset locks them as well)."""
    tables = set()
    for label in ("league", "devtools"):
        for model in apps.get_app_config(label).get_models(include_auto_created=True):
            table = model._meta.db_table
            if model._meta.managed and table not in KEEP_TABLES:
                tables.add(table)
    models = [m for m in apps.get_models(include_auto_created=True) if m._meta.managed]
    grew = True
    while grew:
        grew = False
        for model in models:
            table = model._meta.db_table
            # A kept table that names a player keeps its rows: the reset clears that column.
            if table in tables or table in KEEP_TABLES:
                continue
            targets = {
                f.related_model._meta.db_table
                for f in model._meta.concrete_fields
                if f.is_relation and f.related_model is not None
            }
            if targets & tables:
                tables.add(table)
                grew = True
    return sorted(tables)


def _lock_tables(tables: list[str], give_up: float) -> None:
    """Take every table the reset empties, all at once, before touching any of them.

    The bot's loops read and lock these tables in their own orders (a pass of the
    deadline loop joins outbox_effects to matches, a queue pop locks the community first), so a
    TRUNCATE that takes its locks one by one can deadlock with them. Each try here is bounded by
    a statement timeout below Postgres's deadlock_timeout (1 s): a try that would deadlock gives
    up before Postgres picks a victim, lets go of what it got, and goes again. Once this returns,
    nothing else touches league state until the reset commits: no deadline fires, no effect is
    claimed, no interaction lands."""
    names = ", ".join(connection.ops.quote_name(table) for table in tables)
    while True:
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                # SET LOCAL: transaction-scoped, so it ends with the reset's transaction.
                cursor.execute(f"SET LOCAL statement_timeout = {LOCK_TRY_MS}")
                cursor.execute(f"LOCK TABLE {names} IN ACCESS EXCLUSIVE MODE")
                cursor.execute("SET LOCAL statement_timeout TO DEFAULT")
            return
        except OperationalError as exc:
            if not isinstance(exc.__cause__, QueryCanceled | LockNotAvailable):
                raise
            if time.monotonic() >= give_up:
                raise BotBusy(
                    "The reset couldn't get the league tables: the bot kept "
                    f"them busy for {RESET_SECONDS:g} s. Try again."
                ) from exc
        time.sleep(random.uniform(0.02, 0.15))  # Jitter, so two tries don't keep colliding.


def _claimed_since_quiesce() -> bool:
    """Whether the bot claimed an effect after `_quiesce` last looked: it marked every pending
    effect skipped, so a pending one that has started is new, and may be running now."""
    return OutboxEffect.objects.filter(
        status=EffectStatus.PENDING, started_at__isnull=False
    ).exists()


def _quiesce() -> None:
    """Stop the bot's pending effects and give the ones it is running a moment to finish. One
    still running across the TRUNCATE would write to rows that are gone, or to the new match that
    gets its id once ids restart. An effect that finishes can queue more, so this repeats."""
    deadline = time.monotonic() + QUIESCE_SECONDS
    running: dict[int, int] = {}
    while True:
        pending = OutboxEffect.objects.filter(status=EffectStatus.PENDING)
        # The unclaimed first: the worker claims only a pending effect, so these never start.
        pending.filter(started_at__isnull=True).update(status=EffectStatus.SKIPPED, done_at=now())
        # Then those claimed before that. A running one, when it finishes, sets done_at, or
        # counts an attempt if it is to be retried; one waiting for a retry isn't running.
        running |= dict(pending.filter(run_after__lte=now()).values_list("pk", "attempts"))
        pending.update(status=EffectStatus.SKIPPED)
        still = OutboxEffect.objects.filter(pk__in=running, done_at__isnull=True)
        busy = any(running[pk] == attempts for pk, attempts in still.values_list("pk", "attempts"))
        if not busy or time.monotonic() >= deadline:
            return
        time.sleep(0.1)


def reset(fixture: str = "dev_default") -> seed.SeedReport:
    """Back to the dev fixtures: the simulator's seeded state, empty league tables (champions and
    draft modes stay, ids restart at 1), then dev_seed, which lays out the guild again.

    In order: stop the bot's effects, then lock every league table, so nothing (a deadline the
    bot fires, an effect it claims) can happen between the two and outlive the wipe.
    An effect the bot claimed in between sends the reset round again. Outbox ids keep counting
    rather than restart: a claim the bot read before the wipe then finds no row, instead of a
    new effect with the old one's id."""
    if fixture not in {"dev_default", "none"}:
        raise BadRequest('fixture is "dev_default" or "none".')
    tables = _tables()
    give_up = time.monotonic() + RESET_SECONDS
    while True:
        _quiesce()
        with transaction.atomic():
            _lock_tables(tables, give_up)
            if _claimed_since_quiesce() and time.monotonic() < give_up:
                transaction.set_rollback(True)
                continue
            if sim_client.reachable():
                with sim_client.client() as sim:
                    sim.reset()
            # Players are emptied apart from the rest: a kept table (a draft mode's created_by)
            # refers to them, and TRUNCATE ... CASCADE would empty it too.
            players = Player._meta.db_table
            names = ", ".join(connection.ops.quote_name(t) for t in tables if t != players)
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_get_serial_sequence(%s, 'id')", [OutboxEffect._meta.db_table]
                )
                (outbox_ids,) = cursor.fetchone()
                cursor.execute(f"SELECT last_value FROM {outbox_ids}")
                (last_id,) = cursor.fetchone()
                # Settle deferred foreign key checks first: TRUNCATE refuses while any are pending.
                cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
                logins = _admin_logins()
                cursor.execute(f"TRUNCATE {names} RESTART IDENTITY CASCADE")
                _empty_players(cursor)
                cursor.execute("SET CONSTRAINTS ALL DEFERRED")
                cursor.execute("SELECT setval(%s, %s)", [outbox_ids, last_id])
            report = seed.run(players=fixture == "dev_default")
            _restore_admin_logins(logins)
            return report


# What a reset keeps of each admin login: players are the user model, so the wipe takes them too.
ADMIN_LOGIN_FIELDS = (
    "discord_user_id",
    "display_name",
    "username",
    "password",
    "email",
    "is_staff",
    "is_superuser",
    "is_active",
)


def _empty_players(cursor: Any) -> None:
    """Every player but those a kept row still names (whoever saved a draft mode: those rows are
    append-only), then ids from just past whoever stayed."""
    keep = [
        (model._meta.db_table, field.column)
        for model in apps.get_app_config("league").get_models()
        if model._meta.db_table in KEEP_TABLES
        for field in model._meta.concrete_fields
        if field.is_relation and field.related_model is Player and field.column
    ]
    quote = connection.ops.quote_name
    players = quote(Player._meta.db_table)
    named = " UNION ".join(
        f"SELECT {quote(column)} FROM {quote(table)} WHERE {quote(column)} IS NOT NULL"
        for table, column in keep
    )
    cursor.execute(f"DELETE FROM {players}" + (f" WHERE id NOT IN ({named})" if named else ""))
    cursor.execute(
        f"SELECT setval(pg_get_serial_sequence(%s, 'id'), "
        f"COALESCE((SELECT max(id) FROM {players}), 0) + 1, false)",
        [Player._meta.db_table],
    )


def _admin_logins() -> list[dict[str, Any]]:
    staff = Player.objects.filter(is_staff=True) | Player.objects.filter(is_superuser=True)
    return list(staff.values(*ADMIN_LOGIN_FIELDS))


def _restore_admin_logins(logins: list[dict[str, Any]]) -> None:
    """Every admin login back after a reset, merged into the fixture player with the same Discord
    ID if there is one. Its groups and permissions don't survive; staff areas live in Discord."""
    for login in logins:
        discord_user_id = login.pop("discord_user_id")
        Player.objects.update_or_create(discord_user_id=discord_user_id, defaults=login)
