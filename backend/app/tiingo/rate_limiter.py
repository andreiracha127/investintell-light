"""Asyncio-safe token-bucket rate limiter with sliding-window hard caps.

Usage::

    limiter = TokenBucketLimiter(
        rate_per_sec=2.0,
        burst=10,
        hourly_cap=9000,
        daily_cap=90000,
    )
    await limiter.acquire()   # call before every Tiingo request
"""

import asyncio
import time
from collections import deque
from collections.abc import Callable
from typing import Any

from app.tiingo.exceptions import TiingoRateLimitError


class TokenBucketLimiter:
    """Token-bucket limiter with sliding-window hourly and daily hard caps.

    Args:
        rate_per_sec: Token refill rate (tokens added per second).
        burst: Maximum token capacity (allows short bursts).
        hourly_cap: Hard ceiling on requests in any rolling 3600-second window.
            When reached, ``acquire()`` raises ``TiingoRateLimitError`` immediately
            rather than waiting — the caller decides how to handle it.
        daily_cap: Hard ceiling on requests in any rolling 86400-second window.
        time_func: Callable returning the current monotonic time in seconds.
            Defaults to ``time.monotonic``.  Inject a fake clock in tests to
            avoid real sleeps.
    """

    def __init__(
        self,
        rate_per_sec: float,
        burst: int,
        hourly_cap: int,
        daily_cap: int,
        time_func: Callable[[], float] = time.monotonic,
    ) -> None:
        self._rate = rate_per_sec
        self._burst = float(burst)
        self._hourly_cap = hourly_cap
        self._daily_cap = daily_cap
        self._time_func = time_func

        self._tokens: float = float(burst)
        self._last_refill: float = time_func()

        # Sliding-window queues: store timestamps of each acquisition.
        self._hourly_window: deque[float] = deque()
        self._daily_window: deque[float] = deque()

        self._lock: asyncio.Lock = asyncio.Lock()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _refill(self) -> None:
        """Refill tokens based on elapsed time since last call (called under lock)."""
        now = self._time_func()
        elapsed = now - self._last_refill
        self._tokens = min(self._burst, self._tokens + elapsed * self._rate)
        self._last_refill = now

    def _evict_old(self, now: float) -> None:
        """Drop timestamps outside the sliding windows (called under lock)."""
        hour_boundary = now - 3600.0
        day_boundary = now - 86400.0
        while self._hourly_window and self._hourly_window[0] <= hour_boundary:
            self._hourly_window.popleft()
        while self._daily_window and self._daily_window[0] <= day_boundary:
            self._daily_window.popleft()

    def _check_caps(self, now: float) -> None:
        """Raise TiingoRateLimitError if either hard cap is already reached."""
        if len(self._hourly_window) >= self._hourly_cap:
            raise TiingoRateLimitError(
                f"Tiingo hourly cap of {self._hourly_cap} requests reached. "
                "Wait until the oldest request falls out of the 1-hour window."
            )
        if len(self._daily_window) >= self._daily_cap:
            raise TiingoRateLimitError(
                f"Tiingo daily cap of {self._daily_cap} requests reached. "
                "Wait until the oldest request falls out of the 24-hour window."
            )

    def _record(self, now: float) -> None:
        """Record an acquisition timestamp in both sliding windows."""
        self._hourly_window.append(now)
        self._daily_window.append(now)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def acquire(self) -> None:
        """Wait until a token is available, then consume it.

        Raises:
            TiingoRateLimitError: If the hourly or daily hard cap is reached.
        """
        async with self._lock:
            now = self._time_func()
            self._evict_old(now)
            self._check_caps(now)

            # Refill and wait if no token available.
            self._refill()
            while self._tokens < 1.0:
                wait = (1.0 - self._tokens) / self._rate
                # Release the lock while sleeping so other coroutines can check.
                self._lock.release()
                try:
                    await asyncio.sleep(wait)
                finally:
                    await self._lock.acquire()
                self._refill()

            self._tokens -= 1.0
            now = self._time_func()
            self._record(now)

    # ------------------------------------------------------------------
    # Introspection (for tests / monitoring)
    # ------------------------------------------------------------------

    @property
    def hourly_count(self) -> int:
        """Number of acquisitions in the current 1-hour sliding window."""
        now = self._time_func()
        self._evict_old(now)
        return len(self._hourly_window)

    @property
    def daily_count(self) -> int:
        """Number of acquisitions in the current 24-hour sliding window."""
        now = self._time_func()
        self._evict_old(now)
        return len(self._daily_window)

    # Convenience so callers can do ``async with limiter:`` if desired.
    async def __aenter__(self) -> "TokenBucketLimiter":
        await self.acquire()
        return self

    async def __aexit__(self, *args: Any) -> None:
        pass
