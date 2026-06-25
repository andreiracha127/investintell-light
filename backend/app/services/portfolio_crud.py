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

from sqlalchemy import CursorResult, Row, delete, func, select, union_all
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError, OperationalError, ProgrammingError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config import get_settings
from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundClass, FundClassResolution, FundListRow, FundNav
from app.models.instrument import Instrument
from app.models.portfolio import Portfolio, Position
from app.models.price_latest import NavLatest, PriceLatest
from app.schemas.portfolios import (
    OverviewAggregates,
    PortfolioCreate,
    PositionBasis,
    PositionOverview,
    PositionPriceSource,
)

# Hard cap on GET /portfolios — owner-scoped, so no pagination, just a bound.
LIST_HARD_CAP = 100

# Sentinel for "field absent from a partial update" — None can be a real value
# for nullable fields, so it cannot double as the default.
UNSET: Any = object()


class DuplicatePortfolioNameError(Exception):
    """Raised when a portfolio name violates the UNIQUE constraint."""


class MissingPriceDataError(Exception):
    """Raised when a position ticker has no local EOD/NAV rows."""


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
    """Insert a portfolio (and its initial positions); return it fully loaded.

    ``origin`` is provenance, NOT user input ('manual' | 'builder' — the
    builder save passes 'builder'; the public CRUD never exposes it).
    Raises DuplicatePortfolioNameError on a name conflict.  Duplicate tickers
    cannot reach the positions UNIQUE constraint — the schema rejects them
    with 422 — so an IntegrityError here can only be the name.
    """
    portfolio = Portfolio(
        name=payload.name,
        owner_sub=owner_sub,
        org_id=org_id,
        cash=payload.cash,
        inception_date=payload.inception_date,
        origin=origin,
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
    # Re-select so server-set defaults (timestamps) and the positions
    # collection are loaded without tripping lazy="raise".
    loaded = await get_portfolio(session, portfolio.id, owner_sub)
    if loaded is None:  # pragma: no cover — the row was just committed
        raise RuntimeError(f"Portfolio {portfolio.id} vanished after commit.")
    return loaded


async def get_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str | None = None
) -> Portfolio | None:
    """Load one portfolio WITH its positions (explicit selectinload — lazy='raise')."""
    clauses = [Portfolio.id == portfolio_id]
    if owner_sub is not None:
        clauses.append(Portfolio.owner_sub == owner_sub)
    result = await session.execute(
        select(Portfolio)
        .options(selectinload(Portfolio.positions))
        .where(*clauses)
    )
    return result.scalar_one_or_none()


async def list_portfolios(session: AsyncSession, owner_sub: str) -> Sequence[Row]:
    """List rows of portfolio summary fields, id order, capped."""
    result = await session.execute(
        select(
            Portfolio.id,
            Portfolio.name,
            Portfolio.cash,
            func.count(Position.id).label("position_count"),
            Portfolio.inception_date,
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
    inception_date: dt.date | None | Any = UNSET,
) -> Portfolio | None:
    """Apply a partial update; return the reloaded portfolio, or None if missing."""
    portfolio = await get_portfolio(session, portfolio_id, owner_sub)
    if portfolio is None:
        return None
    if name is not None:
        portfolio.name = name
    if cash is not None:
        portfolio.cash = cash
    if inception_date is not UNSET:
        portfolio.inception_date = inception_date
    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise DuplicatePortfolioNameError(
            f"A portfolio named {name!r} already exists."
        ) from exc
    # Re-select so the DB-computed updated_at is reflected in the response.
    return await get_portfolio(session, portfolio_id, owner_sub)


async def delete_portfolio(
    session: AsyncSession, portfolio_id: int, owner_sub: str
) -> bool:
    """Delete one portfolio; positions go with it via ON DELETE CASCADE."""
    result = cast(
        "CursorResult[Any]",
        await session.execute(
            delete(Portfolio).where(
                Portfolio.id == portfolio_id,
                Portfolio.owner_sub == owner_sub,
            )
        ),
    )
    await session.commit()
    return bool(result.rowcount)


async def portfolio_exists(
    session: AsyncSession, portfolio_id: int, owner_sub: str | None = None
) -> bool:
    """True when the portfolio row exists (positions not loaded)."""
    clauses = [Portfolio.id == portfolio_id]
    if owner_sub is not None:
        clauses.append(Portfolio.owner_sub == owner_sub)
    found = await session.scalar(
        select(Portfolio.id).where(*clauses)
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

    The route checks existence FIRST (get_position) to gate local coverage
    validation on the INSERT path only. After validation, this upsert collapses
    any concurrent INSERT race to last-write-wins instead of an unhandled
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
    session: AsyncSession,
    portfolio_id: int,
    ticker: str,
    owner_sub: str | None = None,
) -> bool:
    """Delete one position; False when no row matched."""
    clauses = [Position.portfolio_id == portfolio_id, Position.ticker == ticker]
    if owner_sub is not None:
        clauses.append(
            Position.portfolio_id.in_(
                select(Portfolio.id).where(
                    Portfolio.id == portfolio_id,
                    Portfolio.owner_sub == owner_sub,
                )
            )
        )
    result = cast(
        "CursorResult[Any]",
        await session.execute(delete(Position).where(*clauses)),
    )
    await session.commit()
    return bool(result.rowcount)


# ---------------------------------------------------------------------------
# Overview reads
# ---------------------------------------------------------------------------


async def _select_last_two_closes_legacy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, list[tuple[dt.date, float]]]:
    """The two most recent (date, close) rows per ticker, newest first.

    Raw ``close`` (not adj_close): last/prev power the quote-style price,
    change and market-value columns, which display traded prices.
    """
    if not tickers:
        return {}
    per_ticker = []
    for ticker in dict.fromkeys(tickers):
        latest = (
            select(
                EodPrice.ticker.label("ticker"),
                EodPrice.date.label("date"),
                EodPrice.close.label("close"),
            )
            .where(EodPrice.ticker == ticker)
            .order_by(EodPrice.date.desc())
            .limit(2)
            .subquery()
        )
        per_ticker.append(select(latest.c.ticker, latest.c.date, latest.c.close))
    unioned = (
        per_ticker[0].subquery()
        if len(per_ticker) == 1
        else union_all(*per_ticker).subquery()
    )
    result = await session.execute(
        select(unioned.c.ticker, unioned.c.date, unioned.c.close).order_by(
            unioned.c.ticker, unioned.c.date.desc()
        )
    )
    closes: dict[str, list[tuple[dt.date, float]]] = {}
    for ticker, date_, close in result.all():
        closes.setdefault(ticker, []).append((date_, close))
    return closes


async def select_last_two_closes(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    use_mv: bool | None = None,
    fallback_missing: bool = True,
) -> dict[str, list[tuple[dt.date, float]]]:
    """Two most recent (date, close) per ticker, newest first.

    DB-first: lê de price_latest_mv quando habilitado; tickers ausentes do MV
    (ex.: recém-backfillados, ainda não capturados pelo matview_refresh) caem
    para a tabela base, então o shape de saída é idêntico ao legado.

    Comportamento de frescor (lag do refresh): ``eod_prices`` é populado pelo
    backfill/warming worker out-of-band e ``price_latest_mv`` é refrescado por
    cron próprio (``matview_refresh``); há, portanto, um lag entre os dois — um
    preço recém-backfillado pode aparecer no MV só após o próximo refresh.
    Tickers ainda ausentes do MV usam o fallback à tabela base (sem regressão
    funcional). Para um overview EOD isso é aceitável; a flag de dual-read
    (``use_latest_mv_prices``) permite validar em staging antes de virar o
    default em produção.
    """
    if not tickers:
        return {}
    if use_mv is None:
        use_mv = get_settings().use_latest_mv_prices
    if not use_mv:
        return await _select_last_two_closes_legacy(session, tickers)

    rows = await session.execute(
        select(
            PriceLatest.ticker,
            PriceLatest.as_of,
            PriceLatest.last_close,
            PriceLatest.prev_date,
            PriceLatest.prev_close,
        ).where(PriceLatest.ticker.in_(tickers))
    )
    closes: dict[str, list[tuple[dt.date, float]]] = {}
    for ticker, as_of, last_close, prev_date, prev_close in rows.all():
        series = [(as_of, float(last_close))]
        if prev_close is not None and prev_date is not None:
            series.append((prev_date, float(prev_close)))
        closes[ticker] = series

    missing = [t for t in tickers if t not in closes]
    if missing and not fallback_missing:
        return closes
    if missing:
        closes.update(await _select_last_two_closes_legacy(session, missing))
    return closes


async def select_fund_tickers(
    session: AsyncSession, tickers: Sequence[str]
) -> set[str]:
    """Subset of *tickers* known as fund tickers — series-representative
    tickers in ``funds`` OR share-class tickers in ``fund_classes`` (F8.6b).

    Used to make portfolio pricing fund-aware (F8.5): fund tickers are priced
    from fund_nav and do not require local EOD coverage.
    """
    if not tickers:
        return set()
    return set((await _fund_resolution_by_ticker(session, tickers)).keys())


class PositionTaxonomy(NamedTuple):
    """Per-position fund taxonomy for the grouped allocation view."""

    asset_class: str | None
    strategy_label: str | None
    instrument_id: uuid.UUID | None
    fund_type: str | None = None


class FundResolution(NamedTuple):
    """Request-time fund/class ticker resolution flattened for overview reads."""

    instrument_id: uuid.UUID
    asset_class: str | None
    strategy_label: str | None
    fund_type: str | None
    name: str | None
    class_name: str | None = None


def _fund_resolution_display_name(resolution: FundResolution) -> str | None:
    if resolution.class_name and resolution.name:
        return f"{resolution.name} — {resolution.class_name}"
    return resolution.name


async def _fund_resolution_by_ticker_mv(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, FundResolution]:
    """Resolve fund and share-class tickers from indexed materialized views."""
    if not tickers:
        return {}
    unique = list(dict.fromkeys(tickers))
    result = await session.execute(
        select(
            FundListRow.ticker,
            FundListRow.instrument_id,
            FundListRow.asset_class,
            FundListRow.strategy_label,
            FundListRow.fund_type,
            FundListRow.name,
        )
        .where(FundListRow.ticker.in_(unique))
        .order_by(FundListRow.ticker, FundListRow.instrument_id)
    )
    out: dict[str, FundResolution] = {}
    for ticker, instrument_id, asset_class, strategy_label, fund_type, name in result.all():
        if ticker is None:
            continue
        out.setdefault(
            ticker,
            FundResolution(
                instrument_id,
                asset_class,
                strategy_label,
                fund_type,
                name,
            ),
        )

    remaining = [ticker for ticker in unique if ticker not in out]
    if remaining:
        class_rows = await session.execute(
            select(
                FundClassResolution.class_ticker,
                FundClassResolution.instrument_id,
                FundClassResolution.asset_class,
                FundClassResolution.strategy_label,
                FundClassResolution.fund_type,
                FundClassResolution.fund_name,
                FundClassResolution.class_name,
            )
            .where(FundClassResolution.class_ticker.in_(remaining))
            .order_by(
                FundClassResolution.class_ticker,
                FundClassResolution.instrument_id,
            )
        )
        for (
            ticker,
            instrument_id,
            asset_class,
            strategy_label,
            fund_type,
            fund_name,
            class_name,
        ) in class_rows.all():
            out.setdefault(
                ticker,
                FundResolution(
                    instrument_id,
                    asset_class,
                    strategy_label,
                    fund_type,
                    fund_name,
                    class_name,
                ),
            )
    return out


async def _fund_resolution_by_ticker_legacy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, FundResolution]:
    """Fallback resolver over dynamic lineage views for stale/missing MV rows."""
    if not tickers:
        return {}
    unique = list(dict.fromkeys(tickers))
    out: dict[str, FundResolution] = {}
    fund_rows = await session.execute(
        select(
            Fund.ticker,
            Fund.instrument_id,
            Fund.asset_class,
            Fund.strategy_label,
            Fund.fund_type,
            Fund.name,
        )
        .where(Fund.ticker.in_(unique))
        .order_by(Fund.ticker, Fund.instrument_id)
    )
    for ticker, instrument_id, asset_class, strategy_label, fund_type, name in fund_rows.all():
        if ticker is None:
            continue
        out.setdefault(
            ticker,
            FundResolution(
                instrument_id,
                asset_class,
                strategy_label,
                fund_type,
                name,
            ),
        )

    remaining = [ticker for ticker in unique if ticker not in out]
    if remaining:
        class_rows = await session.execute(
            select(
                FundClass.ticker,
                FundClass.class_name,
                Fund.instrument_id,
                Fund.asset_class,
                Fund.strategy_label,
                Fund.fund_type,
                Fund.name,
            )
            .join(Fund, Fund.series_id == FundClass.series_id)
            .where(FundClass.ticker.in_(remaining))
            .order_by(FundClass.ticker, Fund.instrument_id)
        )
        for (
            ticker,
            class_name,
            instrument_id,
            asset_class,
            strategy_label,
            fund_type,
            fund_name,
        ) in class_rows.all():
            out.setdefault(
                ticker,
                FundResolution(
                    instrument_id,
                    asset_class,
                    strategy_label,
                    fund_type,
                    fund_name,
                    class_name,
                ),
            )
    return out


async def _fund_resolution_by_ticker(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, FundResolution]:
    """Fast fund/class resolver with legacy fallback for undeployed MV states."""
    if not tickers:
        return {}
    unique = list(dict.fromkeys(tickers))
    try:
        resolved = await _fund_resolution_by_ticker_mv(session, unique)
    except (OperationalError, ProgrammingError):
        await session.rollback()
        return await _fund_resolution_by_ticker_legacy(session, unique)

    missing = [ticker for ticker in unique if ticker not in resolved]
    if missing:
        resolved.update(await _fund_resolution_by_ticker_legacy(session, missing))
    return resolved


async def _fund_instrument_by_ticker(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, Any]:
    """ticker -> instrument_id for fund pricing/naming (F8.5/F8.6b).

    Resolution order: series-representative ticker (``funds.ticker``) first,
    then share-class ticker (``fund_classes.ticker`` — priced with the SERIES
    NAV as a proxy). Within each source the lowest instrument_id wins when a
    ticker is duplicated (deterministic).
    """
    resolved = await _fund_resolution_by_ticker(session, tickers)
    return {ticker: resolution.instrument_id for ticker, resolution in resolved.items()}


async def _fund_type_by_instrument(
    session: AsyncSession, instrument_ids: Sequence[Any]
) -> dict[Any, str]:
    """instrument_id -> fund_type for resolved fund holdings."""
    if not instrument_ids:
        return {}
    try:
        result = await session.execute(
            select(FundListRow.instrument_id, FundListRow.fund_type).where(
                FundListRow.instrument_id.in_(instrument_ids)
            )
        )
        found = {instrument_id: fund_type for instrument_id, fund_type in result.all()}
    except (OperationalError, ProgrammingError):
        await session.rollback()
        found = {}
    missing = [instrument_id for instrument_id in instrument_ids if instrument_id not in found]
    if missing:
        result = await session.execute(
            select(Fund.instrument_id, Fund.fund_type).where(
                Fund.instrument_id.in_(missing)
            )
        )
        found.update({instrument_id: fund_type for instrument_id, fund_type in result.all()})
    return found


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
    resolution_by_ticker = await _fund_resolution_by_ticker(session, tickers)
    out: dict[str, PositionTaxonomy] = {}
    for ticker in tickers:
        resolution = resolution_by_ticker.get(ticker)
        if resolution is None:
            out[ticker] = PositionTaxonomy("equity", None, None)
        else:
            out[ticker] = PositionTaxonomy(
                resolution.asset_class,
                resolution.strategy_label,
                resolution.instrument_id,
                resolution.fund_type,
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


async def _select_last_two_navs_legacy(
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

    per_instrument = []
    for instrument_id in dict.fromkeys(instrument_by_ticker.values()):
        latest = (
            select(
                FundNav.instrument_id.label("instrument_id"),
                FundNav.nav_date.label("nav_date"),
                FundNav.nav.label("nav"),
            )
            .where(FundNav.instrument_id == instrument_id, FundNav.nav.is_not(None))
            .order_by(FundNav.nav_date.desc())
            .limit(2)
            .subquery()
        )
        per_instrument.append(
            select(latest.c.instrument_id, latest.c.nav_date, latest.c.nav)
        )
    unioned = (
        per_instrument[0].subquery()
        if len(per_instrument) == 1
        else union_all(*per_instrument).subquery()
    )
    result = await session.execute(
        select(unioned.c.instrument_id, unioned.c.nav_date, unioned.c.nav).order_by(
            unioned.c.instrument_id, unioned.c.nav_date.desc()
        )
    )
    navs: dict[str, list[tuple[dt.date, float]]] = {}
    for instrument_id, nav_date, nav in result.all():
        for ticker in tickers_by_instrument[instrument_id]:
            navs.setdefault(ticker, []).append((nav_date, float(nav)))
    return navs


async def select_last_two_navs(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    use_mv: bool | None = None,
) -> dict[str, list[tuple[dt.date, float]]]:
    """Two most recent (nav_date, nav) per FUND ticker, newest first.

    Same shape as ``select_last_two_closes`` (build_overview consumes both
    transparently). DB-first: lê de nav_latest_mv quando habilitado; o MV é
    keyed por instrument_id, então a resolução ticker→instrumento permanece —
    instrumentos ausentes do MV caem para a tabela base.
    """
    if not tickers:
        return {}
    if use_mv is None:
        use_mv = get_settings().use_latest_mv_prices
    if not use_mv:
        return await _select_last_two_navs_legacy(session, tickers)

    instrument_by_ticker = await _fund_instrument_by_ticker(session, tickers)
    if not instrument_by_ticker:
        return {}
    # Several class tickers may share one instrument — keep ALL of them.
    tickers_by_instrument: dict[Any, list[str]] = {}
    for ticker, instrument_id in instrument_by_ticker.items():
        tickers_by_instrument.setdefault(instrument_id, []).append(ticker)

    rows = await session.execute(
        select(
            NavLatest.instrument_id,
            NavLatest.as_of,
            NavLatest.last_nav,
            NavLatest.prev_date,
            NavLatest.prev_nav,
        ).where(NavLatest.instrument_id.in_(list(instrument_by_ticker.values())))
    )
    navs: dict[str, list[tuple[dt.date, float]]] = {}
    for instrument_id, as_of, last_nav, prev_date, prev_nav in rows.all():
        series = [(as_of, float(last_nav))]
        if prev_nav is not None and prev_date is not None:
            series.append((prev_date, float(prev_nav)))
        for ticker in tickers_by_instrument[instrument_id]:
            navs[ticker] = list(series)

    missing = [t for t in tickers if t not in navs]
    if missing:
        navs.update(await _select_last_two_navs_legacy(session, missing))
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
    return {
        ticker: _fund_resolution_display_name(resolution)
        for ticker, resolution in (
            await _fund_resolution_by_ticker(session, tickers)
        ).items()
    }


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
    nav_tickers: set[str] | None = None,
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
        fund_type = tax.fund_type.lower() if tax.fund_type else None
        price_source: PositionPriceSource = (
            "nav" if position.ticker in (nav_tickers or set()) else "eod"
        )
        live_price_eligible = price_source == "eod" and (
            tax.instrument_id is None or fund_type == "etf"
        )
        rows.append(
            PositionOverview(
                ticker=position.ticker,
                name=names_by_ticker.get(position.ticker),
                asset_class=tax.asset_class,
                strategy_label=tax.strategy_label,
                instrument_id=tax.instrument_id,
                fund_type=fund_type,
                price_source=price_source,
                live_price_eligible=live_price_eligible,
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
