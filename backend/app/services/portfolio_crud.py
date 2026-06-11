"""Thin persistence service for portfolios/positions (F4).

Routes own HTTP mapping; this module owns SQL plus the pure overview math.
Fail-loud contract:
- duplicate portfolio names raise ``DuplicatePortfolioNameError`` (routes → 409);
- "not found" is signalled by ``None``/``False`` returns (routes → 404);
- a position ticker without EOD rows raises ``MissingPriceDataError``
  (routes → 404, same message convention as the analysis endpoints).
"""

import datetime as dt
from collections.abc import Sequence
from typing import Any, Protocol, cast

from sqlalchemy import CursorResult, Row, delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.eod_price import EodPrice
from app.models.instrument import Instrument
from app.models.portfolio import Portfolio, Position
from app.schemas.portfolios import (
    OverviewAggregates,
    PortfolioCreate,
    PositionOverview,
)

# Hard cap on GET /portfolios — single-tenant, so no pagination, just a bound.
LIST_HARD_CAP = 100


class DuplicatePortfolioNameError(Exception):
    """Raised when a portfolio name violates the UNIQUE constraint."""


class MissingPriceDataError(Exception):
    """Raised when a position ticker has no EOD rows even after the ensure step."""


# ---------------------------------------------------------------------------
# Portfolio CRUD
# ---------------------------------------------------------------------------


async def create_portfolio(session: AsyncSession, payload: PortfolioCreate) -> Portfolio:
    """Insert a portfolio (and its initial positions); return it fully loaded.

    Raises DuplicatePortfolioNameError on a name conflict.  Duplicate tickers
    cannot reach the positions UNIQUE constraint — the schema rejects them
    with 422 — so an IntegrityError here can only be the name.
    """
    portfolio = Portfolio(
        name=payload.name,
        cash=payload.cash,
        positions=[
            Position(ticker=p.ticker, quantity=p.quantity, acq_price=p.acq_price)
            for p in payload.positions
        ],
    )
    session.add(portfolio)
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePortfolioNameError(
            f"A portfolio named {payload.name!r} already exists."
        ) from exc
    # Re-select so server-set defaults (timestamps) and the positions
    # collection are loaded without tripping lazy="raise".
    loaded = await get_portfolio(session, portfolio.id)
    if loaded is None:  # pragma: no cover — the row was just committed
        raise RuntimeError(f"Portfolio {portfolio.id} vanished after commit.")
    return loaded


async def get_portfolio(session: AsyncSession, portfolio_id: int) -> Portfolio | None:
    """Load one portfolio WITH its positions (explicit selectinload — lazy='raise')."""
    result = await session.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.positions))
        .where(Portfolio.id == portfolio_id)
    )
    return result.scalar_one_or_none()


async def list_portfolios(session: AsyncSession) -> Sequence[Row]:
    """List rows of (id, name, cash, position_count, created_at), id order, capped."""
    result = await session.execute(
        select(
            Portfolio.id,
            Portfolio.name,
            Portfolio.cash,
            func.count(Position.id).label("position_count"),
            Portfolio.created_at,
        )
        .outerjoin(Position)
        .group_by(Portfolio.id)
        .order_by(Portfolio.id)
        .limit(LIST_HARD_CAP)
    )
    return result.all()


async def update_portfolio(
    session: AsyncSession,
    portfolio_id: int,
    *,
    name: str | None,
    cash: float | None,
) -> Portfolio | None:
    """Apply a partial update; return the reloaded portfolio, or None if missing."""
    portfolio = await get_portfolio(session, portfolio_id)
    if portfolio is None:
        return None
    if name is not None:
        portfolio.name = name
    if cash is not None:
        portfolio.cash = cash
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePortfolioNameError(
            f"A portfolio named {name!r} already exists."
        ) from exc
    # Re-select so the DB-computed updated_at is reflected in the response.
    return await get_portfolio(session, portfolio_id)


async def delete_portfolio(session: AsyncSession, portfolio_id: int) -> bool:
    """Delete one portfolio; positions go with it via ON DELETE CASCADE."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(Portfolio).where(Portfolio.id == portfolio_id)),
    )
    await session.commit()
    return bool(result.rowcount)


async def portfolio_exists(session: AsyncSession, portfolio_id: int) -> bool:
    """True when the portfolio row exists (positions not loaded)."""
    found = await session.scalar(
        select(Portfolio.id).where(Portfolio.id == portfolio_id)
    )
    return found is not None


# ---------------------------------------------------------------------------
# Position upsert/delete
# ---------------------------------------------------------------------------


async def get_position(
    session: AsyncSession, portfolio_id: int, ticker: str
) -> Position | None:
    """Load one position by (portfolio_id, ticker), or None."""
    position: Position | None = await session.scalar(
        select(Position).where(
            Position.portfolio_id == portfolio_id, Position.ticker == ticker
        )
    )
    return position


async def insert_position(
    session: AsyncSession,
    portfolio_id: int,
    ticker: str,
    quantity: float,
    acq_price: float | None,
) -> Position:
    """Insert a new position (caller has already ensured the ticker exists)."""
    position = Position(
        portfolio_id=portfolio_id,
        ticker=ticker,
        quantity=quantity,
        acq_price=acq_price,
    )
    session.add(position)
    await session.commit()
    return position


async def update_position(
    session: AsyncSession,
    position: Position,
    quantity: float,
    acq_price: float | None,
) -> Position:
    """Overwrite quantity/acq_price on an existing position (PUT semantics)."""
    position.quantity = quantity
    position.acq_price = acq_price
    await session.commit()
    return position


async def delete_position(
    session: AsyncSession, portfolio_id: int, ticker: str
) -> bool:
    """Delete one position; False when no row matched."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Position).where(
                Position.portfolio_id == portfolio_id, Position.ticker == ticker
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


# ---------------------------------------------------------------------------
# Overview reads
# ---------------------------------------------------------------------------


async def select_last_two_closes(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, list[tuple[dt.date, float]]]:
    """The two most recent (date, close) rows per ticker, newest first.

    Raw ``close`` (not adj_close): last/prev power the quote-style price,
    change and market-value columns, which display traded prices.
    """
    if not tickers:
        return {}
    rn = (
        func.row_number()
        .over(partition_by=EodPrice.ticker, order_by=EodPrice.date.desc())
        .label("rn")
    )
    latest = (
        select(EodPrice.ticker, EodPrice.date, EodPrice.close, rn)
        .where(EodPrice.ticker.in_(tickers))
        .subquery()
    )
    result = await session.execute(
        select(latest.c.ticker, latest.c.date, latest.c.close)
        .where(latest.c.rn <= 2)
        .order_by(latest.c.ticker, latest.c.date.desc())
    )
    closes: dict[str, list[tuple[dt.date, float]]] = {}
    for ticker, date_, close in result.all():
        closes.setdefault(ticker, []).append((date_, close))
    return closes


async def select_instrument_names(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, str | None]:
    """Display names from the instruments cache (missing tickers are absent)."""
    if not tickers:
        return {}
    result = await session.execute(
        select(Instrument.ticker, Instrument.name).where(
            Instrument.ticker.in_(tickers)
        )
    )
    return dict(result.tuples().all())


# ---------------------------------------------------------------------------
# Overview math (pure — unit-tested directly)
# ---------------------------------------------------------------------------


class PositionLike(Protocol):
    """Structural view of a position — lets tests pass plain namespaces."""

    ticker: str
    quantity: float
    acq_price: float | None


def build_overview(
    positions: Sequence[PositionLike],
    closes_by_ticker: dict[str, list[tuple[dt.date, float]]],
    names_by_ticker: dict[str, str | None],
    cash: float,
) -> tuple[list[PositionOverview], OverviewAggregates]:
    """Assemble the render-ready overview rows + aggregates (no I/O).

    All fractional outputs are decimal fractions (0.05 = 5%), never 0-100.
    ``cost_basis`` is positive whenever present (quantity > 0 and acq_price > 0
    are API-enforced), so the pct divisions cannot hit zero.
    """
    rows: list[PositionOverview] = []
    for position in positions:
        closes = closes_by_ticker.get(position.ticker)
        if not closes:
            raise MissingPriceDataError(
                f"No price data available for {position.ticker}."
            )
        as_of, last_close = closes[0]
        prev_close = closes[1][1] if len(closes) > 1 else None
        change = last_close - prev_close if prev_close is not None else None
        change_pct = change / prev_close if prev_close is not None and change is not None else None
        market_value = position.quantity * last_close
        cost_basis = (
            position.quantity * position.acq_price
            if position.acq_price is not None
            else None
        )
        pnl = market_value - cost_basis if cost_basis is not None else None
        pnl_pct = pnl / cost_basis if pnl is not None and cost_basis is not None else None
        rows.append(
            PositionOverview(
                ticker=position.ticker,
                name=names_by_ticker.get(position.ticker),
                quantity=position.quantity,
                acq_price=position.acq_price,
                last_close=last_close,
                prev_close=prev_close,
                change=change,
                change_pct=change_pct,
                market_value=market_value,
                cost_basis=cost_basis,
                pnl=pnl,
                pnl_pct=pnl_pct,
                as_of=as_of,
            )
        )

    total_market_value = sum(row.market_value for row in rows)
    cost_values = [row.cost_basis for row in rows if row.cost_basis is not None]
    pnl_values = [row.pnl for row in rows if row.pnl is not None]
    total_cost_basis = sum(cost_values) if cost_values else None
    total_pnl = sum(pnl_values) if pnl_values else None
    total_pnl_pct = (
        total_pnl / total_cost_basis
        if total_pnl is not None and total_cost_basis is not None
        else None
    )
    aggregates = OverviewAggregates(
        total_market_value=total_market_value,
        total_cost_basis=total_cost_basis,
        total_pnl=total_pnl,
        total_pnl_pct=total_pnl_pct,
        cash=cash,
        total_value=total_market_value + cash,
        as_of=max(row.as_of for row in rows) if rows else None,
    )
    return rows, aggregates
