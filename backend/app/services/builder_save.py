"""Save a builder proposal as a persisted portfolio (F8.5).

Flow (POST /builder/save):
1. resolve a SPOT price per asset — equities: latest ``eod_prices.adj_close``
   by ticker; funds: latest non-NULL ``fund_nav.nav`` by instrument_id plus
   the fund's ticker from ``funds`` (a fund without a ticker cannot become a
   position — positions are keyed by ticker);
2. size each position: ``quantity = weight * notional_usd / price`` rounded
   to ``QUANTITY_DECIMALS`` (the ``positions.quantity`` column is a float);
3. persist via the F4 CRUD with ``acq_price`` = the spot price (the cost
   basis of the proposal).

Error contract: every domain failure raises ``BuilderError`` (→ 422 with the
message verbatim at the route), including a duplicate portfolio name — the
builder flow treats it as an input problem, not a 409 resource conflict.
"""

import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundNav
from app.schemas.builder import (
    EquityRefIn,
    FundRefIn,
    SavedPositionOut,
    SaveRequest,
    SaveResponse,
)
from app.schemas.portfolios import PortfolioCreate, PositionCreate
from app.services import portfolio_crud
from app.services.portfolio_builder import BuilderError

# positions.quantity is a float column — 4 decimals is the product contract.
QUANTITY_DECIMALS = 4


@dataclass(frozen=True)
class FundSpot:
    """Spot view of one fund: position ticker + latest non-NULL NAV."""

    ticker: str | None
    name: str
    nav: float | None


# ---------------------------------------------------------------------------
# Spot-price reads
# ---------------------------------------------------------------------------


async def load_equity_spots(
    session: AsyncSession, tickers: list[str]
) -> dict[str, float]:
    """Latest adj_close per ticker; tickers without EOD rows are absent."""
    if not tickers:
        return {}
    latest_date = (
        select(EodPrice.ticker, func.max(EodPrice.date).label("max_date"))
        .where(EodPrice.ticker.in_(tickers))
        .group_by(EodPrice.ticker)
        .subquery()
    )
    result = await session.execute(
        select(EodPrice.ticker, EodPrice.adj_close).join(
            latest_date,
            (EodPrice.ticker == latest_date.c.ticker)
            & (EodPrice.date == latest_date.c.max_date),
        )
    )
    return {ticker: float(price) for ticker, price in result.all()}


async def load_fund_spots(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, FundSpot]:
    """Fund ticker/name + latest non-NULL NAV per instrument; unknown ids absent."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.ticker, Fund.name).where(
            Fund.instrument_id.in_(fund_ids)
        )
    )
    identity = {row[0]: (row[1], row[2]) for row in result.all()}

    latest_date = (
        select(FundNav.instrument_id, func.max(FundNav.nav_date).label("max_date"))
        .where(FundNav.instrument_id.in_(fund_ids), FundNav.nav.is_not(None))
        .group_by(FundNav.instrument_id)
        .subquery()
    )
    nav_result = await session.execute(
        select(FundNav.instrument_id, FundNav.nav).join(
            latest_date,
            (FundNav.instrument_id == latest_date.c.instrument_id)
            & (FundNav.nav_date == latest_date.c.max_date),
        )
    )
    navs = {row[0]: float(row[1]) for row in nav_result.all()}
    return {
        fund_id: FundSpot(ticker=ticker, name=name, nav=navs.get(fund_id))
        for fund_id, (ticker, name) in identity.items()
    }


# ---------------------------------------------------------------------------
# Pure sizing math (unit-tested directly)
# ---------------------------------------------------------------------------


def position_for(
    ticker: str, weight: float, price: float, notional_usd: float
) -> PositionCreate:
    """Size one position: quantity = weight * notional / price, 4 decimals.

    Raises BuilderError when the rounded quantity is not positive (the weight
    is too small for the notional) or the ticker fails position validation.
    """
    if price <= 0:
        raise BuilderError(f"sem preço para {ticker}: preço spot {price} inválido")
    quantity = round(weight * notional_usd / price, QUANTITY_DECIMALS)
    if quantity <= 0:
        raise BuilderError(
            f"peso {weight:.6f} de {ticker} resulta em quantidade 0 com notional "
            f"{notional_usd:,.0f} — remova o ativo ou aumente o notional"
        )
    try:
        return PositionCreate(ticker=ticker, quantity=quantity, acq_price=price)
    except (ValidationError, ValueError) as exc:
        raise BuilderError(f"posição inválida para {ticker}: {exc}") from exc


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


async def run_save(session: AsyncSession, payload: SaveRequest) -> SaveResponse:
    """Resolve spot prices, size positions and persist the portfolio."""
    equity_tickers = sorted(
        {
            item.asset.ticker.upper()
            for item in payload.weights
            if isinstance(item.asset, EquityRefIn)
        }
    )
    fund_ids = [
        item.asset.id for item in payload.weights if isinstance(item.asset, FundRefIn)
    ]
    equity_spots = await load_equity_spots(session, equity_tickers)
    fund_spots = await load_fund_spots(session, list(dict.fromkeys(fund_ids)))

    positions: list[PositionCreate] = []
    seen_tickers: set[str] = set()
    for item in payload.weights:
        if isinstance(item.asset, EquityRefIn):
            ticker = item.asset.ticker.upper()
            price = equity_spots.get(ticker)
            if price is None:
                raise BuilderError(
                    f"sem preço para equity:{ticker} — nenhuma linha em eod_prices"
                )
        else:
            spot = fund_spots.get(item.asset.id)
            if spot is None:
                raise BuilderError(f"fundo desconhecido: {item.asset.id}")
            if spot.ticker is None:
                raise BuilderError(
                    f"o fundo {spot.name!r} ({item.asset.id}) não tem ticker — "
                    "posições são identificadas por ticker, então ele não pode "
                    "virar posição de portfólio; remova-o da proposta"
                )
            if spot.nav is None:
                raise BuilderError(
                    f"sem preço para fund:{item.asset.id} ({spot.ticker}) — "
                    "nenhum NAV em fund_nav"
                )
            ticker, price = spot.ticker.upper(), spot.nav
        if ticker in seen_tickers:
            raise BuilderError(
                f"ativos duplicados na proposta: o ticker {ticker} aparece mais "
                "de uma vez — consolide os pesos antes de salvar"
            )
        seen_tickers.add(ticker)
        positions.append(position_for(ticker, item.weight, price, payload.notional_usd))

    try:
        create_payload = PortfolioCreate(name=payload.name, cash=0.0, positions=positions)
    except ValidationError as exc:
        raise BuilderError(str(exc)) from exc
    try:
        portfolio = await portfolio_crud.create_portfolio(session, create_payload)
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise BuilderError(str(exc)) from exc

    return SaveResponse(
        portfolio_id=portfolio.id,
        name=portfolio.name,
        notional_usd=payload.notional_usd,
        positions=[
            # acq_price is always set by position_for; assert narrows the type.
            SavedPositionOut(ticker=p.ticker, quantity=p.quantity, price=_price(p))
            for p in positions
        ],
    )


def _price(position: PositionCreate) -> float:
    assert position.acq_price is not None  # set unconditionally by position_for
    return position.acq_price
