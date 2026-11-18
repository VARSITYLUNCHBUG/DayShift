"""The league's state as gauges: the queue, live matches and the effect outbox.

Three small queries, run at most once every `CACHE_SECONDS` however often Prometheus scrapes, so
scraping never adds real load to the database. Only the web process exports these, so each series
exists once however many bot processes run.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from datetime import timedelta

from django.db.models import Count, Min, Q
from prometheus_client.core import GaugeMetricFamily, Metric
from prometheus_client.registry import Collector

from league.domain.engine import TIMED
from league.models import Match, OutboxEffect, QueueEntry
from league.models.outbox import EffectStatus
from league.services.common import now

logger = logging.getLogger(__name__)

CACHE_SECONDS = 10.0
# A deadline this long past and still not fired means the scheduler isn't keeping up.
OVERDUE_SECONDS = 30
# Failed effects are kept for good (prune_finished leaves them for a person to look at), so an
# all-time count would only ever grow. The gauge counts the ones that failed in this window.
FAILED_WINDOW = timedelta(hours=24)
OUTBOX_STATES = ("due", "scheduled", "failed")


def _families() -> dict[str, GaugeMetricFamily]:
    return {
        "up": GaugeMetricFamily(
            "draftbot_league_metrics_up", "1 when the league gauges were read from the database."
        ),
        "queue": GaugeMetricFamily("draftbot_queue_players", "Players waiting in a queue."),
        "matches": GaugeMetricFamily(
            "draftbot_matches_live",
            "Matches in a timed phase, by status and kind.",
            labels=("status", "kind"),
        ),
        "overdue": GaugeMetricFamily(
            "draftbot_deadlines_overdue",
            f"Live matches whose deadline passed over {OVERDUE_SECONDS} s ago without firing.",
        ),
        "outbox": GaugeMetricFamily(
            "draftbot_outbox_effects",
            "Outbox effects by state: due now, scheduled for later, or failed for good in the"
            " last 24 hours.",
            labels=("state",),
        ),
        "oldest": GaugeMetricFamily(
            "draftbot_outbox_oldest_due_seconds",
            "How long the oldest due effect has waited. 0 when none is due.",
        ),
    }


def read() -> list[Metric]:
    """Query the database for every gauge."""
    moment = now()
    families = _families()
    families["queue"].add_metric([], QueueEntry.objects.count())

    late = moment - timedelta(seconds=OVERDUE_SECONDS)
    overdue = 0
    rows = (
        Match.objects.filter(status__in=TIMED)
        .values("status", "kind")
        .annotate(live=Count("id"), late=Count("id", filter=Q(deadline_at__lt=late)))
    )
    for row in rows:
        families["matches"].add_metric([row["status"], row["kind"]], row["live"])
        overdue += row["late"]
    families["overdue"].add_metric([], overdue)

    pending_due = Q(status=EffectStatus.PENDING, run_after__lte=moment)
    recently_failed = Q(status=EffectStatus.FAILED, done_at__gte=moment - FAILED_WINDOW)
    live = OutboxEffect.objects.filter(Q(status=EffectStatus.PENDING) | recently_failed)
    outbox = live.aggregate(
        due=Count("id", filter=pending_due),
        scheduled=Count("id", filter=Q(status=EffectStatus.PENDING, run_after__gt=moment)),
        failed=Count("id", filter=recently_failed),
        oldest=Min("run_after", filter=pending_due),
    )
    for state in OUTBOX_STATES:
        families["outbox"].add_metric([state], outbox[state])
    oldest = outbox["oldest"]
    families["oldest"].add_metric([], (moment - oldest).total_seconds() if oldest else 0.0)

    families["up"].add_metric([], 1)
    return list(families.values())


class DomainCollector(Collector):
    """Serves `read()`'s gauges, cached for `cache_seconds`. A failed read isn't cached."""

    def __init__(
        self,
        cache_seconds: float = CACHE_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache_seconds = cache_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._cached: list[Metric] = []
        self._read_at: float | None = None

    def describe(self) -> list[Metric]:
        # The registry checks these names for clashes when the collector is registered. A registry
        # with auto_describe would otherwise call collect() for them, and query the database.
        return list(_families().values())

    def collect(self) -> list[Metric]:
        with self._lock:
            moment = self._clock()
            if self._read_at is not None and moment - self._read_at < self.cache_seconds:
                return self._cached
            try:
                self._cached = read()
            except Exception:
                logger.exception("Couldn't read the league gauges")
                failed = _families()["up"]
                failed.add_metric([], 0)
                return [failed]
            self._read_at = moment
            return self._cached
