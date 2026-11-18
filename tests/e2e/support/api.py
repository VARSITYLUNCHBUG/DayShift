"""Clients for the dev control API and the Discord simulator's control API.

The browser does the part under test; these set the stage and read the outcome. Every wait is
bounded polling on API state (`wait_for`), never a fixed sleep.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import httpx

JSON = dict[str, Any]

# How long the control API may take on one call: an advance through the bot clicks for each
# player and waits for the bot each time.
CALL_TIMEOUT = 120.0


def wait_for[T](probe: Callable[[], T | None], what: str, *, timeout: float = 30.0) -> T:
    """Poll `probe` until it returns something truthy, and return that. Fails after `timeout` s."""
    deadline = time.monotonic() + timeout
    while True:
        result = probe()
        if result:
            return result
        if time.monotonic() >= deadline:
            raise AssertionError(f"Timed out after {timeout:g} s waiting for {what}.")
        time.sleep(0.2)


class ApiError(AssertionError):
    """A call answered with an error."""


def checked(response: httpx.Response) -> Any:
    """The JSON body of a 200 response."""
    if response.status_code != 200:
        request = response.request
        detail = response.text[:2000]
        raise ApiError(f"{request.method} {request.url}: {response.status_code} {detail}")
    return response.json() if response.content else None


class _Client:
    def __init__(self, base_url: str) -> None:
        self.http = httpx.Client(base_url=base_url.rstrip("/") + "/", timeout=CALL_TIMEOUT)

    def call(self, method: str, path: str, body: JSON | None = None) -> Any:
        return checked(self.http.request(method, path, json=body))

    def close(self) -> None:
        self.http.close()


class ControlApi(_Client):
    """The dev control API, `/_control/api/` (devtools/README.md)."""

    def state(self) -> JSON:
        state: JSON = self.call("GET", "state")
        return state

    def reset(self) -> JSON:
        """Back to the dev fixtures."""
        result: JSON = self.call("POST", "reset", {"fixture": "dev_default"})
        return result

    def players(self) -> list[JSON]:
        players: list[JSON] = self.call("GET", "players")["players"]
        return players

    def create_players(self, count: int, **options: Any) -> JSON:
        result: JSON = self.call("POST", "players", {"count": count, **options})
        return result

    def match(self, match_id: int | str = "latest") -> JSON:
        match: JSON = self.call("GET", f"matches/{match_id}")
        return match

    def advance(self, match_id: int | str, until: str, *, via: str = "service") -> JSON:
        result: JSON = self.call(
            "POST", f"matches/{match_id}/advance", {"until": until, "via": via}
        )
        return result

    def lobby_match(self) -> JSON:
        """Twelve fresh players join the queue (through the services, so it's quick): a lobby."""
        match_id = self.create_players(12, join_queue=True, name_prefix="Lobby")["match_id"]
        assert match_id, "Twelve players in the queue should pop a lobby."
        return self.match(match_id)

    def wait_match(
        self, match_id: int | str, check: Callable[[JSON], bool], what: str, timeout: float = 30
    ) -> JSON:
        """The match once `check` holds for it."""

        def probe() -> JSON | None:
            match = self.match(match_id)
            return match if check(match) else None

        return wait_for(probe, f"match {match_id}: {what}", timeout=timeout)


class SimApi(_Client):
    """The Discord simulator's control API, `/_sim/` (services/discord-sim/README.md)."""

    def health(self) -> JSON:
        health: JSON = self.call("GET", "_sim/health")
        return health

    def channel(self, channel: str) -> JSON:
        """A channel's summary: id, name, type, parent."""
        summary: JSON = self.call("GET", f"_sim/channels/{channel}/messages?limit=1")["channel"]
        return summary

    def messages(self, channel: str, limit: int = 50) -> list[JSON]:
        """A channel's messages, newest first."""
        result: JSON = self.call("GET", f"_sim/channels/{channel}/messages?limit={limit}")
        messages: list[JSON] = result["messages"]
        return messages

    def attachment(self, attachment_id: str) -> bytes:
        response = self.http.get(f"_sim/attachments/{attachment_id}")
        response.raise_for_status()
        return response.content

    def last_seq(self) -> int:
        """The sequence number of the newest log entry."""
        return int(self.call("GET", f"_sim/log?since={2**62}")["last_seq"])

    def log_tail(self, count: int = 500) -> list[JSON]:
        """The newest `count` entries of the log: REST calls, gateway events, control calls."""
        since = max(0, self.last_seq() - count)
        entries: list[JSON] = self.call("GET", f"_sim/log?since={since}&limit={count}")["entries"]
        return entries

    def gateway_events(self, since: int) -> list[str]:
        """The gateway events after log entry `since`, oldest first."""
        log = self.call("GET", f"_sim/log?since={since}&kind=gateway&limit=5000")["entries"]
        return [str(entry.get("event")) for entry in log]

    def reconnected_since(self, seq: int) -> bool:
        """Whether the bot identified on the gateway after log entry `seq`, and is connected."""
        identified = "IDENTIFY" in self.gateway_events(seq)
        return identified and bool(self.health().get("bot_connected"))


def text_of(message: JSON) -> str:
    """Every text block of a simulator message, as one string."""
    return "\n".join(message.get("text") or []) or str(message.get("content") or "")
