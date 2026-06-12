# Funds chart interativo + Compare autocomplete — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detalhe do fundo (`/funds/[id]`) com o chart interativo IXChart (ETF = OHLCV+live como stocks; mutual fund/MMF = NAV linha/área) e campo Compare com dropdown de sugestões (estilo Barchart) nos charts de stocks e funds.

**Architecture:** Backend ganha `GET /funds/{instrument_id}/history` (mesmo contrato `{t,o,h,l,c,v}` do stocks/history + discriminador `mode`) e `GET /search/symbols` (busca unificada universe+funds, ranking puro unit-tested). Frontend: `InteractiveChart` ganha prop `mode`, novo `SymbolSearchInput` substitui o input livre do Compare, `FundProfileView` troca o NAV estático pelo chart interativo.

**Tech Stack:** FastAPI + SQLAlchemy async (backend); Next.js 15, TanStack Query 5, canvas 2D, vitest (frontend). pnpm workspace.

**Spec:** `docs/superpowers/specs/2026-06-12-funds-chart-compare-design.md`

**Working dir:** worktree `E:\investintell-light\.worktrees\stocks-redesign` (branch `feat/stocks-redesign`). Backend: `uv run` a partir de `<worktree>/backend`; frontend: `pnpm` a partir de `<worktree>/frontend`. NUNCA tocar na working tree principal `E:\investintell-light`.

---

## File Structure

**Backend (`backend/`):**

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `app/schemas/market.py` | Modify | `FundHistoryResponse` (mode/instrument_id) e `SymbolSearchResult` |
| `app/api/routes/funds.py` | Modify | rota `GET /funds/{instrument_id}/history` (ETF→OHLCV, senão NAV) |
| `app/services/symbol_search.py` | Create | readers SQL finos + `rank_hits` puro (unit-tested) |
| `app/api/routes/search.py` | Create | rota `GET /search/symbols` |
| `app/main.py` | Modify | registrar `search_router` |
| `tests/test_fund_history_route.py` | Create | rota history (helpers stubados) |
| `tests/test_symbol_search.py` | Create | `rank_hits` puro |
| `tests/test_search_route.py` | Create | rota search (service stubado) |

**Frontend (`frontend/`):**

| Arquivo | Ação | Responsabilidade |
|---|---|---|
| `src/lib/api/client.ts` | Modify | `fetchFundHistory`, `fetchSymbolSearch` + tipos |
| `src/lib/api/api.d.ts` | Modify | gerado (regen OpenAPI) |
| `src/components/charts/SymbolSearchInput.tsx` | Create | input + dropdown debounce/teclado |
| `src/components/charts/InteractiveChart.tsx` | Modify | prop `mode`, Compare via SymbolSearchInput |
| `src/components/funds/FundProfileView.tsx` | Modify | NAV estático → InteractiveChart |

---

### Task 0: Preparar o worktree

- [ ] **Step 0.1: Instalar dependências do frontend no worktree** (node_modules não existe lá):

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && pnpm install
```
Expected: `Done` sem erros.

- [ ] **Step 0.2: Sanity das suítes no worktree**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest -q 2>&1 | tail -1 && cd ../frontend && pnpm run test 2>&1 | grep "Tests"
```
Expected: `681 passed` e `11 passed` (estado herdado da branch).

---

### Task 1: Schemas — `FundHistoryResponse` e `SymbolSearchResult`

**Files:**
- Modify: `backend/app/schemas/market.py`

- [ ] **Step 1.1: Adicionar ao final de `app/schemas/market.py`** (imports novos no topo: `import uuid` e `from typing import Literal`):

```python
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
```

- [ ] **Step 1.2: Sanity import + commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run python -c "from app.schemas.market import FundHistoryResponse, SymbolSearchResult; print('ok')" && cd .. && git add backend/app/schemas/market.py && git commit -m "feat(backend): schemas FundHistoryResponse e SymbolSearchResult"
```

---

### Task 2: Rota `GET /funds/{instrument_id}/history` (TDD)

**Files:**
- Modify: `backend/app/api/routes/funds.py`
- Test: `backend/tests/test_fund_history_route.py`

- [ ] **Step 2.1: Escrever os testes** — `backend/tests/test_fund_history_route.py`:

```python
"""Tests de GET /funds/{instrument_id}/history (helpers stubados, sem DB/Tiingo)."""

import datetime as dt
import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.main import create_app
from app.tiingo.exceptions import TiingoError

import app.api.routes.funds as funds_routes

FUND_ID = uuid.uuid4()


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _etf() -> SimpleNamespace:
    return SimpleNamespace(instrument_id=FUND_ID, ticker="SPY", fund_type="etf")


def _mutual() -> SimpleNamespace:
    return SimpleNamespace(instrument_id=FUND_ID, ticker="VFIAX", fund_type="mutual_fund")


OHLCV_ROWS = [
    (dt.date(2026, 6, 10), 100.0, 105.0, 99.0, 104.0, 1_000_000),
    (dt.date(2026, 6, 11), 104.0, 106.0, 103.0, 105.5, 1_200_000),
]
NAV_ROWS = [(dt.date(2026, 6, 10), 412.31), (dt.date(2026, 6, 11), 414.02)]


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def get_fund(session, instrument_id):
        return _etf()

    async def ensure(session, client, symbols, start, end):
        return None

    async def adj(session, ticker, start, end):
        assert ticker == "SPY"
        return OHLCV_ROWS

    async def nav(session, instrument_id, start, end):
        return NAV_ROWS

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    monkeypatch.setattr(funds_routes, "_ensure_eod_or_http_error", ensure)
    monkeypatch.setattr(funds_routes, "_select_adj_ohlcv_rows", adj)
    monkeypatch.setattr(funds_routes, "_select_nav_rows", nav)


@pytest.mark.anyio
async def test_etf_uses_ohlcv_path() -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history?bars=100")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "ohlcv" and body["ticker"] == "SPY" and body["count"] == 2
    bar = body["bars"][-1]
    assert bar["t"] == int(dt.datetime(2026, 6, 11, tzinfo=dt.timezone.utc).timestamp() * 1000)
    assert (bar["o"], bar["h"], bar["l"], bar["c"], bar["v"]) == (104.0, 106.0, 103.0, 105.5, 1_200_000)


@pytest.mark.anyio
async def test_mutual_fund_uses_nav_path(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_fund(session, instrument_id):
        return _mutual()

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "nav" and body["count"] == 2
    bar = body["bars"][-1]
    assert bar["o"] == bar["h"] == bar["l"] == bar["c"] == 414.02
    assert bar["v"] == 0


@pytest.mark.anyio
async def test_etf_degrades_to_nav_when_tiingo_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    async def ensure(session, client, symbols, start, end):
        raise TiingoError("down")

    monkeypatch.setattr(funds_routes, "_ensure_eod_or_http_error", ensure)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 200
    assert resp.json()["mode"] == "nav"


@pytest.mark.anyio
async def test_404_unknown_fund(monkeypatch: pytest.MonkeyPatch) -> None:
    async def none(session, instrument_id):
        return None

    monkeypatch.setattr(funds_routes, "_get_fund", none)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_404_when_no_series_at_all(monkeypatch: pytest.MonkeyPatch) -> None:
    async def get_fund(session, instrument_id):
        return _mutual()

    async def empty(session, instrument_id, start, end):
        return []

    monkeypatch.setattr(funds_routes, "_get_fund", get_fund)
    monkeypatch.setattr(funds_routes, "_select_nav_rows", empty)
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history")
    assert resp.status_code == 404


@pytest.mark.anyio
async def test_bars_validation() -> None:
    async with _client() as client:
        resp = await client.get(f"/funds/{FUND_ID}/history?bars=2")
    assert resp.status_code == 422
```

- [ ] **Step 2.2: Rodar e ver falhar**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest tests/test_fund_history_route.py -q
```
Expected: FAIL — `AttributeError: module ... has no attribute '_get_fund'` / 404 (rota não existe).

- [ ] **Step 2.3: Implementar** — em `backend/app/api/routes/funds.py`.

Imports novos (juntar aos existentes):

```python
import datetime as dt

from sqlalchemy import select

from app.api._shared import ensure_eod_or_http_error
from app.api.routes.stocks import _select_adj_ohlcv_rows
from app.core.tiingo_provider import get_tiingo_client
from app.models.fund import Fund, FundNav
from app.schemas.market import FundHistoryResponse, HistoryBar
from app.tiingo.client import TiingoClient
from app.tiingo.exceptions import TiingoError
```

Acrescentar nota ao docstring do módulo (o contrato DB-only ganha UMA exceção declarada):

```
ETF exception: GET /funds/{id}/history may warm eod_prices via the sanctioned
ingestion path (app.api._shared.ensure_eod_or_http_error) — ETFs trade like
stocks and reuse the stocks OHLCV series; on Tiingo failure it degrades to
the local fund_nav series (mode "nav").
```

Helpers + rota (após `get_fund_profile`). `_ensure_eod_or_http_error` é alias módulo-level para stub nos testes:

```python
_ensure_eod_or_http_error = ensure_eod_or_http_error

import logging

logger = logging.getLogger(__name__)


async def _get_fund(session: AsyncSession, instrument_id: uuid.UUID) -> Fund | None:
    return await session.get(Fund, instrument_id)


async def _select_nav_rows(
    session: AsyncSession, instrument_id: uuid.UUID, start: dt.date, end: dt.date
) -> list[tuple[dt.date, float]]:
    """(nav_date, nav) em [start, end], ASC, NAVs nulos descartados."""
    result = await session.execute(
        select(FundNav.nav_date, FundNav.nav)
        .where(
            FundNav.instrument_id == instrument_id,
            FundNav.nav_date >= start,
            FundNav.nav_date <= end,
            FundNav.nav.is_not(None),
        )
        .order_by(FundNav.nav_date)
    )
    return [(d, float(v)) for d, v in result.all()]


def _ms(d: dt.date) -> int:
    return int(dt.datetime(d.year, d.month, d.day, tzinfo=dt.timezone.utc).timestamp() * 1000)


@router.get("/funds/{instrument_id}/history", response_model=FundHistoryResponse)
async def get_fund_history(
    instrument_id: uuid.UUID,
    session: SessionDep,
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
    bars: Annotated[
        int, Query(ge=30, le=5000, description="Nº de barras diárias mais recentes.")
    ] = 2520,
) -> FundHistoryResponse:
    """Série do fundo no contrato do chart interativo ({t,o,h,l,c,v} + mode).

    ETF com ticker → OHLCV ajustado de eod_prices (mesmo caminho dos stocks,
    com warm on-demand); demais fundos (ou ETF sem cobertura/Tiingo fora) →
    NAV de fund_nav com o=h=l=c=nav, v=0.
    """
    fund = await _get_fund(session, instrument_id)
    if fund is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")

    today = dt.date.today()
    start = today - dt.timedelta(days=int(bars * 1.6) + 10)

    if fund.fund_type == "etf" and fund.ticker:
        symbol = fund.ticker.strip().upper()
        try:
            await _ensure_eod_or_http_error(session, client, [symbol], start, today)
            rows = await _select_adj_ohlcv_rows(session, symbol, start, today)
        except (HTTPException, TiingoError) as exc:
            logger.warning("Fund %s ETF history degraded to NAV: %s", instrument_id, exc)
            rows = []
        if rows:
            rows = rows[-bars:]
            return FundHistoryResponse(
                instrument_id=instrument_id, ticker=symbol, mode="ohlcv", count=len(rows),
                bars=[
                    HistoryBar(t=_ms(d), o=o, h=h, l=lo, c=c, v=int(v or 0))
                    for d, o, h, lo, c, v in rows
                ],
            )

    nav_rows = await _select_nav_rows(session, instrument_id, start, today)
    if not nav_rows:
        raise HTTPException(
            status_code=404, detail=f"No price or NAV history for fund {instrument_id}."
        )
    nav_rows = nav_rows[-bars:]
    return FundHistoryResponse(
        instrument_id=instrument_id, ticker=fund.ticker, mode="nav", count=len(nav_rows),
        bars=[HistoryBar(t=_ms(d), o=v, h=v, l=v, c=v, v=0) for d, v in nav_rows],
    )
```

Nota: `SessionDep` já existe em funds.py (alias de `Annotated[AsyncSession, Depends(get_session)]`); `Annotated`/`Query`/`HTTPException`/`uuid` já estão importados. Se `logger` já existir no módulo, não redeclarar.

- [ ] **Step 2.4: Rodar e ver passar (suíte inteira)**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest -q 2>&1 | tail -1
```
Expected: `687 passed` (6 novos, sem regressões).

- [ ] **Step 2.5: Commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && git add backend/app/api/routes/funds.py backend/tests/test_fund_history_route.py && git commit -m "feat(backend): GET /funds/{id}/history — ETF OHLCV / NAV fallback p/ chart interativo"
```

---

### Task 3: `symbol_search` service + rota `GET /search/symbols` (TDD)

**Files:**
- Create: `backend/app/services/symbol_search.py`
- Create: `backend/app/api/routes/search.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_symbol_search.py`, `backend/tests/test_search_route.py`

- [ ] **Step 3.1: Testes do ranking puro** — `backend/tests/test_symbol_search.py`:

```python
"""Tests do ranking puro do symbol search (sem DB)."""

import uuid

from app.services.symbol_search import SymbolHit, rank_hits

FID = uuid.uuid4()


def _stock(sym: str, name: str = "") -> SymbolHit:
    return SymbolHit(symbol=sym, name=name or f"{sym} Inc", kind="stock", instrument_id=None)


def _fund(sym: str, kind: str = "etf") -> SymbolHit:
    return SymbolHit(symbol=sym, name=f"{sym} Fund", kind=kind, instrument_id=FID)


def test_exact_ticker_first_then_prefix_then_name() -> None:
    hits = [_stock("SPYX"), _stock("XSPY", name="Spy Holdings"), _stock("SPY")]
    out = rank_hits(hits, "SPY", 10)
    assert [h.symbol for h in out] == ["SPY", "SPYX", "XSPY"]


def test_fund_wins_dedup_over_stock() -> None:
    out = rank_hits([_stock("SPY"), _fund("SPY")], "SPY", 10)
    assert len(out) == 1
    assert out[0].kind == "etf" and out[0].instrument_id == FID


def test_limit_applied_after_ranking() -> None:
    hits = [_stock(f"AB{i}") for i in range(30)] + [_stock("AB")]
    out = rank_hits(hits, "AB", 5)
    assert len(out) == 5 and out[0].symbol == "AB"


def test_case_insensitive_query() -> None:
    out = rank_hits([_stock("MSFT")], "msft", 10)
    assert out[0].symbol == "MSFT"
```

- [ ] **Step 3.2: Rodar e ver falhar**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest tests/test_symbol_search.py -q
```
Expected: FAIL — `ModuleNotFoundError: app.services.symbol_search`.

- [ ] **Step 3.3: Implementar o service** — `backend/app/services/symbol_search.py`:

```python
"""Symbol search unificado (Compare autocomplete): universe + funds.

Sem Tiingo, sem cache — ILIKE em duas tabelas locais pequenas a cada tecla.
``rank_hits`` é puro (unit-tested); os readers SQL são finos.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.fund import Fund
from app.models.universe import UniverseConstituent

FETCH_CAP = 50  # por tabela, antes do ranking


@dataclass(frozen=True)
class SymbolHit:
    symbol: str
    name: str | None
    kind: str  # "stock" | fund_type ("etf" | "mutual_fund" | "mmf")
    instrument_id: uuid.UUID | None


async def fetch_stock_hits(session: AsyncSession, q: str) -> list[SymbolHit]:
    prefix = f"{q.upper()}%"
    sub = f"%{q}%"
    result = await session.execute(
        select(UniverseConstituent.ticker, UniverseConstituent.name)
        .where(
            UniverseConstituent.status == "active",
            (UniverseConstituent.ticker.like(prefix))
            | (UniverseConstituent.name.ilike(sub)),
        )
        .limit(FETCH_CAP)
    )
    return [SymbolHit(symbol=t, name=n, kind="stock", instrument_id=None) for t, n in result.all()]


async def fetch_fund_hits(session: AsyncSession, q: str) -> list[SymbolHit]:
    prefix = f"{q.upper()}%"
    sub = f"%{q}%"
    result = await session.execute(
        select(Fund.ticker, Fund.name, Fund.fund_type, Fund.instrument_id)
        .where(
            Fund.ticker.is_not(None),
            (func.upper(Fund.ticker).like(prefix)) | (Fund.name.ilike(sub)),
        )
        .limit(FETCH_CAP)
    )
    return [
        SymbolHit(symbol=t.upper(), name=n, kind=ft, instrument_id=iid)
        for t, n, ft, iid in result.all()
    ]


def rank_hits(hits: list[SymbolHit], q: str, limit: int) -> list[SymbolHit]:
    """Dedup por symbol (último vence — passar stocks ANTES de funds) e
    ordena: ticker exato, prefixo de ticker, resto; tiebreak alfabético."""
    q_upper = q.upper()
    by_symbol: dict[str, SymbolHit] = {}
    for h in hits:
        by_symbol[h.symbol] = h

    def key(h: SymbolHit) -> tuple[int, str]:
        if h.symbol == q_upper:
            rank = 0
        elif h.symbol.startswith(q_upper):
            rank = 1
        else:
            rank = 2
        return (rank, h.symbol)

    return sorted(by_symbol.values(), key=key)[:limit]
```

- [ ] **Step 3.4: Rodar e ver passar**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest tests/test_symbol_search.py -q
```
Expected: 4 passed.

- [ ] **Step 3.5: Teste da rota** — `backend/tests/test_search_route.py`:

```python
"""Tests de GET /search/symbols (readers stubados, sem DB)."""

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.services.symbol_search import SymbolHit

import app.api.routes.search as search_routes


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.fixture(autouse=True)
def _stub(monkeypatch: pytest.MonkeyPatch):
    async def stocks(session, q):
        return [SymbolHit(symbol="SPYX", name="SPYX Inc", kind="stock", instrument_id=None)]

    async def funds(session, q):
        return [SymbolHit(symbol="SPY", name="SPDR S&P 500", kind="etf", instrument_id=None)]

    monkeypatch.setattr(search_routes, "fetch_stock_hits", stocks)
    monkeypatch.setattr(search_routes, "fetch_fund_hits", funds)


@pytest.mark.anyio
async def test_search_merges_and_ranks() -> None:
    async with _client() as client:
        resp = await client.get("/search/symbols?q=SPY")
    assert resp.status_code == 200
    body = resp.json()
    assert [r["symbol"] for r in body] == ["SPY", "SPYX"]  # exato primeiro
    assert body[0]["kind"] == "etf"


@pytest.mark.anyio
async def test_search_requires_q() -> None:
    async with _client() as client:
        assert (await client.get("/search/symbols")).status_code == 422
        assert (await client.get("/search/symbols?q=")).status_code == 422


@pytest.mark.anyio
async def test_search_limit_le_25() -> None:
    async with _client() as client:
        assert (await client.get("/search/symbols?q=A&limit=26")).status_code == 422
```

- [ ] **Step 3.6: Rodar e ver falhar**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest tests/test_search_route.py -q
```
Expected: FAIL — `ModuleNotFoundError: app.api.routes.search`.

- [ ] **Step 3.7: Implementar a rota** — `backend/app/api/routes/search.py`:

```python
"""Symbol search (Compare autocomplete): GET /search/symbols.

DB-only: universe_constituents + funds locais; nunca Tiingo. Sem cache de
catálogo — a query muda a cada tecla e viraria churn.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.market import SymbolSearchResult
from app.services.symbol_search import fetch_fund_hits, fetch_stock_hits, rank_hits

router = APIRouter(prefix="/search", tags=["search"])


@router.get("/symbols", response_model=list[SymbolSearchResult])
async def search_symbols(
    session: Annotated[AsyncSession, Depends(get_session)],
    q: Annotated[str, Query(min_length=1, max_length=40)],
    limit: Annotated[int, Query(ge=1, le=25)] = 10,
) -> list[SymbolSearchResult]:
    """Sugestões para o Compare: ações (universe) e fundos com ticker."""
    query = q.strip()
    if not query:
        return []
    # stocks ANTES de funds: no dedup por symbol o fund (mais específico) vence.
    hits = (await fetch_stock_hits(session, query)) + (await fetch_fund_hits(session, query))
    return [
        SymbolSearchResult(
            symbol=h.symbol, name=h.name, kind=h.kind, instrument_id=h.instrument_id
        )
        for h in rank_hits(hits, query, limit)
    ]
```

Registrar em `backend/app/main.py` — junto aos imports de routers:

```python
from app.api.routes import search as search_router
```

e junto aos `include_router` (após `funds_router`):

```python
    application.include_router(search_router.router)
```

- [ ] **Step 3.8: Rodar suíte inteira**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest -q 2>&1 | tail -1
```
Expected: `694 passed` (7 novos no total da task).

- [ ] **Step 3.9: Commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && git add backend/app/services/symbol_search.py backend/app/api/routes/search.py backend/app/main.py backend/tests/test_symbol_search.py backend/tests/test_search_route.py && git commit -m "feat(backend): GET /search/symbols — busca unificada universe+funds com ranking"
```

---

### Task 4: OpenAPI regen + client fetchers

**Files:**
- Modify: `backend/openapi.json` (gerado), `frontend/src/lib/api/api.d.ts` (gerado)
- Modify: `frontend/src/lib/api/client.ts`

- [ ] **Step 4.1: Regenerar**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run python scripts/export_openapi.py && cd ../frontend && pnpm run types
```
Expected: `api.d.ts` ganha `"/funds/{instrument_id}/history"` e `"/search/symbols"`.

- [ ] **Step 4.2: Tipos + fetchers** — em `frontend/src/lib/api/client.ts`, na seção de type aliases (junto de `StockHistoryOperation`):

```ts
type FundHistoryOperation = paths["/funds/{instrument_id}/history"]["get"];
export type FundHistory =
  FundHistoryOperation["responses"]["200"]["content"]["application/json"];

type SymbolSearchOperation = paths["/search/symbols"]["get"];
export type SymbolSearchResult =
  SymbolSearchOperation["responses"]["200"]["content"]["application/json"][number];
```

E os fetchers (junto de `fetchStockHistory`):

```ts
export function fetchFundHistory(
  instrumentId: string,
  bars = 2520,
  signal?: AbortSignal,
): Promise<FundHistory> {
  return request<FundHistory>(
    `/funds/${encodeURIComponent(instrumentId)}/history?bars=${bars}`,
    signal,
  );
}

export function fetchSymbolSearch(
  q: string,
  signal?: AbortSignal,
): Promise<SymbolSearchResult[]> {
  return request<SymbolSearchResult[]>(
    `/search/symbols?q=${encodeURIComponent(q)}`,
    signal,
  );
}
```

- [ ] **Step 4.3: Typecheck + commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/frontend && pnpm run typecheck && cd .. && git add backend/openapi.json frontend/src/lib/api/api.d.ts frontend/src/lib/api/client.ts && git commit -m "feat(frontend): tipos e fetchers de fund history e symbol search"
```

---

### Task 5: `SymbolSearchInput`

**Files:**
- Create: `frontend/src/components/charts/SymbolSearchInput.tsx`

- [ ] **Step 5.1: Criar o componente**

```tsx
"use client";

/**
 * Input do Compare com dropdown de sugestões (estilo Barchart): debounce
 * 250ms → GET /search/symbols; teclado ↑/↓/Enter/Esc; clique fora fecha.
 * Enter sem item destacado usa o texto cru como ticker (fallback).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import { fetchSymbolSearch, type SymbolSearchResult } from "@/lib/api/client";

const KIND_LABEL: Record<string, string> = {
  stock: "Stock",
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "MMF",
};

export function SymbolSearchInput({
  onSelect,
  onClear,
  active,
  placeholder = "Compare…",
}: {
  onSelect: (item: SymbolSearchResult) => void;
  onClear: () => void;
  /** Símbolo ativo (mostra o ×). */
  active: string | null;
  placeholder?: string;
}) {
  const [text, setText] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const [hi, setHi] = useState(-1);
  const rootRef = useRef<HTMLDivElement>(null);

  // debounce 250ms
  useEffect(() => {
    const t = setTimeout(() => setQ(text.trim()), 250);
    return () => clearTimeout(t);
  }, [text]);

  const { data: results = [] } = useQuery({
    queryKey: ["symbol-search", q],
    queryFn: ({ signal }) => fetchSymbolSearch(q, signal),
    enabled: q.length >= 1,
    staleTime: 5 * 60 * 1000,
  });

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (!rootRef.current?.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener("mousedown", onDown);
    return () => window.removeEventListener("mousedown", onDown);
  }, [open]);

  const pick = (item: SymbolSearchResult) => {
    onSelect(item);
    setText("");
    setQ("");
    setOpen(false);
    setHi(-1);
  };

  return (
    <div ref={rootRef} className="relative flex items-center gap-1">
      <input
        value={text}
        onChange={(e) => {
          setText(e.target.value);
          setOpen(true);
          setHi(-1);
        }}
        onFocus={() => text && setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") {
            e.preventDefault();
            setHi((i) => Math.min(i + 1, results.length - 1));
          } else if (e.key === "ArrowUp") {
            e.preventDefault();
            setHi((i) => Math.max(i - 1, -1));
          } else if (e.key === "Enter") {
            e.preventDefault();
            if (hi >= 0 && results[hi]) pick(results[hi]);
            else if (text.trim()) {
              // fallback: texto cru como ticker de ação
              pick({
                symbol: text.trim().toUpperCase(),
                name: null,
                kind: "stock",
                instrument_id: null,
              });
            }
          } else if (e.key === "Escape") {
            setOpen(false);
            setHi(-1);
          }
        }}
        placeholder={placeholder}
        aria-label="Compare symbol"
        aria-expanded={open && results.length > 0}
        role="combobox"
        className="h-7 w-32 border border-border-strong bg-field px-2 text-[11px] text-text-primary placeholder:text-text-muted"
      />
      {active && (
        <button
          type="button"
          aria-label={`Remove comparison ${active}`}
          className="text-[11px] text-text-muted hover:text-text-primary"
          onClick={onClear}
        >
          ×
        </button>
      )}
      {open && results.length > 0 && (
        <ul
          role="listbox"
          className="absolute left-0 top-full z-30 mt-1 max-h-64 w-72 overflow-auto border border-border-strong bg-surface-1 shadow-lg"
        >
          {results.map((r, i) => (
            <li key={`${r.kind}:${r.symbol}`} role="option" aria-selected={i === hi}>
              <button
                type="button"
                onMouseEnter={() => setHi(i)}
                onClick={() => pick(r)}
                className={`flex w-full items-baseline gap-2 px-2 py-1.5 text-left text-[12px] ${
                  i === hi ? "bg-layer-hover" : ""
                }`}
              >
                <span className="font-bold text-accent">{r.symbol}</span>
                <span className="min-w-0 flex-1 truncate text-text-secondary">{r.name}</span>
                <span className="shrink-0 text-[10px] uppercase text-text-muted">
                  {KIND_LABEL[r.kind] ?? r.kind}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
```

- [ ] **Step 5.2: Typecheck + commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/frontend && pnpm run typecheck && cd .. && git add frontend/src/components/charts/SymbolSearchInput.tsx && git commit -m "feat(frontend): SymbolSearchInput — autocomplete do Compare"
```

---

### Task 6: `InteractiveChart` — prop `mode` + Compare com dropdown

**Files:**
- Modify: `frontend/src/components/charts/InteractiveChart.tsx`

- [ ] **Step 6.1: Imports e assinatura.** Adicionar imports:

```ts
import { fetchFundHistory, type SymbolSearchResult } from "@/lib/api/client";
import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
```

(`fetchStockHistory`, `RANGE_PRESETS`, `RangePreset` já estão importados.)

Assinatura do componente — adicionar prop `mode`:

```ts
export function InteractiveChart({
  symbol,
  bars,
  range,
  onRangeChange,
  mode = "ohlcv",
  className,
}: {
  symbol: string;
  bars: Bar[];
  range: RangePreset;
  onRangeChange: (next: RangePreset) => void;
  /** "nav" = série de NAV (mutual fund): só Line/Area, sem VOL nem live. */
  mode?: "ohlcv" | "nav";
  className?: string;
}) {
```

- [ ] **Step 6.2: Estado sensível ao mode.** Substituir as inicializações de `type` e `panes`:

```ts
  const [type, setType] = useState<ChartType>(mode === "nav" ? "line" : "candles");
  const [panes, setPanes] = useState({ volume: mode !== "nav", rsi: false });
```

E logo após os arrays TYPES/TOOLS (fora do componente eles são constantes; DENTRO do componente, antes do return):

```ts
  const typeOptions = mode === "nav" ? TYPES.filter((t) => t.id === "line" || t.id === "area") : TYPES;
```

No JSX da toolbar: o map de tipos passa a iterar `typeOptions`; o botão VOL é envolvido em `{mode !== "nav" && (...)}`; o botão LIVE inteiro (incluindo o `<div className="flex-1" />` fica) é envolvido em `{mode !== "nav" && (...)}`.

- [ ] **Step 6.3: Live guard.** No effect do feed:

```ts
  useEffect(() => {
    if (!live || mode === "nav") return;
    return subscribeTicks(symbol, (tick) => chartRef.current?.applyTick(tick.price, tick.size));
  }, [symbol, live, mode]);
```

- [ ] **Step 6.4: Compare via SymbolSearchInput.** Substituir os states `compare`/`compareActive`:

```ts
  const [compareSel, setCompareSel] = useState<SymbolSearchResult | null>(null);
```

Substituir a query do compare:

```ts
  const { data: compareBars } = useQuery({
    queryKey: [
      "compare-history",
      compareSel?.kind,
      compareSel?.symbol,
      compareSel?.instrument_id,
    ],
    queryFn: ({ signal }) =>
      compareSel!.instrument_id &&
      (compareSel!.kind === "mutual_fund" || compareSel!.kind === "mmf")
        ? fetchFundHistory(compareSel!.instrument_id, 2520, signal)
        : fetchStockHistory(compareSel!.symbol, 2520, signal),
    enabled: compareSel != null,
    staleTime: 60 * 60 * 1000,
  });
```

Substituir o effect de comparação:

```ts
  useEffect(() => {
    chartRef.current?.setCompare(compareSel?.symbol ?? null, compareBars?.bars);
  }, [compareSel, compareBars]);
```

Substituir o `<form>` inteiro do Compare por:

```tsx
        <SymbolSearchInput
          active={compareSel?.symbol ?? null}
          onSelect={(item) => setCompareSel(item)}
          onClear={() => setCompareSel(null)}
        />
```

- [ ] **Step 6.5: Typecheck + lint + testes**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/frontend && pnpm run typecheck && pnpm run lint && pnpm run test
```
Expected: PASS (11 testes existentes intactos).

- [ ] **Step 6.6: Commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && git add frontend/src/components/charts/InteractiveChart.tsx && git commit -m "feat(frontend): InteractiveChart — mode nav e Compare com autocomplete"
```

---

### Task 7: `FundProfileView` — chart interativo

**Files:**
- Modify: `frontend/src/components/funds/FundProfileView.tsx`

- [ ] **Step 7.1: Query + estado.** Imports novos:

```ts
import { fetchFundHistory, RANGE_PRESETS, type RangePreset } from "@/lib/api/client";
import { InteractiveChart } from "@/components/charts/InteractiveChart";
```

(Manter `RANGE_PRESETS` só se o linter exigir uso — ele é usado pela toolbar do próprio chart, então NÃO importar `RANGE_PRESETS` aqui; importar apenas `RangePreset` e `fetchFundHistory`.)

Remover: `import { buildFundNavOption } from "@/lib/charts/fundnav";` e — se ficarem órfãos — `EChart`, `chartColors`/`ChartColors` e o state `colors` com seu `useEffect` (verificar se mais nenhum chart ECharts resta no arquivo; o navOption era o único).

Dentro de `FundProfileView`, junto da `profileQuery`:

```ts
  const [range, setRange] = useState<RangePreset>("1Y");
  const historyQuery = useQuery({
    queryKey: ["fund-history", instrumentId],
    queryFn: ({ signal }) => fetchFundHistory(instrumentId, 2520, signal),
    staleTime: 60 * 60 * 1000,
    retry: retryPolicy,
  });
```

Remover o `navOption` useMemo.

- [ ] **Step 7.2: Substituir o Card NAV.** Trocar o bloco:

```tsx
          <Card title="NAV" subtitle="2y window, decimated server-side">
            {fund.nav.length > 0 && navOption ? (
              <EChart option={navOption} className="h-[300px] w-full" />
            ) : (
              <p className="py-8 text-center text-[13px] text-text-muted">
                No NAV history in the synced window.
              </p>
            )}
          </Card>
```

por:

```tsx
          {historyQuery.data && historyQuery.data.bars.length > 0 ? (
            <InteractiveChart
              symbol={historyQuery.data.ticker ?? ""}
              bars={historyQuery.data.bars}
              mode={historyQuery.data.mode}
              range={range}
              onRangeChange={setRange}
            />
          ) : (
            <Card title={historyQuery.isPending ? "Loading chart…" : "NAV"}>
              <p className="py-8 text-center text-[13px] text-text-muted">
                {historyQuery.isPending
                  ? "Loading price history…"
                  : "No price or NAV history in the synced window."}
              </p>
            </Card>
          )}
```

- [ ] **Step 7.3: Typecheck + lint**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/frontend && pnpm run typecheck && pnpm run lint
```
Expected: PASS (sem imports órfãos).

- [ ] **Step 7.4: Commit**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && git add frontend/src/components/funds/FundProfileView.tsx && git commit -m "feat(frontend): fund profile — chart interativo (ETF=OHLCV+live, fund=NAV)"
```

---

### Task 8: Verificação ponta-a-ponta

- [ ] **Step 8.1: Suítes completas**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run pytest -q 2>&1 | tail -1 && cd ../frontend && pnpm run test 2>&1 | grep "Tests" && pnpm run typecheck && pnpm run lint
```
Expected: `694 passed` backend, `11 passed` frontend, typecheck/lint limpos.

- [ ] **Step 8.2: Smoke do backend** (porta 8001 para não colidir com a working tree principal):

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/backend && uv run uvicorn app.main:app --port 8001 &
sleep 5
curl -s "http://localhost:8001/search/symbols?q=SPY" | head -c 300
# pegar um ETF e um mutual fund reais:
curl -s "http://localhost:8001/funds?search=spdr&fund_type=etf&page_size=1" | python -c "import json,sys; print(json.load(sys.stdin)['items'][0]['instrument_id'])"
curl -s "http://localhost:8001/funds/<id-acima>/history?bars=40" | head -c 200   # mode ohlcv
curl -s "http://localhost:8001/funds?fund_type=mutual_fund&page_size=1" | python -c "import json,sys; print(json.load(sys.stdin)['items'][0]['instrument_id'])"
curl -s "http://localhost:8001/funds/<id-acima>/history?bars=40" | head -c 200   # mode nav, o==c
```
Expected: search devolve SPY (etf) primeiro; ETF history `"mode":"ohlcv"`; mutual fund `"mode":"nav"` com `o==h==l==c`.

- [ ] **Step 8.3: Smoke visual** — frontend dev na 3001 apontando para a 8001:

```bash
cd /e/investintell-light/.worktrees/stocks-redesign/frontend && NEXT_PUBLIC_API_URL=http://localhost:8001 NEXT_PUBLIC_LIVEFEED_WS_URL=wss://livefeed-production-2c39.up.railway.app/stream pnpm run dev -- --port 3001
```

(Confirmar o nome exato da env var da API em `src/lib/api/client.ts` — se for outro, usar o existente.)

Verificar no browser (Playwright MCP):
1. `/funds` → abrir um ETF: chart com candles, VOL, badge LIVE; toolbar completa.
2. Abrir um mutual fund: chart em linha, SEM botões Candles/OHLC/VOL/LIVE; ranges e SMA funcionam.
3. Em `/stocks/TSLA`: digitar "VFI" no Compare → dropdown sugere fundos e ações; selecionar um → série tracejada aparece e escala vira %.

- [ ] **Step 8.4: Marcar checkboxes + commit final**

```bash
cd /e/investintell-light/.worktrees/stocks-redesign && git add docs/superpowers/plans/2026-06-12-funds-chart-compare.md && git commit -m "docs: plano funds-chart-compare executado"
```

---

## Riscos & notas para o executor

- **Worktree only:** NUNCA rodar comandos git/arquivo na working tree principal `E:\investintell-light` — outra sessão trabalha lá. Tudo em `.worktrees/stocks-redesign`.
- **`SessionDep` em funds.py:** conferir o nome exato do alias (linha ~50); se a rota profile usa `SessionDep`, seguir o mesmo padrão.
- **Import circular:** `funds.py` importa `_select_adj_ohlcv_rows` de `stocks.py` — stocks.py não importa funds.py, sem ciclo. Se o linter reclamar de import privado, mover o selector para `app/services/_series.py` e importar dos dois lados.
- **`logger` em funds.py:** o módulo pode não ter logger — criar `logger = logging.getLogger(__name__)` + `import logging` se ausente.
- **Portas:** smoke usa 8001/3001 para não colidir com processos da working tree principal.
- **ETF sem `eod_prices` e Tiingo fora:** degrada para NAV (`mode: "nav"`) — comportamento declarado na spec.
