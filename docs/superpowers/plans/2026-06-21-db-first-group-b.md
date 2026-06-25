# DB-First — Grupo B (Stock/holdings por entidade) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrar os três endpoints do Grupo B (`stocks/{ticker}/holders`, `stocks/{ticker}/holders/funds`, `holdings/{cusip}/reverse-lookup`) de SQL pesado no request path para leitura de materialized views/views pré-computadas no datalake, reproduzindo dentro da MV a resolução de nome de gestor (3 níveis, CIK `lpad` a 10, LATERAL highest-AUM), a resolução de família (3 níveis) e a trilha de 4 trimestres, atrás de uma flag nova `use_holders_db_first` (default `False`) com fallback ao caminho legado — sem mudar números nem o shape de resposta.

**Architecture:** Três objetos novos no **datalake DB** (onde residem `sec_13f_holdings`, `sec_nport_holdings`, `sec_cusip_ticker_map`, `fundamentals_snapshot`, `eod_prices` e os crosswalks SEC): `stock_institutional_holders_mv` (B1), `stock_fund_holders_mv` (B2) e `holding_reverse_lookup_mv` (B3, lado institucional 13F). Toda a álgebra de nomes/períodos vira parte do SELECT da MV; o backend faz apenas `SELECT ... WHERE` + montagem fina do dict/árvore (sem cálculo, sem pandas). Cada MV tem índice UNIQUE e populate inicial não-concorrente; o refresh agendado é feito pelo worker `matview_refresh` (criado no Grupo D) num **segundo passo contra o DSN do datalake**. O lado de exposições de fundo do B3 (`fund_holdings`/`funds_v`) permanece uma leitura on-demand no **app DB** (não materializado nesta migração — é catálogo dinâmico por org) e fica documentado como split explícito. B1 mantém o subquery histórico de `eod_prices` (ou `cagg_eod_daily`) **dentro da MV** para `entry_price`/`current_price`, porque `price_latest_mv` só guarda last/prev close e não consegue resolver preço numa data de entrada arbitrária.

**Tech Stack:** Python 3.11+, psycopg3 (workers), SQLAlchemy 2.0 async + asyncpg (backend), FastAPI, PostgreSQL/TimescaleDB, pytest (`asyncio_mode = "auto"`), Railway cron.

## Baseline — branch `feat/db-first-analytics` @ `f6e2c27`, worktree `E:/investintell-light/.claude/worktrees/db-first-analytics`

Este plano assume a Fundação + Grupo D **já implementados nesta branch** (commit do plano `2026-06-21-db-first-foundation-group-d.md`): `price_latest_mv`/`nav_latest_mv` existem no app DB, a flag `use_latest_mv_prices` (default `False`) existe em `app/core/config.py`, os modelos `PriceLatest`/`NavLatest` já estão registrados em `app/models/__init__.py`, e o worker `matview_refresh` existe no repo de workers (`E:/investintell-datalake-workers/src/workers/matview_refresh.py`) refrescando os dois MVs do app DB.

**Dependência crítica do worker (ler antes da Task 4):** no `main` do repo de workers, `src/workers/matview_refresh.py` **ainda não existe** (o Grupo D foi mantido não-mesclado pelo dono). Quando a Task 4 deste plano for executada num worktree limpo do repo de workers, ela DEVE primeiro garantir que o worker existe (criar idêntico ao da Task 2 do plano do Grupo D se ausente) e então estendê-lo para refrescar os MVs do datalake. A Task 4 abaixo traz o **arquivo completo** do worker pós-Grupo-B, então ela é auto-suficiente mesmo se o arquivo do Grupo D não estiver presente.

## Global Constraints

- Os MVs do Grupo B (`stock_institutional_holders_mv`, `stock_fund_holders_mv`, `holding_reverse_lookup_mv`) residem no **datalake DB** (`DATALAKE_DB_URL` / `settings.datalake_db_url`), o mesmo banco lido por `get_datalake_session` e onde estão `sec_13f_holdings`, `sec_nport_holdings`, `sec_cusip_ticker_map`, `fundamentals_snapshot`, `eod_prices`, `nport_holdings_history`, `sec_13f_entry`, `sec_investment_company_series_class`, `fund_instrument_map`, `sec_13f_filer_name`, `sec_managers`. NÃO no app DB.
- DDL é versionado em **`backend/db/ddl/`** (arquivos datados, aplicados via Tiger/psql), seguindo a convenção de `38dbdb4`/Grupo D (`backend/db/ddl/2026-06-21_price_nav_latest_mv.sql`). Cada DDL tem um teste de string-assert em `backend/tests/test_<name>_sql.py` no estilo de `test_dynamic_catalog_sql.py` / `test_price_nav_latest_mv_sql.py`.
- Todo MV refrescado com `CONCURRENTLY` DEVE ter um índice **UNIQUE** e ter sido populado ao menos uma vez (refresh não-concorrente inicial) antes do primeiro `CONCURRENTLY`.
- O refresh roda em conexão **autocommit**, **fora** de qualquer advisory lock e bloco de transação (igual a `risk_metrics._refresh_fund_risk_latest_mv` e ao worker `matview_refresh` do Grupo D).
- Grupo B **não tem worker Python computacional** — tudo é MV/SQL. O único trabalho no repo de workers é estender o `matview_refresh` (que já existe via Grupo D) para também refrescar os três MVs do datalake. Trabalhar num **worktree limpo do `main` do repo de workers** (regra permanente do dono — o working tree compartilhado tem trabalho de outras sessões).
- Modelos ORM dos MVs vivem em `backend/app/models/` e são registrados em `backend/app/models/__init__.py` (espelhando `PriceLatest`/`NavLatest`).
- Transição (spec §12): construir MV → teste de paridade vs SQL atual → dual-read atrás de flag nova `use_holders_db_first` (default `False`) → flip → remover legado. Manter o fallback legado enquanto a flag estiver off.
- "Nenhum cálculo pesado/pandas no request path": o backend dos endpoints migrados só faz `SELECT` + reshape; testes afirmam que o caminho MV não toca as tabelas cruas (`sec_13f_holdings`/`sec_nport_holdings`) — espelhando o padrão de asserção sobre `_FakeSession.executed` de `backend/tests/test_price_latest_mv_reads.py`.
- O tipo de retorno de `fetch_stock_holders`/`fetch_stock_fund_holders`/`fetch_holding_reverse_lookup` permanece **exatamente** `StockHoldersResponse`/`StockFundHoldersResponse`/`HoldingReverseLookupResponse` (paridade — frontend só renderiza).
- Backend tests: `cd backend && pytest`; `asyncio_mode = "auto"`; I/O é stubado por `monkeypatch`/fake session (sem DB vivo).
- Workers tests: `pytest tests/test_<x>.py -s -v`; sem `conftest`; fake connection via `monkeypatch`.
- Advisory locks ficam no range `900_2xx`/`900_3xx` em `investintell-datalake-workers/src/db.py`; `LOCK_MATVIEW_REFRESH = 900_210` já definido pelo Grupo D (reutilizado, não duplicado).

---

## File Structure

**Repo backend — `E:/investintell-light/.claude/worktrees/db-first-analytics/backend` (DDL datalake + leitura):**
- Create: `backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql` — DDL do MV B1.
- Create: `backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql` — DDL do MV B2.
- Create: `backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql` — DDL do MV B3 (lado 13F).
- Create: `backend/tests/test_stock_institutional_holders_mv_sql.py` — string-assert do DDL B1.
- Create: `backend/tests/test_stock_fund_holders_mv_sql.py` — string-assert do DDL B2.
- Create: `backend/tests/test_holding_reverse_lookup_mv_sql.py` — string-assert do DDL B3.
- Create: `backend/app/models/stock_holders_mv.py` — modelos ORM `StockInstitutionalHolder`, `StockFundHolderRow`, `HoldingReverseLookupRow`.
- Modify: `backend/app/models/__init__.py` — registrar os 3 modelos novos.
- Modify: `backend/app/core/config.py` — flag `use_holders_db_first`.
- Modify: `backend/app/services/stock_holders.py` — caminho MV + fallback legado atrás da flag (B1 + B2).
- Modify: `backend/app/services/fund_dossier_tier_b.py` — caminho MV para o lado 13F do reverse-lookup, atrás da flag (B3).
- Create: `backend/tests/test_stock_holders_db_first.py` — paridade/flag/"no-heavy-SQL" para B1 e B2.
- Create: `backend/tests/test_reverse_lookup_db_first.py` — paridade/flag/"no-heavy-SQL" para B3.

**Repo workers — worktree limpo do `main` de `E:/investintell-datalake-workers` (apenas o refresh):**
- Modify (ou Create se ausente, vide Baseline): `src/workers/matview_refresh.py` — adicionar refresh dos 3 MVs do datalake (segundo passo, DSN do datalake).
- Modify: `tests/test_matview_refresh.py` — cobrir o refresh dos MVs do datalake.

**Por que estas fronteiras:** DDL e leitura são read-models do datalake e seguem a convenção `backend/db/ddl/`; só o refresh agendado vive no repo de workers, reusando o worker do Grupo D (não cria worker novo). Cada tarefa termina com um deliverable testável independentemente.

---

## Interfaces (contratos entre tarefas)

- `stock_institutional_holders_mv(ticker text, cik text, manager_name text, report_date date, cusip text, issuer_name text, shares numeric, market_value numeric, entry_date date, entry_price numeric, current_price numeric, shares_outstanding numeric)`, UNIQUE(`ticker`, `cik`, `cusip`).
- `stock_fund_holders_mv(ticker text, registrant_cik text, family text, series_id text, fund_name text, instrument_id uuid, issuer_name text, quantity numeric, market_value numeric, pct_of_nav numeric, pct_nav_q1 numeric, pct_nav_q2 numeric, pct_nav_q3 numeric, report_date date, cusip text)`, UNIQUE(`ticker`, `series_id`).
- `holding_reverse_lookup_mv(cusip text, cik text, manager_name text, period date, report_date date, name text, value_usd numeric, shares numeric)`, UNIQUE(`cusip`, `cik`).
- `StockInstitutionalHolder` ORM: `.ticker .cik .manager_name .report_date .cusip .issuer_name .shares .market_value .entry_date .entry_price .current_price .shares_outstanding`.
- `StockFundHolderRow` ORM: `.ticker .registrant_cik .family .series_id .fund_name .instrument_id .issuer_name .quantity .market_value .pct_of_nav .pct_nav_q1 .pct_nav_q2 .pct_nav_q3 .report_date .cusip`.
- `HoldingReverseLookupRow` ORM: `.cusip .cik .manager_name .period .report_date .name .value_usd .shares`.
- `settings.use_holders_db_first: bool` (default `False`).
- `fetch_stock_holders(datalake, ticker, *, use_db_first: bool | None = None) -> StockHoldersResponse`.
- `fetch_stock_fund_holders(datalake, ticker, *, use_db_first: bool | None = None) -> StockFundHoldersResponse`.
- `fetch_holding_reverse_lookup(session, datalake, cusip, *, use_db_first: bool | None = None) -> HoldingReverseLookupResponse`.
- `matview_refresh.run(dsn: str, *, datalake_dsn: str | None = None) -> dict` retorna `{"refreshed": [...], "refreshed_datalake": [...]}`.

---

## Task 1: DDL `stock_institutional_holders_mv` (B1)

**Files:**
- Create: `backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql`
- Test: `backend/tests/test_stock_institutional_holders_mv_sql.py`

**Interfaces:**
- Produces: MV B1 com o shape e índice UNIQUE da seção Interfaces, no datalake DB.

**Contexto:** o SQL atual (`_HOLDERS_SQL` em `backend/app/services/stock_holders.py:38-104`) resolve ticker→CUSIP via `sec_cusip_ticker_map`, pega o `max(report_date)` **global** de `sec_13f_holdings`, e por holder resolve `manager_name` em 3 níveis (`COALESCE(sec_13f_filer_name.filer_name` por `cik = lpad(h.cik,10,'0')`, `sec_managers.firm_name` via LATERAL highest-AUM com `cik = lpad(h.cik,10,'0')`, `'CIK ' || h.cik`), `entry_date` da MV `sec_13f_entry`, `entry_price`/`current_price`/`shares_outstanding` por subqueries históricas. **Limitação de `price_latest_mv` (CRÍTICO):** `price_latest_mv` só guarda `last_close`/`prev_close`, não preço numa data arbitrária — `entry_price` precisa de "primeiro `adj_close >= entry_date`", que o MV não consegue dar. Por isso a MV B1 **mantém os subqueries de `eod_prices`** para `entry_price` e `current_price` (paridade exata; `current_price` poderia vir de `price_latest_mv` mas seria a mesma observação do `ORDER BY date DESC LIMIT 1`, então não vale acoplar). Toda a resolução de nome/entrada/preço fica **dentro do SELECT da MV**, materializada por `(ticker, cik, cusip)`. Convenção de DDL/teste idêntica a `backend/db/ddl/2026-06-21_price_nav_latest_mv.sql`.

- [ ] **Step 1: Escrever o teste que falha (conteúdo do schema)**

```python
# backend/tests/test_stock_institutional_holders_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_stock_institutional_holders_mv.sql"
)


def test_schema_defines_b1_mv_with_unique_index_and_name_resolution():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_institutional_holders_mv" in sql
    # CONCURRENTLY exige índice UNIQUE.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_institutional_holders_mv_pk" in sql
    # Populate inicial não-concorrente.
    assert "REFRESH MATERIALIZED VIEW stock_institutional_holders_mv;" in sql
    # Resolução de nome de gestor em 3 níveis, CIK lpad a 10 dígitos.
    assert "lpad(h.cik, 10, '0')" in sql
    assert "COALESCE(fn.filer_name, mgr.firm_name, 'CIK ' || h.cik)" in sql
    assert "sec_13f_filer_name" in sql
    assert "ORDER BY m.aum_total DESC NULLS LAST" in sql
    # entry_date vem da MV sec_13f_entry.
    assert "sec_13f_entry" in sql
    # entry_price/current_price ficam em eod_prices (price_latest_mv NÃO serve).
    assert "FROM eod_prices p" in sql
    assert "p.date >= " in sql  # primeiro adj_close em/após entry_date
    # shares_outstanding de fundamentals_snapshot.
    assert "fundamentals_snapshot" in sql
    # índice por cusip de sec_13f_holdings (latest report_date global).
    assert "max(report_date) AS period FROM sec_13f_holdings" in sql
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_stock_institutional_holders_mv_sql.py -q`
Expected: FAIL (arquivo não existe → `FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql
-- B1 read-model (datalake DB): holders 13F (universo >$5bn) por ticker no
-- período mais recente, com manager_name resolvido em 3 níveis, entry_date da
-- MV sec_13f_entry e entry_price/current_price/shares_outstanding já resolvidos.
-- Refrescado por matview_refresh (passo datalake). Espelha _HOLDERS_SQL de
-- backend/app/services/stock_holders.py (paridade exata).
--
-- NOTA price_latest_mv: NÃO usado aqui. entry_price = primeiro adj_close em/após
-- entry_date (data arbitrária) — price_latest_mv só tem last/prev close. Mantemos
-- o subquery de eod_prices para entry_price e current_price.

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_institutional_holders_mv AS
WITH map AS (
    SELECT DISTINCT upper(ticker) AS ticker, upper(cusip) AS cusip
    FROM sec_cusip_ticker_map
    WHERE cusip IS NOT NULL AND ticker IS NOT NULL
),
latest AS (
    SELECT max(report_date) AS period FROM sec_13f_holdings
),
base AS (
    SELECT
        m.ticker,
        h.cik,
        COALESCE(fn.filer_name, mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
        h.report_date,
        upper(h.cusip) AS cusip,
        h.issuer_name,
        h.shares,
        h.market_value,
        entry.entry_date
    FROM sec_13f_holdings h
    JOIN map m ON m.cusip = upper(h.cusip)
    LEFT JOIN sec_13f_filer_name fn ON fn.cik = lpad(h.cik, 10, '0')
    LEFT JOIN LATERAL (
        SELECT mm.firm_name
        FROM sec_managers mm
        WHERE mm.cik = lpad(h.cik, 10, '0') AND mm.firm_name IS NOT NULL
        ORDER BY mm.aum_total DESC NULLS LAST
        LIMIT 1
    ) mgr ON true
    LEFT JOIN sec_13f_entry entry ON entry.cik = h.cik AND entry.cusip = h.cusip
    WHERE h.report_date = (SELECT period FROM latest)
)
SELECT
    base.ticker,
    base.cik,
    base.manager_name,
    base.report_date,
    base.cusip,
    base.issuer_name,
    base.shares,
    base.market_value,
    base.entry_date,
    -- primeiro adj_close em/após a data de entrada (preço de custo aproximado)
    (SELECT p.adj_close FROM eod_prices p
     WHERE p.ticker = base.ticker AND p.date >= base.entry_date
     ORDER BY p.date ASC LIMIT 1) AS entry_price,
    -- último adj_close conhecido do ticker
    (SELECT p.adj_close FROM eod_prices p
     WHERE p.ticker = base.ticker
     ORDER BY p.date DESC LIMIT 1) AS current_price,
    -- shares outstanding mais recentes (para % de ownership)
    (SELECT f.shares_outstanding FROM fundamentals_snapshot f
     WHERE upper(f.ticker) = base.ticker AND f.shares_outstanding > 0
     ORDER BY f.period_end DESC LIMIT 1) AS shares_outstanding
FROM base
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_institutional_holders_mv_pk
    ON stock_institutional_holders_mv (ticker, cik, cusip);
CREATE INDEX IF NOT EXISTS stock_institutional_holders_mv_ticker
    ON stock_institutional_holders_mv (ticker);

REFRESH MATERIALIZED VIEW stock_institutional_holders_mv;
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_stock_institutional_holders_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Aplicar o DDL no datalake (ops, manual)**

```bash
psql "$DATALAKE_DB_URL" -f backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql
psql "$DATALAKE_DB_URL" -c "SELECT ticker, cik, manager_name, entry_price, current_price FROM stock_institutional_holders_mv WHERE ticker = 'AAPL' LIMIT 5;"
```

Expected: linhas retornadas (MV populado); `entry_price`/`current_price` podem ser NULL para tickers sem `eod_prices`.

- [ ] **Step 6: Commit**

```bash
git add backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql backend/tests/test_stock_institutional_holders_mv_sql.py
git commit -m "feat(matview): add stock_institutional_holders_mv DDL (B1)"
```

---

## Task 2: DDL `stock_fund_holders_mv` (B2)

**Files:**
- Create: `backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql`
- Test: `backend/tests/test_stock_fund_holders_mv_sql.py`

**Interfaces:**
- Produces: MV B2 com o shape e índice UNIQUE da seção Interfaces, no datalake DB.

**Contexto:** o SQL atual (`_FUND_HOLDERS_SQL` em `backend/app/services/stock_holders.py:195-242`) lê da MV `nport_holdings_history` (não da hypertable crua), pega `max(report_date)` global, agrega por `(cik, series_id)`, resolve `family` em 3 níveis (`COALESCE(fam.entity_name` por `registrant_cik`, `sc.entity_name` por `series_id`, `'CIK ' || n.cik)`), `fund_name = COALESCE(sc.series_name, n.series_id)`, `instrument_id` via `fund_instrument_map`, e a trilha de 4 trimestres (`pct_nav_0..3`). O agrupamento family→funds é feito em Python depois (sem cálculo). A MV materializa exatamente essas linhas por `(ticker, series_id)`; o filtro `report_date >= (max) - interval '130 days'` é preservado dentro da MV.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_stock_fund_holders_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_stock_fund_holders_mv.sql"
)


def test_schema_defines_b2_mv_with_family_resolution_and_4q_trail():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fund_holders_mv" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_fund_holders_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW stock_fund_holders_mv;" in sql
    # Fonte = MV nport_holdings_history (não a hypertable crua).
    assert "FROM nport_holdings_history" in sql
    # Família em 3 níveis.
    assert "COALESCE(fam.entity_name, sc.entity_name, 'CIK ' || n.cik)" in sql
    assert "COALESCE(sc.series_name, n.series_id)" in sql
    assert "sec_investment_company_series_class" in sql
    # instrument_id do mapa pré-materializado, não funds_v.
    assert "fund_instrument_map" in sql
    # Trilha de 4 trimestres.
    assert "pct_nav_0" in sql
    assert "pct_nav_1" in sql
    assert "pct_nav_2" in sql
    assert "pct_nav_3" in sql
    # Filtro de recência preservado.
    assert "interval '130 days'" in sql
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_stock_fund_holders_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql
-- B2 read-model (datalake DB): funds registrados (N-PORT) que detêm o ticker,
-- agregados por (ticker, series_id), com family resolvida em 3 níveis, fund_name,
-- instrument_id e trilha de 4 trimestres. Espelha _FUND_HOLDERS_SQL de
-- backend/app/services/stock_holders.py. O agrupamento family->funds é feito no
-- backend (sem cálculo). Refrescado por matview_refresh (passo datalake).

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fund_holders_mv AS
WITH map AS (
    SELECT DISTINCT upper(ticker) AS ticker, upper(cusip) AS cusip
    FROM sec_cusip_ticker_map
    WHERE cusip IS NOT NULL AND ticker IS NOT NULL
),
bounds AS (SELECT max(report_date) AS m FROM nport_holdings_history)
SELECT
    map.ticker,
    n.cik AS registrant_cik,
    COALESCE(fam.entity_name, sc.entity_name, 'CIK ' || n.cik) AS family,
    n.series_id,
    COALESCE(sc.series_name, n.series_id) AS fund_name,
    fv.instrument_id AS instrument_id,
    max(n.issuer_name) AS issuer_name,
    sum(n.quantity) AS quantity,
    sum(n.market_value) AS market_value,
    max(n.pct_nav_0) AS pct_of_nav,
    max(n.pct_nav_1) AS pct_nav_q1,
    max(n.pct_nav_2) AS pct_nav_q2,
    max(n.pct_nav_3) AS pct_nav_q3,
    max(n.report_date) AS report_date,
    map.cusip AS cusip
FROM nport_holdings_history n
JOIN map ON n.cusip = map.cusip
LEFT JOIN LATERAL (
    SELECT entity_name, series_name
    FROM sec_investment_company_series_class c
    WHERE c.series_id = n.series_id
    LIMIT 1
) sc ON true
LEFT JOIN LATERAL (
    SELECT entity_name
    FROM sec_investment_company_series_class c
    WHERE c.registrant_cik = n.cik
    LIMIT 1
) fam ON true
LEFT JOIN fund_instrument_map fv ON fv.series_id = n.series_id
WHERE n.report_date >= (SELECT m FROM bounds) - interval '130 days'
GROUP BY map.ticker, n.cik, fam.entity_name, sc.entity_name, n.series_id,
         sc.series_name, fv.instrument_id, map.cusip
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_fund_holders_mv_pk
    ON stock_fund_holders_mv (ticker, series_id);
CREATE INDEX IF NOT EXISTS stock_fund_holders_mv_ticker
    ON stock_fund_holders_mv (ticker);

REFRESH MATERIALIZED VIEW stock_fund_holders_mv;
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_stock_fund_holders_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Aplicar o DDL no datalake (ops, manual)**

```bash
psql "$DATALAKE_DB_URL" -f backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql
psql "$DATALAKE_DB_URL" -c "SELECT ticker, family, fund_name, pct_of_nav FROM stock_fund_holders_mv WHERE ticker = 'AAPL' LIMIT 5;"
```

Expected: linhas retornadas.

- [ ] **Step 6: Commit**

```bash
git add backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql backend/tests/test_stock_fund_holders_mv_sql.py
git commit -m "feat(matview): add stock_fund_holders_mv DDL (B2)"
```

---

## Task 3: DDL `holding_reverse_lookup_mv` (B3, lado 13F)

**Files:**
- Create: `backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql`
- Test: `backend/tests/test_holding_reverse_lookup_mv_sql.py`

**Interfaces:**
- Produces: MV B3 (lado institucional) com o shape e índice UNIQUE da seção Interfaces, no datalake DB.

**Contexto e SPLIT EXPLÍCITO (CRÍTICO):** `fetch_holding_reverse_lookup` (`backend/app/services/fund_dossier_tier_b.py:1471-1527`) tem **dois lados**:
1. **Lado de exposições de fundo** (`_fund_exposures_for_cusip`, linhas 1427-1468): lê `fund_holdings` JOIN `funds_v` no **app DB** (`session`). `funds_v` é uma view de catálogo dinâmico, org-scoped, que **não** se materializa globalmente nesta migração. **Decisão de placement: este lado permanece leitura on-demand no app DB, inalterado.** A álgebra é leve (latest report por série + JOIN + LIMIT 50), não há cálculo Python — fica fora da MV de propósito.
2. **Lado institucional 13F** (`_REVERSE_LOOKUP_SQL`, linhas 1337-1364): lê `sec_13f_holdings` + `sec_managers` (LATERAL highest-AUM) no **datalake** (`datalake`). É o lado pesado (10,1M linhas) e por-cusip. **Este lado vira a MV `holding_reverse_lookup_mv` no datalake DB.**

Diferença do B1: o `_REVERSE_LOOKUP_SQL` casa `sec_managers.cik = h.cik` **sem `lpad`** e usa um `COALESCE` de **2 níveis** (`mgr.firm_name`, `'CIK ' || h.cik`) — sem `sec_13f_filer_name`. A MV preserva essa lógica exata (paridade), `LIMIT 100` por cusip aplicado na **leitura** (não na MV — a MV guarda todos para o `cusip`, a rota corta). Materializada por `(cusip, cik)`.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_holding_reverse_lookup_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_holding_reverse_lookup_mv.sql"
)


def test_schema_defines_b3_mv_with_2tier_name_and_unique_index():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS holding_reverse_lookup_mv" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS holding_reverse_lookup_mv_pk" in sql
    assert "REFRESH MATERIALIZED VIEW holding_reverse_lookup_mv;" in sql
    # Lado institucional: sec_13f_holdings + sec_managers (LATERAL highest-AUM).
    assert "FROM sec_13f_holdings h" in sql
    assert "ORDER BY m.aum_total DESC NULLS LAST" in sql
    # COALESCE de 2 níveis (sem sec_13f_filer_name, sem lpad — paridade com o SQL atual).
    assert "COALESCE(mgr.firm_name, 'CIK ' || h.cik)" in sql
    assert "lpad" not in sql
    assert "sec_13f_filer_name" not in sql
    # latest report_date por cusip.
    assert "max(report_date) AS period" in sql
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_holding_reverse_lookup_mv_sql.py -q`
Expected: FAIL (`FileNotFoundError`).

- [ ] **Step 3: Escrever o DDL**

```sql
-- backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql
-- B3 read-model (datalake DB), LADO INSTITUCIONAL apenas: holders 13F por cusip
-- no período mais recente daquele cusip. Espelha _REVERSE_LOOKUP_SQL de
-- backend/app/services/fund_dossier_tier_b.py (COALESCE de 2 níveis, sem lpad,
-- sem sec_13f_filer_name — paridade exata). O LIMIT 100 é aplicado na leitura,
-- não aqui. O lado de exposições de fundo (fund_holdings/funds_v) permanece no
-- app DB, on-demand (catálogo dinâmico, não materializado). Refrescado por
-- matview_refresh (passo datalake).

CREATE MATERIALIZED VIEW IF NOT EXISTS holding_reverse_lookup_mv AS
WITH latest AS (
    SELECT upper(cusip) AS cusip, max(report_date) AS period
    FROM sec_13f_holdings
    GROUP BY upper(cusip)
)
SELECT
    upper(h.cusip) AS cusip,
    h.cik,
    COALESCE(mgr.firm_name, 'CIK ' || h.cik) AS manager_name,
    h.report_date AS period,
    h.report_date,
    h.issuer_name AS name,
    h.market_value AS value_usd,
    h.shares
FROM sec_13f_holdings h
JOIN latest l ON l.cusip = upper(h.cusip) AND l.period = h.report_date
LEFT JOIN LATERAL (
    SELECT m.firm_name
    FROM sec_managers m
    WHERE m.cik = h.cik AND m.firm_name IS NOT NULL
    ORDER BY m.aum_total DESC NULLS LAST
    LIMIT 1
) mgr ON true
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS holding_reverse_lookup_mv_pk
    ON holding_reverse_lookup_mv (cusip, cik);

REFRESH MATERIALIZED VIEW holding_reverse_lookup_mv;
```

- [ ] **Step 4: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_holding_reverse_lookup_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Aplicar o DDL no datalake (ops, manual)**

```bash
psql "$DATALAKE_DB_URL" -f backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql
psql "$DATALAKE_DB_URL" -c "SELECT cusip, cik, manager_name, value_usd FROM holding_reverse_lookup_mv LIMIT 5;"
```

Expected: linhas retornadas.

- [ ] **Step 6: Commit**

```bash
git add backend/db/ddl/2026-06-21_holding_reverse_lookup_mv.sql backend/tests/test_holding_reverse_lookup_mv_sql.py
git commit -m "feat(matview): add holding_reverse_lookup_mv DDL (B3 institutional side)"
```

---

## Task 4: Estender o worker `matview_refresh` para os MVs do datalake

**Files:**
- Modify (ou Create se ausente, vide Baseline): `E:/investintell-datalake-workers/src/workers/matview_refresh.py` (worktree limpo do `main`)
- Test: `E:/investintell-datalake-workers/tests/test_matview_refresh.py`

**Interfaces:**
- Consumes: `connect`, `advisory_lock`, `LOCK_MATVIEW_REFRESH`, `resolve_dsn` de `src/db.py`; os MVs das Tasks 1-3.
- Produces: `matview_refresh.run(dsn, *, datalake_dsn=None) -> {"refreshed": [...], "refreshed_datalake": [...]}`.

**Contexto:** os MVs do app DB (`price_latest_mv`/`nav_latest_mv`, Grupo D) são refrescados via `dsn` (app DB). Os MVs do Grupo B vivem no **datalake** e precisam ser refrescados via `DATALAKE_DB_URL`. Adiciona-se um **segundo passo** ao mesmo worker, conectando ao datalake. O DSN do datalake vem de `os.getenv("DATALAKE_DB_URL")` (passado por `run_worker.py`); se ausente, o passo datalake é pulado (sem erro). Cada `REFRESH CONCURRENTLY` roda em conexão autocommit própria. **Se o arquivo não existir** (Grupo D não mesclado no worktree), criar com o conteúdo completo abaixo (que já inclui o Grupo D + Grupo B); a constante `LOCK_MATVIEW_REFRESH = 900_210` então também precisa existir em `src/db.py` (adicionar se ausente). **Trabalhar num worktree limpo do `main` do repo de workers.**

- [ ] **Step 1: Garantir o worktree limpo e a constante de lock**

```bash
cd /e/investintell-datalake-workers && git worktree add ../investintell-datalake-workers-matview-b main
cd ../investintell-datalake-workers-matview-b
grep -n "LOCK_MATVIEW_REFRESH" src/db.py || echo "LOCK ausente — adicionar"
```

Se ausente, em `src/db.py` (junto às outras constantes `LOCK_*`):

```python
LOCK_MATVIEW_REFRESH = 900_210
```

- [ ] **Step 2: Escrever/atualizar o teste que falha**

```python
# tests/test_matview_refresh.py
import src.workers.matview_refresh as mr


class _FakeCursor:
    def __init__(self, sink): self._sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def execute(self, sql, params=None):
        self._sink.setdefault("sql", []).append(sql)
    def fetchone(self): return (True,)


class _FakeConn:
    def __init__(self, sink, tag): self._sink = sink; self._tag = tag
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def cursor(self): return _FakeCursor(self._sink)


def test_refresh_runs_app_and_datalake_mvs(monkeypatch):
    sink: dict = {}

    def _fake_connect(dsn=None, *, autocommit=False):
        sink.setdefault("dsns", []).append(dsn)
        sink["autocommit"] = autocommit or sink.get("autocommit")
        return _FakeConn(sink, dsn)

    monkeypatch.setattr(mr, "connect", _fake_connect)
    result = mr.run("postgres://app", datalake_dsn="postgres://lake")

    joined = "\n".join(sink["sql"])
    # App DB MVs (Grupo D).
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY price_latest_mv" in joined
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY nav_latest_mv" in joined
    # Datalake MVs (Grupo B).
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY stock_institutional_holders_mv" in joined
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY stock_fund_holders_mv" in joined
    assert "REFRESH MATERIALIZED VIEW CONCURRENTLY holding_reverse_lookup_mv" in joined
    assert result["refreshed"] == ["price_latest_mv", "nav_latest_mv"]
    assert result["refreshed_datalake"] == [
        "stock_institutional_holders_mv",
        "stock_fund_holders_mv",
        "holding_reverse_lookup_mv",
    ]


def test_datalake_step_skipped_when_no_dsn(monkeypatch):
    sink: dict = {}

    def _fake_connect(dsn=None, *, autocommit=False):
        sink.setdefault("dsns", []).append(dsn)
        return _FakeConn(sink, dsn)

    monkeypatch.setattr(mr, "connect", _fake_connect)
    result = mr.run("postgres://app", datalake_dsn=None)
    assert result["refreshed_datalake"] == []
```

- [ ] **Step 3: Rodar o teste e ver falhar**

Run: `cd /e/investintell-datalake-workers-matview-b && pytest tests/test_matview_refresh.py -q`
Expected: FAIL (`datalake_dsn` não aceito / MVs do datalake não refrescados).

- [ ] **Step 4: Implementar/atualizar o worker (arquivo completo)**

```python
# src/workers/matview_refresh.py
"""Refresca os read-model MVs do Light.

App DB (price_latest_mv / nav_latest_mv, Grupo D) e datalake DB
(stock_institutional_holders_mv / stock_fund_holders_mv /
holding_reverse_lookup_mv, Grupo B). Nenhum tem worker computacional próprio;
este worker apenas dá REFRESH ... CONCURRENTLY em cada um, num cron, em conexão
autocommit (CONCURRENTLY não roda em bloco de transação) e exige os índices
UNIQUE definidos nos DDLs em backend/db/ddl/. O advisory lock evita refreshes
concorrentes do mesmo conjunto entre execuções.
"""
from __future__ import annotations

import os

from src.db import LOCK_MATVIEW_REFRESH, advisory_lock, connect

_APP_MVS = ["price_latest_mv", "nav_latest_mv"]
_DATALAKE_MVS = [
    "stock_institutional_holders_mv",
    "stock_fund_holders_mv",
    "holding_reverse_lookup_mv",
]


def _refresh_all(dsn: str, mvs: list[str]) -> list[str]:
    refreshed: list[str] = []
    with connect(dsn, autocommit=True) as conn:
        for mv in mvs:
            with conn.cursor() as cur:
                cur.execute(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {mv}")
            refreshed.append(mv)
    return refreshed


def run(dsn: str, *, datalake_dsn: str | None = None) -> dict:
    if datalake_dsn is None:
        datalake_dsn = os.getenv("DATALAKE_DB_URL")
    # Lock só serializa este worker contra si mesmo; CONCURRENTLY precisa de
    # autocommit, então cada REFRESH roda em conexão autocommit própria.
    with connect(dsn) as guard:
        with advisory_lock(guard, LOCK_MATVIEW_REFRESH) as got:
            if not got:
                return {"refreshed": [], "refreshed_datalake": [], "skipped": "lock_busy"}
            refreshed = _refresh_all(dsn, _APP_MVS)
            refreshed_datalake: list[str] = []
            if datalake_dsn:
                refreshed_datalake = _refresh_all(datalake_dsn, _DATALAKE_MVS)
            return {"refreshed": refreshed, "refreshed_datalake": refreshed_datalake}
```

Nota: os nomes em `_APP_MVS`/`_DATALAKE_MVS` são literais fixos do próprio código (não input externo) — sem risco de injeção.

- [ ] **Step 5: Garantir o registro no dispatcher (se Grupo D não mesclado)**

Se `matview_refresh` não estiver na string de uso de `src/run_worker.py`, adicionar (o dispatch é dinâmico via `importlib`, mas a mensagem de uso deve listá-lo). Conferir também que `run_worker.py` passa o DSN do datalake quando presente — o worker já faz fallback a `os.getenv("DATALAKE_DB_URL")`, então nenhuma mudança em `run_worker.py` é estritamente necessária (a env var basta).

- [ ] **Step 6: Rodar o teste e ver passar**

Run: `cd /e/investintell-datalake-workers-matview-b && pytest tests/test_matview_refresh.py -q`
Expected: PASS (2 testes).

- [ ] **Step 7: Smoke local (opcional, self-skip)**

```bash
WORKER=matview_refresh \
  DATABASE_URL="host=localhost port=5434 dbname=investintell_alloc user=investintell password=investintell" \
  DATALAKE_DB_URL="host=localhost port=5434 dbname=investintell_alloc user=investintell password=investintell" \
  python -m src.run_worker
```

Expected: JSON com `refreshed` + `refreshed_datalake` populados (ou `refreshed_datalake: []` se os MVs do datalake não estiverem aplicados localmente).

- [ ] **Step 8: Deploy / cron (ops)**

Garantir que o serviço `matview-refresh` no Railway tem `DATALAKE_DB_URL` setado (além de `DATABASE_URL`). A cadência pode ser alinhada à ingestão SEC (N-PORT 31/01, 13F trimestral têm lag natural — não precisa diária; ex.: diário às 07:30 UTC cobre o lag do refresh de preço, e os dados SEC simplesmente repetem entre ingestões).

```bash
railway up --service matview-refresh
# Dashboard: WORKER=matview_refresh, DATABASE_URL=<app DSN>, DATALAKE_DB_URL=<datalake DSN>.
```

- [ ] **Step 9: Commit e limpeza do worktree**

```bash
git add src/db.py src/workers/matview_refresh.py tests/test_matview_refresh.py
git commit -m "feat(matview): refresh Group B datalake MVs in matview_refresh worker"
cd /e/investintell-datalake-workers && git worktree remove ../investintell-datalake-workers-matview-b
```

---

## Task 5: Modelos ORM dos 3 MVs + registro em `__init__.py`

**Files:**
- Create: `backend/app/models/stock_holders_mv.py`
- Modify: `backend/app/models/__init__.py`
- Test: `backend/tests/test_stock_holders_mv_models.py`

**Interfaces:**
- Consumes: os MVs das Tasks 1-3 (no datalake DB).
- Produces: `StockInstitutionalHolder`, `StockFundHolderRow`, `HoldingReverseLookupRow` ORM, conforme seção Interfaces.

**Contexto — padrão a espelhar** (`backend/app/models/fund.py` `FundRiskLatest`; `backend/app/models/price_latest.py` `PriceLatest`/`NavLatest`): MV mapeado como modelo ORM read-only via `Base`, `mapped_column` tipado, chave composta como `primary_key=True` em cada coluna da UNIQUE. Os MVs vivem no datalake, mas o ORM só descreve colunas (a sessão de datalake decide o banco) — registrar em `__init__.py` para o metadata e imports diretos.

- [ ] **Step 1: Escrever o teste que falha**

```python
# backend/tests/test_stock_holders_mv_models.py
from app.models import (
    HoldingReverseLookupRow,
    StockFundHolderRow,
    StockInstitutionalHolder,
)


def test_b1_model_maps_columns_and_composite_pk():
    assert StockInstitutionalHolder.__tablename__ == "stock_institutional_holders_mv"
    cols = set(StockInstitutionalHolder.__table__.columns.keys())
    assert {
        "ticker", "cik", "manager_name", "report_date", "cusip", "issuer_name",
        "shares", "market_value", "entry_date", "entry_price", "current_price",
        "shares_outstanding",
    } <= cols
    pk = set(StockInstitutionalHolder.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "cik", "cusip"}


def test_b2_model_maps_columns_and_composite_pk():
    assert StockFundHolderRow.__tablename__ == "stock_fund_holders_mv"
    cols = set(StockFundHolderRow.__table__.columns.keys())
    assert {
        "ticker", "registrant_cik", "family", "series_id", "fund_name",
        "instrument_id", "issuer_name", "quantity", "market_value", "pct_of_nav",
        "pct_nav_q1", "pct_nav_q2", "pct_nav_q3", "report_date", "cusip",
    } <= cols
    pk = set(StockFundHolderRow.__table__.primary_key.columns.keys())
    assert pk == {"ticker", "series_id"}


def test_b3_model_maps_columns_and_composite_pk():
    assert HoldingReverseLookupRow.__tablename__ == "holding_reverse_lookup_mv"
    cols = set(HoldingReverseLookupRow.__table__.columns.keys())
    assert {
        "cusip", "cik", "manager_name", "period", "report_date", "name",
        "value_usd", "shares",
    } <= cols
    pk = set(HoldingReverseLookupRow.__table__.primary_key.columns.keys())
    assert pk == {"cusip", "cik"}
```

- [ ] **Step 2: Rodar o teste e ver falhar**

Run: `cd backend && pytest tests/test_stock_holders_mv_models.py -q`
Expected: FAIL (`ImportError` — nomes não exportados de `app.models`).

- [ ] **Step 3: Implementar os modelos**

```python
# backend/app/models/stock_holders_mv.py
"""Modelos ORM read-only sobre os MVs do Grupo B (datalake DB).

Espelham FundRiskLatest / PriceLatest: MV mapeado via Base, lido por chave/IN,
nunca escrito. Refrescados pelo worker matview_refresh (passo datalake).
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import Date, Numeric, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StockInstitutionalHolder(Base):
    __tablename__ = "stock_institutional_holders_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, primary_key=True)
    cusip: Mapped[str] = mapped_column(String, primary_key=True)
    manager_name: Mapped[str] = mapped_column(String, nullable=False)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    shares: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    entry_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    entry_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    current_price: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares_outstanding: Mapped[float | None] = mapped_column(Numeric, nullable=True)


class StockFundHolderRow(Base):
    __tablename__ = "stock_fund_holders_mv"

    ticker: Mapped[str] = mapped_column(String, primary_key=True)
    series_id: Mapped[str] = mapped_column(String, primary_key=True)
    registrant_cik: Mapped[str] = mapped_column(String, nullable=False)
    family: Mapped[str] = mapped_column(String, nullable=False)
    fund_name: Mapped[str] = mapped_column(String, nullable=False)
    instrument_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    issuer_name: Mapped[str | None] = mapped_column(String, nullable=True)
    quantity: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    market_value: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_of_nav: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q1: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q2: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    pct_nav_q3: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    cusip: Mapped[str | None] = mapped_column(String, nullable=True)


class HoldingReverseLookupRow(Base):
    __tablename__ = "holding_reverse_lookup_mv"

    cusip: Mapped[str] = mapped_column(String, primary_key=True)
    cik: Mapped[str] = mapped_column(String, primary_key=True)
    manager_name: Mapped[str] = mapped_column(String, nullable=False)
    period: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    report_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    name: Mapped[str | None] = mapped_column(String, nullable=True)
    value_usd: Mapped[float | None] = mapped_column(Numeric, nullable=True)
    shares: Mapped[float | None] = mapped_column(Numeric, nullable=True)
```

- [ ] **Step 4: Registrar em `__init__.py`**

Em `backend/app/models/__init__.py`, adicionar o import (após a linha de `price_latest`) e as três entradas em `__all__`:

```python
from app.models.stock_holders_mv import (
    HoldingReverseLookupRow,
    StockFundHolderRow,
    StockInstitutionalHolder,
)
```

E em `__all__` (mantendo ordem alfabética aproximada do arquivo):

```python
    "HoldingReverseLookupRow",
    "StockFundHolderRow",
    "StockInstitutionalHolder",
```

- [ ] **Step 5: Rodar o teste e ver passar**

Run: `cd backend && pytest tests/test_stock_holders_mv_models.py -q`
Expected: PASS (3 testes).

- [ ] **Step 6: Commit**

```bash
git add app/models/stock_holders_mv.py app/models/__init__.py tests/test_stock_holders_mv_models.py
git commit -m "feat(models): add Group B holders MV ORM models"
```

---

## Task 6: B1/B2 — `stock_holders.py` lê do MV com fallback, atrás de flag

**Files:**
- Modify: `backend/app/core/config.py` (flag `use_holders_db_first`)
- Modify: `backend/app/services/stock_holders.py`
- Test: `backend/tests/test_stock_holders_db_first.py`

**Interfaces:**
- Consumes: `StockInstitutionalHolder`, `StockFundHolderRow` (Task 5); `settings.use_holders_db_first`.
- Produces: `fetch_stock_holders(datalake, ticker, *, use_db_first=None)` e `fetch_stock_fund_holders(datalake, ticker, *, use_db_first=None)` — mesmo tipo de retorno de hoje.

**Contexto:** as duas funções (`fetch_stock_holders` 119-187, `fetch_stock_fund_holders` 246-310) hoje executam `_HOLDERS_SQL`/`_FUND_HOLDERS_SQL` (texto cru) contra `datalake`. O caminho novo lê do ORM MV (sem cálculo). O reshape/montagem (`StockHolder`, `_pct`, `_ret`, agrupamento family→funds) **permanece idêntico** — só muda a fonte das linhas. O fallback ao SQL legado cobre o lag do refresh (MV pode não ter um ticker recém-enriquecido) e o caso de o MV não existir ainda no banco (transição). Quando `use_db_first` é `None`, lê `settings.use_holders_db_first`.

- [ ] **Step 1: Adicionar a flag de settings**

Em `backend/app/core/config.py`, na classe `Settings`:

```python
    # DB-first Grupo B: quando True, holders/holders-funds/reverse-lookup leem
    # dos MVs pré-computados (com fallback ao SQL legado p/ entidades ausentes).
    use_holders_db_first: bool = False
```

- [ ] **Step 2: Escrever os testes que falham (paridade de reshape, flag-off, no-heavy-SQL)**

```python
# backend/tests/test_stock_holders_db_first.py
import datetime as dt
import uuid

import pytest

from app.services import stock_holders

_PERIOD = dt.date(2026, 3, 31)
_ENTRY = dt.date(2024, 6, 30)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeSession:
    """Roteia execute() por marcador na query stringificada (MV vs legado)."""
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "stock_institutional_holders_mv" in text or "stock_fund_holders_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


def _b1_row(**over):
    base = {
        "ticker": "AAPL", "cik": "0000320193", "manager_name": "Vanguard Group Inc",
        "report_date": _PERIOD, "cusip": "037833100", "issuer_name": "Apple Inc",
        "shares": 1_000_000.0, "market_value": 200_000_000.0, "entry_date": _ENTRY,
        "entry_price": 100.0, "current_price": 110.0, "shares_outstanding": 15_000_000_000.0,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b1_mv_path_reshapes_and_computes_pct_and_return():
    session = _FakeSession(mv_rows=[_b1_row()])
    resp = await stock_holders.fetch_stock_holders(session, "AAPL", use_db_first=True)
    assert resp.ticker == "AAPL"
    assert resp.holder_count == 1
    h = resp.holders[0]
    assert h.manager_name == "Vanguard Group Inc"
    assert h.pct_outstanding == pytest.approx(1_000_000.0 / 15_000_000_000.0)
    assert h.position_return == pytest.approx(110.0 / 100.0 - 1.0)
    # MV path NÃO toca a hypertable crua.
    assert any("stock_institutional_holders_mv" in q for q in session.executed)
    assert all("FROM sec_13f_holdings h" not in q for q in session.executed)


@pytest.mark.asyncio
async def test_b1_mv_empty_returns_empty_state():
    session = _FakeSession(mv_rows=[])
    resp = await stock_holders.fetch_stock_holders(session, "ZZZZ", use_db_first=True)
    assert resp.empty_state is not None
    assert resp.holders == []


@pytest.mark.asyncio
async def test_b1_flag_off_uses_legacy_sql():
    session = _FakeSession(legacy_rows=[_b1_row()])
    resp = await stock_holders.fetch_stock_holders(session, "AAPL", use_db_first=False)
    assert resp.holder_count == 1
    assert all("stock_institutional_holders_mv" not in q for q in session.executed)


def _b2_row(**over):
    base = {
        "ticker": "AAPL", "registrant_cik": "0000102909", "family": "Vanguard",
        "series_id": "S000002277", "fund_name": "Vanguard 500 Index Fund",
        "instrument_id": uuid.uuid4(), "issuer_name": "Apple Inc",
        "quantity": 500.0, "market_value": 1_000_000.0, "pct_of_nav": 6.5,
        "pct_nav_q1": 6.4, "pct_nav_q2": 6.3, "pct_nav_q3": 6.2,
        "report_date": _PERIOD, "cusip": "037833100",
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b2_mv_path_groups_family_to_funds():
    rows = [
        _b2_row(series_id="S1", fund_name="Fund A", market_value=1_000_000.0),
        _b2_row(series_id="S2", fund_name="Fund B", market_value=2_000_000.0),
    ]
    session = _FakeSession(mv_rows=rows)
    resp = await stock_holders.fetch_stock_fund_holders(session, "AAPL", use_db_first=True)
    assert resp.family_count == 1
    assert resp.fund_count == 2
    fam = resp.families[0]
    assert fam.family == "Vanguard"
    assert fam.fund_count == 2
    assert fam.market_value == pytest.approx(3_000_000.0)
    assert any("stock_fund_holders_mv" in q for q in session.executed)
    assert all("FROM nport_holdings_history" not in q for q in session.executed)


@pytest.mark.asyncio
async def test_b2_flag_off_uses_legacy_sql():
    session = _FakeSession(legacy_rows=[_b2_row()])
    resp = await stock_holders.fetch_stock_fund_holders(session, "AAPL", use_db_first=False)
    assert resp.fund_count == 1
    assert all("stock_fund_holders_mv" not in q for q in session.executed)
```

- [ ] **Step 3: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_stock_holders_db_first.py -q`
Expected: FAIL (assinatura sem `use_db_first` / sem caminho MV).

- [ ] **Step 4: Reescrever as duas funções (legado vira helper, caminho MV novo)**

Em `backend/app/services/stock_holders.py`: adicionar imports, extrair os corpos atuais em helpers privados, e introduzir os wrappers com caminho MV + fallback. As funções de reshape (`StockHolder`, `_pct`, `_ret`, agrupamento) são **fatoradas em helpers compartilhados** para que MV e legado produzam o mesmo objeto.

Adicionar no topo (junto aos imports existentes):

```python
from sqlalchemy import select

from app.core.config import get_settings
from app.models.stock_holders_mv import StockFundHolderRow, StockInstitutionalHolder
```

Renomear o corpo atual de `fetch_stock_holders` (linhas 119-187) para `_fetch_stock_holders_legacy(datalake, norm)` recebendo o ticker já normalizado, retornando `StockHoldersResponse` — **mover verbatim** o bloco `try/execute(_HOLDERS_SQL)...return StockHoldersResponse(...)`. Extrair o reshape (a partir de `typed = cast(...)` até o `return`) em:

```python
def _build_holders_response(
    norm: str, rows: Sequence[Mapping[str, Any]]
) -> StockHoldersResponse:
    if not rows:
        return StockHoldersResponse(
            ticker=norm,
            empty_state=_empty(
                f"No 13F institutional holders are mapped for {norm}.",
                "sec_13f_holdings",
            ),
        )
    typed = cast(Sequence[Mapping[str, Any]], rows)
    shares_out = _float(typed[0]["shares_outstanding"])

    def _pct(shares: float | None) -> float | None:
        if not shares_out or shares is None:
            return None
        return shares / shares_out

    def _ret(row: Mapping[str, Any]) -> float | None:
        entry = _float(row["entry_price"])
        cur = _float(row["current_price"])
        if not entry or cur is None:
            return None
        return cur / entry - 1.0

    holders = []
    for row in typed:
        shares = _float(row["shares"])
        holders.append(
            StockHolder(
                cik=row["cik"],
                manager_name=row["manager_name"],
                shares=shares,
                market_value=_float(row["market_value"]),
                pct_outstanding=_pct(shares),
                position_return=_ret(row),
                entry_date=row["entry_date"],
            )
        )
    total_mv = sum(h.market_value for h in holders if h.market_value is not None)
    first = typed[0]
    return StockHoldersResponse(
        ticker=norm,
        cusip=first["cusip"],
        security_name=first["issuer_name"],
        period=first["report_date"],
        holder_count=len(holders),
        total_market_value=total_mv or None,
        shares_outstanding=shares_out,
        holders=holders,
    )
```

`_fetch_stock_holders_legacy` então termina com `return _build_holders_response(norm, rows)` em vez do reshape inline. Novo wrapper público:

```python
async def fetch_stock_holders(
    datalake: AsyncSession,
    ticker: str,
    *,
    use_db_first: bool | None = None,
) -> StockHoldersResponse:
    norm = ticker.strip().upper()
    if not norm:
        raise ValueError("Ticker must not be empty.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first
    if not use_db_first:
        return await _fetch_stock_holders_legacy(datalake, norm)

    try:
        rows = (
            await datalake.execute(
                select(
                    StockInstitutionalHolder.cik,
                    StockInstitutionalHolder.manager_name,
                    StockInstitutionalHolder.report_date,
                    StockInstitutionalHolder.cusip,
                    StockInstitutionalHolder.issuer_name,
                    StockInstitutionalHolder.shares,
                    StockInstitutionalHolder.market_value,
                    StockInstitutionalHolder.entry_date,
                    StockInstitutionalHolder.shares_outstanding,
                    StockInstitutionalHolder.entry_price,
                    StockInstitutionalHolder.current_price,
                )
                .where(StockInstitutionalHolder.ticker == norm)
                .order_by(StockInstitutionalHolder.market_value.desc().nullslast())
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read 13F holders for {norm}."
        ) from exc
    if not rows:
        # MV vazio para este ticker → fallback ao SQL legado (cobre lag de refresh
        # e MV ainda não aplicada).
        return await _fetch_stock_holders_legacy(datalake, norm)
    return _build_holders_response(norm, rows)
```

Análogo para `fetch_stock_fund_holders`: renomear o corpo atual (246-310) para `_fetch_stock_fund_holders_legacy(datalake, norm)`, extrair o reshape (a partir de `typed = cast(...)`) em `_build_fund_holders_response(norm, rows)` **verbatim** (o bloco que monta `families`/`FundFamily`/`FundHolder` e o `return StockFundHoldersResponse(...)`, mais o early-return de empty-state quando `not rows`), e o wrapper:

```python
async def fetch_stock_fund_holders(
    datalake: AsyncSession,
    ticker: str,
    *,
    use_db_first: bool | None = None,
) -> StockFundHoldersResponse:
    norm = ticker.strip().upper()
    if not norm:
        raise ValueError("Ticker must not be empty.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first
    if not use_db_first:
        return await _fetch_stock_fund_holders_legacy(datalake, norm)

    try:
        rows = (
            await datalake.execute(
                select(
                    StockFundHolderRow.registrant_cik,
                    StockFundHolderRow.family,
                    StockFundHolderRow.series_id,
                    StockFundHolderRow.fund_name,
                    StockFundHolderRow.instrument_id,
                    StockFundHolderRow.issuer_name,
                    StockFundHolderRow.quantity,
                    StockFundHolderRow.market_value,
                    StockFundHolderRow.pct_of_nav,
                    StockFundHolderRow.pct_nav_q1,
                    StockFundHolderRow.pct_nav_q2,
                    StockFundHolderRow.pct_nav_q3,
                    StockFundHolderRow.report_date,
                    StockFundHolderRow.cusip,
                )
                .where(StockFundHolderRow.ticker == norm)
                .order_by(
                    StockFundHolderRow.family,
                    StockFundHolderRow.market_value.desc().nullslast(),
                )
            )
        ).mappings().all()
    except SQLAlchemyError as exc:
        raise StockHoldersSourceError(
            f"Failed to read N-PORT fund holders for {norm}."
        ) from exc
    if not rows:
        return await _fetch_stock_fund_holders_legacy(datalake, norm)
    return _build_fund_holders_response(norm, rows)
```

Nota: `_build_fund_holders_response` deve conter o early-return de empty-state (o bloco `if not rows: return StockFundHoldersResponse(... empty_state=...)`) para o caso de o legado também voltar vazio.

- [ ] **Step 5: Rodar e ver passar**

Run: `cd backend && pytest tests/test_stock_holders_db_first.py -q`
Expected: PASS (6 testes).

- [ ] **Step 6: Regressão dos testes existentes de holders**

Run: `cd backend && pytest tests/test_stocks_route.py -q`
Expected: PASS (flag off por default → comportamento idêntico; assinatura nova é kwarg opcional).

- [ ] **Step 7: Commit**

```bash
git add app/core/config.py app/services/stock_holders.py tests/test_stock_holders_db_first.py
git commit -m "feat(stocks): read holders/holders-funds from MVs behind use_holders_db_first"
```

---

## Task 7: B3 — `reverse-lookup` lê o lado 13F do MV com fallback, atrás de flag

**Files:**
- Modify: `backend/app/services/fund_dossier_tier_b.py`
- Test: `backend/tests/test_reverse_lookup_db_first.py`

**Interfaces:**
- Consumes: `HoldingReverseLookupRow` (Task 5); `settings.use_holders_db_first` (Task 6).
- Produces: `fetch_holding_reverse_lookup(session, datalake, cusip, *, use_db_first=None)` — mesmo tipo de retorno.

**Contexto e SPLIT (repetido por clareza):** `fetch_holding_reverse_lookup` (1471-1527) tem dois lados. O **lado de exposições de fundo** (`_fund_exposures_for_cusip`, app DB via `session`) **NÃO muda** — permanece on-demand. Só o **lado institucional** (`_REVERSE_LOOKUP_SQL` contra `datalake`) passa a ler do MV `holding_reverse_lookup_mv`. O reshape (`ReverseLookupInstitution`, escolha de `security_name`/`period`, lógica de `empty_state`) permanece idêntico — só muda a fonte das `rows`. O `LIMIT 100` (que estava no SQL) passa a ser aplicado na **leitura** (`.limit(100)`). O fallback ao SQL legado cobre lag/ausência do MV.

- [ ] **Step 1: Escrever os testes que falham**

```python
# backend/tests/test_reverse_lookup_db_first.py
import datetime as dt

import pytest

from app.services import fund_dossier_tier_b as tier_b

_PERIOD = dt.date(2026, 3, 31)


class _Result:
    def __init__(self, rows): self._rows = rows
    def mappings(self): return self
    def all(self): return self._rows


class _FakeDatalake:
    def __init__(self, *, mv_rows=None, legacy_rows=None):
        self._mv_rows = mv_rows or []
        self._legacy_rows = legacy_rows or []
        self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        if "holding_reverse_lookup_mv" in text:
            return _Result(self._mv_rows)
        return _Result(self._legacy_rows)


def _inst_row(**over):
    base = {
        "cik": "0001067983", "manager_name": "Berkshire Hathaway Inc",
        "period": _PERIOD, "report_date": _PERIOD, "name": "Apple Inc",
        "value_usd": 150_000_000_000.0, "shares": 900_000_000.0,
    }
    base.update(over)
    return base


@pytest.mark.asyncio
async def test_b3_mv_path_reads_institutions_from_mv(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(mv_rows=[_inst_row()])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=True
    )
    assert resp.cusip == "037833100"
    assert len(resp.institutions) == 1
    assert resp.institutions[0].manager_name == "Berkshire Hathaway Inc"
    assert resp.security_name == "Apple Inc"
    assert any("holding_reverse_lookup_mv" in q for q in datalake.executed)
    # MV path NÃO toca a hypertable crua.
    assert all("FROM sec_13f_holdings h" not in q for q in datalake.executed)


@pytest.mark.asyncio
async def test_b3_mv_empty_sets_empty_state(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(mv_rows=[])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=True
    )
    assert resp.institutions == []
    assert resp.empty_state is not None


@pytest.mark.asyncio
async def test_b3_flag_off_uses_legacy_sql(monkeypatch):
    async def _fake_fund_side(session, cusip):
        return []
    monkeypatch.setattr(tier_b, "_fund_exposures_for_cusip", _fake_fund_side)

    datalake = _FakeDatalake(legacy_rows=[_inst_row()])
    resp = await tier_b.fetch_holding_reverse_lookup(
        object(), datalake, "037833100", use_db_first=False
    )
    assert len(resp.institutions) == 1
    assert all("holding_reverse_lookup_mv" not in q for q in datalake.executed)
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `cd backend && pytest tests/test_reverse_lookup_db_first.py -q`
Expected: FAIL (sem `use_db_first` / sem caminho MV).

- [ ] **Step 3: Reescrever a função**

Em `backend/app/services/fund_dossier_tier_b.py`: adicionar imports e fatorar o lado institucional em dois helpers (legado e MV) + reshape compartilhado. O lado de fundo (`_fund_exposures_for_cusip`) e o reshape de instituições permanecem.

Adicionar aos imports (junto aos existentes):

```python
from sqlalchemy import select

from app.core.config import get_settings
from app.models.stock_holders_mv import HoldingReverseLookupRow
```

Substituir o corpo de `fetch_holding_reverse_lookup` (1471-1527) por:

```python
def _build_reverse_lookup_response(
    normalized: str,
    institution_rows: Sequence[Mapping[str, Any]],
    fund_exposures: list[ReverseLookupFundExposure],
    source_empty_state: EmptyState | None,
) -> HoldingReverseLookupResponse:
    institutions = [
        ReverseLookupInstitution(
            cik=row["cik"],
            manager_name=row["manager_name"],
            value_usd=_float(row["value_usd"]),
            shares=_float(row["shares"]),
            period=row["period"],
            report_date=row["report_date"],
        )
        for row in institution_rows
    ]
    security_name = (
        institution_rows[0]["name"]
        if institution_rows
        else (fund_exposures[0].issuer_name if fund_exposures else None)
    )
    period = institution_rows[0]["period"] if institution_rows else None
    empty_state = source_empty_state
    if empty_state is None and not institutions:
        empty_state = _empty(
            "No 13F institutional holders matched this CUSIP.", "sec_13f_holdings"
        )
    if not institutions and not fund_exposures:
        empty_state = _empty(
            "No fund exposure or 13F institutional holder matched this CUSIP."
        )
    return HoldingReverseLookupResponse(
        cusip=normalized,
        security_name=security_name,
        period=period,
        institutions=institutions,
        fund_exposures=fund_exposures,
        empty_state=empty_state,
    )


async def _reverse_lookup_institutions_legacy(
    datalake: AsyncSession, normalized: str
) -> tuple[list[Mapping[str, Any]], EmptyState | None]:
    try:
        rows = (
            await datalake.execute(text(_REVERSE_LOOKUP_SQL), {"cusip": normalized})
        ).mappings().all()
    except SQLAlchemyError as exc:
        if _is_missing_relation(exc):
            return [], _empty(
                "SEC 13F holdings tables are not deployed yet.", "sec_13f_holdings"
            )
        raise _source_error("sec_13f_holdings", exc) from exc
    return list(rows), None


async def fetch_holding_reverse_lookup(
    session: AsyncSession,
    datalake: AsyncSession,
    cusip: str,
    *,
    use_db_first: bool | None = None,
) -> HoldingReverseLookupResponse:
    normalized = _normalize_cusip(cusip)
    if normalized is None:
        raise ValueError(f"Invalid CUSIP {cusip!r}.")
    if use_db_first is None:
        use_db_first = get_settings().use_holders_db_first

    # Lado de exposições de fundo: SEMPRE on-demand no app DB (catálogo dinâmico,
    # não materializado nesta migração — split documentado no plano/spec §7 B3).
    fund_exposures = await _fund_exposures_for_cusip(session, normalized)

    # Lado institucional: MV quando habilitado, com fallback ao SQL legado.
    institution_rows: list[Mapping[str, Any]] = []
    source_empty_state: EmptyState | None = None
    if use_db_first:
        try:
            rows = (
                await datalake.execute(
                    select(
                        HoldingReverseLookupRow.cik,
                        HoldingReverseLookupRow.manager_name,
                        HoldingReverseLookupRow.period,
                        HoldingReverseLookupRow.report_date,
                        HoldingReverseLookupRow.name,
                        HoldingReverseLookupRow.value_usd,
                        HoldingReverseLookupRow.shares,
                    )
                    .where(HoldingReverseLookupRow.cusip == normalized)
                    .order_by(HoldingReverseLookupRow.value_usd.desc().nullslast())
                    .limit(100)
                )
            ).mappings().all()
        except SQLAlchemyError as exc:
            if _is_missing_relation(exc):
                rows = []
            else:
                raise _source_error("sec_13f_holdings", exc) from exc
        if rows:
            institution_rows = list(rows)
        else:
            # MV vazio/ausente → fallback ao SQL legado.
            institution_rows, source_empty_state = (
                await _reverse_lookup_institutions_legacy(datalake, normalized)
            )
    else:
        institution_rows, source_empty_state = (
            await _reverse_lookup_institutions_legacy(datalake, normalized)
        )

    return _build_reverse_lookup_response(
        normalized, institution_rows, fund_exposures, source_empty_state
    )
```

Nota: confirmar que `EmptyState`, `ReverseLookupInstitution`, `ReverseLookupFundExposure`, `HoldingReverseLookupResponse`, `Mapping`, `Sequence`, `Any` já estão importados no módulo (estão — usados pelo corpo atual e por outras funções).

- [ ] **Step 4: Rodar e ver passar**

Run: `cd backend && pytest tests/test_reverse_lookup_db_first.py -q`
Expected: PASS (3 testes).

- [ ] **Step 5: Regressão dos testes existentes de tier_b**

Run: `cd backend && pytest tests/test_fund_dossier_tier_b_service.py tests/test_fund_tier_b_routes.py -q`
Expected: PASS (flag off por default → comportamento idêntico; o teste de rota `test_holding_reverse_lookup_*` faz monkeypatch de `fetch_holding_reverse_lookup`, então a assinatura nova com kwarg opcional não quebra).

- [ ] **Step 6: Commit**

```bash
git add app/services/fund_dossier_tier_b.py tests/test_reverse_lookup_db_first.py
git commit -m "feat(funds): read reverse-lookup 13F side from MV behind use_holders_db_first"
```

---

## Task 8: Paridade, regressão e documentação de frescor (suíte completa)

**Files:**
- Modify (se necessário): docstrings em `backend/app/services/stock_holders.py` e `backend/app/services/fund_dossier_tier_b.py`
- Test: rodar suítes completas + um teste de paridade reshape MV-vs-legado

**Interfaces:**
- Consumes: tudo acima.

**Contexto:** com a flag **desligada** (default), os três endpoints se comportam exatamente como hoje. As rotas (`get_stock_holders`/`get_stock_fund_holders` em `backend/app/api/routes/stocks.py:319-354`, `get_holding_reverse_lookup` em `backend/app/api/routes/funds.py:446-463`) **não precisam mudar** — chamam as funções sem passar `use_db_first`, herdando a flag. A paridade real (números idênticos) é garantida porque o reshape é o **mesmo helper** para MV e legado, e os DDLs reproduzem a álgebra SQL verbatim.

- [ ] **Step 1: Teste de paridade de reshape (MV-row vs legacy-row produzem o mesmo objeto)**

Adicionar ao `tests/test_stock_holders_db_first.py`:

```python
@pytest.mark.asyncio
async def test_b1_parity_mv_vs_legacy_same_payload():
    row = _b1_row()
    mv = await stock_holders.fetch_stock_holders(
        _FakeSession(mv_rows=[row]), "AAPL", use_db_first=True
    )
    legacy = await stock_holders.fetch_stock_holders(
        _FakeSession(legacy_rows=[row]), "AAPL", use_db_first=False
    )
    assert mv.model_dump() == legacy.model_dump()
```

Run: `cd backend && pytest tests/test_stock_holders_db_first.py::test_b1_parity_mv_vs_legacy_same_payload -q`
Expected: PASS (mesma linha em ambas as fontes ⇒ payload idêntico; prova que a única diferença é a fonte, não o cálculo).

- [ ] **Step 2: Localizar todos os callers das três funções**

Run: `cd backend && grep -rn "fetch_stock_holders\|fetch_stock_fund_holders\|fetch_holding_reverse_lookup" app tests`
Expected: confirmar que callers de produção (rotas) não passam `use_db_first` (herdam a flag) e toleram a assinatura nova.

- [ ] **Step 3: Documentar o split e o frescor (lag do refresh)**

No docstring de `fetch_holding_reverse_lookup`, registrar o split (lado de fundo on-demand no app DB; lado 13F do MV no datalake) e o lag aceito: o MV é refrescado por cron (`matview_refresh`), então um holding 13F recém-ingerido aparece só após o próximo refresh; cusips ausentes do MV usam o fallback ao SQL legado (sem regressão funcional). Idem nos docstrings de `fetch_stock_holders`/`fetch_stock_fund_holders` (fonte = MV com fallback à hypertable). Frescor é exposto ao frontend via os campos `period`/`report_date` já presentes nas respostas.

- [ ] **Step 4: Suíte completa do backend**

Run: `cd backend && pytest -q`
Expected: verde (sem novas falhas; flag off por default). As 24 falhas pré-existentes da suíte completa documentadas no Grupo D, se presentes, permanecem pré-existentes e não relacionadas.

- [ ] **Step 5: Commit**

```bash
git add app/services/stock_holders.py app/services/fund_dossier_tier_b.py tests/test_stock_holders_db_first.py
git commit -m "test(holders): MV-vs-legacy parity + freshness/split docs for Group B"
```

---

## Estratégia de rollout (pós-merge)

Seguindo a transição do spec (§12): com tudo mergeado e `use_holders_db_first=False`, nada muda em produção. Para ativar: aplicar os 3 DDLs no datalake (Tasks 1-3, Step 5), garantir que o serviço `matview-refresh` no Railway tem `DATALAKE_DB_URL` e refresca os MVs do datalake (Task 4, Step 8), confirmar MVs populados/frescos, ligar `use_holders_db_first=True` em staging, comparar os payloads dos três endpoints contra o caminho legado (registrar a comparação), e só então virar o default em produção. Depois de estável, remover o SQL legado (`_HOLDERS_SQL`, `_FUND_HOLDERS_SQL`, `_REVERSE_LOOKUP_SQL` e os helpers `_legacy`) — fora do escopo deste plano (passo final do §12).

---

## Self-Review

**Cobertura do escopo (spec §7 Grupo B + §11 + §12, e o REPORT autoritativo):**
- B1 `stocks/holders` → MV `stock_institutional_holders_mv` (Task 1) + ORM (Task 5) + leitura/flag/fallback (Task 6). Resolução de nome 3-níveis com `lpad(cik,10)` + LATERAL highest-AUM reproduzida dentro da MV. ✓
- Limitação de `entry_price` vs `price_latest_mv` tratada explicitamente: MV B1 mantém o subquery de `eod_prices` (primeiro `adj_close >= entry_date`); `price_latest_mv` NÃO usado. Documentado no Contexto da Task 1 e no Architecture. ✓
- B2 `stocks/holders/funds` → MV `stock_fund_holders_mv` (Task 2) + ORM (Task 5) + leitura/flag/fallback (Task 6). Família 3-níveis + trilha 4-trimestres dentro da MV; agrupamento family→funds é montagem fina em Python (sem cálculo). ✓
- B3 `holdings/{cusip}/reverse-lookup` → MV `holding_reverse_lookup_mv` (lado 13F, Task 3) + ORM (Task 5) + leitura/flag/fallback (Task 7). Split app-DB (fund_holdings/funds_v on-demand) vs datalake (13F materializado) documentado em Architecture, Task 3 Contexto e Task 7 Contexto. ✓
- DDL datado + test_*_sql string-assert + índice UNIQUE + populate inicial + ops-manual apply → Tasks 1/2/3 (cada uma com os 6 steps). ✓
- Adicionar os MVs ao worker `matview_refresh` em worktree limpo do repo de workers → Task 4 (com guard para o caso de o worker do Grupo D não estar presente; refresh em passo datalake separado). ✓
- ORM registrado em `__init__.py` → Task 5 Step 4. ✓
- Rota lê do MV atrás de flag nova `use_holders_db_first` com fallback legado → Tasks 6/7 (flag em config.py Task 6 Step 1). ✓
- Teste de paridade → Task 8 Step 1 (reshape MV==legacy) + Tasks 6/7 (flag-on/off). ✓
- "No heavy SQL in request path" → asserções `_FakeSession.executed` (não toca `sec_13f_holdings h`/`nport_holdings_history`/`sec_13f_holdings h` no caminho MV) em Tasks 6/7. ✓
- Transição §12 (build → parity → dual-read flag default False → flip → remove) → flag default False em toda parte; rollout descrito; remoção do legado marcada como passo final fora de escopo. ✓

**Varredura de placeholders:** sem "TBD"/"etc."/"add error handling". Todo step de código traz código real. As referências a "mover verbatim" (Task 6) apontam para linhas exatas do arquivo atual e preservam o corpo — é move-refactor, não hand-wave; o reshape extraído é mostrado por inteiro.

**Consistência de tipos:** shapes de MV em Interfaces batem entre DDL (Tasks 1-3), ORM (Task 5) e desempacotamento `.mappings()` nas leituras (Tasks 6/7) — todas usam acesso por chave de dict (`row["cik"]` etc.), então a ordem de colunas no `select(...)` é irrelevante para o reshape (acesso nominal). Nomes de modelo `StockInstitutionalHolder`/`StockFundHolderRow`/`HoldingReverseLookupRow` idênticos em Task 5 (definição), `__init__.py` (registro) e Tasks 6/7 (uso). `use_holders_db_first` idêntico em config (Task 6) e leituras (Tasks 6/7). `matview_refresh.run(dsn, *, datalake_dsn=None)` consistente entre Interfaces, Task 4 teste e implementação. `LOCK_MATVIEW_REFRESH = 900_210` reutilizado do Grupo D (não redefinido com valor diferente).

**Risco conhecido (documentado, não placeholder):** lag entre ingestão SEC e `matview_refresh` → fallback ao SQL legado + flag dual-read + doc em Task 8 Step 3. Cobertura: ETFs/cusips sem N-PORT/13F recente caem em empty-state explícito (preservado verbatim do código atual).
