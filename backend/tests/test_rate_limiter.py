"""Tests for TokenBucketLimiter — no real sleeps, no real time."""

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
