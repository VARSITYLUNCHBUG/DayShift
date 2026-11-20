"""The HTTP API's endpoints. Every one but `landing` needs a signed-in player; POSTs need
Django's CSRF token (the `X-CSRFToken` header), which the CSRF middleware checks before any of
this runs.

A player's profile is private: `/api/me/...` only ever reads the signed-in player, and there is
no endpoint for anyone else's.
"""

from __future__ import annotations

from collections.abc import Callable
from functools import wraps
from typing import Concatenate

from django.http import HttpRequest, HttpResponse, JsonResponse
from django.views.decorators.http import require_GET, require_POST
from pydantic import BaseModel

from league.models import Player, Season, SteamAccount
from league.services import landing as landing_service
from league.services import share_card, steam
from league.web.api import reads
from league.web.api import schema as a
from league.web.api.reads import Scope
from league.web.auth.session import player_of

# Per player and changing all the time: the browser may keep it, but must ask again each time.
READ_CACHE = "private, no-cache"
MAX_ID = 2**63 - 1

type ApiView[**P] = Callable[Concatenate[HttpRequest, Player, Scope, P], HttpResponse]


def send(body: BaseModel, *, status: int = 200, cache: str = READ_CACHE) -> JsonResponse:
    response = JsonResponse(body.model_dump(mode="json"), status=status)
    response["Cache-Control"] = cache
    return response


def error(code: a.ErrorCode, status: int) -> JsonResponse:
    return send(a.ApiError(error=code), status=status, cache="no-store")


def signed_in[**P](view: ApiView[P]) -> Callable[Concatenate[HttpRequest, P], HttpResponse]:
    """The signed-in player and the web's server, or a JSON refusal."""

    @wraps(view)
    def inner(request: HttpRequest, *args: P.args, **kwargs: P.kwargs) -> HttpResponse:
        player = player_of(request)
        if player is None:
            return error("signed-out", 401)
        where = reads.scope()
        if where is None:
            return error("not-set-up", 503)
        return view(request, player, where, *args, **kwargs)

    return inner


def _id(raw: str | None) -> int | None:
    """A positive database ID from a query string, or None."""
    if raw is None or not raw.isdigit() or len(raw) > 19:
        return None
    value = int(raw)
    return value if 0 < value <= MAX_ID else None


def _offset(raw: str | None) -> int | None:
    """A row offset from a query string (0 when absent), or None if it isn't one."""
    if raw is None:
        return 0
    if not raw.isdigit() or len(raw) > 9:
        return None
    return int(raw)


def _season(request: HttpRequest, where: Scope) -> Season | JsonResponse:
    """The `season` asked for (the open one without it), or the refusal to send."""
    raw = request.GET.get("season")
    season_id = None if raw is None else _id(raw)
    if raw is not None and season_id is None:
        return error("bad-request", 400)
    return reads.season_of(where, season_id) or error("not-found", 404)


# --- Matches ----------------------------------------------------------------------------------


@require_GET
@signed_in
def matches(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    kind = request.GET.get("status", "live")
    cursor = request.GET.get("cursor") or None
    before = _id(cursor)
    mine = request.GET.get("mine", "0")
    if (
        kind not in {"live", "recent"}
        or (cursor is not None and before is None)
        or mine not in {"0", "1"}
    ):
        return error("bad-request", 400)
    filtered: reads.MatchFilter = "live" if kind == "live" else "recent"
    return send(reads.match_list(where, viewer, filtered, before, mine=mine == "1"))


@require_GET
@signed_in
def match(request: HttpRequest, viewer: Player, where: Scope, match_id: int) -> HttpResponse:
    detail = reads.match_detail(where, match_id) if match_id <= MAX_ID else None
    if detail is None:
        return error("not-found", 404)
    return send(detail)


@require_GET
@signed_in
def match_postgame(
    request: HttpRequest, viewer: Player, where: Scope, match_id: int
) -> HttpResponse:
    body = reads.match_postgame(where, viewer, match_id) if match_id <= MAX_ID else None
    if body is None:
        return error("not-found", 404)
    return send(body)


# --- Ladder and seasons -----------------------------------------------------------------------


@require_GET
@signed_in
def ladder(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    offset = _offset(request.GET.get("offset"))
    if offset is None:
        return error("bad-request", 400)
    season = _season(request, where)
    if isinstance(season, JsonResponse):
        return season
    return send(reads.ladder(where, viewer, season, offset))


@require_GET
@signed_in
def seasons(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    return send(reads.seasons(where))


# --- The signed-in player's own ---------------------------------------------------------------


@require_GET
@signed_in
def me(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    season = _season(request, where)
    if isinstance(season, JsonResponse):
        return season
    return send(reads.my_profile(where, viewer, season))


SHARE_FLAGS = ("rating", "place", "award")


@require_GET
@signed_in
def share_png(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    """The viewer's own highlight card, with the parts they chose to show."""
    flags = {name: request.GET.get(name, "1") for name in SHARE_FLAGS}
    if any(value not in {"0", "1"} for value in flags.values()):
        return error("bad-request", 400)
    image = share_card.render(
        viewer,
        show_rating=flags["rating"] == "1",
        show_place=flags["place"] == "1",
        show_award=flags["award"] == "1",
        season=where.season,
    )
    response = HttpResponse(image, content_type="image/png")
    response["Cache-Control"] = "no-store"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_POST
@signed_in
def steam_unlink(
    request: HttpRequest, viewer: Player, where: Scope, account_pk: int
) -> HttpResponse:
    """Unlink one of the viewer's own Steam accounts, by its link's handle. Someone else's is
    not found, so the answer never says whose it is."""
    row = (
        SteamAccount.objects.filter(pk=account_pk, player=viewer).first()
        if account_pk <= MAX_ID
        else None
    )
    if row is None:
        return error("not-found", 404)
    steam.unlink(viewer, row.account_id)
    return send(a.SteamUnlinked(steam=reads.steam_rows(viewer)), cache="no-store")


# --- Search and tools -------------------------------------------------------------------------


@require_GET
@signed_in
def player_search(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    return send(reads.search_players(where, viewer, request.GET.get("q", "")))


@require_POST
@signed_in
def random_draft(request: HttpRequest, viewer: Player, where: Scope) -> HttpResponse:
    return send(reads.random_draft(where), cache="no-store")


@require_GET
def landing(request: HttpRequest) -> HttpResponse:
    """The sign-in page's tagline and advert. Public: it's shown before anyone signs in. The
    same for everyone, so shared caches may keep it a minute."""
    now = landing_service.current()
    advert = now.advert
    body = a.Landing(
        headline_html=now.tagline.headline_html if now.tagline else None,
        lead_html=now.tagline.lead_html if now.tagline else None,
        advert=None
        if advert is None
        else a.Advert(
            kind=advert.kind,
            alt=advert.alt,
            link_url=advert.link_url,
            html=advert.html,
            src=advert.src,
            youtube_id=advert.youtube_id,
        ),
    )
    return send(body, cache="public, max-age=60")
