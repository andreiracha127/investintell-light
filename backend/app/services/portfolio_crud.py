"""Thin persistence service for portfolios/positions (F4).

Routes own HTTP mapping; this module owns SQL plus the pure overview math.
Fail-loud contract:
- duplicate portfolio names raise ``DuplicatePortfolioNameError`` (routes → 409);
- "not found" is signalled by ``None``/``False`` returns (routes → 404);
- a position ticker without EOD rows raises ``MissingPriceDataError``
  (routes → 404, same message convention as the analysis endpoints).
"""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any, NamedTuple, Protocol, cast

from sqlalchemy import CursorResult, Row, delete, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundClass, FundNav
from app.models.instrument import Instrument
from app.models.portfolio import Portfolio, Position
from app.optimizer import data as optimizer_data
from app.schemas.portfolios import (
    OverviewAggregates,
    PortfolioCreate,
    PositionBasis,
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


async def create_portfolio(
    session: AsyncSession,
    payload: PortfolioCreate,
    owner_sub: str,
    org_id: str | None,
    *,
    origin: str = "manual",
) -> Portfolio:
    portfolio = Portfolio(
        name=payload.name,
        cash=payload.cash,
        origin=origin,
        owner_sub=owner_sub,
        org_id=org_id,
        positions=[
            Position(
                ticker=p.ticker,
                quantity=p.quantity,
                acq_price=p.acq_price,
                basis=p.basis or "reference",
                commission=p.commission,
                trade_date=p.trade_date,
            )
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
    loaded = await get_portfolio(session, portfolio.id, owner_sub)
    if loaded is None:  # pragma: no cover — the row was just committed
        raise RuntimeError(f"Portfolio {portfolio.id} vanished after commit.")
    return loaded


async def get_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> Portfolio | None:
    """Load one OWNED portfolio WITH its positions (lazy='raise')."""
    result = await session.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.positions))
        .where(Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub)
    )
    return result.scalar_one_or_none()


async def list_portfolios(session: AsyncSession, owner_sub: str) -> Sequence[Row]:
    """List the caller's portfolios (id order), capped at LIST_HARD_CAP."""
    result = await session.execute(
        select(
            Portfolio.id,
            Portfolio.name,
            Portfolio.cash,
            func.count(Position.id).label("position_count"),
            Portfolio.created_at,
        )
        .outerjoin(Position)
        .where(Portfolio.owner_sub == owner_sub)
        .group_by(Portfolio.id)
        .order_by(Portfolio.id)
        .limit(LIST_HARD_CAP)
    )
    return result.all()


async def update_portfolio(
    session: AsyncSession,
    portfolio_id: int,
    owner_sub: str,
    *,
    name: str | None,
    cash: float | None,
) -> Portfolio | None:
    portfolio = await get_portfolio(session, portfolio_id, owner_sub)
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
    return await get_portfolio(session, portfolio_id, owner_sub)


async def delete_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> bool:
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Portfolio).where(
                Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def portfolio_exists(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> bool:
    found = await session.scalar(
        select(Portfolio.id).where(
            Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
        )
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
    *,
    basis: str = "reference",
    commission: float | None = None,
    trade_date: dt.date | None = None,
) -> Position:
    """Upsert a position via INSERT ... ON CONFLICT (portfolio_id, ticker) DO UPDATE.

    The route checks existence FIRST (get_position) to gate the Tiingo ensure
    call on the INSERT path only.  After ensure, this upsert collapses any
    concurrent INSERT race to last-write-wins instead of an unhandled
    IntegrityError → 500.

    NOTE: Core-level upserts bypass the ORM onupdate hook, so updated_at is
    set explicitly here (same rule documented on the model).
    """
    stmt = (
        pg_insert(Position)
        .values(
            portfolio_id=portfolio_id,
            ticker=ticker,
            quantity=quantity,
            acq_price=acq_price,
            basis=basis,
            commission=commission,
            trade_date=trade_date,
        )
        .on_conflict_do_update(
            index_elements=["portfolio_id", "ticker"],
            set_={
                "quantity": quantity,
                "acq_price": acq_price,
                "basis": basis,
                "commission": commission,
                "trade_date": trade_date,
                "updated_at": func.now(),
            },
        )
        .returning(Position)
    )
    result = await session.execute(stmt)
    await session.commit()
    row = result.scalar_one()
    return row


# Sentinel for "field absent from the PUT body" — None is a real value
# (clear the commission / trade_date), so it cannot double as the default.
UNSET: Any = object()


async def update_position(
    session: AsyncSession,
    position: Position,
    quantity: float,
    acq_price: float | None,
    *,
    basis: str | None = None,
    commission: float | None | Any = UNSET,
    trade_date: dt.date | None | Any = UNSET,
) -> Position:
    """Overwrite quantity/acq_price on an existing position (PUT semantics).

    F8.6b fill fields are OPTIONAL extensions of the PUT body: when absent
    the stored basis/commission/trade_date are left untouched (the default
    keeps the pre-F8.6b behavior); when present they overwrite.
    """
    position.quantity = quantity
    position.acq_price = acq_price
    if basis is not None:
        position.basis = basis
    if commission is not UNSET:
        position.commission = cast("Decimal | None", commission)
    if trade_date is not UNSET:
        position.trade_date = trade_date
    await session.commit()
    return position


async def delete_position(
    session: AsyncSession, portfolio_id: int, ticker: str, owner_sub: str
) -> bool:
    """Delete one position only if its portfolio belongs to owner_sub."""
    owned = select(Portfolio.id).where(
        Portfolio.id == portfolio_id, Portfolio.owner_sub == owner_sub
    )
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Position).where(
                Position.portfolio_id == portfolio_id,
                Position.ticker == ticker,
                Position.portfolio_id.in_(owned),
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


async def select_fund_tickers(
    session: AsyncSession, tickers: Sequence[str]
) -> set[str]:
    """Subset of *tickers* known as fund tickers — series-representative
    tickers in ``funds`` OR share-class tickers in ``fund_classes`` (F8.6b).

    Used to make portfolio pricing fund-aware (F8.5): fund tickers are priced
    from fund_nav and must NOT be sent to the Tiingo EOD ensure.
    """
    if not tickers:
        return set()
    result = await session.execute(
        select(Fund.ticker)
        .where(Fund.ticker.in_(tickers))
        .union(select(FundClass.ticker).where(FundClass.ticker.in_(tickers)))
    )
    return {row[0] for row in result.all()}


class PositionTaxonomy(NamedTuple):
    """Per-position fund taxonomy for the grouped allocation view."""

    asset_class: str | None
    strategy_label: str | None
    instrument_id: uuid.UUID | None


async def _fund_instrument_by_ticker(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, Any]:
    """ticker -> instrument_id for fund pricing/naming (F8.5/F8.6b).

    Resolution order: series-representative ticker (``funds.ticker``) first,
    then share-class ticker (``fund_classes.ticker`` — priced with the SERIES
    NAV as a proxy). Within each source the lowest instrument_id wins when a
    ticker is duplicated (deterministic).
    """
    if not tickers:
        return {}
    instrument_by_ticker: dict[str, Any] = {}
    fund_rows = await session.execute(
        select(Fund.ticker, Fund.instrument_id)
        .where(Fund.ticker.in_(tickers))
        .order_by(Fund.ticker, Fund.instrument_id)
    )
    for ticker, instrument_id in fund_rows.all():
        instrument_by_ticker.setdefault(ticker, instrument_id)
    remaining = [t for t in tickers if t not in instrument_by_ticker]
    if remaining:
        # FundClass (fund_classes_v) is keyed by series_id; resolve the
        # instrument by joining funds_v on series_id (Task 2.5). Lowest
        # instrument_id still wins ties (deterministic).
        class_rows = await session.execute(
            select(FundClass.ticker, Fund.instrument_id)
            .join(Fund, Fund.series_id == FundClass.series_id)
            .where(FundClass.ticker.in_(remaining))
            .order_by(FundClass.ticker, Fund.instrument_id)
        )
        for ticker, instrument_id in class_rows.all():
            instrument_by_ticker.setdefault(ticker, instrument_id)
    return instrument_by_ticker


async def resolve_position_taxonomy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, PositionTaxonomy]:
    """ticker -> PositionTaxonomy for the grouped allocation view.

    Fund tickers resolve to their instrument_id (via _fund_instrument_by_ticker)
    and carry the fund asset_class / strategy_label. Any ticker that does not
    resolve to a fund instrument is treated as a directly-held equity:
    ('equity', None, None).
    """
    if not tickers:
        return {}
    instrument_by_ticker = await _fund_instrument_by_ticker(session, tickers)
    instrument_ids = list({iid for iid in instrument_by_ticker.values()})
    asset_class_of = await optimizer_data.load_fund_asset_class(session, instrument_ids)
    strategy_of = await optimizer_data.load_fund_strategy_label(session, instrument_ids)
    out: dict[str, PositionTaxonomy] = {}
    for ticker in tickers:
        iid = instrument_by_ticker.get(ticker)
        if iid is None:
            out[ticker] = PositionTaxonomy("equity", None, None)
        else:
            out[ticker] = PositionTaxonomy(
                asset_class_of.get(iid), strategy_of.get(iid), iid
            )
    return out


async def select_tickers_with_eod(
    session: AsyncSession, tickers: Sequence[str]
) -> set[str]:
    """Subset of *tickers* that have at least one eod_prices row."""
    if not tickers:
        return set()
    result = await session.execute(
        select(EodPrice.ticker).where(EodPrice.ticker.in_(tickers)).distinct()
    )
    return {row[0] for row in result.all()}


async def select_last_two_navs(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, list[tuple[dt.date, float]]]:
    """The two most recent (nav_date, nav) rows per FUND ticker, newest first.

    Same shape as ``select_last_two_closes`` so ``build_overview`` consumes
    both transparently (NAV plays the role of last/prev close for funds).
    Rows with NULL NAV are skipped. Class tickers (fund_classes) resolve to
    their series instrument — the SERIES NAV proxies the class NAV (F8.6b,
    the source prices only the representative class). When several share
    classes carry the same ticker, the lowest instrument_id wins
    (deterministic).
    """
    if not tickers:
        return {}
    instrument_by_ticker = await _fund_instrument_by_ticker(session, tickers)
    if not instrument_by_ticker:
        return {}
    # Several class tickers may share one instrument — keep ALL of them.
    tickers_by_instrument: dict[Any, list[str]] = {}
    for ticker, instrument_id in instrument_by_ticker.items():
        tickers_by_instrument.setdefault(instrument_id, []).append(ticker)

    rn = (
        func.row_number()
        .over(partition_by=FundNav.instrument_id, order_by=FundNav.nav_date.desc())
        .label("rn")
    )
    latest = (
        select(FundNav.instrument_id, FundNav.nav_date, FundNav.nav, rn)
        .where(
            FundNav.instrument_id.in_(list(instrument_by_ticker.values())),
            FundNav.nav.is_not(None),
        )
        .subquery()
    )
    result = await session.execute(
        select(latest.c.instrument_id, latest.c.nav_date, latest.c.nav)
        .where(latest.c.rn <= 2)
        .order_by(latest.c.instrument_id, latest.c.nav_date.desc())
    )
    navs: dict[str, list[tuple[dt.date, float]]] = {}
    for instrument_id, nav_date, nav in result.all():
        for ticker in tickers_by_instrument[instrument_id]:
            navs.setdefault(ticker, []).append((nav_date, float(nav)))
    return navs


async def select_fund_names(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, str | None]:
    """Display names from the local funds table (missing tickers are absent).

    Class tickers (fund_classes) display as "{fund.name} — {class_name}"
    (falling back to the fund name when the class has no name).
    """
    if not tickers:
        return {}
    result = await session.execute(
        select(Fund.ticker, Fund.name)
        .where(Fund.ticker.in_(tickers))
        .order_by(Fund.ticker, Fund.instrument_id)
    )
    names: dict[str, str | None] = {}
    for ticker, name in result.all():
        names.setdefault(ticker, name)
    remaining = [t for t in tickers if t not in names]
    if remaining:
        class_rows = await session.execute(
            select(FundClass.ticker, FundClass.class_name, Fund.name)
            .join(Fund, Fund.series_id == FundClass.series_id)
            .where(FundClass.ticker.in_(remaining))
            .order_by(FundClass.ticker, Fund.instrument_id)
        )
        for ticker, class_name, fund_name in class_rows.all():
            display = f"{fund_name} — {class_name}" if class_name else fund_name
            names.setdefault(ticker, display)
    return names


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
    """Structural view of a position — lets tests pass plain namespaces.

    Read-only properties (not plain attributes) so the ORM ``Position`` —
    whose ``commission`` is ``Decimal | None`` — and test namespaces both
    satisfy the protocol (covariance)."""

    @property
    def ticker(self) -> str: ...

    @property
    def quantity(self) -> float: ...

    @property
    def acq_price(self) -> float | None: ...

    @property
    def basis(self) -> str: ...

    @property
    def commission(self) -> float | Decimal | None: ...

    @property
    def trade_date(self) -> dt.date | None: ...


def build_overview(
    positions: Sequence[PositionLike],
    closes_by_ticker: dict[str, list[tuple[dt.date, float]]],
    names_by_ticker: dict[str, str | None],
    cash: float,
    taxonomy_by_ticker: Mapping[str, PositionTaxonomy] | None = None,
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
        # closes[0] = newest, closes[1] = second-newest — guaranteed by
        # select_last_two_closes ordering (date DESC within each ticker).
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
        tax = (taxonomy_by_ticker or {}).get(
            position.ticker, PositionTaxonomy(None, None, None)
        )
        rows.append(
            PositionOverview(
                ticker=position.ticker,
                name=names_by_ticker.get(position.ticker),
                asset_class=tax.asset_class,
                strategy_label=tax.strategy_label,
                instrument_id=tax.instrument_id,
                quantity=position.quantity,
                acq_price=position.acq_price,
                basis=cast("PositionBasis", position.basis),
                commission=(
                    float(position.commission)
                    if position.commission is not None
                    else None
                ),
                trade_date=position.trade_date,
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

    total_market_value = sum((row.market_value for row in rows), 0.0)
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
