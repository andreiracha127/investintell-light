"""Stock endpoints: GET /stocks/{ticker}/prices and /stocks/{ticker}/analysis.

DB-first contract: request handlers never call Tiingo for historical EOD data.
Historical freshness is owned by out-of-band ingestion/backfill workers; route
requests read local tables only and return explicit missing-data errors when
the DB has not been populated.

Error mapping (fail loud, never silently empty):
- unknown ticker / no local price rows -> 404
- inverted dates / oversized window   -> 422
- insufficient history for analysis   -> 422
"""

import datetime as dt
import logging
import re
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import raise_news_fetch_error
from app.core.config import get_settings
from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.news import ensure_news
from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.models.news_item import NewsItem
from app.schemas.analysis import AnalysisHeader, RangeKey, StockAnalysisResponse
from app.schemas.market import HistoryBar, HistoryResponse, MarketOverviewResponse
from app.schemas.news import NewsArticle, NewsResponse
from app.schemas.prices import PricePoint, PriceSeriesResponse
from app.schemas.stock_holders import StockFundHoldersResponse, StockHoldersResponse
from app.schemas.timeseries import OhlcSeriesResponse
from app.services import market_overview
from app.services._series import (
    RANGE_DAYS,
)
from app.services._series import (
    select_adj_close_rows as _select_adj_close_rows,
)
from app.services._series import (
    select_adj_ohlcv_rows as _select_adj_ohlcv_rows,
)
from app.services._series import (
    select_date_bounds as _select_date_bounds,
)
from app.services.stock_analysis import (
    StockAnalysisError,
    assemble_analysis,
    assemble_analysis_sql,
    build_adj_close_series,
    build_price_frame,
    lookback_pad_days,
)
from app.services.stock_holders import (
    StockHoldersSourceError,
    fetch_stock_fund_holders,
    fetch_stock_holders,
)
from app.services.timeseries import (
    EOD_PRICE_INTERVAL,
    range_start,
    to_ms_ohlc,
)
from app.services.timeseries import (
    select_eod_ohlc as _select_eod_ohlc_impl,
)
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoError

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 365

# Sanity bound for ticker path segments on endpoints that do not 404 on
# unknown tickers (news): alphanumeric plus "." and "-", at most 10 chars.
_TICKER_PATTERN = re.compile(r"^[A-Z0-9.\-]{1,10}$")

router = APIRouter(prefix="/stocks", tags=["stocks"])


# Module-level alias so tests can monkeypatch the DB read independently of the
# service module's own binding.
_select_eod_ohlc = _select_eod_ohlc_impl


# ---------------------------------------------------------------------------
# Market overview (landing /stocks)
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=MarketOverviewResponse)
async def get_market_overview(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> MarketOverviewResponse:
    """Payload único da landing /stocks — leaders/setores das tabelas locais.

    Leaders e setores leem eod_prices ⋈ universe_constituents (pipeline batch
    F6.2); ficam tão frescos quanto o último backfill. Os 4 ETFs de índice
    também são lidos somente do banco local.
    """
    indices = await market_overview.fetch_index_rows(session)
    rows = await market_overview.fetch_overview_rows(session)
    ranked = market_overview.rank_overview(rows)
    return MarketOverviewResponse(universe_size=len(rows), indices=indices, **ranked)


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
    start_date: Annotated[dt.date | None, Query(description="Defaults to end_date - 365d")] = None,
    end_date: Annotated[dt.date | None, Query(description="Defaults to today")] = None,
) -> PriceSeriesResponse:
    """Return the local EOD price series for *ticker*."""
    end = end_date if end_date is not None else dt.date.today()
    start = start_date if start_date is not None else end - dt.timedelta(days=DEFAULT_WINDOW_DAYS)
    if start > end:
        raise HTTPException(
            status_code=422,
            detail=f"start_date ({start}) must be on or before end_date ({end}).",
        )

    symbol = ticker.strip().upper()

    max_points = get_settings().price_series_max_points
    rows = await _select_price_rows(session, symbol, start, end, max_points + 1)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data available for {symbol}.")
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


async def _select_latest_quote_rows(
    session: AsyncSession, ticker: str
) -> list[tuple[dt.date, float]]:
    """Read the latest two raw closes for the stock header strip."""
    result = await session.execute(
        select(EodPrice.date, EodPrice.close)
        .where(EodPrice.ticker == ticker)
        .order_by(EodPrice.date.desc())
        .limit(2)
    )
    return [(date, float(close)) for date, close in result.tuples().all()]


@router.get("/{ticker}/history", response_model=HistoryResponse)
async def get_stock_history(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    bars: Annotated[
        int, Query(ge=30, le=5000, description="Nº de barras diárias mais recentes.")
    ] = 760,
) -> HistoryResponse:
    """OHLCV diário ajustado no contrato do chart interativo ({t,o,h,l,c,v}).

    Resample semanal/mensal é client-side (engine). t = epoch ms UTC do pregão.
    """
    symbol = ticker.strip().upper()
    today = dt.date.today()
    # ~252 pregões/ano → 1.6 dias-calendário por barra cobre feriados com folga.
    start = today - dt.timedelta(days=int(bars * 1.6) + 10)

    rows = await _select_adj_ohlcv_rows(session, symbol, start, today)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data available for {symbol}.")
    rows = rows[-bars:]

    def _ms(d: dt.date) -> int:
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.UTC).timestamp() * 1000)

    return HistoryResponse(
        ticker=symbol,
        count=len(rows),
        bars=[
            HistoryBar(t=_ms(d), o=o, h=h, l=lo, c=c, v=int(v or 0))
            for d, o, h, lo, c, v in rows
        ],
    )


@router.get("/{ticker}/timeseries", response_model=OhlcSeriesResponse)
async def get_stock_timeseries(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    range_: Annotated[
        RangeKey, Query(alias="range", description="Visible range preset.")
    ] = "1Y",
) -> OhlcSeriesResponse:
    """Adjusted daily OHLC + volume in Highcharts Stock arrays.

    Every range reads the same DB-first daily CAGG; the range only changes the
    date floor. Historical ingestion is outside the request path.
    """
    symbol = ticker.strip().upper()
    today = dt.date.today()
    interval = EOD_PRICE_INTERVAL
    start = range_start(range_, today)
    rows = await _select_eod_ohlc(session, symbol, start)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data for {symbol}.")
    ohlc, volume = to_ms_ohlc(rows)
    return OhlcSeriesResponse(id=symbol, interval=interval, ohlc=ohlc, volume=volume)


async def _select_instrument_name(session: AsyncSession, ticker: str) -> str | None:
    """Read the instrument display name, if known."""
    return await session.scalar(select(Instrument.name).where(Instrument.ticker == ticker))


@router.get("/{ticker}/quote", response_model=AnalysisHeader)
async def get_stock_quote(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> AnalysisHeader:
    """Fast header payload for stock pages.

    This endpoint is intentionally tiny: it reads only the two latest raw EOD
    closes and the display name, so the LCP price can paint before the heavier
    analytics payload finishes.
    """
    symbol = ticker.strip().upper()
    rows = await _select_latest_quote_rows(session, symbol)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data available for {symbol}.")
    if len(rows) < 2:
        raise HTTPException(
            status_code=422,
            detail=f"Not enough price history for {symbol} to compute a one-day change.",
        )
    (last_date, last_close), (_, prev_close) = rows
    name = await _select_instrument_name(session, symbol)
    change = last_close - prev_close
    return AnalysisHeader(
        ticker=symbol,
        name=name,
        last_close=last_close,
        prev_close=prev_close,
        change=change,
        change_pct=change / prev_close,
        as_of=last_date,
    )


@router.get("/{ticker}/analysis", response_model=StockAnalysisResponse)
async def get_stock_analysis(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
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
        if get_settings().use_series_db_first:
            return await assemble_analysis_sql(
                session,
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
# Holders endpoint (Stocks → Holders tab)
# ---------------------------------------------------------------------------


@router.get("/{ticker}/holders", response_model=StockHoldersResponse)
async def get_stock_holders(
    ticker: str,
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> StockHoldersResponse:
    """Full 13F institutional holder list for one stock (latest period).

    Resolves ticker → CUSIP and returns every filer in the >$5bn universe that
    holds it — no curated filter, no row cap. `position_return` is reserved for
    a later step (needs prior-period history) and is null for now.
    """
    try:
        return await fetch_stock_holders(datalake, ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StockHoldersSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/{ticker}/holders/funds", response_model=StockFundHoldersResponse)
async def get_stock_fund_holders(
    ticker: str,
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> StockFundHoldersResponse:
    """Registered funds (N-PORT) holding the stock, grouped family → fund.

    The "by fund" view of the Holders tab: a registrant/trust parent with its
    funds as children (shares, market value, % of NAV). Names come from the SEC
    series-class crosswalk. Latest N-PORT period.
    """
    try:
        return await fetch_stock_fund_holders(datalake, ticker)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except StockHoldersSourceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


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
            raise_news_fetch_error(exc)
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
