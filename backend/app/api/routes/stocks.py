"""Stock endpoints: GET /stocks/{ticker}/prices and /stocks/{ticker}/analysis.

DB-first contract: these routes never talk to Tiingo directly. They call the
ingestion service (the only sanctioned Tiingo path) to guarantee the cache is
warm and fresh, then serve from the eod_prices table.

Error mapping (fail loud, never silently empty):
- unknown ticker                      -> 404
- Tiingo rate limited                 -> 503
- Tiingo auth misconfiguration        -> 502 (no detail leak)
- Tiingo server / bad response        -> 502
- cold-ticker cap exceeded            -> 422
- inverted dates / oversized window   -> 422
- insufficient history for analysis   -> 422
"""

import datetime as dt
import logging
import re
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.news import ensure_news
from app.ingestion.service import (
    HISTORY_FLOOR,
    ColdTickerCapExceededError,
    ensure_eod_data,
)
from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.models.news_item import NewsItem
from app.schemas.analysis import RangeKey, StockAnalysisResponse
from app.schemas.news import NewsArticle, NewsResponse
from app.schemas.prices import PricePoint, PriceSeriesResponse
from app.services.stock_analysis import (
    StockAnalysisError,
    assemble_analysis,
    build_adj_close_series,
    build_price_frame,
    lookback_pad_days,
)
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import (
    TiingoAuthError,
    TiingoBadResponseError,
    TiingoError,
    TiingoNotFoundError,
    TiingoRateLimitError,
    TiingoServerError,
)

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 365

# Sanity bound for ticker path segments on endpoints that do not 404 on
# unknown tickers (news): alphanumeric plus "." and "-", at most 10 chars.
_TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,10}$")

# Visible-range presets: calendar days subtracted from the last available
# trading day. "MAX" is resolved to the first available date instead.
RANGE_DAYS: dict[str, int] = {"1M": 30, "6M": 182, "1Y": 365, "5Y": 1826}

router = APIRouter(prefix="/stocks", tags=["stocks"])


async def _ensure_eod_or_http_error(
    session: AsyncSession,
    client: TiingoClient,
    symbols: list[str],
    start: dt.date,
    end: dt.date,
) -> None:
    """Run ``ensure_eod_data`` and map service/Tiingo errors to HTTP errors."""
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

    await _ensure_eod_or_http_error(session, client, [symbol], start, end)

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


# ---------------------------------------------------------------------------
# Analysis endpoint
# ---------------------------------------------------------------------------


async def _select_date_bounds(
    session: AsyncSession, ticker: str
) -> tuple[dt.date | None, dt.date | None]:
    """Return (min_date, max_date) available for *ticker* in eod_prices."""
    result = await session.execute(
        select(func.min(EodPrice.date), func.max(EodPrice.date)).where(
            EodPrice.ticker == ticker
        )
    )
    first, last = result.one()
    return first, last


async def _select_ohlcv_rows(
    session: AsyncSession, ticker: str, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float, float, float, float, int, float]]:
    """Read (date, open, high, low, close, volume, adj_close) tuples for [start, end]."""
    result = await session.execute(
        select(
            EodPrice.date,
            EodPrice.open,
            EodPrice.high,
            EodPrice.low,
            EodPrice.close,
            EodPrice.volume,
            EodPrice.adj_close,
        )
        .where(EodPrice.ticker == ticker, EodPrice.date >= start, EodPrice.date <= end)
        .order_by(EodPrice.date)
    )
    return list(result.tuples().all())


async def _select_adj_close_rows(
    session: AsyncSession, ticker: str, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float]]:
    """Read (date, adj_close) tuples for [start, end]."""
    result = await session.execute(
        select(EodPrice.date, EodPrice.adj_close)
        .where(EodPrice.ticker == ticker, EodPrice.date >= start, EodPrice.date <= end)
        .order_by(EodPrice.date)
    )
    return list(result.tuples().all())


async def _select_instrument_name(session: AsyncSession, ticker: str) -> str | None:
    """Read the instrument display name, if known."""
    return await session.scalar(select(Instrument.name).where(Instrument.ticker == ticker))


@router.get("/{ticker}/analysis", response_model=StockAnalysisResponse)
async def get_stock_analysis(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    range_: Annotated[
        RangeKey,
        Query(alias="range", description="Visible-range preset; MAX = full available history."),
    ] = "1Y",
    benchmark: Annotated[
        str, Query(description="Benchmark ticker for beta/correlation/relative series.")
    ] = "SPY",
    window: Annotated[
        int, Query(ge=10, le=252, description="Rolling window in TRADING days (10..252).")
    ] = 63,
) -> StockAnalysisResponse:
    """Render-ready analysis payload for one ticker — single call, no frontend finance.

    The visible range ends at the last trading day available for the ticker;
    rolling series are warmed up on a pre-range pad and sliced back to the
    visible range. All fractional fields are decimal fractions (0.05 = 5%).
    """
    symbol = ticker.strip().upper()
    bench_symbol = benchmark.strip().upper()

    # Ensure both symbols are warm. The service fetches full history for cold
    # tickers regardless of this window (informational — see service docstring).
    today = dt.date.today()
    ensure_start = (
        HISTORY_FLOOR if range_ == "MAX" else today - dt.timedelta(days=RANGE_DAYS[range_])
    )
    symbols = [symbol] if bench_symbol == symbol else [symbol, bench_symbol]
    await _ensure_eod_or_http_error(session, client, symbols, ensure_start, today)

    first_date, last_date = await _select_date_bounds(session, symbol)
    if first_date is None or last_date is None:
        raise HTTPException(status_code=404, detail=f"No price data available for {symbol}.")

    # Resolve the visible window, then pad backwards so rolling windows are
    # warm from the first visible day (pad feeds rolling stats ONLY).
    end = last_date
    start = first_date if range_ == "MAX" else end - dt.timedelta(days=RANGE_DAYS[range_])
    query_start = start - dt.timedelta(days=lookback_pad_days(window))

    asset_rows = await _select_ohlcv_rows(session, symbol, query_start, end)
    bench_rows = await _select_adj_close_rows(session, bench_symbol, query_start, end)
    name = await _select_instrument_name(session, symbol)

    try:
        return assemble_analysis(
            build_price_frame(asset_rows),
            build_adj_close_series(bench_rows),
            ticker=symbol,
            name=name,
            benchmark=bench_symbol,
            range_key=range_,
            window=window,
            start=start,
            end=end,
            max_candles=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# News endpoint
# ---------------------------------------------------------------------------


async def _select_news_rows(
    session: AsyncSession, ticker: str, limit: int
) -> Sequence[NewsItem]:
    """Read news rows tagged with *ticker*, newest first, bounded by *limit*."""
    result = await session.execute(
        select(NewsItem)
        .where(NewsItem.tickers.contains([ticker]))
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    )
    return result.scalars().all()


def _raise_news_fetch_error(exc: TiingoError) -> None:
    """Map a Tiingo news-fetch failure to HTTP, mirroring the other endpoints."""
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


@router.get("/{ticker}/news", response_model=NewsResponse)
async def get_ticker_news(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    limit: Annotated[int, Query(ge=1, le=50, description="Max articles returned.")] = 20,
) -> NewsResponse:
    """Per-ticker news, newest first — DB-first with a declared degrade path.

    Degrade decision (deliberate, documented): news is a SECONDARY panel.  If
    the Tiingo refresh fails but the DB holds cached articles, serve them with
    ``stale=true`` and log the error — a declared degradation, NOT a silent
    fallback.  If the refresh fails and the cache is empty, fail loud with the
    usual 503/502 mapping.

    Unknown tickers do not 404 here: Tiingo's news feed has no per-ticker
    existence check, and "no news" is a legitimate ``count=0`` response.  The
    ticker format is sanity-checked (alphanumeric + ".-", at most 10 chars)
    to reject absurd path segments with 422.
    """
    symbol = ticker.strip().upper()
    if not _TICKER_PATTERN.fullmatch(symbol):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid ticker {ticker!r}: expected 1-10 characters from "
                "A-Z, 0-9, '.', '-'."
            ),
        )

    stale = False
    try:
        await ensure_news(session, client, symbol, limit=get_settings().news_fetch_limit)
    except TiingoError as exc:
        rows = await _select_news_rows(session, symbol, limit)
        if not rows:
            _raise_news_fetch_error(exc)
        logger.warning(
            "News refresh for %s failed (%s: %s) — serving %d cached articles "
            "with stale=true.",
            symbol,
            type(exc).__name__,
            exc,
            len(rows),
        )
        stale = True
    else:
        rows = await _select_news_rows(session, symbol, limit)

    return NewsResponse(
        ticker=symbol,
        count=len(rows),
        stale=stale,
        items=[NewsArticle.model_validate(row) for row in rows],
    )
