"""Tests for TokenBucketLimiter — no real sleeps, no real time."""

import asyncio
from unittest.mock import patch

import pytest

from app.tiingo.exceptions import TiingoRateLimitError
from app.tiingo.rate_limiter import TokenBucketLimiter

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_fake_clock(start: float = 0.0) -> list[float]:
    """Return a mutable list [current_time] used as a fake monotonic clock."""
    return [start]


def fake_time_func(clock: list[float]) -> float:
    return clock[0]


# ---------------------------------------------------------------------------
# Token bucket: burst allows N immediate acquires
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_burst_allows_n_immediate_acquires() -> None:
    """With a burst of 5 and no time passing, 5 acquires should succeed without sleeping."""
    clock = make_fake_clock(0.0)
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        # Advance the fake clock when sleeping so limiter can refill tokens.
        clock[0] += seconds
        sleep_calls.append(seconds)

    limiter = TokenBucketLimiter(
        rate_per_sec=2.0,
        burst=5,
        hourly_cap=9000,
        daily_cap=90000,
        time_func=lambda: fake_time_func(clock),
    )

    with patch("asyncio.sleep", side_effect=fake_sleep):
        for _ in range(5):
            await limiter.acquire()

    # All 5 acquires should have happened without sleeping.
    assert sleep_calls == []


@pytest.mark.asyncio
async def test_next_acquire_after_burst_sleeps() -> None:
    """After exhausting burst tokens, the next acquire must sleep ~1/rate seconds."""
    clock = make_fake_clock(0.0)
    sleep_calls: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds
        sleep_calls.append(seconds)

    limiter = TokenBucketLimiter(
        rate_per_sec=2.0,
        burst=3,
        hourly_cap=9000,
        daily_cap=90000,
        time_func=lambda: fake_time_func(clock),
    )

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # Exhaust the burst.
        for _ in range(3):
            await limiter.acquire()
        # This one needs a token; rate is 2/s → need to wait ~0.5s.
        await limiter.acquire()

    assert len(sleep_calls) >= 1
    # Total sleep should be close to 0.5s (1 token / 2 tokens per second).
    assert abs(sum(sleep_calls) - 0.5) < 0.1


# ---------------------------------------------------------------------------
# Hourly hard-stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hourly_cap_raises_after_limit() -> None:
    """After hourly_cap acquisitions within the window, acquire must raise."""
    clock = make_fake_clock(0.0)

    limiter = TokenBucketLimiter(
        rate_per_sec=1000.0,
        burst=200,
        hourly_cap=5,
        daily_cap=90000,
        time_func=lambda: fake_time_func(clock),
    )

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    with patch("asyncio.sleep", side_effect=fake_sleep):
        for _ in range(5):
            # Refill burst between iterations to avoid token-bucket sleep.
            clock[0] += 0.001
            await limiter.acquire()

        with pytest.raises(TiingoRateLimitError, match="hourly cap"):
            await limiter.acquire()


@pytest.mark.asyncio
async def test_hourly_cap_releases_after_window_slides() -> None:
    """After the 1-hour window slides, old timestamps are evicted and acquires succeed."""
    clock = make_fake_clock(0.0)

    limiter = TokenBucketLimiter(
        rate_per_sec=1000.0,
        burst=200,
        hourly_cap=3,
        daily_cap=90000,
        time_func=lambda: fake_time_func(clock),
    )

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # Fill up the hourly cap.
        for _ in range(3):
            clock[0] += 0.001
            await limiter.acquire()

        # Confirm cap is hit.
        with pytest.raises(TiingoRateLimitError):
            await limiter.acquire()

        # Advance clock by 3601 seconds — all old timestamps fall out.
        clock[0] += 3601.0

        # Should succeed now.
        await limiter.acquire()


# ---------------------------------------------------------------------------
# Daily hard-stop
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_cap_raises_after_limit() -> None:
    """After daily_cap acquisitions, acquire must raise TiingoRateLimitError."""
    clock = make_fake_clock(0.0)

    limiter = TokenBucketLimiter(
        rate_per_sec=1000.0,
        burst=200,
        hourly_cap=9000,
        daily_cap=4,
        time_func=lambda: fake_time_func(clock),
    )

    async def fake_sleep(seconds: float) -> None:
        clock[0] += seconds

    with patch("asyncio.sleep", side_effect=fake_sleep):
        for _ in range(4):
            clock[0] += 0.001
            await limiter.acquire()

        with pytest.raises(TiingoRateLimitError, match="daily cap"):
            await limiter.acquire()


# ---------------------------------------------------------------------------
# Fix 2: Cap re-checked after token-wait sleep
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hourly_cap_enforced_after_token_wait() -> None:
    """Cap filled while waiting for a token must be caught when the loop re-checks.

    Setup: burst=2, rate=1/s (slow refill), hourly_cap=3.
    - Acquire 1 & 2 succeed immediately (consume both burst tokens; cap at 2/3).
    - Acquire 3: no tokens left → must sleep ~1 s to refill one token.
      Inside fake_sleep we directly append a third timestamp to the limiter's
      sliding windows (simulating another coroutine filling the cap while we
      sleep).  We also advance the clock enough to refill a token so the sleep
      itself completes — but NOT enough to evict any recorded timestamps.
    - On the next while-True iteration _check_caps fires (cap now 3/3 + the
      one just appended inside sleep = 3 ≥ hourly_cap) and raises.

    This directly exercises the post-sleep _check_caps call.
    """
    clock = make_fake_clock(100.0)
    sleep_calls: list[float] = []

    # We need a reference to the limiter inside fake_sleep — use a list cell.
    limiter_ref: list[TokenBucketLimiter] = []

    async def fake_sleep(seconds: float) -> None:
        sleep_calls.append(seconds)
        # Advance the clock enough to refill a token (rate=1 → 1s = 1 token).
        clock[0] += seconds
        # Simulate another coroutine consuming the last cap slot while we slept.
        lim = limiter_ref[0]
        lim._hourly_window.append(clock[0])
        lim._daily_window.append(clock[0])

    limiter = TokenBucketLimiter(
        rate_per_sec=1.0,
        burst=2,
        hourly_cap=3,
        daily_cap=9000,
        time_func=lambda: fake_time_func(clock),
    )
    limiter_ref.append(limiter)

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # Two immediate acquires using the burst tokens (cap now 2/3).
        await limiter.acquire()
        await limiter.acquire()

        # Third acquire: no token → sleeps → cap becomes 3/3 inside sleep →
        # post-sleep re-check raises.
        with pytest.raises(TiingoRateLimitError, match="hourly cap"):
            await limiter.acquire()

    assert len(sleep_calls) >= 1, "Expected at least one sleep before the cap raise"


# ---------------------------------------------------------------------------
# Fix 3: Cancellation safety — limiter not deadlocked after mid-wait cancel
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cancellation_mid_wait_does_not_deadlock_limiter() -> None:
    """A task cancelled while sleeping in acquire() must not deadlock the limiter.

    Protocol:
    1. Exhaust the burst so the next acquire() will need to sleep.
    2. Start a task that calls acquire() — it enters the sleep outside the lock.
    3. Cancel it immediately (we know it will be in the sleep because the lock
       is not held during the sleep in the new design).
    4. After cancellation, a fresh acquire() from the test coroutine must
       complete successfully (limiter not deadlocked or corrupted).
    """
    clock = make_fake_clock(0.0)
    # Flag set when fake_sleep is entered so we know the task reached the sleep.
    entered_sleep = False

    async def fake_sleep(seconds: float) -> None:
        nonlocal entered_sleep
        entered_sleep = True
        # Advance the fake clock but do NOT await anything (avoids re-entering
        # the patched sleep and causing recursion).  The CancelledError will be
        # raised at the next real await after this returns.
        clock[0] += seconds

    limiter = TokenBucketLimiter(
        rate_per_sec=2.0,
        burst=1,
        hourly_cap=9000,
        daily_cap=90000,
        time_func=lambda: fake_time_func(clock),
    )

    with patch("asyncio.sleep", side_effect=fake_sleep):
        # Exhaust the burst so the next acquire() will need to sleep.
        await limiter.acquire()

        # Start the waiting task.
        task = asyncio.create_task(limiter.acquire())

        # Cancel immediately — the task is either in its sleep or about to enter
        # it; either way CancelledError will be delivered at the next await.
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, Exception):
            pass

        # Advance clock so a fresh token is available.
        clock[0] += 1.0

        # A fresh acquire() must complete — proves the limiter is not deadlocked.
        await limiter.acquire()
