"""dev_seed and reset: the dev fixtures on a fresh database, ratings through the ledger, and the
simulator's guild laid out the way /setup lays it out."""

from __future__ import annotations

import json
from io import StringIO
from typing import Any

import httpx
import pytest
from django.core.management import call_command
from django.utils import timezone

from bot.effects.gateway import SELF_TEXT, SELF_VOICE
from devtools import api, control, seed, sim_client
from devtools.errors import Conflict
from devtools.models import DevProfile
from league.models import (
    CaptainOverride,
    Community,
    CommunityRoleGrant,
    DraftModeVersion,
    Match,
    OutboxEffect,
    Player,
    PlayerRating,
)

pytestmark = pytest.mark.django_db

SIM_GUILD = 1_100_000_000_000_000_001
SIM_BOT = 1_100_000_000_000_000_002
STAFF_ROLE = 1_100_000_000_000_000_004
FIXTURE_IDS = [1_100_000_000_000_000_100 + n for n in range(14)]
VIEW, SEND = 1 << 10, 1 << 11


@pytest.fixture
def presets(db: None) -> None:
    """What compose's migrate job runs before dev_seed."""
    call_command("load_presets", stdout=StringIO())


def dev_seed(*args: str) -> str:
    out = StringIO()
    call_command("dev_seed", *args, stdout=out)
    return out.getvalue()


def test_dev_seed_loads_the_fixtures_and_seeds_ratings_once(presets: None) -> None:
    out = dev_seed()
    assert "Fixtures: loaded" in out
    assert "Ratings seeded: 14" in out
    community = Community.objects.get()
    assert (community.pk, community.discord_guild_id, community.name) == (
        1,
        SIM_GUILD,
        "Dev League",
    )
    latest = DraftModeVersion.objects.filter(slug="draft_3ban").order_by("-version").first()
    assert community.active_mode == latest
    assert community.runtime.api_results is False
    assert CommunityRoleGrant.objects.filter(role_id=STAFF_ROLE).count() == 7
    players = list(Player.objects.order_by("pk"))
    assert [p.discord_user_id for p in players] == FIXTURE_IDS
    ratings = dict(PlayerRating.objects.values_list("player__display_name", "rating"))
    assert (ratings["Ash"], ratings["Nico"], len(ratings)) == (1600, 400, 14)
    assert CaptainOverride.objects.filter(status="allow").count() == 14
    call_command("check_ledger", stdout=StringIO())

    out = dev_seed()
    assert "Fixtures: already there" in out
    assert "Ratings seeded: 0" in out
    assert "Captain overrides added: 0" in out
    assert PlayerRating.objects.count() == 14


def test_reloading_updates_the_rows_in_place(presets: None) -> None:
    dev_seed()
    Player.objects.filter(pk=1).update(display_name="Changed")
    assert "Fixtures: loaded" in dev_seed("--reload")
    assert Player.objects.get(pk=1).display_name == "Ash"
    assert Player.objects.count() == 14


def test_dev_seed_needs_the_presets(db: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(seed, "DEFAULT_MODE_SLUG", "not_published")
    with pytest.raises(Conflict, match="load_presets"):
        seed.run()


def test_without_a_simulator_the_channels_stay_unwired(presets: None) -> None:
    assert "Channels: not wired" in dev_seed()
    assert Community.objects.get().queue_channel_id is None


class FakeSim:
    """The simulator's control API over an in-memory guild: the seed's roles and #general, and
    the first twelve fixture players as members under the simulator's own names."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, Any]] = []
        self.next_id = 1_100_000_000_000_010_000
        self.reset()

    def reset(self) -> None:
        self.roles = [
            {"id": str(SIM_GUILD), "name": "@everyone"},
            {"id": str(STAFF_ROLE), "name": "Staff"},
        ]
        self.channels: list[dict[str, Any]] = [{"id": "600", "name": "general", "type": 0}]
        self.members: list[dict[str, Any]] = [
            {"id": str(uid), "name": "Ash" if n == 0 else f"player{n}", "roles": []}
            for n, uid in enumerate(FIXTURE_IDS[:12])
        ]

    def new_id(self) -> str:
        self.next_id += 1
        return str(self.next_id)

    def state(self) -> dict[str, Any]:
        return {
            "guild": {"id": str(SIM_GUILD), "name": "Sim", "owner_id": "42"},
            "bot": {"user_id": str(SIM_BOT), "application_id": str(SIM_BOT)},
            "roles": self.roles,
            "channels": self.channels,
            "members": self.members,
        }

    def channel(self, name: str) -> dict[str, Any]:
        return next(c for c in self.channels if c["name"] == name)

    def handle(self, request: httpx.Request) -> httpx.Response:
        body: Any = json.loads(request.content) if request.content else None
        path, method = request.url.path, request.method
        self.calls.append((method, path, body))
        if path == "/_sim/state":
            return httpx.Response(200, json=self.state())
        if path == "/_sim/reset":
            self.reset()
            return httpx.Response(200, json=self.state())
        if path == "/_sim/roles":
            role = {"id": self.new_id(), "name": body["name"]}
            self.roles.append(role)
            return httpx.Response(201, json=role)
        if path == "/_sim/channels":
            channel = {"id": self.new_id(), **body}
            self.channels.append(channel)
            return httpx.Response(201, json=channel)
        if path == "/_sim/users" and method == "POST":
            names = body.get("names") or [f"{body['name_prefix']}{n}" for n in range(body["count"])]
            roles = body.get("roles", [])
            users = [{"id": self.new_id(), "name": name, "roles": roles} for name in names]
            self.members.extend(users)
            return httpx.Response(201, json={"users": users})
        if path.startswith("/_sim/users/") and method == "PATCH":
            member = next(m for m in self.members if m["id"] == path.rsplit("/", 1)[1])
            member.update(body)
            return httpx.Response(200, json=member)
        return httpx.Response(200, json={"ok": True})


@pytest.fixture
def sim(settings: Any, monkeypatch: pytest.MonkeyPatch) -> FakeSim:
    fake = FakeSim()
    settings.DISCORD_SIM_URL = "http://sim.test"
    monkeypatch.setattr(sim_client, "TRANSPORT", httpx.MockTransport(fake.handle))
    return fake


SETUP_CHANNELS = [
    ("waiting_room_channel_id", "Waiting Room"),
    ("queue_channel_id", "queue"),
    ("results_channel_id", "results"),
    ("leaderboard_channel_id", "leaderboard"),
    ("archive_channel_id", "scoreboard-archive"),
    ("staff_channel_id", "staff-alerts"),
]


def test_dev_seed_lays_out_the_guild_as_setup_does(presets: None, sim: FakeSim) -> None:
    out = dev_seed()
    assert f"Guild: {SIM_GUILD}, the simulator's" in out
    assert "Channels made: Waiting Room, queue, results, leaderboard" in out
    assert "Channels and PUG role: wired" in out
    community = Community.objects.get()
    pug = next(role for role in sim.roles if role["name"] == "PUGS")
    assert community.pug_role_id == int(pug["id"])
    category = sim.channel("Deadlock")
    assert (category["type"], community.match_category_id) == (4, int(category["id"]))
    for field, name in SETUP_CHANNELS:
        channel = sim.channel(name)
        assert getattr(community, field) == int(channel["id"])
        assert channel["parent_id"] == category["id"]
        everyone = channel["permission_overwrites"][0]
        assert (everyone["id"], everyone["deny"]) == (str(SIM_GUILD), str(VIEW))
    queue = sim.channel("queue")["permission_overwrites"][1]
    assert (queue["id"], queue["allow"], queue["deny"]) == (pug["id"], str(VIEW), str(SEND))
    assert sim.channel("staff-alerts")["permission_overwrites"][1]["id"] == str(STAFF_ROLE)
    # Every channel grants the bot its own access, as /setup's do (SELF_TEXT, SELF_VOICE).
    text_allow, text_deny = (str(p.value) for p in SELF_TEXT.pair())
    voice_allow, voice_deny = (str(p.value) for p in SELF_VOICE.pair())
    for name, allow, deny in [
        ("Deadlock", voice_allow, voice_deny),
        ("Waiting Room", voice_allow, voice_deny),
        *((name, text_allow, text_deny) for _, name in SETUP_CHANNELS[1:]),
    ]:
        own = sim.channel(name)["permission_overwrites"][-1]
        assert own == {"id": str(SIM_BOT), "type": 1, "allow": allow, "deny": deny}, name
    # What /setup does last: the bot posts the queue panel and the leaderboard when it connects.
    kinds = set(OutboxEffect.objects.values_list("kind", flat=True))
    assert {"render_queue", "render_leaderboard"} <= kinds

    edits = [(path, body) for method, path, body in sim.calls if method == "PATCH"]
    assert len(edits) == 12  # Every member gets the PUG role, and all but Ash a new name.
    assert edits[1] == (f"/_sim/users/{FIXTURE_IDS[1]}", {"name": "Bex", "roles": [pug["id"]]})
    created = [
        body for method, path, body in sim.calls if method == "POST" and path == "/_sim/users"
    ]
    assert created == [
        {"count": 2, "dm_open": True, "roles": [pug["id"]], "names": ["Mags", "Nico"]}
    ]
    fixture_ids = Player.objects.filter(pk__in=[13, 14]).order_by("pk")
    assert list(fixture_ids.values_list("discord_user_id", flat=True)) == [
        int(user["id"]) for user in sim.members[-2:]
    ]
    assert DevProfile.objects.filter(sim_user=True).count() == 14

    calls = len(sim.calls)
    assert "Channels made" not in dev_seed()
    assert [call for call in sim.calls[calls:] if call[0] != "GET"] == []


def test_reset_goes_back_to_the_fixtures_and_restarts_ids(presets: None, sim: FakeSim) -> None:
    dev_seed()
    first_queue = Community.objects.get().queue_channel_id
    status, body = api.call("POST", "queue/fill", {})
    assert status == 200 and body["match_id"] is not None
    status, body = api.call("POST", "reset", {})
    assert status == 200, body
    assert body["seed"]["fixtures_loaded"] and body["seed"]["sim"]
    assert body["seed"]["channels_wired"] and len(body["seed"]["channels_created"]) == 6
    assert ("POST", "/_sim/reset", None) in sim.calls
    queue = body["state"]["community"]["channels"]["queue"]
    assert queue == sim.channel("queue")["id"] != str(first_queue)
    assert not Match.objects.exists()
    assert Player.objects.count() == 14
    assert body["state"]["queue"] == [] and body["state"]["matches"] == []
    call_command("check_ledger", stdout=StringIO())
    status, body = api.call("POST", "players", {"count": 1})
    assert body["players"][0]["id"] == 15
    made = [call for call in sim.calls if call[:2] == ("POST", "/_sim/users")][-1]
    assert made[2]["roles"] == [str(Community.objects.get().pug_role_id)]


def test_reset_without_players(presets: None) -> None:
    dev_seed()
    status, body = api.call("POST", "reset", {"fixture": "none"})
    assert status == 200, body
    assert body["seed"]["players"] == 0
    assert Community.objects.count() == 1 and not Player.objects.exists()
    assert api.call("POST", "reset", {"fixture": "other"})[0] == 400


def test_a_reset_stops_the_bots_effects_before_it_truncates(
    presets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev_seed()
    community = Community.objects.get()
    moment = timezone.now()
    waiting = OutboxEffect.objects.create(
        community=community, kind="render_queue", run_after=moment, created_at=moment
    )
    running = OutboxEffect.objects.create(
        community=community,
        kind="render_leaderboard",
        run_after=moment,
        started_at=moment,
        created_at=moment,
    )
    finished: list[int] = []

    def bot_finishes(seconds: float) -> None:
        # While the reset waits, the running effect finishes and queues one more.
        OutboxEffect.objects.filter(pk=running.pk).update(status="done", done_at=timezone.now())
        later = OutboxEffect.objects.create(
            community=community, kind="ping", run_after=moment, created_at=moment
        )
        finished.append(later.pk)

    monkeypatch.setattr(control.time, "sleep", bot_finishes)
    control._quiesce()
    assert OutboxEffect.objects.get(pk=waiting.pk).status == "skipped"
    assert OutboxEffect.objects.get(pk=running.pk).status == "done"
    [later] = finished
    assert OutboxEffect.objects.get(pk=later).status == "skipped"


def test_a_reset_doesnt_wait_out_an_effect_that_failed_into_a_retry(
    presets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    dev_seed()
    moment = timezone.now()
    running = OutboxEffect.objects.create(
        community=Community.objects.get(),
        kind="render_leaderboard",
        run_after=moment,
        started_at=moment,
        created_at=moment,
    )
    waits: list[float] = []

    def bot_fails(seconds: float) -> None:
        # What mark_retry leaves: an attempt counted, a later run_after, and no done_at.
        waits.append(seconds)
        OutboxEffect.objects.filter(pk=running.pk).update(attempts=1)

    monkeypatch.setattr(control.time, "sleep", bot_fails)
    control._quiesce()
    assert len(waits) == 1
    assert OutboxEffect.objects.get(pk=running.pk).status == "skipped"


def _other_session() -> Any:
    """A second database session, as the bot would hold."""
    import psycopg
    from django.db import connection

    return psycopg.connect(**connection.get_connection_params(), autocommit=False)


@pytest.mark.django_db(transaction=True)
def test_a_reset_waits_for_a_table_another_session_holds(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A reset takes every table before it empties any, retrying a try that would wait too long,
    so it can't deadlock with the bot's own locks."""
    call_command("load_presets", stdout=StringIO())
    dev_seed()
    other = _other_session()
    other.execute("SELECT 1 FROM players LIMIT 1")  # Holds players for its transaction.
    tries: list[float] = []
    real_sleep = control.time.sleep

    def release_on_the_third_try(seconds: float) -> None:
        tries.append(seconds)
        if len(tries) == 3:
            other.rollback()
        real_sleep(0)

    monkeypatch.setattr(control, "LOCK_TRY_MS", 50)
    monkeypatch.setattr(control.time, "sleep", release_on_the_third_try)
    try:
        status, body = api.call("POST", "reset", {})
    finally:
        other.close()
    assert status == 200, body
    assert len(tries) >= 3
    assert Player.objects.count() == 14


@pytest.mark.django_db(transaction=True)
def test_a_reset_gives_up_with_a_503_when_the_tables_stay_busy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    call_command("load_presets", stdout=StringIO())
    dev_seed()
    other = _other_session()
    other.execute("SELECT 1 FROM matches LIMIT 1")
    monkeypatch.setattr(control, "LOCK_TRY_MS", 20)
    monkeypatch.setattr(control, "RESET_SECONDS", 0.3)
    try:
        status, body = api.call("POST", "reset", {})
    finally:
        other.close()
    assert status == 503, body
    assert body["error"]["code"] == "busy"
    assert Player.objects.count() == 14  # Nothing was emptied.


def test_a_reset_goes_round_again_when_the_bot_claims_an_effect_meanwhile(
    presets: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An effect claimed between stopping the effects and taking the tables may be running: the
    reset lets go and stops the effects again, rather than empty the tables under it."""
    dev_seed()
    community = Community.objects.get()
    passes: list[int] = []
    real_quiesce = control._quiesce

    def quiesce_then_the_bot_claims_one() -> None:
        real_quiesce()
        passes.append(1)
        if len(passes) == 1:
            moment = timezone.now()
            OutboxEffect.objects.create(
                community=community,
                kind="render_queue",
                run_after=moment,
                started_at=moment,
                created_at=moment,
            )

    monkeypatch.setattr(control, "_quiesce", quiesce_then_the_bot_claims_one)
    monkeypatch.setattr(control, "QUIESCE_SECONDS", 0.2)  # The claimed one never finishes.
    before = OutboxEffect.objects.order_by("-pk").values_list("pk", flat=True).first()
    assert before is not None
    status, body = api.call("POST", "reset", {})
    assert status == 200, body
    assert len(passes) == 2
    # Outbox ids keep counting across the reset: a stale claim can't land on a new effect.
    first = OutboxEffect.objects.order_by("pk").values_list("pk", flat=True).first()
    assert first is not None and first > before
