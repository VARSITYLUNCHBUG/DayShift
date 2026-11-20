"""Why a sign-in was refused. Every refusal redirects to `/signin?error=<code>`, and the sign-in
page shows the matching message. The codes are the contract with the frontend:

- `not-member`: the Discord account isn't in the server. Join it (the session's `invite_url`),
  then try again.
- `denied`: the player cancelled on Discord's or Steam's consent screen.
- `discord-down`: Discord didn't answer, or answered something we couldn't use. Try again soon.
- `state`: the sign-in link expired, was used twice, came from another browser, or Steam's
  answer didn't check out. Start again.
- `steam-unproven`: no player has proven or verified this Steam account. Sign in with Discord
  first, then link Steam.
- `steam-taken`: another player has proven or verified this Steam account.
- `steam-down`: Steam didn't answer. Try again soon.
- `inactive`: staff have switched this player's account off.
- `signed-out`: linking Steam needs a signed-in player. Sign in, then link.
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlencode

from django.http import HttpResponseRedirect

NOT_MEMBER = "not-member"
DENIED = "denied"
DISCORD_DOWN = "discord-down"
STATE = "state"
STEAM_UNPROVEN = "steam-unproven"
STEAM_TAKEN = "steam-taken"
STEAM_DOWN = "steam-down"
INACTIVE = "inactive"
SIGNED_OUT = "signed-out"

CODES = frozenset(
    {
        NOT_MEMBER,
        DENIED,
        DISCORD_DOWN,
        STATE,
        STEAM_UNPROVEN,
        STEAM_TAKEN,
        STEAM_DOWN,
        INACTIVE,
        SIGNED_OUT,
    }
)

SIGNIN_PATH = "/signin"

logger = logging.getLogger("league.web.auth")


def refuse(code: str, why: str, **detail: Any) -> HttpResponseRedirect:
    """Log why for staff (never a token or secret), and send the player to the sign-in page."""
    if code not in CODES:
        raise ValueError(f"unknown sign-in refusal code {code!r}")
    logger.info("Sign-in refused", extra={"code": code, "why": why, **detail})
    response = HttpResponseRedirect(f"{SIGNIN_PATH}?{urlencode({'error': code})}")
    response["Cache-Control"] = "no-store"
    return response
