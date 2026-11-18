"""The bot's Prometheus metrics, served on `METRICS_PORT` by the gateway and the scheduler.

Nothing here touches the database: the league's gauges (queue, live matches, outbox depth) come
from the web process, so they exist once however many bot processes run. A heartbeat's age is
`time() - draftbot_loop_heartbeat_timestamp_seconds`, and the scheduler's last tick is that series
for `loop="deadlines"`. Interactions that fail are logged as errors, so they show up in
`draftbot_log_errors_total` under the `bot.routing` and `bot.client` loggers.
"""

from __future__ import annotations

import logging
import math
from wsgiref.simple_server import WSGIServer

import discord
from django.conf import settings
from prometheus_client import (
    GC_COLLECTOR,
    PLATFORM_COLLECTOR,
    PROCESS_COLLECTOR,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    disable_created_metrics,
    start_http_server,
)

logger = logging.getLogger(__name__)

# Prometheus has no use for each series' `_created` twin.
disable_created_metrics()

# Its own registry, so whatever else the process imports (the web's metrics, say) stays out.
REGISTRY = CollectorRegistry()
for _collector in (PROCESS_COLLECTOR, PLATFORM_COLLECTOR, GC_COLLECTOR):
    REGISTRY.register(_collector)

LOOP_HEARTBEAT = Gauge(
    "draftbot_loop_heartbeat_timestamp_seconds",
    "When each background loop last went round.",
    ("loop",),
    registry=REGISTRY,
)
LOG_ERRORS = Counter(
    "draftbot_log_errors",
    "ERROR and CRITICAL log records, by logger.",
    ("logger",),
    registry=REGISTRY,
)
GATEWAY_LATENCY = Gauge(
    "draftbot_gateway_latency_seconds",
    "Discord gateway heartbeat latency. NaN until the first heartbeat.",
    registry=REGISTRY,
)
INTERACTIONS = Counter(
    "draftbot_interactions",
    "Interactions received, by type: clicks, slash commands and modals.",
    ("type",),
    registry=REGISTRY,
)
EFFECTS = Counter(
    "draftbot_effects",
    "Outbox effects run, by kind and outcome: done, skipped, retried or failed.",
    ("kind", "outcome"),
    registry=REGISTRY,
)
EFFECT_DURATION = Histogram(
    "draftbot_effect_duration_seconds",
    "Time an effect's Discord work took, whatever the outcome.",
    registry=REGISTRY,
)
TICK_DURATION = Histogram(
    "draftbot_deadline_tick_duration_seconds",
    "Time one deadline pass took. Its count is the number of passes.",
    registry=REGISTRY,
)
DEADLINES_FIRED = Counter(
    "draftbot_deadlines_fired",
    "Deadlines fired: phase timers, sub windows, swaps, scrims and the priority list.",
    registry=REGISTRY,
)


class ErrorCounter(logging.Handler):
    """Counts every ERROR record by logger, so a rate of errors can be graphed and alerted on."""

    def __init__(self) -> None:
        super().__init__(level=logging.ERROR)

    def emit(self, record: logging.LogRecord) -> None:
        LOG_ERRORS.labels(record.name).inc()


def serve(client: discord.Client | None = None) -> WSGIServer | None:
    """Start the metrics endpoint on a background thread. `METRICS_PORT=0` turns it off.

    Pass the gateway's client to export its latency."""
    logging.getLogger().addHandler(ErrorCounter())
    if client is not None:
        GATEWAY_LATENCY.set_function(lambda: _finite(client.latency))
    if not settings.METRICS_PORT:
        return None
    server, _thread = start_http_server(
        settings.METRICS_PORT, addr=settings.METRICS_ADDR, registry=REGISTRY
    )
    logger.info(
        "Serving metrics", extra={"addr": settings.METRICS_ADDR, "port": settings.METRICS_PORT}
    )
    return server


def _finite(value: float) -> float:
    return value if math.isfinite(value) else math.nan
