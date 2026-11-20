"""Which player a browser session belongs to.

The web keeps its own session key instead of `django.contrib.auth.login()`: `Player` is the
user model, so `login()` would hand a staff player's Discord sign-in the admin without a password.
The web's keys all start with `web_`, so signing out leaves anything else in the session alone:
a staff member signed in to the admin stays signed in there.
"""

from __future__ import annotations

from typing import Any

from django.contrib.sessions.backends.base import SessionBase
from django.http import HttpRequest

from league.asyncdb import db
from league.models import Player
from league.services import live

SESSION_KEY = "web_player_id"
PREFIX = "web_"


def sign_in(request: HttpRequest, player: Player) -> None:
    """Sign the browser in as this player. Callers check guild membership and is_active first."""
    if not player.is_active:
        raise ValueError("an inactive player can't sign in")
    # A new session key, so one planted before sign-in is worthless afterwards.
    request.session.cycle_key()
    request.session[SESSION_KEY] = player.pk


def sign_out(request: HttpRequest) -> int | None:
    """Sign the player out and tell the web process, so that player's open sockets close.
    Returns the player's ID, or None when nobody was signed in."""
    player_id = request.session.get(SESSION_KEY)
    # A session isn't iterable, so .keys() it is.
    for key in [key for key in request.session.keys() if key.startswith(PREFIX)]:  # noqa: SIM118
        del request.session[key]
    if not isinstance(player_id, int):
        return None
    # Stored now, not when the response goes out: the web process rereads the session as soon
    # as it hears the notification. An emptied session is deleted, as Django would otherwise
    # leave its row (and the old cookie's sign-in) behind.
    if request.session.keys():
        request.session.save()
    else:
        request.session.flush()
    live.publish(live.player_topic(player_id))
    return player_id


def _player(player_id: Any) -> Player | None:
    # bool is an int too; a session never stores one here, but don't let True mean player 1.
    if not isinstance(player_id, int) or isinstance(player_id, bool):
        return None
    return Player.objects.filter(pk=player_id, is_active=True).first()


def player_of(request: HttpRequest) -> Player | None:
    """The signed-in player, or None. A player made inactive since signing in is signed out."""
    return _player(request.session.get(SESSION_KEY))


async def player_of_session(session: SessionBase) -> Player | None:
    """For the websocket consumer, which has the session but no request."""
    return await db(_player, await session.aget(SESSION_KEY))
