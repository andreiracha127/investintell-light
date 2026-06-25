"""Save a builder proposal as a persisted portfolio (F8.5 + F8.6b).

Flow (POST /builder/save):
1. resolve a REFERENCE price per asset — equities: latest
   ``eod_prices.adj_close`` by ticker; funds: latest non-NULL
   ``fund_nav.nav`` by instrument_id plus the fund's ticker from ``funds``
   (a fund without a ticker cannot become a position — positions are keyed
   by ticker);
2. size each position: ``quantity = weight * notional_usd / price`` rounded
   to ``QUANTITY_DECIMALS`` (the ``positions.quantity`` column is a float),
   where price is the weight's ``fill_price`` when present (EXECUTED), else
   the reference price;
3. persist via the F4 CRUD with portfolio origin='builder' and, per
   position, basis='reference' (acq_price = reference price) or
   basis='executed' (acq_price = (fill*qty + commission)/qty, 6 decimals,
   plus commission/trade_date).

F8.6b fund classes: a weight may carry ``class_ticker`` — a share-class
ticker from ``fund_classes`` belonging to the SAME instrument (otherwise a
422 listing the valid classes). The position is then keyed by the CLASS
ticker. NOTE the documented approximation: the mother DB prices only the
series' representative class, so the class position is priced/analyzed with
the SERIES NAV as a proxy.

Error contract: every domain failure raises ``BuilderError`` (→ 422 with the
message verbatim at the route), including a duplicate portfolio name — the
builder flow treats it as an input problem, not a 409 resource conflict.
"""

import datetime as dt
import uuid
from dataclasses import dataclass

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.fund import Fund, FundClass, FundNav
from app.schemas.builder import (
    EquityRefIn,
    FundRefIn,
    SavedPositionOut,
    SaveRequest,
    SaveResponse,
    SaveWeightIn,
)
from app.schemas.portfolios import PortfolioCreate, PositionBasis, PositionCreate
from app.services import portfolio_crud
from app.services.portfolio_builder import BuilderError

# positions.quantity is a float column — 4 decimals is the product contract.
QUANTITY_DECIMALS = 4
# Effective cost basis (acq_price) rounding for executed fills.
COST_BASIS_DECIMALS = 6


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


async def load_fund_classes(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, dict[str, str | None]]:
    """instrument_id -> {class ticker (upper) -> class_name} from fund_classes.

    Used to validate ``class_ticker`` against the SAME instrument and to
    label the position. Funds without synced classes map to {}.
    """
    if not fund_ids:
        return {}
    # FundClass (fund_classes_latest_mv) is keyed by series_id, not
    # instrument_id; recover the instrument by joining funds_profile_mv on
    # series_id (Task 2.5).
    result = await session.execute(
        select(Fund.instrument_id, FundClass.ticker, FundClass.class_name)
        .join(FundClass, FundClass.series_id == Fund.series_id)
        .where(Fund.instrument_id.in_(fund_ids))
    )
    classes: dict[uuid.UUID, dict[str, str | None]] = {}
    for instrument_id, ticker, class_name in result.all():
        classes.setdefault(instrument_id, {})[ticker.upper()] = class_name
    return classes


# ---------------------------------------------------------------------------
# Pure sizing math (unit-tested directly)
# ---------------------------------------------------------------------------


def executed_cost_basis(
    fill_price: float, quantity: float, commission: float | None
) -> float:
    """Effective per-unit cost basis of an executed fill, 6 decimals.

    (fill_price * quantity + commission) / quantity — e.g. fill 100,
    qty 10, commission 5 ⇒ 100.5.
    """
    total = fill_price * quantity + (commission or 0.0)
    return round(total / quantity, COST_BASIS_DECIMALS)


def position_for(
    ticker: str,
    weight: float,
    price: float,
    notional_usd: float,
    *,
    fill_price: float | None = None,
    commission: float | None = None,
    trade_date: dt.date | None = None,
) -> PositionCreate:
    """Size one position: quantity = weight * notional / price, 4 decimals.

    Without ``fill_price`` the REFERENCE price sizes the position and becomes
    its cost basis (basis='reference'). With ``fill_price`` the fill sizes
    the position and the cost basis includes the commission
    (basis='executed'); commission/trade_date are persisted.

    Raises BuilderError when the rounded quantity is not positive (the weight
    is too small for the notional) or the ticker fails position validation.
    """
    if fill_price is None and price <= 0:
        raise BuilderError(f"sem preço para {ticker}: preço spot {price} inválido")
    sizing_price = fill_price if fill_price is not None else price
    quantity = round(weight * notional_usd / sizing_price, QUANTITY_DECIMALS)
    if quantity <= 0:
        raise BuilderError(
            f"peso {weight:.6f} de {ticker} resulta em quantidade 0 com notional "
            f"{notional_usd:,.0f} — remova o ativo ou aumente o notional"
        )
    basis: PositionBasis
    if fill_price is not None:
        acq_price = executed_cost_basis(fill_price, quantity, commission)
        basis = "executed"
    else:
        acq_price = price
        basis = "reference"
    try:
        return PositionCreate(
            ticker=ticker,
            quantity=quantity,
            acq_price=acq_price,
            basis=basis,
            commission=commission,
            trade_date=trade_date,
        )
    except (ValidationError, ValueError) as exc:
        raise BuilderError(f"posição inválida para {ticker}: {exc}") from exc


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def _resolve_class_ticker(
    item: SaveWeightIn,
    fund_id: uuid.UUID,
    fund_name: str,
    classes: dict[uuid.UUID, dict[str, str | None]],
) -> str:
    """Validate ``class_ticker`` against the fund's synced classes (422 with
    the valid list otherwise) and return it normalized."""
    assert item.class_ticker is not None  # caller gates on presence
    wanted = item.class_ticker.strip().upper()
    fund_classes = classes.get(fund_id, {})
    if wanted not in fund_classes:
        valid = ", ".join(sorted(fund_classes)) or "nenhuma classe sincronizada"
        raise BuilderError(
            f"classe {wanted!r} não pertence ao fundo {fund_name!r} ({fund_id}) — "
            f"classes válidas: {valid}"
        )
    return wanted


async def run_save(
    session: AsyncSession,
    payload: SaveRequest,
    owner_sub: str,
    org_id: str | None,
) -> SaveResponse:
    """Resolve reference prices, size positions and persist the portfolio
    (origin='builder'). See the module docstring for the F8.6b semantics."""
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
    class_fund_ids = [
        item.asset.id
        for item in payload.weights
        if isinstance(item.asset, FundRefIn) and item.class_ticker is not None
    ]
    equity_spots = await load_equity_spots(session, equity_tickers)
    fund_spots = await load_fund_spots(session, list(dict.fromkeys(fund_ids)))
    fund_classes = await load_fund_classes(session, list(dict.fromkeys(class_fund_ids)))

    positions: list[PositionCreate] = []
    sizing_prices: list[float] = []
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
            if item.class_ticker is not None:
                # Position keyed by the CLASS ticker; the series NAV (the
                # representative class) proxies the class NAV — the source
                # prices only one class per series.
                ticker = _resolve_class_ticker(
                    item, item.asset.id, spot.name, fund_classes
                )
            elif spot.ticker is None:
                raise BuilderError(
                    f"o fundo {spot.name!r} ({item.asset.id}) não tem ticker — "
                    "posições são identificadas por ticker, então ele não pode "
                    "virar posição de portfólio; remova-o da proposta ou "
                    "selecione uma classe (class_ticker)"
                )
            else:
                ticker = spot.ticker.upper()
            if spot.nav is None:
                raise BuilderError(
                    f"sem preço para fund:{item.asset.id} ({ticker}) — "
                    "nenhum NAV em fund_nav"
                )
            price = spot.nav
        if ticker in seen_tickers:
            raise BuilderError(
                f"ativos duplicados na proposta: o ticker {ticker} aparece mais "
                "de uma vez — consolide os pesos antes de salvar"
            )
        seen_tickers.add(ticker)
        positions.append(
            position_for(
                ticker,
                item.weight,
                price,
                payload.notional_usd,
                fill_price=item.fill_price,
                commission=item.commission,
                trade_date=item.trade_date,
            )
        )
        sizing_prices.append(item.fill_price if item.fill_price is not None else price)

    try:
        create_payload = PortfolioCreate(name=payload.name, cash=0.0, positions=positions)
    except ValidationError as exc:
        raise BuilderError(str(exc)) from exc
    try:
        portfolio = await portfolio_crud.create_portfolio(
            session, create_payload, owner_sub, org_id, origin="builder"
        )
    except portfolio_crud.DuplicatePortfolioNameError as exc:
        raise BuilderError(str(exc)) from exc

    return SaveResponse(
        portfolio_id=portfolio.id,
        name=portfolio.name,
        notional_usd=payload.notional_usd,
        positions=[
            SavedPositionOut(
                ticker=p.ticker,
                quantity=p.quantity,
                price=sizing_price,
                # basis is always set by position_for ('reference'|'executed');
                # acq_price is always set too — the assert narrows the types.
                basis=_basis(p),
                cost_basis=_cost_basis(p),
            )
            for p, sizing_price in zip(positions, sizing_prices, strict=True)
        ],
    )


def _cost_basis(position: PositionCreate) -> float:
    assert position.acq_price is not None  # set unconditionally by position_for
    return position.acq_price


def _basis(position: PositionCreate) -> PositionBasis:
    assert position.basis is not None  # set unconditionally by position_for
    return position.basis
