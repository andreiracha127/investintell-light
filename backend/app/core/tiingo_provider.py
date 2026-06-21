"""App-level Tiingo wiring: one limiter + one client per process.

The client is created LAZILY on first dependency use (not at startup) so the
app can boot without a TIINGO_TOKEN — /health must keep working on a
misconfigured box.  If created, the client is closed in main.py's lifespan
shutdown via ``provider.aclose()``.

Historical price/history/analysis routes must not depend on this provider.
They read local DB tables only. Provider-backed endpoints and batch jobs can
depend on ``get_tiingo_client`` explicitly when they are not serving historical
EOD on demand.
"""

import logging

from fastapi import HTTPException

from app.core.config import get_settings
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoAuthError
from app.tiingo.rate_limiter import TokenBucketLimiter

logger = logging.getLogger(__name__)


class TiingoProvider:
    """Holds the per-process TiingoClient singleton (lazily constructed)."""

    def __init__(self) -> None:
        self._client: TiingoClient | None = None

    def get_client(self) -> TiingoClient:
        """Return the singleton client, constructing it on first use.

        Raises:
            TiingoAuthError: If ``tiingo_token`` is unset (raised by the
                TiingoClient constructor — nothing is cached in that case).
        """
        if self._client is None:
            settings = get_settings()
            limiter = TokenBucketLimiter(
                rate_per_sec=settings.tiingo_rate_per_sec,
                burst=settings.tiingo_burst,
                hourly_cap=settings.tiingo_hourly_cap,
                daily_cap=settings.tiingo_daily_cap,
            )
            self._client = TiingoClient(
                token=settings.tiingo_token,
                limiter=limiter,
                base_url=settings.tiingo_base_url,
                timeout=settings.tiingo_timeout_seconds,
                max_retries=settings.tiingo_max_retries,
            )
        return self._client

    async def aclose(self) -> None:
        """Close the client if it was ever created (called at lifespan shutdown)."""
        if self._client is not None:
            client, self._client = self._client, None
            await client.aclose()


provider = TiingoProvider()


def get_tiingo_client() -> TiingoClient:
    """FastAPI dependency returning the process-wide TiingoClient.

    Maps a missing token to HTTP 502 (server misconfiguration) without leaking
    configuration details to the caller.
    """
    try:
        return provider.get_client()
    except TiingoAuthError:
        logger.exception("Tiingo client construction failed (token misconfiguration)")
        raise HTTPException(
            status_code=502,
            detail="Market data provider is not configured on the server.",
        ) from None
