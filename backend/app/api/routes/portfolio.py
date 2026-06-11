"""Portfolio endpoint: POST /portfolio/analysis (ad-hoc, no persistence).

DB-first contract, same as the stock routes: never talks to Tiingo directly —
it calls the ingestion service (via the shared error-mapping helper) so the
cache is warm, then serves from eod_prices.

Window resolution:
- ``end``   = the COMMON last date: min over (positions + benchmark) of each
  ticker's max available date.
- ``start`` = ``end`` minus the range preset; for MAX, the LATEST inception
  (max over tickers of each min date) — the full COMMON history. The
  benchmark participates so the NAV and the comparison series share the same
  window.

Error mapping (fail loud, never silently empty):
- request validation (weights/quantities/tickers/bounds)  -> 422 (Pydantic)
- unknown ticker / no price rows                           -> 404
- Tiingo rate limited                                      -> 503
- Tiingo auth misconfiguration / server error              -> 502
- cold-ticker cap exceeded                                 -> 422
- insufficient common history / oversized payload          -> 422
"""

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.stocks import (
    RANGE_DAYS,
    _ensure_eod_or_http_error,
    _select_adj_close_rows,
    _select_date_bounds,
)
from app.core.config import get_settings
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import HISTORY_FLOOR
from app.schemas.portfolio_analysis import (
    PortfolioAnalysisRequest,
    PortfolioAnalysisResponse,
)
from app.services.portfolio_analysis import assemble_portfolio_analysis
from app.services.stock_analysis import StockAnalysisError, build_adj_close_series
from app.tiingo.client import TiingoClient

router = APIRouter(prefix="/portfolio", tags=["portfolio"])


@router.post("/analysis", response_model=PortfolioAnalysisResponse)
async def analyze_portfolio(
    payload: PortfolioAnalysisRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> PortfolioAnalysisResponse:
    """Render-ready analysis payload for an ad-hoc portfolio — single call.

    Buy-and-hold replay (NAV, returns-based stats, benchmark comparison) plus
    covariance decomposition (risk contributions, diversification ratio,
    correlation matrix) — see ``app.analytics.portfolio`` for the two-views
    semantics. All fractional fields are decimal fractions (0.05 = 5%).
    """
    tickers = [position.ticker for position in payload.positions]
    bench_symbol = payload.benchmark
    symbols = tickers + ([] if bench_symbol in tickers else [bench_symbol])

    # Ensure every symbol is warm (cold tickers get full history; the cap may
    # raise 422 with an actionable message — see the ingestion service).
    today = dt.date.today()
    ensure_start = (
        HISTORY_FLOOR
        if payload.range == "MAX"
        else today - dt.timedelta(days=RANGE_DAYS[payload.range])
    )
    await _ensure_eod_or_http_error(session, client, symbols, ensure_start, today)

    # Resolve the common window across positions AND benchmark.
    first_dates: dict[str, dt.date] = {}
    last_dates: dict[str, dt.date] = {}
    for symbol in symbols:
        first, last = await _select_date_bounds(session, symbol)
        if first is None or last is None:
            raise HTTPException(
                status_code=404, detail=f"No price data available for {symbol}."
            )
        first_dates[symbol] = first
        last_dates[symbol] = last

    end = min(last_dates.values())
    if payload.range == "MAX":
        start = max(first_dates.values())  # the LATEST inception — common history
    else:
        start = end - dt.timedelta(days=RANGE_DAYS[payload.range])

    series_by_ticker = {
        ticker: build_adj_close_series(
            await _select_adj_close_rows(session, ticker, start, end)
        )
        for ticker in tickers
    }
    benchmark_series = build_adj_close_series(
        await _select_adj_close_rows(session, bench_symbol, start, end)
    )

    weights = (
        {p.ticker: p.weight for p in payload.positions if p.weight is not None}
        if payload.mode == "weights"
        else None
    )
    quantities = (
        {p.ticker: p.quantity for p in payload.positions if p.quantity is not None}
        if payload.mode == "quantities"
        else None
    )

    try:
        return assemble_portfolio_analysis(
            series_by_ticker,
            benchmark_series,
            mode=payload.mode,
            weights=weights,
            quantities=quantities,
            benchmark=bench_symbol,
            range_key=payload.range,
            max_points=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
