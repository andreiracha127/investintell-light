"""Market overview / history schemas (Stocks redesign — landing /stocks)."""

import datetime as dt
import uuid
from typing import Literal

from pydantic import BaseModel


class IndexCard(BaseModel):
    ticker: str
    name: str
    last: float
    change_pct: float  # fração decimal (0.012 = +1.2%)
    spark: list[float]  # ~30 closes, do mais antigo ao mais novo


class LeaderRow(BaseModel):
    ticker: str
    name: str | None
    sector: str | None
    last: float
    change: float  # absoluto
    change_pct: float  # fração decimal
    volume: int  # ações negociadas no dia as_of
    high_52w: float
    low_52w: float


class SectorPerf(BaseModel):
    sector: str
    change_pct_median: float  # fração decimal
    n: int  # constituintes líquidos com dado


class MarketOverviewResponse(BaseModel):
    as_of: dt.date | None  # None = universo sem preços (pré-backfill)
    universe_size: int
    indices: list[IndexCard]
    most_active: list[LeaderRow]
    gainers: list[LeaderRow]
    losers: list[LeaderRow]
    highs_52w: list[LeaderRow]
    lows_52w: list[LeaderRow]
    sectors: list[SectorPerf]


class HistoryBar(BaseModel):
    t: int  # epoch ms UTC do pregão
    o: float
    h: float
    l: float  # noqa: E741 — campo do contrato {t,o,h,l,c,v}
    c: float
    v: int


class HistoryResponse(BaseModel):
    ticker: str
    count: int
    bars: list[HistoryBar]


class FundHistoryResponse(BaseModel):
    instrument_id: uuid.UUID
    ticker: str | None  # mutual funds podem não ter ticker
    mode: Literal["ohlcv", "nav"]  # ohlcv = ETF (eod_prices); nav = fund_nav
    count: int
    bars: list[HistoryBar]


class SymbolSearchResult(BaseModel):
    symbol: str
    name: str | None
    kind: str  # "stock" | "etf" | "mutual_fund" | "mmf" (fund_type passa direto)
    instrument_id: uuid.UUID | None  # None para stocks
