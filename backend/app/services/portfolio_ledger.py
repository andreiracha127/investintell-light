"""Portfolio transaction ledger and transaction-aware NAV reconstruction.

The existing ``positions`` table is a current snapshot. This module owns the
auditable buy/sell ledger and a NAV index derived from transaction-dated
holdings, so the UI does not need to backcast current holdings into the past.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import NamedTuple, Protocol, cast

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.fund import FundNav
from app.models.portfolio import PortfolioNavDaily, PortfolioTransaction, Position
from app.schemas.portfolios import PortfolioTransactionCreate
from app.services import portfolio_crud

EPSILON = 1e-9


class PortfolioLedgerError(Exception):
    """Base class for ledger-domain errors mapped by the route layer."""


class PortfolioNotFoundError(PortfolioLedgerError):
    """Raised when a portfolio id does not exist."""


class InsufficientPositionError(PortfolioLedgerError):
    """Raised when a sell would take the transaction ledger below zero shares."""


class MissingLedgerPriceDataError(PortfolioLedgerError):
    """Raised when NAV reconstruction cannot price an active position."""


class TransactionLike(Protocol):
    ticker: str
    side: str
    quantity: float
    price: float
    commission: float | Decimal
    trade_date: dt.date


class LedgerNavPoint(NamedTuple):
    date: dt.date
    nav: float
    market_value: float
    cash: float


class PortfolioNavMaterialization(NamedTuple):
    portfolio_id: int
    points: int
    start_date: dt.date | None
    end_date: dt.date | None


def _money(value: float) -> float:
    return round(value, 6)


def _price_lookup(
    prices_by_ticker: Mapping[str, Sequence[tuple[dt.date, float]]],
) -> dict[dt.date, dict[str, float]]:
    by_date: dict[dt.date, dict[str, float]] = defaultdict(dict)
    for ticker, rows in prices_by_ticker.items():
        for date_, price in rows:
            by_date[date_][ticker] = float(price)
    return dict(by_date)


def _position_value(positions: Mapping[str, float], prices: Mapping[str, float]) -> float:
    value = 0.0
    for ticker, quantity in positions.items():
        if quantity <= EPSILON:
            continue
        price = prices.get(ticker)
        if price is None:
            raise MissingLedgerPriceDataError(
                f"No price available for active ledger position {ticker}."
            )
        value += quantity * price
    return value


def _apply_transaction(
    positions: dict[str, float],
    cash: float,
    transaction: TransactionLike,
) -> float:
    gross = transaction.quantity * transaction.price
    commission = float(transaction.commission or 0.0)
    current = positions.get(transaction.ticker, 0.0)
    if transaction.side == "buy":
        positions[transaction.ticker] = current + transaction.quantity
        return cash - gross - commission
    if current + EPSILON < transaction.quantity:
        raise InsufficientPositionError(
            f"Cannot sell {transaction.quantity:g} {transaction.ticker}; "
            f"ledger holds {current:g}."
        )
    remaining = current - transaction.quantity
    if remaining <= EPSILON:
        positions.pop(transaction.ticker, None)
    else:
        positions[transaction.ticker] = remaining
    return cash + gross - commission


def build_transaction_nav(
    transactions: Sequence[TransactionLike],
    prices_by_ticker: Mapping[str, Sequence[tuple[dt.date, float]]],
    *,
    inception_date: dt.date | None = None,
) -> list[LedgerNavPoint]:
    """Build a transaction-aware NAV index, rebased to 100 at first trade.

    Trades update the active holdings from their actual trade date. The NAV
    index is time-weighted: a trade changes future exposure but does not itself
    create return on the trade date.
    """
    ordered = sorted(transactions, key=lambda t: (t.trade_date, t.ticker, t.side))
    if not ordered:
        return []

    first_trade = ordered[0].trade_date
    inception = min(inception_date, first_trade) if inception_date else first_trade
    price_by_date = _price_lookup(prices_by_ticker)
    dates = {inception, *(t.trade_date for t in ordered)}
    dates.update(date_ for date_ in price_by_date if date_ >= inception)
    all_dates = sorted(dates)

    tx_by_date: dict[dt.date, list[TransactionLike]] = defaultdict(list)
    for tx in ordered:
        tx_by_date[tx.trade_date].append(tx)

    positions: dict[str, float] = {}
    last_prices: dict[str, float] = {}
    cash = 0.0
    nav_index = 100.0
    previous_market_value = 0.0
    points: list[LedgerNavPoint] = []

    for date_ in all_dates:
        last_prices.update(price_by_date.get(date_, {}))
        for tx in tx_by_date.get(date_, []):
            last_prices.setdefault(tx.ticker, tx.price)

        if points and previous_market_value > EPSILON:
            before_trades = _position_value(positions, last_prices)
            nav_index *= before_trades / previous_market_value

        for tx in tx_by_date.get(date_, []):
            cash = _apply_transaction(positions, cash, tx)

        market_value = _position_value(positions, last_prices) if positions else 0.0
        points.append(
            LedgerNavPoint(
                date=date_,
                nav=_money(nav_index),
                market_value=_money(market_value),
                cash=_money(cash),
            )
        )
        previous_market_value = market_value

    return points


def build_portfolio_transaction_nav(
    transactions: Sequence[PortfolioTransaction],
    prices_by_ticker: Mapping[str, Sequence[tuple[dt.date, float]]],
    *,
    inception_date: dt.date | None = None,
) -> list[LedgerNavPoint]:
    """Typed wrapper for ORM ledger rows.

    SQLAlchemy mapped attributes are valid at runtime but do not satisfy the
    structural protocol cleanly under mypy, so the cast stays at this boundary.
    """
    return build_transaction_nav(
        cast("Sequence[TransactionLike]", transactions),
        prices_by_ticker,
        inception_date=inception_date,
    )


async def list_transactions(
    session: AsyncSession, portfolio_id: int
) -> list[PortfolioTransaction]:
    result = await session.execute(
        select(PortfolioTransaction)
        .where(PortfolioTransaction.portfolio_id == portfolio_id)
        .order_by(PortfolioTransaction.trade_date, PortfolioTransaction.id)
    )
    return list(result.scalars().all())


async def create_transaction(
    session: AsyncSession,
    portfolio_id: int,
    payload: PortfolioTransactionCreate,
) -> PortfolioTransaction:
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found.")

    position = next(
        (p for p in portfolio.positions if p.ticker == payload.ticker),
        None,
    )
    commission = float(payload.commission or 0.0)
    gross = payload.quantity * payload.price

    if payload.side == "buy":
        if position is None:
            position = Position(
                portfolio_id=portfolio_id,
                ticker=payload.ticker,
                quantity=payload.quantity,
                acq_price=(gross + commission) / payload.quantity,
                basis="executed",
                commission=Decimal(str(commission)),
                trade_date=payload.trade_date,
            )
            session.add(position)
        else:
            existing_cost = position.quantity * (position.acq_price or payload.price)
            total_quantity = position.quantity + payload.quantity
            position.quantity = total_quantity
            position.acq_price = (existing_cost + gross + commission) / total_quantity
            position.basis = "executed"
            position.commission = Decimal(
                str(float(position.commission or 0.0) + commission)
            )
            position.trade_date = payload.trade_date
        portfolio.cash = float(portfolio.cash) - gross - commission
    else:
        if position is None or position.quantity + EPSILON < payload.quantity:
            held = 0.0 if position is None else position.quantity
            raise InsufficientPositionError(
                f"Cannot sell {payload.quantity:g} {payload.ticker}; "
                f"portfolio holds {held:g}."
            )
        remaining = position.quantity - payload.quantity
        if remaining <= EPSILON:
            await session.delete(position)
        else:
            position.quantity = remaining
        portfolio.cash = float(portfolio.cash) + gross - commission

    transaction = PortfolioTransaction(
        portfolio_id=portfolio_id,
        ticker=payload.ticker,
        side=payload.side,
        quantity=payload.quantity,
        price=payload.price,
        commission=Decimal(str(commission)),
        trade_date=payload.trade_date,
    )
    session.add(transaction)
    await session.flush()
    return transaction


async def load_price_history(
    session: AsyncSession,
    tickers: Sequence[str],
    start_date: dt.date,
    end_date: dt.date,
) -> dict[str, list[tuple[dt.date, float]]]:
    if not tickers:
        return {}

    unique_tickers = sorted(set(tickers))
    result = await session.execute(
        select(EodPrice.ticker, EodPrice.date, EodPrice.close)
        .where(
            EodPrice.ticker.in_(unique_tickers),
            EodPrice.date >= start_date,
            EodPrice.date <= end_date,
        )
        .order_by(EodPrice.ticker, EodPrice.date)
    )
    prices: dict[str, list[tuple[dt.date, float]]] = defaultdict(list)
    for ticker, date_, close in result.all():
        prices[ticker].append((date_, float(close)))

    fund_tickers = await portfolio_crud.select_fund_tickers(session, unique_tickers)
    missing_funds = sorted(fund_tickers - set(prices))
    if missing_funds:
        instrument_by_ticker = await portfolio_crud._fund_instrument_by_ticker(
            session, missing_funds
        )
        tickers_by_instrument: dict[object, list[str]] = defaultdict(list)
        for ticker, instrument_id in instrument_by_ticker.items():
            tickers_by_instrument[instrument_id].append(ticker)

        nav_result = await session.execute(
            select(FundNav.instrument_id, FundNav.nav_date, FundNav.nav)
            .where(
                FundNav.instrument_id.in_(list(tickers_by_instrument)),
                FundNav.nav_date >= start_date,
                FundNav.nav_date <= end_date,
                FundNav.nav.is_not(None),
            )
            .order_by(FundNav.instrument_id, FundNav.nav_date)
        )
        for instrument_id, nav_date, nav in nav_result.all():
            for ticker in tickers_by_instrument[instrument_id]:
                prices[ticker].append((nav_date, float(nav)))

    return {ticker: rows for ticker, rows in prices.items()}


async def get_portfolio_nav(
    session: AsyncSession,
    portfolio_id: int,
    *,
    end_date: dt.date | None = None,
) -> list[LedgerNavPoint]:
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found.")

    transactions = await list_transactions(session, portfolio_id)
    if not transactions:
        return []

    first_trade = min(tx.trade_date for tx in transactions)
    start = (
        min(portfolio.inception_date, first_trade)
        if portfolio.inception_date
        else first_trade
    )
    end = end_date or dt.date.today()
    tickers = [tx.ticker for tx in transactions]
    prices = await load_price_history(session, tickers, start, end)
    return build_portfolio_transaction_nav(
        transactions,
        prices,
        inception_date=portfolio.inception_date,
    )


async def list_materialized_nav(
    session: AsyncSession,
    portfolio_id: int,
    *,
    end_date: dt.date | None = None,
) -> list[PortfolioNavDaily]:
    stmt = (
        select(PortfolioNavDaily)
        .where(PortfolioNavDaily.portfolio_id == portfolio_id)
        .order_by(PortfolioNavDaily.nav_date)
    )
    if end_date is not None:
        stmt = stmt.where(PortfolioNavDaily.nav_date <= end_date)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def materialize_portfolio_nav(
    session: AsyncSession,
    portfolio_id: int,
    *,
    end_date: dt.date | None = None,
) -> PortfolioNavMaterialization:
    portfolio = await portfolio_crud.get_portfolio(session, portfolio_id)
    if portfolio is None:
        raise PortfolioNotFoundError(f"Portfolio {portfolio_id} not found.")

    transactions = await list_transactions(session, portfolio_id)
    await session.execute(
        delete(PortfolioNavDaily).where(PortfolioNavDaily.portfolio_id == portfolio_id)
    )
    if not transactions:
        await session.flush()
        return PortfolioNavMaterialization(portfolio_id, 0, None, None)

    first_trade = min(tx.trade_date for tx in transactions)
    start = (
        min(portfolio.inception_date, first_trade)
        if portfolio.inception_date
        else first_trade
    )
    end = end_date or dt.date.today()
    prices = await load_price_history(
        session,
        [tx.ticker for tx in transactions],
        start,
        end,
    )
    points = build_portfolio_transaction_nav(
        transactions,
        prices,
        inception_date=portfolio.inception_date,
    )
    rows = [
        PortfolioNavDaily(
            portfolio_id=portfolio_id,
            nav_date=point.date,
            nav=point.nav,
            market_value=point.market_value,
            cash=point.cash,
            total_value=_money(point.market_value + point.cash),
        )
        for point in points
    ]
    session.add_all(rows)
    await session.flush()
    return PortfolioNavMaterialization(
        portfolio_id,
        len(rows),
        rows[0].nav_date if rows else None,
        rows[-1].nav_date if rows else None,
    )


async def select_portfolio_ids_with_ledger(session: AsyncSession) -> list[int]:
    result = await session.execute(
        select(PortfolioTransaction.portfolio_id)
        .distinct()
        .order_by(PortfolioTransaction.portfolio_id)
    )
    return [int(portfolio_id) for portfolio_id in result.scalars().all()]


async def materialize_all_portfolio_nav(
    session: AsyncSession,
    *,
    portfolio_ids: Sequence[int] | None = None,
    end_date: dt.date | None = None,
) -> list[PortfolioNavMaterialization]:
    ids = (
        list(portfolio_ids)
        if portfolio_ids is not None
        else await select_portfolio_ids_with_ledger(session)
    )
    results: list[PortfolioNavMaterialization] = []
    for portfolio_id in ids:
        results.append(
            await materialize_portfolio_nav(
                session,
                int(portfolio_id),
                end_date=end_date,
            )
        )
    return results
