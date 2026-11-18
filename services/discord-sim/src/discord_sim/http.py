"""HTTP plumbing: Discord-exact JSON responses, request bodies, and the two middlewares.

discord.py only parses a body as JSON when Content-Type is exactly `application/json`, so every
response here sets it by hand (aiohttp's json_response would add `; charset=utf-8`).
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import urlsplit

from aiohttp import BodyPartReader, web

from discord_sim import errors
from discord_sim.context import sim_of
from discord_sim.errors import ControlError, DiscordError
from discord_sim.message_body import UploadedFile

Handler = Callable[[web.Request], Awaitable[web.StreamResponse]]

BODY_KEY: web.RequestKey[tuple[Any, list[UploadedFile]]] = web.RequestKey("sim_body", tuple)
API_PREFIX = "/api/v10/"
NO_AUTH = (f"{API_PREFIX}interactions/", f"{API_PREFIX}webhooks/", f"{API_PREFIX}gateway")
LOGGED_BODY_LIMIT = 16_000
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1"})

_FILE_FIELD = re.compile(r"files\[(\d+)\]")


def json_response(
    data: Any, status: int = 200, headers: dict[str, str] | None = None
) -> web.Response:
    return web.Response(
        body=json.dumps(data, separators=(",", ":")).encode(),
        status=status,
        headers={"Content-Type": "application/json", **(headers or {})},
    )


def no_content() -> web.Response:
    return web.Response(status=204)


async def read_body(request: web.Request) -> tuple[Any, list[UploadedFile]]:
    """The JSON body, or `payload_json` plus `files[N]` from multipart. Cached on the request."""
    if BODY_KEY in request:
        return request[BODY_KEY]
    files: list[UploadedFile] = []
    data: Any = {}
    if request.content_type == "multipart/form-data":
        reader = await request.multipart()
        while (part := await reader.next()) is not None:
            if not isinstance(part, BodyPartReader):
                continue
            raw = await part.read()
            match = _FILE_FIELD.fullmatch(part.name or "")
            if part.name == "payload_json":
                data = _loads(raw)
            elif match:
                files.append(
                    UploadedFile(
                        index=int(match.group(1)),
                        filename=part.filename or f"file{match.group(1)}",
                        content_type=part.headers.get("Content-Type"),
                        data=bytes(raw),
                    )
                )
    else:
        raw = await request.read()
        data = _loads(raw) if raw.strip() else {}
    request[BODY_KEY] = (data, files)
    return data, files


async def read_json_object(request: web.Request) -> dict[str, Any]:
    data, _files = await read_body(request)
    if not isinstance(data, dict):
        raise errors.invalid_form({"_": ("DICT_TYPE_CONVERT", "Only dictionaries may be used.")})
    return data


def _loads(raw: bytes | bytearray) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        raise errors.invalid_json() from None


def snowflake_param(request: web.Request, name: str) -> int:
    value = request.match_info[name]
    if not value.isdigit():
        raise errors.invalid_form(
            {name: ("NUMBER_TYPE_COERCE", f"Value {value!r} is not snowflake.")}
        )
    return int(value)


@web.middleware
async def api_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """Discord REST behaviour: auth, injected faults, error JSON, rate-limit headers, the log."""
    if not request.path.startswith(API_PREFIX):
        return await handler(request)
    sim = sim_of(request)
    started = time.monotonic()
    fault = sim.faults.match(request.method, request.path)
    response: web.StreamResponse
    error: dict[str, Any] | None = None
    try:
        if fault is not None:
            raise DiscordError(fault.status, fault.code, fault.message)
        if not request.path.startswith(NO_AUTH):
            header = request.headers.get("Authorization", "")
            if not header.startswith("Bot ") or not sim.config.token_ok(header[4:]):
                raise errors.unauthorized()
        response = await handler(request)
    except DiscordError as exc:
        error = fault.body() if fault is not None else exc.body()
        headers = {}
        if exc.status == 429:
            retry = fault.retry_after if fault else 1.0
            headers = {"Via": "1.1 google", "Retry-After": str(retry), "X-RateLimit-Scope": "user"}
        response = json_response(error, exc.status, headers)
    except web.HTTPMethodNotAllowed:
        error = {"message": "405: Method Not Allowed", "code": 0}
        response = json_response(error, 405)
    except web.HTTPNotFound:
        error = errors.not_found_route().body()
        response = json_response(error, 404)
    _rate_limit_headers(request, response)
    sim.log.add(
        "rest",
        method=request.method,
        path=request.path,
        query=dict(request.query),
        status=response.status,
        body=_logged_body(request),
        error=error,
        ms=round((time.monotonic() - started) * 1000, 1),
    )
    return response


@web.middleware
async def control_middleware(request: web.Request, handler: Handler) -> web.StreamResponse:
    """CORS for the control panel, and ControlError as `{"error": ...}` JSON."""
    if not request.path.startswith(("/_sim", "/attachments")):
        return await handler(request)
    sim = sim_of(request)
    response: web.StreamResponse
    if not same_site(request):
        response = json_response(
            {"error": "Only this machine's pages may change the simulator.", "reason": "origin"},
            403,
        )
    elif request.method == "OPTIONS" and cors_headers(request):
        response = web.Response(status=204)
        response.headers["Access-Control-Allow-Methods"] = "GET, POST, PATCH, PUT, DELETE, OPTIONS"
        response.headers["Access-Control-Allow-Headers"] = request.headers.get(
            "Access-Control-Request-Headers", "Content-Type"
        )
        response.headers["Access-Control-Max-Age"] = "600"
    else:
        try:
            response = await handler(request)
        except ControlError as exc:
            response = json_response({"error": exc.error, **exc.details}, exc.status)
        except DiscordError as exc:
            response = json_response({"error": exc.message, "code": exc.code}, exc.status)
        except web.HTTPException as exc:
            response = json_response({"error": exc.reason}, exc.status)
        if request.path.startswith("/_sim") and request.method != "GET":
            sim.log.add(
                "control",
                method=request.method,
                path=request.path,
                status=response.status,
                body=_logged_body(request),
            )
    if not response.prepared:
        response.headers.update(cors_headers(request))
    return response


def same_site(request: web.Request) -> bool:
    """Whether a state-changing call may come from where it says it came from.

    A plain-text or multipart POST is a "simple" request: a browser sends it cross-origin with no
    preflight, so without this any web page the developer visits could drive the simulator.
    Browsers send `Origin` with every non-GET request: allowed CORS origins, loopback pages and
    pages on the host being called get through. Clients that send no Origin (the bot, the web
    container, tests, curl) aren't browsers and pass."""
    if request.method in SAFE_METHODS:
        return True
    origin = request.headers.get("Origin")
    if origin is None:
        return True
    origins = sim_of(request).config.cors_origins
    if "*" in origins or origin in origins:
        return True
    hostname = urlsplit(origin).hostname  # None for the opaque origin "null".
    if hostname is None:
        return False
    return hostname in LOOPBACK or hostname == urlsplit(f"//{request.host}").hostname


def cors_headers(request: web.Request) -> dict[str, str]:
    """CORS headers for an allowed Origin. Streaming handlers set them before they prepare."""
    origin = request.headers.get("Origin")
    origins = sim_of(request).config.cors_origins
    if origin is None or ("*" not in origins and origin not in origins):
        return {}
    return {"Access-Control-Allow-Origin": origin, "Vary": "Origin"}


def _rate_limit_headers(request: web.Request, response: web.StreamResponse) -> None:
    """Never at zero, so the client never waits. A 429 fault carries its own Retry-After."""
    resource = request.match_info.route.resource
    route = resource.canonical if resource is not None else request.path
    bucket = hashlib.sha1(f"{request.method} {route}".encode()).hexdigest()[:16]
    reset_after = 1.0
    response.headers.update(
        {
            "X-RateLimit-Limit": "50",
            "X-RateLimit-Remaining": "49",
            "X-RateLimit-Reset": f"{time.time() + reset_after:.3f}",
            "X-RateLimit-Reset-After": f"{reset_after:.3f}",
            "X-RateLimit-Bucket": bucket,
        }
    )


def _logged_body(request: web.Request) -> Any:
    cached = request.get(BODY_KEY)
    if cached is None:
        return None
    data, files = cached
    text = json.dumps(data)
    logged: Any = data if len(text) <= LOGGED_BODY_LIMIT else f"<{len(text)} bytes of JSON>"
    if files:
        return {
            "json": logged,
            "files": [{"filename": f.filename, "size": len(f.data)} for f in files],
        }
    return logged
