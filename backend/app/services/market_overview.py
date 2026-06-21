"""Market overview assembly (landing /stocks).

DB-first sobre tabelas LOCAIS (universe_constituents + eod_prices), mantidas
pelo pipeline batch existente (sync_universe.py + backfill_universe_eod.py).
Nenhuma chamada Tiingo aqui; os índices também dependem de preços já populados
localmente pelo backfill/worker.

Separação para testabilidade:
- ``fetch_overview_rows`` / ``fetch_index_rows`` — readers SQL finos;
- ``rank_overview`` — ranking puro sobre rows planas (unit-tested).
"""

import datetime as dt
import statistics
from collections import defaultdict
from dataclasses import dataclass
from typing import TypedDict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.eod_price import EodPrice
from app.models.universe import UniverseConstituent
from app.schemas.market import IndexCard, LeaderRow, MarketBreadth, SectorPerf

# Piso de liquidez das tabelas rankeadas: sem ele a lista de gainers é
# dominada por micro caps abrindo com gap sem volume.
PRICE_FLOOR = 5.0
MIN_DOLLAR_VOLUME = 5_000_000.0
TOP_N = 25
LOOKBACK_52W_DAYS = 364
RECENT_WINDOW_DAYS = 14  # cobre feriados/fins de semana p/ achar os 2 últimos pregões
NEAR_EXTREME_PCT = 0.02  # "no extremo 52w" = a 2% do high/low
INDEX_TICKERS: tuple[str, ...] = ("SPY", "QQQ", "DIA", "IWM")
INDEX_NAMES = {"SPY": "S&P 500", "QQQ": "Nasdaq 100", "DIA": "Dow Jones", "IWM": "Russell 2000"}
SPARK_POINTS = 30


@dataclass(frozen=True)
class OverviewRow:
    """Um constituinte com os 2 últimos closes, volume do dia e extremos 52w."""

    ticker: str
    name: str | None
    sector: str | None
    last: float
    prev: float
    volume: int
    high_52w: float
    low_52w: float
    as_of: dt.date


class RankedOverview(TypedDict):
    as_of: dt.date | None
    most_active: list[LeaderRow]
    gainers: list[LeaderRow]
    losers: list[LeaderRow]
    highs_52w: list[LeaderRow]
    lows_52w: list[LeaderRow]
    sectors: list[SectorPerf]
    breadth: MarketBreadth | None


def _breadth(liquid: list[OverviewRow]) -> MarketBreadth | None:
    """Amplitude do dia sobre o mesmo universo líquido do ranking.

    Avançam/recuam por variação do close; novas máximas/mínimas por toque no
    extremo 52w; up-volume share = fração do volume total negociada em altas.
    """
    if not liquid:
        return None
    advancing = declining = unchanged = 0
    new_highs = new_lows = 0
    up_volume = 0.0
    total_volume = 0.0
    for r in liquid:
        total_volume += r.volume
        if r.last > r.prev:
            advancing += 1
            up_volume += r.volume
        elif r.last < r.prev:
            declining += 1
        else:
            unchanged += 1
        if r.high_52w > 0 and r.last >= r.high_52w:
            new_highs += 1
        if r.low_52w > 0 and r.last <= r.low_52w:
            new_lows += 1
    return MarketBreadth(
        tracked=len(liquid),
        advancing=advancing,
        declining=declining,
        unchanged=unchanged,
        advance_decline_ratio=(advancing / declining) if declining else float(advancing),
        new_highs_52w=new_highs,
        new_lows_52w=new_lows,
        up_volume_share=(up_volume / total_volume) if total_volume > 0 else 0.0,
    )


async def fetch_overview_rows(session: AsyncSession) -> list[OverviewRow]:
    """Lê eod_prices ⋈ universe ativos e monta uma OverviewRow por ticker."""
    max_date = await session.scalar(
        select(func.max(EodPrice.date))
        .join(UniverseConstituent, UniverseConstituent.ticker == EodPrice.ticker)
        .where(UniverseConstituent.status == "active")
    )
    if max_date is None:
        return []

    recent = await session.execute(
        select(
            EodPrice.ticker, EodPrice.date, EodPrice.close, EodPrice.volume,
            UniverseConstituent.name, UniverseConstituent.sector,
        )
        .join(UniverseConstituent, UniverseConstituent.ticker == EodPrice.ticker)
        .where(
            UniverseConstituent.status == "active",
            EodPrice.date >= max_date - dt.timedelta(days=RECENT_WINDOW_DAYS),
        )
        .order_by(EodPrice.ticker, EodPrice.date.desc())
    )
    extremes = await session.execute(
        select(EodPrice.ticker, func.max(EodPrice.close), func.min(EodPrice.close))
        .join(UniverseConstituent, UniverseConstituent.ticker == EodPrice.ticker)
        .where(
            UniverseConstituent.status == "active",
            EodPrice.date >= max_date - dt.timedelta(days=LOOKBACK_52W_DAYS),
        )
        .group_by(EodPrice.ticker)
    )
    extreme_by_ticker = {t: (hi, lo) for t, hi, lo in extremes.all()}

    # recent vem DESC por data dentro de cada ticker: 1ª linha = last, 2ª = prev.
    seen: dict[str, list[tuple[dt.date, float, int, str | None, str | None]]] = defaultdict(list)
    for ticker, date, close, volume, name, sector in recent.all():
        if len(seen[ticker]) < 2:
            seen[ticker].append((date, close, volume, name, sector))

    rows: list[OverviewRow] = []
    for ticker, points in seen.items():
        if len(points) < 2 or ticker not in extreme_by_ticker:
            continue
        (d1, last, volume, name, sector), (_, prev, *_rest) = points[0], points[1]
        if prev <= 0:
            continue
        hi, lo = extreme_by_ticker[ticker]
        rows.append(OverviewRow(
            ticker=ticker, name=name, sector=sector, last=last, prev=prev,
            volume=int(volume), high_52w=hi, low_52w=lo, as_of=d1,
        ))
    return rows


async def fetch_index_rows(session: AsyncSession) -> list[IndexCard]:
    """Últimos SPARK_POINTS closes de cada ETF de índice já presente no DB local."""
    cards: list[IndexCard] = []
    for ticker in INDEX_TICKERS:
        result = await session.execute(
            select(EodPrice.close)
            .where(EodPrice.ticker == ticker)
            .order_by(EodPrice.date.desc())
            .limit(SPARK_POINTS)
        )
        closes = [float(c) for (c,) in result.all()][::-1]  # ASC novamente
        if len(closes) < 2:
            continue
        cards.append(IndexCard(
            ticker=ticker, name=INDEX_NAMES[ticker], last=closes[-1],
            change_pct=closes[-1] / closes[-2] - 1, spark=closes,
        ))
    return cards


def _leader(row: OverviewRow) -> LeaderRow:
    return LeaderRow(
        ticker=row.ticker, name=row.name, sector=row.sector, last=row.last,
        change=row.last - row.prev, change_pct=row.last / row.prev - 1,
        volume=row.volume, high_52w=row.high_52w, low_52w=row.low_52w,
    )


def rank_overview(rows: list[OverviewRow]) -> RankedOverview:
    """Ranking puro: aplica o piso de liquidez e monta as seis listas."""
    liquid = [
        r for r in rows
        if r.last >= PRICE_FLOOR and r.last * r.volume >= MIN_DOLLAR_VOLUME
    ]
    by_chg = sorted(liquid, key=lambda r: r.last / r.prev - 1, reverse=True)
    by_dollar_vol = sorted(liquid, key=lambda r: r.last * r.volume, reverse=True)
    at_high = sorted(
        (r for r in liquid if r.high_52w > 0 and r.last >= r.high_52w * (1 - NEAR_EXTREME_PCT)),
        key=lambda r: r.last / r.high_52w, reverse=True,
    )
    at_low = sorted(
        (r for r in liquid if r.low_52w > 0 and r.last <= r.low_52w * (1 + NEAR_EXTREME_PCT)),
        key=lambda r: r.last / r.low_52w,
    )

    by_sector: dict[str, list[float]] = defaultdict(list)
    for r in liquid:
        if r.sector:
            by_sector[r.sector].append(r.last / r.prev - 1)
    sectors = sorted(
        (
            SectorPerf(sector=s, change_pct_median=statistics.median(v), n=len(v))
            for s, v in by_sector.items()
        ),
        key=lambda s: s.change_pct_median, reverse=True,
    )

    return RankedOverview(
        as_of=max((r.as_of for r in rows), default=None),
        most_active=[_leader(r) for r in by_dollar_vol[:TOP_N]],
        gainers=[_leader(r) for r in by_chg[:TOP_N] if r.last > r.prev],
        losers=[_leader(r) for r in by_chg[::-1][:TOP_N] if r.last < r.prev],
        highs_52w=[_leader(r) for r in at_high[:TOP_N]],
        lows_52w=[_leader(r) for r in at_low[:TOP_N]],
        sectors=sectors,
        breadth=_breadth(liquid),
    )
