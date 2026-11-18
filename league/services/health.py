"""Is the league keeping up? The bot's watchdog asks every minute (bot.client.Watchdog).

Only what a person needs to act on: timers that stopped firing, and Discord work that piles up.
An effect that fails for good is already logged as an error by the worker, and a dead process
shows up as its container's failed healthcheck and a missing ping, so neither is repeated here.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from django.db.models import Min

from league.models import Match, OutboxEffect
from league.services.common import now

# A deadline this far past and still not fired means the deadline loop isn't running.
OVERDUE = timedelta(seconds=60)
# The oldest due effect waiting this long means the effect worker isn't keeping up.
BACKLOG = timedelta(minutes=5)


def problems(at: datetime | None = None) -> list[str]:
    """What is wrong right now, one line each. Empty when all is well."""
    at = at or now()
    found = []
    overdue = Match.objects.overdue(at - OVERDUE).count()
    if overdue:
        found.append(f"{overdue} match timer(s) over a minute late: deadlines aren't firing")
    oldest = OutboxEffect.objects.due(at).aggregate(oldest=Min("run_after"))["oldest"]
    if oldest is not None and at - oldest > BACKLOG:
        minutes = int((at - oldest).total_seconds() // 60)
        found.append(f"Discord updates waiting {minutes} min: the effect worker isn't keeping up")
    return found
