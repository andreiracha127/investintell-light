"""Shared HTTP-error mapping helpers for stock and portfolio routes.

Extracted from ``app.api.routes.stocks`` so sibling routes can import from a
single canonical location without crossing private-underscore boundaries.

The only concern here is the mapping: service / Tiingo errors → HTTP status
codes.  All DB read helpers live in ``app.services._series``.
"""

import datetime as dt

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.service import ColdTickerCapExceededError, ensure_eod_data
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoBadResponseError,
    TiingoError,
    TiingoNotFoundError,
    TiingoRateLimitError,
    TiingoServerError,
)


async def ensure_eod_or_http_error(
    session: AsyncSession,
    client: TiingoClient,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
) -> None:
    """Run ``ensure_eod_data`` and map service/Tiingo errors to HTTP errors.

    This is the single canonical implementation; both the stocks and portfolio
    routes import from here.
    """
    label = ", ".join(symbols)
    try:
        await ensure_eod_data(session, client, symbols, start, end)
    except ColdTickerCapExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TiingoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {label}") from exc
    except TiingoRateLimitError as exc:
        raise HTTPException(
            status_code=503,
            detail="Market data provider rate limit reached — retry later.",
        ) from exc
    except TiingoAuthError as exc:
        # Server misconfiguration — do NOT leak token/auth details to the caller.
        raise HTTPException(
            status_code=502,
            detail="Market data provider is not configured on the server.",
        ) from exc
    except (TiingoServerError, TiingoBadResponseError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Market data provider error while fetching {label}: {exc}",
        ) from exc


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
