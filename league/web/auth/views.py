"""Sign-in, sign-out and the session the player frontend boots from.

Sign-in is only ever for active members of the web's Discord server (`WEB_GUILD_ID`): Discord
sign-in checks membership with the bot's token, and Steam sign-in checks it again for the player
the Steam account belongs to. Every refusal goes back to the sign-in page with a code from
`errors`. Network calls to Discord and Steam run outside any database transaction.
"""

from __future__ import annotations

import hmac
import logging
import secrets
from typing import Any

from django.conf import settings
from django.db import transaction
from django.http import (
    Http404,
    HttpRequest,
    HttpResponse,
    HttpResponseBase,
    HttpResponseRedirect,
    JsonResponse,
)
from django.shortcuts import render
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from league.domain import steam as steam_ids
from league.domain.errors import InvalidAction
from league.integrations import discord_rest
from league.models import Player, SteamAccount
from league.services import steam as steam_service
from league.web.auth import discord_oauth, errors, steam_openid
from league.web.auth.session import player_of, sign_in, sign_out
from league.web.avatars import avatar_url

DISCORD_PENDING = "web_discord_oauth"
STEAM_PENDING = "web_steam_openid"
LOGIN, LINK = "login", "link"
INTENTS = (LOGIN, LINK)
# Stand-in players have Discord IDs under 1000, like the live test runs' stand-ins: no real
# Discord account has one.
STAND_IN_MAX_ID = 999
MAX_NEXT_LENGTH = 500

logger = logging.getLogger("league.web.auth")


def safe_next(raw: str | None) -> str:
    """Where to go after sign-in: a path on this site, never another site."""
    if (
        not raw
        or len(raw) > MAX_NEXT_LENGTH
        or not raw.startswith("/")
        or raw.startswith("//")
        or "\\" in raw
        or any(ord(char) < 0x20 or ord(char) == 0x7F for char in raw)
        or not url_has_allowed_host_and_scheme(raw, allowed_hosts=set())
    ):
        return "/"
    return raw


def _state_matches(given: str | None, pending: Any) -> bool:
    expected = pending.get("state") if isinstance(pending, dict) else None
    if not isinstance(expected, str) or not expected or not given:
        return False
    return hmac.compare_digest(given.encode(), expected.encode())


def _member(user_id: int) -> discord_rest.Member | None:
    """Raises DiscordRestError when Discord can't say either way."""
    return discord_rest.get_member(settings.WEB_GUILD_ID, user_id)


def _is_inactive(discord_user_id: int) -> bool:
    return Player.objects.filter(discord_user_id=discord_user_id, is_active=False).exists()


@transaction.atomic
def _save_member(member: discord_rest.Member) -> Player:
    """The member's player, made on first sight, with their server name and avatar now."""
    player = Player.objects.from_discord(member.user_id, member.display_name)
    if player.discord_avatar != member.avatar:
        player.discord_avatar = member.avatar
        player.save(update_fields=["discord_avatar", "updated_at"])
    return player


def _finish(
    request: HttpRequest, member: discord_rest.Member, next_url: str, how: str
) -> HttpResponseBase:
    """Sign in the member's player, unless staff switched it off."""
    if _is_inactive(member.user_id):
        return errors.refuse(errors.INACTIVE, "player is inactive", discord_user=member.user_id)
    player = _save_member(member)
    if not player.is_active:  # Switched off in the moment since the check above.
        return errors.refuse(errors.INACTIVE, "player is inactive", player=player.pk)
    sign_in(request, player)
    logger.info("Signed in", extra={"player": player.pk, "via": how})
    return HttpResponseRedirect(next_url)


# --- Discord ---------------------------------------------------------------------------------


@require_GET
@never_cache
def discord_start(request: HttpRequest) -> HttpResponseBase:
    if not settings.DISCORD_CLIENT_ID or not settings.DISCORD_CLIENT_SECRET:
        return errors.refuse(errors.DISCORD_DOWN, "DISCORD_CLIENT_ID/SECRET aren't set")
    state = secrets.token_urlsafe(32)
    request.session[DISCORD_PENDING] = {"state": state, "next": safe_next(request.GET.get("next"))}
    return HttpResponseRedirect(discord_oauth.authorize_url(state))


@require_GET
@never_cache
def discord_callback(request: HttpRequest) -> HttpResponseBase:
    # Popped first, so a state works once whatever happens next.
    pending = request.session.pop(DISCORD_PENDING, None)
    if not _state_matches(request.GET.get("state"), pending):
        return errors.refuse(errors.STATE, "Discord state missing or wrong")
    error = request.GET.get("error")
    if error == "access_denied":
        return errors.refuse(errors.DENIED, "player cancelled on Discord")
    code = request.GET.get("code")
    if error or not code:
        return errors.refuse(errors.DISCORD_DOWN, "no code", error=(error or "")[:50])
    try:
        user_id = discord_oauth.fetch_user_id(code)
        member = _member(user_id)
    except (discord_oauth.OAuthError, discord_rest.DiscordRestError) as exc:
        return errors.refuse(errors.DISCORD_DOWN, str(exc)[:200])
    if member is None:
        return errors.refuse(errors.NOT_MEMBER, "not in the server", discord_user=user_id)
    return _finish(request, member, safe_next(pending["next"]), "Discord")


# --- Steam -----------------------------------------------------------------------------------


@require_GET
@never_cache
def steam_start(request: HttpRequest) -> HttpResponseBase:
    intent = request.GET.get("intent", LOGIN)
    if intent not in INTENTS:
        intent = LOGIN
    player = player_of(request)
    if intent == LINK and player is None:
        return errors.refuse(errors.SIGNED_OUT, "Steam link without a signed-in player")
    state = secrets.token_urlsafe(32)
    return_to = steam_openid.return_to(state)
    request.session[STEAM_PENDING] = {
        "state": state,
        "intent": intent,
        "next": safe_next(request.GET.get("next")),
        "return_to": return_to,
        "player": player.pk if player is not None else None,
    }
    return HttpResponseRedirect(steam_openid.login_url(return_to))


@require_GET
@never_cache
def steam_callback(request: HttpRequest) -> HttpResponseBase:
    pending = request.session.pop(STEAM_PENDING, None)
    if not _state_matches(request.GET.get("state"), pending):
        return errors.refuse(errors.STATE, "Steam state missing or wrong")
    try:
        steam64 = steam_openid.verify(request.GET, pending["return_to"])
    except steam_openid.Cancelled:
        return errors.refuse(errors.DENIED, "player cancelled on Steam")
    except steam_openid.Invalid as exc:
        return errors.refuse(errors.STATE, f"Steam answer invalid: {exc}")
    except steam_openid.Unreachable as exc:
        return errors.refuse(errors.STEAM_DOWN, str(exc))
    account_id = steam_ids.account_from_steam64(steam64)
    if account_id is None:
        return errors.refuse(errors.STATE, "not an individual account", steam64=steam64)
    if pending["intent"] == LINK:
        return _steam_link(request, pending, account_id, steam64)
    return _steam_login(request, pending, account_id)


def _steam_link(
    request: HttpRequest, pending: dict[str, Any], account_id: int, steam64: int
) -> HttpResponseBase:
    player = player_of(request)
    if player is None:
        return errors.refuse(errors.SIGNED_OUT, "signed out before Steam came back")
    if player.pk != pending["player"]:
        return errors.refuse(errors.STATE, "another player signed in meanwhile")
    name = steam_openid.persona_name(steam64)
    try:
        steam_service.link_proven(player, account_id, name)
    except InvalidAction as exc:
        return errors.refuse(
            errors.STEAM_TAKEN, exc.message, player=player.pk, steam_account=account_id
        )
    logger.info("Steam proven", extra={"player": player.pk, "steam_account": account_id})
    return HttpResponseRedirect(safe_next(pending["next"]))


def _steam_login(
    request: HttpRequest, pending: dict[str, Any], account_id: int
) -> HttpResponseBase:
    account = SteamAccount.objects.select_related("player").filter(account_id=account_id).first()
    if account is None or not steam_service.is_proven_or_verified(account):
        return errors.refuse(
            errors.STEAM_UNPROVEN, "no proven or verified link", steam_account=account_id
        )
    player = account.player
    if not player.is_active:
        return errors.refuse(errors.INACTIVE, "player is inactive", player=player.pk)
    try:
        member = _member(player.discord_user_id)
    except discord_rest.DiscordRestError as exc:
        return errors.refuse(errors.DISCORD_DOWN, str(exc)[:200])
    if member is None:
        return errors.refuse(errors.NOT_MEMBER, "not in the server", player=player.pk)
    return _finish(request, member, safe_next(pending["next"]), "Steam")


# --- Session ---------------------------------------------------------------------------------


@require_POST
def sign_out_view(request: HttpRequest) -> HttpResponse:
    """Signs out the web player only: an admin sign-in in the same browser stays."""
    sign_out(request)
    if "text/html" in request.headers.get("Accept", ""):
        return HttpResponseRedirect("/")
    return HttpResponse(status=204)


def player_json(player: Player) -> dict[str, Any]:
    """The signed-in player as the frontend sees them. Never a Discord or Steam ID."""
    return {
        "id": str(player.pk),
        "name": player.display_name,
        "avatar": avatar_url(player),
        "steam": [
            {
                "name": account.steam_name,
                "proven": account.proven_at is not None,
                "verified": account.verified_at is not None,
            }
            for account in SteamAccount.objects.filter(player=player).order_by("linked_at", "pk")
        ],
    }


def dev_login_enabled() -> bool:
    return bool(settings.WEB_DEV_LOGIN and settings.DEBUG)


@require_GET
@ensure_csrf_cookie
def session_view(request: HttpRequest) -> JsonResponse:
    """Who is signed in. Also sets the CSRF cookie the frontend's POSTs need."""
    player = player_of(request)
    response = JsonResponse(
        {
            "signed_in": player is not None,
            "player": player_json(player) if player is not None else None,
            "dev_login": dev_login_enabled(),
            "invite_url": settings.DISCORD_INVITE_URL or None,
        }
    )
    response["Cache-Control"] = "no-store"
    return response


# --- Dev login -------------------------------------------------------------------------------


@transaction.atomic
def _stand_in(name: str) -> Player | None:
    """The stand-in player with this name, made on first use with the lowest free stand-in ID."""
    stand_ins = Player.objects.select_for_update().filter(
        discord_user_id__gt=0, discord_user_id__lte=STAND_IN_MAX_ID
    )
    existing = stand_ins.filter(display_name=name).order_by("pk").first()
    if existing is not None:
        return existing
    used = set(stand_ins.values_list("discord_user_id", flat=True))
    free = next((n for n in range(1, STAND_IN_MAX_ID + 1) if n not in used), None)
    return Player.objects.from_discord(free, name) if free is not None else None


@require_http_methods(["GET", "POST"])
@never_cache
def dev_login(request: HttpRequest) -> HttpResponse:
    """Sign in as anyone, or as a new stand-in, without Discord. Local testing only."""
    if not dev_login_enabled():
        raise Http404
    error = ""
    if request.method == "POST":
        chosen = request.POST.get("player", "")
        name = request.POST.get("name", "").strip()[:100]
        player: Player | None = None
        if chosen.isdigit():
            player = Player.objects.filter(pk=int(chosen)).first()
            error = "" if player else "No player has that ID."
        elif name:
            player = _stand_in(name)
            error = "" if player else "Every stand-in ID is taken."
        else:
            error = "Pick a player or type a name."
        if player is not None and not player.is_active:
            player, error = None, "That player is inactive."
        if player is not None:
            sign_in(request, player)
            return HttpResponseRedirect(safe_next(request.POST.get("next")))
    players = Player.objects.filter(is_active=True).order_by("display_name", "pk")[:500]
    return render(
        request,
        "league/dev_login.html",
        {"players": players, "error": error, "next": safe_next(request.GET.get("next"))},
        status=400 if error else 200,
    )
