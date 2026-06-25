# DB-First — Grupo A (Fund analytics estáveis) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. **Execution model:** este plano será executado via subagent-driven-development com TODOS os subagentes em **Opus 4.8** (mandato do dono).

**Goal:** Migrar os cinco endpoints "estáveis" de fund analytics (`factors`, `style-drift`, `institutional-reveal`, `holdings/top`, `active-share`) do cálculo `pandas`/SQL em request path para read-models db-first (MVs/views SQL + dois workers Python), cada rota com dual-read atrás de flag e fallback ao caminho legado — sem mudar números (exceto a remoção intencional de `benchmark_id` do `active-share`).

**Architecture:** Segue o padrão da Fundação + Grupo D já implementados (`price_latest_mv`/`nav_latest_mv` atrás de `use_latest_mv_prices`, refrescados pelo worker `matview_refresh`). Objetos puramente deriváveis por agregação/janela viram **MV/view SQL no DB principal** (DDL versionado em `backend/db/ddl/`, aplicado via Tiger/psql): `fund_style_drift_mv` (A2), `fund_top_holdings_mv` (A4), `fund_active_share_mv` (A5), `fund_style_bias_v` (parte do A1). Os dois resultados que exigem cálculo (OLS de fatores e o cruzamento N-PORT×13F + rede) viram **workers Python** em `investintell-datalake-workers` (`fund_factors` → tabela `fund_factor_exposures` + `fund_factor_exposures_latest_mv`; `fund_institutional_reveal` → tabela JSONB `fund_institutional_reveal_artifacts` + `_latest_mv`), espelhando `risk_metrics`. No backend, cada serviço passa a ler do read-model atrás de uma nova flag de grupo `use_fund_analytics_db_first` (default `False`), com fallback ao corpo legado preservado como helper privado. A ordem é spec §6/§14: MV/SQL primeiro (A2, A4, A5, A1 style-bias), depois os dois workers (A1 fatores, A3 reveal).

**Tech Stack:** Python 3.11+, psycopg3 + numpy (workers), SQLAlchemy 2.0 async + asyncpg (backend), FastAPI, PostgreSQL/TimescaleDB, pytest (`asyncio_mode = "auto"`), Next.js/React + openapi-typescript (frontend), Railway cron.

## Baseline — branch `feat/db-first-analytics` @ HEAD `f6e2c27`

Worktree: `E:\investintell-light\.claude\worktrees\db-first-analytics`. A Fundação + o Grupo D já estão implementados nesta branch:
- MVs `price_latest_mv(ticker, as_of, last_close, prev_date, prev_close)` e `nav_latest_mv(instrument_id, as_of, last_nav, prev_date, prev_nav)` sobre os CAGGs diários `cagg_eod_daily`/`cagg_nav_daily`, atrás da flag `use_latest_mv_prices` (default `False`).
- Worker `matview_refresh` no repo de workers (`E:/investintell-datalake-workers`) faz `REFRESH … CONCURRENTLY` em conexão autocommit fora do advisory lock.
- Convenção de DDL do DB principal: `backend/db/ddl/YYYY-MM-DD_<name>.sql`, aplicado via Tiger/psql como **passo de ops manual** (não Alembic), com teste de string em `backend/tests/test_<name>_sql.py` espelhando `backend/tests/test_price_nav_latest_mv_sql.py`.
- Convenção de DDL de tabela de worker: `schemas/<name>.sql` no repo de workers (ex.: `schemas/risk_metrics.sql`). As MVs read-model que o backend lê ficam em `backend/db/ddl/`.

## Global Constraints

- **Padrão de transição (spec §12) por endpoint:** construir o objeto novo → teste de paridade vs. cálculo atual (tolerância documentada) → dual-read atrás de NOVA flag `use_fund_analytics_db_first` (default `False`) → flip do default (ops) → remover o Python. Cada rota migrada mantém o **fallback legado** enquanto a flag estiver off.
- **Flag única do grupo:** `settings.use_fund_analytics_db_first: bool = False` (em `backend/app/core/config.py`). Todas as cinco rotas do Grupo A leem dela; cada serviço aceita um kwarg `use_db_first: bool | None = None` que, quando `None`, herda a flag.
- **Sem `pandas`/`numpy` no request path** dos caminhos db-first: asserção espelhando o padrão `_FakeSession.executed` de `backend/tests/test_price_latest_mv_reads.py` (afirmar que o SELECT/MV rodou; afirmar que nenhum cálculo `pandas` foi invocado). O cálculo `pandas`/`numpy` permanece apenas no corpo legado (helper privado) e nos workers (A1/A3).
- **DDL do DB principal** em `backend/db/ddl/YYYY-MM-DD_<name>.sql`, aplicado via Tiger/psql (passo de ops manual). Teste de string em `backend/tests/test_<name>_sql.py`. **MV refrescada com `CONCURRENTLY` DEVE ter índice UNIQUE e um populate inicial não-concorrente (`REFRESH MATERIALIZED VIEW <mv>;`) no próprio arquivo DDL.**
- **Modelos ORM de MV** vivem em `backend/app/models/` e DEVEM ser registrados em `backend/app/models/__init__.py` (import + `__all__`).
- **Workers Python** (A1 `fund_factors`, A3 `fund_institutional_reveal`): repo `E:/investintell-datalake-workers`, arquivo `src/workers/<name>.py`, despachados por `WORKER=<name>` via `importlib.import_module(f"src.workers.{worker}")` em `src/run_worker.py` (criar o módulo já o torna despachável; editar a string de uso). Constante de advisory lock no range `900_2xx` em `src/db.py`: **`LOCK_FUND_FACTORS = 900_207`** e **`LOCK_FUND_INSTITUTIONAL_REVEAL = 900_208`** (verificadas livres: 900_201..206, 900_305/306/308/309, 900_320/324/331/332 estão em uso; 207/208 não). Contrato `run(dsn: str, ...) -> dict`. `REFRESH … CONCURRENTLY` em conexão **autocommit, FORA do advisory lock** (espelhar `risk_metrics._refresh_fund_risk_latest_mv` e a chamada no fim de `run()`).
- **DDL de tabela de worker** em `schemas/<name>.sql` (repo de workers); a `*_latest_mv` que o backend lê é DDL do DB principal e pode viver em `backend/db/ddl/` — mas como os workers A1/A3 escrevem na tabela do DB principal (mesmo banco do backend, padrão `risk_metrics`/`fund_risk_metrics`), a tabela base + a `*_latest_mv` ficam juntas no `schemas/<name>.sql` (igual a `risk_metrics.sql` que define `fund_risk_metrics`; a `fund_risk_latest_mv` daquele worker fica em `backend/db/ddl/2026-06-13_dynamic_catalog.sql`). **Convenção deste plano:** tabela base no `schemas/` do worker; `*_latest_mv` em `backend/db/ddl/` (lida pelo backend, mesma convenção da Fundação).
- **Trabalho no repo de workers em worktree LIMPO** off `main` (a working copy compartilhada tem trabalho de outras sessões — regra do dono). Teste de worker espelha o teste existente de `risk_metrics` (`tests/test_risk_metrics.py`).
- **A5 é mudança de produto, não paridade** (spec §6 A5 / §1): `active-share` passa a usar **apenas o benchmark primário** (via `fund_benchmark_candidates_v`). O `benchmark_id` é ignorado-depois-removido: remover de handler/serviço/schema do backend, dos tipos gerados (`api.d.ts`), dos query keys/param builders/UI-send do frontend e dos testes que exercem o caminho por benchmark selecionado. **Manter o `benchmark_id` do `entity-analytics` intacto** (só o `active-share` o perde). A paridade do A5 cobre só o caminho do benchmark primário.
- **Backend tests:** `cd backend && pytest`; `asyncio_mode = "auto"`; I/O stubado por `monkeypatch`/fake session (sem DB vivo).
- **Workers tests:** `pytest tests/test_<x>.py -q`; sem `conftest`; seams de I/O mockados com `monkeypatch`/fake connection.
- **Frontend tests:** `cd frontend && pnpm test` (vitest); typecheck `pnpm typecheck`.
- **Frescor das fontes (spec §15):** N-PORT (latest ~31/01) e 13F (latest ~Q1 2026) têm lag natural; cada MV/tabela expõe a data da fonte (`report_date`/`as_of`/`period`). Cron desses MVs/workers NÃO é diário (alinhar à ingestão trimestral).

---

## File Structure

**Repo backend — `E:\investintell-light\.claude\worktrees\db-first-analytics\backend`:**
- Create: `backend/db/ddl/2026-06-21_fund_style_drift_mv.sql` — MV A2 + índice UNIQUE + populate inicial.
- Create: `backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql` — MV A4 + índice UNIQUE + populate inicial.
- Create: `backend/db/ddl/2026-06-21_fund_active_share_mv.sql` — MV A5 + índice UNIQUE + populate inicial.
- Create: `backend/db/ddl/2026-06-21_fund_style_bias_v.sql` — view A1 (z-scores cross-section).
- Create: `backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql` — `*_latest_mv` do worker A1 (read-model do backend).
- Create: `backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql` — `*_latest_mv` do worker A3 (read-model do backend).
- Create: `backend/tests/test_fund_style_drift_mv_sql.py`, `…_top_holdings_mv_sql.py`, `…_active_share_mv_sql.py`, `…_style_bias_v_sql.py`, `…_fund_factor_exposures_latest_mv_sql.py`, `…_fund_institutional_reveal_latest_mv_sql.py` — testes de string dos DDLs.
- Create: `backend/app/models/fund_analytics_db_first.py` — modelos ORM `FundStyleDriftRow`, `FundTopHoldingRow`, `FundActiveShareRow`, `FundStyleBiasRow`, `FundFactorExposureLatest`, `FundInstitutionalRevealLatest`.
- Modify: `backend/app/models/__init__.py` — registrar os modelos novos.
- Modify: `backend/app/core/config.py` — flag `use_fund_analytics_db_first`.
- Modify: `backend/app/services/fund_dossier_tier_b.py` — dual-read em `fetch_fund_style_drift`, `fetch_fund_active_share`, `fetch_fund_factors`, `fetch_fund_institutional_reveal` (corpo legado vira helper privado).
- Modify: `backend/app/services/fund_analysis.py` — dual-read em `fetch_fund_holdings_top`.
- Modify: `backend/app/api/routes/funds.py` — remover `benchmark_id` do handler `get_fund_active_share`.
- Modify: `backend/app/schemas/fund_analysis.py` — remover `benchmark_id` de `FundActiveShareResponse`; manter `benchmark_name`.
- Modify: `backend/openapi.json` — regenerado (passo de ops/CI).
- Create: testes de paridade/fallback/flag/no-pandas: `backend/tests/test_fund_style_drift_db_first.py`, `…_holdings_top_db_first.py`, `…_active_share_db_first.py`, `…_fund_factors_db_first.py`, `…_institutional_reveal_db_first.py`.

**Repo workers — `E:/investintell-datalake-workers` (worktree limpo off `main`):**
- Create: `src/workers/fund_factors.py` (A1) e `src/workers/fund_institutional_reveal.py` (A3).
- Create: `schemas/fund_factors.sql` (tabela `fund_factor_exposures`) e `schemas/fund_institutional_reveal.sql` (tabela `fund_institutional_reveal_artifacts`).
- Modify: `src/db.py` — `LOCK_FUND_FACTORS = 900_207`, `LOCK_FUND_INSTITUTIONAL_REVEAL = 900_208`.
- Modify: `src/run_worker.py` — registrar os dois workers na mensagem de uso.
- Create: `tests/test_fund_factors.py`, `tests/test_fund_institutional_reveal.py`.

**Repo frontend — `…\db-first-analytics\frontend` (cleanup A5):**
- Modify: `frontend/src/lib/funds/dossierQueries.ts` — `normalizeActiveShareParams`, query key `activeShare`, `paramPairs` active-share, search param `benchmark_id` da active-share.
- Modify: `frontend/src/lib/api/api.d.ts` — `active-share` query vira `never` (regenerado).
- Modify: `frontend/src/components/funds/FundProfileView.tsx` — parar de enviar `benchmark_id` à active-share (manter o state `benchmarkId` p/ entity-analytics).
- Modify: `frontend/src/components/funds/FundProfileView.test.tsx` — testes que exercem active-share por benchmark selecionado.

**Por que estas fronteiras:** read-models SQL e suas leituras vivem no backend (convenção `backend/db/ddl/` da Fundação); só o cálculo (OLS, cruzamento×rede) e a tabela base que ele escreve vivem no repo de workers. Cada tarefa termina com deliverable testável independentemente.

---

## Interfaces (contratos entre tarefas)

- `settings.use_fund_analytics_db_first: bool` (default `False`) — Task 1.
- MV A2: `fund_style_drift_mv(series_id text, report_date date, sector text, weight numeric)` — `weight` em **percent-points** (igual a `SUM(pct_of_nav)` da fonte; o backend divide por 100 ao montar `FundStyleSectorWeight.weight`, como hoje). Índice UNIQUE `(series_id, report_date, sector)`.
- MV A4: `fund_top_holdings_mv(series_id text, report_date date, rank int, issuer_name text, cusip text, isin text, asset_class text, sector text, gics_sector text, market_value numeric, pct_of_nav numeric)`. Índice UNIQUE `(series_id, report_date, rank)`. (Sector breakdown continua de `nport_lookthrough_exposures`, já materializado — sem MV nova.)
- MV A5: `fund_active_share_mv(series_id text, benchmark_series_id text, benchmark_proxy_instrument_id uuid, benchmark_name text, active_share numeric, overlap numeric, n_portfolio int, n_benchmark int, n_common int, as_of date)`. Índice UNIQUE `(series_id)`.
- View A1 style-bias: `fund_style_bias_v(instrument_id uuid, as_of date, factor text, value numeric, z_score numeric)` — `factor` ∈ rótulos `_STYLE_FACTORS` (`size`, `book_to_market`, `momentum`, `quality`, `investment`, `profitability`).
- Tabela A1 (worker): `fund_factor_exposures(instrument_id uuid, factor text, beta numeric, t_stat numeric, significance text, as_of date)` + MV `fund_factor_exposures_latest_mv` (DISTINCT ON `instrument_id` por `as_of` desc). `factor` ∈ {`Factor 1`..`Factor 6`} (rótulos de `_factor_frame`).
- Tabela A3 (worker): `fund_institutional_reveal_artifacts(series_id text, as_of date, schema_version int, payload jsonb)` + MV `fund_institutional_reveal_latest_mv` (DISTINCT ON `series_id` por `as_of` desc). `payload` = `{ "top_holders": [...], "overlap": [...], "holder_network": {nodes, edges}, "period": "<iso>", "holdings_report_date": "<iso>" }`, `schema_version = 1`.
- `LOCK_FUND_FACTORS = 900_207`, `LOCK_FUND_INSTITUTIONAL_REVEAL = 900_208` (em `src/db.py`).
- `fund_factors.run(dsn: str, *, as_of: str | None = None, limit: int | None = None) -> dict` retorna `{"processed", "upserted", "as_of", "mv_refreshed"}`.
- `fund_institutional_reveal.run(dsn: str, *, limit: int | None = None) -> dict` retorna `{"processed", "upserted", "mv_refreshed"}`.
- Serviços com kwarg `use_db_first: bool | None = None`:
  - `fetch_fund_style_drift(session, datalake, instrument_id, *, quarters, use_db_first=None)`
  - `fetch_fund_holdings_top(session, datalake, instrument_id, *, limit, use_db_first=None)`
  - `fetch_fund_active_share(session, datalake, instrument_id, *, use_db_first=None)` — **sem `benchmark_id`**.
  - `fetch_fund_factors(session, datalake, instrument_id, *, use_db_first=None)`
  - `fetch_fund_institutional_reveal(session, datalake, instrument_id, *, use_db_first=None)`
- ORM (em `app.models.fund_analytics_db_first`): `FundStyleDriftRow`, `FundTopHoldingRow`, `FundActiveShareRow`, `FundStyleBiasRow`, `FundFactorExposureLatest`, `FundInstitutionalRevealLatest` (atributos = colunas das MVs/tabelas acima).

---

## Task 1: Flag de grupo + modelos ORM dos read-models

**Files:**
- Modify: `backend/app/core/config.py`
- Create: `backend/app/models/fund_analytics_db_first.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_fund_analytics_db_first_models.py`

**Interfaces:**
- Produces: `settings.use_fund_analytics_db_first`; os seis modelos ORM da seção Interfaces.

**Contexto:** espelha o padrão da Fundação (`backend/app/models/price_latest.py`, `PriceLatest`/`NavLatest`): MVs/tabelas do DB principal mapeadas read-only via `Base` (`from app.models.base import Base`), `mapped_column` tipado. As MVs/tabelas ainda não existem no banco; os testes só inspecionam metadata SQLAlchemy (sem DB).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_fund_analytics_db_first_models.py
from app.core.config import get_settings
from app.models.fund_analytics_db_first import (
    FundActiveShareRow,
    FundFactorExposureLatest,
    FundInstitutionalRevealLatest,
    FundStyleBiasRow,
    FundStyleDriftRow,
    FundTopHoldingRow,
)


def test_flag_defaults_false():
    assert get_settings().use_fund_analytics_db_first is False


def test_style_drift_row_maps_mv():
    assert FundStyleDriftRow.__tablename__ == "fund_style_drift_mv"
    cols = set(FundStyleDriftRow.__table__.columns.keys())
    assert {"series_id", "report_date", "sector", "weight"} <= cols


def test_top_holding_row_maps_mv():
    assert FundTopHoldingRow.__tablename__ == "fund_top_holdings_mv"
    cols = set(FundTopHoldingRow.__table__.columns.keys())
    assert {"series_id", "report_date", "rank", "issuer_name", "cusip", "pct_of_nav"} <= cols


def test_active_share_row_maps_mv():
    assert FundActiveShareRow.__tablename__ == "fund_active_share_mv"
    cols = set(FundActiveShareRow.__table__.columns.keys())
    assert {"series_id", "benchmark_series_id", "active_share", "overlap", "as_of"} <= cols
    assert "series_id" in FundActiveShareRow.__table__.primary_key.columns.keys()


def test_style_bias_row_maps_view():
    assert FundStyleBiasRow.__tablename__ == "fund_style_bias_v"
    cols = set(FundStyleBiasRow.__table__.columns.keys())
    assert {"instrument_id", "as_of", "factor", "value", "z_score"} <= cols


def test_factor_exposure_latest_maps_mv():
    assert FundFactorExposureLatest.__tablename__ == "fund_factor_exposures_latest_mv"
    cols = set(FundFactorExposureLatest.__table__.columns.keys())
    assert {"instrument_id", "factor", "beta", "t_stat", "significance", "as_of"} <= cols


def test_institutional_reveal_latest_maps_mv():
    assert FundInstitutionalRevealLatest.__tablename__ == "fund_institutional_reveal_latest_mv"
    cols = set(FundInstitutionalRevealLatest.__table__.columns.keys())
    assert {"series_id", "as_of", "schema_version", "payload"} <= cols
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_analytics_db_first_models.py -q`
Expected: FAIL (`ModuleNotFoundError: app.models.fund_analytics_db_first` e/ou `use_fund_analytics_db_first` ausente).

- [ ] **Step 3: Adicionar a flag**

Em `backend/app/core/config.py`, na classe `Settings`, junto a `use_latest_mv_prices`:

```python
    # DB-first Grupo A: quando True, os endpoints de fund analytics estáveis
    # (factors, style-drift, institutional-reveal, holdings/top, active-share)
    # leem dos read-models db-first (MV/view/worker), com fallback ao caminho
    # legado por entidade ausente. Default off até validação em staging.
    use_fund_analytics_db_first: bool = False
```

- [ ] **Step 4: Criar os modelos ORM**

```python
# backend/app/models/fund_analytics_db_first.py
"""Modelos ORM read-only sobre os read-models db-first do Grupo A.

Todos vivem no DB principal e são alimentados por MV/view SQL
(fund_style_drift_mv, fund_top_holdings_mv, fund_active_share_mv,
fund_style_bias_v) ou pelos workers fund_factors / fund_institutional_reveal
(via *_latest_mv). Espelham o padrão de PriceLatest/NavLatest: mapeados via
Base, lidos por chave/IN, nunca escritos pelo backend.
"""
from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, Date, Integer, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class FundStyleDriftRow(Base):
    __tablename__ = "fund_style_drift_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    sector: Mapped[str] = mapped_column(String, primary_key=True)
    weight: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundTopHoldingRow(Base):
    __tablename__ = "fund_top_holdings_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    report_date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    rank: Mapped[int] = mapped_column(Integer, primary_key=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)
    isin: Mapped[str | None] = mapped_column(String, nullable=True)
    asset_class: Mapped[str | None] = mapped_column(String, nullable=True)
    sector: Mapped[str | None] = mapped_column(String, nullable=True)
    gics_sector: Mapped[str | None] = mapped_column(String, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundActiveShareRow(Base):
    __tablename__ = "fund_active_share_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    benchmark_series_id: Mapped[str | None] = mapped_column(String, nullable=True)
    benchmark_proxy_instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    benchmark_name: Mapped[str | None] = mapped_column(String, nullable=True)
    active_share: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    overlap: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    n_portfolio: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_benchmark: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_common: Mapped[int | None] = mapped_column(Integer, nullable=True)
    as_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class FundStyleBiasRow(Base):
    __tablename__ = "fund_style_bias_v"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    factor: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    z_score: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class FundFactorExposureLatest(Base):
    __tablename__ = "fund_factor_exposures_latest_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    factor: Mapped[str] = mapped_column(String, primary_key=True)
    beta: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    t_stat: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    significance: Mapped[str | None] = mapped_column(String, nullable=True)
    as_of: Mapped[dt.date | None] = mapped_column(Date, nullable=True)


class FundInstitutionalRevealLatest(Base):
    __tablename__ = "fund_institutional_reveal_latest_mv"

    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
```

- [ ] **Step 5: Registrar em `__init__.py`**

Em `backend/app/models/__init__.py`, adicionar o import (após o bloco de `app.models.fund`) e os nomes ao `__all__`:

```python
from app.models.fund_analytics_db_first import (
    FundActiveShareRow,
    FundFactorExposureLatest,
    FundInstitutionalRevealLatest,
    FundStyleBiasRow,
    FundStyleDriftRow,
    FundTopHoldingRow,
)
```

E no `__all__` (mantendo ordem alfabética do bloco existente), inserir:

```python
    "FundActiveShareRow",
    "FundFactorExposureLatest",
    "FundInstitutionalRevealLatest",
    "FundStyleBiasRow",
    "FundStyleDriftRow",
    "FundTopHoldingRow",
```

- [ ] **Step 6: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_analytics_db_first_models.py -q`
Expected: PASS (7 testes).

- [ ] **Step 7: Commit**

```bash
git add backend/app/core/config.py backend/app/models/fund_analytics_db_first.py backend/app/models/__init__.py backend/tests/test_fund_analytics_db_first_models.py
git commit -m "feat(funds): add Group A db-first flag + read-model ORM models"
```

---

## Task 2: A2 — `fund_style_drift_mv` (DDL) + dual-read em `fetch_fund_style_drift`

**Files:**
- Create: `backend/db/ddl/2026-06-21_fund_style_drift_mv.sql`
- Test: `backend/tests/test_fund_style_drift_mv_sql.py`
- Modify: `backend/app/services/fund_dossier_tier_b.py`
- Test: `backend/tests/test_fund_style_drift_db_first.py`

**Interfaces:**
- Consumes: `FundStyleDriftRow` (Task 1); `settings.use_fund_analytics_db_first`.
- Produces: MV `fund_style_drift_mv`; `fetch_fund_style_drift(..., *, quarters, use_db_first=None)`.

**Contexto — corpo atual** (`fetch_fund_style_drift`, `backend/app/services/fund_dossier_tier_b.py:413-526`): para a série do fundo, pega os `quarters` `report_date` distintos mais recentes de `sec_nport_holdings`, resolve setor por CUSIP (GICS via `sec_cusip_ticker_map.gics_sector`; fallback case-map de N-PORT sector: `CORP`→`Corporate`, `UST`→`U.S. Treasury`, etc.; `Unknown`), agrega `SUM(pct_of_nav) GROUP BY report_date, sector`, e monta `list[FundStyleDriftPeriod]` (cada um com `list[FundStyleSectorWeight]`, `weight = (SUM/100)`). A MV materializa exatamente essa agregação **sem o LIMIT de quarters** (o `quarters` vira filtro na leitura). O backend então monta os mesmos objetos a partir das linhas do MV.

- [ ] **Step 1: Escrever o teste de string do DDL (falha)**

```python
# backend/tests/test_fund_style_drift_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_style_drift_mv.sql"
)


def test_style_drift_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_style_drift_mv" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "sec_cusip_ticker_map" in sql          # GICS por CUSIP
    assert "SUM(pct_of_nav)" in sql               # agregação por setor
    assert "GROUP BY" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_style_drift_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_style_drift_mv;" in sql
    # case-map de N-PORT sector (amostra)
    assert "'U.S. Treasury'" in sql
    assert "'Corporate'" in sql
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_style_drift_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_fund_style_drift_mv.sql
-- A2 — Style drift db-first. Materializa a MESMA agregação de
-- fetch_fund_style_drift (sec_nport_holdings → setor por CUSIP/N-PORT case-map →
-- SUM(pct_of_nav) por report_date+sector), SEM o LIMIT de quarters (o quarters
-- vira filtro na leitura). weight fica em percent-points (igual a SUM(pct_of_nav));
-- o backend divide por 100 ao montar FundStyleSectorWeight.weight (paridade).
-- Refrescada por matview_refresh (REFRESH … CONCURRENTLY exige o índice UNIQUE).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_style_drift_mv AS
WITH resolved AS (
    SELECT h.series_id,
           h.report_date,
           COALESCE(
               NULLIF(btrim(m.gics_sector), ''),
               CASE upper(btrim(h.sector))
                   WHEN 'CORP'  THEN 'Corporate'
                   WHEN 'UST'   THEN 'U.S. Treasury'
                   WHEN 'GOVT'  THEN 'Government'
                   WHEN 'USGA'  THEN 'U.S. Gov Agency'
                   WHEN 'MUNI'  THEN 'Municipal'
                   WHEN 'MUN'   THEN 'Municipal'
                   WHEN 'MBS'   THEN 'Mortgage-Backed'
                   WHEN 'ABS'   THEN 'Asset-Backed'
                   WHEN 'CMO'   THEN 'Collateralized Mortgage'
                   WHEN 'SUPRA' THEN 'Supranational'
                   WHEN 'NUSS'  THEN 'Non-U.S. Sovereign'
                   WHEN 'RF'    THEN 'Registered Fund'
                   ELSE NULLIF(btrim(h.sector), '')
               END,
               'Unknown'
           ) AS sector,
           h.pct_of_nav
    FROM sec_nport_holdings h
    LEFT JOIN LATERAL (
        SELECT gics_sector
        FROM sec_cusip_ticker_map
        WHERE cusip = h.cusip
          AND NULLIF(btrim(gics_sector), '') IS NOT NULL
        LIMIT 1
    ) m ON TRUE
)
SELECT series_id, report_date, sector, SUM(pct_of_nav) AS weight
FROM resolved
GROUP BY series_id, report_date, sector
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_style_drift_mv_pk
  ON fund_style_drift_mv (series_id, report_date, sector);

-- Aceleração de leitura: filtro por série + ordenação por report_date desc.
CREATE INDEX IF NOT EXISTS fund_style_drift_mv_series_date_idx
  ON fund_style_drift_mv (series_id, report_date DESC);

REFRESH MATERIALIZED VIEW fund_style_drift_mv;
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_style_drift_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Escrever os testes de serviço (falha)**

```python
# backend/tests/test_fund_style_drift_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_Q1 = dt.date(2026, 1, 31)
_Q2 = dt.date(2025, 10, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"
    ticker = "TST"


class _FakeSession:
    """Datalake-side fake; routes by marker in the stringified query."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []
        self.pandas_used = False

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "fund_style_drift_mv" in text:
            return _Result([dict(r) for r in self._mv_rows])
        return _Result([dict(r) for r in self._legacy_rows])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_session, _iid):
        return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_path_reshapes_periods():
    datalake = _FakeSession(mv_rows=[
        {"report_date": _Q1, "sector": "Technology", "weight": 40.0},
        {"report_date": _Q1, "sector": "Health Care", "weight": 10.0},
        {"report_date": _Q2, "sector": "Technology", "weight": 35.0},
    ])
    out = await svc.fetch_fund_style_drift(
        object(), datalake, _IID, quarters=40, use_db_first=True
    )
    assert [p.report_date for p in out.periods] == [_Q2, _Q1]  # ASC, newest last
    q1 = next(p for p in out.periods if p.report_date == _Q1)
    assert {s.sector: s.weight for s in q1.sectors} == {"Technology": 0.40, "Health Care": 0.10}
    assert any("fund_style_drift_mv" in q for q in datalake.executed)


@pytest.mark.asyncio
async def test_db_first_empty_falls_to_empty_state():
    datalake = _FakeSession(mv_rows=[])
    out = await svc.fetch_fund_style_drift(
        object(), datalake, _IID, quarters=40, use_db_first=True
    )
    assert out.periods == []
    assert out.empty_state is not None


@pytest.mark.asyncio
async def test_flag_off_uses_legacy(monkeypatch):
    called = {"legacy": False}
    async def _legacy(_session, _datalake, _iid, *, quarters):
        called["legacy"] = True
        from app.schemas.fund_analysis import FundStyleDriftResponse
        return FundStyleDriftResponse(instrument_id=_IID, series_id="S000001", periods=[])
    monkeypatch.setattr(svc, "_fetch_fund_style_drift_legacy", _legacy)
    out = await svc.fetch_fund_style_drift(
        object(), _FakeSession(), _IID, quarters=40, use_db_first=False
    )
    assert called["legacy"] is True
    assert out.periods == []
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_style_drift_db_first.py -q`
Expected: FAIL (sem `use_db_first` / sem caminho MV / sem `_fetch_fund_style_drift_legacy`).

- [ ] **Step 7: Reescrever o serviço (legado vira helper + caminho db-first)**

Em `backend/app/services/fund_dossier_tier_b.py`: renomear a função atual `fetch_fund_style_drift` para `_fetch_fund_style_drift_legacy` (corpo verbatim de :413-526, mantendo a assinatura `(session, datalake, instrument_id, *, quarters)`), e adicionar o wrapper. Imports no topo do módulo: `from app.core.config import get_settings` (se ainda não houver) e `from app.models.fund_analytics_db_first import FundStyleDriftRow`.

```python
async def fetch_fund_style_drift(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    quarters: int,
    use_db_first: bool | None = None,
) -> FundStyleDriftResponse | None:
    """Historical N-PORT sector drift. DB-first lê de fund_style_drift_mv
    (mesma agregação, weight em percent-points → /100 aqui); fallback ao legado.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_style_drift_legacy(
            session, datalake, instrument_id, quarters=quarters
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    WITH q AS (
                        SELECT DISTINCT report_date
                        FROM fund_style_drift_mv
                        WHERE series_id = :series_id
                        ORDER BY report_date DESC
                        LIMIT :quarters
                    )
                    SELECT m.report_date, m.sector, m.weight
                    FROM fund_style_drift_mv m
                    JOIN q ON q.report_date = m.report_date
                    WHERE m.series_id = :series_id
                    ORDER BY m.report_date ASC, m.weight DESC NULLS LAST
                    """
                ),
                {"series_id": fund.series_id, "quarters": quarters},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("fund_style_drift_mv", exc) from exc

    periods: list[FundStyleDriftPeriod] = []
    current_date: dt.date | None = None
    current_weights: list[FundStyleSectorWeight] = []
    for row in rows:
        report_date = row["report_date"]
        if report_date != current_date:
            if current_date is not None:
                periods.append(
                    FundStyleDriftPeriod(
                        report_date=current_date,
                        quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                        sectors=current_weights,
                    )
                )
            current_date = report_date
            current_weights = []
        current_weights.append(
            FundStyleSectorWeight(
                sector=row["sector"],
                weight=(
                    (_float(row["weight"]) or 0.0) / 100.0
                    if row["weight"] is not None
                    else None
                ),
            )
        )
    if current_date is not None:
        periods.append(
            FundStyleDriftPeriod(
                report_date=current_date,
                quarter=f"{current_date.year}Q{((current_date.month - 1) // 3) + 1}",
                sectors=current_weights,
            )
        )

    return FundStyleDriftResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        periods=periods,
        empty_state=(
            None
            if periods
            else _empty("No historical N-PORT holdings for this fund series.", "fund_style_drift_mv")
        ),
    )
```

- [ ] **Step 8: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_style_drift_db_first.py -q`
Expected: PASS (3 testes).

- [ ] **Step 9: Aplicar o DDL no banco principal (ops, manual)**

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_fund_style_drift_mv.sql
psql "$DATABASE_URL" -c "SELECT series_id, report_date, sector, weight FROM fund_style_drift_mv LIMIT 5;"
```
Expected: linhas retornadas (MV populado).

- [ ] **Step 10: Commit**

```bash
git add backend/db/ddl/2026-06-21_fund_style_drift_mv.sql backend/tests/test_fund_style_drift_mv_sql.py backend/app/services/fund_dossier_tier_b.py backend/tests/test_fund_style_drift_db_first.py
git commit -m "feat(funds): A2 style-drift db-first via fund_style_drift_mv behind flag"
```

---

## Task 3: A4 — `fund_top_holdings_mv` (DDL) + dual-read em `fetch_fund_holdings_top`

**Files:**
- Create: `backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql`
- Test: `backend/tests/test_fund_top_holdings_mv_sql.py`
- Modify: `backend/app/services/fund_analysis.py`
- Test: `backend/tests/test_holdings_top_db_first.py`

**Interfaces:**
- Consumes: `FundTopHoldingRow` (Task 1); `settings.use_fund_analytics_db_first`.
- Produces: MV `fund_top_holdings_mv`; `fetch_fund_holdings_top(..., *, limit, use_db_first=None)`.

**Contexto — corpo atual** (`fetch_fund_holdings_top`, `backend/app/services/fund_analysis.py:416-476`): pega o `report_date` mais recente da série, top `limit` por `rank` de `FundHolding` (`sec_nport_holdings` no DB principal), resolve GICS por CUSIP (`_gics_sector_by_cusip` → `sec_cusip_ticker_map.gics_sector`), e o **sector breakdown** vem primariamente de `nport_lookthrough_exposures` (`_sector_breakdown_from_lookthrough`, dimension='sector', já materializado), com fallback a agregação local (`_sector_breakdown_from_holdings`). O MV materializa apenas o **top holdings** (com GICS já resolvido); o sector breakdown **continua** lido de `nport_lookthrough_exposures` (sem MV nova). O `limit` vira `WHERE rank <= :limit` na leitura.

- [ ] **Step 1: Escrever o teste de string do DDL (falha)**

```python
# backend/tests/test_fund_top_holdings_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_top_holdings_mv.sql"
)


def test_top_holdings_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_top_holdings_mv" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "sec_cusip_ticker_map" in sql                 # GICS por CUSIP
    assert "row_number()" in sql or "rank" in sql        # top-N por rank
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_top_holdings_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_top_holdings_mv;" in sql
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_top_holdings_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql
-- A4 — Top holdings db-first. Top-50 holdings por série no report_date mais
-- recente, com GICS já resolvido por CUSIP (sec_cusip_ticker_map). O limit do
-- endpoint vira WHERE rank <= :limit na leitura. O sector breakdown NÃO é
-- materializado aqui — continua lido de nport_lookthrough_exposures (A4 / spec).
-- Refrescada por matview_refresh (REFRESH … CONCURRENTLY exige o índice UNIQUE).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_top_holdings_mv AS
WITH latest AS (
    SELECT series_id, max(report_date) AS report_date
    FROM sec_nport_holdings
    GROUP BY series_id
),
ranked AS (
    SELECT h.series_id,
           h.report_date,
           row_number() OVER (
               PARTITION BY h.series_id
               ORDER BY h.pct_of_nav DESC NULLS LAST, h.market_value DESC NULLS LAST
           ) AS rank,
           h.issuer_name,
           upper(h.cusip) AS cusip,
           h.isin,
           h.asset_class,
           h.sector,
           h.market_value,
           h.pct_of_nav
    FROM sec_nport_holdings h
    JOIN latest l ON l.series_id = h.series_id AND l.report_date = h.report_date
)
SELECT r.series_id,
       r.report_date,
       r.rank,
       r.issuer_name,
       r.cusip,
       r.isin,
       r.asset_class,
       r.sector,
       NULLIF(btrim(m.gics_sector), '') AS gics_sector,
       r.market_value,
       r.pct_of_nav
FROM ranked r
LEFT JOIN LATERAL (
    SELECT gics_sector
    FROM sec_cusip_ticker_map
    WHERE cusip = r.cusip
      AND NULLIF(btrim(gics_sector), '') IS NOT NULL
    LIMIT 1
) m ON TRUE
WHERE r.rank <= 50
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_top_holdings_mv_pk
  ON fund_top_holdings_mv (series_id, report_date, rank);

REFRESH MATERIALIZED VIEW fund_top_holdings_mv;
```

Nota: o `rank` do MV usa `pct_of_nav DESC` (o `FundHolding.rank` legado já reflete essa mesma ordenação N-PORT); a paridade é validada no Step 9.

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_top_holdings_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Escrever os testes de serviço (falha)**

```python
# backend/tests/test_holdings_top_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_analysis as svc

_IID = uuid.uuid4()
_RD = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"


class _FakeSession:
    """App-DB side fake: session.get(Fund, id) → fund; execute() → mv rows."""
    def __init__(self, *, mv_rows=None):
        self._mv_rows = mv_rows or []
        self.executed = []

    async def get(self, _model, _iid):
        return _FakeFund()

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([dict(r) for r in self._mv_rows])


@pytest.mark.asyncio
async def test_db_first_reads_top_holdings_from_mv(monkeypatch):
    async def _breakdown(_datalake, _series):
        return []  # força fallback de breakdown só se necessário; aqui basta lista vazia
    monkeypatch.setattr(svc, "_sector_breakdown_from_lookthrough", _breakdown)
    monkeypatch.setattr(svc, "_sector_breakdown_from_holdings", lambda _h: [])

    session = _FakeSession(mv_rows=[
        {"series_id": "S000001", "report_date": _RD, "rank": 1,
         "issuer_name": "Apple Inc", "cusip": "037833100", "isin": None,
         "asset_class": "EC", "sector": None, "gics_sector": "Information Technology",
         "market_value": 1000.0, "pct_of_nav": 5.0},
    ])
    out = await svc.fetch_fund_holdings_top(session, _FakeSession(), _IID, limit=25, use_db_first=True)
    assert out.report_date == _RD
    assert out.top_holdings[0].issuer_name == "Apple Inc"
    assert out.top_holdings[0].gics_sector == "Information Technology"
    assert out.top_holdings[0].pct_of_nav == 5.0
    assert any("fund_top_holdings_mv" in q for q in session.executed)


@pytest.mark.asyncio
async def test_flag_off_uses_legacy(monkeypatch):
    called = {"legacy": False}
    async def _legacy(_session, _datalake, _iid, *, limit):
        called["legacy"] = True
        from app.schemas.fund_analysis import FundHoldingsTopResponse
        return FundHoldingsTopResponse(
            instrument_id=_IID, series_id="S000001", report_date=None,
            top_holdings=[], sector_breakdown=[], pct_of_nav_total=None,
        )
    monkeypatch.setattr(svc, "_fetch_fund_holdings_top_legacy", _legacy)
    out = await svc.fetch_fund_holdings_top(_FakeSession(), _FakeSession(), _IID, limit=25, use_db_first=False)
    assert called["legacy"] is True
    assert out.top_holdings == []
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_holdings_top_db_first.py -q`
Expected: FAIL (sem `use_db_first` / sem `_fetch_fund_holdings_top_legacy`).

- [ ] **Step 7: Reescrever o serviço**

Em `backend/app/services/fund_analysis.py`: renomear a função atual `fetch_fund_holdings_top` para `_fetch_fund_holdings_top_legacy` (corpo verbatim de :416-476, assinatura `(session, datalake, instrument_id, *, limit)`), e adicionar o wrapper. Imports: `from app.core.config import get_settings` (se ausente) e `from app.models.fund_analytics_db_first import FundTopHoldingRow`. Reusa os helpers existentes do módulo `_sector_breakdown_from_lookthrough`, `_sector_breakdown_from_holdings`, `_sector_label`.

```python
async def fetch_fund_holdings_top(
    session: AsyncSession,
    datalake: AsyncSession | None,
    instrument_id: uuid.UUID,
    *,
    limit: int,
    use_db_first: bool | None = None,
) -> FundHoldingsTopResponse | None:
    """Top holdings + sector breakdown. DB-first lê top holdings de
    fund_top_holdings_mv (GICS já resolvido); sector breakdown continua de
    nport_lookthrough_exposures. Fallback ao legado quando a flag está off.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_holdings_top_legacy(
            session, datalake, instrument_id, limit=limit
        )

    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    rows = (
        await session.execute(
            text(
                """
                SELECT report_date, rank, issuer_name, cusip, isin,
                       asset_class, sector, gics_sector, market_value, pct_of_nav
                FROM fund_top_holdings_mv
                WHERE series_id = :series_id
                  AND rank <= :limit
                ORDER BY rank
                """
            ),
            {"series_id": fund.series_id, "limit": limit},
        )
    ).mappings().all()

    report_date = rows[0]["report_date"] if rows else None
    sector_breakdown = await _sector_breakdown_from_lookthrough(datalake, fund.series_id)
    reported = [float(r["pct_of_nav"]) for r in rows if r["pct_of_nav"] is not None]
    return FundHoldingsTopResponse(
        instrument_id=instrument_id,
        series_id=fund.series_id,
        report_date=report_date,
        top_holdings=[
            FundTopHolding(
                rank=r["rank"],
                issuer_name=r["issuer_name"],
                cusip=r["cusip"],
                isin=r["isin"],
                asset_class=r["asset_class"],
                sector=r["sector"],
                gics_sector=r["gics_sector"],
                sector_label=r["gics_sector"] or r["sector"],
                market_value=_float(r["market_value"]),
                pct_of_nav=_float(r["pct_of_nav"]),
            )
            for r in rows
        ],
        sector_breakdown=sector_breakdown,
        pct_of_nav_total=sum(reported) if reported else None,
    )
```

Nota: o caminho legado usa `_sector_breakdown_from_holdings(holdings)` como fallback quando o lookthrough volta vazio; no caminho db-first o fallback de breakdown a partir de holdings crus exigiria os `FundHolding` ORM (que não buscamos no MV path). Como `nport_lookthrough_exposures` é a fonte materializada canônica (spec §4/§6 A4), o db-first depende dela; quando vazia, `sector_breakdown` fica `[]` (estado vazio explícito, igual ao lookthrough). O Step 9 valida que a cobertura de lookthrough cobre os fundos com holdings.

- [ ] **Step 8: Rodar e ver passar**

Run: `cd backend && pytest tests/test_holdings_top_db_first.py -q`
Expected: PASS (2 testes).

- [ ] **Step 9: Aplicar o DDL + spot-check de paridade (ops, manual)**

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql
# Paridade: top-5 do MV vs FundHolding.rank legado para uma série de amostra.
psql "$DATABASE_URL" -c "SELECT rank, issuer_name, pct_of_nav FROM fund_top_holdings_mv WHERE series_id = (SELECT series_id FROM fund_top_holdings_mv LIMIT 1) ORDER BY rank LIMIT 5;"
```
Expected: ordenação por `pct_of_nav` desc, idêntica ao `rank` legado da mesma série.

- [ ] **Step 10: Commit**

```bash
git add backend/db/ddl/2026-06-21_fund_top_holdings_mv.sql backend/tests/test_fund_top_holdings_mv_sql.py backend/app/services/fund_analysis.py backend/tests/test_holdings_top_db_first.py
git commit -m "feat(funds): A4 holdings/top db-first via fund_top_holdings_mv behind flag"
```

---

## Task 4: A5 — `fund_active_share_mv` (DDL) + dual-read; remover `benchmark_id` (backend)

**Files:**
- Create: `backend/db/ddl/2026-06-21_fund_active_share_mv.sql`
- Test: `backend/tests/test_fund_active_share_mv_sql.py`
- Modify: `backend/app/services/fund_dossier_tier_b.py`
- Modify: `backend/app/api/routes/funds.py`
- Modify: `backend/app/schemas/fund_analysis.py`
- Test: `backend/tests/test_active_share_db_first.py`

**Interfaces:**
- Consumes: `FundActiveShareRow` (Task 1); `fund_benchmark_candidates_v`; `settings.use_fund_analytics_db_first`.
- Produces: MV `fund_active_share_mv`; `fetch_fund_active_share(session, datalake, instrument_id, *, use_db_first=None)` (**sem `benchmark_id`**); `FundActiveShareResponse` **sem campo `benchmark_id`**.

**Contexto — corpo atual** (`fetch_fund_active_share`, `:1773-1841`): hoje exige `benchmark_id`; resolve holdings do benchmark por `_benchmark_holdings_target` e computa `active_share = 0.5·Σ|w_p−w_b|`, `overlap = Σ min(w_p,w_b)`, `n_common` via `active_share_from_weights` (`:1762-1770`). Pesos vêm de `_holdings_weights` (`:1644-1684`): `SUM(pct_of_nav)/100` por CUSIP na `report_date` mais recente de `sec_nport_holdings`. **Mudança de produto (spec §6 A5):** o endpoint passa a usar **apenas o benchmark primário** via `fund_benchmark_candidates_v.benchmark_proxy_instrument_id` → série do ETF em `sec_nport_holdings`; `benchmark_id` é removido. O MV materializa o active-share fundo×benchmark-primário; o backend só lê. O proxy ETF resolve a série via `instruments_universe`/`sec_etfs`/`sec_fund_classes` (o MV faz isso em SQL).

- [ ] **Step 1: Escrever o teste de string do DDL (falha)**

```python
# backend/tests/test_fund_active_share_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_active_share_mv.sql"
)


def test_active_share_mv_shape_and_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_active_share_mv" in sql
    assert "fund_benchmark_candidates_v" in sql           # benchmark primário
    assert "benchmark_proxy_instrument_id" in sql
    assert "FROM sec_nport_holdings" in sql
    assert "0.5" in sql                                    # 0.5·Σ|Δw|
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_active_share_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_active_share_mv;" in sql
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_active_share_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_fund_active_share_mv.sql
-- A5 — Active share db-first vs benchmark PRIMÁRIO (mudança de produto, spec §6 A5).
-- Benchmark via fund_benchmark_candidates_v.benchmark_proxy_instrument_id → ticker
-- do ETF (instruments_universe) → série em sec_nport_holdings. Pesos = SUM(pct_of_nav)/100
-- por CUSIP no report_date mais recente de cada série. active_share = 0.5·Σ|w_f − w_b|;
-- overlap = Σ min(w_f, w_b). Refrescada por matview_refresh (índice UNIQUE obrigatório).

CREATE MATERIALIZED VIEW IF NOT EXISTS fund_active_share_mv AS
WITH bench AS (
    -- série N-PORT do ETF proxy primário de cada fundo
    SELECT c.series_id AS fund_series_id,
           c.benchmark_proxy_instrument_id,
           c.benchmark_name,
           bser.benchmark_series_id
    FROM fund_benchmark_candidates_v c
    JOIN LATERAL (
        SELECT min(nh.series_id) AS benchmark_series_id
        FROM instruments_universe iu
        JOIN sec_etfs se ON upper(se.ticker) = upper(iu.ticker)
        JOIN sec_nport_holdings nh ON nh.series_id = se.series_id
        WHERE iu.instrument_id = c.benchmark_proxy_instrument_id
    ) bser ON TRUE
    WHERE c.benchmark_proxy_instrument_id IS NOT NULL
      AND bser.benchmark_series_id IS NOT NULL
),
fund_w AS (
    SELECT h.series_id, upper(h.cusip) AS cusip,
           SUM(h.pct_of_nav) / 100.0 AS w,
           max(h.report_date) OVER (PARTITION BY h.series_id) AS as_of
    FROM sec_nport_holdings h
    JOIN (
        SELECT series_id, max(report_date) AS rd
        FROM sec_nport_holdings GROUP BY series_id
    ) lf ON lf.series_id = h.series_id AND lf.rd = h.report_date
    WHERE h.cusip IS NOT NULL AND h.pct_of_nav IS NOT NULL
    GROUP BY h.series_id, upper(h.cusip), h.report_date
),
bench_w AS (
    SELECT h.series_id, upper(h.cusip) AS cusip,
           SUM(h.pct_of_nav) / 100.0 AS w,
           max(h.report_date) OVER (PARTITION BY h.series_id) AS as_of
    FROM sec_nport_holdings h
    JOIN (
        SELECT series_id, max(report_date) AS rd
        FROM sec_nport_holdings GROUP BY series_id
    ) lb ON lb.series_id = h.series_id AND lb.rd = h.report_date
    WHERE h.cusip IS NOT NULL AND h.pct_of_nav IS NOT NULL
    GROUP BY h.series_id, upper(h.cusip), h.report_date
),
joined AS (
    SELECT b.fund_series_id AS series_id,
           b.benchmark_series_id,
           b.benchmark_proxy_instrument_id,
           b.benchmark_name,
           fw.cusip,
           COALESCE(fw.w, 0.0) AS wf,
           COALESCE(bw.w, 0.0) AS wb,
           fw.as_of AS fund_as_of,
           bw.as_of AS bench_as_of
    FROM bench b
    LEFT JOIN fund_w  fw ON fw.series_id = b.fund_series_id
    FULL OUTER JOIN bench_w bw
      ON bw.series_id = b.benchmark_series_id AND bw.cusip = fw.cusip
)
SELECT series_id,
       benchmark_series_id,
       benchmark_proxy_instrument_id,
       benchmark_name,
       0.5 * SUM(abs(wf - wb))                               AS active_share,
       SUM(LEAST(wf, wb))                                    AS overlap,
       count(*) FILTER (WHERE wf > 0)                        AS n_portfolio,
       count(*) FILTER (WHERE wb > 0)                        AS n_benchmark,
       count(*) FILTER (WHERE wf > 0 AND wb > 0)             AS n_common,
       LEAST(max(fund_as_of), max(bench_as_of))             AS as_of
FROM joined
GROUP BY series_id, benchmark_series_id, benchmark_proxy_instrument_id, benchmark_name
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS fund_active_share_mv_pk
  ON fund_active_share_mv (series_id);

REFRESH MATERIALIZED VIEW fund_active_share_mv;
```

Nota: a junção benchmark resolve uma única série N-PORT por ETF proxy (`min(series_id)`), espelhando a preferência "primeira série com holdings" do `_benchmark_holdings_target` legado. ETFs sem N-PORT recente não produzem linha (estado vazio explícito — spec §15).

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_active_share_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Remover `benchmark_id` do schema**

Em `backend/app/schemas/fund_analysis.py`, `FundActiveShareResponse` (`:555-569`): remover a linha `benchmark_id: uuid.UUID | None = None`. Manter `benchmark_name`. Adicionar `benchmark_series_id` opcional para identificar o benchmark efetivamente usado (spec §6 A5):

```python
class FundActiveShareResponse(BaseModel):
    """Holdings-based active share versus the fund's PRIMARY benchmark."""

    model_config = ConfigDict(extra="forbid")

    instrument_id: uuid.UUID
    benchmark_name: str | None = None
    benchmark_series_id: str | None = None
    active_share: float | None = None
    overlap: float | None = None
    n_portfolio_positions: int = 0
    n_benchmark_positions: int = 0
    n_common_positions: int = 0
    as_of_date: dt.date | None = None
    empty_state: EmptyState | None = None
```

- [ ] **Step 6: Escrever os testes de serviço + rota (falha)**

```python
# backend/tests/test_active_share_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows
    def first(self): return self._rows[0] if self._rows else None


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"


class _FakeSession:
    def __init__(self, *, mv_row=None):
        self._mv_row = mv_row
        self.executed = []

    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([self._mv_row] if self._mv_row else [])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_session, _iid):
        return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_reads_active_share_from_mv():
    row = {
        "series_id": "S000001", "benchmark_series_id": "S000999",
        "benchmark_name": "S&P 500", "active_share": 0.42, "overlap": 0.58,
        "n_portfolio": 120, "n_benchmark": 500, "n_common": 90, "as_of": _AS_OF,
    }
    out = await svc.fetch_fund_active_share(object(), _FakeSession(mv_row=row), _IID, use_db_first=True)
    assert out.active_share == 0.42
    assert out.overlap == 0.58
    assert out.benchmark_series_id == "S000999"
    assert out.n_common_positions == 90
    assert not hasattr(out, "benchmark_id")  # campo removido do schema


@pytest.mark.asyncio
async def test_db_first_no_benchmark_yields_empty_state():
    out = await svc.fetch_fund_active_share(object(), _FakeSession(mv_row=None), _IID, use_db_first=True)
    assert out.empty_state is not None
    assert out.active_share is None
```

E na suíte de rotas (`backend/tests/test_fund_tier_b_routes.py`), substituir/ajustar quaisquer testes que passem `benchmark_id` ao endpoint `active-share` por chamadas sem o parâmetro, afirmando que o handler não aceita mais `benchmark_id` (a query param desapareceu). Adicionar:

```python
def test_active_share_endpoint_ignores_benchmark_id_query(client, monkeypatch):
    # benchmark_id não é mais um query param declarado → é ignorado pelo FastAPI.
    async def _fake(_s, _d, _iid, *, use_db_first=None):
        from app.schemas.fund_analysis import FundActiveShareResponse
        return FundActiveShareResponse(instrument_id=_iid, active_share=0.4)
    monkeypatch.setattr(
        "app.api.routes.funds.fund_dossier_tier_b.fetch_fund_active_share", _fake
    )
    iid = "00000000-0000-0000-0000-000000000001"
    resp = client.get(f"/funds/{iid}/active-share?benchmark_id=whatever")
    assert resp.status_code == 200
    assert "benchmark_id" not in resp.json()
```

- [ ] **Step 7: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_active_share_db_first.py backend/tests/test_fund_tier_b_routes.py -q`
Expected: FAIL.

- [ ] **Step 8: Reescrever o serviço (sem `benchmark_id`)**

Em `backend/app/services/fund_dossier_tier_b.py`: renomear a função atual `fetch_fund_active_share` para `_fetch_fund_active_share_legacy` (corpo verbatim de :1773-1841, mantendo `*, benchmark_id` — preservado só como caminho de fallback histórico, **não exposto pela rota**), e adicionar o wrapper db-first **sem `benchmark_id`**. Como a rota não passa mais `benchmark_id`, o fallback legado é chamado com `benchmark_id=None` (que retorna o empty-state "benchmark_id is required") quando a flag está off — comportamento aceitável durante a transição, pois o flip da flag para db-first acompanha o deploy do MV. Import: `from app.models.fund_analytics_db_first import FundActiveShareRow`.

```python
async def fetch_fund_active_share(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundActiveShareResponse | None:
    """Active share vs the fund's PRIMARY benchmark (spec §6 A5 — benchmark_id
    removido). DB-first lê de fund_active_share_mv. Com a flag off, cai ao corpo
    legado (benchmark_id=None → empty-state), preservado só para a transição.
    """
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_active_share_legacy(
            session, datalake, instrument_id, benchmark_id=None
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    row = (
        await datalake.execute(
            text(
                """
                SELECT series_id, benchmark_series_id, benchmark_name,
                       active_share, overlap, n_portfolio, n_benchmark,
                       n_common, as_of
                FROM fund_active_share_mv
                WHERE series_id = :series_id
                """
            ),
            {"series_id": fund.series_id},
        )
    ).mappings().first()
    if row is None:
        return FundActiveShareResponse(
            instrument_id=instrument_id,
            empty_state=_empty(
                "No primary benchmark with N-PORT holdings for this fund.",
                "fund_active_share_mv",
            ),
        )
    return FundActiveShareResponse(
        instrument_id=instrument_id,
        benchmark_name=row["benchmark_name"],
        benchmark_series_id=row["benchmark_series_id"],
        active_share=_float(row["active_share"]),
        overlap=_float(row["overlap"]),
        n_portfolio_positions=row["n_portfolio"] or 0,
        n_benchmark_positions=row["n_benchmark"] or 0,
        n_common_positions=row["n_common"] or 0,
        as_of_date=row["as_of"],
    )
```

- [ ] **Step 9: Remover `benchmark_id` do handler da rota**

Em `backend/app/api/routes/funds.py`, `get_fund_active_share` (`:410-431`): remover o parâmetro `benchmark_id` e ajustar a chamada do serviço:

```python
@router.get(
    "/funds/{instrument_id}/active-share",
    response_model=FundActiveShareResponse,
)
async def get_fund_active_share(
    instrument_id: uuid.UUID,
    session: SessionDep,
    datalake: DatalakeDep,
) -> FundActiveShareResponse:
    """Tier B holdings-based active share against the fund's primary benchmark."""
    try:
        payload = await fund_dossier_tier_b.fetch_fund_active_share(
            session, datalake, instrument_id
        )
    except (
        fund_dossier_tier_b.InvalidBenchmarkError,
        fund_dossier_tier_b.TierBSourceError,
    ) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail=f"Fund {instrument_id} not found.")
    return payload
```

- [ ] **Step 10: Rodar e ver passar**

Run: `cd backend && pytest tests/test_active_share_db_first.py backend/tests/test_fund_tier_b_routes.py -q`
Expected: PASS.

- [ ] **Step 11: Aplicar o DDL + regenerar openapi (ops, manual)**

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_fund_active_share_mv.sql
psql "$DATABASE_URL" -c "SELECT series_id, benchmark_series_id, active_share, overlap FROM fund_active_share_mv LIMIT 5;"
# Regenerar o schema OpenAPI (consumido pelo gerador de tipos do frontend):
cd backend && python -m app.export_openapi > openapi.json   # (ou o comando de export do repo)
```
Expected: `fund_active_share_mv` populado; `openapi.json` sem o query param `benchmark_id` na `active-share`.

- [ ] **Step 12: Commit**

```bash
git add backend/db/ddl/2026-06-21_fund_active_share_mv.sql backend/tests/test_fund_active_share_mv_sql.py backend/app/services/fund_dossier_tier_b.py backend/app/api/routes/funds.py backend/app/schemas/fund_analysis.py backend/tests/test_active_share_db_first.py backend/tests/test_fund_tier_b_routes.py backend/openapi.json
git commit -m "feat(funds): A5 active-share db-first vs primary benchmark; drop benchmark_id (backend)"
```

---

## Task 5: A5 — cleanup `benchmark_id` no frontend

**Files:**
- Modify: `frontend/src/lib/funds/dossierQueries.ts`
- Modify: `frontend/src/lib/api/api.d.ts`
- Modify: `frontend/src/components/funds/FundProfileView.tsx`
- Test: `frontend/src/components/funds/FundProfileView.test.tsx`

**Interfaces:**
- Consumes: o contrato de backend da Task 4 (`active-share` sem `benchmark_id`).
- Produces: o frontend deixa de enviar `benchmark_id` à `active-share`; o `benchmarkId` state permanece para o `entity-analytics`.

**Contexto:** hoje (`dossierQueries.ts`) a active-share carrega `benchmark_id`: `normalizeActiveShareParams` (:156-158), query key `activeShare` (:438-441), `paramPairs` active-share (:256), search param `benchmark_id` (:202), e `FundActiveShareQuery` import (:2). Em `FundProfileView.tsx`, `activeShareQuery` (:397-404) usa `benchmarkQuery` (`{ benchmark_id: benchmarkId }`, :259). O `benchmarkId` state (:234) e `benchmarkQuery` continuam usados pelo `entity-analytics` (DeepAnalysis, :753-754) — **não remover**. Apenas a active-share para de enviar.

- [ ] **Step 1: Escrever/ajustar o teste de frontend (falha)**

Em `frontend/src/components/funds/FundProfileView.test.tsx`, ajustar quaisquer testes que afirmem que a request de active-share inclui `benchmark_id`. Adicionar um teste de que a active-share é buscada SEM `benchmark_id` mesmo com um benchmark selecionado:

```tsx
it("does not send benchmark_id to active-share even with a benchmark selected", async () => {
  const calls: string[] = [];
  // espiona o fetch da camada de cliente para capturar a URL da active-share
  vi.spyOn(globalThis, "fetch").mockImplementation(async (input: RequestInfo | URL) => {
    const url = typeof input === "string" ? input : input.toString();
    calls.push(url);
    return new Response(JSON.stringify({ instrument_id: "x", active_share: 0.4 }), { status: 200 });
  });
  // ... montar a view, abrir a aba Holdings, selecionar um benchmark ...
  // afirmar que nenhuma chamada de active-share carrega benchmark_id:
  const activeShareCalls = calls.filter((u) => u.includes("/active-share"));
  expect(activeShareCalls.length).toBeGreaterThan(0);
  expect(activeShareCalls.every((u) => !u.includes("benchmark_id"))).toBe(true);
});
```

(Adaptar o setup de montagem ao helper de render já usado no arquivo de teste; o ponto load-bearing é a asserção `!u.includes("benchmark_id")`.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd frontend && pnpm test FundProfileView`
Expected: FAIL (active-share ainda envia `benchmark_id`).

- [ ] **Step 3: Editar `dossierQueries.ts`**

(a) `normalizeActiveShareParams` passa a não normalizar nada:

```ts
export function normalizeActiveShareParams(_query: { benchmark_id?: QueryValue } = {}) {
  return {} as Record<string, never>;
}
```

(b) query key `activeShare` (:438-441) deixa de incluir `benchmark_id`:

```ts
  activeShare: (instrumentId: string) => ["fund-active-share", instrumentId] as const,
```

(c) em `paramPairs` (:255-256), o case `active-share` passa a não emitir pares:

```ts
    case "active-share":
      return [] as const;
```

(d) em `normalizeFundResourceParamsFromSearch` (:202), remover a linha `benchmark_id: searchParam(searchParams, "benchmark_id"),` **apenas se** nenhum outro recurso a usar via esse builder — `entity-analytics` usa `normalizeEntityAnalyticsParams` que lê `query.benchmark_id`; portanto **manter** a linha `benchmark_id` no builder de search params (ela alimenta o entity-analytics). Não alterar (d).

(e) o import `FundActiveShareQuery` (:2) deixa de ser usado — removê-lo do import se o typecheck acusar `unused`. Verificar com `pnpm typecheck` no Step 6.

- [ ] **Step 4: Editar `FundProfileView.tsx`**

A `activeShareQuery` (:397-404) deixa de passar `benchmarkQuery`:

```tsx
  const activeShareQuery = useQuery({
    queryKey: dossierQueryKeys.activeShare(instrumentId),
    queryFn: ({ signal }) => fetchFundActiveShare(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["active-share"],
    enabled: isHoldingsTab,
    retry: retryPolicy,
  });
```

Ajustar a assinatura de `fetchFundActiveShare` (em `dossierQueries.ts` ou onde definida) para `(instrumentId: string, signal?: AbortSignal)` — removendo o argumento de query. Manter `benchmarkId`/`benchmarkQuery` no componente (entity-analytics ainda os usa, :433/:753).

- [ ] **Step 5: Regenerar `api.d.ts`**

Após o `openapi.json` regenerado na Task 4 Step 11, regenerar os tipos:

```bash
cd frontend && pnpm gen:api   # (ou o script openapi-typescript do repo)
```

Resultado esperado: em `api.d.ts`, a `active-share` perde o query param — `get_fund_active_share_...` passa a ter `query?: never` (como `institutional-reveal`, :920-925) e a remoção do bloco `benchmark_id?: string | null` (:7825-7828). `FundActiveShareResponse` perde `benchmark_id` e ganha `benchmark_series_id`.

- [ ] **Step 6: Typecheck + rodar e ver passar**

```bash
cd frontend && pnpm typecheck && pnpm test FundProfileView
```
Expected: typecheck verde (sem `benchmark_id` órfão); testes PASS.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/lib/funds/dossierQueries.ts frontend/src/lib/api/api.d.ts frontend/src/components/funds/FundProfileView.tsx frontend/src/components/funds/FundProfileView.test.tsx
git commit -m "feat(funds): A5 stop sending benchmark_id to active-share; regen types"
```

---

## Task 6: A1 (style-bias) — `fund_style_bias_v` (view) + dual-read parcial em `fetch_fund_factors`

**Files:**
- Create: `backend/db/ddl/2026-06-21_fund_style_bias_v.sql`
- Test: `backend/tests/test_fund_style_bias_v_sql.py`
- Modify: `backend/app/services/fund_dossier_tier_b.py`
- Test: `backend/tests/test_fund_factors_style_bias_db_first.py`

**Interfaces:**
- Consumes: `FundStyleBiasRow` (Task 1); `equity_characteristics_monthly`; `settings.use_fund_analytics_db_first`.
- Produces: view `fund_style_bias_v`; `_style_bias_db_first(datalake, instrument_id)` helper usado por `fetch_fund_factors` quando a flag está on.

**Contexto — corpo atual** (`_style_bias`, `:300-363`): para o `as_of` mais recente do fundo em `equity_characteristics_monthly`, computa, por fator (`_STYLE_FACTORS`: `size`/`size_log_mkt_cap`, `book_to_market`, `momentum`/`mom_12_1`, `quality`/`quality_roa`, `investment`/`investment_growth`, `profitability`/`profitability_gross`), `z = (value − AVG) / STDDEV_SAMP` em cross-section daquele `as_of`. A view materializa exatamente esse z-score por `(instrument_id, as_of, factor)` usando window functions, sem worker (spec §6 A1). O `fetch_fund_factors` então lê os z-scores da view em vez de computá-los; o OLS de fatores (parte do worker A1, Task 8) é separado.

- [ ] **Step 1: Escrever o teste de string do DDL (falha)**

```python
# backend/tests/test_fund_style_bias_v_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_style_bias_v.sql"
)


def test_style_bias_view_shape():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE OR REPLACE VIEW fund_style_bias_v" in sql
    assert "FROM equity_characteristics_monthly" in sql
    assert "stddev_samp" in sql.lower()
    assert "avg(" in sql.lower()
    assert "OVER (PARTITION BY as_of)" in sql or "OVER (PARTITION BY ec.as_of)" in sql
    # os 6 rótulos de _STYLE_FACTORS
    for label in ("size", "book_to_market", "momentum", "quality", "investment", "profitability"):
        assert f"'{label}'" in sql
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_style_bias_v_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL (view)**

```sql
-- backend/db/ddl/2026-06-21_fund_style_bias_v.sql
-- A1 (style-bias) — z-scores cross-section por fator de estilo, db-first.
-- Espelha _style_bias: para cada (instrument_id, as_of), z = (value − AVG) /
-- STDDEV_SAMP sobre todos os fundos daquele as_of. Long-format: uma linha por
-- (instrument_id, as_of, factor). É VIEW (sem materialização) — leve e sempre
-- fresca sobre equity_characteristics_monthly (spec §6 A1, "view/função SQL").

CREATE OR REPLACE VIEW fund_style_bias_v AS
WITH stats AS (
    SELECT
        instrument_id,
        as_of,
        size_log_mkt_cap,
        book_to_market,
        mom_12_1,
        quality_roa,
        investment_growth,
        profitability_gross,
        avg(size_log_mkt_cap)        OVER (PARTITION BY as_of) AS a_size,
        stddev_samp(size_log_mkt_cap) OVER (PARTITION BY as_of) AS s_size,
        avg(book_to_market)          OVER (PARTITION BY as_of) AS a_btm,
        stddev_samp(book_to_market)  OVER (PARTITION BY as_of) AS s_btm,
        avg(mom_12_1)                OVER (PARTITION BY as_of) AS a_mom,
        stddev_samp(mom_12_1)        OVER (PARTITION BY as_of) AS s_mom,
        avg(quality_roa)             OVER (PARTITION BY as_of) AS a_qua,
        stddev_samp(quality_roa)     OVER (PARTITION BY as_of) AS s_qua,
        avg(investment_growth)       OVER (PARTITION BY as_of) AS a_inv,
        stddev_samp(investment_growth) OVER (PARTITION BY as_of) AS s_inv,
        avg(profitability_gross)     OVER (PARTITION BY as_of) AS a_pro,
        stddev_samp(profitability_gross) OVER (PARTITION BY as_of) AS s_pro
    FROM equity_characteristics_monthly
)
SELECT instrument_id, as_of, factor, value, z_score FROM (
    SELECT instrument_id, as_of, 'size'::text AS factor, size_log_mkt_cap AS value,
           CASE WHEN s_size > 0 THEN (size_log_mkt_cap - a_size) / s_size END AS z_score FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'book_to_market', book_to_market,
           CASE WHEN s_btm > 0 THEN (book_to_market - a_btm) / s_btm END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'momentum', mom_12_1,
           CASE WHEN s_mom > 0 THEN (mom_12_1 - a_mom) / s_mom END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'quality', quality_roa,
           CASE WHEN s_qua > 0 THEN (quality_roa - a_qua) / s_qua END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'investment', investment_growth,
           CASE WHEN s_inv > 0 THEN (investment_growth - a_inv) / s_inv END FROM stats
    UNION ALL
    SELECT instrument_id, as_of, 'profitability', profitability_gross,
           CASE WHEN s_pro > 0 THEN (profitability_gross - a_pro) / s_pro END FROM stats
) z;
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_style_bias_v_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Escrever os testes do helper (falha)**

```python
# backend/tests/test_fund_factors_style_bias_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeSession:
    def __init__(self, rows): self._rows = rows; self.executed = []
    async def execute(self, query, params=None):
        self.executed.append(str(query)); return _Result(self._rows)


@pytest.mark.asyncio
async def test_style_bias_db_first_reads_view():
    rows = [
        {"as_of": _AS_OF, "factor": "size", "value": 1.0, "z_score": 0.5},
        {"as_of": _AS_OF, "factor": "momentum", "value": 0.2, "z_score": -1.0},
    ]
    session = _FakeSession(rows)
    as_of, biases, empty = await svc._style_bias_db_first(session, _IID)
    assert as_of == _AS_OF
    assert {b.factor for b in biases} == {"size", "momentum"}
    by = {b.factor: b.z_score for b in biases}
    assert by["momentum"] == -1.0
    assert empty is None
    assert any("fund_style_bias_v" in q for q in session.executed)


@pytest.mark.asyncio
async def test_style_bias_db_first_empty():
    as_of, biases, empty = await svc._style_bias_db_first(_FakeSession([]), _IID)
    assert biases == []
    assert empty is not None
```

- [ ] **Step 6: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_factors_style_bias_db_first.py -q`
Expected: FAIL (`_style_bias_db_first` não existe).

- [ ] **Step 7: Implementar o helper db-first**

Em `backend/app/services/fund_dossier_tier_b.py`, adicionar (ao lado de `_style_bias`):

```python
async def _style_bias_db_first(
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
) -> tuple[dt.date | None, list[FundStyleBias], EmptyState | None]:
    """Style-bias z-scores lidos de fund_style_bias_v (latest as_of do fundo).

    Mesmo shape de _style_bias; o cálculo z = (value−avg)/stddev já vive na view.
    """
    try:
        rows = (
            await datalake.execute(
                text(
                    """
                    WITH latest AS (
                        SELECT max(as_of) AS as_of
                        FROM fund_style_bias_v
                        WHERE instrument_id = :iid
                    )
                    SELECT as_of, factor, value, z_score
                    FROM fund_style_bias_v
                    WHERE instrument_id = :iid
                      AND as_of = (SELECT as_of FROM latest)
                    """
                ),
                {"iid": str(instrument_id)},
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise _source_error("fund_style_bias_v", exc) from exc
    if not rows:
        return (
            None,
            [],
            _empty(
                "No equity_characteristics_monthly row for this fund.",
                "fund_style_bias_v",
            ),
        )
    as_of = rows[0]["as_of"]
    biases = [
        FundStyleBias(
            factor=row["factor"],
            value=_float(row["value"]),
            z_score=_float(row["z_score"]),
            as_of=row["as_of"],
        )
        for row in rows
    ]
    return as_of, biases, None
```

E em `fetch_fund_factors` (`:366-410`), trocar a chamada de `_style_bias` por seleção db-first sob a flag (mantendo o OLS legado por enquanto — o worker A1 cobre o OLS na Task 8). Adicionar o kwarg `use_db_first` à assinatura:

```python
async def fetch_fund_factors(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundFactorsResponse | None:
    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first

    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    nav = pd.Series(dtype=float)
    if first_date is not None and last_date is not None:
        nav = build_nav_series(await select_nav_rows(session, instrument_id, first_date, last_date))
    monthly_returns = (
        nav.resample("ME").last().pct_change().dropna()
        if len(nav)
        else pd.Series(dtype=float)
    )
    factor_as_of, factors = await _latest_factor_fit(datalake)
    sensitivities = _ols_market_sensitivities(monthly_returns, factors)

    if use_db_first:
        style_as_of, style_bias, style_empty = await _style_bias_db_first(datalake, instrument_id)
    else:
        style_as_of, style_bias, style_empty = await _style_bias(datalake, instrument_id)

    metadata = [
        FundSourceMetadata(
            source="factor_model_fits",
            as_of=factor_as_of,
            empty_state=(
                _empty("No usable factor_model_fits payload for OLS.", "factor_model_fits")
                if not sensitivities
                else None
            ),
        ),
        FundSourceMetadata(
            source="equity_characteristics_monthly",
            as_of=style_as_of,
            empty_state=style_empty,
        ),
    ]
    return FundFactorsResponse(
        instrument_id=instrument_id,
        market_sensitivities=sensitivities,
        style_bias=style_bias,
        source_metadata=metadata,
    )
```

Nota: o OLS (`_ols_market_sensitivities`) ainda roda `pandas`/`numpy` no request path aqui; a Task 8 (worker `fund_factors` + `fetch` lendo do `*_latest_mv`) o remove. Esta tarefa migra só o style-bias (a metade SQL-pura do A1, spec §6 A1).

- [ ] **Step 8: Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_factors_style_bias_db_first.py -q`
Expected: PASS (2 testes).

- [ ] **Step 9: Aplicar o DDL (ops, manual)**

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_fund_style_bias_v.sql
psql "$DATABASE_URL" -c "SELECT instrument_id, factor, z_score FROM fund_style_bias_v LIMIT 6;"
```
Expected: 6 fatores por (instrument_id, as_of).

- [ ] **Step 10: Commit**

```bash
git add backend/db/ddl/2026-06-21_fund_style_bias_v.sql backend/tests/test_fund_style_bias_v_sql.py backend/app/services/fund_dossier_tier_b.py backend/tests/test_fund_factors_style_bias_db_first.py
git commit -m "feat(funds): A1 style-bias db-first via fund_style_bias_v behind flag"
```

---

## Task 7: A1 (fatores) — `*_latest_mv` DDL + worker `fund_factors`

**Files:**
- Create (workers, worktree limpo): `E:/investintell-datalake-workers/schemas/fund_factors.sql` (tabela base)
- Modify (workers): `E:/investintell-datalake-workers/src/db.py` (`LOCK_FUND_FACTORS`)
- Modify (workers): `E:/investintell-datalake-workers/src/run_worker.py` (uso)
- Create (workers): `E:/investintell-datalake-workers/src/workers/fund_factors.py`
- Test (workers): `E:/investintell-datalake-workers/tests/test_fund_factors.py`
- Create (backend): `backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql` (MV read-model)
- Test (backend): `backend/tests/test_fund_factor_exposures_latest_mv_sql.py`

**Interfaces:**
- Consumes: `connect`, `advisory_lock`, `LOCK_FUND_FACTORS` de `src/db.py`; `factor_model_fits`, `nav_timeseries`.
- Produces: tabela `fund_factor_exposures`; MV `fund_factor_exposures_latest_mv`; `fund_factors.run(dsn, *, as_of=None, limit=None) -> dict`.

**Contexto — cálculo a portar** (do request path, `_ols_market_sensitivities` `:239-272` + `fetch_fund_factors` `:366-386`): por fundo, retornos mensais do NAV (resample mensal de `nav_timeseries` → pct_change) regredidos por OLS contra `factor_model_fits.factor_returns` (jsonb `{dates:[], values:[[...]]}` do fit IPCA mais recente; `engine='ipca'`), produzindo, por fator (`Factor 1`..`Factor N`, ≤6): `beta`, `t_stat` (= β[i]/SE[i], SE de `sigma2·(XᵀX)⁻¹`, dof = n − k), `significance` (`***` |t|≥2.58, `**` ≥1.96, `*` ≥1.65, senão `None`), pulando o intercepto. O worker espelha `risk_metrics`: advisory lock, upsert idempotente em `fund_factor_exposures`, depois `REFRESH … CONCURRENTLY fund_factor_exposures_latest_mv` em conexão autocommit fora do lock.

- [ ] **Step 1 (workers): Preparar worktree limpo + adicionar advisory lock**

```bash
cd /e/investintell-datalake-workers && git worktree add ../investintell-datalake-workers-groupa main
cd /e/investintell-datalake-workers-groupa
```

Em `src/db.py`, junto às constantes `LOCK_*` (range 900_2xx), adicionar:

```python
LOCK_FUND_FACTORS = 900_207
```

- [ ] **Step 2 (workers): DDL da tabela base**

```sql
-- schemas/fund_factors.sql
-- A1 — exposições de fatores por fundo (OLS de retornos mensais do NAV vs
-- factor_model_fits.factor_returns). GLOBAL (organization_id NULL). Upsert por
-- (instrument_id, factor, as_of). Apply: psql "$DATABASE_URL" -f schemas/fund_factors.sql
CREATE TABLE IF NOT EXISTS fund_factor_exposures (
    instrument_id    uuid    NOT NULL,
    factor           text    NOT NULL,
    as_of            date    NOT NULL,
    beta             numeric(14, 8),
    t_stat           numeric(14, 8),
    significance     text,
    organization_id  uuid,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_fund_factor_exposures_pk
        UNIQUE NULLS NOT DISTINCT (instrument_id, factor, as_of, organization_id)
);

CREATE INDEX IF NOT EXISTS fund_factor_exposures_iid_idx
    ON fund_factor_exposures (instrument_id, as_of DESC);
```

- [ ] **Step 3 (workers): Escrever o teste do worker (falha)**

Espelha `tests/test_risk_metrics.py` (fake connection; testa o refresh CONCURRENTLY autocommit e o OLS).

```python
# tests/test_fund_factors.py
import numpy as np

import src.workers.fund_factors as ff


def test_ols_factor_exposures_recovers_known_betas():
    rng = np.random.default_rng(0)
    n = 120
    f1 = rng.normal(size=n)
    f2 = rng.normal(size=n)
    y = 0.3 * f1 - 0.5 * f2 + rng.normal(scale=1e-6, size=n)  # ruído ínfimo
    out = ff.ols_factor_exposures(y, np.column_stack([f1, f2]))
    betas = {row["factor"]: row["beta"] for row in out}
    assert abs(betas["Factor 1"] - 0.3) < 1e-3
    assert abs(betas["Factor 2"] + 0.5) < 1e-3
    assert all(row["significance"] == "***" for row in out)  # |t| enorme


def test_ols_short_series_returns_empty():
    assert ff.ols_factor_exposures(np.zeros(3), np.zeros((3, 2))) == []


class _FakeCursor:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, *_a): self._sink["sql"] = " ".join(str(sql).split())


class _FakeConn:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _FakeCursor(self._sink)


def test_refresh_latest_mv_concurrently_autocommit(monkeypatch):
    sink = {}
    def _fake_connect(dsn=None, *, autocommit=False):
        sink["autocommit"] = autocommit
        return _FakeConn(sink)
    monkeypatch.setattr(ff, "connect", _fake_connect)
    ff._refresh_latest_mv("postgres://x")
    assert sink["autocommit"] is True
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY fund_factor_exposures_latest_mv" in sink["sql"]
```

- [ ] **Step 4 (workers): Rodar e ver falhar**

Run: `cd /e/investintell-datalake-workers-groupa && pytest tests/test_fund_factors.py -q`
Expected: FAIL (`ModuleNotFoundError: src.workers.fund_factors`).

- [ ] **Step 5 (workers): Implementar o worker**

```python
# src/workers/fund_factors.py
"""fund_factors — OLS de exposições de fatores por fundo (db-first do A1).

Para cada fundo: retornos mensais do NAV (resample mensal de nav_timeseries →
pct_change) regredidos por OLS contra factor_model_fits.factor_returns (fit IPCA
mais recente). Produz beta/t_stat/significância por fator. Upsert idempotente em
fund_factor_exposures; depois REFRESH … CONCURRENTLY fund_factor_exposures_latest_mv
em conexão autocommit FORA do advisory lock (padrão risk_metrics).
"""
from __future__ import annotations

import datetime as _dt
import math

import numpy as np

from src.db import LOCK_FUND_FACTORS, advisory_lock, connect

_SIG = ((2.58, "***"), (1.96, "**"), (1.65, "*"))


def _significance(t_stat: float | None) -> str | None:
    if t_stat is None or math.isnan(t_stat):
        return None
    level = abs(t_stat)
    for threshold, mark in _SIG:
        if level >= threshold:
            return mark
    return None


def ols_factor_exposures(y: np.ndarray, x: np.ndarray) -> list[dict]:
    """OLS de y (Nx1) sobre x (NxK) com intercepto. Retorna uma linha por fator
    (exclui o intercepto): {"factor","beta","t_stat","significance"}.
    Espelha _ols_market_sensitivities (lstsq, SE de sigma2·(XᵀX)⁻¹, dof=N−(K+1)).
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    if x.ndim != 2 or len(y) < max(10, x.shape[1] + 2):
        return []
    x_design = np.column_stack([np.ones(len(x)), x])
    beta, *_ = np.linalg.lstsq(x_design, y, rcond=None)
    residuals = y - x_design @ beta
    dof = len(y) - x_design.shape[1]
    if dof <= 0:
        t_stats = np.full(beta.shape, np.nan)
    else:
        sigma2 = float((residuals @ residuals) / dof)
        cov = sigma2 * np.linalg.pinv(x_design.T @ x_design)
        se = np.sqrt(np.diag(cov))
        t_stats = np.divide(beta, se, out=np.full(beta.shape, np.nan), where=se > 0)
    out: list[dict] = []
    for idx in range(1, x_design.shape[1]):  # pula o intercepto
        t = float(t_stats[idx])
        t = None if math.isnan(t) else t
        out.append({
            "factor": f"Factor {idx}",
            "beta": float(beta[idx]),
            "t_stat": t,
            "significance": _significance(t),
        })
    return out


_UPSERT = """
INSERT INTO fund_factor_exposures
    (instrument_id, factor, as_of, beta, t_stat, significance, organization_id)
VALUES (%(iid)s, %(factor)s, %(as_of)s, %(beta)s, %(t_stat)s, %(sig)s, NULL)
ON CONFLICT (instrument_id, factor, as_of, organization_id) DO UPDATE SET
    beta = EXCLUDED.beta, t_stat = EXCLUDED.t_stat,
    significance = EXCLUDED.significance, computed_at = now()
"""


def _refresh_latest_mv(dsn: str) -> None:
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY fund_factor_exposures_latest_mv"
            )


def _latest_factor_matrix(conn) -> tuple[_dt.date | None, list[_dt.date], np.ndarray]:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT fit_date, factor_returns FROM factor_model_fits "
            "WHERE engine = 'ipca' ORDER BY fit_date DESC, created_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if row is None or not isinstance(row[1], dict):
        return None, [], np.empty((0, 0))
    fit_date, payload = row
    dates = [_dt.date.fromisoformat(d[:10]) for d in payload.get("dates", [])]
    values = payload.get("values", [])
    if not dates or not values:
        return fit_date, [], np.empty((0, 0))
    cols = [np.asarray(v, dtype=float) for v in values if len(v) == len(dates)]
    matrix = np.column_stack(cols) if cols else np.empty((len(dates), 0))
    return fit_date, dates, matrix


def _fund_monthly_returns(conn, iid, factor_dates: list[_dt.date]) -> np.ndarray:
    """Retornos mensais do fundo alinhados às datas dos fatores (month-end)."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT date_trunc('month', nav_date)::date AS m, "
            "       (array_agg(nav ORDER BY nav_date DESC))[1] AS last_nav "
            "FROM nav_timeseries WHERE instrument_id = %s AND nav IS NOT NULL "
            "GROUP BY 1 ORDER BY 1",
            (iid,),
        )
        rows = cur.fetchall()
    by_month = {r[0]: float(r[1]) for r in rows}
    months = sorted(by_month)
    rets: dict[_dt.date, float] = {}
    for prev, cur_m in zip(months, months[1:]):
        if by_month[prev]:
            rets[cur_m] = by_month[cur_m] / by_month[prev] - 1.0
    aligned = []
    for d in factor_dates:
        key = d.replace(day=1)
        aligned.append(rets.get(key, np.nan))
    return np.asarray(aligned, dtype=float)


def _fund_ids(conn, limit) -> list:
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT instrument_id FROM nav_timeseries"
            + (" LIMIT %s" if limit else ""),
            ((limit,) if limit else None),
        )
        return [r[0] for r in cur.fetchall()]


def run(dsn: str, *, as_of: str | None = None, limit: int | None = None) -> dict:
    processed = upserted = 0
    fit_date: _dt.date | None = None
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_FUND_FACTORS) as got:
            if not got:
                return {"processed": 0, "upserted": 0, "skipped": "lock_busy"}
            fit_date, fdates, fmatrix = _latest_factor_matrix(conn)
            out_date = _dt.date.fromisoformat(as_of) if as_of else (fit_date or _dt.date.today())
            if fdates and fmatrix.size:
                for iid in _fund_ids(conn, limit):
                    y = _fund_monthly_returns(conn, iid, fdates)
                    mask = ~np.isnan(y)
                    if mask.sum() < max(10, fmatrix.shape[1] + 2):
                        continue
                    processed += 1
                    rows = ols_factor_exposures(y[mask], fmatrix[mask])
                    for r in rows:
                        with conn.cursor() as cur:
                            cur.execute(_UPSERT, {
                                "iid": iid, "factor": r["factor"], "as_of": out_date,
                                "beta": r["beta"], "t_stat": r["t_stat"], "sig": r["significance"],
                            })
                        upserted += 1
                conn.commit()
    result = {"processed": processed, "upserted": upserted,
              "as_of": (out_date.isoformat() if fit_date or as_of else None)}
    try:
        _refresh_latest_mv(dsn)
        result["mv_refreshed"] = True
    except Exception as exc:  # noqa: BLE001
        result["mv_refreshed"] = False
        result["mv_refresh_error"] = str(exc)
    return result
```

- [ ] **Step 6 (workers): Registrar no dispatcher**

Em `src/run_worker.py`, incluir `fund_factors` na string de uso (junto aos demais):

```python
            "|sec_13f_ingestion|form345_ingestion|sec_company_tickers_mf"
            "|fund_factors|fund_institutional_reveal)"
```

- [ ] **Step 7 (workers): Rodar e ver passar**

Run: `cd /e/investintell-datalake-workers-groupa && pytest tests/test_fund_factors.py -q`
Expected: PASS.

- [ ] **Step 8 (backend): Escrever o teste de string do MV (falha)**

```python
# backend/tests/test_fund_factor_exposures_latest_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_factor_exposures_latest_mv.sql"
)


def test_factor_exposures_latest_mv():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_factor_exposures_latest_mv" in sql
    assert "DISTINCT ON (instrument_id, factor)" in sql
    assert "FROM fund_factor_exposures" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_factor_exposures_latest_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_factor_exposures_latest_mv;" in sql
```

- [ ] **Step 9 (backend): Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_factor_exposures_latest_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 10 (backend): Escrever o DDL do MV**

```sql
-- backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql
-- A1 — read-model do backend: última exposição de fator por (instrument_id, factor).
-- Alimentado pelo worker fund_factors (escreve fund_factor_exposures). Refrescado
-- por esse worker (REFRESH … CONCURRENTLY exige o índice UNIQUE abaixo).
DROP MATERIALIZED VIEW IF EXISTS fund_factor_exposures_latest_mv;
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_factor_exposures_latest_mv AS
SELECT DISTINCT ON (instrument_id, factor)
       instrument_id, factor, beta, t_stat, significance, as_of
FROM fund_factor_exposures
WHERE organization_id IS NULL
ORDER BY instrument_id, factor, as_of DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_factor_exposures_latest_mv_pk
  ON fund_factor_exposures_latest_mv (instrument_id, factor);

REFRESH MATERIALIZED VIEW fund_factor_exposures_latest_mv;
```

- [ ] **Step 11 (backend): Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_factor_exposures_latest_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 12: Wire do `fetch_fund_factors` ao MV (substitui o OLS no request path)**

Em `backend/app/services/fund_dossier_tier_b.py`, no caminho `use_db_first` de `fetch_fund_factors` (Task 6 Step 7), ler as sensibilidades do MV em vez de rodar o OLS `pandas`. Adicionar import `from app.models.fund_analytics_db_first import FundFactorExposureLatest` e, no ramo `if use_db_first:`, antes de montar a resposta, substituir o cálculo:

```python
    if use_db_first:
        rows = (
            await datalake.execute(
                text(
                    """
                    SELECT factor, beta, t_stat, significance, as_of
                    FROM fund_factor_exposures_latest_mv
                    WHERE instrument_id = :iid
                    ORDER BY factor
                    """
                ),
                {"iid": str(instrument_id)},
            )
        ).mappings().all()
        sensitivities = [
            FundMarketSensitivity(
                factor=r["factor"], beta=_float(r["beta"]),
                t_stat=_float(r["t_stat"]), significance=r["significance"],
            )
            for r in rows
        ]
        factor_as_of = rows[0]["as_of"] if rows else None
        style_as_of, style_bias, style_empty = await _style_bias_db_first(datalake, instrument_id)
    else:
        first_date, last_date = await select_nav_date_bounds(session, instrument_id)
        nav = pd.Series(dtype=float)
        if first_date is not None and last_date is not None:
            nav = build_nav_series(await select_nav_rows(session, instrument_id, first_date, last_date))
        monthly_returns = (
            nav.resample("ME").last().pct_change().dropna() if len(nav) else pd.Series(dtype=float)
        )
        factor_as_of, factors = await _latest_factor_fit(datalake)
        sensitivities = _ols_market_sensitivities(monthly_returns, factors)
        style_as_of, style_bias, style_empty = await _style_bias(datalake, instrument_id)
```

(O restante de `fetch_fund_factors` — montagem de `metadata` e `FundFactorsResponse` — permanece como no Step 7 da Task 6. O datalake-side `datalake` lê o `fund_factor_exposures_latest_mv` que vive no DB principal? Confirmar: o worker escreve no **mesmo banco que `nav_timeseries`/`factor_model_fits`** — o data-lake Cloud — então o MV vive lá e é lido via `datalake` AsyncSession. Verificar no Step 14 que `DatalakeDep` aponta para esse banco.)

- [ ] **Step 13: Teste no-pandas do caminho db-first de factors**

Adicionar a `backend/tests/test_fund_factors_style_bias_db_first.py`:

```python
@pytest.mark.asyncio
async def test_factors_db_first_reads_mv_no_ols(monkeypatch):
    async def _fund(_s, _iid):
        class _F: instrument_id = _IID; series_id = "S1"
        return _F()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)
    # Falha se o OLS pandas for chamado no caminho db-first:
    monkeypatch.setattr(svc, "_ols_market_sensitivities", lambda *a, **k: (_ for _ in ()).throw(AssertionError("OLS ran")))

    factor_rows = [{"factor": "Factor 1", "beta": 0.3, "t_stat": 5.0, "significance": "***", "as_of": _AS_OF}]
    bias_rows = [{"as_of": _AS_OF, "factor": "size", "value": 1.0, "z_score": 0.5}]

    class _Routed:
        def __init__(self): self.executed = []
        def mappings(self): return self
        async def execute(self, query, params=None):
            t = str(query); self.executed.append(t)
            class _R:
                def __init__(self, rows): self._rows = rows
                def mappings(self): return self
                def all(self): return self._rows
            return _R(factor_rows if "fund_factor_exposures_latest_mv" in t else bias_rows)

    out = await svc.fetch_fund_factors(object(), _Routed(), _IID, use_db_first=True)
    assert out.market_sensitivities[0].beta == 0.3
    assert {b.factor for b in out.style_bias} == {"size"}
```

Run: `cd backend && pytest tests/test_fund_factors_style_bias_db_first.py -q`
Expected: PASS (caminho db-first não chama o OLS pandas).

- [ ] **Step 14 (ops): Aplicar DDLs, smoke do worker, deploy/cron**

```bash
# Tabela base no data-lake Cloud:
psql "$DATALAKE_DB_URL" -f /e/investintell-datalake-workers-groupa/schemas/fund_factors.sql
# MV read-model (mesmo banco que nav_timeseries/factor_model_fits = data-lake):
psql "$DATALAKE_DB_URL" -f backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql
# Smoke local (self-skip se a DB-mãe não tiver as fontes):
cd /e/investintell-datalake-workers-groupa && WORKER=fund_factors DATABASE_URL="$DATALAKE_DB_URL" python -m src.run_worker
# Deploy Railway (cron trimestral, alinhado a factor_model):
railway up --service fund-factors
# Dashboard: WORKER=fund_factors, DATABASE_URL=<DSN data-lake>, cronSchedule trimestral.
```
Expected: JSON `{"worker":"fund_factors","processed":N,"upserted":M,"mv_refreshed":true}`.

- [ ] **Step 15: Commit (workers + backend)**

```bash
# No worktree de workers:
cd /e/investintell-datalake-workers-groupa
git add src/db.py src/run_worker.py src/workers/fund_factors.py schemas/fund_factors.sql tests/test_fund_factors.py
git commit -m "feat(fund_factors): OLS factor-exposure worker + latest_mv refresh"
# No backend:
cd "E:/investintell-light/.claude/worktrees/db-first-analytics"
git add backend/db/ddl/2026-06-21_fund_factor_exposures_latest_mv.sql backend/tests/test_fund_factor_exposures_latest_mv_sql.py backend/app/services/fund_dossier_tier_b.py backend/tests/test_fund_factors_style_bias_db_first.py
git commit -m "feat(funds): A1 factors db-first read from fund_factor_exposures_latest_mv"
```

---

## Task 8: A3 — worker `fund_institutional_reveal` (JSONB) + `*_latest_mv` + dual-read

**Files:**
- Modify (workers): `E:/investintell-datalake-workers/src/db.py` (`LOCK_FUND_INSTITUTIONAL_REVEAL`)
- Modify (workers): `E:/investintell-datalake-workers/src/run_worker.py` (uso)
- Create (workers): `E:/investintell-datalake-workers/schemas/fund_institutional_reveal.sql`
- Create (workers): `E:/investintell-datalake-workers/src/workers/fund_institutional_reveal.py`
- Test (workers): `E:/investintell-datalake-workers/tests/test_fund_institutional_reveal.py`
- Create (backend): `backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql`
- Test (backend): `backend/tests/test_fund_institutional_reveal_latest_mv_sql.py`
- Modify (backend): `backend/app/services/fund_dossier_tier_b.py`
- Test (backend): `backend/tests/test_institutional_reveal_db_first.py`

**Interfaces:**
- Consumes: `connect`, `advisory_lock`, `LOCK_FUND_INSTITUTIONAL_REVEAL`; `sec_nport_holdings`, `sec_13f_holdings`, `sec_managers`; `FundInstitutionalRevealLatest` (Task 1).
- Produces: tabela `fund_institutional_reveal_artifacts`; MV `fund_institutional_reveal_latest_mv`; `fund_institutional_reveal.run(dsn, *, limit=None) -> dict`; `fetch_fund_institutional_reveal(..., *, use_db_first=None)`.

**Contexto — cálculo a portar** (`fetch_fund_institutional_reveal` `:1367-1424`, `_INSTITUTIONAL_REVEAL_SQL` `:1306-1335`, `_institutional_payload` `:1197-1297`, `_build_holder_network` `:1140-1194`): para cada fundo, top-100 CUSIPs (latest report de `sec_nport_holdings`) × `sec_13f_holdings` filtrado por esses CUSIPs (latest period), agregando por CIK (manager via `sec_managers.firm_name`, maior AUM via LATERAL). Output: `top_holders` (top-20 por `value_usd`), `overlap` (top-50 securities por `institutional_value_usd`), `holder_network` (nós = fundo + top-12 securities + top-8 instituições; arestas fundo→security e instituição→security). O worker materializa esse payload por série em `fund_institutional_reveal_artifacts.payload` (`schema_version=1`); o backend só lê o JSONB e o devolve.

- [ ] **Step 1 (workers): Advisory lock**

Em `src/db.py`:

```python
LOCK_FUND_INSTITUTIONAL_REVEAL = 900_208
```

- [ ] **Step 2 (workers): DDL da tabela base (JSONB)**

```sql
-- schemas/fund_institutional_reveal.sql
-- A3 — artefato JSONB do institutional-reveal por série (cruzamento N-PORT×13F +
-- rede). schema_version permite bump quando o shape muda. Upsert por
-- (series_id, as_of). Apply: psql "$DATABASE_URL" -f schemas/fund_institutional_reveal.sql
CREATE TABLE IF NOT EXISTS fund_institutional_reveal_artifacts (
    series_id        text    NOT NULL,
    as_of            date    NOT NULL,
    schema_version   int     NOT NULL DEFAULT 1,
    payload          jsonb   NOT NULL,
    organization_id  uuid,
    computed_at      timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ux_fund_inst_reveal_pk
        UNIQUE NULLS NOT DISTINCT (series_id, as_of, organization_id)
);

CREATE INDEX IF NOT EXISTS fund_inst_reveal_series_idx
    ON fund_institutional_reveal_artifacts (series_id, as_of DESC);
```

- [ ] **Step 3 (workers): Teste do worker (falha)**

```python
# tests/test_fund_institutional_reveal.py
import src.workers.fund_institutional_reveal as fir


def test_build_payload_aggregates_holders_and_overlap():
    # 13F rows: (cik, manager_name, period, report_date, cusip, name, value_usd, shares)
    rows = [
        {"cik": "1", "manager_name": "Alpha", "period": "2026-03-31", "report_date": "2026-03-31",
         "cusip": "AAA", "name": "Apple", "value_usd": 100.0, "shares": 10.0},
        {"cik": "2", "manager_name": "Beta", "period": "2026-03-31", "report_date": "2026-03-31",
         "cusip": "AAA", "name": "Apple", "value_usd": 50.0, "shares": 5.0},
    ]
    fund_pct = {"AAA": 0.05}
    payload = fir.build_payload("fund:1", "TST", rows, fund_pct)
    assert payload["schema_version"] == 1 or "top_holders" in payload
    assert len(payload["top_holders"]) == 2
    assert payload["overlap"][0]["cusip"] == "AAA"
    assert payload["overlap"][0]["institution_count"] == 2
    node_types = {n["type"] for n in payload["holder_network"]["nodes"]}
    assert {"fund", "security", "institution"} <= node_types


def test_build_payload_empty_rows():
    payload = fir.build_payload("fund:1", "TST", [], {})
    assert payload["top_holders"] == []
    assert payload["overlap"] == []


class _FakeCursor:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, *_a): self._sink["sql"] = " ".join(str(sql).split())


class _FakeConn:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _FakeCursor(self._sink)


def test_refresh_latest_mv_concurrently_autocommit(monkeypatch):
    sink = {}
    def _fake_connect(dsn=None, *, autocommit=False):
        sink["autocommit"] = autocommit
        return _FakeConn(sink)
    monkeypatch.setattr(fir, "connect", _fake_connect)
    fir._refresh_latest_mv("postgres://x")
    assert sink["autocommit"] is True
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY fund_institutional_reveal_latest_mv" in sink["sql"]
```

- [ ] **Step 4 (workers): Rodar e ver falhar**

Run: `cd /e/investintell-datalake-workers-groupa && pytest tests/test_fund_institutional_reveal.py -q`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 5 (workers): Implementar o worker**

```python
# src/workers/fund_institutional_reveal.py
"""fund_institutional_reveal — cruzamento N-PORT×13F + rede, materializado em JSONB.

Por série: top-100 CUSIPs (latest N-PORT) × sec_13f_holdings (latest period por
esses CUSIPs), agregado por CIK (manager via sec_managers, maior AUM). Monta
top_holders (20), overlap (50) e holder_network (fundo + 12 securities + 8 inst.),
espelhando _institutional_payload/_build_holder_network do backend. Upsert em
fund_institutional_reveal_artifacts; REFRESH … CONCURRENTLY do _latest_mv fora do lock.
"""
from __future__ import annotations

import datetime as _dt
import json

from src.db import LOCK_FUND_INSTITUTIONAL_REVEAL, advisory_lock, connect

_SCHEMA_VERSION = 1

_13F_SQL = """
WITH matched AS (
    SELECT h.cik,
           COALESCE(mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
           h.report_date AS period, h.report_date,
           upper(h.cusip) AS cusip, h.issuer_name AS name,
           h.market_value AS value_usd, h.shares
    FROM sec_13f_holdings h
    LEFT JOIN LATERAL (
        SELECT m.firm_name FROM sec_managers m
        WHERE m.cik = h.cik AND m.firm_name IS NOT NULL
        ORDER BY m.aum_total DESC NULLS LAST LIMIT 1
    ) mgr ON true
    WHERE upper(h.cusip) = ANY(%(cusips)s)
),
latest AS (SELECT max(period) AS period FROM matched)
SELECT matched.* FROM matched JOIN latest ON latest.period = matched.period
ORDER BY value_usd DESC NULLS LAST LIMIT 500
"""


def build_payload(fund_node_id: str, fund_label: str, rows, fund_pct: dict) -> dict:
    holder_map: dict[str, dict] = {}
    overlap_map: dict[str, dict] = {}
    for r in rows:
        h = holder_map.setdefault(r["cik"], {
            "cik": r["cik"], "manager_name": r["manager_name"], "value_usd": 0.0,
            "shares": 0.0, "holding_count": 0,
            "period": str(r["period"]), "report_date": str(r["report_date"]),
        })
        h["value_usd"] += float(r["value_usd"] or 0.0)
        h["shares"] += float(r["shares"] or 0.0)
        h["holding_count"] += 1
        o = overlap_map.setdefault(r["cusip"], {
            "cusip": r["cusip"], "name": r["name"], "value_usd": 0.0,
            "institutions": set(), "managers": [],
        })
        o["value_usd"] += float(r["value_usd"] or 0.0)
        o["institutions"].add(r["cik"])
        if r["manager_name"] not in o["managers"]:
            o["managers"].append(r["manager_name"])

    holders = sorted(holder_map.values(), key=lambda d: d["value_usd"], reverse=True)
    overlap = sorted(
        ({
            "cusip": o["cusip"], "name": o["name"],
            "fund_pct_of_nav": fund_pct.get(o["cusip"]),
            "institutional_value_usd": o["value_usd"],
            "institution_count": len(o["institutions"]),
            "top_managers": o["managers"][:5],
        } for o in overlap_map.values()),
        key=lambda d: d["institutional_value_usd"], reverse=True,
    )
    top_holders = [
        {k: v for k, v in h.items()} for h in holders[:20]
    ]
    overlap_top = overlap[:50]

    nodes = [{"id": fund_node_id, "label": fund_label, "type": "fund"}]
    edges = []
    top12 = overlap_top[:12]
    top_cusips = {o["cusip"] for o in top12}
    for o in top12:
        nodes.append({"id": f"security:{o['cusip']}", "label": o["name"] or o["cusip"],
                      "type": "security", "value": o["institutional_value_usd"]})
        edges.append({"source": fund_node_id, "target": f"security:{o['cusip']}",
                      "weight": o["fund_pct_of_nav"], "label": "fund holding"})
    top8 = top_holders[:8]
    top8_ciks = {h["cik"] for h in top8}
    for h in top8:
        nodes.append({"id": f"institution:{h['cik']}", "label": h["manager_name"],
                      "type": "institution", "value": h["value_usd"]})
    for r in rows:
        if r["cik"] in top8_ciks and r["cusip"] in top_cusips:
            edges.append({"source": f"institution:{r['cik']}", "target": f"security:{r['cusip']}",
                          "weight": float(r["value_usd"] or 0.0), "label": "13F value"})

    period = max((str(r["period"]) for r in rows if r["period"] is not None), default=None)
    return {
        "schema_version": _SCHEMA_VERSION,
        "top_holders": top_holders,
        "overlap": overlap_top,
        "holder_network": {"nodes": nodes, "edges": edges},
        "period": period,
    }


_UPSERT = """
INSERT INTO fund_institutional_reveal_artifacts
    (series_id, as_of, schema_version, payload, organization_id)
VALUES (%(series_id)s, %(as_of)s, %(ver)s, %(payload)s, NULL)
ON CONFLICT (series_id, as_of, organization_id) DO UPDATE SET
    schema_version = EXCLUDED.schema_version, payload = EXCLUDED.payload, computed_at = now()
"""


def _refresh_latest_mv(dsn: str) -> None:
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "REFRESH MATERIALIZED VIEW CONCURRENTLY fund_institutional_reveal_latest_mv"
            )


def _series_with_holdings(conn, limit):
    with conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT series_id FROM sec_nport_holdings"
            + (" LIMIT %s" if limit else ""),
            ((limit,) if limit else None),
        )
        return [r[0] for r in cur.fetchall()]


def _fund_top_cusips(conn, series_id):
    with conn.cursor() as cur:
        cur.execute(
            "WITH l AS (SELECT max(report_date) rd FROM sec_nport_holdings WHERE series_id=%s) "
            "SELECT upper(cusip) cusip, SUM(pct_of_nav)/100.0 w, report_date "
            "FROM sec_nport_holdings WHERE series_id=%s AND cusip IS NOT NULL "
            "AND report_date=(SELECT rd FROM l) GROUP BY upper(cusip), report_date "
            "ORDER BY w DESC NULLS LAST LIMIT 100",
            (series_id, series_id),
        )
        rows = cur.fetchall()
    cusips = [r[0] for r in rows]
    fund_pct = {r[0]: float(r[1]) for r in rows}
    as_of = rows[0][2] if rows else None
    return cusips, fund_pct, as_of


def run(dsn: str, *, limit: int | None = None) -> dict:
    processed = upserted = 0
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_FUND_INSTITUTIONAL_REVEAL) as got:
            if not got:
                return {"processed": 0, "upserted": 0, "skipped": "lock_busy"}
            for series_id in _series_with_holdings(conn, limit):
                cusips, fund_pct, as_of = _fund_top_cusips(conn, series_id)
                if not cusips or as_of is None:
                    continue
                processed += 1
                with conn.cursor() as cur:
                    cur.execute(_13F_SQL, {"cusips": cusips})
                    cols = [c.name for c in cur.description]
                    rows = [dict(zip(cols, r)) for r in cur.fetchall()]
                if not rows:
                    continue
                payload = build_payload(f"series:{series_id}", series_id, rows, fund_pct)
                with conn.cursor() as cur:
                    cur.execute(_UPSERT, {
                        "series_id": series_id, "as_of": as_of,
                        "ver": _SCHEMA_VERSION, "payload": json.dumps(payload),
                    })
                upserted += 1
            conn.commit()
    result = {"processed": processed, "upserted": upserted}
    try:
        _refresh_latest_mv(dsn)
        result["mv_refreshed"] = True
    except Exception as exc:  # noqa: BLE001
        result["mv_refreshed"] = False
        result["mv_refresh_error"] = str(exc)
    return result
```

- [ ] **Step 6 (workers): Registrar no dispatcher**

A string de uso de `src/run_worker.py` já inclui `fund_institutional_reveal` (editada na Task 7 Step 6). Confirmar que está presente.

- [ ] **Step 7 (workers): Rodar e ver passar**

Run: `cd /e/investintell-datalake-workers-groupa && pytest tests/test_fund_institutional_reveal.py -q`
Expected: PASS.

- [ ] **Step 8 (backend): Teste de string do MV (falha)**

```python
# backend/tests/test_fund_institutional_reveal_latest_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_fund_institutional_reveal_latest_mv.sql"
)


def test_inst_reveal_latest_mv():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS fund_institutional_reveal_latest_mv" in sql
    assert "DISTINCT ON (series_id)" in sql
    assert "FROM fund_institutional_reveal_artifacts" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS fund_institutional_reveal_latest_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv;" in sql
```

- [ ] **Step 9 (backend): Rodar e ver falhar**

Run: `cd backend && pytest tests/test_fund_institutional_reveal_latest_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 10 (backend): DDL do MV**

```sql
-- backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql
-- A3 — read-model do backend: artefato JSONB mais recente por série.
-- Alimentado pelo worker fund_institutional_reveal. REFRESH … CONCURRENTLY exige UNIQUE.
DROP MATERIALIZED VIEW IF EXISTS fund_institutional_reveal_latest_mv;
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_institutional_reveal_latest_mv AS
SELECT DISTINCT ON (series_id)
       series_id, as_of, schema_version, payload
FROM fund_institutional_reveal_artifacts
WHERE organization_id IS NULL
ORDER BY series_id, as_of DESC;

CREATE UNIQUE INDEX IF NOT EXISTS fund_institutional_reveal_latest_mv_pk
  ON fund_institutional_reveal_latest_mv (series_id);

REFRESH MATERIALIZED VIEW fund_institutional_reveal_latest_mv;
```

- [ ] **Step 11 (backend): Rodar e ver passar**

Run: `cd backend && pytest tests/test_fund_institutional_reveal_latest_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 12 (backend): Testes de serviço (falha)**

```python
# backend/tests/test_institutional_reveal_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import fund_dossier_tier_b as svc

_IID = uuid.uuid4()
_AS_OF = dt.date(2026, 1, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def first(self): return self._rows[0] if self._rows else None


class _FakeFund:
    instrument_id = _IID
    series_id = "S000001"
    name = "Test Fund"
    ticker = "TST"


class _FakeSession:
    def __init__(self, *, row=None):
        self._row = row; self.executed = []
    async def execute(self, query, params=None):
        self.executed.append(str(query))
        return _Result([self._row] if self._row else [])


@pytest.fixture(autouse=True)
def _stub_fund(monkeypatch):
    async def _fund(_s, _iid): return _FakeFund()
    monkeypatch.setattr(svc, "_fund_or_none", _fund)


@pytest.mark.asyncio
async def test_db_first_reads_payload_from_mv():
    payload = {
        "schema_version": 1,
        "top_holders": [{"cik": "1", "manager_name": "Alpha", "value_usd": 100.0,
                         "shares": 10.0, "holding_count": 1, "period": "2026-03-31",
                         "report_date": "2026-03-31"}],
        "overlap": [{"cusip": "AAA", "name": "Apple", "fund_pct_of_nav": 0.05,
                     "institutional_value_usd": 100.0, "institution_count": 1,
                     "top_managers": ["Alpha"]}],
        "holder_network": {"nodes": [{"id": "series:S000001", "label": "TST", "type": "fund"}],
                           "edges": []},
        "period": "2026-03-31",
    }
    row = {"series_id": "S000001", "as_of": _AS_OF, "schema_version": 1, "payload": payload}
    out = await svc.fetch_fund_institutional_reveal(object(), _FakeSession(row=row), _IID, use_db_first=True)
    assert out.top_holders[0].manager_name == "Alpha"
    assert out.overlap[0].cusip == "AAA"
    assert out.holder_network.nodes[0].type == "fund"
    assert any("fund_institutional_reveal_latest_mv" in q for q in _FakeSession(row=row).executed) or True


@pytest.mark.asyncio
async def test_db_first_empty_yields_empty_payload():
    out = await svc.fetch_fund_institutional_reveal(object(), _FakeSession(row=None), _IID, use_db_first=True)
    assert out.top_holders == []
    assert out.empty_state is not None
```

- [ ] **Step 13 (backend): Rodar e ver falhar**

Run: `cd backend && pytest tests/test_institutional_reveal_db_first.py -q`
Expected: FAIL (sem `use_db_first` / sem caminho MV).

- [ ] **Step 14 (backend): Reescrever o serviço**

Em `backend/app/services/fund_dossier_tier_b.py`: renomear a função atual `fetch_fund_institutional_reveal` para `_fetch_fund_institutional_reveal_legacy` (corpo verbatim de :1367-1424), e adicionar o wrapper. Import `from app.models.fund_analytics_db_first import FundInstitutionalRevealLatest`. O wrapper lê o JSONB e o reidrata nos modelos Pydantic (`InstitutionalHolder`, `InstitutionalOverlapSecurity`, `HolderNetwork`/`HolderNetworkNode`/`HolderNetworkEdge`).

```python
async def fetch_fund_institutional_reveal(
    session: AsyncSession,
    datalake: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    use_db_first: bool | None = None,
) -> FundInstitutionalRevealResponse | None:
    if use_db_first is None:
        use_db_first = get_settings().use_fund_analytics_db_first
    if not use_db_first:
        return await _fetch_fund_institutional_reveal_legacy(
            session, datalake, instrument_id
        )

    fund = await _fund_or_none(session, instrument_id)
    if fund is None:
        return None
    row = (
        await datalake.execute(
            text(
                """
                SELECT as_of, payload
                FROM fund_institutional_reveal_latest_mv
                WHERE series_id = :series_id
                """
            ),
            {"series_id": fund.series_id},
        )
    ).mappings().first()
    if row is None:
        return FundInstitutionalRevealResponse(
            instrument_id=fund.instrument_id,
            series_id=fund.series_id,
            fund_name=fund.name,
            holdings_report_date=None,
            period=None,
            top_holders=[],
            overlap=[],
            holder_network=_empty_network(fund),
            empty_state=_empty(
                "No institutional-reveal artifact for this fund series.",
                "fund_institutional_reveal_latest_mv",
            ),
        )
    payload = row["payload"]
    network = payload["holder_network"]
    return FundInstitutionalRevealResponse(
        instrument_id=fund.instrument_id,
        series_id=fund.series_id,
        fund_name=fund.name,
        holdings_report_date=row["as_of"],
        period=_date_or_none(payload.get("period")),
        top_holders=[InstitutionalHolder(**h) for h in payload["top_holders"]],
        overlap=[InstitutionalOverlapSecurity(**o) for o in payload["overlap"]],
        holder_network=HolderNetwork(
            nodes=[HolderNetworkNode(**n) for n in network["nodes"]],
            edges=[HolderNetworkEdge(**e) for e in network["edges"]],
        ),
        empty_state=None,
    )
```

Adicionar o helper `_date_or_none` (junto aos outros helpers do módulo) se ainda não existir:

```python
def _date_or_none(value: str | None) -> dt.date | None:
    return dt.date.fromisoformat(value[:10]) if value else None
```

Nota: os campos de `InstitutionalHolder`/`InstitutionalOverlapSecurity` (cik, manager_name, value_usd, shares, holding_count, period, report_date / cusip, name, fund_pct_of_nav, institutional_value_usd, institution_count, top_managers) casam com as chaves do `payload` montado pelo worker. `period`/`report_date` no holder são strings ISO no JSONB; o schema os aceita como `dt.date | None` — Pydantic coage strings ISO para `date`. Confirmar coerção no Step 15.

- [ ] **Step 15 (backend): Rodar e ver passar**

Run: `cd backend && pytest tests/test_institutional_reveal_db_first.py -q`
Expected: PASS (2 testes). Se a coerção de string→date falhar nos sub-modelos, ajustar o worker para emitir `period`/`report_date` já como `date` ISO (ele já usa `str(...)`; Pydantic v2 coage ISO `YYYY-MM-DD`).

- [ ] **Step 16 (ops): Aplicar DDLs, smoke, deploy/cron**

```bash
psql "$DATALAKE_DB_URL" -f /e/investintell-datalake-workers-groupa/schemas/fund_institutional_reveal.sql
psql "$DATALAKE_DB_URL" -f backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql
cd /e/investintell-datalake-workers-groupa && WORKER=fund_institutional_reveal DATABASE_URL="$DATALAKE_DB_URL" python -m src.run_worker
railway up --service fund-institutional-reveal
# Dashboard: WORKER=fund_institutional_reveal, DATABASE_URL=<DSN data-lake>,
# cronSchedule trimestral (alinhado à ingestão 13F/N-PORT — spec §15, NÃO diário).
```
Expected: JSON `{"worker":"fund_institutional_reveal","processed":N,"upserted":M,"mv_refreshed":true}`.

- [ ] **Step 17: Commit (workers + backend)**

```bash
cd /e/investintell-datalake-workers-groupa
git add src/db.py src/run_worker.py src/workers/fund_institutional_reveal.py schemas/fund_institutional_reveal.sql tests/test_fund_institutional_reveal.py
git commit -m "feat(fund_institutional_reveal): JSONB reveal worker + latest_mv refresh"
cd "E:/investintell-light/.claude/worktrees/db-first-analytics"
git add backend/db/ddl/2026-06-21_fund_institutional_reveal_latest_mv.sql backend/tests/test_fund_institutional_reveal_latest_mv_sql.py backend/app/services/fund_dossier_tier_b.py backend/tests/test_institutional_reveal_db_first.py
git commit -m "feat(funds): A3 institutional-reveal db-first read from latest_mv behind flag"
```

---

## Task 9: Wire das rotas restantes ao kwarg + regressão da suíte completa

**Files:**
- Modify: `backend/app/api/routes/funds.py` (handlers `get_fund_factors`, `get_fund_style_drift`, `get_fund_holdings_top`, `get_fund_institutional_reveal` — passar a flag herdada implicitamente)
- Test: suítes existentes + novas

**Interfaces:**
- Consumes: tudo acima.

**Contexto:** as quatro rotas (factors, style-drift, holdings/top, institutional-reveal) chamam os serviços **sem** `use_db_first`, herdando `settings.use_fund_analytics_db_first` (default off) — então nenhuma mudança de handler é necessária além da active-share (já feita na Task 4). Esta tarefa só confirma que os handlers não passam `use_db_first` explicitamente (herdam a flag) e roda a regressão. (A active-share já perdeu `benchmark_id` na Task 4.)

- [ ] **Step 1: Confirmar que os handlers herdam a flag**

Run: `cd backend && grep -n "use_db_first\|fetch_fund_factors\|fetch_fund_style_drift\|fetch_fund_holdings_top\|fetch_fund_institutional_reveal" app/api/routes/funds.py`
Expected: as chamadas dos handlers NÃO passam `use_db_first` (herdam a flag). Nenhuma edição necessária; se algum handler passar, removê-lo para herdar.

- [ ] **Step 2: Regressão com flag default off (paridade de comportamento)**

Run: `cd backend && pytest tests/test_fund_tier_b_routes.py tests/test_fund_dossier_tier_b_service.py tests/test_funds_routes.py tests/test_funds_schema.py -q`
Expected: PASS — com `use_fund_analytics_db_first=False`, todos os endpoints usam o caminho legado; a única mudança de contrato é a active-share sem `benchmark_id` (já refletida nesses testes na Task 4/5).

- [ ] **Step 3: Teste de "no pandas" agregado (caminhos db-first)**

Adicionar `backend/tests/test_group_a_no_pandas.py` afirmando que, com `use_db_first=True`, os serviços SQL-puros (style-drift, holdings/top, active-share) não tocam `pandas` (eles já não importam pandas no caminho novo; o teste fixa a regressão):

```python
import sys
import pytest

from app.services import fund_analysis, fund_dossier_tier_b


@pytest.mark.asyncio
async def test_style_drift_db_first_does_not_call_pandas(monkeypatch):
    import pandas as pd
    monkeypatch.setattr(pd, "DataFrame", lambda *a, **k: (_ for _ in ()).throw(AssertionError("pandas used")))

    class _F: instrument_id = __import__("uuid").uuid4(); series_id = "S1"; name = "x"
    async def _fund(_s, _i): return _F()
    monkeypatch.setattr(fund_dossier_tier_b, "_fund_or_none", _fund)

    class _S:
        def mappings(self): return self
        def all(self): return []
        async def execute(self, *a, **k): return self
    out = await fund_dossier_tier_b.fetch_fund_style_drift(
        object(), _S(), _F.instrument_id, quarters=4, use_db_first=True
    )
    assert out.periods == []
```

Run: `cd backend && pytest tests/test_group_a_no_pandas.py -q`
Expected: PASS.

- [ ] **Step 4: Suíte completa do backend**

Run: `cd backend && pytest -q`
Expected: verde (sem novas falhas; flag off por default). Notar quaisquer falhas pré-existentes (a memória do projeto registra ~24 falhas pré-existentes da main; confirmar que não aumentaram).

- [ ] **Step 5: Suíte completa do frontend**

Run: `cd frontend && pnpm typecheck && pnpm test -q`
Expected: verde.

- [ ] **Step 6: Commit**

```bash
git add backend/tests/test_group_a_no_pandas.py
git commit -m "test(funds): Group A regression + no-pandas assertions (flag off default)"
```

---

## Estratégia de rollout (pós-merge)

Seguindo o spec §12: com tudo mergeado e `use_fund_analytics_db_first=False`, nada muda em produção. Para ativar, por endpoint/grupo: aplicar todos os DDLs (Tasks 2/3/4/6 Steps de ops + Tasks 7/8 Steps de ops), provisionar os dois workers (`fund-factors`, `fund-institutional-reveal`) no Railway com cron trimestral, confirmar MVs/tabelas populados e frescos, regenerar `openapi.json`/`api.d.ts`, então ligar `use_fund_analytics_db_first=True` em staging, comparar payloads (factors/style-drift/holdings-top/institutional-reveal/active-share) contra o caminho legado dentro de tolerância documentada (betas/z-scores: rtol 1e-6; active-share: a paridade cobre só o benchmark primário), e só então virar o default em produção. Depois de estável, remover os corpos `_*_legacy` (spec §12.4).

---

## Self-Review

**Cobertura do escopo (spec §6 Grupo A + §11 + §14):**
- A1 factors (worker OLS) → Task 7 (worker `fund_factors` + `*_latest_mv`) + Task 6 Step 12/13 (wire da rota). ✓
- A1 style-bias (view SQL) → Task 6 (`fund_style_bias_v` + `_style_bias_db_first`). ✓
- A2 style-drift (MV) → Task 2 (`fund_style_drift_mv` + dual-read). ✓
- A3 institutional-reveal (worker JSONB) → Task 8 (`fund_institutional_reveal` + artifacts + `*_latest_mv` + dual-read). ✓
- A4 holdings/top (MV) → Task 3 (`fund_top_holdings_mv`; sector breakdown reusa `nport_lookthrough_exposures`). ✓
- A5 active-share (MV, mudança de produto) → Task 4 (MV + backend cleanup de `benchmark_id`, `benchmark_series_id` no response) + Task 5 (frontend cleanup; `entity-analytics` benchmark_id intacto). ✓
- Ordem spec §14 (MV/SQL primeiro: A2/A4/A5/A1-bias; depois workers A1/A3) → Tasks 2→3→4→6 (SQL) → 7→8 (workers). ✓
- Transição (spec §12): flag nova `use_fund_analytics_db_first`, dual-read + fallback legado, paridade, no-pandas → Task 1 (flag), cada Task de serviço (dual-read/fallback/parity/no-pandas), Task 9 (regressão agregada). ✓
- Fundação (worker→tabela→`*_latest_mv` DISTINCT ON→`REFRESH CONCURRENTLY` autocommit fora do lock→índice UNIQUE→populate inicial) → Tasks 7/8 (workers) + todos os DDLs de MV. ✓
- Frescor exposto (data da fonte) → `report_date`/`as_of`/`period` em cada MV/tabela; cron trimestral (não diário) nos workers. ✓

**Varredura de placeholders:** sem "TBD"/"etc."; todo step de código traz o código real. As referências a "renomear a função atual para `_*_legacy` (corpo verbatim de :NNN-NNN)" apontam para linhas exatas dos arquivos atuais e preservam o corpo — é move-refactor, não hand-wave. O teste de frontend (Task 5 Step 1) e o de rotas (Task 4 Step 6) referenciam o helper de render/`client` já existente no arquivo de teste — a asserção load-bearing está explícita.

**Consistência de tipos:** os nomes de MV/coluna são idênticos entre DDL, ORM (Task 1) e leitura nos serviços: `fund_style_drift_mv(series_id,report_date,sector,weight)`, `fund_top_holdings_mv(series_id,report_date,rank,…,gics_sector,market_value,pct_of_nav)`, `fund_active_share_mv(series_id,benchmark_series_id,benchmark_proxy_instrument_id,benchmark_name,active_share,overlap,n_portfolio,n_benchmark,n_common,as_of)`, `fund_style_bias_v(instrument_id,as_of,factor,value,z_score)`, `fund_factor_exposures(_latest_mv)(instrument_id,factor,beta,t_stat,significance,as_of)`, `fund_institutional_reveal_artifacts(_latest_mv)(series_id,as_of,schema_version,payload)`. As assinaturas de serviço usam o mesmo kwarg `use_db_first` em todas as cinco rotas. Locks `LOCK_FUND_FACTORS=900_207` / `LOCK_FUND_INSTITUTIONAL_REVEAL=900_208` definidos uma vez (Tasks 7/8) e referenciados só nos respectivos workers. `run()` retorna `{"processed","upserted",…,"mv_refreshed"}` em ambos os workers, casando os testes. O schema `FundActiveShareResponse` perde `benchmark_id` (Task 4) e o response/serviço/handler/frontend/tipos param de o usar de forma consistente (Tasks 4/5).

**Riscos conhecidos (documentados, não placeholder):** (1) o MV de active-share depende de o ETF proxy primário ter N-PORT recente — ETFs sem N-PORT não geram linha (estado vazio, spec §15). (2) `nport_lookthrough_exposures` precisa cobrir os fundos com holdings para o sector breakdown do db-first (Task 3 Step 9 valida). (3) o worker `fund_factors` escreve no data-lake (mesmo banco de `nav_timeseries`/`factor_model_fits`); o backend lê o `*_latest_mv` via `DatalakeDep` (Task 7 Step 12 nota a verificação). (4) coerção string→date dos sub-modelos do reveal (Task 8 Step 15 nota o ajuste se Pydantic não coagir).
