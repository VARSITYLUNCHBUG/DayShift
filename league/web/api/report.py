"""`POST /api/matches/{id}/report/`: a captain's result, with an optional scoreboard screenshot.

The same steps as Discord's report form (`bot/handlers/results.py`): the checks, then any
screenshot is copied to the archive channel (Discord's CDN links expire, message IDs don't), then
`results.submit_report` records it. The multipart form takes what that one does: `winner` ("A" or
"B"), `deadlock_match_id` (required), and optionally `screenshot`, `mvp` and up to two `keys`
player IDs.

It's async so the upload to Discord, which can take seconds for a 20 MB file, waits on a thread
of its own rather than on the one thread every other view and `db()` call shares. Database work
still runs on that thread, as a sync view's would; Django's request cycle retires connections
around it, so this doesn't use `db()`, which does that itself.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from asgiref.sync import sync_to_async
from django.core.exceptions import RequestDataTooBig, TooManyFilesSent
from django.core.files.uploadedfile import UploadedFile
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.http.multipartparser import MultiPartParserError
from django.views.decorators.http import require_POST
from pydantic import BaseModel

from league.domain.errors import DomainError, InvalidAction
from league.domain.images import MAX_IMAGE_BYTES, detect_image, sha256
from league.integrations import discord_rest
from league.models import Match, Player
from league.services import awards, results
from league.services.results import ImageRef
from league.web.api import reads
from league.web.api import schema as a
from league.web.auth.session import player_of
from league.web.live.schema import MatchStatus
from league.web.text import plain

logger = logging.getLogger(__name__)

MAX_ID = 2**63 - 1
# The form's other fields and the multipart framing fit easily in this, on top of the image.
FORM_OVERHEAD = 1024 * 1024
# The bot's own words (bot/handlers/results.py), so Discord and the web refuse alike.
MATCH_ID_HELP = "It's on the scoreboard after the game, and in the match history."
NO_MATCH_ID = f"Enter the Deadlock match ID. {MATCH_ID_HELP}"
BAD_MATCH_ID = f"The Deadlock match ID is numbers only. {MATCH_ID_HELP}"
TOO_LARGE = "That file is too large: the limit is 20 MB."
NOT_AN_IMAGE = "That file isn't a PNG, JPEG or WebP image."
NO_ARCHIVE = "The archive channel isn't set up. Ask staff to run /setup."
NO_WINNER = "Choose the winning team."
TOO_MANY_KEYS = "Choose up to two key players."
BAD_REQUEST = "That didn't work. Refresh and try again."
UPLOAD_FAILED = "Couldn't send the screenshot to Discord. Try again in a moment."


@dataclass(frozen=True, slots=True)
class ReportForm:
    winner: str
    deadlock_match_id: int
    awards: dict[int, str]
    screenshot: UploadedFile | None


async def _db[**P, T](fn: Callable[P, T], /, *args: P.args, **kwargs: P.kwargs) -> T:
    return await sync_to_async(fn, thread_sensitive=True)(*args, **kwargs)


def _send(body: BaseModel, status: int = 200) -> JsonResponse:
    response = JsonResponse(body.model_dump(mode="json"), status=status)
    response["Cache-Control"] = "no-store"
    return response


def _refuse(text: str, status: int = 400) -> JsonResponse:
    return _send(a.Refusal(refusal=plain(text) or BAD_REQUEST), status)


def _in_server(match_id: int, community_id: int) -> bool:
    return Match.objects.filter(pk=match_id, community_id=community_id).exists()


def _archive_channel_id(match_id: int) -> int | None:
    match = Match.objects.select_related("community").get(pk=match_id)
    return match.community.archive_channel_id


def parse_deadlock_match_id(raw: str) -> int:
    """A captain's Deadlock match ID, as the bot's form reads it. Required: it's how the result
    is checked and the stats fetched."""
    cleaned = raw.strip()
    if not cleaned:
        raise InvalidAction(NO_MATCH_ID)
    if not cleaned.isdigit() or len(cleaned) > 18 or int(cleaned) <= 0:
        raise InvalidAction(BAD_MATCH_ID)
    return int(cleaned)


def _player_id(raw: str) -> int:
    if not raw.isdigit() or len(raw) > 19 or not 0 < int(raw) <= MAX_ID:
        raise InvalidAction(BAD_REQUEST)
    return int(raw)


def _form(request: HttpRequest) -> ReportForm:
    """Reads the form. Parsing may spool a large upload to disk, so this runs on a thread."""
    try:
        post, files = request.POST, request.FILES
    except (MultiPartParserError, RequestDataTooBig, TooManyFilesSent) as exc:
        raise InvalidAction(BAD_REQUEST) from exc
    winner = post.get("winner", "")
    if winner not in {"A", "B"}:
        raise InvalidAction(NO_WINNER)
    deadlock_match_id = parse_deadlock_match_id(post.get("deadlock_match_id", ""))
    raw_mvp = post.get("mvp", "")
    mvp = _player_id(raw_mvp) if raw_mvp else None
    keys = [_player_id(raw) for raw in post.getlist("keys") if raw]
    if len(keys) > awards.MAX_KEY:
        raise InvalidAction(TOO_MANY_KEYS)
    return ReportForm(
        winner=winner,
        deadlock_match_id=deadlock_match_id,
        awards=awards.from_picks(mvp, [key for key in keys if key != mvp]),
        screenshot=files.get("screenshot"),
    )


def _image_ref(data: bytes, extension: str, channel_id: int, message: dict[str, Any]) -> ImageRef:
    """Raises KeyError, IndexError, TypeError or ValueError on a message without the file."""
    return ImageRef(
        sha256=sha256(data),
        archive_channel_id=channel_id,
        archive_message_id=int(message["id"]),
        attachment_id=int(message["attachments"][0]["id"]),
        extension=extension,
    )


async def _screenshot(form: ReportForm, match_id: int) -> tuple[bytes, str, int] | None:
    """The screenshot's bytes, kind and archive channel, checked; None with no screenshot.
    Raises InvalidAction with the bot's words."""
    if form.screenshot is None:
        return None
    if form.screenshot.size is None or form.screenshot.size > MAX_IMAGE_BYTES:
        raise InvalidAction(TOO_LARGE)
    data = await asyncio.to_thread(form.screenshot.read)
    extension = detect_image(data)
    if extension is None:
        raise InvalidAction(NOT_AN_IMAGE)
    channel_id = await _db(_archive_channel_id, match_id)
    if channel_id is None:
        raise InvalidAction(NO_ARCHIVE)
    return data, extension, channel_id


@require_POST
async def report(request: HttpRequest, match_id: int) -> HttpResponse:
    # On the database thread: the session loads from the database on first use.
    player: Player | None = await _db(player_of, request)
    if player is None:
        return _send(a.ApiError(error="signed-out"), 401)
    where = await _db(reads.scope)
    if where is None:
        return _send(a.ApiError(error="not-set-up"), 503)
    if match_id > MAX_ID or not await _db(_in_server, match_id, where.community.pk):
        return _send(a.ApiError(error="not-found"), 404)

    try:
        await _db(results.check_can_report, match_id, player)
        # By the declared size too, so an oversized body is refused whatever it holds.
        length = request.META.get("CONTENT_LENGTH") or "0"
        if not length.isdigit() or int(length) > MAX_IMAGE_BYTES + FORM_OVERHEAD:
            raise InvalidAction(TOO_LARGE)
        form = await asyncio.to_thread(_form, request)
        shot = await _screenshot(form, match_id)
    except DomainError as refused:
        return _refuse(refused.message)

    image = None
    if shot is not None:
        data, extension, channel_id = shot
        filename = f"match-{match_id}-player-{player.pk}.{extension}"
        content = f"Match #{match_id}: submitted by {player.display_name}"
        try:
            message = await asyncio.to_thread(
                discord_rest.post_file, channel_id, data, filename, content
            )
            image = _image_ref(data, extension, channel_id, message)
        except (discord_rest.DiscordRestError, KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning(
                "Match %s: the report screenshot didn't reach Discord: %s", match_id, exc
            )
            return _refuse(UPLOAD_FAILED, 502)

    try:
        status = await _db(
            results.submit_report,
            match_id,
            player,
            form.winner,
            image,
            form.deadlock_match_id,
            form.awards or None,
        )
    except DomainError as refused:
        return _refuse(refused.message)
    return _send(a.ReportDone(status=cast(MatchStatus, status)))
