# Stocks Redesign (padrão Barchart) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Landing `/stocks` estilo Barchart (índices + market leaders + setores, preços ao vivo) e detalhe `/stocks/[ticker]` abrindo direto num chart interativo canvas (port do IXChart) com as métricas existentes abaixo.

**Architecture:** O Light backend (FastAPI) ganha `GET /stocks/overview` (lê tabelas locais `universe_constituents` + `eod_prices`) e `GET /stocks/{ticker}/history` (OHLCV ajustado, contrato `{t,o,h,l,c,v}`). O frontend porta o engine canvas do protótipo (`E:\investintell-datalake-workers\design\assets\chart-engine.js`) para `src/lib/ixchart/`, adiciona um cliente WebSocket compartilhado para o livefeed worker em produção e monta as duas páginas. O repo workers NÃO é alterado.

**Tech Stack:** FastAPI + SQLAlchemy async + alembic (backend); Next.js 15 App Router, React 19, TanStack Query 5, Tailwind 4, canvas 2D puro, vitest (novo dev-dep) (frontend). WS: `wss://livefeed-production-2c39.up.railway.app/stream`.

**Spec:** `docs/superpowers/specs/2026-06-12-stocks-redesign-design.md`

**Working dir:** tudo em `E:\investintell-light` (backend roda com `uv run` a partir de `backend/`; frontend com `npm` a partir de `frontend/`).

---

## File Structure

**Backend (`backend/`):**

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `alembic/versions/0011_universe_sector.py` | Create | coluna `sector` em `universe_constituents` |
| `app/models/universe.py` | Modify | campo `sector` no ORM |
| `scripts/enrich_sectors.py` | Create | ticker→GICS de `sec_cusip_ticker_map` (data lake) → UPDATE local |
| `app/schemas/market.py` | Create | response models do overview e history |
| `app/services/market_overview.py` | Create | SQL readers finos + `rank_overview` puro (unit-tested) |
| `app/api/routes/stocks.py` | Modify | rotas `GET /stocks/overview` e `GET /stocks/{ticker}/history` |
| `app/core/cache.py` | Modify | prefixo `/stocks/overview` no cache de catálogo |
| `tests/test_market_overview_service.py` | Create | ranking puro |
| `tests/test_stocks_overview_route.py` | Create | rota overview (service stubado) |
| `tests/test_stocks_history_route.py` | Create | rota history (selectors stubados) |

**Frontend (`frontend/`):**

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `vitest.config.ts`, `package.json` | Create/Modify | runner de testes p/ lógica pura |
| `src/lib/ixchart/types.ts` | Create | `Bar`, `Tick`, tipos do engine |
| `src/lib/ixchart/series.ts` | Create | resample/sma/rsi/niceTicks/formatadores (puros) |
| `src/lib/ixchart/series.test.ts` | Create | testes das funções puras |
| `src/lib/ixchart/tokens.ts` | Create | leitura dos design tokens p/ canvas |
| `src/lib/ixchart/engine.ts` | Create | classe `Chart` (port do protótipo) |
| `src/lib/livefeed/client.ts` | Create | WS compartilhado, ref-count, backoff, filtro `source:"sim"` |
| `src/lib/livefeed/client.test.ts` | Create | teste do `parseTick` |
| `src/lib/livefeed/useLiveTicks.ts` | Create | hook React com throttle rAF |
| `src/components/charts/InteractiveChart.tsx` | Create | canvas + toolbar + legenda OHLC + live |
| `src/components/stocks/AddToPortfolio.tsx` | Create | popover portfólio + quantidade → `putPosition` |
| `src/components/stocks/IndexStrip.tsx` | Create | cards SPY/QQQ/DIA/IWM com sparkline |
| `src/components/stocks/LeadersTable.tsx` | Create | tabs Most Active/Gainers/Losers/52w H/L |
| `src/components/stocks/SectorPanel.tsx` | Create | barras de % dia por setor |
| `src/components/stocks/MarketOverview.tsx` | Create | composição da landing (query + skeleton + erro) |
| `src/app/stocks/page.tsx` | Create | rota `/stocks` |
| `src/components/stocks/StockAnalysisView.tsx` | Modify | chart interativo no topo, header live, range único |
| `src/components/shell/AppShell.tsx` | Modify | nav "Stocks" → `/stocks` |
| `src/lib/api/client.ts` | Modify | `fetchMarketOverview`, `fetchStockHistory` + tipos |

---

### Task 0: Branch

- [ ] **Step 0.1:** A partir do HEAD atual de `investintell-light` (branch `feature/analytics-charts-echarts6`, que já contém o spec):

```bash
cd /e/investintell-light && git checkout -b feat/stocks-redesign
```

---

### Task 1: Migration + modelo — `universe_constituents.sector`

**Files:**
- Create: `backend/alembic/versions/0011_universe_sector.py`
- Modify: `backend/app/models/universe.py` (classe `UniverseConstituent`)

- [ ] **Step 1.1: Verificar head atual do alembic**

```bash
cd /e/investintell-light/backend && uv run alembic heads
```
Expected: `0011` ainda não existe; head é `0010`. Se o head for outro, use-o em `down_revision`.

- [ ] **Step 1.2: Criar a migration** — `backend/alembic/versions/0011_universe_sector.py`:

```python
"""universe_constituents.sector — setor GICS por ticker

Revision ID: 0011
Revises: 0010

Setor real (GICS) por constituinte do universo do screener, populado pelo
scripts/enrich_sectors.py a partir de sec_cusip_ticker_map (data lake,
resolvida via OpenFIGI + Tiingo meta). NULL quando o ticker está fora do
mapa — o painel de setores da landing /stocks simplesmente o ignora.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "universe_constituents",
        sa.Column("sector", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("universe_constituents", "sector")
```

- [ ] **Step 1.3: Adicionar o campo ao ORM** — em `backend/app/models/universe.py`, dentro de `UniverseConstituent`, logo após o campo `name`:

```python
    # Setor GICS (11 setores) via sec_cusip_ticker_map do data-lake —
    # populado por scripts/enrich_sectors.py; NULL = fora do mapa.
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 1.4: Aplicar e validar**

```bash
cd /e/investintell-light/backend && uv run alembic upgrade head && uv run pytest tests/test_models.py -q
```
Expected: migration aplica sem erro; testes de modelo passam.

- [ ] **Step 1.5: Commit**

```bash
cd /e/investintell-light && git add backend/alembic/versions/0011_universe_sector.py backend/app/models/universe.py && git commit -m "feat(backend): coluna sector em universe_constituents (GICS)"
```

---

### Task 2: `scripts/enrich_sectors.py`

**Files:**
- Create: `backend/scripts/enrich_sectors.py`

Sem teste automatizado (script batch fora do request path, padrão do repo — `sync_universe.py` e `backfill_universe_eod.py` também não têm); validação é o run real do Step 2.2.

- [ ] **Step 2.1: Criar o script**

```python
"""Enrich universe_constituents.sector from the data-lake sec_cusip_ticker_map.

Run from backend/:
    uv run python scripts/enrich_sectors.py            # real run (writes)
    uv run python scripts/enrich_sectors.py --dry-run  # counts only

Requires DATALAKE_DB_URL (read-only data-lake) and the local DB. The map has
~7.0k tickers with GICS sector (11 sectors); coverage over the ~5k-ticker
universe is reported at the end. mode() picks the most common sector when a
ticker maps to several CUSIPs.
"""

import argparse
import asyncio
import logging
import pathlib
import sys

_BACKEND_ROOT = pathlib.Path(__file__).parent.parent
if str(_BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(_BACKEND_ROOT))

from sqlalchemy import text  # noqa: E402

from app.core.db import AsyncSessionLocal  # noqa: E402
from app.core.datalake import get_datalake_session  # noqa: E402

logger = logging.getLogger("enrich_sectors")

SECTOR_MAP_SQL = text("""
    SELECT upper(ticker) AS ticker,
           mode() WITHIN GROUP (ORDER BY gics_sector) AS sector
    FROM sec_cusip_ticker_map
    WHERE ticker IS NOT NULL AND gics_sector IS NOT NULL
    GROUP BY upper(ticker)
""")

UPDATE_SQL = text("""
    UPDATE universe_constituents AS u
    SET sector = :sector
    WHERE u.ticker = :ticker AND (u.sector IS DISTINCT FROM :sector)
""")

COVERAGE_SQL = text("""
    SELECT count(*) AS total, count(sector) AS with_sector
    FROM universe_constituents WHERE status = 'active'
""")


async def run(dry_run: bool) -> None:
    async for datalake in get_datalake_session():
        rows = (await datalake.execute(SECTOR_MAP_SQL)).all()
    logger.info("sec_cusip_ticker_map: %d tickers com setor", len(rows))
    if dry_run:
        return
    async with AsyncSessionLocal() as session:
        for ticker, sector in rows:
            await session.execute(UPDATE_SQL, {"ticker": ticker, "sector": sector})
        await session.commit()
        total, with_sector = (await session.execute(COVERAGE_SQL)).one()
    logger.info("cobertura: %d/%d constituintes ativos com setor", with_sector, total)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(run(dry_run=args.dry_run))


if __name__ == "__main__":
    main()
```

Nota: `get_datalake_session` levanta `HTTPException` 503 se `DATALAKE_DB_URL` não estiver setada — em script isso aborta com traceback claro, aceitável (fail loud).

- [ ] **Step 2.2: Rodar dry-run e run real**

```bash
cd /e/investintell-light/backend && uv run python scripts/enrich_sectors.py --dry-run && uv run python scripts/enrich_sectors.py
```
Expected: `sec_cusip_ticker_map: ~7000 tickers com setor` e `cobertura: >3500/~5000`.

- [ ] **Step 2.3: Commit**

```bash
cd /e/investintell-light && git add backend/scripts/enrich_sectors.py && git commit -m "feat(backend): enrich_sectors — GICS por ticker via sec_cusip_ticker_map"
```

---

### Task 3: Schemas + service `market_overview` (TDD no ranking puro)

**Files:**
- Create: `backend/app/schemas/market.py`
- Create: `backend/app/services/market_overview.py`
- Test: `backend/tests/test_market_overview_service.py`

- [ ] **Step 3.1: Criar os schemas** — `backend/app/schemas/market.py`:

```python
"""Market overview / history schemas (Stocks redesign — landing /stocks)."""

import datetime as dt

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
    l: float
    c: float
    v: int


class HistoryResponse(BaseModel):
    ticker: str
    count: int
    bars: list[HistoryBar]
```

- [ ] **Step 3.2: Escrever os testes do ranking puro** — `backend/tests/test_market_overview_service.py`:

```python
"""Tests do ranking puro do market overview (sem DB)."""

import datetime as dt

import pytest

from app.services.market_overview import (
    MIN_DOLLAR_VOLUME,
    PRICE_FLOOR,
    OverviewRow,
    rank_overview,
)

AS_OF = dt.date(2026, 6, 11)


def _row(ticker: str, last: float, prev: float, *, volume: int = 10_000_000,
         high: float | None = None, low: float | None = None,
         sector: str | None = "Information Technology") -> OverviewRow:
    return OverviewRow(
        ticker=ticker, name=f"{ticker} Inc", sector=sector,
        last=last, prev=prev, volume=volume,
        high_52w=high if high is not None else max(last, prev) * 1.3,
        low_52w=low if low is not None else min(last, prev) * 0.7,
        as_of=AS_OF,
    )


def test_gainers_losers_sorted_by_change_pct() -> None:
    rows = [_row("UP9", 109, 100), _row("UP5", 105, 100), _row("DN7", 93, 100)]
    out = rank_overview(rows)
    assert [r.ticker for r in out["gainers"][:2]] == ["UP9", "UP5"]
    assert out["losers"][0].ticker == "DN7"
    assert out["gainers"][0].change_pct == pytest.approx(0.09)
    assert out["as_of"] == AS_OF


def test_liquidity_floor_excludes_penny_and_thin_volume() -> None:
    rows = [
        _row("PENNY", 4.40, 4.00),                       # < PRICE_FLOOR
        _row("THIN", 200.0, 100.0, volume=1_000),        # dollar vol < MIN_DOLLAR_VOLUME
        _row("OK", 101.0, 100.0),
    ]
    out = rank_overview(rows)
    tickers = {r.ticker for r in out["gainers"]}
    assert tickers == {"OK"}
    assert PRICE_FLOOR == 5.0 and MIN_DOLLAR_VOLUME == 5_000_000.0


def test_most_active_ranked_by_dollar_volume() -> None:
    rows = [
        _row("BIG", 100.0, 100.0, volume=50_000_000),
        _row("MID", 100.0, 100.0, volume=20_000_000),
    ]
    out = rank_overview(rows)
    assert [r.ticker for r in out["most_active"]] == ["BIG", "MID"]


def test_52w_lists_rank_by_proximity_to_extreme() -> None:
    rows = [
        _row("ATHI", 130.0, 128.0, high=130.0, low=80.0),   # no topo
        _row("NEAR", 127.0, 126.0, high=130.0, low=80.0),   # perto
        _row("ATLO", 80.0, 81.0, high=130.0, low=80.0),     # no fundo
        _row("MID", 100.0, 100.0, high=130.0, low=80.0),    # longe de ambos
    ]
    out = rank_overview(rows)
    highs = [r.ticker for r in out["highs_52w"]]
    lows = [r.ticker for r in out["lows_52w"]]
    assert highs[0] == "ATHI" and "ATLO" not in highs
    assert lows[0] == "ATLO" and "ATHI" not in lows
    assert "MID" not in highs and "MID" not in lows  # fora da janela de 2%


def test_sectors_median_and_null_sector_ignored() -> None:
    rows = [
        _row("A", 102, 100, sector="Energy"),
        _row("B", 104, 100, sector="Energy"),
        _row("C", 106, 100, sector="Energy"),
        _row("D", 99, 100, sector=None),
    ]
    out = rank_overview(rows)
    assert len(out["sectors"]) == 1
    sec = out["sectors"][0]
    assert sec.sector == "Energy" and sec.n == 3
    assert sec.change_pct_median == pytest.approx(0.04)


def test_empty_rows_yield_empty_overview() -> None:
    out = rank_overview([])
    assert out["as_of"] is None
    assert out["gainers"] == [] and out["sectors"] == []
```

- [ ] **Step 3.3: Rodar e ver falhar**

```bash
cd /e/investintell-light/backend && uv run pytest tests/test_market_overview_service.py -q
```
Expected: FAIL — `ModuleNotFoundError: app.services.market_overview`.

- [ ] **Step 3.4: Implementar o service** — `backend/app/services/market_overview.py`:

```python
"""Market overview assembly (landing /stocks).

DB-first sobre tabelas LOCAIS (universe_constituents + eod_prices), mantidas
pelo pipeline batch existente (sync_universe.py + backfill_universe_eod.py).
Nenhuma chamada Tiingo aqui — o warm dos índices é responsabilidade da rota.

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
from app.schemas.market import IndexCard, LeaderRow, SectorPerf

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
    """Últimos SPARK_POINTS closes de cada ETF de índice (warm é da rota)."""
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
    )
```

- [ ] **Step 3.5: Rodar e ver passar**

```bash
cd /e/investintell-light/backend && uv run pytest tests/test_market_overview_service.py -q
```
Expected: 6 passed.

- [ ] **Step 3.6: Commit**

```bash
cd /e/investintell-light && git add backend/app/schemas/market.py backend/app/services/market_overview.py backend/tests/test_market_overview_service.py && git commit -m "feat(backend): service market_overview — ranking puro + readers SQL"
```

---

### Task 4: Rota `GET /stocks/overview` + cache

**Files:**
- Modify: `backend/app/api/routes/stocks.py`
- Modify: `backend/app/core/cache.py` (`CACHED_GET_PREFIXES`)
- Test: `backend/tests/test_stocks_overview_route.py`

- [ ] **Step 4.1: Escrever os testes da rota** — `backend/tests/test_stocks_overview_route.py` (padrão `test_macro_regime_route.py`: dependências sobrescritas, service monkeypatched, sem DB):

```python
"""Tests de GET /stocks/overview (service stubado, sem DB/Tiingo)."""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.schemas.market import IndexCard, LeaderRow, SectorPerf
from app.services import market_overview as mo
from app.tiingo.exceptions import TiingoError


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _leader(ticker: str = "NVDA") -> LeaderRow:
    return LeaderRow(ticker=ticker, name="NVIDIA", sector="Information Technology",
                     last=171.4, change=4.2, change_pct=0.0251, volume=160_000_000,
                     high_52w=190.0, low_52w=90.0)


def _patch_happy(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_rows(session):
        return ["sentinel"]

    async def fake_indices(session):
        return [IndexCard(ticker="SPY", name="S&P 500", last=672.3,
                          change_pct=0.004, spark=[670.0, 672.3])]

    def fake_rank(rows):
        assert rows == ["sentinel"]
        return mo.RankedOverview(
            as_of=dt.date(2026, 6, 11), most_active=[_leader()], gainers=[_leader()],
            losers=[], highs_52w=[], lows_52w=[],
            sectors=[SectorPerf(sector="Energy", change_pct_median=0.01, n=12)],
        )

    monkeypatch.setattr(mo, "fetch_overview_rows", fake_rows)
    monkeypatch.setattr(mo, "fetch_index_rows", fake_indices)
    monkeypatch.setattr(mo, "rank_overview", fake_rank)


@pytest.mark.anyio
async def test_overview_assembles_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _patch_happy(monkeypatch)

    async def fake_ensure(session, client, symbols, start, end):
        assert set(symbols) == set(mo.INDEX_TICKERS)

    import app.api.routes.stocks as stocks_routes
    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)

    async with _client() as client:
        resp = await client.get("/stocks/overview")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of"] == "2026-06-11"
    assert body["gainers"][0]["ticker"] == "NVDA"
    assert body["indices"][0]["ticker"] == "SPY"
    assert body["sectors"][0]["sector"] == "Energy"
    assert body["universe_size"] == 1


@pytest.mark.anyio
async def test_overview_degrades_indices_when_tiingo_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Índices são painel secundário: falha da Tiingo degrada para [], não 5xx."""
    _patch_happy(monkeypatch)

    async def fake_ensure(session, client, symbols, start, end):
        raise TiingoError("down")

    import app.api.routes.stocks as stocks_routes
    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)

    async with _client() as client:
        resp = await client.get("/stocks/overview")
    assert resp.status_code == 200
    assert resp.json()["indices"] == []
    assert resp.json()["gainers"][0]["ticker"] == "NVDA"
```

Nota: `_ensure_eod_or_http_error` levanta `HTTPException` (não `TiingoError`) nos caminhos reais — o teste usa `TiingoError` para exercitar o catch amplo do degrade; a rota captura `HTTPException` E `TiingoError` (ver Step 4.3).

- [ ] **Step 4.2: Rodar e ver falhar**

```bash
cd /e/investintell-light/backend && uv run pytest tests/test_stocks_overview_route.py -q
```
Expected: FAIL — 404 (rota não existe).

- [ ] **Step 4.3: Implementar a rota** — em `backend/app/api/routes/stocks.py`.

Imports novos no topo (juntar aos existentes):

```python
from app.schemas.market import HistoryBar, HistoryResponse, MarketOverviewResponse
from app.services import market_overview
```

Rota, inserida ANTES das rotas `/{ticker}/...` (clareza; não há colisão de path de fato):

```python
# ---------------------------------------------------------------------------
# Market overview (landing /stocks)
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=MarketOverviewResponse)
async def get_market_overview(
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> MarketOverviewResponse:
    """Payload único da landing /stocks — leaders/setores das tabelas locais.

    Leaders e setores leem eod_prices ⋈ universe_constituents (pipeline batch
    F6.2); ficam tão frescos quanto o último backfill. Os 4 ETFs de índice são
    painel SECUNDÁRIO: warm on-demand via ensure_eod, e falha da Tiingo degrada
    para indices=[] com warning (degradação declarada, como o news stale).
    """
    indices: list = []
    today = dt.date.today()
    try:
        await _ensure_eod_or_http_error(
            session, client, list(market_overview.INDEX_TICKERS),
            today - dt.timedelta(days=60), today,
        )
        indices = await market_overview.fetch_index_rows(session)
    except (HTTPException, TiingoError) as exc:
        logger.warning("Index strip degraded (ensure/fetch failed): %s", exc)

    rows = await market_overview.fetch_overview_rows(session)
    ranked = market_overview.rank_overview(rows)
    return MarketOverviewResponse(universe_size=len(rows), indices=indices, **ranked)
```

- [ ] **Step 4.4: Cachear o overview** — em `backend/app/core/cache.py`, estender a tupla:

```python
CACHED_GET_PREFIXES: tuple[str, ...] = (
    "/funds",
    "/macro/regime",
    "/stocks/overview",
)
```

CUIDADO: `/stocks/overview` é mais específico que `/stocks` de propósito — `/stocks/{ticker}/analysis` etc. NÃO devem entrar no cache de catálogo.

- [ ] **Step 4.5: Rodar testes (rota + cache existente)**

```bash
cd /e/investintell-light/backend && uv run pytest tests/test_stocks_overview_route.py tests/test_catalog_cache.py -q
```
Expected: PASS (o autouse `_reset_catalog_cache` do conftest evita vazamento entre testes).

- [ ] **Step 4.6: Commit**

```bash
cd /e/investintell-light && git add backend/app/api/routes/stocks.py backend/app/core/cache.py backend/tests/test_stocks_overview_route.py && git commit -m "feat(backend): GET /stocks/overview — leaders, índices e setores com cache"
```

---

### Task 5: Rota `GET /stocks/{ticker}/history`

**Files:**
- Modify: `backend/app/api/routes/stocks.py`
- Test: `backend/tests/test_stocks_history_route.py`

- [ ] **Step 5.1: Escrever os testes** — `backend/tests/test_stocks_history_route.py`:

```python
"""Tests de GET /stocks/{ticker}/history (selectors stubados, sem DB/Tiingo)."""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app

import app.api.routes.stocks as stocks_routes


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _rows() -> list[tuple]:
    # (date, adj_open, adj_high, adj_low, adj_close, adj_volume)
    return [
        (dt.date(2026, 6, 10), 100.0, 105.0, 99.0, 104.0, 1_000_000),
        (dt.date(2026, 6, 11), 104.0, 106.0, 103.0, 105.5, 1_200_000),
    ]


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def fake_ensure(session, client, symbols, start, end):
        assert symbols == ["TSLA"]

    async def fake_select(session, ticker, start, end):
        assert ticker == "TSLA"
        return _rows()

    monkeypatch.setattr(stocks_routes, "_ensure_eod_or_http_error", fake_ensure)
    monkeypatch.setattr(stocks_routes, "_select_adj_ohlcv_rows", fake_select)


@pytest.mark.anyio
async def test_history_contract_t_o_h_l_c_v() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/tsla/history?bars=760")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "TSLA" and body["count"] == 2
    bar = body["bars"][-1]
    # t = epoch ms UTC de 2026-06-11
    assert bar["t"] == int(dt.datetime(2026, 6, 11, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (104.0, 106.0, 103.0, 105.5, 1_200_000)


@pytest.mark.anyio
async def test_history_truncates_to_bars_param() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/TSLA/history?bars=30")
    # 2 linhas stubadas < 30 → todas voltam; o recorte é dos N MAIS RECENTES
    assert resp.json()["count"] == 2


@pytest.mark.anyio
async def test_history_404_when_no_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(session, ticker, start, end):
        return []

    monkeypatch.setattr(stocks_routes, "_select_adj_ohlcv_rows", empty)
    async with _client() as client:
        resp = await client.get("/stocks/ZZZZ/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_history_bars_validation() -> None:
    async with _client() as client:
        resp = await client.get("/stocks/TSLA/history?bars=2")
    assert resp.status_code == 422
```

- [ ] **Step 5.2: Rodar e ver falhar**

```bash
cd /e/investintell-light/backend && uv run pytest tests/test_stocks_history_route.py -q
```
Expected: FAIL — 404/AttributeError (rota e selector não existem).

- [ ] **Step 5.3: Implementar selector + rota** — em `backend/app/api/routes/stocks.py`, após `_select_ohlcv_rows`:

```python
async def _select_adj_ohlcv_rows(
    session: AsyncSession, ticker: str, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float, float, float, float, int]]:
    """(date, adj_open, adj_high, adj_low, adj_close, adj_volume) em [start, end].

    Ajustado, não cru: contínuo em splits/dividendos E coincide com os ticks
    ao vivo na barra corrente (a Tiingo ancora o ajuste no presente).
    """
    result = await session.execute(
        select(
            EodPrice.date,
            EodPrice.adj_open,
            EodPrice.adj_high,
            EodPrice.adj_low,
            EodPrice.adj_close,
            EodPrice.adj_volume,
        )
        .where(EodPrice.ticker == ticker, EodPrice.date >= start, EodPrice.date <= end)
        .order_by(EodPrice.date)
    )
    return list(result.tuples().all())
```

Rota (logo após `get_market_overview`):

```python
@router.get("/{ticker}/history", response_model=HistoryResponse)
async def get_stock_history(
    ticker: str,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    bars: Annotated[
        int, Query(ge=30, le=5000, description="Nº de barras diárias mais recentes.")
    ] = 760,
) -> HistoryResponse:
    """OHLCV diário ajustado no contrato do chart interativo ({t,o,h,l,c,v}).

    Resample semanal/mensal é client-side (engine). t = epoch ms UTC do pregão.
    """
    symbol = ticker.strip().upper()
    today = dt.date.today()
    # ~252 pregões/ano → 1.6 dias-calendário por barra cobre feriados com folga.
    start = today - dt.timedelta(days=int(bars * 1.6) + 10)
    await _ensure_eod_or_http_error(session, client, [symbol], start, today)

    rows = await _select_adj_ohlcv_rows(session, symbol, start, today)
    if not rows:
        raise HTTPException(status_code=404, detail=f"No price data available for {symbol}.")
    rows = rows[-bars:]

    def _ms(d: dt.date) -> int:
        return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)

    return HistoryResponse(
        ticker=symbol,
        count=len(rows),
        bars=[
            HistoryBar(t=_ms(d), o=o, h=h, l=lo, c=c, v=int(v or 0))
            for d, o, h, lo, c, v in rows
        ],
    )
```

- [ ] **Step 5.4: Rodar e ver passar (suíte backend inteira)**

```bash
cd /e/investintell-light/backend && uv run pytest -q
```
Expected: PASS (sem regressões).

- [ ] **Step 5.5: Commit**

```bash
cd /e/investintell-light && git add backend/app/api/routes/stocks.py backend/tests/test_stocks_history_route.py && git commit -m "feat(backend): GET /stocks/{ticker}/history — OHLCV ajustado p/ chart interativo"
```

---

### Task 6: OpenAPI regen + client do frontend

**Files:**
- Modify: `backend/openapi.json` (gerado)
- Modify: `frontend/src/lib/api/api.d.ts` (gerado)
- Modify: `frontend/src/lib/api/client.ts`

- [ ] **Step 6.1: Regenerar contrato e tipos**

```bash
cd /e/investintell-light/backend && uv run python scripts/export_openapi.py && cd ../frontend && npm run types
```
Expected: `api.d.ts` ganha `"/stocks/overview"` e `"/stocks/{ticker}/history"`.

- [ ] **Step 6.2: Tipos + fetchers no client** — em `frontend/src/lib/api/client.ts`. Na seção de type aliases (seguir o padrão dos existentes, que derivam de `paths`):

```ts
type MarketOverviewOperation = paths["/stocks/overview"]["get"];
export type MarketOverview =
  MarketOverviewOperation["responses"]["200"]["content"]["application/json"];
export type LeaderRow = MarketOverview["gainers"][number];
export type IndexCard = MarketOverview["indices"][number];
export type SectorPerf = MarketOverview["sectors"][number];

type StockHistoryOperation = paths["/stocks/{ticker}/history"]["get"];
export type StockHistory =
  StockHistoryOperation["responses"]["200"]["content"]["application/json"];
export type HistoryBar = StockHistory["bars"][number];
```

E os fetchers, junto de `fetchStockAnalysis`:

```ts
export function fetchMarketOverview(signal?: AbortSignal): Promise<MarketOverview> {
  return request<MarketOverview>("/stocks/overview", signal);
}

export function fetchStockHistory(
  ticker: string,
  bars = 2520,
  signal?: AbortSignal,
): Promise<StockHistory> {
  return request<StockHistory>(
    `/stocks/${encodeURIComponent(ticker)}/history?bars=${bars}`,
    signal,
  );
}
```

(Se `paths` ainda não estiver importado no topo, adicione-o ao import de `./api` existente.)

- [ ] **Step 6.3: Typecheck**

```bash
cd /e/investintell-light/frontend && npm run typecheck
```
Expected: PASS.

- [ ] **Step 6.4: Commit**

```bash
cd /e/investintell-light && git add backend/openapi.json frontend/src/lib/api/api.d.ts frontend/src/lib/api/client.ts && git commit -m "feat(frontend): tipos e fetchers de market overview e stock history"
```

---

### Task 7: vitest + `src/lib/ixchart/series.ts` (puro, TDD)

**Files:**
- Create: `frontend/vitest.config.ts`
- Modify: `frontend/package.json` (devDep + script)
- Create: `frontend/src/lib/ixchart/types.ts`
- Create: `frontend/src/lib/ixchart/series.ts`
- Test: `frontend/src/lib/ixchart/series.test.ts`

- [ ] **Step 7.1: Instalar vitest e configurar**

```bash
cd /e/investintell-light/frontend && npm install -D vitest
```

`frontend/vitest.config.ts`:

```ts
import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  resolve: { alias: { "@": path.resolve(__dirname, "src") } },
  test: { include: ["src/**/*.test.ts"] },
});
```

Em `frontend/package.json`, adicionar ao bloco `scripts`:

```json
"test": "vitest run"
```

- [ ] **Step 7.2: Criar os tipos** — `frontend/src/lib/ixchart/types.ts`:

```ts
/** Barra OHLCV — mesmo contrato do GET /stocks/{ticker}/history. */
export interface Bar {
  t: number; // epoch ms UTC
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export type ChartType = "candles" | "ohlc" | "line" | "area";
export type Period = "D" | "W" | "M";
export type DrawTool = "trend" | "hline" | "fib" | "measure";

export interface DrawPoint {
  i: number; // índice fracionário da barra
  p: number; // preço
}

export interface Drawing {
  type: DrawTool;
  p1: DrawPoint;
  p2?: DrawPoint;
}

/** Tick do livefeed worker; source === "sim" é descartado pelo parser. */
export interface Tick {
  symbol: string;
  price: number;
  size: number;
  time: string;
}
```

- [ ] **Step 7.3: Escrever os testes** — `frontend/src/lib/ixchart/series.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { fmtP, fmtV, niceTicks, resample, rsi, sma } from "./series";
import type { Bar } from "./types";

const DAY = 86_400_000;
// Seg 2026-06-01 00:00 UTC — duas semanas úteis contíguas
const MON = Date.UTC(2026, 5, 1);

function bars(closes: number[]): Bar[] {
  return closes.map((c, i) => ({
    // pula fins de semana: 5 barras por semana
    t: MON + (Math.floor(i / 5) * 7 + (i % 5)) * DAY,
    o: c - 1, h: c + 2, l: c - 2, c, v: 1000 + i,
  }));
}

describe("resample", () => {
  it("D devolve as barras como estão", () => {
    const b = bars([1, 2, 3]);
    expect(resample(b, "D")).toEqual(b);
  });

  it("W agrega OHLC por semana ISO: o do 1º dia, c do último, h/l extremos, v somado", () => {
    const b = bars([10, 12, 8, 11, 13, 20, 22, 18, 21, 23]); // 2 semanas × 5 dias
    const w = resample(b, "W");
    expect(w).toHaveLength(2);
    expect(w[0].o).toBe(10 - 1);
    expect(w[0].c).toBe(13);
    expect(w[0].h).toBe(13 + 2);
    expect(w[0].l).toBe(8 - 2);
    expect(w[0].v).toBe(1000 + 1001 + 1002 + 1003 + 1004);
    expect(w[1].c).toBe(23);
  });
});

describe("sma", () => {
  it("é null até a janela encher e correto depois", () => {
    const out = sma(bars([1, 2, 3, 4, 5]), 3);
    expect(out[0]).toBeNull();
    expect(out[1]).toBeNull();
    expect(out[2]).toBeCloseTo(2);
    expect(out[4]).toBeCloseTo(4);
  });
});

describe("rsi", () => {
  it("alta monotônica → RSI 100; mistura fica em (0,100)", () => {
    const up = rsi(bars([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]), 14);
    expect(up[15]).toBe(100);
    const mixed = rsi(bars([10, 11, 10, 12, 11, 13, 12, 14, 13, 15, 14, 16, 15, 17, 16, 18]), 14);
    expect(mixed[15]).toBeGreaterThan(0);
    expect(mixed[15]).toBeLessThan(100);
  });
});

describe("niceTicks", () => {
  it("gera ticks redondos dentro do intervalo", () => {
    const ticks = niceTicks(0, 100, 5);
    expect(ticks[0]).toBeGreaterThanOrEqual(0);
    expect(ticks.at(-1)).toBeLessThanOrEqual(100);
    expect(ticks.length).toBeGreaterThanOrEqual(3);
  });
  it("intervalo vazio → []", () => {
    expect(niceTicks(5, 5, 5)).toEqual([]);
  });
});

describe("formatters", () => {
  it("fmtP en-US com casas fixas; null → em-dash", () => {
    expect(fmtP(1234.5, 2)).toBe("1,234.50");
    expect(fmtP(null, 2)).toBe("—");
  });
  it("fmtV abrevia K/M/B", () => {
    expect(fmtV(1_500)).toBe("1.5K");
    expect(fmtV(2_500_000)).toBe("2.50M");
    expect(fmtV(3_100_000_000)).toBe("3.10B");
  });
});
```

- [ ] **Step 7.4: Rodar e ver falhar**

```bash
cd /e/investintell-light/frontend && npm run test
```
Expected: FAIL — `Cannot find module './series'`.

- [ ] **Step 7.5: Implementar** — `frontend/src/lib/ixchart/series.ts`. Port direto das funções do protótipo (`E:\investintell-datalake-workers\design\assets\chart-engine.js` linhas 93–155), com formatação en-US (a UI do app é em inglês) e tipos:

```ts
/**
 * Funções puras do chart interativo: resample D/W/M, indicadores e
 * formatadores. Port de design/assets/chart-engine.js (repo workers),
 * sem dados sintéticos — barras reais vêm de GET /stocks/{ticker}/history.
 */
import type { Bar, Period } from "./types";

export function resample(bars: Bar[], period: Period): Bar[] {
  if (period === "D") return bars;
  const keyOf = (t: number): number => {
    const d = new Date(t);
    if (period === "M") return d.getFullYear() * 100 + d.getMonth();
    // semana ISO aproximada: ano*100 + nº da semana
    const onejan = new Date(d.getFullYear(), 0, 1);
    return (
      d.getFullYear() * 100 +
      Math.floor((((t - onejan.getTime()) / 86_400_000) + onejan.getDay()) / 7)
    );
  };
  const out: Bar[] = [];
  let cur: Bar | null = null;
  let curKey: number | null = null;
  for (const b of bars) {
    const k = keyOf(b.t);
    if (k !== curKey) {
      if (cur) out.push(cur);
      curKey = k;
      cur = { ...b };
    } else if (cur) {
      cur.h = Math.max(cur.h, b.h);
      cur.l = Math.min(cur.l, b.l);
      cur.c = b.c;
      cur.v += b.v;
    }
  }
  if (cur) out.push(cur);
  return out;
}

export function sma(bars: Bar[], p: number): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let acc = 0;
  for (let i = 0; i < bars.length; i++) {
    acc += bars[i].c;
    if (i >= p) acc -= bars[i - p].c;
    if (i >= p - 1) out[i] = acc / p;
  }
  return out;
}

export function rsi(bars: Bar[], p = 14): (number | null)[] {
  const out: (number | null)[] = new Array(bars.length).fill(null);
  let g = 0;
  let l = 0;
  for (let i = 1; i < bars.length; i++) {
    const d = bars[i].c - bars[i - 1].c;
    const up = Math.max(d, 0);
    const dn = Math.max(-d, 0);
    if (i <= p) {
      g += up / p;
      l += dn / p;
    } else {
      g = (g * (p - 1) + up) / p;
      l = (l * (p - 1) + dn) / p;
    }
    if (i >= p) out[i] = l === 0 ? 100 : 100 - 100 / (1 + g / l);
  }
  return out;
}

export function niceTicks(min: number, max: number, target: number): number[] {
  const span = max - min;
  if (!(span > 0)) return [];
  const raw = span / Math.max(2, target);
  const mag = Math.pow(10, Math.floor(Math.log10(raw)));
  const step =
    [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= target + 1) ?? 10 * mag;
  const out: number[] = [];
  for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) out.push(v);
  return out;
}

export const fmtP = (x: number | null | undefined, dec: number): string =>
  x == null
    ? "—"
    : x.toLocaleString("en-US", { minimumFractionDigits: dec, maximumFractionDigits: dec });

export const fmtV = (x: number): string =>
  x >= 1e9 ? (x / 1e9).toFixed(2) + "B"
  : x >= 1e6 ? (x / 1e6).toFixed(2) + "M"
  : x >= 1e3 ? (x / 1e3).toFixed(1) + "K"
  : String(Math.round(x));

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

export const fmtD = (t: number): string => {
  const d = new Date(t);
  return `${d.getDate()} ${MONTHS[d.getMonth()]} ${String(d.getFullYear()).slice(2)}`;
};

export { MONTHS };
```

- [ ] **Step 7.6: Rodar e ver passar**

```bash
cd /e/investintell-light/frontend && npm run test && npm run typecheck
```
Expected: PASS.

- [ ] **Step 7.7: Commit**

```bash
cd /e/investintell-light && git add frontend/vitest.config.ts frontend/package.json frontend/package-lock.json frontend/src/lib/ixchart/ && git commit -m "feat(frontend): ixchart series — resample/indicadores/formatadores puros + vitest"
```

---

### Task 8: `tokens.ts` + `engine.ts` (port da classe Chart)

**Files:**
- Create: `frontend/src/lib/ixchart/tokens.ts`
- Create: `frontend/src/lib/ixchart/engine.ts`

O engine é um port MECÂNICO de `E:\investintell-datalake-workers\design\assets\chart-engine.js` (classe `Chart`, linhas 158–652). Sem teste unitário próprio (canvas/DOM); a verificação é typecheck + smoke visual da Task 13/15. As transformações são enumeradas abaixo — todo o resto é cópia literal.

- [ ] **Step 8.1: Tokens** — `frontend/src/lib/ixchart/tokens.ts`:

```ts
/**
 * Tokens do canvas lidos dos CSS custom properties do design system
 * (mesma fonte do chartColors() em src/lib/charts/theme.ts) — o chart
 * reage a tema/accent. Client-only (getComputedStyle após mount).
 * Fontes: literais (canvas não resolve var() aninhado no ctx.font).
 */
export interface IxTokens {
  bg: string;
  grid: string;
  border: string;
  borderS: string;
  text: string;
  text2: string;
  text3: string;
  graphite: string;
  pos: string;
  neg: string;
  accent: string;
  sma20: string;
  sma50: string;
  compare: string;
  mono: string;
  ui: string;
}

export function readIxTokens(): IxTokens {
  const s = getComputedStyle(document.documentElement);
  const v = (name: string, fb: string): string => s.getPropertyValue(name).trim() || fb;
  return {
    bg: v("--color-surface-1", "#ffffff"),
    grid: v("--color-chart-grid", "#ececec"),
    border: v("--color-border", "#e0e0e0"),
    borderS: v("--color-border-strong", "#c6c6c6"),
    text: v("--color-text-primary", "#161616"),
    text2: v("--color-text-secondary", "#525252"),
    text3: v("--color-text-muted", "#6f6f6f"),
    graphite: v("--color-chart-bar", "#2b2f36"),
    pos: v("--color-gain", "#198038"),
    neg: v("--color-loss", "#a2191f"),
    accent: v("--color-accent", "#7a1c24"),
    sma20: v("--color-cat-7", "#a08184"),
    sma50: v("--color-cat-3", "#565b63"),
    compare: v("--color-cat-8", "#4d5560"),
    mono: '"Geist Mono", Consolas, ui-monospace, monospace',
    ui: 'Arial, "Arimo", sans-serif',
  };
}
```

- [ ] **Step 8.2: Engine** — `frontend/src/lib/ixchart/engine.ts`. Estrutura nova (escreva exatamente):

```ts
/**
 * IXChart — engine canvas 2D do chart interativo (zero deps).
 * Port de design/assets/chart-engine.js (repo investintell-datalake-workers,
 * commit 517eb41): candles/ohlc/linha/área, painéis volume/RSI, SMA20/50,
 * comparação normalizada, log/%, pan/zoom, crosshair, desenhos
 * (trend/hline/fib/régua), tick ao vivo no candle corrente.
 *
 * Diferenças deliberadas vs protótipo:
 *  - dados reais via setBars()/setCompare() — sem séries sintéticas;
 *  - tokens injetados (reage a tema), sem getComputedStyle interno;
 *  - destroy() remove listeners/observer (ciclo de vida React);
 *  - sem LiveFeed/fetchMetrics aqui — o wrapper liga o feed e chama applyTick.
 */
import { fmtD, fmtP, fmtV, niceTicks, resample, rsi, sma } from "./series";
import { MONTHS } from "./series";
import type { Bar, ChartType, DrawTool, Drawing, DrawPoint, Period } from "./types";
import type { IxTokens } from "./tokens";

export interface ChartCallbacks {
  onCrosshair?: (bar: Bar | null, prev: Bar | null) => void;
  onViewChange?: () => void;
  onToolDone?: () => void;
}

export class Chart {
  // ... (port abaixo)
}
```

Transformações sobre o código do protótipo (linhas 158–652 do `chart-engine.js`):

1. `constructor(canvas, opts)` → `constructor(canvas: HTMLCanvasElement, tokens: IxTokens, cb: ChartCallbacks = {})`. Guarde `this.tk = tokens`. REMOVA `this.setSymbol("TSLA")` do construtor (o chart nasce vazio; `render()` já tem guard `if (!this.bars || !this.W) return`). Guarde o observer: `this._ro = new ResizeObserver(() => this._resize()); this._ro.observe(canvas.parentElement!)`.
2. Todo `TK.` → `this.tk.` (são ~40 ocorrências em `render`, `_renderDrawings`, `_renderCrosshair`).
3. REMOVA: `setSymbol()` (linhas 186–190), `genDailySeries`/`KNOWN`/`hashSeed`/`mulberry32` (já não existem em series.ts), `LiveFeed` (classe separada), `fetchMetrics`/`localMetrics`, o IIFE e `window.IXChart = ...`.
4. ADICIONE no lugar de `setSymbol`:

```ts
  /** Define a série diária real (contrato do /history) e re-deriva tudo. */
  setBars(daily: Bar[]): void {
    this.daily = daily;
    this._rebuild(true);
  }

  /** Comparação normalizada: barras diárias do outro símbolo (ou null p/ limpar). */
  setCompare(symbol: string | null, daily?: Bar[]): void {
    if (!symbol || !daily) {
      this.compareWith = null;
      this._compareDaily = null;
      if (!this._pctForced) this.scale.pct = false;
    } else {
      this._compareDaily = daily;
      this.compareWith = { symbol: symbol.toUpperCase(), bars: resample(daily, this.period) };
      this._pctForced = this.scale.pct;
      this.scale.pct = true; // comparação só faz sentido normalizada
    }
    this.render();
  }
```

5. Em `_rebuild`: troque `resample(genDailySeries(this.compareWith.symbol), this.period)` por `resample(this._compareDaily!, this.period)` (guard `if (this.compareWith && this._compareDaily)`).
6. `_bindEvents()`: os três listeners de `window` (`mousemove`, `mouseup`, `keydown`) devem ser guardados como campos (`this._onWinMove = (e) => {...}` etc.) para remoção; adicione:

```ts
  /** Remove listeners globais e o ResizeObserver — chamar no unmount. */
  destroy(): void {
    this._ro.disconnect();
    window.removeEventListener("mousemove", this._onWinMove);
    window.removeEventListener("mouseup", this._onWinUp);
    window.removeEventListener("keydown", this._onKeyDown);
    clearTimeout(this._flashT);
  }
```

7. Tipagem dos campos (declare no topo da classe): `cv: HTMLCanvasElement; cx: CanvasRenderingContext2D; tk: IxTokens; daily: Bar[] = []; bars: Bar[] = []; period: Period = "D"; type: ChartType = "candles"; scale = { log: false, pct: false }; overlays = { sma20: true, sma50: false }; panes = { volume: true, rsi: false }; compareWith: { symbol: string; bars: Bar[] } | null = null; drawings: Drawing[] = []; tool: DrawTool | null = null; magnet = false; pending: DrawPoint | null = null; cross: { x: number; y: number } | null = null; view = { first: 0, count: 0 }; lastTick = { dir: 0, at: 0 };` — mais os privados `_compareDaily: Bar[] | null`, `_pctForced: boolean`, `_flashT: ReturnType<typeof setTimeout> | undefined`, `_ro: ResizeObserver`, `ind`, `L`, `W`, `H`, `_yP`, `_pMin`, `_pMax`, `_T` (tipar como `any`/tipos locais simples onde o custo de tipagem exata não paga — manter o port mecânico).
8. `applyTick(price, size)`: adicione guard `if (!this.daily.length || !this.bars.length) return;` na primeira linha; resto idêntico.
9. Métodos copiados VERBATIM (apenas renames acima): `setPeriod`, `setType`, `setRange`, `toggleOverlay`, `togglePane`, `setScale`, `setTool`, `undoDrawing`, `clearDrawings`, `_rebuild`, `_resize`, `_layout`, `_xAt`, `_iAt`, `_priceTransform`, `render`, `_renderDrawings`, `_renderCrosshair`, `_dataPoint`, `_bindEvents`. A marca d'água `"investintell"` (linha 351) fica.
10. `fmtD`/`fmtP`/`fmtV`/`niceTicks`/`resample`/`sma`/`rsi`/`MONTHS` vêm de `./series` (imports já no skeleton).

- [ ] **Step 8.3: Typecheck + lint**

```bash
cd /e/investintell-light/frontend && npm run typecheck && npm run lint
```
Expected: PASS (engine compila; nenhum consumer ainda).

- [ ] **Step 8.4: Commit**

```bash
cd /e/investintell-light && git add frontend/src/lib/ixchart/ && git commit -m "feat(frontend): port do engine IXChart (canvas) com tokens injetados e destroy()"
```

---

### Task 9: Cliente WS compartilhado (`livefeed`)

**Files:**
- Create: `frontend/src/lib/livefeed/client.ts`
- Create: `frontend/src/lib/livefeed/useLiveTicks.ts`
- Test: `frontend/src/lib/livefeed/client.test.ts`

- [ ] **Step 9.1: Teste do parser** — `frontend/src/lib/livefeed/client.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { parseTick } from "./client";

describe("parseTick", () => {
  it("aceita tick real do worker", () => {
    const t = parseTick(
      '{"type":"tick","symbol":"TSLA","price":400.13,"size":100,"time":"2026-06-12T14:20:17Z"}',
    );
    expect(t).toEqual({ symbol: "TSLA", price: 400.13, size: 100, time: "2026-06-12T14:20:17Z" });
  });

  it('descarta ticks simulados (source:"sim") — nunca mostrar preço fake', () => {
    expect(
      parseTick('{"type":"tick","symbol":"TSLA","price":1.0,"size":0,"time":"t","source":"sim"}'),
    ).toBeNull();
  });

  it("descarta mensagens de controle e lixo", () => {
    expect(parseTick('{"type":"subscribed","symbols":["TSLA"]}')).toBeNull();
    expect(parseTick("not json")).toBeNull();
    expect(parseTick('{"type":"tick","symbol":"TSLA"}')).toBeNull(); // sem price
  });
});
```

- [ ] **Step 9.2: Rodar e ver falhar**

```bash
cd /e/investintell-light/frontend && npm run test
```
Expected: FAIL — `Cannot find module './client'`.

- [ ] **Step 9.3: Implementar o cliente** — `frontend/src/lib/livefeed/client.ts`:

```ts
/**
 * Cliente WebSocket COMPARTILHADO do livefeed worker (Railway, fan-out por
 * símbolo). Um socket por aba: handlers ref-counted por símbolo, subscribe
 * aditivo / unsubscribe (protocolo do worker), reconexão com backoff
 * exponencial (1s→30s) e re-subscribe ao reconectar.
 *
 * Ticks com source:"sim" (simulador fora do pregão) são DESCARTADOS no
 * parse — esta UI nunca anima preço fake; sem feed real, fica no EOD.
 *
 * Sem NEXT_PUBLIC_LIVEFEED_WS_URL o módulo degrada para no-op silencioso
 * (status "off") — páginas funcionam 100% com REST.
 */
import type { Tick } from "@/lib/ixchart/types";

export type FeedStatus = "off" | "connecting" | "live" | "error";
export type TickHandler = (tick: Tick) => void;
export type StatusHandler = (status: FeedStatus) => void;

const URL = process.env.NEXT_PUBLIC_LIVEFEED_WS_URL ?? "";
const MAX_BACKOFF_MS = 30_000;

export function parseTick(raw: string): Tick | null {
  try {
    const m = JSON.parse(raw) as Record<string, unknown>;
    if (m.type !== "tick" || m.source === "sim") return null;
    if (typeof m.symbol !== "string" || typeof m.price !== "number") return null;
    return {
      symbol: m.symbol.toUpperCase(),
      price: m.price,
      size: typeof m.size === "number" ? m.size : 0,
      time: typeof m.time === "string" ? m.time : "",
    };
  } catch {
    return null;
  }
}

class SharedFeed {
  private ws: WebSocket | null = null;
  private handlers = new Map<string, Set<TickHandler>>();
  private statusHandlers = new Set<StatusHandler>();
  private status: FeedStatus = "off";
  private backoff = 1_000;
  private reconnectT: ReturnType<typeof setTimeout> | undefined;
  private closedByUs = false;

  subscribe(symbol: string, handler: TickHandler): () => void {
    if (!URL || typeof window === "undefined") return () => {};
    const sym = symbol.toUpperCase();
    let set = this.handlers.get(sym);
    const isNew = !set;
    if (!set) {
      set = new Set();
      this.handlers.set(sym, set);
    }
    set.add(handler);
    this.ensureConnected();
    if (isNew && this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify({ action: "subscribe", symbols: [sym] }));
    }
    return () => {
      const s = this.handlers.get(sym);
      if (!s) return;
      s.delete(handler);
      if (s.size === 0) {
        this.handlers.delete(sym);
        if (this.ws?.readyState === WebSocket.OPEN) {
          this.ws.send(JSON.stringify({ action: "unsubscribe", symbols: [sym] }));
        }
        if (this.handlers.size === 0) this.teardown();
      }
    };
  }

  onStatus(handler: StatusHandler): () => void {
    this.statusHandlers.add(handler);
    handler(this.status);
    return () => this.statusHandlers.delete(handler);
  }

  private setStatus(next: FeedStatus): void {
    if (this.status === next) return;
    this.status = next;
    for (const h of this.statusHandlers) h(next);
  }

  private ensureConnected(): void {
    if (this.ws || !this.handlers.size) return;
    this.closedByUs = false;
    this.setStatus("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(URL);
    } catch {
      this.setStatus("error");
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.backoff = 1_000;
      this.setStatus("live");
      const symbols = [...this.handlers.keys()];
      if (symbols.length) ws.send(JSON.stringify({ action: "subscribe", symbols }));
    };
    ws.onmessage = (ev) => {
      const tick = parseTick(String(ev.data));
      if (!tick) return;
      const set = this.handlers.get(tick.symbol);
      if (set) for (const h of set) h(tick);
    };
    ws.onclose = () => {
      this.ws = null;
      if (this.closedByUs || !this.handlers.size) {
        this.setStatus("off");
        return;
      }
      this.setStatus("error");
      this.reconnectT = setTimeout(() => this.ensureConnected(), this.backoff);
      this.backoff = Math.min(this.backoff * 2, MAX_BACKOFF_MS);
    };
    ws.onerror = () => ws.close();
  }

  private teardown(): void {
    clearTimeout(this.reconnectT);
    this.closedByUs = true;
    this.ws?.close();
    this.ws = null;
    this.setStatus("off");
  }
}

const feed = new SharedFeed();

/** Inscreve um handler para os ticks reais de um símbolo; retorna o unsubscribe. */
export const subscribeTicks = (symbol: string, handler: TickHandler) =>
  feed.subscribe(symbol, handler);

/** Observa o estado do feed ("off" | "connecting" | "live" | "error"). */
export const onFeedStatus = (handler: StatusHandler) => feed.onStatus(handler);
```

- [ ] **Step 9.4: Hook com throttle** — `frontend/src/lib/livefeed/useLiveTicks.ts`:

```ts
"use client";

/**
 * useLiveTicks(symbols) — último preço ao vivo por símbolo, com flush em
 * requestAnimationFrame (uma re-render por frame, não por tick) — a tabela
 * de leaders assina ~25 símbolos sem virar um re-render storm.
 */
import { useEffect, useRef, useState } from "react";
import { onFeedStatus, subscribeTicks, type FeedStatus } from "./client";

export interface LivePrice {
  price: number;
  /** +1 subiu, -1 caiu vs tick anterior (para o flash). */
  dir: 1 | -1 | 0;
  time: string;
}

export function useLiveTicks(symbols: string[]): {
  ticks: Record<string, LivePrice>;
  status: FeedStatus;
} {
  const [ticks, setTicks] = useState<Record<string, LivePrice>>({});
  const [status, setStatus] = useState<FeedStatus>("off");
  const pending = useRef<Record<string, LivePrice>>({});
  const raf = useRef<number>(0);
  const key = symbols.join(",");

  useEffect(() => {
    const offStatus = onFeedStatus(setStatus);
    const flush = () => {
      raf.current = 0;
      const batch = pending.current;
      pending.current = {};
      setTicks((prev) => ({ ...prev, ...batch }));
    };
    const unsubs = key
      ? key.split(",").map((sym) =>
          subscribeTicks(sym, (tick) => {
            const prev = pending.current[sym]?.price;
            pending.current[sym] = {
              price: tick.price,
              dir: prev == null || tick.price === prev ? 0 : tick.price > prev ? 1 : -1,
              time: tick.time,
            };
            if (!raf.current) raf.current = requestAnimationFrame(flush);
          }),
        )
      : [];
    return () => {
      offStatus();
      for (const u of unsubs) u();
      if (raf.current) cancelAnimationFrame(raf.current);
      pending.current = {};
    };
  }, [key]);

  return { ticks, status };
}
```

- [ ] **Step 9.5: Rodar testes + typecheck**

```bash
cd /e/investintell-light/frontend && npm run test && npm run typecheck
```
Expected: PASS.

- [ ] **Step 9.6: Commit**

```bash
cd /e/investintell-light && git add frontend/src/lib/livefeed/ && git commit -m "feat(frontend): cliente WS compartilhado do livefeed + useLiveTicks (sim ticks descartados)"
```

---

### Task 10: `InteractiveChart.tsx` (canvas + toolbar)

**Files:**
- Create: `frontend/src/components/charts/InteractiveChart.tsx`

- [ ] **Step 10.1: Criar o componente**

```tsx
"use client";

/**
 * Chart interativo (IXChart) com toolbar: tipo, período D/W/M, ranges,
 * SMA/VOL/RSI, log/%, compare, ferramentas de desenho e tick ao vivo
 * (subscribeTicks → chart.applyTick; barra do dia anima a cada trade).
 * O range selecionado é elevado via onRangeChange para sincronizar as
 * métricas da página (analysis) com a janela visível.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchStockHistory, RANGE_PRESETS, type RangePreset } from "@/lib/api/client";
import { Chart } from "@/lib/ixchart/engine";
import { readIxTokens } from "@/lib/ixchart/tokens";
import { fmtP, fmtV } from "@/lib/ixchart/series";
import type { Bar, ChartType, DrawTool, Period } from "@/lib/ixchart/types";
import { onFeedStatus, subscribeTicks, type FeedStatus } from "@/lib/livefeed/client";

/** Barras visíveis por preset, em pregões (D); W/M dividem na troca de período. */
const RANGE_BARS: Record<RangePreset, number | "all"> = {
  "1M": 21, "6M": 126, "1Y": 252, "5Y": 1260, MAX: "all",
};

const PERIODS: Period[] = ["D", "W", "M"];
const TYPES: { id: ChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "ohlc", label: "OHLC" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
];
const TOOLS: { id: DrawTool; label: string }[] = [
  { id: "trend", label: "Trend" },
  { id: "hline", label: "Horizontal" },
  { id: "fib", label: "Fib" },
  { id: "measure", label: "Measure" },
];

export function InteractiveChart({
  symbol,
  bars,
  range,
  onRangeChange,
  className,
}: {
  symbol: string;
  bars: Bar[];
  range: RangePreset;
  onRangeChange: (next: RangePreset) => void;
  className?: string;
}) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const legendRef = useRef<HTMLDivElement>(null);

  const [period, setPeriod] = useState<Period>("D");
  const [type, setType] = useState<ChartType>("candles");
  const [overlays, setOverlays] = useState({ sma20: true, sma50: false });
  const [panes, setPanes] = useState({ volume: true, rsi: false });
  const [scale, setScale] = useState({ log: false, pct: false });
  const [tool, setTool] = useState<DrawTool | null>(null);
  const [compare, setCompare] = useState("");
  const [compareActive, setCompareActive] = useState<string | null>(null);
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<FeedStatus>("off");

  const { data: compareBars } = useQuery({
    queryKey: ["history", compareActive],
    queryFn: ({ signal }) => fetchStockHistory(compareActive!, 2520, signal),
    enabled: compareActive != null,
    staleTime: 60 * 60 * 1000,
  });

  const applyRange = (c: Chart, preset: RangePreset, p: Period) => {
    const n = RANGE_BARS[preset];
    if (n === "all") c.setRange("all");
    else c.setRange(Math.max(15, Math.round(n / (p === "D" ? 1 : p === "W" ? 5 : 21))));
  };

  // mount/unmount do engine
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const chart = new Chart(canvas, readIxTokens(), {
      onCrosshair: (bar, prev) => {
        const el = legendRef.current;
        if (!el) return;
        if (!bar) {
          el.textContent = "";
          return;
        }
        const chg = prev ? ((bar.c / prev.c - 1) * 100).toFixed(2) : "0.00";
        el.textContent =
          `O ${fmtP(bar.o, 2)}  H ${fmtP(bar.h, 2)}  L ${fmtP(bar.l, 2)}  ` +
          `C ${fmtP(bar.c, 2)}  Δ ${chg}%  VOL ${fmtV(bar.v)}`;
      },
      onToolDone: () => setTool(null),
    });
    chartRef.current = chart;
    return () => {
      chart.destroy();
      chartRef.current = null;
    };
  }, []);

  // dados / período / range
  useEffect(() => {
    const c = chartRef.current;
    if (!c || !bars.length) return;
    c.setPeriod(period); // _rebuild com a série atual (no-op de dados)
    c.setBars(bars);
    applyRange(c, range, period);
  }, [bars, period, range]);

  // comparação
  useEffect(() => {
    chartRef.current?.setCompare(compareActive, compareBars?.bars);
  }, [compareActive, compareBars]);

  // opções de render
  useEffect(() => { chartRef.current?.setType(type); }, [type]);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    if (c.overlays.sma20 !== overlays.sma20) c.toggleOverlay("sma20");
    if (c.overlays.sma50 !== overlays.sma50) c.toggleOverlay("sma50");
  }, [overlays]);
  useEffect(() => {
    const c = chartRef.current;
    if (!c) return;
    if (c.panes.volume !== panes.volume) c.togglePane("volume");
    if (c.panes.rsi !== panes.rsi) c.togglePane("rsi");
  }, [panes]);
  useEffect(() => { chartRef.current?.setScale(scale); }, [scale]);
  useEffect(() => { chartRef.current?.setTool(tool); }, [tool]);

  // feed ao vivo
  useEffect(() => onFeedStatus(setFeed), []);
  useEffect(() => {
    if (!live) return;
    return subscribeTicks(symbol, (tick) => chartRef.current?.applyTick(tick.price, tick.size));
  }, [symbol, live]);

  const btn = (active: boolean) =>
    `px-2 h-7 text-[11px] border-r border-border last:border-r-0 transition-colors ${
      active ? "bg-accent font-bold text-on-accent" : "text-text-muted hover:bg-layer-hover hover:text-text-primary"
    }`;

  const group = "flex items-stretch border border-border-strong";

  return (
    <div className={className}>
      {/* ── toolbar ── */}
      <div className="flex flex-wrap items-center gap-2 border border-b-0 border-border bg-surface-1 px-2 py-1.5 text-[11px]">
        <div role="group" aria-label="Chart type" className={group}>
          {TYPES.map((t) => (
            <button key={t.id} type="button" aria-pressed={type === t.id}
              className={btn(type === t.id)} onClick={() => setType(t.id)}>
              {t.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Period" className={group}>
          {PERIODS.map((p) => (
            <button key={p} type="button" aria-pressed={period === p}
              className={btn(period === p)} onClick={() => setPeriod(p)}>
              {p}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Range" className={group}>
          {RANGE_PRESETS.map((r) => (
            <button key={r} type="button" aria-pressed={range === r}
              className={btn(range === r)} onClick={() => onRangeChange(r)}>
              {r}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Overlays" className={group}>
          <button type="button" aria-pressed={overlays.sma20} className={btn(overlays.sma20)}
            onClick={() => setOverlays((o) => ({ ...o, sma20: !o.sma20 }))}>SMA20</button>
          <button type="button" aria-pressed={overlays.sma50} className={btn(overlays.sma50)}
            onClick={() => setOverlays((o) => ({ ...o, sma50: !o.sma50 }))}>SMA50</button>
          <button type="button" aria-pressed={panes.volume} className={btn(panes.volume)}
            onClick={() => setPanes((p) => ({ ...p, volume: !p.volume }))}>VOL</button>
          <button type="button" aria-pressed={panes.rsi} className={btn(panes.rsi)}
            onClick={() => setPanes((p) => ({ ...p, rsi: !p.rsi }))}>RSI</button>
        </div>
        <div role="group" aria-label="Scale" className={group}>
          <button type="button" aria-pressed={scale.log} className={btn(scale.log)}
            onClick={() => setScale((s) => ({ ...s, log: !s.log, pct: false }))}>Log</button>
          <button type="button" aria-pressed={scale.pct} className={btn(scale.pct)}
            onClick={() => setScale((s) => ({ ...s, pct: !s.pct, log: false }))}>%</button>
        </div>
        <div role="group" aria-label="Draw" className={group}>
          {TOOLS.map((t) => (
            <button key={t.id} type="button" aria-pressed={tool === t.id}
              className={btn(tool === t.id)} onClick={() => setTool(tool === t.id ? null : t.id)}>
              {t.label}
            </button>
          ))}
          <button type="button" className={btn(false)}
            onClick={() => chartRef.current?.undoDrawing()}>Undo</button>
          <button type="button" className={btn(false)}
            onClick={() => chartRef.current?.clearDrawings()}>Clear</button>
        </div>
        <form
          className="flex items-center gap-1"
          onSubmit={(e) => {
            e.preventDefault();
            const sym = compare.trim().toUpperCase();
            setCompareActive(sym || null);
          }}
        >
          <input
            value={compare}
            onChange={(e) => setCompare(e.target.value)}
            placeholder="Compare…"
            aria-label="Compare symbol"
            className="h-7 w-24 border border-border-strong bg-field px-2 text-[11px] text-text-primary placeholder:text-text-muted"
          />
          {compareActive && (
            <button type="button" className="text-[11px] text-text-muted hover:text-text-primary"
              onClick={() => { setCompare(""); setCompareActive(null); }}>
              ×
            </button>
          )}
        </form>
        <div className="flex-1" />
        <button
          type="button"
          aria-pressed={live}
          onClick={() => setLive((v) => !v)}
          className={`flex h-7 items-center gap-1.5 border border-border-strong px-2 text-[11px] ${
            live && feed === "live" ? "text-gain" : "text-text-muted"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${
            live && feed === "live" ? "bg-gain" : "bg-border-strong"
          }`} />
          {live && feed === "live" ? "LIVE" : "EOD"}
        </button>
      </div>

      {/* ── legenda OHLC (atualizada via ref, sem re-render) ── */}
      <div
        ref={legendRef}
        aria-live="off"
        className="border border-b-0 border-border bg-surface-1 px-3 py-1 font-mono text-[10.5px] tabular-nums text-text-secondary min-h-[24px]"
      />

      {/* ── canvas ── */}
      <div className="relative h-[58vh] min-h-[380px] border border-border bg-surface-1">
        <canvas ref={canvasRef} />
      </div>
    </div>
  );
}
```

- [ ] **Step 10.2: Typecheck + lint**

```bash
cd /e/investintell-light/frontend && npm run typecheck && npm run lint
```
Expected: PASS. (Os campos `overlays`/`panes` do engine são lidos aqui — eles são públicos na classe portada.)

- [ ] **Step 10.3: Commit**

```bash
cd /e/investintell-light && git add frontend/src/components/charts/InteractiveChart.tsx && git commit -m "feat(frontend): InteractiveChart — canvas IXChart com toolbar e live tick"
```

---

### Task 11: `AddToPortfolio.tsx`

**Files:**
- Create: `frontend/src/components/stocks/AddToPortfolio.tsx`

- [ ] **Step 11.1: Criar o componente**

```tsx
"use client";

/**
 * Botão "+ Portfolio": popover com a lista de portfólios persistidos e um
 * campo de quantidade → PUT /portfolios/{id}/positions/{ticker}. Usado nas
 * linhas da LeadersTable e no header do detalhe da ação.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchPortfolios, putPosition } from "@/lib/api/client";

export function AddToPortfolio({ ticker }: { ticker: string }) {
  const [open, setOpen] = useState(false);
  const [qty, setQty] = useState("1");
  const [done, setDone] = useState<string | null>(null);
  const rootRef = useRef<HTMLDivElement>(null);
  const queryClient = useQueryClient();

  const { data: portfolios } = useQuery({
    queryKey: ["portfolios"],
    queryFn: ({ signal }) => fetchPortfolios(signal),
    enabled: open,
    staleTime: 5 * 60 * 1000,
  });

  const add = useMutation({
    mutationFn: ({ portfolioId }: { portfolioId: number }) =>
      putPosition(portfolioId, ticker, { quantity: Number(qty) || 1 }),
    onSuccess: (_data, vars) => {
      setDone(String(vars.portfolioId));
      queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    },
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  return (
    <div ref={rootRef} className="relative inline-block">
      <button
        type="button"
        title={`Add ${ticker} to a portfolio`}
        aria-haspopup="true"
        aria-expanded={open}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
          setDone(null);
        }}
        className="flex h-6 items-center border border-border-strong px-1.5 text-[11px] font-bold text-text-secondary hover:bg-layer-hover hover:text-text-primary"
      >
        +
      </button>
      {open && (
        <div
          onClick={(e) => e.stopPropagation()}
          className="absolute right-0 z-30 mt-1 w-56 border border-border-strong bg-surface-1 p-2 shadow-lg"
        >
          <div className="mb-1.5 text-[10px] font-bold uppercase tracking-[0.1em] text-text-muted">
            Add {ticker}
          </div>
          <label className="mb-2 flex items-center gap-2 text-[11px] text-text-secondary">
            Qty
            <input
              value={qty}
              onChange={(e) => setQty(e.target.value)}
              inputMode="decimal"
              className="h-6 w-20 border border-border-strong bg-field px-1.5 tabular-nums text-text-primary"
            />
          </label>
          {portfolios?.length === 0 && (
            <p className="text-[11px] text-text-muted">
              No portfolios yet — create one in Portfolio.
            </p>
          )}
          {portfolios?.map((p) => (
            <button
              key={p.id}
              type="button"
              disabled={add.isPending}
              onClick={() => add.mutate({ portfolioId: p.id })}
              className="flex w-full items-center justify-between px-1.5 py-1 text-left text-[12px] text-text-primary hover:bg-layer-hover disabled:opacity-50"
            >
              <span className="truncate">{p.name}</span>
              {done === String(p.id) && <span className="text-gain">✓</span>}
            </button>
          ))}
          {add.isError && (
            <p className="mt-1 text-[11px] text-loss">{(add.error as Error).message}</p>
          )}
        </div>
      )}
    </div>
  );
}
```

Nota: `PortfolioListItem` tem `id`/`name` (CRUD F4) e `PositionBody` é `{ quantity }` — confirme os nomes exatos em `api.d.ts` após o regen da Task 6 e ajuste se o schema usar outro campo.

- [ ] **Step 11.2: Typecheck + commit**

```bash
cd /e/investintell-light/frontend && npm run typecheck && cd .. && git add frontend/src/components/stocks/AddToPortfolio.tsx && git commit -m "feat(frontend): AddToPortfolio — popover de inclusão rápida em portfólio"
```

---

### Task 12: Landing `/stocks` (IndexStrip + LeadersTable + SectorPanel)

**Files:**
- Create: `frontend/src/components/stocks/IndexStrip.tsx`
- Create: `frontend/src/components/stocks/LeadersTable.tsx`
- Create: `frontend/src/components/stocks/SectorPanel.tsx`
- Create: `frontend/src/components/stocks/MarketOverview.tsx`
- Create: `frontend/src/app/stocks/page.tsx`
- Modify: `frontend/src/components/shell/AppShell.tsx`

- [ ] **Step 12.1: IndexStrip** — `frontend/src/components/stocks/IndexStrip.tsx`:

```tsx
"use client";

/** Cards SPY/QQQ/DIA/IWM: último preço (live quando o feed está aberto),
 *  variação do dia e sparkline 30d em SVG puro. */
import type { IndexCard } from "@/lib/api/client";
import { formatCurrency, formatPercent } from "@/lib/format";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";

function Spark({ points }: { points: number[] }) {
  const w = 96;
  const h = 28;
  const min = Math.min(...points);
  const max = Math.max(...points);
  const span = max - min || 1;
  const d = points
    .map((p, i) => `${((i / (points.length - 1)) * w).toFixed(1)},${(h - ((p - min) / span) * h).toFixed(1)}`)
    .join(" ");
  const up = points[points.length - 1] >= points[0];
  return (
    <svg width={w} height={h} aria-hidden className="shrink-0">
      <polyline
        points={d}
        fill="none"
        stroke={up ? "var(--color-gain)" : "var(--color-loss)"}
        strokeWidth="1.4"
      />
    </svg>
  );
}

export function IndexStrip({ indices }: { indices: IndexCard[] }) {
  const { ticks } = useLiveTicks(indices.map((i) => i.ticker));
  if (!indices.length) return null;
  return (
    <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
      {indices.map((ix) => {
        const live = ticks[ix.ticker];
        const last = live?.price ?? ix.last;
        // Baseline do live = último close do banco (ix.last) — variação de hoje.
        const chg = live && ix.last > 0 ? last / ix.last - 1 : ix.change_pct;
        const tone = chg > 0 ? "text-gain" : chg < 0 ? "text-loss" : "text-neutral-value";
        return (
          <div key={ix.ticker} className="flex items-center justify-between gap-3 bg-surface-2 px-4 py-3">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.08em] text-text-muted">
                {ix.name} <span className="text-text-secondary">{ix.ticker}</span>
              </div>
              <div className="mt-1 flex items-baseline gap-2 tabular-nums">
                <span className="text-[18px] font-bold text-text-primary">
                  {formatCurrency(last)}
                </span>
                <span className={`text-[12px] font-bold ${tone}`}>
                  {formatPercent(chg, 2, { signed: true })}
                </span>
              </div>
            </div>
            <Spark points={ix.spark} />
          </div>
        );
      })}
    </div>
  );
}
```

- [ ] **Step 12.2: LeadersTable** — `frontend/src/components/stocks/LeadersTable.tsx`:

```tsx
"use client";

/**
 * Market Leaders com tabs (Most Active / Gainers / Losers / 52w High / 52w
 * Low). Last/Chg atualizam ao vivo (flash gain/loss); o RANKING não re-sorta
 * por tick — ordem fixa até o refetch (evita a tabela "pulando").
 * Clique na linha → /stocks/{ticker}; botão "+" → AddToPortfolio.
 */
import { useRouter } from "next/navigation";
import { useState } from "react";
import type { LeaderRow, MarketOverview } from "@/lib/api/client";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { AddToPortfolio } from "@/components/stocks/AddToPortfolio";

const TABS = [
  { key: "most_active", label: "Most Active" },
  { key: "gainers", label: "Gainers" },
  { key: "losers", label: "Losers" },
  { key: "highs_52w", label: "52w Highs" },
  { key: "lows_52w", label: "52w Lows" },
] as const;

type TabKey = (typeof TABS)[number]["key"];

export function LeadersTable({ overview }: { overview: MarketOverview }) {
  const router = useRouter();
  const [tab, setTab] = useState<TabKey>("most_active");
  const rows: LeaderRow[] = overview[tab];
  const { ticks } = useLiveTicks(rows.map((r) => r.ticker));

  return (
    <div className="border border-border bg-surface-2">
      <div role="tablist" aria-label="Market leaders" className="flex border-b border-border">
        {TABS.map((t) => (
          <button
            key={t.key}
            role="tab"
            aria-selected={tab === t.key}
            type="button"
            onClick={() => setTab(t.key)}
            className={`px-3.5 py-2 text-[12px] transition-colors ${
              tab === t.key
                ? "font-bold text-accent shadow-[inset_0_-2px_0_var(--color-accent)]"
                : "text-text-muted hover:text-text-primary"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      <table className="w-full border-collapse text-[12.5px] tabular-nums">
        <thead>
          <tr className="text-left text-[10.5px] uppercase tracking-[0.08em] text-text-muted">
            <th className="px-3 py-2 font-bold">Symbol</th>
            <th className="px-3 py-2 font-bold">Name</th>
            <th className="px-3 py-2 text-right font-bold">Last</th>
            <th className="px-3 py-2 text-right font-bold">Chg</th>
            <th className="px-3 py-2 text-right font-bold">%Chg</th>
            <th className="hidden px-3 py-2 text-right font-bold md:table-cell">Volume</th>
            <th className="hidden px-3 py-2 text-right font-bold lg:table-cell">52w Range</th>
            <th className="px-3 py-2" aria-label="Actions" />
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const live = ticks[r.ticker];
            const last = live?.price ?? r.last;
            // Baseline do live = último close do banco (r.last): durante o
            // pregão o banco ainda tem o close de ontem, então live/r.last - 1
            // é a variação de HOJE. Sem tick, vale o EOD do payload.
            const change = live ? last - r.last : r.change;
            const changePct = live && r.last > 0 ? last / r.last - 1 : r.change_pct;
            const tone = change > 0 ? "text-gain" : change < 0 ? "text-loss" : "text-neutral-value";
            const flash =
              live?.dir === 1 ? "animate-pulse text-gain" : live?.dir === -1 ? "animate-pulse text-loss" : "";
            return (
              <tr
                key={r.ticker}
                onClick={() => router.push(`/stocks/${encodeURIComponent(r.ticker)}`)}
                className="cursor-pointer border-t border-border hover:bg-layer-hover"
              >
                <td className="px-3 py-1.5 font-bold text-accent">{r.ticker}</td>
                <td className="max-w-[260px] truncate px-3 py-1.5 text-text-secondary">{r.name}</td>
                <td className={`px-3 py-1.5 text-right font-bold text-text-primary ${flash}`}>
                  {formatCurrency(last)}
                </td>
                <td className={`px-3 py-1.5 text-right ${tone}`}>
                  {formatCurrency(change, { signed: true })}
                </td>
                <td className={`px-3 py-1.5 text-right font-bold ${tone}`}>
                  {formatPercent(changePct, 2, { signed: true })}
                </td>
                <td className="hidden px-3 py-1.5 text-right text-text-secondary md:table-cell">
                  {formatNumber(r.volume, 0)}
                </td>
                <td className="hidden px-3 py-1.5 text-right text-text-muted lg:table-cell">
                  {formatCurrency(r.low_52w)} – {formatCurrency(r.high_52w)}
                </td>
                <td className="px-3 py-1.5 text-right" onClick={(e) => e.stopPropagation()}>
                  <AddToPortfolio ticker={r.ticker} />
                </td>
              </tr>
            );
          })}
          {rows.length === 0 && (
            <tr>
              <td colSpan={8} className="px-3 py-6 text-center text-[12px] text-text-muted">
                No data — universe EOD backfill has not run yet.
              </td>
            </tr>
          )}
        </tbody>
      </table>
    </div>
  );
}
```

(Se `formatNumber` no `lib/format` tiver outra assinatura, use a existente — objetivo: volume inteiro com separador de milhar.)

- [ ] **Step 12.3: SectorPanel** — `frontend/src/components/stocks/SectorPanel.tsx`:

```tsx
"use client";

/** Performance do dia por setor GICS (mediana dos constituintes líquidos).
 *  Auto-oculto enquanto o enriquecimento de setor não rodou (sectors=[]). */
import type { SectorPerf } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

export function SectorPanel({ sectors }: { sectors: SectorPerf[] }) {
  if (!sectors.length) return null;
  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.change_pct_median)), 0.001);
  return (
    <div className="border border-border bg-surface-2 px-4 py-3">
      <h2 className="mb-2 text-[11px] font-bold uppercase tracking-[0.1em] text-text-muted">
        Sectors · today (median)
      </h2>
      <div className="flex flex-col gap-1">
        {sectors.map((s) => {
          const pct = s.change_pct_median;
          const width = Math.max(2, (Math.abs(pct) / maxAbs) * 100);
          return (
            <div key={s.sector} className="grid grid-cols-[170px_1fr_64px] items-center gap-2 text-[12px]">
              <span className="truncate text-text-secondary">{s.sector}</span>
              <div className="flex h-3 items-center">
                <div
                  className={pct >= 0 ? "bg-gain" : "bg-loss"}
                  style={{ width: `${width}%`, height: "10px" }}
                />
              </div>
              <span className={`text-right font-bold tabular-nums ${pct >= 0 ? "text-gain" : "text-loss"}`}>
                {formatPercent(pct, 2, { signed: true })}
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
```

- [ ] **Step 12.4: MarketOverview (composição)** — `frontend/src/components/stocks/MarketOverview.tsx`:

```tsx
"use client";

/** Landing /stocks: strip de índices + leaders + setores, de UM payload
 *  (GET /stocks/overview, cacheado no backend). Refetch a cada 60s. */
import { useQuery } from "@tanstack/react-query";
import { fetchMarketOverview } from "@/lib/api/client";
import { formatDate } from "@/lib/format";
import { IndexStrip } from "@/components/stocks/IndexStrip";
import { LeadersTable } from "@/components/stocks/LeadersTable";
import { SectorPanel } from "@/components/stocks/SectorPanel";

export function MarketOverview() {
  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["market-overview"],
    queryFn: ({ signal }) => fetchMarketOverview(signal),
    staleTime: 60 * 1000,
    refetchInterval: 60 * 1000,
  });

  if (error) {
    return (
      <div className="flex min-h-full items-center justify-center px-6 py-10">
        <div className="w-full max-w-[520px] border border-border border-l-[3px] border-l-[var(--color-loss)] bg-surface-2 px-8 py-6">
          <h1 className="mb-3 text-lg font-bold text-text-primary">Failed to load market overview</h1>
          <p className="text-sm text-loss break-words">{(error as Error).message}</p>
          <button
            type="button"
            onClick={() => refetch()}
            className="mt-4 px-4 py-1.5 bg-field border border-border-strong text-sm font-semibold text-text-primary hover:bg-layer-hover transition-colors"
          >
            Retry
          </button>
        </div>
      </div>
    );
  }

  if (isPending || !data) {
    return (
      <div aria-busy="true" className="mx-auto flex max-w-[1360px] animate-pulse flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
        <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(220px,1fr))]">
          {Array.from({ length: 4 }, (_, i) => (
            <div key={i} className="h-[72px] bg-surface-2" />
          ))}
        </div>
        <div className="mb-px h-[480px] border border-border bg-surface-2" />
        <div className="h-[280px] border border-border bg-surface-2" />
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col gap-px px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <div className="mb-2 flex items-baseline justify-between">
        <h1 className="m-0 font-serif text-[clamp(22px,3.5vw,28px)] font-bold tracking-[-0.01em] text-text-primary">
          Stocks
        </h1>
        {data.as_of && (
          <span className="border border-border bg-field px-[7px] py-[2px] text-[10.5px] text-text-muted">
            EOD · {formatDate(data.as_of)} · {data.universe_size} symbols
          </span>
        )}
      </div>
      <IndexStrip indices={data.indices} />
      <LeadersTable overview={data} />
      <SectorPanel sectors={data.sectors} />
    </div>
  );
}
```

- [ ] **Step 12.5: Rota** — `frontend/src/app/stocks/page.tsx`:

```tsx
import { MarketOverview } from "@/components/stocks/MarketOverview";

export const metadata = { title: "Stocks · Investintell" };

export default function StocksPage() {
  return <MarketOverview />;
}
```

- [ ] **Step 12.6: Nav** — em `frontend/src/components/shell/AppShell.tsx`, no primeiro item de `NAV_ITEMS`, trocar:

```tsx
    href: "/stocks/AAPL",
    match: (p) => p.startsWith("/stocks"),
    label: "Stock Analysis",
```

por:

```tsx
    href: "/stocks",
    match: (p) => p.startsWith("/stocks"),
    label: "Stocks",
```

- [ ] **Step 12.7: Typecheck + lint + commit**

```bash
cd /e/investintell-light/frontend && npm run typecheck && npm run lint && cd .. && git add frontend/src/components/stocks/ frontend/src/app/stocks/page.tsx frontend/src/components/shell/AppShell.tsx && git commit -m "feat(frontend): landing /stocks — índices, market leaders e setores ao vivo"
```

---

### Task 13: Detalhe — chart interativo + header live

**Files:**
- Modify: `frontend/src/components/stocks/StockAnalysisView.tsx`

- [ ] **Step 13.1: Query do history** — em `StockAnalysisView` (componente externo), junto da query existente:

```tsx
  const history = useQuery({
    queryKey: ["history", ticker],
    queryFn: ({ signal }) => fetchStockHistory(ticker, 2520, signal),
    staleTime: 60 * 60 * 1000,
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
  });
```

Imports novos: `fetchStockHistory` em `@/lib/api/client`; `InteractiveChart` de `@/components/charts/InteractiveChart`; `AddToPortfolio` de `@/components/stocks/AddToPortfolio`; `useLiveTicks` de `@/lib/livefeed/useLiveTicks`.

Passe `historyBars={history.data?.bars ?? []}` para `AnalysisContent` (novo prop). O chart é renderizável assim que `history` chegar — não bloqueie a página no `isPending` do history (apenas do analysis, como hoje).

- [ ] **Step 13.2: Header ao vivo** — em `AnalysisContent`, antes do `return`:

```tsx
  const { ticks, status: feedStatus } = useLiveTicks([header.ticker]);
  const live = ticks[header.ticker];
  const shownLast = live?.price ?? header.last_close;
  // Baseline do live = header.last_close (último close do banco): durante o
  // pregão é o close de ontem → variação de HOJE. Sem tick, EOD do payload.
  const shownChange = live ? shownLast - header.last_close : header.change;
  const shownChangePct =
    live && header.last_close > 0 ? shownLast / header.last_close - 1 : header.change_pct;
```

No bloco do header, substituir os três usos: `formatCurrency(header.last_close)` → `formatCurrency(shownLast)`; `formatCurrency(header.change, ...)` → `formatCurrency(shownChange, ...)`; `formatPercent(header.change_pct, ...)` → `formatPercent(shownChangePct, ...)`; e `changeTone` passa a derivar de `shownChange`. O badge `EOD · {formatDate(header.as_of)}` vira:

```tsx
            <span className="border border-border bg-field px-[7px] py-[2px] text-[10.5px] text-text-muted">
              {feedStatus === "live" && live ? (
                <span className="text-gain">● LIVE</span>
              ) : (
                <>EOD · {formatDate(header.as_of)}</>
              )}
            </span>
            <AddToPortfolio ticker={header.ticker} />
```

- [ ] **Step 13.3: Chart no topo, range único** — em `AnalysisContent`:

1. REMOVER o bloco `{/* ── Range switcher ── */}` inteiro do header (o controle agora vive na toolbar do chart — `onRangeChange` continua sendo o mesmo callback, que atualiza a URL e a query do analysis).
2. REMOVER o bloco `{/* ── Price chart (candles + volume) ── */}` (o `Card` com `EChart option={priceOption}`), o `priceOption` `useMemo`, o import `buildPriceOption` e o swatch `square-grey` se ficar órfão.
3. ADICIONAR, logo após o header e antes dos KPI tiles:

```tsx
      {/* ── Interactive chart (IXChart + livefeed) ── */}
      <div className="mb-px">
        <InteractiveChart
          symbol={header.ticker}
          bars={historyBars}
          range={range}
          onRangeChange={onRangeChange}
        />
      </div>
```

`AnalysisContent` ganha o prop `historyBars: HistoryBar[]` (tipo de `@/lib/api/client`; estruturalmente idêntico a `Bar` do engine).

- [ ] **Step 13.4: Typecheck + lint + suíte**

```bash
cd /e/investintell-light/frontend && npm run typecheck && npm run lint && npm run test
```
Expected: PASS.

- [ ] **Step 13.5: Commit**

```bash
cd /e/investintell-light && git add frontend/src/components/stocks/StockAnalysisView.tsx && git commit -m "feat(frontend): detalhe da ação — chart interativo no topo e header ao vivo"
```

---

### Task 14: Verificação ponta-a-ponta

- [ ] **Step 14.1: Suítes completas**

```bash
cd /e/investintell-light/backend && uv run pytest -q && cd ../frontend && npm run test && npm run typecheck && npm run lint
```
Expected: tudo PASS.

- [ ] **Step 14.2: Smoke do backend** (precisa de `TIINGO_TOKEN` e DB local com universo backfillado):

```bash
cd /e/investintell-light/backend && uv run uvicorn app.main:app --port 8000 &
sleep 3
curl -s "http://localhost:8000/stocks/overview" | head -c 400
curl -s "http://localhost:8000/stocks/TSLA/history?bars=40" | head -c 400
```
Expected: overview com `gainers`/`sectors` não-vazios (após Tasks 1–2 + backfill); history com 40 barras `{t,o,h,l,c,v}`.

- [ ] **Step 14.3: Smoke visual** — com o backend de cima rodando:

```bash
cd /e/investintell-light/frontend && NEXT_PUBLIC_LIVEFEED_WS_URL=wss://livefeed-production-2c39.up.railway.app/stream npm run dev
```

Abrir no browser (Playwright MCP ou manual) e verificar:
1. `http://localhost:3000/stocks` — strip de índices com sparklines; tabs de leaders trocam; durante o pregão, células Last piscam; clique numa linha navega ao detalhe; "+" abre o popover de portfólio.
2. `http://localhost:3000/stocks/TSLA` — chart interativo abre direto (pan por arrasto, zoom de roda, crosshair com legenda OHLC, SMA20 ligada); botões de range atualizam chart E métricas abaixo; badge LIVE durante o pregão (fora dele, EOD — nunca preço simulado); KPIs/rolling/histograma/news preservados.
3. Tema dark (toggle no header): o canvas re-monta com tokens escuros (o `<main>` é re-keyed pelo shell — confirmar que o chart re-renderiza com as cores novas).

- [ ] **Step 14.4: Commit final + atualização do plano**

Marcar checkboxes concluídos neste arquivo e:

```bash
cd /e/investintell-light && git add docs/superpowers/plans/2026-06-12-stocks-redesign.md && git commit -m "docs: plano stocks-redesign executado"
```

---

## Riscos & notas para o executor

- **`paths` em api.d.ts**: os type aliases da Task 6 dependem do regen do OpenAPI (Step 6.1) — rode-o ANTES do typecheck.
- **Engine port**: a fonte é `E:\investintell-datalake-workers\design\assets\chart-engine.js` (763 linhas). As únicas mudanças permitidas são as 10 transformações da Task 8 — resista a "melhorar" o render durante o port; refactors vêm depois com o chart funcionando.
- **`PositionBody`**: validar o nome do campo (`quantity`) no `api.d.ts` gerado (Task 11).
- **Dados locais**: a landing só mostra conteúdo se `sync_universe.py` + `backfill_universe_eod.py` tiverem populado o DB local; em DB vazio a página renderiza com listas vazias (estado documentado).
- **Produção (Railway/Vercel)**: setar `NEXT_PUBLIC_LIVEFEED_WS_URL` no ambiente do frontend; rodar `alembic upgrade head` + `enrich_sectors.py` no deploy do backend.
