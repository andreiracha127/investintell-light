"""Shared HTTP-error mapping helpers for provider-backed auxiliary routes.

Historical EOD/NAV reads are DB-first. User-facing price/history/analysis
routes must read local tables and never call Tiingo REST on demand.
"""

from fastapi import HTTPException

from app.tiingo.exceptions import TiingoAuthError, TiingoError, TiingoRateLimitError


def raise_news_fetch_error(exc: TiingoError) -> None:
    """Map a Tiingo news-fetch failure to HTTP, mirroring the other endpoints.

    Single canonical implementation shared by the per-ticker and per-portfolio
    news routes (only called when the cache is empty — a non-empty cache is
    served with ``stale=true`` instead).
    """
    if isinstance(exc, TiingoRateLimitError):
        raise HTTPException(
            status_code=503,
            detail="News provider rate limit reached — retry later.",
        ) from exc
    if isinstance(exc, TiingoAuthError):
        # Server misconfiguration — do NOT leak token/auth details to the caller.
        raise HTTPException(
            status_code=502,
            detail="News provider is not configured on the server.",
        ) from exc
    raise HTTPException(
        status_code=502,
        detail=f"News provider error: {exc}",
    ) from exc
