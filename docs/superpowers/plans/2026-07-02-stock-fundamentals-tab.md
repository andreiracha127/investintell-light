# Stock Fundamentals Tab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a Fundamentals tab to the stock detail page (valuation snapshot, financial statements 10Y/8Q, growth & health analytics) backed by two new materialized views over `sec_xbrl_facts`, and fully remove the Holders tab and its backend surface.

**Architecture:** Two MVs precompute XBRL normalization (concept COALESCE, restatement dedup, Q4 derivation, TTM, CAGRs) at refresh time. One endpoint `GET /stocks/{ticker}/fundamentals` does two indexed reads. Frontend renders four sections (snapshot strip, trend charts, statements tables, growth/health panels) with Highcharts builders in the house Graphite style. Holders removal keeps the funds reverse-lookup untouched.

**Tech Stack:** Postgres/TimescaleDB (Tiger prod `t83f4np6x4`), FastAPI + SQLAlchemy async, Pydantic v2, Next.js 15 + React Query + Highcharts, vitest + pytest.

**Spec:** `docs/superpowers/specs/2026-07-02-stock-fundamentals-tab-design.md` — read it before starting any task.

## Global Constraints

- Work on branch `feat/stock-fundamentals-tab` in worktree `E:/investintell-light-main-benchmark` (created in Task 0 by orchestrator).
- Backend runs from `backend/` with `uv run`; frontend from `frontend/` with `pnpm`.
- Money formatting in UI: `compactUsd` (adaptive $M/$B/$T). Percentages: `formatPercent`. NULL cells render `—`.
- No SEC form nomenclature in user-facing copy (no "13F", no "XBRL", no "10-K/10-Q" — say "annual/quarterly filings").
- Chart series use `colors.accent` (+ `colors.barMute` for secondary series); flat Graphite style, no rounded corners.
- Keep `holding_reverse_lookup_mv`, `fetch_holding_reverse_lookup`, and the `use_holders_db_first` setting — they serve the FUNDS pages.
- Every task: run the named tests, then commit with the given message before reporting done.

---

### Task 0 (ORCHESTRATOR): Create feature branch

Run in `E:/investintell-light-main-benchmark`:

```bash
git checkout -b feat/stock-fundamentals-tab
```

All subsequent tasks commit to this branch.

---

### Task 1: Statements MV DDL + string test

**Files:**
- Create: `backend/db/ddl/2026-07-02_stock_fundamentals_statements_mv.sql`
- Test: `backend/tests/test_stock_fundamentals_statements_mv_sql.py`

**Interfaces:**
- Produces: MV `stock_fundamentals_statements_mv` with columns
  `(ticker text, cik bigint, freq text 'A'|'Q', period_end date, fy int,
  fp text, filed date, revenue, cost_of_revenue, gross_profit, rnd_expense,
  sga_expense, operating_income, pretax_income, income_tax, net_income,
  eps_diluted, shares_diluted, d_and_a, assets, liabilities, equity, cash,
  st_debt, lt_debt, current_assets, current_liabilities, ocf, capex, fcf,
  dividends_paid, dps — all numeric)`. Unique index
  `(ticker, freq, period_end)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stock_fundamentals_statements_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-07-02_stock_fundamentals_statements_mv.sql"
)


def test_statements_mv_ddl():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fundamentals_statements_mv" in sql
    # Sources and taxonomy guard.
    assert "FROM sec_xbrl_facts" in sql
    assert "taxonomy = 'us-gaap'" in sql
    assert "universe_constituents" in sql
    # Restatements win: latest filed per fact identity.
    assert "DISTINCT ON" in sql and "filed DESC" in sql
    # Duration windows: annual ~1y, quarterly ~90d.
    assert "BETWEEN 330 AND 380" in sql
    assert "BETWEEN 80 AND 100" in sql
    # Q4 derivation and window caps.
    assert "q4_derived" in sql
    assert "<= CASE WHEN freq = 'A' THEN 10 ELSE 8 END" in sql
    # Concept normalization spot checks (priority COALESCE).
    assert "RevenueFromContractWithCustomerExcludingAssessedTax" in sql
    assert "NetCashProvidedByUsedInOperatingActivities" in sql
    assert "CommonStockDividendsPerShareDeclared" in sql
    # Indexes + refresh.
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_fundamentals_statements_mv_pk" in sql
    assert "ON stock_fundamentals_statements_mv (ticker, freq, period_end)" in sql
    assert "REFRESH MATERIALIZED VIEW stock_fundamentals_statements_mv;" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_statements_mv_sql.py -q`
Expected: FAIL (file not found).

- [ ] **Step 3: Write the DDL**

Create `backend/db/ddl/2026-07-02_stock_fundamentals_statements_mv.sql` with
exactly this content:

```sql
-- Stock fundamentals: normalized financial statements per (ticker, freq, period_end).
-- freq 'A' = 10 fiscal years of annual rows; freq 'Q' = 8 most recent quarters.
-- Source: sec_xbrl_facts (us-gaap) x universe_constituents (ticker -> cik).
-- Restated figures win (latest `filed` per fact identity). Q4 flow lines are
-- derived as FY - (Q1+Q2+Q3) per concept when the 10-K files only FY durations.
-- Read path: GET /stocks/{ticker}/fundamentals (app/services/stock_fundamentals.py).

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fundamentals_statements_mv AS
WITH uni AS (
    SELECT DISTINCT upper(ticker) AS ticker, cik
    FROM universe_constituents
    WHERE cik IS NOT NULL
),
-- One value per fact identity; restatements (later `filed`) win.
facts AS (
    SELECT DISTINCT ON (f.cik, f.concept, f.period_end, f.period_start)
           f.cik, f.concept, f.period_start, f.period_end,
           f.val, f.fy, f.fp, f.filed
    FROM sec_xbrl_facts f
    JOIN (SELECT DISTINCT cik FROM uni) u ON u.cik = f.cik
    WHERE f.taxonomy = 'us-gaap'
      AND f.unit IN ('USD', 'USD/shares', 'shares')
      AND f.concept IN (
        'RevenueFromContractWithCustomerExcludingAssessedTax','Revenues','SalesRevenueNet',
        'CostOfGoodsAndServicesSold','CostOfRevenue','CostOfGoodsSold',
        'GrossProfit','ResearchAndDevelopmentExpense','SellingGeneralAndAdministrativeExpense',
        'OperatingIncomeLoss',
        'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest',
        'IncomeTaxExpenseBenefit','NetIncomeLoss','EarningsPerShareDiluted',
        'WeightedAverageNumberOfDilutedSharesOutstanding',
        'DepreciationDepletionAndAmortization','DepreciationAmortizationAndAccretionNet',
        'Assets','Liabilities','StockholdersEquity',
        'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest',
        'CashAndCashEquivalentsAtCarryingValue',
        'LongTermDebtCurrent','DebtCurrent','LongTermDebtNoncurrent','LongTermDebt',
        'AssetsCurrent','LiabilitiesCurrent',
        'NetCashProvidedByUsedInOperatingActivities',
        'PaymentsToAcquirePropertyPlantAndEquipment',
        'PaymentsOfDividendsCommonStock','PaymentsOfDividends',
        'CommonStockDividendsPerShareDeclared'
      )
    ORDER BY f.cik, f.concept, f.period_end, f.period_start, f.filed DESC
),
-- Flow (duration) facts pivoted per period. `span` classifies annual vs quarterly.
flow_pivot AS (
    SELECT cik, period_end, period_start,
           CASE WHEN (period_end - period_start) BETWEEN 330 AND 380 THEN 'A'
                WHEN (period_end - period_start) BETWEEN 80  AND 100 THEN 'Q'
           END AS freq,
           max(fy) AS fy, max(fp) AS fp, max(filed) AS filed,
           COALESCE(
             max(val) FILTER (WHERE concept = 'RevenueFromContractWithCustomerExcludingAssessedTax'),
             max(val) FILTER (WHERE concept = 'Revenues'),
             max(val) FILTER (WHERE concept = 'SalesRevenueNet')
           ) AS revenue,
           COALESCE(
             max(val) FILTER (WHERE concept = 'CostOfGoodsAndServicesSold'),
             max(val) FILTER (WHERE concept = 'CostOfRevenue'),
             max(val) FILTER (WHERE concept = 'CostOfGoodsSold')
           ) AS cost_of_revenue,
           max(val) FILTER (WHERE concept = 'GrossProfit') AS gross_profit_raw,
           max(val) FILTER (WHERE concept = 'ResearchAndDevelopmentExpense') AS rnd_expense,
           max(val) FILTER (WHERE concept = 'SellingGeneralAndAdministrativeExpense') AS sga_expense,
           max(val) FILTER (WHERE concept = 'OperatingIncomeLoss') AS operating_income,
           max(val) FILTER (WHERE concept = 'IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest') AS pretax_income,
           max(val) FILTER (WHERE concept = 'IncomeTaxExpenseBenefit') AS income_tax,
           max(val) FILTER (WHERE concept = 'NetIncomeLoss') AS net_income,
           max(val) FILTER (WHERE concept = 'EarningsPerShareDiluted') AS eps_diluted,
           max(val) FILTER (WHERE concept = 'WeightedAverageNumberOfDilutedSharesOutstanding') AS shares_diluted,
           COALESCE(
             max(val) FILTER (WHERE concept = 'DepreciationDepletionAndAmortization'),
             max(val) FILTER (WHERE concept = 'DepreciationAmortizationAndAccretionNet')
           ) AS d_and_a,
           max(val) FILTER (WHERE concept = 'NetCashProvidedByUsedInOperatingActivities') AS ocf,
           max(val) FILTER (WHERE concept = 'PaymentsToAcquirePropertyPlantAndEquipment') AS capex,
           COALESCE(
             max(val) FILTER (WHERE concept = 'PaymentsOfDividendsCommonStock'),
             max(val) FILTER (WHERE concept = 'PaymentsOfDividends')
           ) AS dividends_paid,
           max(val) FILTER (WHERE concept = 'CommonStockDividendsPerShareDeclared') AS dps
    FROM facts
    WHERE period_start IS NOT NULL
    GROUP BY cik, period_end, period_start
),
flows AS (SELECT * FROM flow_pivot WHERE freq IS NOT NULL),
-- Instant (balance-sheet) facts pivoted per period_end.
instants AS (
    SELECT cik, period_end,
           max(val) FILTER (WHERE concept = 'Assets') AS assets,
           max(val) FILTER (WHERE concept = 'Liabilities') AS liabilities,
           COALESCE(
             max(val) FILTER (WHERE concept = 'StockholdersEquity'),
             max(val) FILTER (WHERE concept = 'StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest')
           ) AS equity,
           max(val) FILTER (WHERE concept = 'CashAndCashEquivalentsAtCarryingValue') AS cash,
           COALESCE(
             max(val) FILTER (WHERE concept = 'LongTermDebtCurrent'),
             max(val) FILTER (WHERE concept = 'DebtCurrent')
           ) AS st_debt,
           COALESCE(
             max(val) FILTER (WHERE concept = 'LongTermDebtNoncurrent'),
             max(val) FILTER (WHERE concept = 'LongTermDebt')
           ) AS lt_debt,
           max(val) FILTER (WHERE concept = 'AssetsCurrent') AS current_assets,
           max(val) FILTER (WHERE concept = 'LiabilitiesCurrent') AS current_liabilities
    FROM facts
    WHERE period_start IS NULL
    GROUP BY cik, period_end
),
annual AS (SELECT * FROM flows WHERE freq = 'A'),
quarterly AS (SELECT * FROM flows WHERE freq = 'Q'),
-- Q4 flows derived per concept: FY - (Q1+Q2+Q3), only when the quarter-end has
-- no ~90d fact of its own and exactly three quarters fall inside the FY window.
q4_derived AS (
    SELECT a.cik, a.period_end, 'Q'::text AS freq, a.fy, 'Q4'::text AS fp, a.filed,
           CASE WHEN q.revenue_n = 3 THEN a.revenue - q.revenue_s END AS revenue,
           CASE WHEN q.cost_n = 3 THEN a.cost_of_revenue - q.cost_s END AS cost_of_revenue,
           CASE WHEN q.gp_n = 3 THEN a.gross_profit_raw - q.gp_s END AS gross_profit_raw,
           CASE WHEN q.rnd_n = 3 THEN a.rnd_expense - q.rnd_s END AS rnd_expense,
           CASE WHEN q.sga_n = 3 THEN a.sga_expense - q.sga_s END AS sga_expense,
           CASE WHEN q.oi_n = 3 THEN a.operating_income - q.oi_s END AS operating_income,
           CASE WHEN q.ptx_n = 3 THEN a.pretax_income - q.ptx_s END AS pretax_income,
           CASE WHEN q.tax_n = 3 THEN a.income_tax - q.tax_s END AS income_tax,
           CASE WHEN q.ni_n = 3 THEN a.net_income - q.ni_s END AS net_income,
           CASE WHEN q.eps_n = 3 THEN a.eps_diluted - q.eps_s END AS eps_diluted,
           NULL::numeric AS shares_diluted,
           CASE WHEN q.da_n = 3 THEN a.d_and_a - q.da_s END AS d_and_a,
           CASE WHEN q.ocf_n = 3 THEN a.ocf - q.ocf_s END AS ocf,
           CASE WHEN q.capex_n = 3 THEN a.capex - q.capex_s END AS capex,
           CASE WHEN q.div_n = 3 THEN a.dividends_paid - q.div_s END AS dividends_paid,
           CASE WHEN q.dps_n = 3 THEN a.dps - q.dps_s END AS dps
    FROM annual a
    JOIN LATERAL (
        SELECT count(*) AS n,
               count(revenue) AS revenue_n, sum(revenue) AS revenue_s,
               count(cost_of_revenue) AS cost_n, sum(cost_of_revenue) AS cost_s,
               count(gross_profit_raw) AS gp_n, sum(gross_profit_raw) AS gp_s,
               count(rnd_expense) AS rnd_n, sum(rnd_expense) AS rnd_s,
               count(sga_expense) AS sga_n, sum(sga_expense) AS sga_s,
               count(operating_income) AS oi_n, sum(operating_income) AS oi_s,
               count(pretax_income) AS ptx_n, sum(pretax_income) AS ptx_s,
               count(income_tax) AS tax_n, sum(income_tax) AS tax_s,
               count(net_income) AS ni_n, sum(net_income) AS ni_s,
               count(eps_diluted) AS eps_n, sum(eps_diluted) AS eps_s,
               count(d_and_a) AS da_n, sum(d_and_a) AS da_s,
               count(ocf) AS ocf_n, sum(ocf) AS ocf_s,
               count(capex) AS capex_n, sum(capex) AS capex_s,
               count(dividends_paid) AS div_n, sum(dividends_paid) AS div_s,
               count(dps) AS dps_n, sum(dps) AS dps_s
        FROM quarterly q
        WHERE q.cik = a.cik
          AND q.period_end > a.period_start
          AND q.period_end < a.period_end
    ) q ON q.n = 3
    WHERE NOT EXISTS (
        SELECT 1 FROM quarterly q2
        WHERE q2.cik = a.cik AND q2.period_end = a.period_end
    )
),
all_rows AS (
    SELECT cik, period_end, freq, fy, fp, filed, revenue, cost_of_revenue,
           gross_profit_raw, rnd_expense, sga_expense, operating_income,
           pretax_income, income_tax, net_income, eps_diluted, shares_diluted,
           d_and_a, ocf, capex, dividends_paid, dps
    FROM flows
    UNION ALL
    SELECT cik, period_end, freq, fy, fp, filed, revenue, cost_of_revenue,
           gross_profit_raw, rnd_expense, sga_expense, operating_income,
           pretax_income, income_tax, net_income, eps_diluted, shares_diluted,
           d_and_a, ocf, capex, dividends_paid, dps
    FROM q4_derived
),
ranked AS (
    SELECT u.ticker, r.*,
           row_number() OVER (
             PARTITION BY u.ticker, r.freq ORDER BY r.period_end DESC
           ) AS rn
    FROM all_rows r
    JOIN uni u ON u.cik = r.cik
)
SELECT r.ticker, r.cik, r.freq, r.period_end, r.fy, r.fp, r.filed,
       r.revenue, r.cost_of_revenue,
       COALESCE(r.gross_profit_raw, r.revenue - r.cost_of_revenue) AS gross_profit,
       r.rnd_expense, r.sga_expense, r.operating_income, r.pretax_income,
       r.income_tax, r.net_income, r.eps_diluted, r.shares_diluted, r.d_and_a,
       i.assets, i.liabilities, i.equity, i.cash, i.st_debt, i.lt_debt,
       i.current_assets, i.current_liabilities,
       r.ocf, r.capex, (r.ocf - r.capex) AS fcf, r.dividends_paid, r.dps
FROM ranked r
LEFT JOIN instants i ON i.cik = r.cik AND i.period_end = r.period_end
WHERE r.rn <= CASE WHEN freq = 'A' THEN 10 ELSE 8 END
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_fundamentals_statements_mv_pk
    ON stock_fundamentals_statements_mv (ticker, freq, period_end);
CREATE INDEX IF NOT EXISTS stock_fundamentals_statements_mv_ticker
    ON stock_fundamentals_statements_mv (ticker);

REFRESH MATERIALIZED VIEW stock_fundamentals_statements_mv;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_statements_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db/ddl/2026-07-02_stock_fundamentals_statements_mv.sql backend/tests/test_stock_fundamentals_statements_mv_sql.py
git commit -m "feat(fundamentals): statements MV DDL (normalized XBRL, 10Y/8Q)"
```

---

### Task 2: Snapshot MV DDL + string test

**Files:**
- Create: `backend/db/ddl/2026-07-02_stock_fundamentals_snapshot_mv.sql`
- Test: `backend/tests/test_stock_fundamentals_snapshot_mv_sql.py`

**Interfaces:**
- Consumes: `stock_fundamentals_statements_mv` (Task 1 columns).
- Produces: MV `stock_fundamentals_snapshot_mv`, one row per ticker:
  `(ticker, cik, sector, latest_period_end, latest_filed, price_close,
  market_cap, pe_ttm, pb, ps, ev, ev_ebitda, dividend_yield, revenue_ttm,
  net_income_ttm, eps_ttm, ocf_ttm, capex_ttm, fcf_ttm, dps_ttm,
  gross_margin, operating_margin, net_margin, roe, roa, de_ratio,
  current_ratio, shares_outstanding, bvps, fcf_ps, payout_ratio,
  revenue_cagr_1y, revenue_cagr_3y, revenue_cagr_5y, revenue_cagr_10y,
  net_income_cagr_1y, net_income_cagr_3y, net_income_cagr_5y,
  net_income_cagr_10y, eps_cagr_1y, eps_cagr_3y, eps_cagr_5y, eps_cagr_10y,
  fcf_cagr_1y, fcf_cagr_3y, fcf_cagr_5y, fcf_cagr_10y)`.
  Unique index `(ticker)`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stock_fundamentals_snapshot_mv_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-07-02_stock_fundamentals_snapshot_mv.sql"
)


def test_snapshot_mv_ddl():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fundamentals_snapshot_mv" in sql
    assert "FROM stock_fundamentals_statements_mv" in sql
    assert "screener_metrics" in sql
    assert "fundamentals_snapshot" in sql
    # TTM = last 4 quarters (guarded), else latest FY fallback.
    assert "q_n = 4" in sql
    # CAGR via power() with positive-base guard.
    assert "power(" in sql and "> 0" in sql
    # Valuation derivations present.
    for col in ("ev_ebitda", "dividend_yield", "payout_ratio", "current_ratio", "bvps"):
        assert col in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS stock_fundamentals_snapshot_mv_pk" in sql
    assert "ON stock_fundamentals_snapshot_mv (ticker)" in sql
    assert "REFRESH MATERIALIZED VIEW stock_fundamentals_snapshot_mv;" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_snapshot_mv_sql.py -q`
Expected: FAIL (file not found).

- [ ] **Step 3: Write the DDL**

Create `backend/db/ddl/2026-07-02_stock_fundamentals_snapshot_mv.sql`:

```sql
-- Stock fundamentals snapshot: one row per ticker with current valuation,
-- TTM lines, margins, health ratios, per-share values and growth CAGRs.
-- Built on stock_fundamentals_statements_mv + screener_metrics (daily price
-- data) + fundamentals_snapshot (shares outstanding fallback).
-- Refresh AFTER stock_fundamentals_statements_mv.

CREATE MATERIALIZED VIEW IF NOT EXISTS stock_fundamentals_snapshot_mv AS
WITH latest_bs AS (
    -- Most recent period with a balance sheet (any freq).
    SELECT DISTINCT ON (ticker)
           ticker, cik, period_end, filed, assets, liabilities, equity, cash,
           st_debt, lt_debt, current_assets, current_liabilities
    FROM stock_fundamentals_statements_mv
    WHERE assets IS NOT NULL OR equity IS NOT NULL
    ORDER BY ticker, period_end DESC
),
ttm AS (
    -- Sum of the 4 most recent quarters, only when all 4 exist.
    SELECT ticker,
           count(*) AS q_n,
           sum(revenue) AS revenue_s, count(revenue) AS revenue_n,
           sum(net_income) AS ni_s, count(net_income) AS ni_n,
           sum(eps_diluted) AS eps_s, count(eps_diluted) AS eps_n,
           sum(ocf) AS ocf_s, count(ocf) AS ocf_n,
           sum(capex) AS capex_s, count(capex) AS capex_n,
           sum(fcf) AS fcf_s, count(fcf) AS fcf_n,
           sum(dps) AS dps_s, count(dps) AS dps_n,
           sum(operating_income) AS oi_s, count(operating_income) AS oi_n,
           sum(gross_profit) AS gp_s, count(gross_profit) AS gp_n,
           sum(d_and_a) AS da_s, count(d_and_a) AS da_n
    FROM (
        SELECT *, row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) AS rn
        FROM stock_fundamentals_statements_mv WHERE freq = 'Q'
    ) q
    WHERE rn <= 4
    GROUP BY ticker
),
latest_fy AS (
    SELECT DISTINCT ON (ticker) *
    FROM stock_fundamentals_statements_mv
    WHERE freq = 'A'
    ORDER BY ticker, period_end DESC
),
-- TTM with FY fallback when the quarterly window is incomplete.
ttm_final AS (
    SELECT COALESCE(t.ticker, f.ticker) AS ticker,
           CASE WHEN t.q_n = 4 AND t.revenue_n = 4 THEN t.revenue_s ELSE f.revenue END AS revenue_ttm,
           CASE WHEN t.q_n = 4 AND t.ni_n = 4 THEN t.ni_s ELSE f.net_income END AS net_income_ttm,
           CASE WHEN t.q_n = 4 AND t.eps_n = 4 THEN t.eps_s ELSE f.eps_diluted END AS eps_ttm,
           CASE WHEN t.q_n = 4 AND t.ocf_n = 4 THEN t.ocf_s ELSE f.ocf END AS ocf_ttm,
           CASE WHEN t.q_n = 4 AND t.capex_n = 4 THEN t.capex_s ELSE f.capex END AS capex_ttm,
           CASE WHEN t.q_n = 4 AND t.fcf_n = 4 THEN t.fcf_s ELSE f.fcf END AS fcf_ttm,
           CASE WHEN t.q_n = 4 AND t.dps_n = 4 THEN t.dps_s ELSE f.dps END AS dps_ttm,
           CASE WHEN t.q_n = 4 AND t.oi_n = 4 THEN t.oi_s ELSE f.operating_income END AS oi_ttm,
           CASE WHEN t.q_n = 4 AND t.gp_n = 4 THEN t.gp_s ELSE f.gross_profit END AS gp_ttm,
           CASE WHEN t.q_n = 4 AND t.da_n = 4 THEN t.da_s ELSE f.d_and_a END AS da_ttm
    FROM ttm t
    FULL OUTER JOIN latest_fy f ON f.ticker = t.ticker
),
-- Annual series ranked ascending age for CAGRs: rn=1 latest FY.
annual_ranked AS (
    SELECT ticker, revenue, net_income, eps_diluted, fcf,
           row_number() OVER (PARTITION BY ticker ORDER BY period_end DESC) AS rn
    FROM stock_fundamentals_statements_mv
    WHERE freq = 'A'
),
cagr AS (
    SELECT l.ticker,
           -- CAGR n-year: (latest/base)^(1/n)-1, positive-base guard.
           (SELECT CASE WHEN b.revenue > 0 AND l.revenue > 0
                        THEN power(l.revenue / b.revenue, 1.0 / 1) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 2) AS revenue_cagr_1y,
           (SELECT CASE WHEN b.revenue > 0 AND l.revenue > 0
                        THEN power(l.revenue / b.revenue, 1.0 / 3) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 4) AS revenue_cagr_3y,
           (SELECT CASE WHEN b.revenue > 0 AND l.revenue > 0
                        THEN power(l.revenue / b.revenue, 1.0 / 5) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 6) AS revenue_cagr_5y,
           (SELECT CASE WHEN b.revenue > 0 AND l.revenue > 0
                        THEN power(l.revenue / b.revenue, 1.0 / 9) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 10) AS revenue_cagr_10y,
           (SELECT CASE WHEN b.net_income > 0 AND l.net_income > 0
                        THEN power(l.net_income / b.net_income, 1.0 / 1) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 2) AS net_income_cagr_1y,
           (SELECT CASE WHEN b.net_income > 0 AND l.net_income > 0
                        THEN power(l.net_income / b.net_income, 1.0 / 3) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 4) AS net_income_cagr_3y,
           (SELECT CASE WHEN b.net_income > 0 AND l.net_income > 0
                        THEN power(l.net_income / b.net_income, 1.0 / 5) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 6) AS net_income_cagr_5y,
           (SELECT CASE WHEN b.net_income > 0 AND l.net_income > 0
                        THEN power(l.net_income / b.net_income, 1.0 / 9) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 10) AS net_income_cagr_10y,
           (SELECT CASE WHEN b.eps_diluted > 0 AND l.eps_diluted > 0
                        THEN power(l.eps_diluted / b.eps_diluted, 1.0 / 1) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 2) AS eps_cagr_1y,
           (SELECT CASE WHEN b.eps_diluted > 0 AND l.eps_diluted > 0
                        THEN power(l.eps_diluted / b.eps_diluted, 1.0 / 3) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 4) AS eps_cagr_3y,
           (SELECT CASE WHEN b.eps_diluted > 0 AND l.eps_diluted > 0
                        THEN power(l.eps_diluted / b.eps_diluted, 1.0 / 5) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 6) AS eps_cagr_5y,
           (SELECT CASE WHEN b.eps_diluted > 0 AND l.eps_diluted > 0
                        THEN power(l.eps_diluted / b.eps_diluted, 1.0 / 9) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 10) AS eps_cagr_10y,
           (SELECT CASE WHEN b.fcf > 0 AND l.fcf > 0
                        THEN power(l.fcf / b.fcf, 1.0 / 1) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 2) AS fcf_cagr_1y,
           (SELECT CASE WHEN b.fcf > 0 AND l.fcf > 0
                        THEN power(l.fcf / b.fcf, 1.0 / 3) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 4) AS fcf_cagr_3y,
           (SELECT CASE WHEN b.fcf > 0 AND l.fcf > 0
                        THEN power(l.fcf / b.fcf, 1.0 / 5) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 6) AS fcf_cagr_5y,
           (SELECT CASE WHEN b.fcf > 0 AND l.fcf > 0
                        THEN power(l.fcf / b.fcf, 1.0 / 9) - 1 END
              FROM annual_ranked b WHERE b.ticker = l.ticker AND b.rn = 10) AS fcf_cagr_10y
    FROM annual_ranked l
    WHERE l.rn = 1
),
uni AS (
    SELECT DISTINCT ON (upper(ticker)) upper(ticker) AS ticker, cik, sector
    FROM universe_constituents WHERE cik IS NOT NULL
    ORDER BY upper(ticker), cik
),
so AS (
    SELECT DISTINCT ON (upper(ticker)) upper(ticker) AS ticker, shares_outstanding
    FROM fundamentals_snapshot
    WHERE shares_outstanding IS NOT NULL AND shares_outstanding > 0
    ORDER BY upper(ticker), period_end DESC
),
sm AS (
    SELECT upper(ticker) AS ticker, price_close, market_cap, pe_ratio, roe, roa
    FROM screener_metrics
)
SELECT u.ticker, u.cik, u.sector,
       bs.period_end AS latest_period_end,
       bs.filed AS latest_filed,
       sm.price_close, sm.market_cap,
       sm.pe_ratio AS pe_ttm,
       CASE WHEN bs.equity > 0 THEN sm.market_cap / bs.equity END AS pb,
       CASE WHEN t.revenue_ttm > 0 THEN sm.market_cap / t.revenue_ttm END AS ps,
       (sm.market_cap + COALESCE(bs.st_debt, 0) + COALESCE(bs.lt_debt, 0)
          - COALESCE(bs.cash, 0)) AS ev,
       CASE WHEN (t.oi_ttm + t.da_ttm) > 0
            THEN (sm.market_cap + COALESCE(bs.st_debt, 0) + COALESCE(bs.lt_debt, 0)
                    - COALESCE(bs.cash, 0)) / (t.oi_ttm + t.da_ttm)
       END AS ev_ebitda,
       CASE WHEN sm.price_close > 0 THEN t.dps_ttm / sm.price_close END AS dividend_yield,
       t.revenue_ttm, t.net_income_ttm, t.eps_ttm AS eps_ttm,
       t.ocf_ttm, t.capex_ttm, t.fcf_ttm, t.dps_ttm,
       CASE WHEN t.revenue_ttm > 0 THEN t.gp_ttm / t.revenue_ttm END AS gross_margin,
       CASE WHEN t.revenue_ttm > 0 THEN t.oi_ttm / t.revenue_ttm END AS operating_margin,
       CASE WHEN t.revenue_ttm > 0 THEN t.net_income_ttm / t.revenue_ttm END AS net_margin,
       COALESCE(sm.roe, CASE WHEN bs.equity > 0 THEN t.net_income_ttm / bs.equity END) AS roe,
       COALESCE(sm.roa, CASE WHEN bs.assets > 0 THEN t.net_income_ttm / bs.assets END) AS roa,
       CASE WHEN bs.equity > 0
            THEN (COALESCE(bs.st_debt, 0) + COALESCE(bs.lt_debt, 0)) / bs.equity
       END AS de_ratio,
       CASE WHEN bs.current_liabilities > 0
            THEN bs.current_assets / bs.current_liabilities
       END AS current_ratio,
       so.shares_outstanding,
       CASE WHEN so.shares_outstanding > 0 THEN bs.equity / so.shares_outstanding END AS bvps,
       CASE WHEN so.shares_outstanding > 0 THEN t.fcf_ttm / so.shares_outstanding END AS fcf_ps,
       CASE WHEN t.net_income_ttm > 0 AND so.shares_outstanding > 0
            THEN (t.dps_ttm * so.shares_outstanding) / t.net_income_ttm
       END AS payout_ratio,
       c.revenue_cagr_1y, c.revenue_cagr_3y, c.revenue_cagr_5y, c.revenue_cagr_10y,
       c.net_income_cagr_1y, c.net_income_cagr_3y, c.net_income_cagr_5y, c.net_income_cagr_10y,
       c.eps_cagr_1y, c.eps_cagr_3y, c.eps_cagr_5y, c.eps_cagr_10y,
       c.fcf_cagr_1y, c.fcf_cagr_3y, c.fcf_cagr_5y, c.fcf_cagr_10y
FROM uni u
LEFT JOIN latest_bs bs ON bs.ticker = u.ticker
LEFT JOIN ttm_final t ON t.ticker = u.ticker
LEFT JOIN cagr c ON c.ticker = u.ticker
LEFT JOIN so ON so.ticker = u.ticker
LEFT JOIN sm ON sm.ticker = u.ticker
WHERE bs.ticker IS NOT NULL OR t.ticker IS NOT NULL
WITH NO DATA;

CREATE UNIQUE INDEX IF NOT EXISTS stock_fundamentals_snapshot_mv_pk
    ON stock_fundamentals_snapshot_mv (ticker);

REFRESH MATERIALIZED VIEW stock_fundamentals_snapshot_mv;
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_snapshot_mv_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/db/ddl/2026-07-02_stock_fundamentals_snapshot_mv.sql backend/tests/test_stock_fundamentals_snapshot_mv_sql.py
git commit -m "feat(fundamentals): snapshot MV DDL (valuation, TTM, CAGRs, health)"
```

---

### Task 3 (ORCHESTRATOR): Apply MVs to prod via Tiger MCP

Not a subagent task — the orchestrator runs this after reviewing Tasks 1–2.

- [ ] Run the statements MV DDL against Tiger service `t83f4np6x4` (split
  statements: CREATE, indexes, then REFRESH with a generous timeout).
- [ ] Run the snapshot MV DDL the same way (refresh AFTER statements MV).
- [ ] Verify:

```sql
SELECT freq, count(*) FROM stock_fundamentals_statements_mv GROUP BY freq;
SELECT count(*) FROM stock_fundamentals_snapshot_mv;
-- Spot checks: AAPL revenue ~ hundreds of $B; JPM (financial) has NULL
-- cost_of_revenue but non-NULL assets/equity/net_income.
SELECT * FROM stock_fundamentals_statements_mv WHERE ticker='AAPL' AND freq='A' ORDER BY period_end DESC LIMIT 3;
SELECT ticker, pe_ttm, pb, net_margin, revenue_cagr_5y FROM stock_fundamentals_snapshot_mv WHERE ticker IN ('AAPL','MSFT','JPM');
```

- [ ] If numbers look wrong (e.g. revenue off by 1000x, negative gross
  margins on AAPL), STOP and fix the DDL before continuing to Task 4.

---

### Task 4: Backend schemas + service

**Files:**
- Create: `backend/app/schemas/stock_fundamentals.py`
- Create: `backend/app/services/stock_fundamentals.py`
- Test: `backend/tests/test_stock_fundamentals_service.py`

**Interfaces:**
- Consumes: the two MVs (Tasks 1–2 column lists).
- Produces:
  - `StockFundamentalsResponse` (Pydantic) with fields
    `ticker: str`, `as_of: date | None`, `snapshot: StockFundamentalsSnapshot | None`,
    `statements: StockFundamentalsStatements`, `empty_state: StockFundamentalsEmptyState | None`.
  - `async def fetch_stock_fundamentals(datalake: AsyncSession, ticker: str) -> StockFundamentalsResponse`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/test_stock_fundamentals_service.py
import datetime as dt

import pytest

from app.services import stock_fundamentals as svc


class _Result:
    def __init__(self, rows):
        self._rows = rows
    def mappings(self):
        return self
    def all(self):
        return self._rows
    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    """Returns snapshot row for the first execute, statement rows for the second."""
    def __init__(self, snapshot=None, statements=None):
        self._snapshot = snapshot
        self._statements = statements or []
        self.queries = []
    async def execute(self, query, params=None):
        self.queries.append((str(query), params))
        if "snapshot_mv" in str(query):
            return _Result([self._snapshot] if self._snapshot else [])
        return _Result(self._statements)


def _snap_row():
    return {
        "ticker": "AAPL", "cik": 320193, "sector": "Technology",
        "latest_period_end": dt.date(2025, 12, 27), "latest_filed": dt.date(2026, 1, 30),
        "price_close": 200.0, "market_cap": 3.0e12, "pe_ttm": 30.0, "pb": 40.0,
        "ps": 7.5, "ev": 3.1e12, "ev_ebitda": 22.0, "dividend_yield": 0.005,
        "revenue_ttm": 4.0e11, "net_income_ttm": 1.0e11, "eps_ttm": 6.5,
        "ocf_ttm": 1.2e11, "capex_ttm": 1.1e10, "fcf_ttm": 1.09e11, "dps_ttm": 1.0,
        "gross_margin": 0.46, "operating_margin": 0.31, "net_margin": 0.25,
        "roe": 1.5, "roa": 0.28, "de_ratio": 1.8, "current_ratio": 0.95,
        "shares_outstanding": 1.5e10, "bvps": 4.9, "fcf_ps": 7.2, "payout_ratio": 0.15,
        "revenue_cagr_1y": 0.06, "revenue_cagr_3y": 0.05, "revenue_cagr_5y": 0.08,
        "revenue_cagr_10y": 0.09, "net_income_cagr_1y": 0.07, "net_income_cagr_3y": 0.04,
        "net_income_cagr_5y": 0.1, "net_income_cagr_10y": 0.11, "eps_cagr_1y": 0.08,
        "eps_cagr_3y": 0.06, "eps_cagr_5y": 0.12, "eps_cagr_10y": 0.14,
        "fcf_cagr_1y": 0.05, "fcf_cagr_3y": 0.03, "fcf_cagr_5y": 0.09, "fcf_cagr_10y": 0.1,
    }


def _stmt_row(freq, period_end):
    return {
        "ticker": "AAPL", "cik": 320193, "freq": freq, "period_end": period_end,
        "fy": 2025, "fp": "FY" if freq == "A" else "Q1", "filed": dt.date(2026, 1, 30),
        "revenue": 1.0e11, "cost_of_revenue": 5.4e10, "gross_profit": 4.6e10,
        "rnd_expense": 8.0e9, "sga_expense": 7.0e9, "operating_income": 3.1e10,
        "pretax_income": 3.0e10, "income_tax": 5.0e9, "net_income": 2.5e10,
        "eps_diluted": 1.6, "shares_diluted": 1.5e10, "d_and_a": 3.0e9,
        "assets": 3.5e11, "liabilities": 2.8e11, "equity": 7.0e10, "cash": 3.0e10,
        "st_debt": 1.0e10, "lt_debt": 9.0e10, "current_assets": 1.4e11,
        "current_liabilities": 1.5e11, "ocf": 3.0e10, "capex": 3.0e9, "fcf": 2.7e10,
        "dividends_paid": 3.8e9, "dps": 0.25,
    }


@pytest.mark.asyncio
async def test_fetch_assembles_snapshot_and_statements():
    session = _FakeSession(
        snapshot=_snap_row(),
        statements=[
            _stmt_row("A", dt.date(2025, 9, 27)),
            _stmt_row("Q", dt.date(2025, 12, 27)),
        ],
    )
    out = await svc.fetch_stock_fundamentals(session, "aapl")
    assert out.ticker == "AAPL"
    assert out.snapshot is not None and out.snapshot.pe_ttm == 30.0
    assert len(out.statements.annual) == 1
    assert len(out.statements.quarterly) == 1
    assert out.statements.quarterly[0].period_end == dt.date(2025, 12, 27)
    assert out.as_of == dt.date(2026, 1, 30)
    assert out.empty_state is None


@pytest.mark.asyncio
async def test_fetch_empty_yields_empty_state():
    session = _FakeSession(snapshot=None, statements=[])
    out = await svc.fetch_stock_fundamentals(session, "ZZZZ")
    assert out.snapshot is None
    assert out.statements.annual == [] and out.statements.quarterly == []
    assert out.empty_state is not None and "coverage" in out.empty_state.reason.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_service.py -q`
Expected: FAIL (module not found).

- [ ] **Step 3: Write schemas**

```python
# backend/app/schemas/stock_fundamentals.py
"""Contracts for GET /stocks/{ticker}/fundamentals (Fundamentals tab)."""
from __future__ import annotations

import datetime as dt

from pydantic import BaseModel


class StockFundamentalsSnapshot(BaseModel):
    ticker: str
    cik: int | None = None
    sector: str | None = None
    latest_period_end: dt.date | None = None
    latest_filed: dt.date | None = None
    price_close: float | None = None
    market_cap: float | None = None
    pe_ttm: float | None = None
    pb: float | None = None
    ps: float | None = None
    ev: float | None = None
    ev_ebitda: float | None = None
    dividend_yield: float | None = None
    revenue_ttm: float | None = None
    net_income_ttm: float | None = None
    eps_ttm: float | None = None
    ocf_ttm: float | None = None
    capex_ttm: float | None = None
    fcf_ttm: float | None = None
    dps_ttm: float | None = None
    gross_margin: float | None = None
    operating_margin: float | None = None
    net_margin: float | None = None
    roe: float | None = None
    roa: float | None = None
    de_ratio: float | None = None
    current_ratio: float | None = None
    shares_outstanding: float | None = None
    bvps: float | None = None
    fcf_ps: float | None = None
    payout_ratio: float | None = None
    revenue_cagr_1y: float | None = None
    revenue_cagr_3y: float | None = None
    revenue_cagr_5y: float | None = None
    revenue_cagr_10y: float | None = None
    net_income_cagr_1y: float | None = None
    net_income_cagr_3y: float | None = None
    net_income_cagr_5y: float | None = None
    net_income_cagr_10y: float | None = None
    eps_cagr_1y: float | None = None
    eps_cagr_3y: float | None = None
    eps_cagr_5y: float | None = None
    eps_cagr_10y: float | None = None
    fcf_cagr_1y: float | None = None
    fcf_cagr_3y: float | None = None
    fcf_cagr_5y: float | None = None
    fcf_cagr_10y: float | None = None


class StockStatementPeriod(BaseModel):
    period_end: dt.date
    fy: int | None = None
    fp: str | None = None
    filed: dt.date | None = None
    revenue: float | None = None
    cost_of_revenue: float | None = None
    gross_profit: float | None = None
    rnd_expense: float | None = None
    sga_expense: float | None = None
    operating_income: float | None = None
    pretax_income: float | None = None
    income_tax: float | None = None
    net_income: float | None = None
    eps_diluted: float | None = None
    shares_diluted: float | None = None
    d_and_a: float | None = None
    assets: float | None = None
    liabilities: float | None = None
    equity: float | None = None
    cash: float | None = None
    st_debt: float | None = None
    lt_debt: float | None = None
    current_assets: float | None = None
    current_liabilities: float | None = None
    ocf: float | None = None
    capex: float | None = None
    fcf: float | None = None
    dividends_paid: float | None = None
    dps: float | None = None


class StockFundamentalsStatements(BaseModel):
    annual: list[StockStatementPeriod] = []
    quarterly: list[StockStatementPeriod] = []


class StockFundamentalsEmptyState(BaseModel):
    reason: str


class StockFundamentalsResponse(BaseModel):
    ticker: str
    as_of: dt.date | None = None
    snapshot: StockFundamentalsSnapshot | None = None
    statements: StockFundamentalsStatements = StockFundamentalsStatements()
    empty_state: StockFundamentalsEmptyState | None = None
```

- [ ] **Step 4: Write the service**

```python
# backend/app/services/stock_fundamentals.py
"""Fundamentals tab reads: two indexed MV lookups per ticker.

`stock_fundamentals_snapshot_mv` (one row) + `stock_fundamentals_statements_mv`
(<=18 rows). Both are precomputed from SEC XBRL facts — see the DDL files under
backend/db/ddl/2026-07-02_*.sql for normalization rules.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.stock_fundamentals import (
    StockFundamentalsEmptyState,
    StockFundamentalsResponse,
    StockFundamentalsSnapshot,
    StockFundamentalsStatements,
    StockStatementPeriod,
)

_SNAPSHOT_SQL = text(
    "SELECT * FROM stock_fundamentals_snapshot_mv WHERE ticker = :ticker"
)
_STATEMENTS_SQL = text(
    "SELECT * FROM stock_fundamentals_statements_mv "
    "WHERE ticker = :ticker ORDER BY freq, period_end DESC"
)


async def fetch_stock_fundamentals(
    datalake: AsyncSession, ticker: str
) -> StockFundamentalsResponse:
    norm = ticker.strip().upper()
    snap_row = (
        await datalake.execute(_SNAPSHOT_SQL, {"ticker": norm})
    ).mappings().first()
    stmt_rows = (
        await datalake.execute(_STATEMENTS_SQL, {"ticker": norm})
    ).mappings().all()

    snapshot = (
        StockFundamentalsSnapshot.model_validate(dict(snap_row)) if snap_row else None
    )
    annual = [
        StockStatementPeriod.model_validate(dict(r))
        for r in stmt_rows
        if r["freq"] == "A"
    ]
    quarterly = [
        StockStatementPeriod.model_validate(dict(r))
        for r in stmt_rows
        if r["freq"] == "Q"
    ]

    if snapshot is None and not annual and not quarterly:
        return StockFundamentalsResponse(
            ticker=norm,
            empty_state=StockFundamentalsEmptyState(
                reason="No fundamentals coverage for this ticker "
                "(not mapped to SEC company filings)."
            ),
        )

    as_of = snapshot.latest_filed if snapshot else None
    if as_of is None:
        filed = [r.filed for r in (annual + quarterly) if r.filed]
        as_of = max(filed) if filed else None

    return StockFundamentalsResponse(
        ticker=norm,
        as_of=as_of,
        snapshot=snapshot,
        statements=StockFundamentalsStatements(annual=annual, quarterly=quarterly),
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_service.py -q`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/schemas/stock_fundamentals.py backend/app/services/stock_fundamentals.py backend/tests/test_stock_fundamentals_service.py
git commit -m "feat(fundamentals): schemas + service (two MV reads per ticker)"
```

---

### Task 5: Backend route + OpenAPI/type regeneration

**Files:**
- Modify: `backend/app/api/routes/stocks.py` (add endpoint near the existing
  per-ticker GET endpoints; read the file first and mirror the sibling
  endpoint style, decorators, and datalake dependency)
- Modify: `backend/openapi.json` (regenerated)
- Modify: `frontend/src/lib/api/api.d.ts` (regenerated)
- Test: `backend/tests/test_stock_fundamentals_route.py`

**Interfaces:**
- Consumes: `fetch_stock_fundamentals` (Task 4).
- Produces: `GET /stocks/{ticker}/fundamentals` returning
  `StockFundamentalsResponse`; generated TS type
  `components["schemas"]["StockFundamentalsResponse"]`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_stock_fundamentals_route.py
from app.main import app


def test_fundamentals_route_registered():
    paths = {r.path for r in app.routes}
    assert "/stocks/{ticker}/fundamentals" in paths


def test_holders_routes_still_present_for_now():
    # Removed later in the holders-cleanup task; guard against premature removal.
    paths = {r.path for r in app.routes}
    assert "/stocks/{ticker}/holders" in paths
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_route.py -q`
Expected: first test FAILs (route missing).

- [ ] **Step 3: Add the endpoint**

In `backend/app/api/routes/stocks.py`, import the service and schema and add
(mirroring the holders endpoint signature/dependency style found in the file):

```python
from app.schemas.stock_fundamentals import StockFundamentalsResponse
from app.services.stock_fundamentals import fetch_stock_fundamentals


@router.get("/{ticker}/fundamentals", response_model=StockFundamentalsResponse)
async def get_stock_fundamentals(
    ticker: str,
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> StockFundamentalsResponse:
    """Company fundamentals: valuation snapshot + normalized statements."""
    return await fetch_stock_fundamentals(datalake, ticker)
```

- [ ] **Step 4: Run test + full stocks test module**

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_route.py -q`
Expected: PASS.

- [ ] **Step 5: Regenerate the OpenAPI contract and frontend types**

Find how `backend/openapi.json` is generated (look for a script in
`backend/pyproject.toml` or `backend/scripts/` that dumps `app.openapi()`;
if none exists, run:
`cd backend && uv run python -c "import json; from app.main import app; open('openapi.json','w').write(json.dumps(app.openapi()))"`).
Then: `cd frontend && pnpm types`.
Expected: `frontend/src/lib/api/api.d.ts` gains `StockFundamentalsResponse`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/routes/stocks.py backend/tests/test_stock_fundamentals_route.py backend/openapi.json frontend/src/lib/api/api.d.ts
git commit -m "feat(fundamentals): GET /stocks/{ticker}/fundamentals + typegen"
```

---

### Task 6: Frontend API client fetcher + query key

**Files:**
- Modify: `frontend/src/lib/api/client.ts` (add type export + fetcher; read
  the file first and mirror the `fetchStockHolders` pattern exactly — same
  request helper, same error handling)
- Modify: `frontend/src/lib/stocks/queries.ts` (add query key)
- Test: extend `frontend/src/lib/api/client.test.ts` ONLY if sibling fetchers
  are tested there (mirror); otherwise no new test (thin passthrough).

**Interfaces:**
- Produces:
  - `export type StockFundamentalsResponse = components["schemas"]["StockFundamentalsResponse"];`
    (and the nested `StockFundamentalsSnapshot`, `StockStatementPeriod` types)
  - `export async function fetchStockFundamentals(ticker: string): Promise<StockFundamentalsResponse>`
  - `stockQueryKeys.fundamentals = (ticker: string) => ["stock-fundamentals", ticker] as const`

- [ ] **Step 1: Add types + fetcher to `client.ts`** (mirror `fetchStockHolders`
  — same helper for URL building and JSON parsing; path
  `/stocks/${encodeURIComponent(ticker)}/fundamentals`).
- [ ] **Step 2: Add `fundamentals` key to `stockQueryKeys` in
  `frontend/src/lib/stocks/queries.ts`.**
- [ ] **Step 3: Typecheck**

Run: `cd frontend && pnpm typecheck`
Expected: clean.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/api/client.ts frontend/src/lib/stocks/queries.ts
git commit -m "feat(fundamentals): client fetcher + query key"
```

---

### Task 7: Highcharts builders

**Files:**
- Create: `frontend/src/lib/charts/hc/stockFundamentals.ts`
- Test: `frontend/src/lib/charts/hc/stockFundamentals.test.ts`

**Interfaces:**
- Consumes: `StockStatementPeriod[]` (chronological handling internal),
  `ChartColors` from `@/lib/charts/chartColors`, `compactUsd` (import from
  `@/lib/grid/holdersGridOptions` for now — Task 10 relocates it to
  `@/lib/format` and updates this import), `formatPercent`/`formatNumber`
  from `@/lib/format`.
- Produces four pure builders, each `(periods: StockStatementPeriod[], colors: ChartColors) => Options`:
  - `buildHcRevenueNetIncomeOption` — column chart, two series
    ("Revenue" `colors.accent`, "Net income" `colors.barMute`), x = period
    labels (fy for annual e.g. "2025", `fp 'YY` for quarterly e.g. "Q1 '26"),
    y compact USD.
  - `buildHcMarginsOption` — line chart, three series Gross/Operating/Net
    margin in % (compute from revenue/gross_profit/operating_income/net_income;
    skip periods with revenue null/<=0).
  - `buildHcEpsOption` — column chart, single accent series, eps_diluted,
    2-decimal labels.
  - `buildHcFcfOption` — column chart, single accent series, fcf, compact USD
    labels, negative values keep accent (zones not required).

All builders: `legend` enabled only for multi-series charts; tooltips show the
period label + formatted values; periods sorted ascending (oldest → newest)
on the x axis; rows with all-null targets skipped.

- [ ] **Step 1: Write the failing tests**

```typescript
// frontend/src/lib/charts/hc/stockFundamentals.test.ts
import { describe, expect, it } from "vitest";

import type { StockStatementPeriod } from "@/lib/api/client";
import {
  buildHcEpsOption,
  buildHcFcfOption,
  buildHcMarginsOption,
  buildHcRevenueNetIncomeOption,
} from "@/lib/charts/hc/stockFundamentals";

const colors = {
  gain: "#0a0", loss: "#a00", accent: "#7f1d1d", accentMuted: "#9f2d2d",
  accentWash: "#fee", textOnAccent: "#fff", text: "#111", textSecondary: "#444",
  textMuted: "#888", grid: "#ddd", surface: "#fff", bar: "#333", barMute: "#bbb",
  blue: "#00a", amber: "#a80", categories: ["#1", "#2", "#3", "#4", "#5", "#6", "#7", "#8"],
};

function period(over: Partial<StockStatementPeriod>): StockStatementPeriod {
  return {
    period_end: "2025-09-27", fy: 2025, fp: "FY", filed: "2025-11-01",
    revenue: 100, cost_of_revenue: 54, gross_profit: 46, rnd_expense: 8,
    sga_expense: 7, operating_income: 31, pretax_income: 30, income_tax: 5,
    net_income: 25, eps_diluted: 1.6, shares_diluted: 15, d_and_a: 3,
    assets: 350, liabilities: 280, equity: 70, cash: 30, st_debt: 10,
    lt_debt: 90, current_assets: 140, current_liabilities: 150, ocf: 30,
    capex: 3, fcf: 27, dividends_paid: 4, dps: 0.25,
    ...over,
  } as StockStatementPeriod;
}

describe("stock fundamentals builders", () => {
  it("builds revenue vs net income columns in chronological order with accent fills", () => {
    const option = buildHcRevenueNetIncomeOption(
      [period({ fy: 2025, revenue: 200 }), period({ period_end: "2024-09-28", fy: 2024, revenue: 100 })],
      colors,
    );
    expect(option.series).toHaveLength(2);
    expect(option.series?.[0]).toMatchObject({ type: "column", name: "Revenue", color: colors.accent });
    expect(option.series?.[1]).toMatchObject({ type: "column", name: "Net income", color: colors.barMute });
    // Oldest first on the axis.
    const cats = (option.xAxis as { categories?: string[] }).categories;
    expect(cats?.[0]).toBe("2024");
    expect(cats?.[1]).toBe("2025");
  });

  it("labels quarterly periods as Qn 'YY", () => {
    const option = buildHcRevenueNetIncomeOption(
      [period({ fp: "Q1", fy: 2026, period_end: "2025-12-27" })],
      colors,
    );
    const cats = (option.xAxis as { categories?: string[] }).categories;
    expect(cats?.[0]).toBe("Q1 '26");
  });

  it("computes margin percentages and skips zero-revenue periods", () => {
    const option = buildHcMarginsOption(
      [period({}), period({ period_end: "2024-09-28", fy: 2024, revenue: 0 })],
      colors,
    );
    expect(option.series).toHaveLength(3);
    const gross = option.series?.[0] as { data?: number[] };
    expect(gross.data).toHaveLength(1); // zero-revenue period skipped
    expect(gross.data?.[0]).toBeCloseTo(46, 5); // 46/100 in percent points
  });

  it("builds EPS and FCF single-series accent columns", () => {
    const eps = buildHcEpsOption([period({})], colors);
    const fcf = buildHcFcfOption([period({})], colors);
    expect(eps.series?.[0]).toMatchObject({ type: "column", color: colors.accent });
    expect(fcf.series?.[0]).toMatchObject({ type: "column", color: colors.accent });
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stockFundamentals.test.ts`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the builders**

Full implementation of `frontend/src/lib/charts/hc/stockFundamentals.ts`:

```typescript
/**
 * Pure option builders for the stock Fundamentals tab trend charts.
 * Data arrives as StockStatementPeriod[] (any order); builders sort
 * chronologically, label periods ("2025" annual, "Q1 '26" quarterly) and
 * apply Graphite colors. Money via compactUsd; margins in percent points.
 */
import type { Options, Point } from "highcharts";

import type { StockStatementPeriod } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";
import { compactUsd } from "@/lib/grid/holdersGridOptions";

function chronological(periods: StockStatementPeriod[]): StockStatementPeriod[] {
  return [...periods].sort((a, b) => a.period_end.localeCompare(b.period_end));
}

export function periodLabel(p: StockStatementPeriod): string {
  if (p.fp && p.fp !== "FY") {
    const yy = p.period_end.slice(2, 4);
    return `${p.fp} '${yy}`;
  }
  return String(p.fy ?? p.period_end.slice(0, 4));
}

export function buildHcRevenueNetIncomeOption(
  periods: StockStatementPeriod[],
  colors: ChartColors,
): Options {
  const rows = chronological(periods).filter(
    (p) => p.revenue != null || p.net_income != null,
  );
  return {
    chart: { type: "column" },
    xAxis: { categories: rows.map(periodLabel), tickWidth: 0, crosshair: true },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return compactUsd(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const idx = this.index;
        const p = rows[idx];
        return (
          `${periodLabel(p)}<br/>` +
          `Revenue <b>${compactUsd(p.revenue ?? null)}</b><br/>` +
          `Net income <b>${compactUsd(p.net_income ?? null)}</b>`
        );
      },
    },
    series: [
      {
        type: "column",
        name: "Revenue",
        color: colors.accent,
        data: rows.map((p) => p.revenue ?? null),
        borderWidth: 0,
      },
      {
        type: "column",
        name: "Net income",
        color: colors.barMute,
        data: rows.map((p) => p.net_income ?? null),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcMarginsOption(
  periods: StockStatementPeriod[],
  colors: ChartColors,
): Options {
  const rows = chronological(periods).filter(
    (p) => p.revenue != null && p.revenue > 0,
  );
  const pct = (num: number | null | undefined, den: number) =>
    num == null ? null : (num / den) * 100;
  return {
    chart: { type: "line" },
    xAxis: { categories: rows.map(periodLabel), tickWidth: 0, crosshair: true },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return `${formatNumber(this.value as number, 0)}%`;
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const p = rows[this.index];
        const rev = p.revenue as number;
        const row = (label: string, v: number | null) =>
          v == null ? "" : `${label} <b>${formatNumber(v, 1)}%</b><br/>`;
        return (
          `${periodLabel(p)}<br/>` +
          row("Gross", pct(p.gross_profit, rev)) +
          row("Operating", pct(p.operating_income, rev)) +
          row("Net", pct(p.net_income, rev))
        );
      },
    },
    series: [
      {
        type: "line",
        name: "Gross margin",
        color: colors.accent,
        data: rows.map((p) => pct(p.gross_profit, p.revenue as number)),
      },
      {
        type: "line",
        name: "Operating margin",
        color: colors.blue,
        data: rows.map((p) => pct(p.operating_income, p.revenue as number)),
      },
      {
        type: "line",
        name: "Net margin",
        color: colors.barMute,
        data: rows.map((p) => pct(p.net_income, p.revenue as number)),
      },
    ],
  };
}

function singleColumn(
  rows: StockStatementPeriod[],
  colors: ChartColors,
  name: string,
  value: (p: StockStatementPeriod) => number | null,
  fmt: (v: number) => string,
): Options {
  return {
    chart: { type: "column" },
    legend: { enabled: false },
    xAxis: { categories: rows.map(periodLabel), tickWidth: 0 },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return fmt(this.value as number);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const p = rows[this.index];
        const v = value(p);
        return `${periodLabel(p)}<br/>${name} <b>${v == null ? "—" : fmt(v)}</b>`;
      },
    },
    series: [
      {
        type: "column",
        name,
        color: colors.accent,
        data: rows.map((p) => value(p)),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcEpsOption(
  periods: StockStatementPeriod[],
  colors: ChartColors,
): Options {
  const rows = chronological(periods).filter((p) => p.eps_diluted != null);
  return singleColumn(rows, colors, "Diluted EPS", (p) => p.eps_diluted ?? null, (v) =>
    `$${formatNumber(v, 2)}`,
  );
}

export function buildHcFcfOption(
  periods: StockStatementPeriod[],
  colors: ChartColors,
): Options {
  const rows = chronological(periods).filter((p) => p.fcf != null);
  return singleColumn(rows, colors, "Free cash flow", (p) => p.fcf ?? null, (v) =>
    compactUsd(v),
  );
}
```

Note: `formatPercent` import may be unused depending on final tooltip code —
remove unused imports before committing (typecheck enforces it).

- [ ] **Step 4: Run tests**

Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/stockFundamentals.test.ts`
Expected: PASS. Also run `pnpm typecheck`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/lib/charts/hc/stockFundamentals.ts frontend/src/lib/charts/hc/stockFundamentals.test.ts
git commit -m "feat(fundamentals): trend chart builders (revenue/NI, margins, EPS, FCF)"
```

---

### Task 8: FundamentalsTab component — snapshot strip + trend charts

**Files:**
- Create: `frontend/src/components/stocks/FundamentalsTab.tsx`
- Test: `frontend/src/components/stocks/FundamentalsTab.test.tsx`

**Interfaces:**
- Consumes: `fetchStockFundamentals` + `stockQueryKeys.fundamentals` (Task 6),
  the four builders (Task 7), `HighchartsChart`
  (`@/components/charts/HighchartsChart`), `chartColors`
  (`@/lib/charts/chartColors`), `compactUsd`, `formatPercent`, `formatNumber`,
  `formatDate` from house libs.
- Produces: `export function FundamentalsTab({ ticker }: { ticker: string })`,
  plus internal `StatementsSection` placeholder slot that Task 9 fills
  (Task 8 renders snapshot strip + charts + Growth/Health panels; the
  statements tables arrive in Task 9 in the same file).

**Layout contract (Graphite/Carbon, mirror `StockAnalysisView.tsx` styling):**
- Section wrapper: `<section className="ix-pad border border-border bg-surface-2">`
  with `<h2 className="ix-label m-0">TITLE</h2>` headers.
- KPI strip: CSS grid `grid grid-cols-2 gap-px bg-border sm:grid-cols-3 xl:grid-cols-9`,
  each tile `bg-surface-2 p-3` with muted label + `text-[15px] font-bold tabular-nums` value.
- Charts grid: `grid gap-4 xl:grid-cols-2`, each chart `h-[260px]`.
- A/Q toggle: two small buttons (`Annual` / `Quarterly`), selected one
  `bg-accent text-on-accent`, unselected `border border-border text-text-secondary`.
- Colors from `chartColors()` after mount (`useState` + `useEffect`, mirror how
  `StockAnalysisView.tsx` obtains colors — read it first; if it uses a
  `useChartColors`-style hook, reuse that).

- [ ] **Step 1: Write the failing test**

```tsx
// frontend/src/components/stocks/FundamentalsTab.test.tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { FundamentalsTab } from "@/components/stocks/FundamentalsTab";

vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="hc-chart" />,
}));

const response = {
  ticker: "AAPL",
  as_of: "2026-01-30",
  snapshot: {
    ticker: "AAPL", market_cap: 3.0e12, pe_ttm: 30.5, pb: 40.1, ps: 7.5,
    ev_ebitda: 22.3, dividend_yield: 0.005, roe: 1.5, net_margin: 0.25,
    de_ratio: 1.8, current_ratio: 0.95, bvps: 4.9, fcf_ps: 7.2,
    dps_ttm: 1.0, payout_ratio: 0.15,
    revenue_cagr_1y: 0.06, revenue_cagr_3y: 0.05, revenue_cagr_5y: 0.08, revenue_cagr_10y: 0.09,
  },
  statements: {
    annual: [{ period_end: "2025-09-27", fy: 2025, fp: "FY", revenue: 4.0e11, net_income: 1.0e11 }],
    quarterly: [{ period_end: "2025-12-27", fy: 2026, fp: "Q1", revenue: 1.2e11, net_income: 3.5e10 }],
  },
  empty_state: null,
};

vi.mock("@/lib/api/client", async (importOriginal) => {
  const mod = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...mod, fetchStockFundamentals: vi.fn().mockResolvedValue(response) };
});

function renderTab() {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={qc}>
      <FundamentalsTab ticker="AAPL" />
    </QueryClientProvider>,
  );
}

describe("FundamentalsTab", () => {
  it("renders the valuation snapshot strip and trend charts", async () => {
    renderTab();
    await waitFor(() => expect(screen.getByText("$3.0T")).toBeInTheDocument());
    expect(screen.getByText("Market Cap")).toBeInTheDocument();
    expect(screen.getByText("30.5")).toBeInTheDocument(); // P/E
    expect(screen.getAllByTestId("hc-chart").length).toBeGreaterThanOrEqual(4);
  });

  it("shows the annual/quarterly toggle", async () => {
    renderTab();
    await waitFor(() => expect(screen.getByText("Annual")).toBeInTheDocument());
    expect(screen.getByText("Quarterly")).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd frontend && pnpm exec vitest run src/components/stocks/FundamentalsTab.test.tsx`
Expected: FAIL (module not found).

- [ ] **Step 3: Implement the component**

Structure (write complete code; ~250 lines):

```tsx
// frontend/src/components/stocks/FundamentalsTab.tsx
"use client";

/**
 * Fundamentals tab — company valuation snapshot, statement trend charts,
 * financial statements tables and growth/health panels. Single payload from
 * GET /stocks/{ticker}/fundamentals (two MV reads, see backend service).
 */
import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import {
  fetchStockFundamentals,
  type StockFundamentalsResponse,
  type StockStatementPeriod,
} from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  buildHcEpsOption,
  buildHcFcfOption,
  buildHcMarginsOption,
  buildHcRevenueNetIncomeOption,
} from "@/lib/charts/hc/stockFundamentals";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";
import { compactUsd } from "@/lib/grid/holdersGridOptions";
import { stockQueryKeys } from "@/lib/stocks/queries";

type Freq = "annual" | "quarterly";

export function FundamentalsTab({ ticker }: { ticker: string }) {
  const [freq, setFreq] = useState<Freq>("annual");
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => setColors(chartColors()), []);

  const query = useQuery({
    queryKey: stockQueryKeys.fundamentals(ticker),
    queryFn: () => fetchStockFundamentals(ticker),
    staleTime: 5 * 60 * 1000,
  });

  const data = query.data ?? null;
  const periods: StockStatementPeriod[] =
    (freq === "annual" ? data?.statements.annual : data?.statements.quarterly) ?? [];

  const revenueOption = useMemo(
    () => (colors && periods.length ? buildHcRevenueNetIncomeOption(periods, colors) : null),
    [colors, periods],
  );
  const marginsOption = useMemo(
    () => (colors && periods.length ? buildHcMarginsOption(periods, colors) : null),
    [colors, periods],
  );
  const epsOption = useMemo(
    () => (colors && periods.length ? buildHcEpsOption(periods, colors) : null),
    [colors, periods],
  );
  const fcfOption = useMemo(
    () => (colors && periods.length ? buildHcFcfOption(periods, colors) : null),
    [colors, periods],
  );

  if (query.isPending) {
    return <SectionMessage text="Loading fundamentals..." />;
  }
  if (query.isError) {
    return <SectionMessage text="Failed to load fundamentals." />;
  }
  if (!data || data.empty_state) {
    return (
      <SectionMessage
        text={data?.empty_state?.reason ?? "No fundamentals available."}
      />
    );
  }
  const s = data.snapshot;

  return (
    <div className="grid gap-4">
      {/* Valuation snapshot strip */}
      <section className="ix-pad border border-border bg-surface-2">
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <h2 className="ix-label m-0">Valuation snapshot</h2>
          {data.as_of ? (
            <span className="text-[11px] text-text-muted">
              Reported as of {formatDate(data.as_of)}
            </span>
          ) : null}
        </div>
        <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-3 xl:grid-cols-9">
          <Kpi label="Market Cap" value={s?.market_cap != null ? compactUsd(s.market_cap) : "—"} />
          <Kpi label="P/E" value={num(s?.pe_ttm, 1)} />
          <Kpi label="P/B" value={num(s?.pb, 1)} />
          <Kpi label="P/S" value={num(s?.ps, 1)} />
          <Kpi label="EV/EBITDA" value={num(s?.ev_ebitda, 1)} />
          <Kpi label="Div Yield" value={pct(s?.dividend_yield)} />
          <Kpi label="ROE" value={pct(s?.roe)} />
          <Kpi label="Net Margin" value={pct(s?.net_margin)} />
          <Kpi label="D/E" value={num(s?.de_ratio, 2)} />
        </div>
      </section>

      {/* Trend charts with A/Q toggle */}
      <section className="ix-pad border border-border bg-surface-2">
        <div className="mb-2.5 flex items-center justify-between gap-2">
          <h2 className="ix-label m-0">Trends</h2>
          <FreqToggle freq={freq} onChange={setFreq} />
        </div>
        <div className="grid gap-4 xl:grid-cols-2">
          <ChartBox title="Revenue & net income" option={revenueOption} />
          <ChartBox title="Margins" option={marginsOption} />
          <ChartBox title="Diluted EPS" option={epsOption} />
          <ChartBox title="Free cash flow" option={fcfOption} />
        </div>
      </section>

      {/* Statements tables (Task 9 fills StatementsSection) */}
      <StatementsSection data={data} freq={freq} />

      {/* Growth & health panels */}
      <div className="grid gap-4 xl:grid-cols-2">
        <GrowthPanel s={s} />
        <HealthPanel s={s} />
      </div>
    </div>
  );
}
```

Include in the same file (complete implementations):

```tsx
function num(v: number | null | undefined, dp: number): string {
  return v == null ? "—" : formatNumber(v, dp);
}
function pct(v: number | null | undefined): string {
  return v == null ? "—" : formatPercent(v, 1);
}

function Kpi({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-2 p-3">
      <div className="text-[10px] uppercase tracking-wide text-text-muted">{label}</div>
      <div className="text-[15px] font-bold tabular-nums text-text-primary">{value}</div>
    </div>
  );
}

function FreqToggle({ freq, onChange }: { freq: Freq; onChange: (f: Freq) => void }) {
  return (
    <div className="flex gap-px">
      {(["annual", "quarterly"] as const).map((f) => (
        <button
          key={f}
          type="button"
          onClick={() => onChange(f)}
          className={
            freq === f
              ? "bg-accent px-2.5 py-1 text-[11px] font-bold uppercase text-on-accent"
              : "border border-border px-2.5 py-1 text-[11px] uppercase text-text-secondary"
          }
        >
          {f === "annual" ? "Annual" : "Quarterly"}
        </button>
      ))}
    </div>
  );
}

function ChartBox({ title, option }: { title: string; option: Highcharts.Options | null }) {
  return (
    <div className="border border-border bg-surface-2 p-3">
      <h3 className="ix-label m-0 mb-2">{title}</h3>
      <div className="h-[260px]">
        {option ? (
          <HighchartsChart options={option} className="h-full" />
        ) : (
          <div className="flex h-full items-center justify-center text-[13px] text-text-muted">
            No data for this window.
          </div>
        )}
      </div>
    </div>
  );
}

function SectionMessage({ text }: { text: string }) {
  return (
    <section className="ix-pad border border-border bg-surface-2">
      <div className="flex h-40 items-center justify-center text-[13px] text-text-muted">
        {text}
      </div>
    </section>
  );
}

function GrowthPanel({ s }: { s: StockFundamentalsResponse["snapshot"] }) {
  const rows: Array<[string, (number | null | undefined)[]]> = [
    ["Revenue", [s?.revenue_cagr_1y, s?.revenue_cagr_3y, s?.revenue_cagr_5y, s?.revenue_cagr_10y]],
    ["Net income", [s?.net_income_cagr_1y, s?.net_income_cagr_3y, s?.net_income_cagr_5y, s?.net_income_cagr_10y]],
    ["Diluted EPS", [s?.eps_cagr_1y, s?.eps_cagr_3y, s?.eps_cagr_5y, s?.eps_cagr_10y]],
    ["Free cash flow", [s?.fcf_cagr_1y, s?.fcf_cagr_3y, s?.fcf_cagr_5y, s?.fcf_cagr_10y]],
  ];
  return (
    <section className="ix-pad border border-border bg-surface-2">
      <h2 className="ix-label m-0 mb-2.5">Growth (CAGR)</h2>
      <table className="w-full border-collapse text-[13px] tabular-nums">
        <thead>
          <tr>
            <th className="pb-1 text-left text-[10px] uppercase text-text-muted" />
            {["1Y", "3Y", "5Y", "10Y"].map((h) => (
              <th key={h} className="pb-1 text-right text-[10px] uppercase text-text-muted">{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map(([label, vals]) => (
            <tr key={label} className="border-t border-border">
              <td className="py-1.5 font-bold text-text-primary">{label}</td>
              {vals.map((v, i) => (
                <td
                  key={i}
                  className={`py-1.5 text-right ${
                    v == null ? "text-text-muted" : v >= 0 ? "text-gain" : "text-loss"
                  }`}
                >
                  {v == null ? "—" : formatPercent(v, 1)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function HealthPanel({ s }: { s: StockFundamentalsResponse["snapshot"] }) {
  const items: Array<[string, string]> = [
    ["Current ratio", num(s?.current_ratio, 2)],
    ["Debt / Equity", num(s?.de_ratio, 2)],
    ["Book value / share", s?.bvps != null ? `$${formatNumber(s.bvps, 2)}` : "—"],
    ["FCF / share", s?.fcf_ps != null ? `$${formatNumber(s.fcf_ps, 2)}` : "—"],
    ["Dividend / share (TTM)", s?.dps_ttm != null ? `$${formatNumber(s.dps_ttm, 2)}` : "—"],
    ["Payout ratio", pct(s?.payout_ratio)],
  ];
  return (
    <section className="ix-pad border border-border bg-surface-2">
      <h2 className="ix-label m-0 mb-2.5">Financial health & per share</h2>
      <div className="grid grid-cols-2 gap-px bg-border sm:grid-cols-3">
        {items.map(([label, value]) => (
          <Kpi key={label} label={label} value={value} />
        ))}
      </div>
    </section>
  );
}

// Task 9 replaces this stub with the full statements tables.
function StatementsSection(_props: {
  data: StockFundamentalsResponse;
  freq: Freq;
}) {
  return null;
}
```

Adjust import of `Highcharts.Options` type as done in sibling components
(e.g. `import type * as Highcharts from "highcharts"` or
`import type { Options } from "highcharts"` — mirror `FundProfileView.tsx`).

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && pnpm exec vitest run src/components/stocks/FundamentalsTab.test.tsx && pnpm typecheck`
Expected: PASS, clean typecheck.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/stocks/FundamentalsTab.tsx frontend/src/components/stocks/FundamentalsTab.test.tsx
git commit -m "feat(fundamentals): tab component — snapshot strip, trends, growth/health"
```

---

### Task 9: Statements tables (Income / Balance / Cash Flow)

**Files:**
- Modify: `frontend/src/components/stocks/FundamentalsTab.tsx` (replace the
  `StatementsSection` stub)
- Test: extend `frontend/src/components/stocks/FundamentalsTab.test.tsx`

**Interfaces:**
- Consumes: `StockFundamentalsResponse` + `Freq` from Task 8 (same file).
- Produces: full `StatementsSection` with sub-tabs
  `income | balance | cashflow`, periods as columns (most recent LEFT),
  sticky first column, `compactUsd` values, YoY % under each value cell in
  muted gain/loss color.

**Row definitions (labels → field keys):**
- Income: Revenue→revenue, Cost of revenue→cost_of_revenue, Gross
  profit→gross_profit, R&D→rnd_expense, SG&A→sga_expense, Operating
  income→operating_income, Pretax income→pretax_income, Income
  tax→income_tax, Net income→net_income, Diluted EPS→eps_diluted (formatted
  `$x.xx`, not compact), Diluted shares→shares_diluted.
- Balance: Cash & equivalents→cash, Current assets→current_assets, Total
  assets→assets, Current liabilities→current_liabilities, Short-term
  debt→st_debt, Long-term debt→lt_debt, Total liabilities→liabilities,
  Shareholders' equity→equity.
- Cash flow: Operating cash flow→ocf, Capital expenditures→capex, Free cash
  flow→fcf, D&A→d_and_a, Dividends paid→dividends_paid, Dividend /
  share→dps (formatted `$x.xx`).

- [ ] **Step 1: Write the failing test** (add to the existing describe):

```tsx
  it("renders statements tables with period columns and YoY deltas", async () => {
    renderTab();
    await waitFor(() => expect(screen.getByText("Income statement")).toBeInTheDocument());
    expect(screen.getByText("Balance sheet")).toBeInTheDocument();
    expect(screen.getByText("Cash flow")).toBeInTheDocument();
    // Annual default: FY 2025 column visible, revenue row present.
    expect(screen.getByText("2025")).toBeInTheDocument();
    expect(screen.getByText("Revenue")).toBeInTheDocument();
    expect(screen.getByText("$400.0B")).toBeInTheDocument();
  });
```

(Extend the mock's `statements.annual` with a second year
`{ period_end: "2024-09-28", fy: 2024, fp: "FY", revenue: 3.6e11, net_income: 0.9e11 }`
so YoY has a base; assert `+11.1%` appears.)

- [ ] **Step 2: Run test to verify it fails** (StatementsSection stub renders null).

- [ ] **Step 3: Implement StatementsSection** (in `FundamentalsTab.tsx`,
  replacing the stub):

```tsx
type StatementKind = "income" | "balance" | "cashflow";

type RowDef = {
  label: string;
  key: keyof StockStatementPeriod;
  perShare?: boolean; // format $x.xx instead of compact USD
  shares?: boolean;   // format compact count, no $
};

const STATEMENT_ROWS: Record<StatementKind, RowDef[]> = {
  income: [
    { label: "Revenue", key: "revenue" },
    { label: "Cost of revenue", key: "cost_of_revenue" },
    { label: "Gross profit", key: "gross_profit" },
    { label: "R&D", key: "rnd_expense" },
    { label: "SG&A", key: "sga_expense" },
    { label: "Operating income", key: "operating_income" },
    { label: "Pretax income", key: "pretax_income" },
    { label: "Income tax", key: "income_tax" },
    { label: "Net income", key: "net_income" },
    { label: "Diluted EPS", key: "eps_diluted", perShare: true },
    { label: "Diluted shares", key: "shares_diluted", shares: true },
  ],
  balance: [
    { label: "Cash & equivalents", key: "cash" },
    { label: "Current assets", key: "current_assets" },
    { label: "Total assets", key: "assets" },
    { label: "Current liabilities", key: "current_liabilities" },
    { label: "Short-term debt", key: "st_debt" },
    { label: "Long-term debt", key: "lt_debt" },
    { label: "Total liabilities", key: "liabilities" },
    { label: "Shareholders' equity", key: "equity" },
  ],
  cashflow: [
    { label: "Operating cash flow", key: "ocf" },
    { label: "Capital expenditures", key: "capex" },
    { label: "Free cash flow", key: "fcf" },
    { label: "D&A", key: "d_and_a" },
    { label: "Dividends paid", key: "dividends_paid" },
    { label: "Dividend / share", key: "dps", perShare: true },
  ],
};

const STATEMENT_TABS: Array<{ id: StatementKind; label: string }> = [
  { id: "income", label: "Income statement" },
  { id: "balance", label: "Balance sheet" },
  { id: "cashflow", label: "Cash flow" },
];

function cellValue(row: RowDef, p: StockStatementPeriod): number | null {
  const v = p[row.key];
  return typeof v === "number" ? v : null;
}

function formatCell(row: RowDef, v: number | null): string {
  if (v == null) return "—";
  if (row.perShare) return `$${formatNumber(v, 2)}`;
  if (row.shares) return formatNumber(v / 1e6, 0) + "M";
  return compactUsd(v);
}

function StatementsSection({
  data,
  freq,
}: {
  data: StockFundamentalsResponse;
  freq: Freq;
}) {
  const [kind, setKind] = useState<StatementKind>("income");
  const periods =
    (freq === "annual" ? data.statements.annual : data.statements.quarterly) ?? [];
  // Most recent LEFT.
  const cols = [...periods].sort((a, b) => b.period_end.localeCompare(a.period_end));
  if (cols.length === 0) return null;
  const rows = STATEMENT_ROWS[kind];

  return (
    <section className="ix-pad border border-border bg-surface-2">
      <div className="mb-2.5 flex items-center justify-between gap-2">
        <div className="flex gap-3">
          {STATEMENT_TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              onClick={() => setKind(t.id)}
              className={
                kind === t.id
                  ? "ix-label m-0 border-b-2 border-accent pb-0.5 text-text-primary"
                  : "ix-label m-0 pb-0.5 text-text-muted"
              }
            >
              {t.label}
            </button>
          ))}
        </div>
        <span className="text-[11px] text-text-muted">values in USD</span>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full min-w-[640px] border-collapse text-[13px] tabular-nums">
          <thead>
            <tr>
              <th className="sticky left-0 bg-surface-2 pr-3 text-left text-[10px] uppercase text-text-muted" />
              {cols.map((p) => (
                <th
                  key={p.period_end}
                  className="px-2 pb-1 text-right text-[10px] uppercase text-text-muted"
                >
                  {periodLabel(p)}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label} className="border-t border-border">
                <td className="sticky left-0 bg-surface-2 py-1.5 pr-3 font-bold text-text-primary">
                  {row.label}
                </td>
                {cols.map((p, i) => {
                  const v = cellValue(row, p);
                  const prev = i + 1 < cols.length ? cellValue(row, cols[i + 1]) : null;
                  const yoy =
                    v != null && prev != null && prev !== 0 ? v / prev - 1 : null;
                  return (
                    <td key={p.period_end} className="px-2 py-1.5 text-right align-top">
                      <div className="text-text-primary">{formatCell(row, v)}</div>
                      {yoy != null ? (
                        <div
                          className={`text-[11px] ${yoy >= 0 ? "text-gain" : "text-loss"}`}
                        >
                          {yoy >= 0 ? "+" : ""}
                          {formatNumber(yoy * 100, 1)}%
                        </div>
                      ) : null}
                    </td>
                  );
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
```

Import `periodLabel` from `@/lib/charts/hc/stockFundamentals`.

- [ ] **Step 4: Run tests + typecheck**

Run: `cd frontend && pnpm exec vitest run src/components/stocks/FundamentalsTab.test.tsx && pnpm typecheck`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/stocks/FundamentalsTab.tsx frontend/src/components/stocks/FundamentalsTab.test.tsx
git commit -m "feat(fundamentals): statements tables with YoY deltas"
```

---

### Task 10: Relocate shared format helpers out of holders grid options

**Files:**
- Modify: `frontend/src/lib/format.ts` (add `decodeEntities` [not exported if
  only used internally], `titleCase`, `compactUsd` — copy implementations
  verbatim from `frontend/src/lib/grid/holdersGridOptions.ts`)
- Modify: `frontend/src/lib/grid/holdersGridOptions.ts` (delete local copies;
  import `titleCase`, `compactUsd` from `@/lib/format`; keep re-exports
  `export { titleCase, compactUsd } from "@/lib/format";` so existing grid
  imports keep working until deletion)
- Modify: `frontend/src/lib/charts/hc/fundDossier.ts` (import from `@/lib/format`)
- Modify: `frontend/src/components/funds/FundProfileView.tsx` (import from `@/lib/format`)
- Modify: `frontend/src/lib/charts/hc/stockFundamentals.ts` +
  `frontend/src/components/stocks/FundamentalsTab.tsx` (import from `@/lib/format`)
- Test: `frontend/src/lib/format.test.ts` — add cases if the file exists;
  otherwise create with the two cases below.

- [ ] **Step 1: Add tests for the relocated helpers**

```typescript
// in frontend/src/lib/format.test.ts (create or extend)
import { describe, expect, it } from "vitest";
import { compactUsd, titleCase } from "@/lib/format";

describe("relocated shared format helpers", () => {
  it("titleCase normalizes SHOUTY names and preserves mixed case", () => {
    expect(titleCase("STATE STREET CORP")).toBe("State Street Corp");
    expect(titleCase("BlackRock, Inc.")).toBe("BlackRock, Inc.");
    expect(titleCase("JPMORGAN CHASE &amp; CO")).toBe("Jpmorgan Chase & Co");
  });
  it("compactUsd scales adaptively", () => {
    expect(compactUsd(1_500_000_000_000)).toBe("$1.5T");
    expect(compactUsd(336_400_000)).toBe("$336.4M");
    expect(compactUsd(null)).toBe("—");
  });
});
```

- [ ] **Step 2: Move the code** — copy `decodeEntities`, `titleCase`,
  `compactUsd` into `lib/format.ts` verbatim; replace originals in
  `holdersGridOptions.ts` with imports/re-exports; update the four consumer
  files' imports to `@/lib/format`.
- [ ] **Step 3: Run the full frontend suite**

Run: `cd frontend && pnpm exec vitest run && pnpm typecheck`
Expected: green (includes fundDossier + FundProfileView + grid tests).

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "refactor(format): relocate titleCase/compactUsd to lib/format"
```

---

### Task 11: Wire Fundamentals tab in, remove Holders UI

**Files:**
- Modify: `frontend/src/components/stocks/StockAnalysisView.tsx`
- Delete: `frontend/src/components/stocks/HoldersTab.tsx`
- Delete: `frontend/src/lib/grid/holdersGridOptions.ts` + its test file
- Delete: `frontend/src/lib/grid/fundHoldersTreeGridOptions.ts` + its test file
- Modify: any file that still imports the deleted modules (search first:
  `grep -r "holdersGridOptions\|fundHoldersTreeGridOptions\|HoldersTab" frontend/src`)

**Interfaces:**
- Consumes: `FundamentalsTab` (Task 8/9).
- Produces: stock page tabs = `analysis | fundamentals`; Fundamentals mounts
  lazily on first activation (mirror the old `holdersMounted` flag, renamed
  `fundamentalsMounted`).

- [ ] **Step 1: Update `StockAnalysisView.tsx`:**
  - `tab` state union: `"analysis" | "holders"` → `"analysis" | "fundamentals"`.
  - `holdersMounted` → `fundamentalsMounted` (same lazy-mount logic).
  - Tab button map: `["analysis", "holders"]` → `["analysis", "fundamentals"]`
    with label "Fundamentals".
  - Replace `<HoldersTab ticker={header.ticker} />` render block with
    `<FundamentalsTab ticker={header.ticker} />` under the same mount guard.
  - Remove the `HoldersTab` import; add the `FundamentalsTab` import.
- [ ] **Step 2: Delete the four files** (HoldersTab + 2 grid options + tests).
  Then fix any residual importer the grep finds. If `client.ts` exports
  `fetchStockHolders`/`fetchStockFundHolders` and their types are now unused,
  remove those exports too (typecheck will confirm).
- [ ] **Step 3: Run the full frontend suite**

Run: `cd frontend && pnpm exec vitest run && pnpm typecheck && pnpm lint`
Expected: green — adjust any test that referenced the holders tab.

- [ ] **Step 4: Commit**

```bash
git add -A frontend/src
git commit -m "feat(stocks): swap Holders tab for Fundamentals tab"
```

---

### Task 12: Remove Holders backend surface

**Files:**
- Modify: `backend/app/api/routes/stocks.py` (remove the two holders endpoints
  and their imports)
- Delete: `backend/app/services/stock_holders.py`
- Delete: `backend/app/schemas/stock_holders.py`
- Delete: `backend/app/models/stock_holders_mv.py`; remove its exports from
  `backend/app/models/__init__.py`
- Delete tests: `backend/tests/test_stock_holders_db_first.py`,
  `backend/tests/test_stock_holders_mv_models.py`,
  `backend/tests/test_stock_institutional_holders_mv_sql.py`,
  `backend/tests/test_stock_fund_holders_mv_sql.py`
- Delete DDL: `backend/db/ddl/2026-06-21_stock_institutional_holders_mv.sql`,
  `backend/db/ddl/2026-06-21_stock_fund_holders_mv.sql`
- Modify: `backend/tests/test_stock_fundamentals_route.py` (drop the
  `test_holders_routes_still_present_for_now` guard; assert holders routes
  are GONE)

**MUST NOT TOUCH:** `holding_reverse_lookup_mv` DDL/tests,
`fetch_holding_reverse_lookup`, `use_holders_db_first` setting, anything under
funds routes/services.

- [ ] **Step 1: Update the route test first**

```python
# in backend/tests/test_stock_fundamentals_route.py — replace the guard test:
def test_holders_routes_removed():
    paths = {r.path for r in app.routes}
    assert "/stocks/{ticker}/holders" not in paths
    assert "/stocks/{ticker}/holders/funds" not in paths
```

Run: `cd backend && uv run pytest tests/test_stock_fundamentals_route.py -q` — FAILS.

- [ ] **Step 2: Remove endpoints, delete the files listed above, clean
  `models/__init__.py` exports.** Search for stragglers:
  `grep -rn "stock_holders\|StockHoldersResponse\|StockFundHoldersResponse\|stock_institutional_holders_mv\|stock_fund_holders_mv" backend/app backend/tests` — must return nothing (except the reverse-lookup files, which reference neither).
- [ ] **Step 3: Regenerate OpenAPI + frontend types** (same procedure as
  Task 5 Step 5) so the removed endpoints leave the contract.
- [ ] **Step 4: Run the full backend suite**

Run: `cd backend && uv run pytest -q`
Expected: green (pre-existing failures unrelated to holders are acceptable —
compare against a `git stash` baseline run if unsure).
Also: `cd frontend && pnpm typecheck` (regenerated api.d.ts must not break
remaining code).

- [ ] **Step 5: Commit**

```bash
git add -A backend frontend/src/lib/api/api.d.ts backend/openapi.json
git commit -m "feat(stocks)!: remove Holders endpoints, services and MV DDL"
```

---

### Task 13 (ORCHESTRATOR): Verify, merge, deploy, drop old MVs

- [ ] Browser-verify on the dev server (worktree serves this branch):
  `/stocks/AAPL` → Fundamentals tab: snapshot strip populated, 4 trend charts,
  statements tables with YoY, A/Q toggle works, Holders tab gone. Also check a
  financial (JPM — sparse income lines render "—") and a ticker without
  coverage (empty state).
- [ ] Full gates: `cd backend && uv run pytest -q`;
  `cd frontend && pnpm exec vitest run && pnpm typecheck && pnpm lint`.
- [ ] Merge `feat/stock-fundamentals-tab` → `main`, push.
- [ ] Deploy `api` on Railway (service `6c7ae990-2751-466e-89d0-5b94c72f4679`,
  env `production`, path = worktree root). Verify `/health` 200 and
  `GET /stocks/AAPL/fundamentals` 200 on
  `api-production-2b6d.up.railway.app`.
- [ ] Drop the old MVs on Tiger (AFTER the new tab is verified live):

```sql
-- check dependencies first; expect none
SELECT dependent_ns.nspname, dependent_view.relname
FROM pg_depend d
JOIN pg_rewrite r ON r.oid = d.objid
JOIN pg_class dependent_view ON dependent_view.oid = r.ev_class
JOIN pg_namespace dependent_ns ON dependent_ns.oid = dependent_view.relnamespace
WHERE d.refobjid IN ('stock_institutional_holders_mv'::regclass,
                     'stock_fund_holders_mv'::regclass,
                     'sec_13f_entry'::regclass)
  AND dependent_view.relname NOT IN ('stock_institutional_holders_mv','stock_fund_holders_mv','sec_13f_entry');

DROP MATERIALIZED VIEW IF EXISTS stock_institutional_holders_mv;
DROP MATERIALIZED VIEW IF EXISTS stock_fund_holders_mv;
DROP MATERIALIZED VIEW IF EXISTS sec_13f_entry;
```

- [ ] Update memory (`stock-fundamentals-tab` note: MVs live, refresh cadence,
  holders retired).

---

## Self-Review Notes

- Spec coverage: MVs (T1–T3), API (T4–T5), client (T6), charts (T7), UI
  sections 1–4 (T8–T9), helper relocation (T10), holders UI removal (T11),
  holders backend removal (T12), rollout order — drop MVs last (T13). Interest
  coverage intentionally NULL (spec v1). Insiders/IFRS/peers out of scope.
- Type consistency: `StockStatementPeriod` field names match MV1 columns and
  the row defs in T9; `Freq`/`periodLabel` shared within T8/T9 file; builders
  consume the generated client type (T6 precedes T7 at typecheck time).
- Ordering constraint: T5 regenerates types BEFORE T6/T7 use them. T10 runs
  after T7/T8 so the `compactUsd` import swap has all consumers in place.
