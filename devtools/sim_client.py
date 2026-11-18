"""The Discord simulator's control API (`/_sim/...`), as the control API uses it."""

from __future__ import annotations

from typing import Any

import httpx
from django.conf import settings

from devtools.errors import BotOffline, SimError

# Tests swap in an httpx.MockTransport here.
TRANSPORT: httpx.BaseTransport | None = None
TIMEOUT_SECONDS = 15.0
# The control API's answer to an interaction while no bot is connected to its gateway.
NO_BOT = 503


def configured() -> bool:
    return bool(settings.DISCORD_SIM_URL)


def url() -> str | None:
    return settings.DISCORD_SIM_URL or None


def client() -> SimClient:
    if not configured():
        raise SimError("No Discord simulator is configured (DISCORD_SIM_URL is empty).")
    return SimClient(settings.DISCORD_SIM_URL, transport=TRANSPORT)


def reachable() -> bool:
    if not configured():
        return False
    try:
        with client() as sim:
            sim.health()
    except SimError:
        return False
    return True


def _message(response: httpx.Response) -> str:
    """The simulator's `{"error": ...}`, with the custom_ids it offers when a press found none."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:300] or response.reason_phrase
    if not isinstance(body, dict) or not body.get("error"):
        return str(body)[:300]
    message = str(body["error"])
    available = body.get("available")
    if isinstance(available, list) and available:
        message += f" There: {', '.join(str(item) for item in available[:20])}."
    return message


class SimClient:
    def __init__(self, base_url: str, *, transport: httpx.BaseTransport | None = None) -> None:
        self.base_url = base_url.rstrip("/")
        self._http = httpx.Client(
            base_url=self.base_url, transport=transport, timeout=TIMEOUT_SECONDS
        )

    def __enter__(self) -> SimClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self._http.close()

    def _call(self, method: str, path: str, **kwargs: Any) -> Any:
        try:
            response = self._http.request(method, f"/_sim/{path}", **kwargs)
        except httpx.HTTPError as exc:
            raise SimError(f"The Discord simulator isn't reachable at {self.base_url}.") from exc
        if response.status_code == NO_BOT:
            raise BotOffline(f"Simulator: {_message(response)}", response.status_code)
        if response.status_code >= 400:
            raise SimError(f"Simulator: {_message(response)}", response.status_code)
        if not response.content:
            return {}
        return response.json()

    # --- State -----------------------------------------------------------------------------

    def health(self) -> dict[str, Any]:
        return dict(self._call("GET", "health", timeout=2.0))

    def state(self) -> dict[str, Any]:
        return dict(self._call("GET", "state"))

    def reset(self) -> None:
        self._call("POST", "reset")

    # --- The guild -------------------------------------------------------------------------

    def create_role(self, name: str) -> dict[str, Any]:
        return dict(self._call("POST", "roles", json={"name": name, "mentionable": True}))

    def create_channel(self, body: dict[str, Any]) -> dict[str, Any]:
        """A channel made as a server admin would: Discord's channel JSON."""
        return dict(self._call("POST", "channels", json=body))

    def set_lobbies(self, mode: str) -> None:
        """Whether the deadlock-api stand-in makes lobbies ("create") or refuses them."""
        self._call("PUT", "deadlock-api", json={"lobby": mode})

    # --- Users -----------------------------------------------------------------------------

    def create_users(
        self,
        count: int,
        *,
        name_prefix: str | None = None,
        names: list[str] | None = None,
        dm_open: bool = True,
        roles: list[int] | None = None,
    ) -> list[dict[str, Any]]:
        """New guild members: `count` of them named from `name_prefix`, or one per name."""
        body: dict[str, Any] = {"count": count, "dm_open": dm_open}
        if roles:
            body["roles"] = [str(role) for role in roles]
        if name_prefix:
            body["name_prefix"] = name_prefix
        if names:
            body["names"] = names
        result = self._call("POST", "users", json=body)
        users = result.get("users", result) if isinstance(result, dict) else result
        return [dict(user) for user in users]

    def update_user(self, user_id: int, **fields: Any) -> None:
        self._call("PATCH", f"users/{user_id}", json=fields)

    def delete_user(self, user_id: int) -> None:
        self._call("DELETE", f"users/{user_id}")

    # --- Messages and interactions ---------------------------------------------------------

    def messages(self, channel_id: int, limit: int = 50) -> list[dict[str, Any]]:
        result = self._call("GET", f"channels/{channel_id}/messages", params={"limit": limit})
        rows = result.get("messages", result) if isinstance(result, dict) else result
        return [dict(row) for row in rows]

    def dms(self, user_id: int) -> list[dict[str, Any]]:
        """What the bot sent this user by DM, newest first."""
        result = self._call("GET", f"users/{user_id}/dms")
        rows = result.get("messages", result) if isinstance(result, dict) else result
        return sorted((dict(row) for row in rows), key=lambda m: int(m["id"]), reverse=True)

    def interaction(self, interaction_id: str) -> dict[str, Any]:
        """An interaction as it stands now, with the bot's answers since it started."""
        return dict(self._call("GET", f"interactions/{interaction_id}"))

    def component(
        self, user_id: int, message_id: int, custom_id: str, values: list[str] | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {
            "user_id": str(user_id),
            "message_id": str(message_id),
            "custom_id": custom_id,
        }
        if values is not None:
            body["values"] = values
        return dict(self._call("POST", "interactions/component", json=body))

    def modal(
        self, user_id: int, values: dict[str, Any], *, attachments: list[str] | None = None
    ) -> dict[str, Any]:
        """Submit the modal the bot last opened for this user. `values` and `attachments` are
        keyed by each field's custom_id; each attachment is a placeholder screenshot."""
        body: dict[str, Any] = {"user_id": str(user_id), "values": values}
        if attachments:
            body["attachments"] = {key: [{"filename": "scoreboard.png"}] for key in attachments}
        return dict(self._call("POST", "interactions/modal", json=body))
