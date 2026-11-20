"""Signing in to the player web UI: Discord OAuth, Steam OpenID, the session and dev login.

Discord and Steam are never called: every client goes through one mock transport, and the
Steam answers are built here the way Steam builds them.
"""

from __future__ import annotations

import asyncio
import json
import secrets
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.db import connections
from django.test import Client
from django.utils import timezone

from league.asyncdb import db
from league.domain import steam as steam_ids
from league.domain.errors import InvalidAction
from league.integrations import discord_rest
from league.models import Player, SteamAccount
from league.services import live
from league.services import steam as steam_service
from league.web.auth import discord_oauth, errors, steam_openid
from league.web.auth.session import SESSION_KEY, player_of_session, sign_in
from league.web.auth.views import safe_next
from tests.conftest import make_player

GUILD = 999
USER = 123456789012345678
STEAM64 = 76561198060265732
ACCOUNT = 100000004
SESSION_URL = "/auth/session/"


@dataclass
class Fake:
    """What Discord and Steam answer. Members are keyed by Discord user ID."""

    user_id: int = USER
    members: dict[int, dict[str, Any]] = field(default_factory=dict)
    token_status: int = 200
    member_status: int | None = None
    steam_valid: bool = True
    steam_down: bool = False
    persona: str = "SteamName"
    rate_limits: int = 0
    seen: list[httpx.Request] = field(default_factory=list)

    def member(
        self,
        user_id: int = USER,
        *,
        nick: str = "",
        global_name: str = "",
        username: str = "u",
        avatar: str = "abc123",
    ) -> None:
        self.members[user_id] = {
            "user": {
                "id": str(user_id),
                "username": username,
                "global_name": global_name or None,
                "avatar": avatar or None,
            },
            "nick": nick or None,
            "roles": ["11", "22"],
        }

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.seen.append(request)
        host, path = request.url.host, request.url.path
        if host == "discord.com" and path == "/api/oauth2/token":
            return httpx.Response(self.token_status, json={"access_token": "user-token"})
        if host == "discord.com" and path == "/api/v10/users/@me":
            return httpx.Response(200, json={"id": str(self.user_id)})
        if host == "discord.com" and path.startswith(f"/api/v10/guilds/{GUILD}/members/"):
            if self.member_status is not None:
                return httpx.Response(self.member_status, json={"message": "down"})
            body = self.members.get(int(path.rsplit("/", 1)[1]))
            if body is None:
                return httpx.Response(404, json={"message": "Unknown Member", "code": 10007})
            return httpx.Response(200, json=body)
        if host == "discord.com" and path.startswith("/api/v10/channels/"):
            if self.rate_limits:
                self.rate_limits -= 1
                return httpx.Response(429, json={"retry_after": 0.25, "global": False})
            return httpx.Response(200, json={"id": "1", "attachments": [{"url": "https://x"}]})
        if host == "steamcommunity.com" and path == "/openid/login":
            if self.steam_down:
                raise httpx.ConnectError("down", request=request)
            valid = "true" if self.steam_valid else "false"
            return httpx.Response(200, text=f"ns:{steam_openid.NS}\nis_valid:{valid}\n")
        if host == "api.steampowered.com":
            return httpx.Response(
                200, json={"response": {"players": [{"personaname": self.persona}]}}
            )
        return httpx.Response(404, json={"message": "Unknown", "code": 0})


@pytest.fixture
def published(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    topics: list[str] = []
    original = live.publish

    def record(*names: str) -> None:
        topics.extend(names)
        original(*names)

    monkeypatch.setattr(live, "publish", record)
    return topics


@pytest.fixture
def fake(monkeypatch: pytest.MonkeyPatch, settings: Any, db: None) -> Iterator[Fake]:
    settings.PUBLIC_URL = "http://testserver"
    settings.WEB_GUILD_ID = GUILD
    settings.DISCORD_CLIENT_ID = "client"
    settings.DISCORD_CLIENT_SECRET = "secret"
    settings.DISCORD_TOKEN = "bot-token"
    settings.DISCORD_API_BASE = "https://discord.com/api/v10"
    settings.DISCORD_INVITE_URL = ""
    settings.STEAM_WEB_API_KEY = ""
    settings.WEB_DEV_LOGIN = False
    state = Fake()
    transport = httpx.MockTransport(state.handle)
    monkeypatch.setattr(
        discord_rest,
        "_client",
        lambda: httpx.Client(
            base_url=discord_rest.api_base(), headers=discord_rest._headers(), transport=transport
        ),
    )
    monkeypatch.setattr(discord_oauth, "_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(steam_openid, "_client", lambda: httpx.Client(transport=transport))
    monkeypatch.setattr(discord_rest, "_sleep", lambda _seconds: None)
    cache.clear()
    yield state
    cache.clear()


def query_of(url: str) -> dict[str, str]:
    return {key: values[0] for key, values in parse_qs(urlparse(url).query).items()}


def refused(response: Any, code: str) -> bool:
    assert code in errors.CODES
    return response.status_code == 302 and response["Location"] == f"/signin?error={code}"


def signed_in(client: Client) -> int | None:
    value = client.session.get(SESSION_KEY)
    return value if isinstance(value, int) else None


def sign_in_as(client: Client, player: Player) -> None:
    session = client.session
    session[SESSION_KEY] = player.pk
    session.save()


# --- Discord ---------------------------------------------------------------------------------


def discord_start(client: Client, next_url: str | None = None) -> str:
    response = client.get("/auth/discord/", {"next": next_url} if next_url else {})
    assert response.status_code == 302
    return query_of(response["Location"])["state"]


def discord_sign_in(client: Client, next_url: str | None = None) -> Any:
    state = discord_start(client, next_url)
    return client.get("/auth/discord/callback/", {"code": "the-code", "state": state})


def test_discord_asks_for_identify_only_and_comes_back_to_public_url(fake: Fake) -> None:
    response = Client().get("/auth/discord/")
    url = urlparse(response["Location"])
    query = query_of(response["Location"])
    assert (url.scheme, url.netloc, url.path) == ("https", "discord.com", "/oauth2/authorize")
    assert query["scope"] == "identify"
    assert query["response_type"] == "code"
    assert query["redirect_uri"] == "http://testserver/auth/discord/callback/"
    assert query["client_id"] == "client" and len(query["state"]) >= 32


def test_discord_without_a_client_is_refused(fake: Fake, settings: Any) -> None:
    settings.DISCORD_CLIENT_SECRET = ""
    assert refused(Client().get("/auth/discord/"), "discord-down")


@pytest.mark.parametrize(
    ("member", "shown"),
    [
        ({"nick": "Nick", "global_name": "Global", "username": "user"}, "Nick"),
        ({"global_name": "Global", "username": "user"}, "Global"),
        ({"username": "user"}, "user"),
    ],
    ids=["nickname-first", "then-global-name", "then-username"],
)
def test_a_member_signs_in_under_their_server_name(
    fake: Fake, member: dict[str, Any], shown: str
) -> None:
    fake.member(**member)
    client = Client()
    response = discord_sign_in(client)
    assert response.status_code == 302 and response["Location"] == "/"
    player = Player.objects.get(discord_user_id=USER)
    assert player.display_name == shown and player.discord_avatar == "abc123"
    assert signed_in(client) == player.pk
    member_call = next(r for r in fake.seen if "/members/" in r.url.path)
    assert member_call.url.path == f"/api/v10/guilds/{GUILD}/members/{USER}"
    assert member_call.headers["Authorization"] == "Bot bot-token"
    token_call = next(r for r in fake.seen if r.url.path.endswith("/oauth2/token"))
    assert str(token_call.url) == "https://discord.com/api/oauth2/token"
    assert parse_qs(token_call.content.decode())["grant_type"] == ["authorization_code"]
    me_call = next(r for r in fake.seen if r.url.path.endswith("/users/@me"))
    assert me_call.headers["Authorization"] == "Bearer user-token"


def test_sign_in_uses_the_web_key_and_not_djangos_login(fake: Fake) -> None:
    staff = make_player(1)
    Player.objects.filter(pk=staff.pk).update(is_staff=True, is_superuser=True)
    fake.member(staff.discord_user_id)
    fake.user_id = staff.discord_user_id
    client = Client()
    discord_sign_in(client)
    session = client.session
    assert session[SESSION_KEY] == staff.pk
    # Django's own auth key would open /admin without the admin password.
    assert "_auth_user_id" not in session
    response = client.get("/admin/")
    assert response.status_code == 302 and "/admin/login/" in response["Location"]


def test_sign_in_renews_the_session_key_and_updates_name_and_avatar(fake: Fake) -> None:
    existing = Player.objects.from_discord(USER, "Old")
    Player.objects.filter(pk=existing.pk).update(discord_avatar="old")
    fake.member(nick="New", avatar="new456")
    client = Client()
    state = discord_start(client)
    before = client.session.session_key
    client.get("/auth/discord/callback/", {"code": "c", "state": state})
    assert client.session.session_key != before
    existing.refresh_from_db()
    assert (existing.display_name, existing.discord_avatar) == ("New", "new456")


def test_a_default_avatar_clears_the_hash(fake: Fake) -> None:
    existing = Player.objects.from_discord(USER, "Old")
    Player.objects.filter(pk=existing.pk).update(discord_avatar="old")
    fake.member(avatar="")
    discord_sign_in(Client())
    existing.refresh_from_db()
    assert existing.discord_avatar == ""


def test_a_non_member_is_refused_and_not_signed_in(fake: Fake) -> None:
    client = Client()
    response = discord_sign_in(client)
    assert refused(response, "not-member")
    assert signed_in(client) is None
    assert not Player.objects.filter(discord_user_id=USER).exists()


def test_an_inactive_player_is_refused(fake: Fake) -> None:
    player = Player.objects.from_discord(USER, "Banned")
    Player.objects.filter(pk=player.pk).update(is_active=False)
    fake.member(nick="Renamed")
    client = Client()
    assert refused(discord_sign_in(client), "inactive")
    assert signed_in(client) is None
    player.refresh_from_db()
    assert player.display_name == "Banned"


def test_sign_in_refuses_an_inactive_player_directly(fake: Fake, rf: Any) -> None:
    player = make_player(1)
    player.is_active = False
    request = rf.get("/")
    request.session = SessionStore()
    with pytest.raises(ValueError, match="inactive"):
        sign_in(request, player)
    assert SESSION_KEY not in request.session


def test_cancelling_on_discord_is_its_own_refusal(fake: Fake) -> None:
    client = Client()
    state = discord_start(client)
    response = client.get("/auth/discord/callback/", {"error": "access_denied", "state": state})
    assert refused(response, "denied")
    assert signed_in(client) is None


@pytest.mark.parametrize("params", [{"error": "server_error"}, {}], ids=["error", "no-code"])
def test_a_callback_without_a_code_is_refused(fake: Fake, params: dict[str, str]) -> None:
    client = Client()
    state = discord_start(client)
    assert refused(
        client.get("/auth/discord/callback/", {"state": state, **params}), "discord-down"
    )


def test_a_failed_token_exchange_is_refused(fake: Fake) -> None:
    fake.member()
    fake.token_status = 400
    client = Client()
    assert refused(discord_sign_in(client), "discord-down")
    assert signed_in(client) is None
    assert not any("/members/" in r.url.path for r in fake.seen)


@pytest.mark.parametrize("status", [500, 429, 403])
def test_discord_failing_the_member_check_is_not_a_non_member(fake: Fake, status: int) -> None:
    fake.member()
    fake.member_status = status
    client = Client()
    assert refused(discord_sign_in(client), "discord-down")
    assert signed_in(client) is None


def test_discord_unreachable_is_refused(fake: Fake, monkeypatch: pytest.MonkeyPatch) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    monkeypatch.setattr(
        discord_oauth, "_client", lambda: httpx.Client(transport=httpx.MockTransport(down))
    )
    assert refused(discord_sign_in(Client()), "discord-down")


@pytest.mark.parametrize("state", [None, "", "not-the-state"])
def test_a_missing_or_wrong_state_is_refused(fake: Fake, state: str | None) -> None:
    fake.member()
    client = Client()
    discord_start(client)
    params = {"code": "c"} | ({"state": state} if state is not None else {})
    assert refused(client.get("/auth/discord/callback/", params), "state")
    assert signed_in(client) is None
    assert not any("/oauth2/token" in r.url.path for r in fake.seen)


def test_a_callback_without_a_start_is_refused(fake: Fake) -> None:
    fake.member()
    client = Client()
    assert refused(client.get("/auth/discord/callback/", {"code": "c", "state": "x"}), "state")
    assert fake.seen == []


def test_a_state_works_once(fake: Fake) -> None:
    fake.member()
    client = Client()
    state = discord_start(client)
    callback = {"code": "c", "state": state}
    assert client.get("/auth/discord/callback/", callback)["Location"] == "/"
    client.post("/auth/logout/")
    assert refused(client.get("/auth/discord/callback/", callback), "state")
    assert signed_in(client) is None


def test_a_wrong_state_still_spends_the_right_one(fake: Fake) -> None:
    fake.member()
    client = Client()
    state = discord_start(client)
    assert refused(client.get("/auth/discord/callback/", {"code": "c", "state": "x"}), "state")
    assert refused(client.get("/auth/discord/callback/", {"code": "c", "state": state}), "state")


def test_a_state_from_another_browser_is_refused(fake: Fake) -> None:
    fake.member()
    state = discord_start(Client())
    attacker = Client()
    discord_start(attacker)
    assert refused(attacker.get("/auth/discord/callback/", {"code": "c", "state": state}), "state")
    assert signed_in(attacker) is None


@pytest.mark.parametrize(
    ("next_url", "lands"),
    [
        ("/play?tab=queue", "/play?tab=queue"),
        ("https://evil.example/x", "/"),
        ("//evil.example/x", "/"),
        ("/\\evil.example", "/"),
        ("javascript:alert(1)", "/"),
        ("/\tevil", "/"),
    ],
)
def test_sign_in_returns_only_to_this_site(fake: Fake, next_url: str, lands: str) -> None:
    fake.member()
    assert discord_sign_in(Client(), next_url)["Location"] == lands


def test_safe_next_refuses_other_sites() -> None:
    assert safe_next(None) == "/"
    assert safe_next("/match/3") == "/match/3"
    assert safe_next("http://testserver/x") == "/"
    assert safe_next("/" + "a" * 600) == "/"


def test_discord_urls_follow_a_stand_in_api_base(fake: Fake, settings: Any) -> None:
    settings.DISCORD_API_BASE = "http://sim.test:8080/api/v10"
    assert discord_oauth.authorize_endpoint() == "http://sim.test:8080/oauth2/authorize"
    assert discord_oauth.token_endpoint() == "http://sim.test:8080/api/v10/oauth2/token"
    assert discord_oauth.me_endpoint() == "http://sim.test:8080/api/v10/users/@me"
    assert (
        Client()
        .get("/auth/discord/")["Location"]
        .startswith("http://sim.test:8080/oauth2/authorize?")
    )
    assert discord_rest.api_base() == "http://sim.test:8080/api/v10"


# --- Steam OpenID ----------------------------------------------------------------------------


def steam_start(client: Client, intent: str = "login") -> tuple[str, str]:
    """The state and the return_to sent to Steam."""
    response = client.get("/auth/steam/", {"intent": intent})
    assert response.status_code == 302, response.get("Location")
    query = query_of(response["Location"])
    assert response["Location"].startswith(steam_openid.OP_ENDPOINT + "?")
    return query_of(query["openid.return_to"])["state"], query["openid.return_to"]


def nonce_at(moment: Any) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ") + secrets.token_hex(4)


def steam_answer(return_to: str, steam64: int = STEAM64, **changes: str | None) -> dict[str, str]:
    """A positive assertion as Steam sends it. A change of None drops that field."""
    claimed = f"https://steamcommunity.com/openid/id/{steam64}"
    params: dict[str, str | None] = {
        "openid.ns": steam_openid.NS,
        "openid.mode": "id_res",
        "openid.op_endpoint": steam_openid.OP_ENDPOINT,
        "openid.claimed_id": claimed,
        "openid.identity": claimed,
        "openid.return_to": return_to,
        "openid.response_nonce": nonce_at(timezone.now()),
        "openid.assoc_handle": "1234567890",
        "openid.signed": "signed,op_endpoint,claimed_id,identity,return_to,response_nonce,"
        "assoc_handle",
        "openid.sig": "c2lnbmF0dXJl",
    }
    params.update(changes)
    return {key: value for key, value in params.items() if value is not None}


def steam_callback(client: Client, state: str, answer: dict[str, str]) -> Any:
    """Steam sends the player back to return_to with its answer added to the query."""
    return client.get(f"/auth/steam/callback/?{urlencode({'state': state, **answer})}")


def proven_player(number: int = 1) -> Player:
    player = make_player(number)
    steam_service.link_proven(player, ACCOUNT)
    return player


def steam_checks(fake: Fake) -> list[httpx.Request]:
    return [r for r in fake.seen if r.url.host == "steamcommunity.com"]


def test_steam_is_asked_with_our_realm_and_return_to(fake: Fake) -> None:
    response = Client().get("/auth/steam/")
    query = query_of(response["Location"])
    assert query["openid.ns"] == steam_openid.NS
    assert query["openid.mode"] == "checkid_setup"
    assert query["openid.realm"] == "http://testserver"
    assert query["openid.return_to"].startswith("http://testserver/auth/steam/callback/?state=")
    assert query["openid.claimed_id"] == steam_openid.IDENTIFIER_SELECT
    assert query["openid.identity"] == steam_openid.IDENTIFIER_SELECT


@pytest.mark.parametrize("how", ["proven", "verified"])
def test_a_proven_or_verified_account_signs_in_with_steam(fake: Fake, how: str) -> None:
    player = make_player(1)
    if how == "proven":
        steam_service.link_proven(player, ACCOUNT)
    else:
        steam_service.link(player, ACCOUNT)
        steam_service.mark_verified([ACCOUNT])
    fake.member(player.discord_user_id, nick="Rook")
    client = Client()
    state, return_to = steam_start(client)
    before = client.session.session_key
    response = steam_callback(client, state, steam_answer(return_to))
    assert response["Location"] == "/"
    assert signed_in(client) == player.pk
    assert client.session.session_key != before
    (check,) = steam_checks(fake)
    body = parse_qs(check.content.decode())
    assert body["openid.mode"] == ["check_authentication"]
    assert body["openid.sig"] == ["c2lnbmF0dXJl"]
    assert body["openid.claimed_id"] == [f"https://steamcommunity.com/openid/id/{STEAM64}"]
    player.refresh_from_db()
    assert player.display_name == "Rook"


def test_any_of_several_accounts_signs_in(fake: Fake) -> None:
    player = make_player(1)
    steam_service.link(player, 5, "Main")
    steam_service.link_proven(player, ACCOUNT)
    fake.member(player.discord_user_id)
    client = Client()
    state, return_to = steam_start(client)
    assert steam_callback(client, state, steam_answer(return_to))["Location"] == "/"
    assert signed_in(client) == player.pk


def test_steam_sign_in_still_needs_the_server(fake: Fake) -> None:
    proven_player()
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "not-member")
    assert signed_in(client) is None


def test_steam_sign_in_refuses_an_inactive_player(fake: Fake) -> None:
    player = proven_player()
    Player.objects.filter(pk=player.pk).update(is_active=False)
    fake.member(player.discord_user_id)
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "inactive")
    assert signed_in(client) is None


def test_steam_sign_in_with_discord_down(fake: Fake) -> None:
    player = proven_player()
    fake.member(player.discord_user_id)
    fake.member_status = 502
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "discord-down")
    assert signed_in(client) is None


@pytest.mark.parametrize("linked", [False, True], ids=["unknown", "only-claimed"])
def test_an_unknown_or_unproven_account_cannot_sign_in(fake: Fake, linked: bool) -> None:
    player = make_player(1)
    fake.member(player.discord_user_id)
    if linked:
        steam_service.link(player, ACCOUNT)  # Only claimed, through /link.
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "steam-unproven")
    assert signed_in(client) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"openid.ns": "http://specs.openid.net/auth/1.1"},
        {"openid.ns": None},
        {"openid.mode": "check_authentication"},
        {"openid.mode": None},
        {"openid.op_endpoint": "https://evil.example/openid/login"},
        {"openid.op_endpoint": None},
        {"openid.return_to": "http://testserver/auth/steam/callback/?state=other"},
        {"openid.return_to": None},
        {"openid.identity": "https://steamcommunity.com/openid/id/76561198000000001"},
        {"openid.identity": None},
        {
            "openid.claimed_id": "https://evil.example/openid/id/76561198060265732",
            "openid.identity": "https://evil.example/openid/id/76561198060265732",
        },
        {
            "openid.claimed_id": "http://steamcommunity.com/openid/id/76561198060265732",
            "openid.identity": "http://steamcommunity.com/openid/id/76561198060265732",
        },
        *(
            {"openid.signed": ",".join(f for f in steam_openid.SIGNED_FIELDS if f != missing)}
            for missing in steam_openid.SIGNED_FIELDS
        ),
        {"openid.signed": None},
        {"openid.sig": None},
        {"openid.assoc_handle": None},
        {"openid.response_nonce": "not-a-time"},
        {"openid.response_nonce": None},
        {"openid.response_nonce": nonce_at(timezone.now() - timedelta(hours=1))},
        {"openid.response_nonce": nonce_at(timezone.now() + timedelta(hours=1))},
    ],
    ids=[
        "ns-wrong",
        "ns-missing",
        "mode-wrong",
        "mode-missing",
        "op_endpoint-wrong",
        "op_endpoint-missing",
        "return_to-wrong",
        "return_to-missing",
        "identity-differs",
        "identity-missing",
        "claimed-not-steam",
        "claimed-not-https",
        *(f"unsigned-{name}" for name in steam_openid.SIGNED_FIELDS),
        "signed-missing",
        "sig-missing",
        "assoc_handle-missing",
        "nonce-format",
        "nonce-missing",
        "nonce-stale",
        "nonce-future",
    ],
)
def test_a_bad_steam_answer_is_refused_before_asking_steam(
    fake: Fake, changes: dict[str, Any]
) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to, **changes)), "state")
    assert signed_in(client) is None
    assert steam_checks(fake) == []


def test_a_non_individual_steam_id_is_refused(fake: Fake) -> None:
    client = Client()
    state, return_to = steam_start(client)
    # A SteamID64 below the individual-account base has no account ID.
    answer = steam_answer(return_to, steam64=10000000000000000)
    assert refused(steam_callback(client, state, answer), "state")


def test_steam_must_confirm_the_signature(fake: Fake) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    fake.steam_valid = False
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "state")
    assert signed_in(client) is None
    assert len(steam_checks(fake)) == 1


def test_steam_unreachable_is_its_own_refusal(fake: Fake) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    fake.steam_down = True
    client = Client()
    state, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "steam-down")
    assert signed_in(client) is None


def test_a_replayed_steam_answer_is_refused(fake: Fake) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    client = Client()
    state, return_to = steam_start(client)
    answer = steam_answer(return_to)
    assert steam_callback(client, state, answer)["Location"] == "/"
    client.post("/auth/logout/")
    # Even inside a fresh sign-in with a matching state and return_to, the nonce is spent.
    state, return_to = steam_start(client)
    answer["openid.return_to"] = return_to
    assert refused(steam_callback(client, state, answer), "state")
    assert signed_in(client) is None
    assert len(steam_checks(fake)) == 1


def test_a_replay_in_another_browser_is_refused(fake: Fake) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    victim, attacker = Client(), Client()
    state, return_to = steam_start(victim)
    answer = steam_answer(return_to)
    assert steam_callback(victim, state, answer)["Location"] == "/"
    # The attacker's own state and return_to, with the victim's spent nonce and signature.
    state, return_to = steam_start(attacker)
    answer["openid.return_to"] = return_to
    assert refused(steam_callback(attacker, state, answer), "state")
    assert signed_in(attacker) is None


def test_cancelling_on_steam_is_its_own_refusal(fake: Fake) -> None:
    client = Client()
    state, _ = steam_start(client)
    answer = {"openid.ns": steam_openid.NS, "openid.mode": "cancel"}
    assert refused(steam_callback(client, state, answer), "denied")


@pytest.mark.parametrize("state", ["forged", ""])
def test_a_wrong_steam_state_is_refused(fake: Fake, state: str) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    client = Client()
    _, return_to = steam_start(client)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "state")
    assert steam_checks(fake) == []


def test_a_steam_state_from_another_browser_is_refused(fake: Fake) -> None:
    proven = proven_player()
    fake.member(proven.discord_user_id)
    state, return_to = steam_start(Client())
    attacker = Client()
    steam_start(attacker)
    assert refused(steam_callback(attacker, state, steam_answer(return_to)), "state")
    assert signed_in(attacker) is None


def test_steam_ids_convert_to_accounts() -> None:
    assert steam_ids.account_from_steam64(STEAM64) == ACCOUNT


# --- Link Steam ------------------------------------------------------------------------------


def test_linking_steam_needs_a_signed_in_player(fake: Fake) -> None:
    assert refused(Client().get("/auth/steam/", {"intent": "link"}), "signed-out")


def test_linking_steam_proves_a_new_account(fake: Fake, published: list[str]) -> None:
    player = make_player(1)
    client = Client()
    sign_in_as(client, player)
    state, return_to = steam_start(client, "link")
    assert steam_callback(client, state, steam_answer(return_to))["Location"] == "/"
    account = SteamAccount.objects.get(account_id=ACCOUNT)
    assert account.player_id == player.pk and account.proven_at is not None
    assert live.player_topic(player.pk) in published
    assert signed_in(client) == player.pk


def test_a_signed_out_link_callback_is_refused(fake: Fake) -> None:
    player = make_player(1)
    client = Client()
    sign_in_as(client, player)
    state, return_to = steam_start(client, "link")
    session = client.session
    del session[SESSION_KEY]
    session.save()
    assert refused(steam_callback(client, state, steam_answer(return_to)), "signed-out")
    assert not SteamAccount.objects.exists()


def test_a_link_finished_by_another_player_is_refused(fake: Fake) -> None:
    first, second = make_player(1), make_player(2)
    client = Client()
    sign_in_as(client, first)
    state, return_to = steam_start(client, "link")
    sign_in_as(client, second)
    assert refused(steam_callback(client, state, steam_answer(return_to)), "state")
    assert not SteamAccount.objects.exists()


def test_proving_steam_takes_over_an_unproven_claim(
    fake: Fake, settings: Any, published: list[str]
) -> None:
    settings.STEAM_WEB_API_KEY = "key"
    claimant, owner = make_player(1), make_player(2)
    steam_service.link(claimant, ACCOUNT, "Claimed")
    published.clear()
    client = Client()
    sign_in_as(client, owner)
    state, return_to = steam_start(client, "link")
    response = steam_callback(client, state, steam_answer(return_to))
    assert response["Location"] == "/"
    account = SteamAccount.objects.get(account_id=ACCOUNT)
    assert account.player_id == owner.pk and account.proven_at is not None
    assert account.steam_name == "SteamName"
    assert not claimant.steam_accounts.exists()
    assert set(published) == {live.player_topic(owner.pk), live.player_topic(claimant.pk)}
    summaries = next(r for r in fake.seen if r.url.host == "api.steampowered.com")
    assert summaries.url.params["steamids"] == str(STEAM64)


@pytest.mark.parametrize("how", ["proven", "verified"])
def test_proving_steam_never_takes_a_proven_or_verified_account(fake: Fake, how: str) -> None:
    holder, other = make_player(1), make_player(2)
    if how == "proven":
        steam_service.link_proven(holder, ACCOUNT)
    else:
        steam_service.link(holder, ACCOUNT)
        steam_service.mark_verified([ACCOUNT])
    client = Client()
    sign_in_as(client, other)
    state, return_to = steam_start(client, "link")
    assert refused(steam_callback(client, state, steam_answer(return_to)), "steam-taken")
    assert SteamAccount.objects.get(account_id=ACCOUNT).player_id == holder.pk
    assert not other.steam_accounts.exists()


def test_a_failed_steam_name_lookup_still_links(
    fake: Fake, settings: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings.STEAM_WEB_API_KEY = "key"
    player = make_player(1)
    steam_service.link(player, ACCOUNT, "Kept")

    def broken() -> httpx.Client:
        def handle(request: httpx.Request) -> httpx.Response:
            if request.url.host == "api.steampowered.com":
                raise httpx.ConnectTimeout("slow", request=request)
            return fake.handle(request)

        return httpx.Client(transport=httpx.MockTransport(handle))

    monkeypatch.setattr(steam_openid, "_client", broken)
    client = Client()
    sign_in_as(client, player)
    state, return_to = steam_start(client, "link")
    assert steam_callback(client, state, steam_answer(return_to))["Location"] == "/"
    account = SteamAccount.objects.get(account_id=ACCOUNT)
    assert account.proven_at is not None and account.steam_name == "Kept"


# --- The Steam service: plain link vs proof --------------------------------------------------


def test_a_plain_link_never_takes_anyones_account(league: Any) -> None:
    holder, other = make_player(1), make_player(2)
    steam_service.link(holder, ACCOUNT, "Mine")
    with pytest.raises(InvalidAction, match="already linked"):
        steam_service.link(other, ACCOUNT)
    steam_service.link_proven(holder, 7)
    with pytest.raises(InvalidAction, match="already linked"):
        steam_service.link(other, 7)
    assert set(holder.steam_accounts.values_list("account_id", flat=True)) == {ACCOUNT, 7}


def test_proof_takes_only_an_unproven_unverified_claim(league: Any, published: list[str]) -> None:
    claimant, owner = make_player(1), make_player(2)
    steam_service.link(claimant, ACCOUNT, "Claimed")
    published.clear()
    account = steam_service.link_proven(owner, ACCOUNT)
    assert account.player_id == owner.pk
    assert account.steam_name == "Claimed"  # No name from Steam: the old one stays.
    assert steam_service.is_proven_or_verified(account)
    assert set(published) == {live.player_topic(owner.pk), live.player_topic(claimant.pk)}
    with pytest.raises(InvalidAction, match="already proven or verified"):
        steam_service.link_proven(claimant, ACCOUNT)
    assert SteamAccount.objects.get(account_id=ACCOUNT).player_id == owner.pk


def test_proof_refuses_an_account_verified_elsewhere(league: Any) -> None:
    holder, other = make_player(1), make_player(2)
    steam_service.link(holder, ACCOUNT)
    steam_service.mark_verified([ACCOUNT])
    with pytest.raises(InvalidAction, match="Ask staff"):
        steam_service.link_proven(other, ACCOUNT)
    account = SteamAccount.objects.get(account_id=ACCOUNT)
    assert account.player_id == holder.pk and account.proven_at is None


def test_proving_your_own_claim_keeps_it_verified(league: Any) -> None:
    player = make_player(1)
    steam_service.link(player, ACCOUNT, "Main")
    steam_service.mark_verified([ACCOUNT])
    account = steam_service.link_proven(player, ACCOUNT, "Renamed")
    assert account.verified_at is not None and account.proven_at is not None
    assert account.steam_name == "Renamed"
    assert SteamAccount.objects.count() == 1


def test_is_proven_or_verified(league: Any) -> None:
    player = make_player(1)
    account = steam_service.link(player, ACCOUNT)
    assert not steam_service.is_proven_or_verified(account)
    steam_service.mark_verified([ACCOUNT])
    account.refresh_from_db()
    assert steam_service.is_proven_or_verified(account)


def test_every_steam_change_tells_the_player(league: Any, published: list[str]) -> None:
    player = make_player(1)
    topic = live.player_topic(player.pk)
    steam_service.link(player, ACCOUNT)
    assert published == [topic]
    steam_service.link(player, ACCOUNT)  # Nothing changed.
    assert published == [topic]
    steam_service.link(player, ACCOUNT, "Named")
    steam_service.mark_verified([ACCOUNT])
    steam_service.mark_verified([ACCOUNT])  # Already verified.
    steam_service.unlink(player, ACCOUNT)
    steam_service.unlink(player)  # Nothing left.
    assert published == [topic] * 4


# --- Session and sign-out --------------------------------------------------------------------


def test_the_session_says_who_is_signed_in(fake: Fake) -> None:
    client = Client()
    response = client.get(SESSION_URL)
    assert response["Cache-Control"] == "no-store"
    assert "csrftoken" in response.cookies
    assert response.json() == {
        "signed_in": False,
        "player": None,
        "dev_login": False,
        "invite_url": None,
    }

    player = make_player(1)
    steam_service.link(player, ACCOUNT, "Vexa")
    steam_service.mark_verified([ACCOUNT])
    steam_service.link_proven(player, 55, "Smurf")
    Player.objects.filter(pk=player.pk).update(discord_avatar="abc123")
    sign_in_as(client, player)
    avatar = f"/avatar/{player.pk}/abc123.png?size=128"
    assert client.get(SESSION_URL).json() == {
        "signed_in": True,
        "player": {
            "id": str(player.pk),
            "name": "P1",
            "avatar": avatar,
            "steam": [
                {"name": "Vexa", "proven": False, "verified": True},
                {"name": "Smurf", "proven": True, "verified": False},
            ],
        },
        "dev_login": False,
        "invite_url": None,
    }


def test_the_session_never_shows_a_discord_or_steam_id(fake: Fake) -> None:
    player = make_player(1)
    steam_service.link(player, ACCOUNT, "")
    client = Client()
    sign_in_as(client, player)
    text = client.get(SESSION_URL).content.decode()
    body = json.loads(text)
    for secret in (player.discord_user_id, ACCOUNT, steam_ids.steam64_from_account(ACCOUNT)):
        assert str(secret) not in text
    assert set(body["player"]) == {"id", "name", "avatar", "steam"}
    assert set(body["player"]["steam"][0]) == {"name", "proven", "verified"}


def test_the_session_carries_the_servers_invite(fake: Fake, settings: Any) -> None:
    settings.DISCORD_INVITE_URL = "https://discord.gg/inhouse"
    assert Client().get(SESSION_URL).json()["invite_url"] == "https://discord.gg/inhouse"


def test_a_session_without_an_avatar_or_steam(fake: Fake) -> None:
    client = Client()
    sign_in_as(client, make_player(1))
    body = client.get(SESSION_URL).json()["player"]
    assert body["avatar"] is None
    assert body["steam"] == []


def test_a_player_switched_off_is_signed_out(fake: Fake) -> None:
    client = Client()
    player = make_player(1)
    sign_in_as(client, player)
    Player.objects.filter(pk=player.pk).update(is_active=False)
    assert client.get(SESSION_URL).json()["signed_in"] is False


def test_a_planted_session_value_is_nobody(fake: Fake) -> None:
    client = Client()
    make_player(1)
    for value in ("1", True, None, [1]):
        session = client.session
        session[SESSION_KEY] = value
        session.save()
        assert client.get(SESSION_URL).json()["signed_in"] is False


def test_signing_out_keeps_a_staff_admin_session(fake: Fake, published: list[str]) -> None:
    admin = Player.objects.create_superuser(
        "staff", "staff@example.com", "pw", discord_user_id=42_000_000
    )
    client = Client()
    client.force_login(admin)
    player = make_player(1)
    sign_in_as(client, player)
    assert client.get("/admin/").status_code == 200

    response = client.post("/auth/logout/")
    assert response.status_code == 204
    assert signed_in(client) is None
    assert client.get(SESSION_URL).json()["signed_in"] is False
    assert client.get("/admin/").status_code == 200
    assert published == [live.player_topic(player.pk)]


def test_signing_out_saves_the_session_before_telling_sockets(
    fake: Fake, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = Client()
    player = make_player(1)
    sign_in_as(client, player)
    key = client.session.session_key
    seen: list[Any] = []

    def check(*topics: str) -> None:
        # What the web process reads when the notification arrives.
        seen.append(SessionStore(key).get(SESSION_KEY))

    monkeypatch.setattr(live, "publish", check)
    client.post("/auth/logout/")
    assert seen == [None]


def test_signing_out_when_signed_out_tells_nobody(fake: Fake, published: list[str]) -> None:
    assert Client().post("/auth/logout/").status_code == 204
    assert published == []


def test_a_form_sign_out_goes_home(fake: Fake) -> None:
    client = Client()
    sign_in_as(client, make_player(1))
    response = client.post("/auth/logout/", headers={"Accept": "text/html"})
    assert response.status_code == 302 and response["Location"] == "/"


def test_sign_out_needs_a_csrf_token(fake: Fake) -> None:
    client = Client(enforce_csrf_checks=True)
    sign_in_as(client, make_player(1))
    assert client.post("/auth/logout/").status_code == 403
    assert signed_in(client) is not None
    assert client.get("/auth/logout/").status_code == 405


def test_sign_out_with_the_sessions_csrf_cookie(fake: Fake) -> None:
    client = Client(enforce_csrf_checks=True)
    sign_in_as(client, make_player(1))
    token = client.get(SESSION_URL).cookies["csrftoken"].value
    assert client.post("/auth/logout/", headers={"X-CSRFToken": token}).status_code == 204
    assert signed_in(client) is None


@pytest.mark.django_db(transaction=True)
def test_the_websocket_reads_the_player_from_the_session() -> None:
    player, inactive = make_player(1), make_player(2)
    Player.objects.filter(pk=inactive.pk).update(is_active=False)
    sessions = []
    for who in (player, inactive):
        session = SessionStore()
        session[SESSION_KEY] = who.pk
        session.save()
        sessions.append(session.session_key)

    async def read() -> list[Player | None]:
        found = [await player_of_session(SessionStore(key)) for key in sessions]
        found.append(await player_of_session(SessionStore()))
        await db(connections.close_all)
        return found

    found, switched_off, missing = asyncio.run(read())
    assert found is not None and found.pk == player.pk
    assert switched_off is None and missing is None


# --- Dev login -------------------------------------------------------------------------------


@pytest.mark.parametrize(("dev_login", "debug"), [(False, True), (True, False), (False, False)])
def test_dev_login_is_not_there_when_off(
    fake: Fake, settings: Any, dev_login: bool, debug: bool
) -> None:
    settings.WEB_DEV_LOGIN, settings.DEBUG = dev_login, debug
    client = Client()
    assert client.get("/auth/dev/").status_code == 404
    assert client.post("/auth/dev/", {"name": "Someone"}).status_code == 404
    assert not Player.objects.filter(display_name="Someone").exists()
    assert client.get(SESSION_URL).json()["dev_login"] is False


def test_dev_login_signs_in_as_anyone(fake: Fake, settings: Any) -> None:
    settings.WEB_DEV_LOGIN, settings.DEBUG = True, True
    existing = make_player(1)
    client = Client()
    page = client.get("/auth/dev/")
    assert page.status_code == 200 and b"P1" in page.content
    assert str(existing.discord_user_id).encode() not in page.content
    assert client.get(SESSION_URL).json()["dev_login"] is True

    assert client.post("/auth/dev/", {"player": existing.pk})["Location"] == "/"
    assert signed_in(client) == existing.pk

    other = Client()
    response = other.post("/auth/dev/", {"name": "Stand In", "next": "/play"})
    assert response["Location"] == "/play"
    stand_in = Player.objects.get(display_name="Stand In")
    assert 0 < stand_in.discord_user_id < 1000
    assert signed_in(other) == stand_in.pk
    Client().post("/auth/dev/", {"name": "Stand In"})
    assert Player.objects.filter(display_name="Stand In").count() == 1
    Client().post("/auth/dev/", {"name": "Second"})
    assert Player.objects.get(display_name="Second").discord_user_id != stand_in.discord_user_id

    assert client.post("/auth/dev/", {"player": 999999}).status_code == 400
    assert client.post("/auth/dev/", {}).status_code == 400
    assert Client().post("/auth/dev/", {"name": "X", "next": "//evil.example"})["Location"] == "/"


def test_dev_login_refuses_an_inactive_player(fake: Fake, settings: Any) -> None:
    settings.WEB_DEV_LOGIN, settings.DEBUG = True, True
    player = make_player(1)
    Player.objects.filter(pk=player.pk).update(is_active=False)
    client = Client()
    assert client.post("/auth/dev/", {"player": player.pk}).status_code == 400
    assert signed_in(client) is None


def test_dev_login_needs_a_csrf_token(fake: Fake, settings: Any) -> None:
    settings.WEB_DEV_LOGIN, settings.DEBUG = True, True
    player = make_player(1)
    client = Client(enforce_csrf_checks=True)
    assert client.post("/auth/dev/", {"player": player.pk}).status_code == 403
    assert signed_in(client) is None


# --- Discord REST ----------------------------------------------------------------------------


def test_get_member_reads_the_member(fake: Fake) -> None:
    fake.member(nick="Nick", global_name="Global", username="user")
    member = discord_rest.get_member(GUILD, USER)
    assert member == discord_rest.Member(USER, "user", "Global", "Nick", "abc123", (11, 22))
    assert member.display_name == "Nick"
    assert discord_rest.get_member(GUILD, 1) is None


def test_an_unknown_server_is_an_error_not_a_non_member(fake: Fake) -> None:
    with pytest.raises(discord_rest.DiscordRestError) as error:
        discord_rest.get_member(1, USER)
    assert error.value.status == 404


def test_a_different_member_in_the_answer_is_an_error(fake: Fake) -> None:
    fake.member()
    fake.members[555] = fake.members[USER]
    with pytest.raises(discord_rest.DiscordRestError, match="different member"):
        discord_rest.get_member(GUILD, 555)


def test_discord_rest_follows_the_api_base(settings: Any) -> None:
    settings.DISCORD_API_BASE = "http://sim.test:8080/api/v10"
    with discord_rest._client() as client:
        assert str(client.base_url) == "http://sim.test:8080/api/v10/"


def test_post_file_waits_out_one_short_rate_limit(fake: Fake) -> None:
    fake.rate_limits = 1
    message = discord_rest.post_file(5, b"png-bytes", "shot.png", "Report")
    assert message["attachments"][0]["url"] == "https://x"
    upload = fake.seen[-1]
    assert upload.headers["Authorization"] == "Bot bot-token"
    assert b'filename="shot.png"' in upload.content and b"png-bytes" in upload.content


def test_post_file_gives_up_on_a_second_rate_limit(fake: Fake) -> None:
    fake.rate_limits = 2
    with pytest.raises(discord_rest.DiscordRestError, match="rate limited") as error:
        discord_rest.post_file(5, b"x", "shot.png")
    assert error.value.status == 429


def test_refuse_knows_every_code() -> None:
    with pytest.raises(ValueError, match="unknown"):
        errors.refuse("nope", "test")
    assert errors.refuse(errors.STATE, "test")["Location"] == "/signin?error=state"
