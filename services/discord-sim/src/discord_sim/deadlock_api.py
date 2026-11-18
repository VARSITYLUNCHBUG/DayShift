"""A stand-in for deadlock-api.com, so a dev stack never calls the real one.

This is its state; `rest/deadlock.py` serves it. It covers what the app calls:

- Custom lobbies. Creating one either works, with a made-up party code, or fails, as
  `PUT /_sim/deadlock-api` sets. Nothing is ever played, so match IDs and metadata are never known.
- The hero roster (`/v1/assets/heroes`), for the admin's champion sync: the repo's seed roster
  (`heroes.py`) unless `PUT /_sim/deadlock-api` replaces it, to try a new, renamed or retired hero.
- Steam names (`/v1/players/steam`), for /link: every account has a made-up name unless
  `PUT /_sim/deadlock-api` names it, or marks it unknown with null.
"""

from __future__ import annotations

import re
import secrets
import string
from dataclasses import dataclass, field
from typing import Any

from discord_sim.errors import ControlError
from discord_sim.heroes import HEROES

CREATE = "create"
FAIL = "fail"
MODES = (CREATE, FAIL)
CODE_ALPHABET = string.ascii_uppercase + string.digits
# Steam's 32-bit account IDs.
MAX_ACCOUNT_ID = 2**32 - 1


@dataclass
class Lobby:
    party_id: str
    party_code: str
    region: str
    started: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "party_id": self.party_id,
            "party_code": self.party_code,
            "region": self.region,
            "started": self.started,
        }


@dataclass(frozen=True)
class Hero:
    id: int
    name: str
    player_selectable: bool = True
    disabled: bool = False

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "player_selectable": self.player_selectable,
            "disabled": self.disabled,
        }

    def payload(self) -> dict[str, Any]:
        """deadlock-api's hero JSON, the fields the app reads and a few around them. No images:
        the stand-in has none to serve, and the app keeps an empty icon."""
        return {
            "id": self.id,
            "class_name": "hero_" + re.sub(r"[^a-z0-9]+", "_", self.name.lower()).strip("_"),
            "name": self.name,
            "player_selectable": self.player_selectable,
            "disabled": self.disabled,
            "in_development": False,
            "images": {},
        }

    @property
    def active(self) -> bool:
        return self.player_selectable and not self.disabled


def seed_heroes() -> list[Hero]:
    return [Hero(hero_id, name) for hero_id, name in HEROES]


def _hero(raw: Any) -> Hero:
    if not isinstance(raw, dict):
        raise ControlError(400, "Each hero is {id, name, player_selectable?, disabled?}.")
    hero_id, name = raw.get("id"), raw.get("name")
    if isinstance(hero_id, bool) or not isinstance(hero_id, int) or hero_id < 1:
        raise ControlError(400, "A hero's id is a positive integer.")
    if not isinstance(name, str) or not name.strip():
        raise ControlError(400, f"Hero {hero_id} needs a name.")
    flags = {
        key: raw.get(key, default)
        for key, default in (("player_selectable", True), ("disabled", False))
    }
    if not all(isinstance(value, bool) for value in flags.values()):
        raise ControlError(400, "player_selectable and disabled are true or false.")
    return Hero(hero_id, name.strip(), **flags)


def account_ids(raw: str) -> list[int]:
    """`?account_ids=1,2,3`, as deadlock-api reads it. Anything else is a 400 there too."""
    try:
        ids = [int(part) for part in raw.split(",") if part.strip()]
    except ValueError:
        raise ControlError(400, "account_ids is a comma-separated list of account IDs.") from None
    if not ids or not all(0 < pk <= MAX_ACCOUNT_ID for pk in ids):
        raise ControlError(400, "account_ids is a comma-separated list of account IDs.")
    return ids


@dataclass
class DeadlockApi:
    lobby_mode: str = CREATE
    lobbies: dict[str, Lobby] = field(default_factory=dict)
    heroes: list[Hero] = field(default_factory=seed_heroes)
    # An account named here answers with that name; one set to None is unknown, as an account
    # that never played is. Every other account gets a made-up name.
    steam_names: dict[int, str | None] = field(default_factory=dict)

    def reset(self) -> None:
        self.lobby_mode = CREATE
        self.lobbies.clear()
        self.heroes = seed_heroes()
        self.steam_names.clear()

    def describe(self) -> dict[str, Any]:
        return {
            "lobby": self.lobby_mode,
            "lobbies": [lobby.describe() for lobby in self.lobbies.values()],
            "heroes": [hero.describe() for hero in self.heroes],
            "steam_names": {str(pk): name for pk, name in self.steam_names.items()},
        }

    def set_mode(self, mode: Any) -> None:
        if mode not in MODES:
            raise ControlError(400, f"lobby is one of {', '.join(MODES)}.")
        self.lobby_mode = mode

    def set_heroes(self, raw: Any) -> None:
        """Replace the roster, to try the admin's sync against a new, renamed or retired hero."""
        if not isinstance(raw, list) or not raw:
            raise ControlError(400, "heroes is a non-empty list of {id, name, ...}.")
        heroes = [_hero(entry) for entry in raw]
        if len({hero.id for hero in heroes}) != len(heroes):
            raise ControlError(400, "Two heroes share an id.")
        self.heroes = heroes

    def set_steam_names(self, raw: Any) -> None:
        """Merge `{account_id: name | null}` into the names the stand-in knows."""
        if not isinstance(raw, dict):
            raise ControlError(400, "steam_names maps an account ID to a name, or to null.")
        names: dict[int, str | None] = {}
        for key, name in raw.items():
            (pk,) = account_ids(str(key))
            if name is not None and (not isinstance(name, str) or not name.strip()):
                raise ControlError(400, f"Account {pk}'s name is a non-empty string, or null.")
            names[pk] = name.strip() if isinstance(name, str) else None
        self.steam_names.update(names)

    def roster(self, *, only_active: bool) -> list[dict[str, Any]]:
        return [hero.payload() for hero in self.heroes if hero.active or not only_active]

    def steam(self, ids: list[int]) -> list[dict[str, Any]]:
        """deadlock-api's Steam profiles for the accounts it knows, in the order asked."""
        rows = []
        for pk in dict.fromkeys(ids):
            name = self.steam_names.get(pk, f"steam_{pk}")
            if name is None:
                continue
            rows.append(
                {
                    "account_id": pk,
                    "personaname": name,
                    "profileurl": f"https://steamcommunity.com/profiles/{pk + 76561197960265728}/",
                    "avatar": "",
                    "countrycode": None,
                    "realname": None,
                }
            )
        return rows

    def create(self, party_id: str, region: str) -> Lobby | None:
        """A new lobby, or None while lobbies are set to fail."""
        if self.lobby_mode == FAIL:
            return None
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(6))
        lobby = Lobby(party_id=party_id, party_code=code, region=region)
        self.lobbies[party_id] = lobby
        return lobby
