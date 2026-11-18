"""REST v10 at the HTTP level: headers, auth, error JSON and codes, multipart, faults."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from discord_sim import snowflake
from discord_sim.interactions import PLACEHOLDER_PNG

from .support import TOKEN, RunningSim

AUTH = {"Authorization": f"Bot {TOKEN}"}


async def api(
    running: RunningSim,
    method: str,
    path: str,
    *,
    auth: bool = True,
    headers: dict[str, str] | None = None,
    **kwargs: Any,
) -> tuple[int, Any, aiohttp.ClientResponse]:
    sent = (AUTH if auth else {}) | (headers or {})
    async with running.http.request(
        method, f"{running.url}/api/v10{path}", headers=sent, **kwargs
    ) as response:
        body = await response.json(content_type=None) if response.status != 204 else None
        return response.status, body, response


async def test_json_content_type_has_no_charset(running: RunningSim) -> None:
    status, body, response = await api(running, "GET", "/users/@me")
    assert status == 200 and body["id"] == str(snowflake.BOT_USER_ID)
    assert response.headers["Content-Type"] == "application/json"
    assert float(response.headers["X-RateLimit-Reset-After"]) > 0
    assert int(response.headers["X-RateLimit-Remaining"]) > 0


async def test_bad_token_is_401(running: RunningSim) -> None:
    status, body, response = await api(running, "GET", "/users/@me", auth=False)
    assert (status, body["code"]) == (401, 0)
    assert response.headers["Content-Type"] == "application/json"


@pytest.mark.parametrize(
    ("method", "path", "status", "code"),
    [
        ("GET", "/channels/123", 404, 10003),
        ("GET", f"/channels/{snowflake.GENERAL_TEXT_ID}/messages/123", 404, 10008),
        ("DELETE", f"/channels/{snowflake.GENERAL_TEXT_ID}/permissions/123", 404, 10009),
        ("GET", "/guilds/123", 404, 10004),
        ("GET", f"/guilds/{snowflake.GUILD_ID}/members/123", 404, 10007),
        ("GET", "/no/such/route", 404, 0),
    ],
)
async def test_errors_carry_discord_codes(
    running: RunningSim, method: str, path: str, status: int, code: int
) -> None:
    got, body, _ = await api(running, method, path)
    assert (got, body["code"]) == (status, code)


async def test_interaction_routes_need_no_auth(running: RunningSim) -> None:
    status, body, _ = await api(
        running, "POST", "/interactions/123/token/callback", auth=False, json={"type": 6}
    )
    assert (status, body["code"]) == (404, 10062)
    status, body, _ = await api(
        running, "POST", f"/webhooks/{snowflake.BOT_USER_ID}/nope", auth=False, json={}
    )
    assert (status, body["code"]) == (404, 10015)


async def test_invalid_json_is_50109(running: RunningSim) -> None:
    status, body, _ = await api(
        running,
        "POST",
        f"/channels/{snowflake.GENERAL_TEXT_ID}/messages",
        data=b"{nope",
        headers={"Content-Type": "application/json"},
    )
    assert (status, body["code"]) == (400, 50109)


async def test_multipart_upload_is_served(running: RunningSim) -> None:
    form = aiohttp.FormData()
    form.add_field(
        "payload_json",
        '{"content": "board", "attachments": [{"id": 0, "filename": "shot.png"}]}',
        content_type="application/json",
    )
    form.add_field("files[0]", PLACEHOLDER_PNG, filename="shot.png")
    status, body, _ = await api(
        running, "POST", f"/channels/{snowflake.GENERAL_TEXT_ID}/messages", data=form
    )
    assert status == 200
    url = body["attachments"][0]["url"]
    async with running.http.get(url) as response:
        assert response.status == 200
        assert response.content_type == "image/png"
        assert await response.read() == PLACEHOLDER_PNG


async def test_429_fault_has_via_and_retry_after(running: RunningSim) -> None:
    await running.call(
        "POST",
        "/_sim/faults",
        {"path": "/messages$", "method": "POST", "status": 429, "retry_after": 0.25},
        status=201,
    )
    path = f"/channels/{snowflake.GENERAL_TEXT_ID}/messages"
    status, body, response = await api(running, "POST", path, json={"content": "hi"})
    assert status == 429 and body["retry_after"] == 0.25 and body["global"] is False
    assert response.headers["Via"]
    status, _, _ = await api(running, "POST", path, json={"content": "hi"})
    assert status == 200  # A fault hits once unless `times` says otherwise.


async def test_gateway_bot_points_at_the_sim(running: RunningSim) -> None:
    status, body, _ = await api(running, "GET", "/gateway/bot")
    assert status == 200 and body["url"] == running.url.replace("http", "ws") + "/gateway"
    assert body["session_start_limit"]["remaining"] > 0


async def test_commands_sync_echoes_with_ids(running: RunningSim) -> None:
    path = f"/applications/{snowflake.BOT_USER_ID}/guilds/{snowflake.GUILD_ID}/commands"
    status, body, _ = await api(
        running, "PUT", path, json=[{"name": "setup", "description": "Set up", "type": 1}]
    )
    assert status == 200
    assert body[0]["application_id"] == str(snowflake.BOT_USER_ID)
    assert body[0]["guild_id"] == str(snowflake.GUILD_ID) and body[0]["id"]
    status, _, _ = await api(running, "PUT", "/applications/1/commands", json=[])
    assert status == 403
