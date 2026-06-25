"""Persisted-portfolio endpoints (F4): CRUD, enriched overview, aggregated news.

Distinct from ``app.api.routes.portfolio`` (the ad-hoc, no-persistence
analysis router).  DB-first contract, same as everywhere: routes never call
Tiingo for historical EOD data on the request path; prices are served from
local tables populated by backfill/worker jobs. Routes are thin: SQL and the
overview math live in ``app.services.portfolio_crud``.

Error mapping (fail loud, never silently empty):
- portfolio / position not found            -> 404
- ticker without local price/fund coverage  -> 404
- duplicate portfolio name                  -> 409
- validation (name/ticker/quantity/price)   -> 422
- news fetch failed with empty cache        -> 502/503; with cache -> 200 stale=true
"""

import datetime as dt
import hashlib
import logging
from collections.abc import Mapping, Sequence
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api._shared import raise_news_fetch_error
from app.core.auth import CurrentUser, get_current_user
from app.core.cache import portfolio_response_cache, response_cache_version
from app.core.config import get_settings
from app.core.datalake import get_datalake_session
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.news import ensure_news
from app.models.news_item import NewsItem
from app.schemas._tickers import normalize_ticker
from app.schemas.lookthrough import (
    ExposureTreeNode as ExposureTreeNodeOut,
)
from app.schemas.lookthrough import (
    PortfolioLookthroughResponse,
    UnexpandedPosition,
    build_dimensions,
)
from app.schemas.news import NewsArticle
from app.schemas.portfolios import (
    PortfolioCreate,
    PortfolioListItem,
    PortfolioNavPoint,
    PortfolioNavResponse,
    PortfolioNewsResponse,
    PortfolioOut,
    PortfolioOverviewResponse,
    PortfolioPatch,
    PortfolioTransactionCreate,
    PortfolioTransactionOut,
    PositionBody,
    PositionOut,
)
from app.services import lookthrough, portfolio_crud, portfolio_ledger
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoError

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/portfolios",
    tags=["portfolios"],
    dependencies=[Depends(get_current_user)],
)


def _owner_cache_token(owner_sub: str) -> str:
    return hashlib.sha256(owner_sub.encode("utf-8")).hexdigest()[:16]


def _portfolio_cache_prefix(owner_sub: str, portfolio_id: int) -> str:
    return (
        f"portfolio:{response_cache_version()}:"
        f"{_owner_cache_token(owner_sub)}:{portfolio_id}:"
    )


def _portfolio_cache_key(
    request: Request, owner_sub: str, portfolio_id: int, suffix: str
) -> str:
    query = "&".join(sorted(request.url.query.split("&"))) if request.url.query else ""
    return f"{_portfolio_cache_prefix(owner_sub, portfolio_id)}{suffix}:{request.url.path}?{query}"


async def _cached_private_response(key: str) -> Response | None:
    cached = await portfolio_response_cache.get(key)
    if cached is None:
        return None
    body, media_type = cached
    return Response(
        content=body,
        media_type=media_type,
        headers={"x-cache-private": "hit", "Cache-Control": "private, no-store"},
    )


async def _store_private_response(key: str, body: bytes) -> Response:
    await portfolio_response_cache.set(
        key,
        body,
        "application/json",
        get_settings().portfolio_cache_ttl_seconds,
    )
    return Response(
        content=body,
        media_type="application/json",
        headers={"x-cache-private": "miss", "Cache-Control": "private, no-store"},
    )


async def _invalidate_portfolio_cache(owner_sub: str, portfolio_id: int) -> None:
    await portfolio_response_cache.delete_prefix(
        _portfolio_cache_prefix(owner_sub, portfolio_id)
    )


def _normalize_ticker_or_422(ticker: str) -> str:
    try:
        return normalize_ticker(ticker, "ticker")
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


async def _require_local_trade_tickers(
    session: AsyncSession,
    tickers: Sequence[str],
) -> None:
    if not tickers:
        return
    symbols = sorted(set(tickers))
    nav_fund_tickers = await _select_nav_priced_fund_tickers(session, symbols)
    eod_candidates = [ticker for ticker in symbols if ticker not in nav_fund_tickers]
    if not eod_candidates:
        return
    eod_tickers = await portfolio_crud.select_tickers_with_eod(session, eod_candidates)
    missing = [ticker for ticker in eod_candidates if ticker not in eod_tickers]
    if missing:
        raise HTTPException(
            status_code=404,
            detail=(
                "No local price or fund coverage for: "
                f"{', '.join(missing)}. Run the EOD backfill before using these tickers."
            ),
        )


def _is_etf_taxonomy(
    taxonomy: Mapping[str, portfolio_crud.PositionTaxonomy], ticker: str
) -> bool:
    tax = taxonomy.get(ticker)
    return bool(tax and (tax.fund_type or "").lower() == "etf")


async def _select_nav_priced_fund_tickers(
    session: AsyncSession, tickers: Sequence[str]
) -> set[str]:
    """Fund tickers that should use NAV snapshots instead of traded closes."""
    if not tickers:
        return set()
    fund_tickers = await portfolio_crud.select_fund_tickers(session, tickers)
    if not fund_tickers:
        return set()
    taxonomy = await portfolio_crud.resolve_position_taxonomy(session, list(fund_tickers))
    return {
        ticker
        for ticker in fund_tickers
        if not _is_etf_taxonomy(taxonomy, ticker)
    }


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


@router.post("", response_model=PortfolioOut, status_code=201)
async def create_portfolio(
    payload: PortfolioCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioOut:
    """Create a portfolio with optional initial positions.

    Position tickers must already exist in local EOD/fund coverage. Missing
    coverage fails loud before anything is persisted.
    """
    if payload.positions:
        await _require_local_trade_tickers(
            session, [p.ticker for p in payload.positions]
        )
    try:
        portfolio = await portfolio_crud.create_portfolio(
            session, payload, user.sub, user.org_id
        )
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return PortfolioOut.model_validate(portfolio)


@router.get("", response_model=list[PortfolioListItem])
async def list_portfolios(
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[PortfolioListItem]:
    """List portfolios (id order), hard-capped at the service's LIST_HARD_CAP."""
    rows = await portfolio_crud.list_portfolios(session, user.sub)
    return [PortfolioListItem.model_validate(row) for row in rows]


@router.get("/{portfolio_id}", response_model=PortfolioOut)
async def get_portfolio(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioOut:
    """One portfolio with its positions (sorted by ticker)."""
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    return PortfolioOut.model_validate(portfolio)


@router.patch("/{portfolio_id}", response_model=PortfolioOut)
async def patch_portfolio(
    portfolio_id: int,
    payload: PortfolioPatch,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioOut:
    """Partially update name and/or cash."""
    try:
        provided = payload.model_fields_set
        portfolio = await portfolio_crud.update_portfolio(
            session,
            portfolio_id,
            user.sub,
            name=payload.name,
            cash=payload.cash,
            inception_date=(
                payload.inception_date
                if "inception_date" in provided
                else portfolio_crud.UNSET
            ),
        )
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    await _invalidate_portfolio_cache(user.sub, portfolio_id)
    return PortfolioOut.model_validate(portfolio)


@router.delete("/{portfolio_id}", status_code=204)
async def delete_portfolio(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Delete a portfolio; its positions cascade away at the DB level."""
    deleted = await portfolio_crud.delete_portfolio(session, portfolio_id, user.sub)
    if not deleted:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    await _invalidate_portfolio_cache(user.sub, portfolio_id)


# ---------------------------------------------------------------------------
# Position upsert / delete (inline editing)
# ---------------------------------------------------------------------------


@router.put("/{portfolio_id}/positions/{ticker}", response_model=PositionOut)
async def put_position(
    portfolio_id: int,
    ticker: str,
    payload: PositionBody,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PositionOut:
    """Upsert one position.

    INSERT path validates that the ticker already has local EOD/fund coverage;
    the UPDATE path deliberately does not re-check coverage — the ticker was
    already accepted when the position was created.

    F8.6b: the body optionally carries basis/commission/trade_date (manual
    fill registration). Fields absent from the body keep the stored values
    on UPDATE; on INSERT basis defaults to 'reference'.
    """
    symbol = _normalize_ticker_or_422(ticker)
    if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    provided = payload.model_fields_set
    position = await portfolio_crud.get_position(session, portfolio_id, symbol)
    if position is None:
        # NAV-priced funds/classes are valid local positions. ETFs remain
        # traded tickers, so they still require local EOD closes.
        nav_fund_tickers = await _select_nav_priced_fund_tickers(session, [symbol])
        if symbol not in nav_fund_tickers:
            await _require_local_trade_tickers(session, [symbol])
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
    await _invalidate_portfolio_cache(user.sub, portfolio_id)
    return PositionOut.model_validate(position)


@router.delete("/{portfolio_id}/positions/{ticker}", status_code=204)
async def delete_position(
    portfolio_id: int,
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> None:
    """Delete one position; 404 covers both a missing portfolio and a missing ticker."""
    symbol = _normalize_ticker_or_422(ticker)
    deleted = await portfolio_crud.delete_position(session, portfolio_id, symbol, user.sub)
    if not deleted:
        raise HTTPException(
            status_code=404,
            detail=f"Position {symbol} not found in portfolio {portfolio_id}.",
        )
    await _invalidate_portfolio_cache(user.sub, portfolio_id)


# ---------------------------------------------------------------------------
# Transaction ledger + NAV
# ---------------------------------------------------------------------------


@router.get(
    "/{portfolio_id}/transactions",
    response_model=list[PortfolioTransactionOut],
)
async def list_portfolio_transactions(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> list[PortfolioTransactionOut]:
    """List immutable buy/sell ledger events for a portfolio."""
    if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    rows = await portfolio_ledger.list_transactions(session, portfolio_id)
    return [PortfolioTransactionOut.model_validate(row) for row in rows]


@router.post(
    "/{portfolio_id}/transactions",
    response_model=PortfolioTransactionOut,
    status_code=201,
)
async def create_portfolio_transaction(
    portfolio_id: int,
    payload: PortfolioTransactionCreate,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioTransactionOut:
    """Append a real buy/sell event and update the current position snapshot."""
    if not await portfolio_crud.portfolio_exists(session, portfolio_id, user.sub):
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    await _require_local_trade_tickers(session, [payload.ticker])
    try:
        row = await portfolio_ledger.create_transaction(session, portfolio_id, payload)
        await portfolio_ledger.materialize_portfolio_nav(session, portfolio_id)
        await session.commit()
    except portfolio_ledger.InsufficientPositionError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except portfolio_ledger.MissingLedgerPriceDataError as exc:
        await session.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except portfolio_ledger.PortfolioNotFoundError as exc:
        await session.rollback()
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    await _invalidate_portfolio_cache(user.sub, portfolio_id)
    return PortfolioTransactionOut.model_validate(row)


@router.get("/{portfolio_id}/nav", response_model=PortfolioNavResponse)
async def get_portfolio_nav(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    end_date: Annotated[dt.date | None, Query(description="Last NAV date.")] = None,
) -> PortfolioNavResponse:
    """Persisted transaction-aware NAV index, rebased to 100 at inception."""
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")
    rows = await portfolio_ledger.list_materialized_nav(
        session,
        portfolio_id,
        end_date=end_date,
    )
    return PortfolioNavResponse(
        portfolio_id=portfolio_id,
        inception_date=rows[0].nav_date if rows else portfolio.inception_date,
        points=[
            PortfolioNavPoint(
                date=row.nav_date,
                nav=row.nav,
                market_value=row.market_value,
                cash=row.cash,
                total_value=row.total_value,
            )
            for row in rows
        ],
    )


# ---------------------------------------------------------------------------
# Overview
# ---------------------------------------------------------------------------


@router.get("/{portfolio_id}/overview", response_model=PortfolioOverviewResponse)
async def get_portfolio_overview(
    portfolio_id: int,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
) -> PortfolioOverviewResponse | Response:
    """Render-ready position table with P&L and column-header aggregates (D6).

    Baseline prices come from the two most recent local eod_prices rows per
    traded ticker, or fund NAV rows for NAV-priced holdings. The payload also
    marks positions that may receive a frontend live-tick overlay. An empty
    portfolio is a legitimate 200 with zeroed/null aggregates.
    """
    cache_key = _portfolio_cache_key(request, user.sub, portfolio_id, "overview")
    cached = await _cached_private_response(cache_key)
    if cached is not None:
        return cached

    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
    if portfolio is None:
        raise HTTPException(status_code=404, detail=f"Portfolio {portfolio_id} not found.")

    tickers = [position.ticker for position in portfolio.positions]
    fund_tickers: set[str] = set()
    nav_fund_tickers: set[str] = set()
    taxonomy = await portfolio_crud.resolve_position_taxonomy(session, tickers)
    if tickers:
        fund_tickers = {
            ticker
            for ticker, position_taxonomy in taxonomy.items()
            if position_taxonomy.instrument_id is not None
        }
        # NAV-priced funds/classes use fund_nav. ETFs remain traded tickers:
        # if their local EOD rows are cold, they should fail like stocks.
        nav_fund_tickers = {
            ticker
            for ticker in fund_tickers
            if not _is_etf_taxonomy(taxonomy, ticker)
        }

    eod_tickers = [ticker for ticker in tickers if ticker not in nav_fund_tickers]
    closes = await portfolio_crud.select_last_two_closes(session, eod_tickers)
    names = await portfolio_crud.select_instrument_names(session, tickers)
    nav_tickers = list(nav_fund_tickers)
    if nav_tickers:
        closes.update(await portfolio_crud.select_last_two_navs(session, nav_tickers))
        fund_names = await portfolio_crud.select_fund_names(session, nav_tickers)
        names = {**fund_names, **names}
    try:
        rows, aggregates = portfolio_crud.build_overview(
            portfolio.positions,
            closes,
            names,
            cash=portfolio.cash,
            taxonomy_by_ticker=taxonomy,
            nav_tickers=set(nav_tickers),
        )
    except portfolio_crud.MissingPriceDataError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    payload = PortfolioOverviewResponse(
        id=portfolio.id,
        name=portfolio.name,
        positions=rows,
        aggregates=aggregates,
    )
    return await _store_private_response(cache_key, payload.model_dump_json().encode())


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
    user: Annotated[CurrentUser, Depends(get_current_user)],
    limit: Annotated[int, Query(ge=1, le=50, description="Max articles returned.")] = 20,
) -> PortfolioNewsResponse:
    """Aggregated news across all portfolio tickers, newest first.

    Staleness is checked per ticker but all stale tickers are refreshed with
    ONE combined Tiingo call (see ``ensure_news``).  Degrade path mirrors
    GET /stocks/{ticker}/news exactly: refresh failure with cached articles
    serves them with ``stale=true``; with an empty cache it fails loud.
    """
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
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


# ---------------------------------------------------------------------------
# Look-through (Frente C)
# ---------------------------------------------------------------------------


@router.get(
    "/{portfolio_id}/lookthrough", response_model=PortfolioLookthroughResponse
)
async def get_portfolio_lookthrough(
    portfolio_id: int,
    session: Annotated[AsyncSession, Depends(get_session)],
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
    user: Annotated[CurrentUser, Depends(get_current_user)],
    dimension: str | None = Query(
        default=None,
        description="Optional exposure dimension filter.",
    ),
    include_tree: bool = Query(
        default=False,
        description="Include bounded asset-class/issuer/security drilldown nodes.",
    ),
) -> PortfolioLookthroughResponse:
    """Exposição consolidada do portfólio atravessando os fundos (Frente C).

    DB-first: pesos vêm dos preços/NAVs já sincronizados localmente (sem
    fetch de preço no request — posição sem preço local é 409 explícito) e as exposições
    vêm das tabelas materializadas pelo worker ``nport_lookthrough`` no
    data-lake. Posições não atravessadas (ações, fundos sem materialização)
    ficam EXPLÍCITAS em ``unexpanded`` — nunca somem silenciosamente.
    """
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id, user.sub)
    if portfolio is None:
        raise HTTPException(
            status_code=404, detail=f"Portfolio {portfolio_id} not found."
        )
    if dimension is not None and dimension not in lookthrough.DIMENSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported dimension {dimension!r}.",
        )

    positions = list(portfolio.positions)
    tickers = [position.ticker for position in positions]
    series_by_ticker = await lookthrough.get_fund_series_by_ticker(
        session, tickers
    )
    closes = await portfolio_crud.select_last_two_closes(session, tickers)
    nav_tickers = [t for t in series_by_ticker if t not in closes]
    if nav_tickers:
        closes.update(
            await portfolio_crud.select_last_two_navs(session, nav_tickers)
        )

    missing = [p.ticker for p in positions if not closes.get(p.ticker)]
    if missing:
        raise HTTPException(
            status_code=409,
            detail=(
                "No local price data for: "
                f"{', '.join(sorted(missing))} — open the portfolio overview "
                "after the EOD backfill has populated prices."
            ),
        )

    market_values = {
        position.ticker: position.quantity * closes[position.ticker][0][1]
        for position in positions
    }
    cash = float(portfolio.cash)
    total_value = sum(market_values.values()) + cash
    cash_weight_pct = 100.0 * cash / total_value if total_value else 0.0

    series_ids = sorted(
        {series_by_ticker[t] for t in series_by_ticker}
    )
    lookthroughs = await lookthrough.fetch_many_lookthroughs(
        datalake, series_ids, dimension=dimension
    )

    weighted: list[tuple[float, lookthrough.SeriesLookthrough]] = []
    unexpanded: list[UnexpandedPosition] = []
    direct_position_weights: list[tuple[str, float]] = []
    unexpanded_fund_weights: list[tuple[str, str, float]] = []
    for position in positions:
        weight = (
            market_values[position.ticker] / total_value if total_value else 0.0
        )
        series_id = series_by_ticker.get(position.ticker)
        if series_id is None:
            direct_position_weights.append((position.ticker, weight))
            unexpanded.append(
                UnexpandedPosition(
                    ticker=position.ticker,
                    weight_pct=100.0 * weight,
                    reason="not_a_fund",
                )
            )
        elif series_id not in lookthroughs:
            unexpanded_fund_weights.append((position.ticker, series_id, weight))
            unexpanded.append(
                UnexpandedPosition(
                    ticker=position.ticker,
                    weight_pct=100.0 * weight,
                    reason="not_materialized",
                )
            )
        else:
            weighted.append((weight, lookthroughs[series_id]))

    rows, aggregates = lookthrough.consolidate_portfolio(weighted)
    series_taxonomy = (
        await lookthrough.get_fund_taxonomy_by_series(session, series_ids)
        if include_tree
        else {}
    )
    direct_holdings: list[lookthrough.DirectHolding] = []
    if include_tree and direct_position_weights:
        direct_tickers = [ticker for ticker, _ in direct_position_weights]
        direct_names = await portfolio_crud.select_instrument_names(
            session, direct_tickers
        )
        direct_taxonomy = await portfolio_crud.resolve_position_taxonomy(
            session, direct_tickers
        )
        direct_holdings = await lookthrough.resolve_direct_holdings(
            datalake,
            [
                lookthrough.DirectHoldingInput(
                    ticker=ticker,
                    label=direct_names.get(ticker),
                    weight_pct=100.0 * weight,
                    asset_class=direct_taxonomy.get(
                        ticker,
                        portfolio_crud.PositionTaxonomy("equity", None, None),
                    ).asset_class,
                    strategy_label=direct_taxonomy.get(
                        ticker,
                        portfolio_crud.PositionTaxonomy("equity", None, None),
                    ).strategy_label,
                )
                for ticker, weight in direct_position_weights
            ],
        )
    if include_tree and unexpanded_fund_weights:
        direct_holdings.extend(
            lookthrough.DirectHolding(
                key=series_id,
                label=(
                    series_taxonomy[series_id].label
                    if series_id in series_taxonomy
                    else ticker
                ),
                value_pct=100.0 * weight,
                asset_class=(
                    series_taxonomy[series_id].asset_class
                    if series_id in series_taxonomy
                    else None
                ),
                strategy_label=(
                    series_taxonomy[series_id].strategy_label
                    if series_id in series_taxonomy
                    else None
                ),
                leaf_kind="fund",
            )
            for ticker, series_id, weight in unexpanded_fund_weights
        )
    if include_tree and cash_weight_pct > 0.0:
        direct_holdings.append(
            lookthrough.DirectHolding(
                key="CASH",
                label="Cash",
                value_pct=cash_weight_pct,
                asset_class="cash",
                strategy_label=None,
                leaf_kind="cash",
            )
        )
    tree = (
        await lookthrough.build_portfolio_exposure_tree(
            datalake,
            weighted,
            series_taxonomy=series_taxonomy,
            taxonomy_loader=lambda child_series_ids: (
                lookthrough.get_fund_taxonomy_by_series(session, child_series_ids)
            ),
            direct_holdings=direct_holdings,
        )
        if include_tree
        else []
    )
    residual_position_weight_pct = 100.0 * (
        sum(weight for _, weight in direct_position_weights)
        + sum(weight for _, _, weight in unexpanded_fund_weights)
    )
    decomposed_weight_pct = min(
        100.0,
        max(
            0.0,
            aggregates.expanded_weight_pct
            + residual_position_weight_pct
            + cash_weight_pct,
        ),
    )
    return PortfolioLookthroughResponse(
        portfolio_id=portfolio.id,
        total_value=total_value,
        cash_weight_pct=cash_weight_pct,
        expanded_weight_pct=aggregates.expanded_weight_pct,
        sum_pct_total=decomposed_weight_pct,
        oldest_report_date=aggregates.oldest_report_date,
        n_funds_expanded=len(weighted),
        unexpanded=unexpanded,
        dimensions=build_dimensions(rows, only=dimension),
        tree=[
            ExposureTreeNodeOut(
                id=node.id,
                parent_id=node.parent_id,
                key=node.key,
                label=node.label,
                kind=node.kind,
                value_pct=node.value_pct,
            )
            for node in tree
        ],
    )
