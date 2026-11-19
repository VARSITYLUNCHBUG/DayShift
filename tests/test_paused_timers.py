"""A timer the dev tools parked ten years out reads "paused", never "in 10 years"."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from bot.renderers import style


def test_a_parked_deadline_reads_paused() -> None:
    parked = datetime.now(UTC) + timedelta(days=3650)
    assert style.relative(parked) == "(paused)"
    assert style.countdown(parked) == " ⌛ (paused)"
    soon = datetime.now(UTC) + timedelta(seconds=40)
    assert style.relative(soon) == f"<t:{int(soon.timestamp())}:R>"
    # A date (not a countdown) is shown as it is.
    assert style.relative(parked, "d") == f"<t:{int(parked.timestamp())}:d>"
