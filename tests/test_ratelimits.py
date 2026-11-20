"""Long reset windows must not be confused with exhausted quotas."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import discord
import pytest

from bot.client import DayShiftBot
from bot.ratelimits import QuotaAwareRatelimit


def test_a_waiter_uses_available_quota_when_the_first_response_arrives() -> None:
    async def scenario() -> None:
        bucket = QuotaAwareRatelimit(60)
        await bucket.acquire()
        task = asyncio.create_task(bucket.acquire())
        await asyncio.sleep(0)
        assert len(bucket._pending_requests) == 1
        bucket.update(
            SimpleNamespace(
                headers={
                    "X-Ratelimit-Limit": "2000",
                    "X-Ratelimit-Remaining": "1996",
                    "X-Ratelimit-Reset-After": "86400",
                }
            )
        )
        await bucket.__aexit__(None, None, None)
        await asyncio.wait_for(task, 2.0)
        assert bucket.remaining == 1995 and bucket.outgoing == 1
        assert not bucket._pending_requests
        await bucket.__aexit__(None, None, None)
        assert bucket.outgoing == 0

    asyncio.run(scenario())


@pytest.mark.parametrize("waiters", [1, 3])
def test_waiting_requests_raise_when_the_first_response_exhausts_a_long_window(
    waiters: int,
) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unhandled = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        bucket = QuotaAwareRatelimit(60)
        await bucket.acquire()  # First request: the quota headers haven't arrived yet.
        tasks = [asyncio.create_task(bucket.acquire()) for _ in range(waiters)]
        await asyncio.sleep(0)
        assert len(bucket._pending_requests) == waiters
        bucket.update(
            SimpleNamespace(
                headers={
                    "X-Ratelimit-Limit": "2000",
                    "X-Ratelimit-Remaining": "0",
                    "X-Ratelimit-Reset-After": "86400",
                }
            )
        )
        await bucket.__aexit__(None, None, None)
        replies = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2.0)
        assert all(isinstance(reply, discord.RateLimited) for reply in replies)
        assert bucket.remaining == 0 and bucket.outgoing == 0
        assert not bucket._pending_requests
        await asyncio.sleep(0)
        assert not unhandled

    asyncio.run(scenario())


@pytest.mark.parametrize("after_wake", [False, True])
def test_cancelling_a_waiter_removes_it_and_consumes_any_racing_error(after_wake: bool) -> None:
    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        unhandled = []
        loop.set_exception_handler(lambda _loop, context: unhandled.append(context))
        bucket = QuotaAwareRatelimit(60)
        await bucket.acquire()
        task = asyncio.create_task(bucket.acquire())
        await asyncio.sleep(0)
        assert len(bucket._pending_requests) == 1
        if after_wake:
            bucket.expires = loop.time() + 86400
            await bucket.__aexit__(None, None, None)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not bucket._pending_requests
        await asyncio.sleep(0)
        assert not unhandled

    asyncio.run(scenario())


def test_a_long_window_with_remaining_tokens_is_usable() -> None:
    async def scenario() -> None:
        bucket = QuotaAwareRatelimit(60)
        bucket.limit = 2000
        bucket.remaining = 1996
        bucket.reset_after = 81000
        bucket.expires = asyncio.get_running_loop().time() + 81000
        async with bucket:
            assert bucket.remaining == 1995
        async with bucket:
            assert bucket.remaining == 1994
        assert bucket.outgoing == 0

    asyncio.run(scenario())


def test_spending_the_last_token_does_not_reset_a_long_quota_early() -> None:
    async def scenario() -> None:
        bucket = QuotaAwareRatelimit(60)
        bucket.limit = 2000
        bucket.remaining = 1
        bucket.reset_after = 81000
        bucket.expires = asyncio.get_running_loop().time() + 81000
        async with bucket:
            pass
        assert bucket.remaining == 0
        expiry = bucket.expires
        with pytest.raises(discord.RateLimited):
            await bucket.acquire()
        assert bucket.remaining == 0 and bucket.expires == expiry

    asyncio.run(scenario())


def test_pending_requests_can_use_returned_quota_in_a_long_window() -> None:
    async def scenario() -> None:
        bucket = QuotaAwareRatelimit(60)
        bucket.remaining = 3
        bucket.outgoing = 1
        bucket.reset_after = 81000
        bucket.expires = asyncio.get_running_loop().time() + 81000
        waiter = asyncio.get_running_loop().create_future()
        bucket._pending_requests.append(waiter)
        await bucket.__aexit__(None, None, None)
        await waiter  # No false RateLimited exception merely because reset is distant.

    asyncio.run(scenario())


def test_a_waiter_gets_quota_that_frees_up_while_others_are_in_flight() -> None:
    """Quota returns with requests still out (tokens <= 0 but remaining > 0): the waiter takes
    it at once, rather than spinning on a timeout after the window expires."""

    async def scenario() -> None:
        loop = asyncio.get_running_loop()
        bucket = QuotaAwareRatelimit(60)
        bucket.limit = 5
        bucket.remaining = 0
        bucket.outgoing = 4
        bucket.expires = loop.time() + 0.05
        task = asyncio.create_task(bucket.acquire())
        await asyncio.sleep(0)
        assert len(bucket._pending_requests) == 1
        bucket.remaining = 1  # A response came back: min(header, limit - outgoing).
        await bucket.__aexit__(None, None, None)  # outgoing 3, so tokens = 1 - 3.
        await asyncio.wait_for(task, 0.5)
        assert bucket.remaining == 0 and bucket.outgoing == 4

    asyncio.run(scenario())


def test_an_exhausted_short_window_waits_before_resetting() -> None:
    async def scenario() -> None:
        bucket = QuotaAwareRatelimit(60)
        bucket.limit = 2
        bucket.remaining = 0
        bucket.expires = asyncio.get_running_loop().time() + 0.01
        await bucket._refresh()
        assert bucket.remaining == 2

    asyncio.run(scenario())


def test_each_bot_uses_the_corrected_factory_and_retains_the_wait_cap() -> None:
    async def scenario() -> None:
        bot = DayShiftBot()
        bucket = bot.http.get_ratelimit("test-route")
        assert isinstance(bucket, QuotaAwareRatelimit)
        assert bot.http.get_ratelimit("test-route") is bucket
        assert bot.http.max_ratelimit_timeout == 60
        await bot.close()

    asyncio.run(scenario())
