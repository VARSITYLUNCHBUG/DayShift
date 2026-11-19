"""Settings, read once from the environment."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field

from discord_sim.snowflake import MAX_SEED_USERS

DEFAULT_CORS_ORIGINS = (
    "http://localhost:18091",
    "http://127.0.0.1:18091",
    "http://localhost:5174",
    "http://127.0.0.1:5174",
)


@dataclass(frozen=True)
class Config:
    host: str = "0.0.0.0"
    port: int = 8090
    # The bot token the sim accepts. "*" accepts any non-empty token.
    bot_token: str = "sim-token"
    # Base URL for attachment and gateway URLs. Empty: built from each request's Host header, so
    # the bot (http://discord-sim:8090) and your host shell (http://127.0.0.1:18090) both get
    # URLs they can reach.
    public_url: str = ""
    seed_users: int = 0
    guild_name: str = "Draft Sim"
    bot_name: str = "DayShift"
    # Seconds the bot has to answer an interaction, as on Discord. 0 turns the check off.
    interaction_ack_seconds: float = 3.0
    # Seconds the interaction token stays valid for followups and edits.
    interaction_token_seconds: float = 15 * 60
    # Mirror Discord's validation of message bodies (component limits, content with V2, ...).
    strict: bool = True
    # Whether the application has the Message Content privileged intent.
    message_content_intent: bool = False
    cors_origins: tuple[str, ...] = field(default=DEFAULT_CORS_ORIGINS)
    log_size: int = 5_000

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> Config:
        env = os.environ if env is None else env
        seed_users = int(env.get("SIM_SEED_USERS", "0"))
        if not 0 <= seed_users <= MAX_SEED_USERS:
            raise SystemExit(f"SIM_SEED_USERS must be between 0 and {MAX_SEED_USERS}.")
        origins = env.get("SIM_CORS_ORIGINS")
        return cls(
            host=env.get("SIM_HOST", cls.host),
            port=int(env.get("SIM_PORT", str(cls.port))),
            bot_token=env.get("SIM_BOT_TOKEN", cls.bot_token),
            public_url=env.get("SIM_PUBLIC_URL", "").rstrip("/"),
            seed_users=seed_users,
            guild_name=env.get("SIM_GUILD_NAME", cls.guild_name),
            bot_name=env.get("SIM_BOT_NAME", cls.bot_name),
            interaction_ack_seconds=float(env.get("SIM_INTERACTION_ACK_SECONDS", "3")),
            interaction_token_seconds=float(env.get("SIM_INTERACTION_TOKEN_SECONDS", "900")),
            strict=_flag(env.get("SIM_STRICT", "true")),
            message_content_intent=_flag(env.get("SIM_MESSAGE_CONTENT_INTENT", "false")),
            cors_origins=(
                tuple(o.strip() for o in origins.split(",") if o.strip())
                if origins is not None
                else DEFAULT_CORS_ORIGINS
            ),
            log_size=int(env.get("SIM_LOG_SIZE", "5000")),
        )

    def token_ok(self, token: str) -> bool:
        return bool(token) and (self.bot_token == "*" or token == self.bot_token)


def _flag(value: str) -> bool:
    return value.strip().lower() in {"1", "true", "yes", "on"}
