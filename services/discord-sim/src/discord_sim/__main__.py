"""`python -m discord_sim` (or `discord-sim`): serve the sim on SIM_HOST:SIM_PORT."""

from __future__ import annotations

import logging

from aiohttp import web

from discord_sim.app import create_app
from discord_sim.config import Config


class _QuietHealth(logging.Filter):
    """Container health checks hit /_sim/health every few seconds; keep them out of the log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return "/_sim/health" not in record.getMessage()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("aiohttp.access").addFilter(_QuietHealth())
    config = Config.from_env()
    logging.getLogger("discord_sim").info(
        "discord-sim on %s:%s (bot token %s)",
        config.host,
        config.port,
        "any" if config.bot_token == "*" else "set",
    )
    web.run_app(create_app(config), host=config.host, port=config.port, print=None)


if __name__ == "__main__":
    main()
