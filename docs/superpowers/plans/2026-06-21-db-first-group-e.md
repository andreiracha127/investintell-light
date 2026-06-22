# DB-First — Grupo E (Aceleração de ferramentas interativas) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Acelerar as ferramentas interativas (`statistics/*`, `backtest/walk-forward`, `correlation-regime`, `monte-carlo/*`) sem alterar números: (E1) pré-computar daily returns de stocks e expor um helper de aligned-returns + cache de covariância Ledoit-Wolf; (E2) um novo módulo de cache de resultado por hash em Redis (fail-open, namespace próprio) decorando os serviços determinísticos; (E3) criar a tabela `optimize_jobs` e enfileirar walk-forward grande / monte-carlo grande como jobs assíncronos (202 + polling), servindo o resultado via E2.

**Architecture:** Aditivo e atrás de flags — cada caminho acelerado preserva a correção (spec §12). E1 vive em dois lugares: o daily-returns de stock é um **worker Python** em `investintell-datalake-workers` que materializa `stock_daily_returns` (TimescaleDB **não** permite window functions como `lag()` em continuous aggregates, logo um cagg de retorno é inexpressível — ver E1 §decisão), e o helper de aligned-returns + cache LW vive no backend (`app/analytics/`). E2 é um módulo novo `app/core/result_cache.py` que reusa o cliente Redis e o fail-open de `app/core/cache.py` mas com namespace `result:` próprio (NÃO é o middleware de catálogo); decorator wrappeia os serviços determinísticos; entradas de portfólio entram na chave por hash de conteúdo+versão. E3 cria o modelo ORM `optimize_jobs` (a spec diz "reusa", mas a tabela **não existe** — ver E3 §divergência), um enqueue path (202 + job id) e `GET /jobs/{id}` para polling.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy 2.0 async + asyncpg (backend), pandas/numpy (apenas no helper E1, fora do request path), sklearn LedoitWolf, Alembic (migration da tabela `optimize_jobs`), Redis (`redis.asyncio`), psycopg3 (worker), pytest (`asyncio_mode = "auto"`), Railway cron.

## Baseline — branch `feat/db-first-analytics` @ `f6e2c27` (Fundação + Grupo D feitos)

Este plano assume Fundação + Grupo D já implementados nesta branch/worktree:
- `price_latest_mv` / `nav_latest_mv` (DDL em `backend/db/ddl/2026-06-21_price_nav_latest_mv.sql`), modelos `PriceLatest`/`NavLatest` (`backend/app/models/price_latest.py`), worker `matview_refresh` no repo de workers, flag `settings.use_latest_mv_prices`.
- O histórico de mercado já é DB-first desde `38dbdb4`: `cagg_eod_daily` (sobre `eod_prices`) e `cagg_nav_daily` (sobre `nav_timeseries`, com `return_1d`) existem com policy de auto-refresh. DDL do DB principal vive em `backend/db/ddl/`.
- O cache de catálogo (`app/core/cache.py`) é HTTP-middleware sobre rotas GET de catálogo público (`/funds`, `/macro/regime`, `/stocks/overview`). Grupo E **não** o toca: cria um módulo separado.

## Global Constraints

- Branch base `feat/db-first-analytics` @ `f6e2c27`; worktree `E:\investintell-light\.claude\worktrees\db-first-analytics`. Edições de backend ocorrem aqui.
- **Edições no repo de workers** (`investintell-datalake-workers`) ocorrem num **worktree LIMPO a partir de `main`** (regra permanente do dono — o working tree compartilhado tem trabalho de outras sessões). Caminho de referência: `E:/investintell-datalake-workers` (verificar que o checkout está limpo / criar worktree próprio antes de editar).
- DDL do **DB principal** é versionado em `backend/db/ddl/YYYY-MM-DD_<name>.sql` (aplicado via Tiger/psql — **passo de OPS MANUAL**), com um teste de asserção-de-string `backend/tests/test_<name>_sql.py` (estilo `test_dynamic_catalog_sql.py`).
- **Tabelas/MVs que os workers POSSUEM** (ex.: `stock_daily_returns` do E1) vivem em `investintell-datalake-workers/schemas/<worker>.sql` (não em `backend/db/ddl/`) — convenção do repo de workers (ver `schemas/risk_metrics`-pattern).
- Worker dispatch: `WORKER=<nome>` em `investintell-datalake-workers/src/run_worker.py` → `importlib.import_module(f"src.workers.{worker}")`; contrato `run(dsn: str, ...) -> dict | None`.
- Advisory locks ficam no range `900_2xx` em `investintell-datalake-workers/src/db.py`; cada worker tem o seu (sem colidir). Em uso hoje: `900_201..206`, `900_208(?)`, `900_305/306/308/309`, `900_320/324/331/332`. **Novo livre para E1: `900_211`** (a Fundação/Grupo D reservou `900_210` para `matview_refresh`).
- **Transição (spec §12)**: cada caminho acelerado preserva correção; cache e jobs são **aditivos atrás de flags**. O cache é **fail-open** — uma falha do Redis NUNCA derruba um request.
- **Nada de `pandas`/`numpy` novo no request path.** O helper E1 (aligned-returns / LW-cov) já é chamado fora do request path crítico (optimizer/backtest/correlation-regime já usam pandas no serviço — E1 só centraliza e cacheia, sem mover pandas para a camada de rota).
- Backend tests: `cd backend && pytest`; `asyncio_mode = "auto"`; I/O stubado por `monkeypatch` no nível de função (sem DB vivo). Workers tests: `pytest tests/test_<x>.py -s -v`; sem `conftest`; seams de I/O mockados por `monkeypatch`/fake connection; testes que precisam de DB fazem self-skip.
- Scale contract (project-wide): frações decimais (0.05 = 5%), nunca 0-100.
- Execução posterior por subagent-driven-development; TODOS os subagentes Opus 4.8.

## Duas divergências da spec (sinalizadas com destaque)

1. **`optimize_jobs` deve ser CRIADA, não reusada.** A spec (§10 E3, §11) diz "reusa o modelo `optimize_jobs`" e o inventário (§4) lista `optimize_jobs (light)` como tabela existente. **Auditoria do código nesta branch: o modelo ORM e a tabela NÃO existem** (não há `app/models/optimize_jobs.py` nem migration). O padrão mais próximo é `RebalancePolicy` (`backend/app/models/rebalance.py`, com `last_evaluated_at`). **Decisão deste plano: criar** a tabela + ORM + migration Alembic (Task E3.1). Se a tabela existir em produção mas não no schema versionado, a migration usa `IF NOT EXISTS`/checagem de existência (Task E3.1, Step 3).
2. **Mecanismo do `daily_returns` de stock = WORKER, não cagg.** A spec (§10 E1, §11) diz "Worker/cagg `daily_returns`". O retorno diário precisa de `lag(adj_close)` (ou de uma subtração entre dois buckets ordenados) — **TimescaleDB proíbe window functions e self-joins em continuous aggregates**, logo um cagg de `return_1d` é inexpressível. **Decisão deste plano: worker Python** `stock_daily_returns` que materializa uma tabela base (espelhando o fato de `nav_timeseries.return_1d` já existir para fundos via worker, não via cagg). Justificativa registrada na Task E1.1.

---

## File Structure

**Repo backend — `E:\investintell-light\.claude\worktrees\db-first-analytics\backend`:**
- Create: `app/models/stock_daily_return.py` — ORM read-only `StockDailyReturn` (mapeia a tabela `stock_daily_returns` que o worker possui).
- Create: `app/analytics/aligned.py` — helper compartilhado `load_aligned_return_matrix` + cache LW (`ledoit_wolf_cov_cached`), keyed por `{asset_set hash, window}`.
- Create: `app/core/result_cache.py` — cache de resultado por hash (Redis fail-open, namespace `result:`), `result_cache_key`, `portfolio_version_hash`, decorator `cached_result`.
- Create: `app/models/optimize_jobs.py` — ORM `OptimizeJob`.
- Create: `app/schemas/jobs.py` — schemas `JobEnqueuedResponse`, `JobStatusResponse`.
- Create: `app/services/jobs.py` — enqueue/poll/execução de jobs (`enqueue_job`, `get_job`, `_run_job_body`, `params_hash`, `JOB_KIND_*`, thresholds).
- Create: `app/api/routes/jobs.py` — `GET /jobs/{job_id}`.
- Modify: `app/core/config.py` — flags `use_result_cache`, `result_cache_ttl_seconds`, `use_async_jobs`, `async_job_threshold_n_simulations`, `async_job_threshold_n_splits`.
- Modify: `app/services/statistics.py` — envolver `run_scenario`/`run_beta`/`run_rolling_correlation`/`run_stock_correlation` com `cached_result`.
- Modify: `app/services/monte_carlo.py` — cache só com `seed`; enqueue quando `n_simulations` >= threshold e `use_async_jobs`.
- Modify: `app/services/backtest.py` — cache; enqueue quando `n_splits` >= threshold e `use_async_jobs`.
- Modify: `app/services/correlation_regime.py` — cache.
- Modify: `app/api/routes/monte_carlo.py` / `app/api/routes/backtest.py` — devolver 202 + job id no caminho assíncrono.
- Modify: `app/main.py` (ou onde os routers são registrados) — registrar `jobs.router`.
- Migration: `backend/alembic/versions/<rev>_add_optimize_jobs.py`.
- Tests: `tests/test_stock_daily_return_model.py`, `tests/test_aligned_helper.py`, `tests/test_result_cache.py`, `tests/test_optimize_jobs_model.py`, `tests/test_jobs_service.py`, `tests/test_jobs_routes.py`, `tests/test_statistics_caching.py`, `tests/test_monte_carlo_caching.py`.

**Repo workers — worktree LIMPO de `investintell-datalake-workers` off main:**
- Create: `schemas/stock_daily_returns.sql` — DDL da tabela base (worker-owned) + hypertable + índice.
- Create: `src/workers/stock_daily_returns.py` — worker que computa `return_1d` por ticker e faz upsert.
- Modify: `src/db.py` — `LOCK_STOCK_DAILY_RETURNS = 900_211`.
- Modify: `src/run_worker.py` — registrar `stock_daily_returns` na mensagem de uso.
- Test: `tests/test_stock_daily_returns.py`.

**Por que estas fronteiras:** E1 separa a **materialização** (worker, repo de workers, schema worker-owned) da **leitura/helper** (backend, `app/analytics/`). E2 é um módulo de cache isolado para não acoplar ao middleware de catálogo. E3 isola jobs em service + rota próprios, reusando E2 para servir resultados. Cada task termina com um deliverable testável de forma independente.

---

## Interfaces (contratos entre tasks)

- **E1 worker:** `stock_daily_returns(ticker text, date date, return_1d double precision, adj_close double precision)`, PK `(ticker, date)`; `LOCK_STOCK_DAILY_RETURNS: int = 900_211`; `stock_daily_returns.run(dsn: str) -> dict` → `{"tickers": int, "upserted": int}`.
- **E1 backend ORM:** `StockDailyReturn` — `.ticker: str`, `.date: dt.date`, `.return_1d: float | None`, `.adj_close: float | None`; `__tablename__ = "stock_daily_returns"`.
- **E1 helper:** `app.analytics.aligned.asset_set_key(labels: Sequence[str], window_days: int | None) -> str` (sha256 hex). `app.analytics.aligned.ledoit_wolf_cov_cached(returns: np.ndarray, *, cache_key: str | None = None) -> np.ndarray` (idêntico a `engine.sigma_ledoit_wolf`, com cache in-process LRU por `cache_key`). `app.analytics.aligned.clear_lw_cache() -> None` (para testes).
- **E2:** `app.core.result_cache.result_cache: ResultCache` (instância única). `ResultCache.get(key: str) -> bytes | None` (async, fail-open). `ResultCache.set(key: str, body: bytes, ttl: float) -> None` (async, fail-open). `ResultCache.active_backend() -> str` (async). `result_cache_key(kind: str, payload: BaseModel) -> str` → `f"result:{_RESULT_CACHE_VERSION}:{kind}:{sha256(canonical_json)}"`. `portfolio_version_hash(portfolio: Portfolio) -> str`. `cached_result(kind: str, *, ttl_setting: str = "result_cache_ttl_seconds", cacheable: Callable[..., bool] | None = None)` — decorator de serviço async que retorna um Pydantic model.
- **E3 ORM:** `OptimizeJob` — `.id: uuid.UUID`, `.portfolio_id: int | None`, `.kind: str`, `.params_hash: str`, `.status: str` (pending/running/succeeded/failed), `.result: dict | None` (jsonb), `.error: str | None`, `.created_at`, `.updated_at`; `__tablename__ = "optimize_jobs"`.
- **E3 service:** `JOB_KIND_WALK_FORWARD = "walk_forward"`, `JOB_KIND_PORTFOLIO_MC = "portfolio_mc"`. `params_hash(kind: str, payload: BaseModel) -> str`. `enqueue_job(session, *, kind, params_hash, portfolio_id, runner) -> OptimizeJob`. `get_job(session, job_id: uuid.UUID) -> OptimizeJob | None`. `should_run_async(*, n_simulations: int | None = None, n_splits: int | None = None) -> bool`.
- **E3 schemas:** `JobEnqueuedResponse(job_id: uuid.UUID, status: str, kind: str)`; `JobStatusResponse(job_id, status, kind, result: dict | None, error: str | None)`.
- **Settings:** `use_result_cache: bool = False`, `result_cache_ttl_seconds: int = 3600`, `use_async_jobs: bool = False`, `async_job_threshold_n_simulations: int = 20000`, `async_job_threshold_n_splits: int = 12`.

---

# E1 — Ingredientes pré-computados

## Task E1.1: Worker `stock_daily_returns` (materializa daily returns de stocks)

**Files (repo de workers, worktree LIMPO off main):**
- Create: `schemas/stock_daily_returns.sql`
- Create: `src/workers/stock_daily_returns.py`
- Modify: `src/db.py` (constante `LOCK_STOCK_DAILY_RETURNS`)
- Modify: `src/run_worker.py` (mensagem de uso)
- Test: `tests/test_stock_daily_returns.py`

**Interfaces:**
- Consumes: `connect`, `advisory_lock`, `resolve_dsn` de `src/db.py`; `eod_prices` no DB principal.
- Produces: tabela `stock_daily_returns` + `stock_daily_returns.run(dsn) -> {"tickers": int, "upserted": int}`.

**Decisão de mecanismo (worker, não cagg) — registrar no docstring do worker:** o retorno diário é `return_1d[t] = adj_close[t]/adj_close[t-1] - 1`, que exige `lag()` (window function) ou um self-join ordenado. TimescaleDB **proíbe window functions e self-joins em continuous aggregates** — logo não é expressível como cagg sobre `eod_prices` (diferente de `cagg_eod_daily`, que só usa agregados simples). Por isso o daily-return de stock vira um **worker Python que upserta uma tabela base** `stock_daily_returns`, espelhando o fato de `nav_timeseries.return_1d` já existir para fundos (materializado por worker de ingestão, não por cagg). A tabela é worker-owned → DDL em `schemas/` do repo de workers (convenção do repo), não em `backend/db/ddl/`.

- [ ] **Step 1: Escrever a DDL da tabela base**

```sql
-- schemas/stock_daily_returns.sql
-- Worker-owned base table: daily simple returns per stock ticker.
-- TimescaleDB forbids window functions (lag) in continuous aggregates, so the
-- per-day return cannot be a cagg over eod_prices; this is materialized by the
-- stock_daily_returns worker (mirrors nav_timeseries.return_1d for funds).
CREATE TABLE IF NOT EXISTS stock_daily_returns (
    ticker      text             NOT NULL,
    date        date             NOT NULL,
    return_1d   double precision,
    adj_close   double precision,
    PRIMARY KEY (ticker, date)
);

-- Cross-sectional ("all tickers on date X") + per-ticker scans both benefit.
CREATE INDEX IF NOT EXISTS stock_daily_returns_date_idx
    ON stock_daily_returns (date);
```

- [ ] **Step 2: Adicionar a constante de advisory lock**

Em `src/db.py`, junto às outras constantes `LOCK_*` (range `900_2xx`; `900_210` reservado p/ `matview_refresh` na Fundação):

```python
LOCK_STOCK_DAILY_RETURNS = 900_211
```

- [ ] **Step 3: Escrever o teste que falha (worker)**

Estilo de `tests/test_risk_metrics.py` — fake connection que captura autocommit/SQL e devolve linhas de preço fixas. O teste valida que `return_1d` é a variação relativa entre adj_closes consecutivos por ticker (primeiro ponto → NULL).

```python
# tests/test_stock_daily_returns.py
import src.workers.stock_daily_returns as sdr


class _FakeCursor:
    def __init__(self, sink, rows):
        self._sink = sink
        self._rows = rows
        self._last = None

    def __enter__(self): return self
    def __exit__(self, *a): return False

    def execute(self, sql, params=None):
        self._sink.setdefault("sql", []).append(sql)
        self._last = sql

    def executemany(self, sql, rows):
        self._sink.setdefault("upserts", []).extend(list(rows))

    def fetchone(self):
        return (True,)  # pg_try_advisory_lock → got

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, sink, rows):
        self._sink = sink
        self._rows = rows

    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _FakeCursor(self._sink, self._rows)
    def commit(self): self._sink["committed"] = True


def test_computes_return_1d_per_ticker_first_point_null(monkeypatch):
    import datetime as dt
    sink: dict = {}
    rows = [
        ("AAPL", dt.date(2026, 6, 16), 100.0),
        ("AAPL", dt.date(2026, 6, 17), 110.0),
        ("AAPL", dt.date(2026, 6, 18), 99.0),
    ]

    def _fake_connect(dsn=None, *, autocommit=False):
        sink["autocommit"] = autocommit
        return _FakeConn(sink, rows)

    monkeypatch.setattr(sdr, "connect", _fake_connect)
    result = sdr.run("postgres://x")

    upserts = {(t, d): r for (t, d, r, _ac) in sink["upserts"]}
    assert upserts[("AAPL", dt.date(2026, 6, 16))] is None
    assert abs(upserts[("AAPL", dt.date(2026, 6, 17))] - 0.10) < 1e-9
    assert abs(upserts[("AAPL", dt.date(2026, 6, 18))] - (99.0 / 110.0 - 1.0)) < 1e-9
    assert result["tickers"] == 1
    assert result["upserted"] == 3
```

- [ ] **Step 4: Rodar o teste e ver falhar**

Run: `cd /e/investintell-datalake-workers && pytest tests/test_stock_daily_returns.py -q`
Expected: FAIL (`ModuleNotFoundError: src.workers.stock_daily_returns`).

- [ ] **Step 5: Implementar o worker**

```python
# src/workers/stock_daily_returns.py
"""Materializa daily simple returns por ticker em stock_daily_returns.

Por que worker e não continuous aggregate: return_1d = adj_close[t]/adj_close[t-1]-1
exige lag()/self-join, e o TimescaleDB proíbe window functions e self-joins em
continuous aggregates. Por isso (igual a nav_timeseries.return_1d nos fundos) o
retorno de stock é computado em Python e upsertado numa tabela base worker-owned
(schemas/stock_daily_returns.sql). Idempotente (ON CONFLICT DO UPDATE). O refresh
roda dentro de um advisory lock próprio (900_211) para não correr contra si mesmo.
"""
from __future__ import annotations

from src.db import LOCK_STOCK_DAILY_RETURNS, advisory_lock, connect

_SELECT = """
    SELECT ticker, date, adj_close
    FROM eod_prices
    WHERE adj_close IS NOT NULL AND adj_close > 0
    ORDER BY ticker, date
"""

_UPSERT = """
    INSERT INTO stock_daily_returns (ticker, date, return_1d, adj_close)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (ticker, date)
    DO UPDATE SET return_1d = EXCLUDED.return_1d, adj_close = EXCLUDED.adj_close
"""


def run(dsn: str) -> dict:
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_STOCK_DAILY_RETURNS) as got:
            if not got:
                return {"tickers": 0, "upserted": 0, "skipped": "lock_busy"}
            with conn.cursor() as cur:
                cur.execute(_SELECT)
                price_rows = cur.fetchall()

            payload: list[tuple] = []
            tickers: set[str] = set()
            prev_ticker: str | None = None
            prev_close: float | None = None
            for ticker, date, adj_close in price_rows:
                tickers.add(ticker)
                close = float(adj_close)
                if ticker != prev_ticker:
                    ret = None  # first observation per ticker has no return
                else:
                    ret = close / prev_close - 1.0 if prev_close else None
                payload.append((ticker, date, ret, close))
                prev_ticker, prev_close = ticker, close

            if payload:
                with conn.cursor() as cur:
                    cur.executemany(_UPSERT, payload)
                conn.commit()
            return {"tickers": len(tickers), "upserted": len(payload)}
```

Nota: o SELECT é literal fixo (sem input externo) — sem risco de injeção. O ordering `ORDER BY ticker, date` garante o varrer sequencial por ticker.

- [ ] **Step 6: Registrar o worker no dispatcher**

Em `src/run_worker.py`, incluir `stock_daily_returns` na string de uso:

```python
    if not worker:
        sys.exit(
            "WORKER env var not set (expected risk_metrics|characteristics|factor_model"
            "|nport_lookthrough|credit_regime|regime_composite|macro_ingestion"
            "|treasury_ingestion|benchmark_ingest|instrument_ingestion"
            "|sec_13f_ingestion|form345_ingestion|sec_company_tickers_mf|stock_daily_returns)"
        )
```

- [ ] **Step 7: Rodar o teste e ver passar**

Run: `cd /e/investintell-datalake-workers && pytest tests/test_stock_daily_returns.py -q`
Expected: PASS.

- [ ] **Step 8: Aplicar a DDL + deploy (OPS, manual)**

```bash
psql "$DATABASE_URL" -f schemas/stock_daily_returns.sql
WORKER=stock_daily_returns DATABASE_URL="<DSN principal>" python -m src.run_worker   # smoke
# Railway: novo serviço WORKER=stock_daily_returns, DATABASE_URL=<DSN principal>,
# startCommand="python -m src.run_worker", cronSchedule (ex. "45 7 * * *",
# após instrument/backfill diário). railway up --service stock-daily-returns
```

- [ ] **Step 9: Commit**

```bash
git add schemas/stock_daily_returns.sql src/db.py src/run_worker.py src/workers/stock_daily_returns.py tests/test_stock_daily_returns.py
git commit -m "feat(worker): add stock_daily_returns worker (worker, not cagg — lag() forbidden in caggs)"
```

---

## Task E1.2: Modelo ORM `StockDailyReturn`

**Files (backend):**
- Create: `backend/app/models/stock_daily_return.py`
- Test: `backend/tests/test_stock_daily_return_model.py`

**Interfaces:**
- Consumes: a tabela `stock_daily_returns` (E1.1), no DB principal.
- Produces: `StockDailyReturn` ORM (read-only) — `.ticker`, `.date`, `.return_1d`, `.adj_close`.

**Contexto — padrão a espelhar:** `backend/app/models/eod_price.py` (PK composta `(ticker, date)`, mapeada via `Base`).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_stock_daily_return_model.py
from app.models.stock_daily_return import StockDailyReturn


def test_stock_daily_return_maps_table():
    assert StockDailyReturn.__tablename__ == "stock_daily_returns"
    cols = set(StockDailyReturn.__table__.columns.keys())
    assert {"ticker", "date", "return_1d", "adj_close"} <= cols
    pk = set(StockDailyReturn.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "date"}
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_stock_daily_return_model.py -q`
Expected: FAIL (`ModuleNotFoundError: app.models.stock_daily_return`).

- [ ] **Step 3: Implementar o modelo**

```python
# backend/app/models/stock_daily_return.py
"""Modelo ORM read-only sobre a tabela worker-owned stock_daily_returns.

Materializada pelo worker stock_daily_returns (repo investintell-datalake-workers)
porque o retorno diário (lag(adj_close)) não é expressível em continuous aggregate.
Lido pelo helper de aligned-returns (app.analytics.aligned); nunca escrito aqui.
"""
from __future__ import annotations

import datetime as dt

from sqlalchemy import Date, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockDailyReturn(Base):
    __tablename__ = "stock_daily_returns"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    date: Mapped[dt.date] = mapped_column(Date, primary_key=True)
    return_1d: Mapped[float | None] = mapped_column(Float, nullable=True)
    adj_close: Mapped[float | None] = mapped_column(Float, nullable=True)
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_stock_daily_return_model.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/stock_daily_return.py tests/test_stock_daily_return_model.py
git commit -m "feat(models): add StockDailyReturn ORM over stock_daily_returns"
```

---

## Task E1.3: Helper de aligned-returns + cache de covariância Ledoit-Wolf

**Files (backend):**
- Create: `backend/app/analytics/aligned.py`
- Test: `backend/tests/test_aligned_helper.py`

**Interfaces:**
- Consumes: `app.analytics.returns.align_returns` (já existente, `backend/app/analytics/returns.py:64-79`); `app.optimizer.engine.sigma_ledoit_wolf` (paridade).
- Produces: `asset_set_key`, `ledoit_wolf_cov_cached`, `clear_lw_cache` (ver Interfaces).

**Decisão de cache (in-process, não Redis):** a covariância LW é uma transformação **pura** de uma matriz numpy (não envolve I/O nem o portfólio do usuário) e é reusada dentro do mesmo processo entre objetivos do optimizer/backtest. Um cache **in-process LRU** keyed por `{asset_set hash, window}` evita o recompute do LW sem a serialização/round-trip do Redis. (E2, por contraste, cacheia **respostas de endpoint** — essas sim vão para o Redis compartilhado.) O cache é por-processo e some no restart — aceitável porque é só um acelerador determinístico.

**Contexto — corpo de `sigma_ledoit_wolf` (`backend/app/optimizer/engine.py:81-101`):** anualiza `LedoitWolf().fit(returns).covariance_ * 252` e simetriza. O helper cacheado **chama essa função** (não reimplementa), garantindo paridade exata.

- [ ] **Step 1: Escrever os testes que falham (paridade + cache hit + invalidação por key)**

```python
# backend/tests/test_aligned_helper.py
import numpy as np
import pandas as pd

from app.analytics import aligned
from app.optimizer.engine import sigma_ledoit_wolf


def test_asset_set_key_is_order_invariant_and_window_sensitive():
    k1 = aligned.asset_set_key(["AAPL", "MSFT"], 252)
    k2 = aligned.asset_set_key(["MSFT", "AAPL"], 252)
    k3 = aligned.asset_set_key(["AAPL", "MSFT"], 126)
    assert k1 == k2          # order-invariant
    assert k1 != k3          # window changes the key
    assert len(k1) == 64     # sha256 hex


def test_lw_cov_matches_engine_sigma_ledoit_wolf():
    rng = np.random.default_rng(0)
    returns = rng.normal(0, 0.01, size=(300, 4))
    expected = sigma_ledoit_wolf(returns)
    got = aligned.ledoit_wolf_cov_cached(returns)
    assert np.allclose(got, expected, atol=1e-12)


def test_lw_cov_cache_returns_same_object_for_same_key():
    aligned.clear_lw_cache()
    rng = np.random.default_rng(1)
    returns = rng.normal(0, 0.01, size=(300, 3))
    key = aligned.asset_set_key(["A", "B", "C"], 252)
    first = aligned.ledoit_wolf_cov_cached(returns, cache_key=key)
    # A second call with the SAME key must not recompute — returns cached array.
    second = aligned.ledoit_wolf_cov_cached(
        np.zeros_like(returns), cache_key=key  # different data, same key
    )
    assert second is first


def test_align_return_matrix_inner_joins_on_common_dates():
    idx_a = pd.to_datetime(["2026-06-15", "2026-06-16", "2026-06-17"])
    idx_b = pd.to_datetime(["2026-06-16", "2026-06-17", "2026-06-18"])
    a = pd.Series([0.01, 0.02, 0.03], index=idx_a, name="A")
    b = pd.Series([0.04, 0.05, 0.06], index=idx_b, name="B")
    frame = aligned.align_return_matrix({"A": a, "B": b})
    assert list(frame.columns) == ["A", "B"]
    assert len(frame) == 2  # only 06-16 and 06-17 are common
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_aligned_helper.py -q`
Expected: FAIL (`ModuleNotFoundError: app.analytics.aligned`).

- [ ] **Step 3: Implementar o helper**

```python
# backend/app/analytics/aligned.py
"""Aligned-returns + cached Ledoit-Wolf covariance (E1 ingredient).

Centraliza dois ingredientes reusados por Grupos C/E e pelo optimizer:
  * align_return_matrix — inner-join de séries de retorno num frame T×N (NaN-drop),
    apoiado em app.analytics.returns.align_returns para o caso de 2 séries.
  * ledoit_wolf_cov_cached — covariância LW anualizada IDÊNTICA a
    engine.sigma_ledoit_wolf, com cache in-process keyed por {asset_set, window}.

O cache LW é por-processo (functools, não Redis): a covariância é uma função pura
da matriz de retornos, sem I/O nem dado de usuário — então não precisa do Redis
compartilhado (E2 cacheia respostas de endpoint, este cacheia o ingrediente).
"""
from __future__ import annotations

import hashlib
from collections import OrderedDict
from collections.abc import Mapping, Sequence

import numpy as np
import pandas as pd

from app.optimizer.engine import sigma_ledoit_wolf

_LW_CACHE_MAX = 256
_lw_cache: "OrderedDict[str, np.ndarray]" = OrderedDict()


def asset_set_key(labels: Sequence[str], window_days: int | None) -> str:
    """Deterministic order-invariant key for a {asset set, window} pair."""
    canonical = "|".join(sorted(labels)) + f"#w={window_days}"
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def align_return_matrix(series_by_label: Mapping[str, pd.Series]) -> pd.DataFrame:
    """Inner-join return series on their common dates (NaN rows dropped).

    Columns are ordered by the mapping's key order. Mirrors the dropna semantics
    of app.optimizer.data.load_aligned_returns without the DB I/O.
    """
    frame = pd.DataFrame(dict(series_by_label)).dropna()
    return frame


def ledoit_wolf_cov_cached(
    returns: np.ndarray, *, cache_key: str | None = None
) -> np.ndarray:
    """Annualized (×252) Ledoit-Wolf covariance, identical to
    engine.sigma_ledoit_wolf, with optional in-process caching by cache_key.

    When cache_key is provided and present, the cached array is returned WITHOUT
    recomputation (the caller guarantees the key uniquely identifies the inputs
    via asset_set_key). When cache_key is None, no caching is applied.
    """
    if cache_key is not None and cache_key in _lw_cache:
        _lw_cache.move_to_end(cache_key)
        return _lw_cache[cache_key]
    cov = sigma_ledoit_wolf(returns)
    if cache_key is not None:
        _lw_cache[cache_key] = cov
        _lw_cache.move_to_end(cache_key)
        if len(_lw_cache) > _LW_CACHE_MAX:
            _lw_cache.popitem(last=False)
    return cov


def clear_lw_cache() -> None:
    """Drop all cached LW covariances (used by tests)."""
    _lw_cache.clear()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_aligned_helper.py -q`
Expected: PASS (4 testes).

- [ ] **Step 5: Commit**

```bash
git add app/analytics/aligned.py tests/test_aligned_helper.py
git commit -m "feat(analytics): aligned-returns helper + cached Ledoit-Wolf covariance (E1)"
```

---

# E2 — Cache de resultado por hash (Redis existente, módulo separado)

## Task E2.1: Módulo `result_cache` (Redis fail-open, namespace próprio)

**Files (backend):**
- Create: `backend/app/core/result_cache.py`
- Modify: `backend/app/core/config.py` (flags `use_result_cache`, `result_cache_ttl_seconds`)
- Test: `backend/tests/test_result_cache.py`

**Interfaces:**
- Consumes: `get_settings().redis_url` (já existe); `Portfolio` ORM.
- Produces: `result_cache`, `ResultCache`, `result_cache_key`, `portfolio_version_hash`, `cached_result` (ver Interfaces).

**Contexto — fail-open a espelhar (`backend/app/core/cache.py`):** cliente lazy `redis.asyncio.from_url(url, socket_connect_timeout=0.5, socket_timeout=0.5, decode_responses=False)`; `get`/`set` envolvem cada chamada Redis em try/except e caem para memória; `_log_redis_failure_once`. E2 **reusa esse padrão** mas com namespace `result:` e — diferente do catálogo — **não** precisa de fallback em memória para o resultado (o miss apenas força o cálculo); ainda assim mantém o fail-open (qualquer erro do Redis → trata como miss e calcula). Guard de versão `_RESULT_CACHE_VERSION` espelha `_CACHE_VERSION` de `cache.py` (schema_version + `RAILWAY_DEPLOYMENT_ID`), atendendo o risco de `schema_version` da spec §15.

- [ ] **Step 1: Adicionar as flags de settings**

Em `backend/app/core/config.py`, na classe `Settings` (perto de `redis_url`/`catalog_cache_ttl_seconds`):

```python
    # DB-first Grupo E2: cache de RESULTADO (respostas determinísticas das
    # ferramentas interativas), separado do cache de catálogo. Fail-open.
    use_result_cache: bool = False
    # TTL de respostas cacheadas (estatística/backtest/correlation-regime/MC com seed).
    result_cache_ttl_seconds: int = 3600
```

- [ ] **Step 2: Escrever os testes que falham (key determinística, versão, portfolio hash, get/set, fail-open)**

```python
# backend/tests/test_result_cache.py
import pytest
from pydantic import BaseModel

from app.core import result_cache as rc


class _Payload(BaseModel):
    ticker: str
    n: int


def test_key_is_deterministic_and_includes_kind_and_version():
    p = _Payload(ticker="AAPL", n=3)
    k1 = rc.result_cache_key("beta", p)
    k2 = rc.result_cache_key("beta", _Payload(n=3, ticker="AAPL"))  # field order irrelevant
    assert k1 == k2
    assert k1.startswith(f"result:{rc._RESULT_CACHE_VERSION}:beta:")
    # kind participa da chave (isolamento entre tipos de cálculo)
    assert rc.result_cache_key("scenario", p) != k1


def test_portfolio_version_hash_changes_with_positions(monkeypatch):
    class _Pos:
        def __init__(self, t, q, a): self.ticker, self.quantity, self.acq_price = t, q, a

    class _Pf:
        def __init__(self, pid, cash, updated, positions):
            self.id, self.cash, self.updated_at, self.positions = pid, cash, updated, positions

    import datetime as dt
    base = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 10, 100.0)])
    same = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 10, 100.0)])
    changed = _Pf(1, 1000.0, dt.datetime(2026, 6, 18), [_Pos("AAPL", 11, 100.0)])
    assert rc.portfolio_version_hash(base) == rc.portfolio_version_hash(same)
    assert rc.portfolio_version_hash(base) != rc.portfolio_version_hash(changed)


@pytest.mark.asyncio
async def test_get_miss_then_set_then_hit(monkeypatch):
    store: dict[str, bytes] = {}

    class _FakeRedis:
        async def get(self, key): return store.get(key)
        async def set(self, key, value, ex=None): store[key] = value
        async def ping(self): return True

    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: _FakeRedis())
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)
    assert await cache.get("result:x:beta:abc") == b"BODY"


@pytest.mark.asyncio
async def test_fail_open_when_redis_raises(monkeypatch):
    class _BrokenRedis:
        async def get(self, key): raise RuntimeError("redis down")
        async def set(self, key, value, ex=None): raise RuntimeError("redis down")

    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: _BrokenRedis())
    # get → trata erro como miss; set → engole o erro. Nenhum levanta.
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)  # não levanta


@pytest.mark.asyncio
async def test_get_returns_none_when_redis_not_configured(monkeypatch):
    cache = rc.ResultCache()
    monkeypatch.setattr(cache, "_redis_client", lambda: None)  # REDIS_URL ausente
    assert await cache.get("result:x:beta:abc") is None
    await cache.set("result:x:beta:abc", b"BODY", 60)  # no-op, não levanta
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_result_cache.py -q`
Expected: FAIL (`ModuleNotFoundError: app.core.result_cache`).

- [ ] **Step 4: Implementar o módulo**

```python
# backend/app/core/result_cache.py
"""Cache de RESULTADO por hash (E2) — Redis com fail-open, namespace próprio.

Separado do middleware de catálogo (app/core/cache.py): aqui cacheiam-se as
respostas DETERMINÍSTICAS das ferramentas interativas (statistics/*, backtest/
walk-forward, correlation-regime, monte-carlo COM seed). A chave é um hash dos
parâmetros normalizados; entradas que envolvem portfólio do usuário incluem o
HASH DE VERSÃO do portfólio (posições + cash + updated_at), preservando
isolamento e invalidando ao editar.

Fail-open: qualquer falha/ausência do Redis é tratada como MISS (a rota recalcula).
Diferente do catálogo, NÃO há fallback em memória — um cache de resultado por
processo daria pouca taxa de acerto e arriscaria divergência entre workers.

Guard de versão (_RESULT_CACHE_VERSION): bump manual do schema_version em qualquer
mudança de SHAPE de resposta cacheada, + RAILWAY_DEPLOYMENT_ID que rotaciona o
namespace a cada deploy (espelha _CACHE_VERSION em app/core/cache.py).
"""
from __future__ import annotations

import hashlib
import logging
import os
from typing import Any

from pydantic import BaseModel

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_RESULT_CACHE_SCHEMA_VERSION = "1"
_RESULT_CACHE_VERSION = (
    f"{_RESULT_CACHE_SCHEMA_VERSION}."
    f"{(os.getenv('RAILWAY_DEPLOYMENT_ID') or 'base')[:20]}"
)


class ResultCache:
    """Fachada Redis-only com fail-open para respostas de resultado."""

    def __init__(self) -> None:
        self._redis: Any | None = None
        self._redis_failed_logged = False

    def _redis_client(self) -> Any | None:
        if self._redis is None:
            url = get_settings().redis_url
            if not url:
                return None
            import redis.asyncio as aioredis

            self._redis = aioredis.from_url(
                url,
                socket_connect_timeout=0.5,
                socket_timeout=0.5,
                decode_responses=False,
            )
        return self._redis

    def _log_failure_once(self, exc: Exception) -> None:
        if not self._redis_failed_logged:
            self._redis_failed_logged = True
            logger.warning(
                "Redis indisponível (%s: %s) — result cache em modo fail-open "
                "(tratando como miss). Próximas falhas não serão logadas.",
                type(exc).__name__, exc,
            )

    async def get(self, key: str) -> bytes | None:
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_failure_once(exc)
            return None
        if client is None:
            return None
        try:
            raw = await client.get(key)
            return bytes(raw) if raw is not None else None
        except Exception as exc:
            self._log_failure_once(exc)
            return None

    async def set(self, key: str, body: bytes, ttl: float) -> None:
        try:
            client = self._redis_client()
        except Exception as exc:
            self._log_failure_once(exc)
            return
        if client is None:
            return
        try:
            await client.set(key, body, ex=int(ttl))
        except Exception as exc:
            self._log_failure_once(exc)

    async def active_backend(self) -> str:
        try:
            client = self._redis_client()
            if client is not None:
                await client.ping()
                return "redis"
        except Exception as exc:
            self._log_failure_once(exc)
        return "disabled"


result_cache = ResultCache()


def result_cache_key(kind: str, payload: BaseModel) -> str:
    """Chave determinística: namespace de versão + kind + sha256 do JSON canônico.

    model_dump_json(...) com sort_keys (via mode='json' + serialização ordenada)
    torna a chave invariante à ordem dos campos.
    """
    canonical = payload.model_dump_json()
    # Reserializa ordenado para invariância de ordem de campos.
    import json

    canonical = json.dumps(json.loads(canonical), sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return f"result:{_RESULT_CACHE_VERSION}:{kind}:{digest}"


def portfolio_version_hash(portfolio: Any) -> str:
    """Hash de versão de um portfólio: posições (ticker, qty, acq_price) ordenadas
    + cash + updated_at. Inclui o conteúdo, não só o id — assim editar o portfólio
    muda a chave de cache (spec §15: derivar versão de posições + timestamp).
    """
    import json

    positions = sorted(
        ((p.ticker, float(p.quantity), None if p.acq_price is None else float(p.acq_price))
         for p in portfolio.positions),
        key=lambda t: t[0],
    )
    blob = json.dumps(
        {
            "id": portfolio.id,
            "cash": float(portfolio.cash),
            "updated_at": portfolio.updated_at.isoformat() if portfolio.updated_at else None,
            "positions": positions,
        },
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()[:16]
```

Nota: `result_cache_key` recebe um Pydantic model; para chaves que precisam misturar payload + versão de portfólio, o caller injeta o `portfolio_version_hash` em um campo do payload (ver Task E2.2 — os serviços de statistics que tomam `portfolio_id` recebem um payload já incluindo a versão).

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_result_cache.py -q`
Expected: PASS (6 testes).

- [ ] **Step 6: Commit**

```bash
git add app/core/config.py app/core/result_cache.py tests/test_result_cache.py
git commit -m "feat(cache): add result_cache module (Redis fail-open, result: namespace)"
```

---

## Task E2.2: Decorator `cached_result` + portfolio-version na chave

**Files (backend):**
- Modify: `backend/app/core/result_cache.py` (adicionar `cached_result`)
- Test: `backend/tests/test_result_cache.py` (estender)

**Interfaces:**
- Consumes: `result_cache`, `result_cache_key` (E2.1).
- Produces: `cached_result(kind, *, ttl_setting="result_cache_ttl_seconds", cacheable=None)` — decorator de serviço async cuja função retorna um Pydantic model. O 2º argumento posicional da função decorada DEVE ser o `payload` (Pydantic model) — o mesmo formato dos serviços (`run_scenario(session, payload, ...)`).

**Contexto:** o decorator: (1) se `use_result_cache` off → chama direto; (2) se `cacheable(payload)` retornar False → chama direto (usado por monte-carlo sem seed); (3) calcula a chave de `payload`, tenta `get` (hit → desserializa e retorna o model), senão chama a função, serializa o model (`.model_dump_json()`), faz `set`, retorna. Fail-open já está dentro do `ResultCache`.

- [ ] **Step 1: Escrever os testes que falham (decorator: hit/miss, flag-off, cacheable=False, classe de retorno preservada)**

```python
# (append a backend/tests/test_result_cache.py)
import pytest
from pydantic import BaseModel

from app.core import result_cache as rc


class _Req(BaseModel):
    ticker: str
    seed: int | None = None


class _Resp(BaseModel):
    value: float


@pytest.mark.asyncio
async def test_decorator_caches_and_rehydrates_model(monkeypatch):
    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key): return store.get(key)
        async def set(self, key, value, ex=None): store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": True, "result_cache_ttl_seconds": 60})())

    @rc.cached_result("beta")
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=1.5)

    r1 = await _svc(None, _Req(ticker="AAPL"))
    r2 = await _svc(None, _Req(ticker="AAPL"))
    assert isinstance(r1, _Resp) and r1.value == 1.5
    assert r2.value == 1.5
    assert calls["n"] == 1  # segunda chamada veio do cache


@pytest.mark.asyncio
async def test_decorator_bypasses_when_flag_off(monkeypatch):
    calls = {"n": 0}
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": False, "result_cache_ttl_seconds": 60})())

    @rc.cached_result("beta")
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=2.0)

    await _svc(None, _Req(ticker="AAPL"))
    await _svc(None, _Req(ticker="AAPL"))
    assert calls["n"] == 2  # sem cache, recomputa sempre


@pytest.mark.asyncio
async def test_decorator_skips_when_not_cacheable(monkeypatch):
    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key): return store.get(key)
        async def set(self, key, value, ex=None): store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": True, "result_cache_ttl_seconds": 60})())

    # monte-carlo sem seed → não cacheável
    @rc.cached_result("monte_carlo", cacheable=lambda p: p.seed is not None)
    async def _svc(session, payload: _Req) -> _Resp:
        calls["n"] += 1
        return _Resp(value=3.0)

    await _svc(None, _Req(ticker="AAPL", seed=None))
    await _svc(None, _Req(ticker="AAPL", seed=None))
    assert calls["n"] == 2          # sem seed nunca cacheia
    assert store == {}              # nada gravado
    await _svc(None, _Req(ticker="AAPL", seed=42))
    await _svc(None, _Req(ticker="AAPL", seed=42))
    assert calls["n"] == 3          # com seed: computou 1×, depois hit
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_result_cache.py -q`
Expected: FAIL (`AttributeError: module 'app.core.result_cache' has no attribute 'cached_result'`).

- [ ] **Step 3: Implementar o decorator**

Adicionar ao fim de `backend/app/core/result_cache.py`:

```python
import functools
from collections.abc import Awaitable, Callable
from typing import TypeVar

_M = TypeVar("_M", bound=BaseModel)


def cached_result(
    kind: str,
    *,
    ttl_setting: str = "result_cache_ttl_seconds",
    cacheable: Callable[[BaseModel], bool] | None = None,
) -> Callable[[Callable[..., Awaitable[_M]]], Callable[..., Awaitable[_M]]]:
    """Decorator: cacheia o retorno (Pydantic model) de um serviço async.

    A função decorada tem assinatura (session, payload: BaseModel, *args, **kwargs)
    e retorna um Pydantic model. Comportamento:
      * settings.use_result_cache False → passa direto (sem tocar Redis);
      * cacheable(payload) False (ex.: monte-carlo sem seed) → passa direto;
      * senão: chave = result_cache_key(kind, payload); hit → reidrata o model
        da classe de retorno; miss → computa, serializa, grava, retorna.
    Fail-open garantido por ResultCache (erro de Redis = miss).
    """

    def _decorate(fn: Callable[..., Awaitable[_M]]) -> Callable[..., Awaitable[_M]]:
        # A classe de retorno é resolvida da anotação de retorno da função.
        return_model = fn.__annotations__.get("return")

        @functools.wraps(fn)
        async def _wrapper(session: Any, payload: BaseModel, *args: Any, **kwargs: Any) -> _M:
            settings = get_settings()
            if not getattr(settings, "use_result_cache", False):
                return await fn(session, payload, *args, **kwargs)
            if cacheable is not None and not cacheable(payload):
                return await fn(session, payload, *args, **kwargs)

            key = result_cache_key(kind, payload)
            hit = await result_cache.get(key)
            if hit is not None and return_model is not None:
                return return_model.model_validate_json(hit)  # type: ignore[no-any-return]

            result = await fn(session, payload, *args, **kwargs)
            ttl = float(getattr(settings, ttl_setting))
            await result_cache.set(key, result.model_dump_json().encode("utf-8"), ttl)
            return result

        return _wrapper

    return _decorate
```

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_result_cache.py -q`
Expected: PASS (todos, incluindo os 3 novos).

- [ ] **Step 5: Commit**

```bash
git add app/core/result_cache.py tests/test_result_cache.py
git commit -m "feat(cache): add cached_result decorator (flag/cacheable-gated, model rehydrate)"
```

---

## Task E2.3: Aplicar o cache aos serviços determinísticos (statistics, backtest, correlation-regime)

**Files (backend):**
- Modify: `backend/app/services/statistics.py` (decorar `run_scenario`, `run_beta`, `run_rolling_correlation`, `run_stock_correlation`)
- Modify: `backend/app/services/backtest.py` (decorar `run_walk_forward_backtest`)
- Modify: `backend/app/services/correlation_regime.py` (decorar `run_correlation_regime`)
- Test: `backend/tests/test_statistics_caching.py`

**Interfaces:**
- Consumes: `cached_result` (E2.2).
- Produces: os mesmos serviços, agora cacheados (sempre cacheáveis — determinísticos).

**Contexto:** os 4 serviços de statistics têm a forma `async def run_x(session, payload, *, max_points=...) -> XResponse` (o decorator usa `session, payload` posicionais; `max_points` vira kwarg — compatível). `run_walk_forward_backtest(session, payload) -> WalkForwardResponse`. `run_correlation_regime(session, refs, *, window_days)` — **NÃO** tem um `payload` Pydantic 2º-posicional (recebe `refs: list[AssetRef]`); por isso o cache do correlation-regime é aplicado **na rota** (que tem o `CorrelationRegimeRequest` payload), não no serviço — ver Step 4.

**Importante (paridade):** decorar não muda o número — com a flag off, comportamento idêntico; com flag on, hit devolve exatamente o model serializado/reidratado. Os serviços de statistics que dependem do portfólio (scenario, stock-correlation) tomam um `portfolio_id` no payload; a versão do portfólio entra na chave porque o cliente recalcula a chave do payload, MAS `portfolio_id` sozinho não invalida ao editar. **Solução:** decorar a **rota** desses dois com uma chave que inclui `portfolio_version_hash` (Step 3), não o serviço puro. Beta e rolling-correlation operam sobre pseudo-assets explícitos (sem id de portfólio) → cacheáveis direto pelo payload.

- [ ] **Step 1: Decorar os serviços sem dependência de portfólio (beta, rolling-correlation)**

Em `backend/app/services/statistics.py`, importar e decorar:

```python
from app.core.result_cache import cached_result


@cached_result("stat_beta")
async def run_beta(session, payload, *, max_points: int) -> BetaResponse:
    ...  # corpo inalterado


@cached_result("stat_rolling_correlation")
async def run_rolling_correlation(session, payload, *, max_points: int) -> CorrelationResponse:
    ...  # corpo inalterado
```

(Apenas adicionar o decorator acima da `def` existente; não mexer no corpo. Confirmar que a anotação de retorno está presente — necessária para o decorator reidratar; se faltar, adicioná-la.)

- [ ] **Step 2: Decorar `run_walk_forward_backtest`**

Em `backend/app/services/backtest.py`:

```python
from app.core.result_cache import cached_result


@cached_result("backtest_walk_forward")
async def run_walk_forward_backtest(session, payload) -> WalkForwardResponse:
    ...  # corpo inalterado
```

(Nota: quando E3 estiver ativo, o enqueue acontece **antes** desta chamada — na rota — para `n_splits` grande; o cache aqui serve o caminho síncrono e o resultado do job — ver E3.4.)

- [ ] **Step 3: Cachear scenario/stock-correlation com versão de portfólio (na rota)**

Os serviços `run_scenario`/`run_stock_correlation` recebem `portfolio_id` no payload. Para invalidar ao editar o portfólio, a chave precisa do conteúdo. Em `backend/app/api/routes/statistics.py`, carregar a versão e injetar num payload-wrapper antes de cachear. Adicionar um helper no serviço:

```python
# backend/app/services/statistics.py
from pydantic import BaseModel
from app.core.result_cache import cached_result, portfolio_version_hash


class _VersionedScenario(BaseModel):
    """Payload de cache: request + hash de versão do portfólio (invalida ao editar)."""
    request: ScenarioRequest
    portfolio_version: str


@cached_result("stat_scenario")
async def _run_scenario_cached(session, payload: _VersionedScenario, *, max_points: int) -> ScenarioResponse:
    return await run_scenario(session, payload.request, max_points=max_points)
```

E na rota `scenario` (`backend/app/api/routes/statistics.py`), quando a flag estiver ligada, carregar o portfólio com `selectinload(Portfolio.positions)`, computar `portfolio_version_hash`, e chamar `_run_scenario_cached`. Manter o caminho legado quando off:

```python
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from app.models.portfolio import Portfolio
from app.services.statistics import _VersionedScenario, _run_scenario_cached
from app.core.result_cache import portfolio_version_hash


@router.post("/scenario", response_model=ScenarioResponse)
async def scenario(payload: ScenarioRequest, session: SessionDep) -> ScenarioResponse:
    try:
        if get_settings().use_result_cache:
            pf = (await session.execute(
                select(Portfolio)
                .where(Portfolio.id == payload.portfolio_id)
                .options(selectinload(Portfolio.positions))
            )).scalar_one_or_none()
            if pf is not None:
                versioned = _VersionedScenario(
                    request=payload, portfolio_version=portfolio_version_hash(pf)
                )
                return await _run_scenario_cached(
                    session, versioned, max_points=get_settings().price_series_max_points
                )
        return await statistics_service.run_scenario(
            session, payload, max_points=get_settings().price_series_max_points
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

(Replicar o mesmo padrão `_VersionedStockCorrelation`/`_run_stock_correlation_cached` para `run_stock_correlation`, usando o `portfolio_id` do `StockCorrelationRequest`. O campo do id de portfólio é `payload.portfolio_id` em ambos — confirmar o nome do campo no schema antes de implementar.)

- [ ] **Step 4: Cachear correlation-regime na rota (payload existe lá, não no serviço)**

Em `backend/app/api/routes/correlation_regime.py`, o serviço recebe `refs` (não um payload). Cachear envolvendo a chamada com a `result_cache_key(CorrelationRegimeRequest)` diretamente (sem decorator, pois a função-alvo não tem assinatura `(session, payload)`):

```python
from app.core.result_cache import result_cache, result_cache_key

# dentro de correlation_regime(), antes de resolver refs, quando flag on:
settings_on = get_settings().use_result_cache  # import get_settings no topo
key = result_cache_key("correlation_regime", payload) if settings_on else None
if key is not None:
    hit = await result_cache.get(key)
    if hit is not None:
        return CorrelationRegimeOut.model_validate_json(hit)
# ... resolução de refs + run_correlation_regime ... → result
if key is not None:
    await result_cache.set(
        key, result.model_dump_json().encode("utf-8"),
        float(get_settings().result_cache_ttl_seconds),
    )
return result
```

(correlation-regime não toca portfólio do usuário — o payload já é determinístico, sem versão de portfólio. Importar `get_settings` no topo da rota.)

- [ ] **Step 5: Escrever o teste que falha (caching de beta + scenario com versão)**

```python
# backend/tests/test_statistics_caching.py
import pytest
from app.core import result_cache as rc


@pytest.mark.asyncio
async def test_beta_service_is_cached(monkeypatch):
    from app.schemas.statistics import BetaRequest, BetaResponse
    from app.services import statistics as svc

    store: dict[str, bytes] = {}
    calls = {"n": 0}

    class _FakeRedis:
        async def get(self, key): return store.get(key)
        async def set(self, key, value, ex=None): store[key] = value

    monkeypatch.setattr(rc.result_cache, "_redis_client", lambda: _FakeRedis())
    monkeypatch.setattr(rc, "get_settings", lambda: type("S", (), {
        "use_result_cache": True, "result_cache_ttl_seconds": 60})())

    async def _inner(session, payload, *, max_points):
        calls["n"] += 1
        # construir um BetaResponse mínimo válido (ver schema p/ campos obrigatórios)
        return _make_min_beta_response()

    # substituir o corpo não-decorado pelo stub e re-decorar
    monkeypatch.setattr(svc, "run_beta", rc.cached_result("stat_beta")(_inner))
    req = _make_min_beta_request()
    await svc.run_beta(None, req, max_points=100)
    await svc.run_beta(None, req, max_points=100)
    assert calls["n"] == 1
```

(Substituir `_make_min_beta_response`/`_make_min_beta_request` por construtores reais conforme `app/schemas/statistics.py` — ler o schema e preencher os campos obrigatórios com valores triviais.)

- [ ] **Step 6: Rodar e ver passar**

Run: `cd backend && pytest tests/test_statistics_caching.py -q`
Expected: PASS.

- [ ] **Step 7: Regressão (flag off por default = sem mudança)**

Run: `cd backend && pytest tests/test_statistics_routes.py tests/test_backtest_routes.py tests/test_correlation_regime_routes.py -q`
Expected: PASS — flag `use_result_cache` é `False` por default, comportamento idêntico.
(Se algum nome de arquivo de teste divergir, descobrir com `grep -rln "statistics\|walk_forward\|correlation_regime" tests | head`.)

- [ ] **Step 8: Commit**

```bash
git add app/services/statistics.py app/services/backtest.py app/api/routes/statistics.py app/api/routes/correlation_regime.py tests/test_statistics_caching.py
git commit -m "feat(cache): cache deterministic statistics/backtest/correlation-regime (portfolio-versioned)"
```

---

## Task E2.4: Cache de monte-carlo SOMENTE com seed

**Files (backend):**
- Modify: `backend/app/services/monte_carlo.py` (decorar com `cacheable=seed-present`)
- Test: `backend/tests/test_monte_carlo_caching.py`

**Interfaces:**
- Consumes: `cached_result` (E2.2).
- Produces: `run_monte_carlo`/`run_portfolio_monte_carlo` cacheados apenas quando `seed` está presente.

**Contexto:** `run_monte_carlo` é chamado pela rota com kwargs (`ticker=`, `seed=`, ...), não com um `payload` Pydantic 2º-posicional — então o decorator `(session, payload)` **não encaixa diretamente**. A rota (`backend/app/api/routes/monte_carlo.py`) tem o `MonteCarloRequest`/`PortfolioMonteCarloRequest` payload, com `seed: int | None` (`backend/app/schemas/monte_carlo.py:50-52`, `:181-183`). **Decisão:** cachear na **rota** (onde o payload existe), com `cacheable = seed is not None`, espelhando o padrão de correlation-regime (Task E2.3 Step 4). Monte-carlo **sem** seed é estocástico → nunca cacheia (spec §10 E2).

- [ ] **Step 1: Escrever o teste que falha (seed cacheia, sem seed não cacheia)**

```python
# backend/tests/test_monte_carlo_caching.py
import pytest
from app.core import result_cache as rc
from app.schemas.monte_carlo import MonteCarloRequest


def test_request_seed_drives_cacheability():
    seeded = MonteCarloRequest(ticker="AAPL", seed=42)
    unseeded = MonteCarloRequest(ticker="AAPL", seed=None)
    assert (seeded.seed is not None) is True
    assert (unseeded.seed is not None) is False
    # chave determinística para o mesmo seed
    assert rc.result_cache_key("monte_carlo", seeded) == rc.result_cache_key(
        "monte_carlo", MonteCarloRequest(ticker="AAPL", seed=42)
    )
    # seed diferente → chave diferente
    assert rc.result_cache_key("monte_carlo", seeded) != rc.result_cache_key(
        "monte_carlo", MonteCarloRequest(ticker="AAPL", seed=7)
    )
```

- [ ] **Step 2: Rodar e ver falhar/passar parcialmente**

Run: `cd backend && pytest tests/test_monte_carlo_caching.py -q`
Expected: PASS já neste step (usa só E2.1) — serve de guard de chave. O comportamento de rota é coberto pelo teste de rota no Step 4.

- [ ] **Step 3: Aplicar o cache na rota `projection`**

Em `backend/app/api/routes/monte_carlo.py`, envolver o caminho síncrono (quando `use_result_cache` e `payload.seed is not None`):

```python
from app.core.config import get_settings
from app.core.result_cache import result_cache, result_cache_key


@router.post("/projection", response_model=MonteCarloResponse)
async def project_monte_carlo(payload: MonteCarloRequest, session: ...) -> MonteCarloResponse:
    settings = get_settings()
    cache_key = (
        result_cache_key("monte_carlo", payload)
        if settings.use_result_cache and payload.seed is not None
        else None
    )
    if cache_key is not None:
        hit = await result_cache.get(cache_key)
        if hit is not None:
            return MonteCarloResponse.model_validate_json(hit)
    try:
        result = await run_monte_carlo(
            session, ticker=payload.ticker, statistic=payload.statistic,
            range_key=payload.range, n_simulations=payload.n_simulations,
            horizons=payload.horizons, risk_free_rate=payload.risk_free_rate,
            seed=payload.seed,
        )
    except InsufficientDataError as exc:
        message = str(exc)
        if message.startswith("No price data available"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if cache_key is not None:
        await result_cache.set(
            cache_key, result.model_dump_json().encode("utf-8"),
            float(settings.result_cache_ttl_seconds),
        )
    return result
```

(Replicar o mesmo padrão em `project_portfolio_monte_carlo` com `PortfolioMonteCarloRequest`; como o payload de portfolio-MC contém as `positions` explícitas (não um `portfolio_id`), a chave já reflete o conteúdo — sem necessidade de `portfolio_version_hash`.)

- [ ] **Step 4: Escrever/rodar o teste de rota (sem seed não grava; com seed hit)**

Adicionar ao `tests/test_monte_carlo_caching.py` um teste com `_FakeRedis` + monkeypatch de `run_monte_carlo` que conta chamadas, afirmando: sem seed → 2 chamadas + store vazio; com seed → 1 chamada + 2ª do cache. (Espelha `test_decorator_skips_when_not_cacheable` de E2.2.)

Run: `cd backend && pytest tests/test_monte_carlo_caching.py tests/test_monte_carlo_routes.py -q`
Expected: PASS (rota de MC sem regressão; flag off por default).

- [ ] **Step 5: Commit**

```bash
git add app/api/routes/monte_carlo.py tests/test_monte_carlo_caching.py
git commit -m "feat(cache): cache monte-carlo only when seed is present (deterministic path)"
```

---

# E3 — Jobs assíncronos

## Task E3.1: Tabela + modelo ORM `optimize_jobs` (CRIAR — divergência da spec)

> **DIVERGÊNCIA DA SPEC (destacada):** a spec §10/§11 diz "reusa o modelo `optimize_jobs`" e §4 lista a tabela como existente. **Ela NÃO existe nesta branch** (sem `app/models/optimize_jobs.py`, sem migration). Este plano **cria** a tabela + ORM + migration. Se em produção a tabela já existir com outro shape, o passo de migration (Step 3) deve checar existência antes de criar.

**Files (backend):**
- Create: `backend/app/models/optimize_jobs.py`
- Create: `backend/alembic/versions/<rev>_add_optimize_jobs.py`
- Test: `backend/tests/test_optimize_jobs_model.py`

**Interfaces:**
- Produces: `OptimizeJob` ORM (ver Interfaces).

**Contexto — padrão a espelhar:** `RebalancePolicy` (`backend/app/models/rebalance.py`) — modelo simples com `Base`, `CheckConstraint`, `created_at`/`updated_at`. Aqui a PK é um `uuid` gerado pela app (não autoincrement, para o cliente poder pollar por um id opaco).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_optimize_jobs_model.py
from app.models.optimize_jobs import OptimizeJob


def test_optimize_jobs_columns_and_pk():
    assert OptimizeJob.__tablename__ == "optimize_jobs"
    cols = set(OptimizeJob.__table__.columns.keys())
    assert {
        "id", "portfolio_id", "kind", "params_hash",
        "status", "result", "error", "created_at", "updated_at",
    } <= cols
    assert "id" in OptimizeJob.__table__.primary_key.columns.keys()


def test_status_check_constraint_present():
    cks = [
        c for c in OptimizeJob.__table__.constraints
        if c.__class__.__name__ == "CheckConstraint"
    ]
    assert any("status" in (c.name or "") for c in cks)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_optimize_jobs_model.py -q`
Expected: FAIL (`ModuleNotFoundError: app.models.optimize_jobs`).

- [ ] **Step 3: Implementar o modelo**

```python
# backend/app/models/optimize_jobs.py
"""ORM model for the optimize_jobs table (E3 — async jobs).

NOTE (spec divergence): the DB-First spec says to "reuse" optimize_jobs, but the
table did not exist in this branch — it is CREATED here. A large walk-forward
backtest or a big monte-carlo enqueues a job (202 + polling) instead of blocking
the request; the runner writes ``result`` (jsonb) and the polling route serves it.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import CheckConstraint, DateTime, Integer, String, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class OptimizeJob(Base):
    __tablename__ = "optimize_jobs"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # Optional — portfolio-scoped jobs (scenario/stock-correlation/portfolio-MC).
    portfolio_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String, nullable=False)
    params_hash: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, server_default="pending")
    result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
        server_default=func.now(), onupdate=func.now(),
    )

    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="status",
        ),
    )
```

- [ ] **Step 4: Gerar a migration Alembic**

Run: `cd backend && alembic revision -m "add optimize_jobs"` e editar a revisão para criar a tabela com `op.create_table(...)` espelhando as colunas/constraint acima, guardada por checagem de existência (idempotente caso a tabela já exista em prod):

```python
# backend/alembic/versions/<rev>_add_optimize_jobs.py
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "<rev>"
down_revision = "<prev_head>"  # preencher com o head atual: alembic heads
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "optimize_jobs" in insp.get_table_names():
        return  # tabela já existe em prod — não recriar (divergência da spec)
    op.create_table(
        "optimize_jobs",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("portfolio_id", sa.Integer(), nullable=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("params_hash", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False, server_default="pending"),
        sa.Column("result", postgresql.JSONB(), nullable=True),
        sa.Column("error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.func.now()),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'failed')",
            name="ck_optimize_jobs_status",
        ),
    )
    op.create_index("ix_optimize_jobs_kind_params_hash", "optimize_jobs",
                    ["kind", "params_hash"])


def downgrade() -> None:
    op.drop_index("ix_optimize_jobs_kind_params_hash", table_name="optimize_jobs")
    op.drop_table("optimize_jobs")
```

(Preencher `down_revision` com `cd backend && alembic heads`.)

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_optimize_jobs_model.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/models/optimize_jobs.py alembic/versions/*_add_optimize_jobs.py tests/test_optimize_jobs_model.py
git commit -m "feat(jobs): create optimize_jobs table + ORM (spec said reuse; table did not exist)"
```

---

## Task E3.2: Service de jobs (enqueue, polling, threshold, execução)

**Files (backend):**
- Create: `backend/app/services/jobs.py`
- Create: `backend/app/schemas/jobs.py`
- Test: `backend/tests/test_jobs_service.py`

**Interfaces:**
- Consumes: `OptimizeJob` (E3.1); `result_cache` (E2).
- Produces: `JOB_KIND_WALK_FORWARD`, `JOB_KIND_PORTFOLIO_MC`, `params_hash`, `enqueue_job`, `get_job`, `should_run_async`, `_run_job_body` (ver Interfaces); schemas `JobEnqueuedResponse`, `JobStatusResponse`.

**Threshold de "grande" (explícito):** um job vai assíncrono quando `use_async_jobs` E (`n_simulations >= async_job_threshold_n_simulations` (default **20000**) para monte-carlo) OU (`n_splits >= async_job_threshold_n_splits` (default **12**) para walk-forward). Abaixo do threshold, executa síncrono (com cache E2). Os defaults são conservadores (MC vai até 50000; walk-forward de muitos folds é o caso lento) e ajustáveis por settings.

**Execução (in-process background task):** sem broker novo (YAGNI). O enqueue cria a linha `pending`, retorna o id, e dispara a execução via `asyncio.create_task` que: marca `running`, roda o `runner` (closure que chama o serviço determinístico), grava `result`+`succeeded` (ou `error`+`failed`), e também grava o resultado no cache E2 sob a chave do serviço (para o caminho síncrono futuro reaproveitar). O `runner` recebe uma **nova** session (não a do request, que fecha ao responder 202).

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_jobs_service.py
import pytest
from app.services import jobs as jobs_svc


def test_should_run_async_thresholds(monkeypatch):
    monkeypatch.setattr(jobs_svc, "get_settings", lambda: type("S", (), {
        "use_async_jobs": True,
        "async_job_threshold_n_simulations": 20000,
        "async_job_threshold_n_splits": 12,
    })())
    assert jobs_svc.should_run_async(n_simulations=30000) is True
    assert jobs_svc.should_run_async(n_simulations=10000) is False
    assert jobs_svc.should_run_async(n_splits=24) is True
    assert jobs_svc.should_run_async(n_splits=6) is False


def test_should_run_async_off_when_flag_off(monkeypatch):
    monkeypatch.setattr(jobs_svc, "get_settings", lambda: type("S", (), {
        "use_async_jobs": False,
        "async_job_threshold_n_simulations": 20000,
        "async_job_threshold_n_splits": 12,
    })())
    assert jobs_svc.should_run_async(n_simulations=50000) is False


def test_params_hash_is_deterministic():
    from app.schemas.monte_carlo import MonteCarloRequest
    a = jobs_svc.params_hash("portfolio_mc", MonteCarloRequest(ticker="AAPL", seed=1))
    b = jobs_svc.params_hash("portfolio_mc", MonteCarloRequest(ticker="AAPL", seed=1))
    assert a == b and len(a) == 64
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_jobs_service.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.jobs`).

- [ ] **Step 3: Implementar os schemas**

```python
# backend/app/schemas/jobs.py
"""Schemas for async job enqueue/polling (E3)."""
from __future__ import annotations

import uuid

from pydantic import BaseModel, Field


class JobEnqueuedResponse(BaseModel):
    """Returned with HTTP 202 when a heavy computation is queued."""
    job_id: uuid.UUID
    status: str = Field(description="pending | running | succeeded | failed")
    kind: str


class JobStatusResponse(BaseModel):
    """Polling payload for GET /jobs/{job_id}."""
    job_id: uuid.UUID
    status: str
    kind: str
    result: dict | None = Field(default=None, description="Serviço result quando succeeded.")
    error: str | None = Field(default=None, description="Mensagem quando failed.")
```

- [ ] **Step 4: Implementar o service**

```python
# backend/app/services/jobs.py
"""Async job orchestration (E3): enqueue heavy computations, poll, serve via E2.

Sem broker externo (YAGNI): o enqueue grava a linha pending e dispara uma
asyncio task que executa o runner numa SESSION NOVA (a do request fecha ao
responder 202). O resultado é gravado em optimize_jobs.result E no result_cache
(E2), para o caminho síncrono futuro reaproveitar.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import uuid
from collections.abc import Awaitable, Callable

from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import get_sessionmaker  # ver nota de import abaixo
from app.models.optimize_jobs import OptimizeJob

logger = logging.getLogger(__name__)

JOB_KIND_WALK_FORWARD = "walk_forward"
JOB_KIND_PORTFOLIO_MC = "portfolio_mc"


def should_run_async(*, n_simulations: int | None = None, n_splits: int | None = None) -> bool:
    settings = get_settings()
    if not getattr(settings, "use_async_jobs", False):
        return False
    if n_simulations is not None and n_simulations >= settings.async_job_threshold_n_simulations:
        return True
    if n_splits is not None and n_splits >= settings.async_job_threshold_n_splits:
        return True
    return False


def params_hash(kind: str, payload: BaseModel) -> str:
    canonical = json.dumps(
        json.loads(payload.model_dump_json()), sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(f"{kind}:{canonical}".encode("utf-8")).hexdigest()


async def get_job(session, job_id: uuid.UUID) -> OptimizeJob | None:
    return (
        await session.execute(select(OptimizeJob).where(OptimizeJob.id == job_id))
    ).scalar_one_or_none()


async def enqueue_job(
    session,
    *,
    kind: str,
    params_hash: str,
    portfolio_id: int | None,
    runner: Callable[[Any], Awaitable[BaseModel]],
) -> OptimizeJob:
    """Cria a linha pending, retorna o job, e dispara a execução em background.

    ``runner(session)`` recebe uma session NOVA e retorna o Pydantic model do
    resultado. A task de fundo marca running → succeeded/failed e persiste.
    """
    job = OptimizeJob(
        id=uuid.uuid4(), kind=kind, params_hash=params_hash,
        portfolio_id=portfolio_id, status="pending",
    )
    session.add(job)
    await session.commit()
    job_id = job.id
    asyncio.create_task(_run_job_body(job_id, runner))
    return job


async def _run_job_body(
    job_id: uuid.UUID, runner: Callable[[Any], Awaitable[BaseModel]]
) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as session:
        job = await get_job(session, job_id)
        if job is None:
            return
        job.status = "running"
        await session.commit()
        try:
            result_model = await runner(session)
            job.status = "succeeded"
            job.result = json.loads(result_model.model_dump_json())
        except Exception as exc:  # noqa: BLE001 — capturar p/ persistir como failed
            logger.exception("job %s failed", job_id)
            job.status = "failed"
            job.error = str(exc)
        await session.commit()
```

Nota de import: `get_sessionmaker` deve ser o factory de sessions async do app (confirmar o nome real em `backend/app/core/db.py`; se for `async_session_maker`/`SessionLocal`, ajustar o import — a única exigência é obter um `async_sessionmaker` para abrir uma session fora do request). `from typing import Any` no topo.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_jobs_service.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/jobs.py app/schemas/jobs.py tests/test_jobs_service.py
git commit -m "feat(jobs): job service (enqueue/poll/threshold) + schemas"
```

---

## Task E3.3: Rota `GET /jobs/{job_id}`

**Files (backend):**
- Create: `backend/app/api/routes/jobs.py`
- Modify: registro de routers (`backend/app/main.py` ou `app/api/__init__.py` — onde os outros routers são incluídos)
- Test: `backend/tests/test_jobs_routes.py`

**Interfaces:**
- Consumes: `get_job` (E3.2); `JobStatusResponse` (E3.2).
- Produces: `GET /jobs/{job_id}` → `JobStatusResponse` (404 quando inexistente).

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_jobs_routes.py
import uuid
import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app  # confirmar caminho do FastAPI app


@pytest.mark.asyncio
async def test_get_unknown_job_returns_404(monkeypatch):
    from app.api.routes import jobs as jobs_route

    async def _none(session, job_id):
        return None
    monkeypatch.setattr(jobs_route.jobs_service, "get_job", _none)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.get(f"/jobs/{uuid.uuid4()}")
    assert resp.status_code == 404
```

(Se a suíte tiver um fixture de client/app, reusá-lo em vez do `ASGITransport` manual — verificar `tests/conftest.py`/`tests/test_jobs_routes.py`-vizinhos.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_jobs_routes.py -q`
Expected: FAIL (404 não definido / rota inexistente → 404 do FastAPI por rota ausente; o teste afirma a rota explícita com o body de `JobStatusResponse`).

- [ ] **Step 3: Implementar a rota**

```python
# backend/app/api/routes/jobs.py
"""Async job polling endpoint (E3): GET /jobs/{job_id}."""
from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.jobs import JobStatusResponse
from app.services import jobs as jobs_service

router = APIRouter(prefix="/jobs", tags=["jobs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job_status(job_id: uuid.UUID, session: SessionDep) -> JobStatusResponse:
    job = await jobs_service.get_job(session, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="job not found")
    return JobStatusResponse(
        job_id=job.id, status=job.status, kind=job.kind,
        result=job.result, error=job.error,
    )
```

- [ ] **Step 4: Registrar o router**

No arquivo onde os routers são incluídos (procurar `include_router` — provavelmente `backend/app/main.py`), adicionar:

```python
from app.api.routes import jobs as jobs_routes
app.include_router(jobs_routes.router)
```

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_jobs_routes.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/api/routes/jobs.py app/main.py tests/test_jobs_routes.py
git commit -m "feat(jobs): add GET /jobs/{job_id} polling route"
```

---

## Task E3.4: Enqueue de walk-forward grande e portfolio-MC grande (202 + job id)

**Files (backend):**
- Modify: `backend/app/api/routes/backtest.py` (202 quando `n_splits` >= threshold)
- Modify: `backend/app/api/routes/monte_carlo.py` (202 quando `n_simulations` >= threshold no `/portfolio`)
- Test: `backend/tests/test_jobs_routes.py` (estender)

**Interfaces:**
- Consumes: `should_run_async`, `enqueue_job`, `params_hash`, `JOB_KIND_*` (E3.2); serviços determinísticos cacheados (E2.3/E2.4).
- Produces: as rotas devolvem `JobEnqueuedResponse` (HTTP 202) no caminho grande; síncrono (com cache) caso contrário.

**Contexto:** o `WalkForwardRequest` tem `n_splits` (confirmar nome do campo em `app/schemas/backtest.py`); o `PortfolioMonteCarloRequest` tem `n_simulations` (`backend/app/schemas/monte_carlo.py:167-171`). O `runner` é uma closure `async def _runner(session) -> Response` que chama o serviço cacheado — assim o resultado do job também alimenta o cache E2 (a chamada cacheada grava na chave do serviço dentro do `_run_job_body`).

- [ ] **Step 1: Escrever o teste que falha (202 no caminho grande, 200 no pequeno)**

```python
# (append a backend/tests/test_jobs_routes.py)
@pytest.mark.asyncio
async def test_walk_forward_enqueues_when_large(monkeypatch):
    from app.api.routes import backtest as bt_route

    captured = {}

    async def _fake_enqueue(session, *, kind, params_hash, portfolio_id, runner):
        captured["kind"] = kind
        import uuid as _u
        return type("J", (), {"id": _u.uuid4(), "status": "pending", "kind": kind})()

    monkeypatch.setattr(bt_route.jobs_service, "should_run_async", lambda **k: True)
    monkeypatch.setattr(bt_route.jobs_service, "enqueue_job", _fake_enqueue)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://t") as client:
        resp = await client.post("/backtest/walk-forward", json=_min_walk_forward_body())
    assert resp.status_code == 202
    assert resp.json()["status"] == "pending"
    assert captured["kind"] == "walk_forward"
```

(`_min_walk_forward_body()` = um corpo válido mínimo conforme `WalkForwardRequest` — ler o schema e preencher os campos obrigatórios com `n_splits` alto.)

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_jobs_routes.py::test_walk_forward_enqueues_when_large -q`
Expected: FAIL (rota ainda devolve 200 síncrono).

- [ ] **Step 3: Implementar o enqueue na rota de backtest**

```python
# backend/app/api/routes/backtest.py
from fastapi import status
from app.schemas.jobs import JobEnqueuedResponse
from app.services import jobs as jobs_service


@router.post("/walk-forward")  # response_model removido: 202|200 polimórfico
async def walk_forward(payload: WalkForwardRequest, session: SessionDep):
    try:
        if jobs_service.should_run_async(n_splits=payload.n_splits):
            async def _runner(job_session) -> WalkForwardResponse:
                return await backtest_service.run_walk_forward_backtest(job_session, payload)
            job = await jobs_service.enqueue_job(
                session,
                kind=jobs_service.JOB_KIND_WALK_FORWARD,
                params_hash=jobs_service.params_hash(jobs_service.JOB_KIND_WALK_FORWARD, payload),
                portfolio_id=None,
                runner=_runner,
            )
            return JSONResponse(
                status_code=status.HTTP_202_ACCEPTED,
                content=JobEnqueuedResponse(
                    job_id=job.id, status=job.status, kind=job.kind
                ).model_dump(mode="json"),
            )
        return await backtest_service.run_walk_forward_backtest(session, payload)
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

(Importar `from fastapi.responses import JSONResponse` no topo. O caminho síncrono retorna `WalkForwardResponse` — FastAPI serializa o model normalmente mesmo sem `response_model`.)

- [ ] **Step 4: Implementar o enqueue na rota portfolio-MC**

Em `backend/app/api/routes/monte_carlo.py::project_portfolio_monte_carlo`, espelhar o padrão acima com `should_run_async(n_simulations=payload.n_simulations)`, `JOB_KIND_PORTFOLIO_MC`, e `_runner` chamando `run_portfolio_monte_carlo(job_session, payload)`. Manter o `try/except InsufficientDataError` para o caminho síncrono.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_jobs_routes.py -q`
Expected: PASS.

- [ ] **Step 6: Regressão (flag off → comportamento síncrono inalterado)**

Run: `cd backend && pytest tests/test_backtest_routes.py tests/test_monte_carlo_routes.py -q`
Expected: PASS — `use_async_jobs` é `False` por default, `should_run_async` sempre False → caminho síncrono idêntico ao atual.

- [ ] **Step 7: Adicionar as flags de async-jobs em settings**

Em `backend/app/core/config.py` (se ainda não adicionadas):

```python
    # DB-first Grupo E3: jobs assíncronos para cálculos pesados.
    use_async_jobs: bool = False
    async_job_threshold_n_simulations: int = 20000
    async_job_threshold_n_splits: int = 12
```

- [ ] **Step 8: Commit**

```bash
git add app/api/routes/backtest.py app/api/routes/monte_carlo.py app/core/config.py tests/test_jobs_routes.py
git commit -m "feat(jobs): enqueue large walk-forward / portfolio-MC (202 + job id), serve via E2"
```

---

## Task E3.5: Suíte completa + regressão

**Files:** nenhuma nova; rodar as suítes.

- [ ] **Step 1: Suíte completa do backend**

Run: `cd backend && pytest -q`
Expected: verde (sem novas falhas; todas as flags off por default). Falhas pré-existentes da main (se houver) não contam — comparar contra o baseline da branch.

- [ ] **Step 2: Suíte completa dos workers**

Run: `cd /e/investintell-datalake-workers && pytest -q`
Expected: verde (inclui `tests/test_stock_daily_returns.py`).

- [ ] **Step 3: Commit (se houve ajuste de regressão)**

```bash
git add -A
git commit -m "test(group-e): full suite green with all E flags off by default"
```

---

## Estratégia de rollout (pós-merge)

Seguindo a transição do spec (§12): com tudo mergeado e as flags `use_result_cache=False`, `use_async_jobs=False`, `use_latest_mv_prices` (Grupo D) inalteradas, nada muda em produção.
1. **E1:** aplicar `schemas/stock_daily_returns.sql`, provisionar o worker `stock_daily_returns` no Railway (cron após o ingest diário), confirmar a tabela populada. O helper LW-cov já vale (in-process, sem ops).
2. **E2:** confirmar `REDIS_URL` no serviço `api`; ligar `use_result_cache=True` em staging; comparar payloads (hit vs recompute) das ferramentas; medir taxa de acerto; então ligar em produção. `result_cache_ttl_seconds` por tipo se necessário (ajustar via decorator `ttl_setting`).
3. **E3:** aplicar a migration `optimize_jobs` (Alembic); ligar `use_async_jobs=True` em staging; validar que walk-forward grande devolve 202 + polling converge a `succeeded` com `result` igual ao síncrono; só então em produção. Ajustar os thresholds (`async_job_threshold_*`) conforme a latência observada.

---

## Self-Review

**1. Cobertura do escopo (spec §10 Grupo E, §13):**
- E1 daily_returns de stocks (worker, justificado vs cagg) → Task E1.1. ✓
- E1 helper de aligned-returns + cache LW por `{asset_set, window}` → Task E1.3 (`asset_set_key`, `ledoit_wolf_cov_cached`, `align_return_matrix`) com paridade vs `engine.sigma_ledoit_wolf`. ✓
- E1 ORM read da tabela → Task E1.2. ✓
- E2 módulo novo separado do middleware de catálogo, Redis fail-open, namespace `result:` → Task E2.1. ✓
- E2 decorator/helper wrappeando os determinísticos (statistics/* sempre, backtest/walk-forward, correlation-regime) → Tasks E2.2/E2.3. ✓
- E2 monte-carlo cacheável SÓ com seed → Task E2.4 (cacheável na rota com `seed is not None`). ✓
- E2 chave inclui versão de portfólio → Task E2.1 `portfolio_version_hash` + E2.3 Step 3 (`_VersionedScenario`/stock-correlation). ✓
- E2 schema_version guard → `_RESULT_CACHE_VERSION` (E2.1), espelhando `_CACHE_VERSION` (risco spec §15). ✓
- E3 criar `optimize_jobs` (divergência destacada) → Task E3.1 (modelo + migration idempotente). ✓
- E3 enqueue (202 + job id) walk-forward grande + monte-carlo grande → Task E3.4; threshold explícito (`n_simulations>=20000`/`n_splits>=12`) → Task E3.2. ✓
- E3 polling GET /jobs/{id} → Task E3.3; resultado servido via E2 (grava no cache dentro do runner cacheado) → E3.4 `_runner` chama o serviço cacheado. ✓
- Testes (spec §13): hit/miss, fail-open Redis down, chave com versão de portfólio, MC sem seed não cacheia, schema_version guard, jobs enfileiramento/polling/estados → cobertos em `test_result_cache.py`, `test_statistics_caching.py`, `test_monte_carlo_caching.py`, `test_jobs_service.py`, `test_jobs_routes.py`. ✓

**2. Varredura de placeholders:** os pontos "preencher campos obrigatórios conforme o schema" (testes de statistics/backtest/MC bodies) e "confirmar o nome do campo/import" são instruções de leitura de um arquivo nomeado e exato (`app/schemas/statistics.py`, `app/core/db.py`, `app/main.py`), não hand-waves de design — o engenheiro lê o schema citado e instancia. Todos os steps de código trazem o código real. Sem "TBD"/"etc."/"add error handling" genérico.

**3. Consistência de tipos:**
- `ResultCache.get -> bytes | None` / `.set(key, body: bytes, ttl: float)` — usados consistentemente em E2.2/E2.3/E2.4 (sempre `model_dump_json().encode("utf-8")` ao gravar, `model_validate_json(hit)` / `model_validate_json(...)` ao ler). ✓
- `result_cache_key(kind, payload: BaseModel) -> str` — mesma assinatura em E2.1/E2.3/E2.4. ✓
- `should_run_async(*, n_simulations=None, n_splits=None) -> bool` — definido em E3.2, chamado com `n_splits=`/`n_simulations=` em E3.4. ✓
- `enqueue_job(session, *, kind, params_hash, portfolio_id, runner) -> OptimizeJob` — definido em E3.2, chamado com exatamente esses kwargs em E3.4. ✓
- `OptimizeJob` colunas (`id, portfolio_id, kind, params_hash, status, result, error, created_at, updated_at`) idênticas entre ORM (E3.1), migration (E3.1 Step 4) e uso (E3.2/E3.3). ✓
- `params_hash` aparece como **nome de coluna** (`OptimizeJob.params_hash`) e como **função** (`jobs_service.params_hash`); são namespaces distintos (atributo de instância vs função de módulo) — sem colisão, mas anotado aqui para evitar confusão do implementador. ✓
- `ledoit_wolf_cov_cached` / `asset_set_key` / `clear_lw_cache` consistentes entre Interfaces, E1.3 e os testes. ✓
- `LOCK_STOCK_DAILY_RETURNS = 900_211` (E1.1) não colide com locks existentes nem com `900_210` (matview_refresh da Fundação). ✓

**Riscos conhecidos (documentados, não placeholders):**
- Frescor de `stock_daily_returns`: cron do worker tem lag vs `eod_prices`; aceitável (o helper E1 é ingrediente do optimizer/backtest, não do request path EOD crítico). Rollout valida.
- Background task in-process (E3): se o processo reiniciar com um job `running`, ele fica órfão — aceitável no MVP (o cliente re-enfileira); um reaper é YAGNI até haver evidência de necessidade. Anotado para evolução, não bloqueante.
- Divergências da spec sinalizadas em duas seções dedicadas no topo (optimize_jobs criada; daily_returns = worker), repetidas nas Tasks E3.1 e E1.1.
