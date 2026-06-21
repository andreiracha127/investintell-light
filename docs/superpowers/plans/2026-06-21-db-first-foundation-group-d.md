# DB-First — Fundação + Grupo D Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materializar os "dois últimos pontos" de preço/NAV em dois materialized views (`price_latest_mv`, `nav_latest_mv`) refrescados por um worker dedicado, e fazer `portfolios/{id}/overview` e `portfolios/{id}/lookthrough` lerem preço desses MVs em vez de varrer a série — sem mudar números nem o shape de resposta.

**Architecture:** Os MVs vivem no **DB principal do app** (em produção, o schema `public` do Timescale Cloud), pois é onde `eod_prices` e `nav_timeseries` residem; um MV só pode cobrir tabelas do próprio banco. Um novo worker `matview_refresh` em `investintell-datalake-workers` dá `REFRESH MATERIALIZED VIEW CONCURRENTLY` nos dois MVs num cron, seguindo o padrão do `risk_metrics` (conexão autocommit, fora do advisory lock). No backend, as duas funções de leitura de preço (`select_last_two_closes`, `select_last_two_navs`) passam a ler do MV atrás de uma flag, com **fallback à tabela base** para entidades ainda ausentes do MV (ticker que o backfill worker já gravou em `eod_prices`/`nav_timeseries` mas que o `matview_refresh` ainda não capturou), preservando exatamente o tipo de retorno que `build_overview`/`consolidate_portfolio` consomem.

**Tech Stack:** Python 3.11+, psycopg3 (workers), SQLAlchemy 2.0 async + asyncpg (backend), FastAPI, PostgreSQL/TimescaleDB, pytest (`asyncio_mode = "auto"`), Railway cron.

## Baseline — commit `38dbdb4` (main, "make historical market data db-first")

Este plano assume o estado pós-`38dbdb4`, já mergeado na main (precisa ser rebaseado/integrado a esta branch antes de executar). O que esse commit já fez e que muda as premissas:

- **`ensure_eod_or_http_error` removido.** Não há mais fetch síncrono do Tiingo no request path. As rotas (stocks, funds, portfolio, portfolios, statistics, monte_carlo) leem histórico **local**. `eod_prices`/`nav_timeseries` passam a ser populados por backfill/warming worker **out-of-band**.
- **`overview`/`lookthrough` já não chamam ensure.** `get_portfolio_overview` **perdeu o parâmetro `client: TiingoClient`**; a cobertura é validada por `_require_local_trade_tickers` → `select_tickers_with_eod` (404 se faltar cobertura local). `select_last_two_closes`/`select_last_two_navs` **permanecem inalteradas** (ainda fazem a window query) — continuam sendo os alvos da reescrita deste plano.
- **`cagg_eod_daily`** (continuous aggregate sobre `eod_prices`: `ticker, bucket, close, …`) e **`cagg_nav_daily`** (sobre `nav_timeseries`: `instrument_id, bucket, nav, return_1d, …`) foram criados, ambos com `add_continuous_aggregate_policy` de auto-refresh diário + real-time aggregation. DDL em `backend/db/ddl/2026-06-21_cagg_eod_daily_timeseries.sql` e `…_cagg_nav_daily_timeseries.sql`, testes em `backend/tests/test_dynamic_catalog_sql.py`. Estabelecem a convenção: **DDL do DB principal vive em `backend/db/ddl/` no repo backend** (aplicado via Tiger/psql), não em `schemas/` do repo de workers.

Implicações deste plano: (1) o DDL dos `*_latest_mv` segue a convenção `backend/db/ddl/`; (2) os MVs leem dos **CAGGs diários canônicos** (`cagg_eod_daily`/`cagg_nav_daily`), não das tabelas cruas — decisão do dono — preservando paridade (os CAGGs usam `last(... , <date>)` por dia sobre tabelas já diárias); (3) o **fallback à tabela base** continua necessário, mas a razão agora é o **lag entre o backfill worker e o `matview_refresh`** (não o ensure, que não existe mais); (4) os CAGGs **não** substituem os `*_latest_mv` — "duas últimas observações por entidade" é window/DISTINCT-ON, não um time-bucket de cagg.

## Global Constraints

- Os MVs `price_latest_mv` / `nav_latest_mv` residem no **DB principal** (`DATABASE_URL` / `settings.database_url`), o mesmo banco que `eod_prices` e `nav_timeseries`. NÃO no datalake (`DATALAKE_DB_URL`).
- DDL do DB principal é versionado em **`backend/db/ddl/`** (arquivos datados, aplicados via Tiger/psql), seguindo a convenção de `38dbdb4` (`backend/db/ddl/2026-06-21_cagg_eod_daily_timeseries.sql`). NÃO em `schemas/` do repo de workers (esse dir é para tabelas/MVs que os workers possuem; estes MVs são read-models do backend).
- Todo MV refrescado com `CONCURRENTLY` DEVE ter um índice **UNIQUE** e ter sido populado ao menos uma vez (refresh não-concorrente inicial) antes do primeiro `CONCURRENTLY`.
- O refresh roda em conexão **autocommit**, **fora** de qualquer advisory lock e bloco de transação (igual a `risk_metrics._refresh_fund_risk_latest_mv`).
- O tipo de retorno de `select_last_two_closes` e `select_last_two_navs` permanece **exatamente** `dict[str, list[tuple[datetime.date, float]]]`, lista ordenada do mais novo para o mais antigo (paridade — `build_overview` em `backend/app/services/portfolio_crud.py` e `consolidate_portfolio` em `backend/app/services/lookthrough.py` consomem sem alteração).
- Nenhum `pandas`/`numpy` introduzido (não se aplica aqui; a leitura é SELECT puro).
- Worker dispatch é por `WORKER=<nome>` em `investintell-datalake-workers/src/run_worker.py` → `importlib.import_module(f"src.workers.{worker}")`; contrato `run(dsn: str, ...) -> dict | None`.
- Advisory locks ficam no range `900_2xx` em `investintell-datalake-workers/src/db.py`; cada worker tem o seu (sem colidir).
- Backend tests: `cd backend && pytest`; `asyncio_mode = "auto"`; I/O é stubado por `monkeypatch` no nível de função (sem DB vivo).
- Workers tests: `pytest tests/test_<x>.py -s -v`; sem `conftest`; testes que precisam de DB usam a DB-mãe local e fazem self-skip se inalcançável; seams de I/O são mockados com `monkeypatch` / fake connection.

---

## File Structure

**Repo backend — `E:\investintell-light\.claude\worktrees\db-first-analytics\backend` (DB principal: DDL + leitura):**
- Create: `backend/db/ddl/2026-06-21_price_nav_latest_mv.sql` — DDL dos dois MVs (CREATE MATERIALIZED VIEW … WITH NO DATA + índices UNIQUE + populate inicial). Mesma convenção de `backend/db/ddl/2026-06-21_cagg_eod_daily_timeseries.sql`.
- Create: `backend/tests/test_price_nav_latest_mv_sql.py` — teste de conteúdo do DDL (estilo `test_dynamic_catalog_sql.py`).
- Create: `app/models/price_latest.py` — modelos ORM `PriceLatest` e `NavLatest` mapeados aos MVs.
- Modify: `app/core/config.py` — flag `use_latest_mv_prices`.
- Modify: `app/services/portfolio_crud.py` — reescrever `select_last_two_closes` e `select_last_two_navs` (MV + fallback atrás da flag); preservar corpo legado como helpers privados.
- Modify: `tests/test_portfolios_overview.py` — testes de paridade/fallback/flag para as funções reescritas (ou novo `tests/test_price_latest_mv_reads.py`).

**Repo workers — `E:/investintell-datalake-workers` (apenas o refresh):**
- Create: `src/workers/matview_refresh.py` — worker que refresca ambos os MVs (conecta ao DB principal via `DATABASE_URL`).
- Modify: `src/db.py` — nova constante `LOCK_MATVIEW_REFRESH`.
- Modify: `src/run_worker.py` — registrar `matview_refresh` na mensagem de uso.
- Create: `tests/test_matview_refresh.py` — teste do worker (fake connection).

**Por que estas fronteiras:** o DDL e a leitura dos MVs vivem no repo backend (são read-models do DB principal, convenção `backend/db/ddl/` de `38dbdb4`); só o **refresh agendado** vive no repo de workers (ele apenas dá `REFRESH CONCURRENTLY`, sem possuir o schema). Cada tarefa termina com um deliverable testável de forma independente.

---

## Interfaces (contratos entre tarefas)

- `price_latest_mv(ticker text, as_of date, last_close numeric, prev_date date, prev_close numeric)`, UNIQUE(`ticker`).
- `nav_latest_mv(instrument_id uuid, as_of date, last_nav numeric, prev_date date, prev_nav numeric)`, UNIQUE(`instrument_id`).
- `LOCK_MATVIEW_REFRESH: int = 900_210` (em `src/db.py`).
- `matview_refresh.run(dsn: str) -> dict` retorna `{"refreshed": [<mv names>], ...}`.
- `PriceLatest` ORM: `.ticker`, `.as_of`, `.last_close`, `.prev_date`, `.prev_close`. `NavLatest` ORM: `.instrument_id`, `.as_of`, `.last_nav`, `.prev_date`, `.prev_nav`.
- `select_last_two_closes(session, tickers, *, use_mv: bool | None = None) -> dict[str, list[tuple[date, float]]]`.
- `select_last_two_navs(session, tickers, *, use_mv: bool | None = None) -> dict[str, list[tuple[date, float]]]`.
- `settings.use_latest_mv_prices: bool` (default `False`).

---

## Task 1: DDL dos materialized views (`price_latest_mv`, `nav_latest_mv`)

**Files:**
- Create: `backend/db/ddl/2026-06-21_price_nav_latest_mv.sql`
- Test: `backend/tests/test_price_nav_latest_mv_sql.py`

**Interfaces:**
- Produces: os dois MVs com o shape e índices UNIQUE da seção Interfaces, no DB principal.

**Contexto:** os CAGGs diários `cagg_eod_daily(ticker, bucket, open/high/low/close/volume, adj_*, …)` e `cagg_nav_daily(instrument_id, bucket, nav, return_1d, n_obs, aum_usd)` já existem no DB principal (continuous aggregates com policy de auto-refresh + real-time aggregation, criados/em uso desde `38dbdb4`). O MV achata as duas observações diárias mais recentes por entidade em uma linha (`last_*` + `prev_*`) usando `row_number()` e `FILTER` sobre o CAGG. Usa-se `close` (não `adj_close`) para casar com a aritmética P&L de `build_overview` (paridade com a leitura legada de `eod_prices.close`). Convenção de DDL/teste idêntica à de `backend/db/ddl/2026-06-21_cagg_eod_daily_timeseries.sql` + `backend/tests/test_dynamic_catalog_sql.py`.

- [ ] **Step 1: Escrever o teste que falha (conteúdo do schema)**

Estilo de `backend/tests/test_dynamic_catalog_sql.py` (asserção de string sobre o artefato SQL; sem DB).

```python
# backend/tests/test_price_nav_latest_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_price_nav_latest_mv.sql"
)


def test_schema_defines_both_mvs_with_unique_indexes():
    sql = SCHEMA.read_text(encoding="utf-8")
    # Ambos os MVs criados sem dados (populate inicial explícito depois).
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS price_latest_mv" in sql
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS nav_latest_mv" in sql
    # Índices UNIQUE são obrigatórios para REFRESH … CONCURRENTLY.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS price_latest_mv_pk" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS nav_latest_mv_pk" in sql
    # Populate inicial não-concorrente (CONCURRENTLY exige MV já populado).
    assert "REFRESH MATERIALIZED VIEW price_latest_mv;" in sql
    assert "REFRESH MATERIALIZED VIEW nav_latest_mv;" in sql
    # Fonte db-first canônica: os CAGGs diários, não as tabelas cruas.
    assert "FROM cagg_eod_daily" in sql
    assert "FROM cagg_nav_daily" in sql
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_price_nav_latest_mv_sql.py -q`
Expected: FAIL (arquivo `db/ddl/2026-06-21_price_nav_latest_mv.sql` não existe → `FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_price_nav_latest_mv.sql
-- Read-model MVs servidos pelo Light no DB principal. Achatam as DUAS
-- observações diárias mais recentes por entidade em uma linha (last_* + prev_*),
-- lendo dos CAGGs diários. Refrescados pelo worker matview_refresh
-- (REFRESH … CONCURRENTLY exige os índices UNIQUE abaixo).

-- Fonte = CAGGs diários canônicos (cagg_eod_daily / cagg_nav_daily), não as
-- tabelas cruas: alinha com a leitura db-first das rotas (38dbdb4), é mais
-- barato e tem real-time aggregation (inclui o dia corrente). Como eod_prices /
-- nav_timeseries são diários e os CAGGs usam last(... , <date>) por bucket, os
-- valores são idênticos aos da leitura legada (paridade). bucket é o time_bucket
-- diário; cast ::date para casar com PositionOverview.as_of (dt.date).

CREATE MATERIALIZED VIEW IF NOT EXISTS price_latest_mv AS
WITH ranked AS (
    SELECT ticker, bucket, close,
           row_number() OVER (PARTITION BY ticker ORDER BY bucket DESC) AS rn
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
)
SELECT
    ticker,
    (max(bucket) FILTER (WHERE rn = 1))::date AS as_of,
    max(close)   FILTER (WHERE rn = 1)        AS last_close,
    (max(bucket) FILTER (WHERE rn = 2))::date AS prev_date,
    max(close)   FILTER (WHERE rn = 2)        AS prev_close
FROM ranked
WHERE rn <= 2
GROUP BY ticker
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS price_latest_mv_pk ON price_latest_mv (ticker);

CREATE MATERIALIZED VIEW IF NOT EXISTS nav_latest_mv AS
WITH ranked AS (
    SELECT instrument_id, bucket, nav,
           row_number() OVER (PARTITION BY instrument_id ORDER BY bucket DESC) AS rn
    FROM cagg_nav_daily
    WHERE nav IS NOT NULL
)
SELECT
    instrument_id,
    (max(bucket) FILTER (WHERE rn = 1))::date AS as_of,
    max(nav)     FILTER (WHERE rn = 1)        AS last_nav,
    (max(bucket) FILTER (WHERE rn = 2))::date AS prev_date,
    max(nav)     FILTER (WHERE rn = 2)        AS prev_nav
FROM ranked
WHERE rn <= 2
GROUP BY instrument_id
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS nav_latest_mv_pk ON nav_latest_mv (instrument_id);

-- Populate inicial NÃO-concorrente: CONCURRENTLY falha enquanto o MV nunca
-- foi populado. O worker matview_refresh usa CONCURRENTLY a partir daqui.
REFRESH MATERIALIZED VIEW price_latest_mv;
REFRESH MATERIALIZED VIEW nav_latest_mv;
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_price_nav_latest_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Aplicar o DDL no banco principal (ops, manual)**

Aplicar contra o DB principal (em prod, o `public` do Timescale Cloud — o mesmo `DATABASE_URL` que o worker usa), via Tiger/psql como os demais arquivos de `backend/db/ddl/`:

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_price_nav_latest_mv.sql
```

Verificar shape e populate:

```bash
psql "$DATABASE_URL" -c "SELECT ticker, as_of, last_close, prev_close FROM price_latest_mv LIMIT 5;"
psql "$DATABASE_URL" -c "SELECT instrument_id, as_of, last_nav, prev_nav FROM nav_latest_mv LIMIT 5;"
```

Expected: linhas retornadas (MV populado); `prev_*` pode ser NULL para entidades com uma só observação.

- [ ] **Step 6: Commit**

```bash
git add backend/db/ddl/2026-06-21_price_nav_latest_mv.sql backend/tests/test_price_nav_latest_mv_sql.py
git commit -m "feat(matview): add price_latest_mv / nav_latest_mv DDL"
```

---

## Task 2: Worker `matview_refresh`

**Files:**
- Modify: `E:/investintell-datalake-workers/src/db.py` (adicionar `LOCK_MATVIEW_REFRESH`)
- Modify: `E:/investintell-datalake-workers/src/run_worker.py` (registrar `matview_refresh` na mensagem de uso)
- Create: `E:/investintell-datalake-workers/src/workers/matview_refresh.py`
- Test: `E:/investintell-datalake-workers/tests/test_matview_refresh.py`

**Interfaces:**
- Consumes: `connect`, `advisory_lock` de `src/db.py`; os MVs da Task 1.
- Produces: `matview_refresh.run(dsn: str) -> dict` com `{"refreshed": [...]}`.

**Contexto — padrão a espelhar** (`src/workers/risk_metrics.py:1014-1028`):

```python
def _refresh_fund_risk_latest_mv(dsn: str) -> None:
    with connect(dsn, autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY fund_risk_latest_mv")
```

- [ ] **Step 1: Adicionar a constante de advisory lock**

Em `src/db.py`, junto às outras constantes `LOCK_*` (range `900_2xx`), adicionar (valor livre):

```python
LOCK_MATVIEW_REFRESH = 900_210
```

- [ ] **Step 2: Escrever o teste que falha (worker)**

Espelha `tests/test_risk_metrics.py::test_refresh_fund_risk_latest_mv_concurrently_in_fresh_autocommit_conn`: fake connection que captura `autocommit` e os SQLs executados.

```python
# tests/test_matview_refresh.py
import src.workers.matview_refresh as mr


class _FakeCursor:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self._sink.setdefault("sql", []).append(sql)
    def fetchone(self): return (True,)  # pg_try_advisory_lock → got


class _FakeConn:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _FakeCursor(self._sink)


def test_refresh_runs_both_mvs_concurrently_in_autocommit(monkeypatch):
    sink: dict = {}

    def _fake_connect(dsn=None, *, autocommit=False):
        sink["dsn"] = dsn
        sink["autocommit"] = autocommit
        return _FakeConn(sink)

    monkeypatch.setattr(mr, "connect", _fake_connect)
    result = mr.run("postgres://x")

    assert sink["autocommit"] is True  # CONCURRENTLY não roda em bloco de txn
    joined = "\n".join(sink["sql"])
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY price_latest_mv" in joined
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY nav_latest_mv" in joined
    assert result["refreshed"] == ["price_latest_mv", "nav_latest_mv"]
```

- [ ] **Step 3: Rodar o teste e ver falhar**

Run: `cd /e/investintell-datalake-workers && pytest tests/test_matview_refresh.py -q`
Expected: FAIL (`ModuleNotFoundError: src.workers.matview_refresh`).

- [ ] **Step 4: Implementar o worker**

```python
# src/workers/matview_refresh.py
"""Refresca os read-model MVs de preço/NAV do Light no DB principal.

price_latest_mv / nav_latest_mv não têm worker computacional próprio
(eod_prices é populado pelo backfill/warming worker out-of-band;
nav_timeseries pelo instrument_ingestion). Este worker dedicado dá
REFRESH … CONCURRENTLY em ambos num cron, em conexão autocommit
(CONCURRENTLY não roda em bloco de transação) e exige os índices UNIQUE
definidos em backend/db/ddl/2026-06-21_price_nav_latest_mv.sql.
O advisory lock evita refreshes concorrentes do mesmo MV entre execuções.
"""
from __future__ import annotations

from src.db import LOCK_MATVIEW_REFRESH, advisory_lock, connect

_MVS = ["price_latest_mv", "nav_latest_mv"]


def run(dsn: str) -> dict:
    # Lock só serializa este worker contra si mesmo; CONCURRENTLY precisa de
    # autocommit, então cada REFRESH roda em conexão autocommit própria.
    with connect(dsn) as guard:
        with advisory_lock(guard, LOCK_MATVIEW_REFRESH) as got:
            if not got:
                return {"refreshed": [], "skipped": "lock_busy"}
            refreshed: list[str] = []
            with connect(dsn, autocommit=True) as conn:
                for mv in _MVS:
                    with conn.cursor() as cur:
                        cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}")
                    refreshed.append(mv)
            return {"refreshed": refreshed}
```

Nota: os nomes em `_MVS` são literais fixos do próprio código (não input externo) — sem risco de injeção.

- [ ] **Step 5: Registrar o worker no dispatcher**

Em `src/run_worker.py`, incluir `matview_refresh` na string de uso (a lista após `expected …`):

```python
    if not worker:
        sys.exit(
            "WORKER env var not set (expected risk_metrics|characteristics|factor_model"
            "|nport_lookthrough|credit_regime|regime_composite|macro_ingestion"
            "|treasury_ingestion|benchmark_ingest|instrument_ingestion"
            "|sec_13f_ingestion|form345_ingestion|sec_company_tickers_mf|matview_refresh)"
        )
```

(O dispatch em si é dinâmico via `importlib.import_module(f"src.workers.{worker}")`, então criar o módulo já o torna despachável; a edição acima só mantém a mensagem de uso correta.)

- [ ] **Step 6: Rodar o teste e ver passar**

Run: `cd /e/investintell-datalake-workers && pytest tests/test_matview_refresh.py -q`
Expected: PASS.

- [ ] **Step 7: Smoke local contra a DB-mãe (opcional, self-skip)**

Se a DB-mãe local tiver os MVs aplicados:

```bash
WORKER=matview_refresh DATABASE_URL="host=localhost port=5434 dbname=investintell_alloc user=investintell password=investintell" python -m src.run_worker
```

Expected: JSON `{"worker": "matview_refresh", "refreshed": ["price_latest_mv", "nav_latest_mv"]}`.

- [ ] **Step 8: Deploy / cron (ops)**

Provisionar o serviço no Railway (padrão do repo: `WORKER` + `DATABASE_URL` por-serviço; `startCommand = "python -m src.run_worker"`; `cronSchedule`). Cadência alinhada ao update diário de preço/nav (ex.: após `instrument_ingestion`):

```bash
railway up --service matview-refresh
# Railway dashboard: WORKER=matview_refresh, DATABASE_URL=<DSN principal>,
# cronSchedule (ex. "30 7 * * *" — logo após o ingest diário 07:00 UTC).
```

- [ ] **Step 9: Commit**

```bash
git add src/db.py src/run_worker.py src/workers/matview_refresh.py tests/test_matview_refresh.py
git commit -m "feat(matview): add matview_refresh worker for price/nav latest MVs"
```

---

## Task 3: Modelos ORM `PriceLatest` e `NavLatest`

**Files:**
- Create: `backend/app/models/price_latest.py`
- Test: `backend/tests/test_price_latest_models.py`

**Interfaces:**
- Consumes: os MVs da Task 1 (no DB principal).
- Produces: `PriceLatest` / `NavLatest` ORM, conforme seção Interfaces.

**Contexto — padrão a espelhar** (`backend/app/models/fund.py`, `FundRiskLatest`): MV no DB principal mapeado como modelo ORM read-only via `Base`, com `mapped_column` tipado.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_price_latest_models.py
from app.models.price_latest import NavLatest, PriceLatest


def test_price_latest_maps_mv_columns():
    assert PriceLatest.__tablename__ == "price_latest_mv"
    cols = set(PriceLatest.__table__.columns.keys())
    assert {"ticker", "as_of", "last_close", "prev_date", "prev_close"} <= cols
    assert "ticker" in PriceLatest.__table__.primary_key.columns.keys()


def test_nav_latest_maps_mv_columns():
    assert NavLatest.__tablename__ == "nav_latest_mv"
    cols = set(NavLatest.__table__.columns.keys())
    assert {"instrument_id", "as_of", "last_nav", "prev_date", "prev_nav"} <= cols
    assert "instrument_id" in NavLatest.__table__.primary_key.columns.keys()
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_price_latest_models.py -q`
Expected: FAIL (`ModuleNotFoundError: app.models.price_latest`).

- [ ] **Step 3: Implementar os modelos**

```python
# backend/app/models/price_latest.py
"""Modelos ORM read-only sobre os MVs price_latest_mv / nav_latest_mv.

Ambos vivem no DB principal (mesmo banco de eod_prices / nav_timeseries) e são
refrescados pelo worker matview_refresh. Espelham o padrão de FundRiskLatest:
MV mapeado via Base, lido por chave/IN, nunca escrito.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base  # mesmo Base usado por FundRiskLatest


class PriceLatest(Base):
    __tablename__ = "price_latest_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_close: Mapped[float] = mapped_column(Numeric, nullable=False)
    prev_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    prev_close: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class NavLatest(Base):
    __tablename__ = "nav_latest_mv"

    instrument_id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True)
    as_of: Mapped[dt.date] = mapped_column(Date, nullable=False)
    last_nav: Mapped[float] = mapped_column(Numeric, nullable=False)
    prev_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    prev_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)
```

Nota de implementação: confirmar o caminho de import de `Base` usado por `FundRiskLatest` em `backend/app/models/fund.py` (provavelmente `from app.models.base import Base` ou equivalente) e usar o **mesmo** import aqui.

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_price_latest_models.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/price_latest.py tests/test_price_latest_models.py
git commit -m "feat(models): add PriceLatest/NavLatest MV models"
```

---

## Task 4: `select_last_two_closes` lê do MV com fallback, atrás de flag

**Files:**
- Modify: `backend/app/core/config.py` (flag `use_latest_mv_prices`)
- Modify: `backend/app/services/portfolio_crud.py`
- Test: `backend/tests/test_price_latest_mv_reads.py`

**Interfaces:**
- Consumes: `PriceLatest` (Task 3); `settings.use_latest_mv_prices`.
- Produces: `select_last_two_closes(session, tickers, *, use_mv=None)` — mesmo tipo de retorno de hoje.

**Contexto — corpo atual** (`select_last_two_closes` em `backend/app/services/portfolio_crud.py`, inalterada por `38dbdb4`): faz `row_number() OVER (PARTITION BY ticker ORDER BY date DESC)` sobre `EodPrice`, `rn <= 2`, e monta `dict[str, list[tuple[date, float]]]` (mais novo primeiro). **Importante (pós-`38dbdb4`):** não há mais `ensure` no request path; `eod_prices` é populado pelo backfill/warming worker out-of-band. Um ticker pode já existir em `eod_prices` (e passar no gate `select_tickers_with_eod` de `_require_local_trade_tickers`) mas ainda **não** estar no `price_latest_mv` (lag entre o backfill e o `matview_refresh`) — por isso o caminho MV faz **fallback à tabela base** para tickers ausentes do MV. Sem o fallback, um ticker recém-backfillado daria `MissingPriceDataError` até o próximo refresh.

- [ ] **Step 1: Adicionar a flag de settings**

Em `backend/app/core/config.py`, na classe `Settings`, adicionar:

```python
    # DB-first Grupo D: quando True, leituras de preço/NAV usam os
    # *_latest_mv (com fallback à tabela base p/ entidades ainda ausentes).
    use_latest_mv_prices: bool = False
```

- [ ] **Step 2: Escrever os testes que falham (paridade, fallback, flag-off)**

Estilo do repo: stub do `session.execute` por `monkeypatch` (sem DB vivo).

```python
# backend/tests/test_price_latest_mv_reads.py
import datetime as dt

import pytest

from app.services import portfolio_crud

_LAST = dt.date(2026, 6, 18)
_PREV = dt.date(2026, 6, 17)


class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _FakeSession:
    """Roteia execute() por marcador embutido na query stringificada."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query):
        text = str(query)
        self.executed.append(text)
        if "price_latest_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


@pytest.mark.asyncio
async def test_mv_path_reshapes_rows_newest_first():
    # MV row: (ticker, as_of, last_close, prev_date, prev_close)
    session = _FakeSession(mv_rows=[("AAPL", _LAST, 110.0, _PREV, 105.0)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=True)
    assert out == {"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]}


@pytest.mark.asyncio
async def test_mv_path_single_point_has_no_prev():
    session = _FakeSession(mv_rows=[("AAPL", _LAST, 110.0, None, None)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=True)
    assert out == {"AAPL": [(_LAST, 110.0)]}


@pytest.mark.asyncio
async def test_mv_path_falls_back_to_base_for_missing_ticker():
    # MSFT ausente do MV → cai p/ tabela base (legacy rows: ticker, date, close).
    session = _FakeSession(
        mv_rows=[("AAPL", _LAST, 110.0, _PREV, 105.0)],
        legacy_rows=[("MSFT", _LAST, 420.0), ("MSFT", _PREV, 410.0)],
    )
    out = await portfolio_crud.select_last_two_closes(
        session, ["AAPL", "MSFT"], use_mv=True
    )
    assert out["AAPL"] == [(_LAST, 110.0), (_PREV, 105.0)]
    assert out["MSFT"] == [(_LAST, 420.0), (_PREV, 410.0)]
    assert any("eod_prices" in q or "price" in q for q in session.executed)


@pytest.mark.asyncio
async def test_flag_off_uses_legacy_only():
    session = _FakeSession(legacy_rows=[("AAPL", _LAST, 110.0), ("AAPL", _PREV, 105.0)])
    out = await portfolio_crud.select_last_two_closes(session, ["AAPL"], use_mv=False)
    assert out == {"AAPL": [(_LAST, 110.0), (_PREV, 105.0)]}
    assert all("price_latest_mv" not in q for q in session.executed)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_price_latest_mv_reads.py -q`
Expected: FAIL (assinatura sem `use_mv`, e/ou sem caminho MV).

- [ ] **Step 4: Reescrever a função (legado vira helper privado + caminho MV)**

Em `backend/app/services/portfolio_crud.py`, renomear o corpo atual para `_select_last_two_closes_legacy` e introduzir o wrapper:

```python
from app.core.config import get_settings
from app.models.price_latest import PriceLatest
# (EodPrice, func, select já importados no módulo)


async def _select_last_two_closes_legacy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, list[tuple[dt.date, float]]]:
    """The two most recent (date, close) rows per ticker, newest first."""
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


async def select_last_two_closes(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    use_mv: bool | None = None,
) -> dict[str, list[tuple[dt.date, float]]]:
    """Two most recent (date, close) per ticker, newest first.

    DB-first: lê de price_latest_mv quando habilitado; tickers ausentes do MV
    (ex.: recém-backfillados, ainda não capturados pelo matview_refresh) caem
    para a tabela base, então o shape de saída é idêntico ao legado.
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
    if missing:
        closes.update(await _select_last_two_closes_legacy(session, missing))
    return closes
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_price_latest_mv_reads.py -q`
Expected: PASS (4 testes).

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py app/services/portfolio_crud.py tests/test_price_latest_mv_reads.py
git commit -m "feat(portfolio): read last-two closes from price_latest_mv behind flag"
```

---

## Task 5: `select_last_two_navs` lê do MV com fallback, atrás de flag

**Files:**
- Modify: `backend/app/services/portfolio_crud.py`
- Test: `backend/tests/test_nav_latest_mv_reads.py`

**Interfaces:**
- Consumes: `NavLatest` (Task 3); `settings.use_latest_mv_prices` (Task 4); helper existente `_fund_instrument_by_ticker`.
- Produces: `select_last_two_navs(session, tickers, *, use_mv=None)` — mesmo tipo de retorno.

**Contexto — corpo atual** (`backend/app/services/portfolio_crud.py:427-475`): resolve ticker→`instrument_id` via `_fund_instrument_by_ticker` (tickers de classe resolvem p/ a série), faz `row_number()` sobre `FundNav` (`nav_timeseries`), e mapeia de volta a cada ticker. O MV é keyed por `instrument_id`, então a resolução ticker→instrumento permanece; só a leitura interna troca para `NavLatest`, com fallback à base para instrumentos ausentes.

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_nav_latest_mv_reads.py
import datetime as dt
import uuid

import pytest

from app.services import portfolio_crud

_LAST = dt.date(2026, 6, 18)
_PREV = dt.date(2026, 6, 17)
_IID = uuid.uuid4()


class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows


class _FakeSession:
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query):
        text = str(query)
        self.executed.append(text)
        if "nav_latest_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


@pytest.mark.asyncio
async def test_nav_mv_path_reshapes_newest_first(monkeypatch):
    async def _fake_resolve(session, tickers):
        return {"VBIAX": _IID}
    monkeypatch.setattr(portfolio_crud, "_fund_instrument_by_ticker", _fake_resolve)

    # MV row: (instrument_id, as_of, last_nav, prev_date, prev_nav)
    session = _FakeSession(mv_rows=[(_IID, _LAST, 50.0, _PREV, 49.0)])
    out = await portfolio_crud.select_last_two_navs(session, ["VBIAX"], use_mv=True)
    assert out == {"VBIAX": [(_LAST, 50.0), (_PREV, 49.0)]}


@pytest.mark.asyncio
async def test_nav_mv_path_falls_back_for_missing_instrument(monkeypatch):
    async def _fake_resolve(session, tickers):
        return {"VBIAX": _IID}
    monkeypatch.setattr(portfolio_crud, "_fund_instrument_by_ticker", _fake_resolve)

    # MV vazio → cai p/ legado (legacy_rows: instrument_id, nav_date, nav)
    session = _FakeSession(mv_rows=[], legacy_rows=[(_IID, _LAST, 50.0), (_IID, _PREV, 49.0)])
    out = await portfolio_crud.select_last_two_navs(session, ["VBIAX"], use_mv=True)
    assert out == {"VBIAX": [(_LAST, 50.0), (_PREV, 49.0)]}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_nav_latest_mv_reads.py -q`
Expected: FAIL (sem `use_mv` / sem caminho MV).

- [ ] **Step 3: Reescrever a função**

Renomear o corpo atual para `_select_last_two_navs_legacy` e adicionar o wrapper. O wrapper resolve ticker→instrumento uma vez, lê o MV por `instrument_id`, e cai ao legado **apenas** para os tickers cujos instrumentos faltam no MV.

```python
from app.models.price_latest import NavLatest


async def _select_last_two_navs_legacy(
    session: AsyncSession, tickers: Sequence[str]
) -> dict[str, list[tuple[dt.date, float]]]:
    """Corpo atual (window over nav_timeseries) — inalterado, vide §427-475."""
    # ... mover o corpo existente de select_last_two_navs para cá, sem mudanças ...


async def select_last_two_navs(
    session: AsyncSession,
    tickers: Sequence[str],
    *,
    use_mv: bool | None = None,
) -> dict[str, list[tuple[dt.date, float]]]:
    """Two most recent (nav_date, nav) per FUND ticker, newest first.

    Mesmo shape de select_last_two_closes (build_overview consome ambos
    transparentemente). DB-first: lê de nav_latest_mv quando habilitado;
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
    seen_instruments: set[Any] = set()
    for instrument_id, as_of, last_nav, prev_date, prev_nav in rows.all():
        seen_instruments.add(instrument_id)
        series = [(as_of, float(last_nav))]
        if prev_nav is not None and prev_date is not None:
            series.append((prev_date, float(prev_nav)))
        for ticker in tickers_by_instrument[instrument_id]:
            navs[ticker] = list(series)

    missing = [t for t in tickers if t not in navs]
    if missing:
        navs.update(await _select_last_two_navs_legacy(session, missing))
    return navs
```

Nota: ao mover o corpo legado, manter os imports/símbolos que ele já usa (`FundNav`, `_fund_instrument_by_ticker`, `func`, `select`).

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_nav_latest_mv_reads.py -q`
Expected: PASS (2 testes).

- [ ] **Step 5: Commit**

```bash
git add app/services/portfolio_crud.py tests/test_nav_latest_mv_reads.py
git commit -m "feat(portfolio): read last-two navs from nav_latest_mv behind flag"
```

---

## Task 6: Verificação de paridade e regressão (suíte completa)

**Files:**
- Modify (se necessário): `backend/app/services/portfolio_crud.py` (docstring/comentário de comportamento)
- Test: rodar suítes existentes de overview e lookthrough

**Interfaces:**
- Consumes: tudo acima.

**Contexto:** `get_portfolio_overview` e `get_portfolio_lookthrough` (em `backend/app/api/routes/portfolios.py`, pós-`38dbdb4` — overview já **sem** o parâmetro `client`) ambos chamam as duas funções reescritas — logo a troca de fonte de preço cobre os DOIS endpoints sem tarefa separada (o spec: lookthrough "sem mudança estrutural além da fonte de preço"). Com a flag **desligada** (default), o comportamento é idêntico ao atual.

- [ ] **Step 1: Garantir que nenhum caller quebrou (flag default off)**

Run: `cd backend && pytest tests/test_portfolios_overview.py tests/test_lookthrough.py -q`
Expected: PASS — sem mudança, pois `use_latest_mv_prices` é `False` por default e a assinatura nova é compatível (novo kwarg opcional).

- [ ] **Step 2: Localizar todos os callers das duas funções**

Run: `cd backend && grep -rn "select_last_two_closes\|select_last_two_navs" app tests`
Expected: confirmar que todos os callers de produção (overview, lookthrough) não passam `use_mv` (herdam a flag) e toleram a assinatura nova. Anotar quaisquer outros callers encontrados.

- [ ] **Step 3: Teste de paridade com a flag ligada (rota overview)**

Adicionar ao `tests/test_price_latest_mv_reads.py` um teste de rota que liga a flag e injeta linhas de MV equivalentes às do caminho legado, afirmando que o payload de `/portfolios/{id}/overview` é igual nos dois modos (mesma aritmética P&L). Reusar os stubs de `tests/test_portfolios_overview.py` (que já stubam `select_last_two_closes`), agora exercitando a função real com `_FakeSession`.

```python
@pytest.mark.asyncio
async def test_overview_payload_parity_mv_vs_legacy(monkeypatch):
    # Mesmos dados em ambas as fontes ⇒ payload idêntico.
    legacy = await portfolio_crud.select_last_two_closes(
        _FakeSession(legacy_rows=[("AAPL", _LAST, 110.0), ("AAPL", _PREV, 105.0)]),
        ["AAPL"], use_mv=False,
    )
    mv = await portfolio_crud.select_last_two_closes(
        _FakeSession(mv_rows=[("AAPL", _LAST, 110.0, _PREV, 105.0)]),
        ["AAPL"], use_mv=True,
    )
    assert legacy == mv
```

Run: `cd backend && pytest tests/test_price_latest_mv_reads.py -q`
Expected: PASS.

- [ ] **Step 4: Documentar o comportamento de frescor (lag do refresh)**

No docstring de `select_last_two_closes`, registrar a diferença conhecida e aceita: como `eod_prices` é populado pelo backfill/warming worker out-of-band e o MV é refrescado por cron próprio (`matview_refresh`), há lag entre os dois — um preço recém-backfillado pode aparecer no MV só após o próximo refresh; tickers ainda ausentes do MV usam o fallback à base (sem regressão funcional). Para um overview EOD isso é aceitável; a flag de dual-read permite validar em staging antes de virar o default.

- [ ] **Step 5: Suíte completa do backend**

Run: `cd backend && pytest -q`
Expected: verde (sem novas falhas; flag off por default).

- [ ] **Step 6: Commit**

```bash
git add app/services/portfolio_crud.py tests/test_price_latest_mv_reads.py
git commit -m "test(portfolio): parity + freshness docs for MV-backed price reads"
```

---

## Estratégia de rollout (pós-merge)

Seguindo a transição do spec (§12): com tudo mergeado e a flag `use_latest_mv_prices=False`, nada muda em produção. Para ativar: aplicar o DDL (Task 1, Step 5), provisionar o worker `matview_refresh` (Task 2, Step 8), confirmar MVs populados e frescos, então ligar `use_latest_mv_prices=True` em staging, comparar payloads de overview/lookthrough contra o caminho legado, e só então virar o default em produção.

---

## Self-Review

**Cobertura do escopo (Fundação + Grupo D do spec §9 e §14.1):**
- `price_latest_mv` (DISTINCT/last-two por ticker) → Task 1 + Task 4. ✓
- `nav_latest_mv` (last-two por instrument_id) → Task 1 + Task 5. ✓
- `overview` lê preço do latest_mv (continua on-demand na aritmética) → Task 4/5 (funções compartilhadas) + Task 6. ✓
- `lookthrough` lê preço do latest_mv, sem mudança estrutural → coberto pelas mesmas funções compartilhadas (Task 4/5), verificado em Task 6. ✓
- Padrão de fundação (worker → MV → REFRESH CONCURRENTLY fora do lock, autocommit, índice UNIQUE) → Task 1 (DDL/índices) + Task 2 (worker). ✓
- Frescor exposto ao frontend (coluna `as_of` no MV, espelhando `nav_staleness`) → coluna `as_of` propagada via `closes[0][0]` para `PositionOverview.as_of`/`OverviewAggregates.as_of` existentes. ✓
- Decisão do dono (worker de refresh dedicado, não acoplado a `instrument_ingestion`) → Task 2. ✓

**Varredura de placeholders:** sem "TBD"/"etc."; todo step de código traz o código real. As duas referências a "mover o corpo existente" (Task 4/5) apontam para linhas exatas do arquivo atual e preservam o corpo verbatim — não é hand-wave, é um move-refactor.

**Consistência de tipos:** shape de MV `(entity, as_of, last_*, prev_date, prev_*)` é idêntico entre DDL (Task 1), modelos ORM (Task 3) e desempacotamento nas leituras (Task 4/5). Retorno `dict[str, list[tuple[date, float]]]` newest-first preservado em todos os caminhos (MV, fallback, legado). `LOCK_MATVIEW_REFRESH = 900_210` definido na Task 2 e referenciado só lá.

**Risco conhecido (documentado, não placeholder):** lag de frescor entre o backfill/warming worker (que popula `eod_prices`/`nav_timeseries`) e o `matview_refresh` (que atualiza os `*_latest_mv`) — tratado por fallback à base (ausência) + flag de dual-read (validação) + doc em Task 6 Step 4.

**Nota de valor (pós-`38dbdb4`):** com o histórico já db-first e a leitura de preço sendo barata, o ganho marginal dos `*_latest_mv` vem sobretudo de evitar o `row_number()` sobre o CAGG a cada request (achatando "duas últimas observações" numa linha indexada por entidade) e de estabelecer o padrão de fundação (worker→MV→`REFRESH CONCURRENTLY`) que os Grupos A/B reutilizam. Os MVs lendo dos CAGGs canônicos mantêm a fonte única db-first.
