"""The league gauges: what they count, and that a scrape costs a few queries at most every 10 s."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import pytest
from django.utils import timezone
from prometheus_client import CollectorRegistry

from league.models import Community, Match, OutboxEffect
from league.models.outbox import EffectStatus
from league.observability import domain
from league.observability.domain import DomainCollector
from league.services import queue
from tests.conftest import make_player


class Ticker:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


def scrape(
    collector: DomainCollector, name: str, labels: dict[str, str] | None = None
) -> float | None:
    registry = CollectorRegistry()
    registry.register(collector)
    return registry.get_sample_value(name, labels or {})


def test_registering_the_collector_never_queries_the_database() -> None:
    """No `db` fixture: a query here would fail the test."""
    CollectorRegistry(auto_describe=True).register(DomainCollector())


@pytest.mark.django_db
def test_the_gauges_count_the_queue_live_matches_and_the_outbox(
    league: Community, popped: Match
) -> None:
    queue.join(league.pk, make_player(99))
    OutboxEffect.objects.filter(match=popped).update(
        run_after=timezone.now() - timedelta(minutes=2)
    )
    effect = OutboxEffect.objects.filter(match=popped).first()
    assert effect is not None
    OutboxEffect.objects.filter(pk=effect.pk).update(
        status=EffectStatus.FAILED, done_at=timezone.now()
    )
    pending = OutboxEffect.objects.filter(status=EffectStatus.PENDING).count()
    collector = DomainCollector(cache_seconds=0)

    assert scrape(collector, "draftbot_league_metrics_up") == 1
    assert scrape(collector, "draftbot_queue_players") == 1
    live = {"status": popped.status, "kind": popped.kind}
    assert scrape(collector, "draftbot_matches_live", live) == 1
    assert scrape(collector, "draftbot_deadlines_overdue") == 0
    assert scrape(collector, "draftbot_outbox_effects", {"state": "due"}) == pending
    assert scrape(collector, "draftbot_outbox_effects", {"state": "failed"}) == 1
    assert scrape(collector, "draftbot_outbox_effects", {"state": "scheduled"}) == 0
    oldest = scrape(collector, "draftbot_outbox_oldest_due_seconds")
    assert oldest is not None and 110 < oldest < 600


@pytest.mark.django_db
def test_a_deadline_long_past_counts_as_overdue(popped: Match) -> None:
    Match.objects.filter(pk=popped.pk).update(deadline_at=timezone.now() - timedelta(minutes=1))
    assert scrape(DomainCollector(cache_seconds=0), "draftbot_deadlines_overdue") == 1


@pytest.mark.django_db
def test_failed_counts_only_the_last_24_hours(popped: Match) -> None:
    """Failed effects are never pruned, so an all-time count would only ever grow."""
    old, recent = OutboxEffect.objects.filter(match=popped)[:2]
    OutboxEffect.objects.filter(pk=old.pk).update(
        status=EffectStatus.FAILED, done_at=timezone.now() - timedelta(hours=25)
    )
    OutboxEffect.objects.filter(pk=recent.pk).update(
        status=EffectStatus.FAILED, done_at=timezone.now() - timedelta(hours=23)
    )
    collector = DomainCollector(cache_seconds=0)
    assert scrape(collector, "draftbot_outbox_effects", {"state": "failed"}) == 1


@pytest.mark.django_db
def test_finished_matches_and_an_empty_outbox_read_as_zero(league: Community) -> None:
    collector = DomainCollector(cache_seconds=0)
    assert scrape(collector, "draftbot_queue_players") == 0
    assert scrape(collector, "draftbot_outbox_effects", {"state": "due"}) == 0
    assert scrape(collector, "draftbot_outbox_oldest_due_seconds") == 0


@pytest.mark.django_db
def test_a_scrape_is_three_queries_and_is_then_cached(
    popped: Match, django_assert_num_queries: Any
) -> None:
    ticker = Ticker()
    collector = DomainCollector(cache_seconds=10, clock=ticker)
    with django_assert_num_queries(3):
        first = list(collector.collect())
    ticker.now = 9.9
    with django_assert_num_queries(0):
        assert list(collector.collect()) == first
    ticker.now = 10.0
    with django_assert_num_queries(3):
        collector.collect()


def test_a_failed_read_reports_down_and_is_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[int] = []

    def broken() -> list[Any]:
        calls.append(1)
        raise RuntimeError("database is down")

    monkeypatch.setattr(domain, "read", broken)
    collector = DomainCollector(cache_seconds=10, clock=Ticker())
    assert scrape(collector, "draftbot_league_metrics_up") == 0
    assert scrape(collector, "draftbot_queue_players") is None
    assert len(calls) == 2  # Not cached: the next scrape tries again.
