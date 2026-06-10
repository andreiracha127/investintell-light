"""Price-series endpoint: GET /stocks/{ticker}/prices.

DB-first contract: this route never talks to Tiingo. It calls the ingestion
service (the only sanctioned Tiingo path) to guarantee the cache is warm and
fresh, then serves the series from the eod_prices table.

Error mapping (fail loud, never silently empty):
- unknown ticker                      -> 404
- Tiingo rate limited                 -> 503
- Tiingo auth misconfiguration        -> 502 (no detail leak)
- Tiingo server / bad response        -> 502
- cold-ticker cap exceeded            -> 422
- inverted dates / oversized window   -> 422
"""

import datetime as dt
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import ColdTickerCapExceededError, ensure_eod_data
from app.models.eod_price import EodPrice
from app.schemas.prices import PricePoint, PriceSeriesResponse
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoBadResponseError,
    TiingoNotFoundError,
    TiingoRateLimitError,
    TiingoServerError,
)

DEFAULT_WINDOW_DAYS = 365

router = APIRouter(prefix="/stocks", tags=["stocks"])


async def _select_price_rows(
    session: AsyncSession,
    ticker: str,
    start: dt.date,
    end: dt.date,
    limit: int,
) -> Sequence[EodPrice]:
    """Read price rows for [start, end] ordered by date, bounded by *limit*."""
    result = await session.execute(
        select(EodPrice)
        .where(EodPrice.ticker == ticker, EodPrice.date >= start, EodPrice.date <= end)
        .order_by(EodPrice.date)
        .limit(limit)
    )
    return result.scalars().all()


@router.get("/{ticker}/prices", response_model=PriceSeriesResponse)
async def get_price_series(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    start_date: Annotated[dt.date | None, Query(description="Defaults to end_date - 365d")] = None,
    end_date: Annotated[dt.date | None, Query(description="Defaults to today")] = None,
) -> PriceSeriesResponse:
    """Return the EOD price series for *ticker*, ingesting on demand if cold/stale."""
    end = end_date if end_date is not None else dt.date.today()
    start = start_date if start_date is not None else end - dt.timedelta(days=DEFAULT_WINDOW_DAYS)
    if start > end:
        raise HTTPException(
            status_code=422,
            detail=f"start_date ({start}) must be on or before end_date ({end}).",
        )

    symbol = ticker.strip().upper()

    try:
        await ensure_eod_data(session, client, [symbol], start, end)
    except ColdTickerCapExceededError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except TiingoNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Unknown ticker: {symbol}") from exc
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
            detail=f"Market data provider error while fetching {symbol}: {exc}",
        ) from exc

    max_points = get_settings().price_series_max_points
    rows = await _select_price_rows(session, symbol, start, end, max_points + 1)
    if len(rows) > max_points:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Window [{start}, {end}] for {symbol} exceeds the maximum of "
                f"{max_points} data points. Narrow start_date/end_date."
            ),
        )

    return PriceSeriesResponse(
        ticker=symbol,
        start_date=start,
        end_date=end,
        count=len(rows),
        prices=[PricePoint.model_validate(row) for row in rows],
    )
