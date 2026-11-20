"""Where a click's time goes: waiting for the database thread, running there, and the effects.

Each sample is a duration in seconds under a name such as `db.wait` or `effect.run:render_board`.
They are kept in memory, a bounded window per name, and summarised (count, median, 95th
percentile, max) when the bot logs them, then forgotten. Nothing is stored: it is for reading a
burst in the logs and comparing a change before and after, not for history.

Samples are added from the database thread and the event loop, so the window is locked.
"""

from __future__ import annotations

import math
import threading
from collections import defaultdict, deque

# The samples a name keeps between summaries. Enough for a busy minute; older ones drop off.
WINDOW = 2000

_lock = threading.Lock()
_samples: defaultdict[str, deque[float]] = defaultdict(lambda: deque(maxlen=WINDOW))


def record(name: str, seconds: float) -> None:
    with _lock:
        _samples[name].append(seconds)


def _percentile(ordered: list[float], fraction: float) -> float:
    """Nearest rank, so a reported time is one that really happened."""
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def summary(reset: bool = True) -> dict[str, dict[str, float]]:
    """{name: {count, p50_ms, p95_ms, max_ms}}, for every name with samples. Empties the window."""
    with _lock:
        taken = {name: sorted(window) for name, window in _samples.items() if window}
        if reset:
            _samples.clear()
    return {
        name: {
            "count": len(ordered),
            "p50_ms": round(_percentile(ordered, 0.5) * 1000, 1),
            "p95_ms": round(_percentile(ordered, 0.95) * 1000, 1),
            "max_ms": round(ordered[-1] * 1000, 1),
        }
        for name, ordered in sorted(taken.items())
    }
