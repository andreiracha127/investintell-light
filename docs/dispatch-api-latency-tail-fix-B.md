# Dispatch — API Latency Tail Fix — REVISÃO PARA ESTRATÉGIA B

**Date:** 2026-06-16 · **Branch/worktree:** `fix/api-latency-tail` @ `E:\investintell-light-latency`
**Base:** `docs/dispatch-api-latency-tail-fix.md` (diagnóstico original — premissas reconfirmadas: `db.py` só `pool_pre_ping=True`; rotas chamam `ensure_*` síncrono sem `BackgroundTasks`; `classify_tickers` fresh/stale/cold com fresh pulado).

## Decisões do dono (RESOLVIDAS)

1. **Estratégia de frescor → B (destino arquitetural).** Worker/cron mantém o universo quente; rotas viram **DB-first puras**; `ensure` on-demand só para **cold absoluto**. (Não A.)
2. **Ticker `cold` → bloquear com deadline.** Mantém contrato atual (404/503/502/422) com `asyncio.timeout` curto (3–5 s) como teto.
3. **Task 5 (cache de `/analysis`) → fora por ora.** Reavaliar depois que B estabilizar.

## Realização de B (apurada no código, não suposta)

- **`/stocks/*`** lê **`eod_prices`** (`EodPrice`, `app/models/eod_price.py`), escrita pelo `ensure_eod_data` on-demand. **Nenhum worker existente aquece `eod_prices`.** → precisa de **app DB-first + worker novo**.
- **`/funds/*`** NAV lê **`nav_timeseries`** (+ CAGGs weekly/monthly), **já aquecida** por `instrument_ingestion` (datalake-workers, diário 06:00 UTC) e `benchmark_ingest` (05:30). O caminho ETF em `funds.py:691` toca `eod_prices` → coberto pelo warmer novo.
- Mesmo `DATABASE_URL` (TimescaleDB Cloud `t83f4np6x4`) para API e workers → o worker pode fazer upsert direto em `eod_prices` (conflito `ticker,date`), espelhando `instrument_ingestion`/`benchmark_ingest`.

### Trilha 1 — App (este repo, backend apenas, TDD)

- **Task 0** — middleware de timing por rota (baseline antes/depois).
- **DB-first (CORE)** — novo entry-point `ensure_eod_db_first` (ou flag em `ensure_eod_data`): `stale` é tratado como `fresh` (serve DB, **sem fetch**); só `cold` busca síncrono. Cap de `cold` e fail-loud preservados. Rotas `/stocks/*` e o caminho ETF de `/funds` passam a usar o modo DB-first.
- **Deadline (Task 4)** — `asyncio.timeout` no fetch `cold` remanescente → mapeia estouro para a degradação/erro existente.
- **Pool (Task 3)** — `core/db.py`: remover `pool_pre_ping`, adicionar `pool_recycle`≈1800 s + `pool_size`/`max_overflow`/`pool_timeout` curto, dimensionados ao teto do TimescaleDB Cloud (compartilhado com workers — **não** subir às cegas).
- **/stocks/overview** — `INDEX_TICKERS` DB-first (servem últimos conhecidos; warmer mantém quente).

### Trilha 2 — Worker `eod_prices_warmer` (repo `investintell-datalake-workers`)

- Novo `src/workers/eod_prices_warmer.py` seguindo o padrão de `benchmark_ingest.py`/`instrument_ingestion.py`:
  - Universo = `SELECT DISTINCT ticker FROM eod_prices` ∪ `INDEX_TICKERS` (auto-mantido).
  - Incremental por watermark (`max(date)` por ticker, overlap p/ revisões); reusa `_tiingo.py` `TiingoClient` + `TokenBucket`; `advisory_lock` (novo ID na banda 900_3xx, ex.: `900_335`).
  - Upsert em `eod_prices` (mesmas colunas do `build_eod_upsert` da API).
  - Cadência tal que o universo fique sob `eod_staleness_hours` (config da API).
  - `tests/test_eod_prices_warmer.py`; registrar serviço/cron no `railway.toml`.
- `nav_timeseries` já coberta — **não** duplicar.

## Aceite

`p95 < 1 s` sob o mesmo tráfego, sem regredir `p50`≈67 ms, fail-loud preservado (404/503/502/422). Verde local: `pytest -q` + `ruff check .` + `mypy app` (de `backend/`). **Sem deploy sem pedido explícito do dono.**

## Não fazer (inalterado)

Rec 1 (timeout Redis), rec 2 (`/stocks/` blanket cache), rec 5 isolada (pool como "cura"). Não tocar `/stocks/{ticker}/news`. Não duplicar o aquecimento de `nav_timeseries`.
