"""Persisted-portfolio endpoints (F4): CRUD, enriched overview, aggregated news.

Distinct from ``app.api.routes.portfolio`` (the ad-hoc, no-persistence
analysis router).  DB-first contract, same as everywhere: routes never talk to
Tiingo directly — the EOD ensure (shared error mapping) validates tickers and
warms the cache; reads are served from the tables.  Routes are thin: SQL and
the overview math live in ``app.services.portfolio_crud``.

Error mapping (fail loud, never silently empty):
- portfolio / position not found            -> 404
- ticker unknown to Tiingo (create/insert)  -> 404 (shared ensure mapping)
- duplicate portfolio name                  -> 409
- validation (name/ticker/quantity/price)   -> 422
- cold-ticker cap exceeded                  -> 422
- Tiingo rate limited / auth / server       -> 503 / 502 / 502
- news fetch failed with empty cache        -> 502/503; with cache -> 200 stale=true
"""

import datetime as dt
import logging
from collections.abc import Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import ensure_eod_or_http_error, raise_news_fetch_error
from app.core.config import get_settings
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.news import ensure_news
from app.models.news_item import NewsItem
from app.schemas._tickers import normalize_ticker
from app.schemas.news import NewsArticle
from app.schemas.portfolios import (
    PortfolioCreate,
    PortfolioListItem,
    PortfolioNewsResponse,
    PortfolioOut,
    PortfolioOverviewResponse,
    PortfolioPatch,
    PositionBody,
    PositionOut,
)
from app.services import portfolio_crud
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoError

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/portfolios", tags=["portfolios"])

# Window passed to the EOD ensure: informational only — the ingestion service
# fetches full history for cold tickers and refreshes incrementally for stale
# ones regardless of this window (see its fetch-window policy).
_ENSURE_WINDOW_DAYS = 30


def _ensure_window() -> tuple[dt.date, dt.date]:
    today = dt.date.today()
    return today - dt.timedelta(days=_ENSURE_WINDOW_DAYS), today


def _normalize_ticker_or_422(ticker: str) -> str:
    try:
        return normalize_ticker(ticker, "ticker")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=PortfolioOut, status_code=201)
async def create_portfolio(
    payload: PortfolioCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> PortfolioOut:
    """Create a portfolio with optional initial positions.

    Position tickers are validated against Tiingo via the EOD ensure — a typo
    fails loud (404) BEFORE anything is persisted — which also warms the EOD
    cache for the overview.
    """
    if payload.positions:
        start, end = _ensure_window()
        await ensure_eod_or_http_error(
            session, client, [p.ticker for p in payload.positions], start, end
        )
    try:
        portfolio = await portfolio_crud.create_portfolio(session, payload)
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PortfolioOut.model_validate(portfolio)


@router.get("", response_model=list[PortfolioListItem])
async def list_portfolios(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PortfolioListItem]:
    """List portfolios (id order), hard-capped at the service's LIST_HARD_CAP."""
    rows = await portfolio_crud.list_portfolios(session)
    return [PortfolioListItem.model_validate(row) for row in rows]


@router.get("/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioOut:
    """One portfolio with its positions (sorted by ticker)."""
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    return PortfolioOut.model_validate(portfolio)


@router.patch("/{portfolio_id}", response_model=PortfolioOut)
async def patch_portfolio(
    portfolio_id: int,
    payload: PortfolioPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioOut:
    """Partially update name and/or cash."""
    try:
        portfolio = await portfolio_crud.update_portfolio(
            session, portfolio_id, name=payload.name, cash=payload.cash
        )
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    return PortfolioOut.model_validate(portfolio)


@router.delete("/{portfolio_id}", status_code=204)
async def delete_portfolio(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete a portfolio; its positions cascade away at the DB level."""
    deleted = await portfolio_crud.delete_portfolio(session, portfolio_id)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")


# ---------------------------------------------------------------------------
# Position upsert / delete (inline editing)
# ---------------------------------------------------------------------------


@router.put("/{portfolio_id}/positions/{ticker}", response_model=PositionOut)
async def put_position(
    portfolio_id: int,
    ticker: str,
    payload: PositionBody,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> PositionOut:
    """Upsert one position.

    INSERT path validates the ticker against Tiingo (and warms the EOD cache);
    the UPDATE path deliberately does NOT re-ensure — the ticker was already
    validated when the position was created.

    F8.6b: the body optionally carries basis/commission/trade_date (manual
    fill registration). Fields absent from the body keep the stored values
    on UPDATE; on INSERT basis defaults to 'reference'.
    """
    symbol = _normalize_ticker_or_422(ticker)
    if not await portfolio_crud.portfolio_exists(session, portfolio_id):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    provided = payload.model_fields_set
    position = await portfolio_crud.get_position(session, portfolio_id, symbol)
    if position is None:
        # Fund tickers (synced funds/fund_classes tables) are valid positions
        # priced from fund_nav — they must NOT be validated against Tiingo
        # (F8.5; class tickers use the series NAV as a proxy, F8.6b).
        is_fund = bool(await portfolio_crud.select_fund_tickers(session, [symbol]))
        if not is_fund:
            start, end = _ensure_window()
            await ensure_eod_or_http_error(session, client, [symbol], start, end)
        position = await portfolio_crud.insert_position(
            session,
            portfolio_id,
            symbol,
            payload.quantity,
            payload.acq_price,
            basis=payload.basis or "reference",
            commission=payload.commission,
            trade_date=payload.trade_date,
        )
    else:
        position = await portfolio_crud.update_position(
            session,
            position,
            payload.quantity,
            payload.acq_price,
            basis=payload.basis,
            commission=(
                payload.commission
                if "commission" in provided
                else portfolio_crud.UNSET
            ),
            trade_date=(
                payload.trade_date
                if "trade_date" in provided
                else portfolio_crud.UNSET
            ),
        )
    return PositionOut.model_validate(position)


@router.delete("/{portfolio_id}/positions/{ticker}", status_code=204)
async def delete_position(
    portfolio_id: int,
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> None:
    """Delete one position; 404 covers both a missing portfolio and a missing ticker."""
    symbol = _normalize_ticker_or_422(ticker)
    deleted = await portfolio_crud.delete_position(session, portfolio_id, symbol)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Position {symbol} not found in portfolio {portfolio_id}.",
        )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/{portfolio_id}/overview", response_model=PortfolioOverviewResponse)
async def get_portfolio_overview(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> PortfolioOverviewResponse:
    """Render-ready position table with P&L and column-header aggregates (D6).

    Last/prev closes come from the two most recent eod_prices rows per ticker;
    the EOD ensure runs first so stale tickers are refreshed.  An empty
    portfolio is a legitimate 200 with zeroed/null aggregates.
    """
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")

    tickers = [position.ticker for position in portfolio.positions]
    fund_tickers: set[str] = set()
    if tickers:
        # Fund-aware pricing (F8.5): tickers known to the synced funds table
        # are priced from fund_nav and skipped by the Tiingo ensure — UNLESS
        # they already have eod_prices rows (pre-existing equity/ETF positions
        # keep their refresh + EOD pricing unchanged).
        fund_tickers = await portfolio_crud.select_fund_tickers(session, tickers)
        eod_known = await portfolio_crud.select_tickers_with_eod(session, tickers)
        ensure_tickers = [
            t for t in tickers if t not in fund_tickers or t in eod_known
        ]
        if ensure_tickers:
            start, end = _ensure_window()
            await ensure_eod_or_http_error(session, client, ensure_tickers, start, end)

    closes = await portfolio_crud.select_last_two_closes(session, tickers)
    names = await portfolio_crud.select_instrument_names(session, tickers)
    nav_tickers = [t for t in fund_tickers if t not in closes]
    if nav_tickers:
        closes.update(await portfolio_crud.select_last_two_navs(session, nav_tickers))
        fund_names = await portfolio_crud.select_fund_names(session, nav_tickers)
        names = {**fund_names, **names}
    try:
        rows, aggregates = portfolio_crud.build_overview(
            portfolio.positions, closes, names, cash=portfolio.cash
        )
    except portfolio_crud.MissingPriceDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return PortfolioOverviewResponse(
        id=portfolio.id,
        name=portfolio.name,
        positions=rows,
        aggregates=aggregates,
    )


# ---------------------------------------------------------------------------
# News (aggregate across portfolio tickers)
# ---------------------------------------------------------------------------


def build_news_overlap_select(tickers: Sequence[str], limit: int) -> Select:
    """SELECT news overlapping ANY of *tickers* (&&), newest first, bounded."""
    return (
        select(NewsItem)
        .where(NewsItem.tickers.overlap(list(tickers)))
        .order_by(NewsItem.published_at.desc())
        .limit(limit)
    )


async def _select_portfolio_news_rows(
    session: AsyncSession, tickers: Sequence[str], limit: int
) -> Sequence[NewsItem]:
    result = await session.execute(build_news_overlap_select(tickers, limit))
    return result.scalars().all()


@router.get("/{portfolio_id}/news", response_model=PortfolioNewsResponse)
async def get_portfolio_news(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    limit: Annotated[int, Query(ge=1, le=50, description="Max articles returned.")] = 20,
) -> PortfolioNewsResponse:
    """Aggregated news across all portfolio tickers, newest first.

    Staleness is checked per ticker but all stale tickers are refreshed with
    ONE combined Tiingo call (see ``ensure_news``).  Degrade path mirrors
    GET /stocks/{ticker}/news exactly: refresh failure with cached articles
    serves them with ``stale=true``; with an empty cache it fails loud.
    """
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")

    symbols = [position.ticker for position in portfolio.positions]
    if not symbols:
        return PortfolioNewsResponse(
            portfolio_id=portfolio.id, tickers=[], count=0, stale=False, items=[]
        )

    stale = False
    try:
        await ensure_news(session, client, symbols, limit=get_settings().news_fetch_limit)
    except TiingoError as exc:
        rows = await _select_portfolio_news_rows(session, symbols, limit)
        if not rows:
            raise_news_fetch_error(exc)
        logger.warning(
            "News refresh for portfolio %d (%s) failed (%s: %s) — serving %d "
            "cached articles with stale=true.",
            portfolio.id,
            ", ".join(symbols),
            type(exc).__name__,
            exc,
            len(rows),
        )
        stale = True
    else:
        rows = await _select_portfolio_news_rows(session, symbols, limit)

    return PortfolioNewsResponse(
        portfolio_id=portfolio.id,
        tickers=symbols,
        count=len(rows),
        stale=stale,
        items=[NewsArticle.model_validate(row) for row in rows],
    )
