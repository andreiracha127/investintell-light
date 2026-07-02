# Stock Fundamentals Tab — Design

**Date:** 2026-07-02
**Status:** Approved (brainstorm 2026-07-02)
**Scope:** New "Fundamentals" tab on the stock detail page, fed by two new
materialized views over the SEC XBRL dataset; full removal of the "Holders"
tab and its dedicated backend surface.

## Goal

Give each selected company a Morningstar/YFinance/Barchart-class fundamentals
view — valuation snapshot, full financial statements (10 annual years +
8 quarters), margin/growth/health analytics — served from precomputed
materialized views so the page loads in milliseconds. Remove the Holders tab,
whose MVs are the heaviest refresh in the system (>14 min) and whose content
adds little value.

## Data inventory (verified in prod Tiger, 2026-07-02)

| Source | Size | Content |
|---|---|---|
| `sec_xbrl_facts` (hypertable) | ~106M rows | Full XBRL company facts per CIK: every us-gaap concept, quarterly + annual, history 15+ years through latest quarter. Indexed `(cik, taxonomy, concept, period_end DESC)` and `(concept, period_end DESC) WHERE taxonomy='us-gaap'`. |
| `screener_metrics` | 4,780 tickers, daily | market_cap, pe_ratio, roe, roa, gross_margin, de_ratio, price_close, returns/vols/betas. |
| `universe_constituents` | 5,152 | ticker → cik + sector. 4,226 CIKs (82%) have XBRL with period_end ≥ 2025. |
| `fundamentals_snapshot` | 5,152 | per-ticker snapshot incl. shares_outstanding. |

Coverage note: v1 is `taxonomy='us-gaap'` only. Financials (banks/insurers)
use bespoke concepts for several lines → those cells are NULL and render "—".
IFRS filers are out of scope for v1.

## Architecture — chosen approach

Two MVs + one endpoint ("Approach A"). Normalization (concept COALESCE, TTM,
Q4 derivation, CAGRs) runs once at refresh time inside the MVs, not per
request. Alternatives rejected: live XBRL queries per ticker (repeats
normalization per visit; user explicitly asked for MVs) and precomputed JSON
artifacts (needless worker infra; normalization fits in SQL).

### MV 1 — `stock_fundamentals_statements_mv`

Grain: `(ticker, freq, period_end)` with `freq ∈ ('A','Q')`.
Window: 10 fiscal years of `A` rows; 8 most recent `Q` rows.

Sources: `sec_xbrl_facts` joined to `universe_constituents` (ticker→cik).

Fact selection rules:
- **Dedup / restatements:** the same `(cik, concept, period_end)` appears in
  multiple filings; take the value with the latest `filed` date
  (`DISTINCT ON ... ORDER BY filed DESC`) so restated figures win.
- **Annual flow (duration) facts:** `form='10-K'`, `fp='FY'`, duration
  `period_end - period_start` in 330–380 days.
- **Quarterly flow facts:** duration 80–100 days (from 10-Q or 10-K).
  **Q4 derivation:** most companies file only FY durations in the 10-K, so
  when a fiscal quarter-end has no ~90-day fact, derive
  `Q4 = FY − (Q1+Q2+Q3)` per concept when FY and all three quarters exist;
  else NULL.
- **Instant (balance-sheet) facts:** value at `period_end`; exist for every
  quarter-end (10-Q + 10-K), no derivation needed.
- **Units:** monetary → `unit='USD'`; per-share → `'USD/shares'`;
  share counts → `'shares'`.

Normalized columns (concept COALESCE priority, first non-null):

| Column | XBRL concepts (priority order) |
|---|---|
| revenue | RevenueFromContractWithCustomerExcludingAssessedTax, Revenues, SalesRevenueNet |
| cost_of_revenue | CostOfGoodsAndServicesSold, CostOfRevenue, CostOfGoodsSold |
| gross_profit | GrossProfit (else revenue − cost_of_revenue) |
| rnd_expense | ResearchAndDevelopmentExpense |
| sga_expense | SellingGeneralAndAdministrativeExpense |
| operating_income | OperatingIncomeLoss |
| pretax_income | IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest |
| income_tax | IncomeTaxExpenseBenefit |
| net_income | NetIncomeLoss |
| eps_diluted | EarningsPerShareDiluted |
| shares_diluted | WeightedAverageNumberOfDilutedSharesOutstanding |
| d_and_a | DepreciationDepletionAndAmortization, DepreciationAmortizationAndAccretionNet |
| assets | Assets |
| liabilities | Liabilities |
| equity | StockholdersEquity, StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest |
| cash | CashAndCashEquivalentsAtCarryingValue |
| st_debt | LongTermDebtCurrent, DebtCurrent |
| lt_debt | LongTermDebtNoncurrent, LongTermDebt |
| current_assets | AssetsCurrent |
| current_liabilities | LiabilitiesCurrent |
| ocf | NetCashProvidedByUsedInOperatingActivities |
| capex | PaymentsToAcquirePropertyPlantAndEquipment |
| fcf | computed: ocf − capex |
| dividends_paid | PaymentsOfDividendsCommonStock, PaymentsOfDividends |
| dps | CommonStockDividendsPerShareDeclared |

Plus metadata: `fy`, `fp`, `filed` (latest contributing filing date).
Unique index `(ticker, freq, period_end)`; secondary index `(ticker)`.

### MV 2 — `stock_fundamentals_snapshot_mv`

Grain: one row per ticker. Built on top of MV 1 (latest rows / TTM sums) +
`screener_metrics` (daily price/market data) + `fundamentals_snapshot`
(shares outstanding fallback).

Columns:
- Identity: ticker, cik, sector, latest_period_end, latest_filed.
- Valuation: market_cap, pe_ttm (screener), pb (mcap/equity), ps
  (mcap/revenue_ttm), ev (mcap + st_debt + lt_debt − cash),
  ev_ebitda (ev / (operating_income_ttm + d_and_a_ttm)),
  dividend_yield (dps_ttm / price_close).
- TTM lines: revenue_ttm, net_income_ttm, eps_ttm, ocf_ttm, capex_ttm,
  fcf_ttm, dps_ttm (sum of last 4 Q rows; fall back to latest FY when
  quarters are incomplete).
- Margins/returns (TTM): gross_margin, operating_margin, net_margin,
  roe, roa (from screener_metrics where present, else computed).
- Health: de_ratio ((st_debt+lt_debt)/equity), current_ratio,
  interest_coverage left NULL in v1 (interest expense concept coverage is
  inconsistent; revisit in v2).
- Per share: bvps (equity/shares), fcf_ps, dps_ttm, payout_ratio
  (dps_ttm × shares / net_income_ttm).
- Growth CAGRs from annual rows: revenue/net_income/eps_diluted/fcf ×
  1y/3y/5y/10y (NULL when the base year is missing or non-positive).

Unique index `(ticker)`.

### Refresh

DDL files in `backend/db/ddl/` following house style, each ending with its
`REFRESH MATERIALIZED VIEW` statement. Applied and refreshed via Tiger MCP
(house migration pattern). Cadence: daily refresh is sufficient (XBRL lands
with filings; screener_metrics is daily) and orders of magnitude cheaper
than the removed holders MVs — statements MV scans ~30 concepts through the
partial cross-sectional index restricted to universe CIKs.

## API

`GET /stocks/{ticker}/fundamentals` → `StockFundamentalsResponse`:

```
{
  ticker, as_of,                      // latest_filed / snapshot as-of
  snapshot: { ...MV2 row... } | null,
  statements: {
    annual:    [ {period_end, fy, ...MV1 columns...}, ... ],  // ≤10, desc
    quarterly: [ ... ],                                        // ≤8, desc
  },
  empty_state: { reason } | null      // ticker without CIK/XBRL coverage
}
```

Single payload (~40 periods × ~25 numeric fields), two indexed reads, private
cache headers like sibling stock endpoints. New service
`app/services/stock_fundamentals.py`; Pydantic schemas in
`app/schemas/stock_fundamentals.py`; OpenAPI regenerated
(`pnpm types`) for the frontend contract.

## Frontend

Tab wiring in `StockAnalysisView.tsx`: tab union becomes
`"analysis" | "fundamentals"`; Fundamentals mounts lazily on first activation
(same pattern Holders used). New `components/stocks/FundamentalsTab.tsx`
with React Query key `["stock-fundamentals", ticker]`.

Sections (top to bottom), all Graphite/Carbon styled, charts via existing
`HighchartsChart` + new pure builders in `lib/charts/hc/stockFundamentals.ts`:

1. **Snapshot strip** — KpiTiles: Market Cap, P/E, P/B, P/S, EV/EBITDA,
   Dividend Yield, ROE, Net Margin, D/E. Values via `compactUsd` /
   `formatPercent`; "—" for NULL.
2. **Trend charts** (2×2 grid, Annual/Quarterly toggle shared):
   Revenue & Net Income (columns, brand accent + muted, end labels);
   Margins % (3 lines: gross/operating/net); Diluted EPS (columns);
   Free Cash Flow (columns).
3. **Statements** — sub-tabs Income Statement | Balance Sheet | Cash Flow,
   Annual/Quarterly toggle, periods as columns (most recent left), sticky
   row-label column, values `compactUsd`. YoY % change renders as a small
   muted line under each value cell (gain/loss colored), not as extra
   columns.
4. **Growth & Health panels** — CAGR table (metric × 1/3/5/10y) and
   health/per-share tiles (current ratio, D/E, BVPS, FCF/share, DPS,
   payout ratio).

Empty state: card explaining no SEC XBRL coverage for the ticker.

## Holders removal (full cleanup)

Verified consumer boundary (2026-07-02): the two stock holders endpoints and
`stock_holders.py` service are consumed ONLY by `HoldersTab`. The reverse
lookup (`fetch_holding_reverse_lookup`, `holding_reverse_lookup_mv`) is
consumed by the FUNDS routes and MUST stay, as must the
`use_holders_db_first` flag that gates it.

Frontend:
- `StockAnalysisView.tsx`: remove `holders` tab state/branches; delete
  `HoldersTab.tsx`.
- **Relocate first:** `titleCase`, `decodeEntities`, `compactUsd` move from
  `lib/grid/holdersGridOptions.ts` to `lib/format.ts` (they are now used by
  the funds dossier); update the surviving importers — `fundDossier.ts` and
  `FundProfileView.tsx`.
- Delete `lib/grid/holdersGridOptions.ts` and
  `lib/grid/fundHoldersTreeGridOptions.ts` (+ their tests).

Backend:
- Remove `GET /stocks/{ticker}/holders` and `/holders/funds` from
  `routes/stocks.py`; delete `app/services/stock_holders.py`,
  `app/schemas/stock_holders.py`, `app/models/stock_holders_mv.py` exports,
  and the four stock-holders test files.
- Keep `holding_reverse_lookup_mv`, `fetch_holding_reverse_lookup`,
  `use_holders_db_first`.

Database (via Tiger MCP, after checking `pg_depend` for external consumers):
- `DROP MATERIALIZED VIEW stock_institutional_holders_mv;`
- `DROP MATERIALIZED VIEW stock_fund_holders_mv;`
- `DROP MATERIALIZED VIEW sec_13f_entry;` (only consumer was the holders
  path — verified 2026-07-02)
- Remove their DDL files from `backend/db/ddl/`.

This retires the >14-minute refresh entirely.

## Testing

House patterns:
- DDL string tests for both new MVs (concept lists, dedup rule, indexes,
  REFRESH statement) — mirrors `test_*_mv_sql.py`.
- Service test with fake sessions: payload assembly, empty state, TTM
  fallback to FY.
- Frontend: builder tests for `stockFundamentals.ts` (series shape, accent
  color, compact USD labels, A/Q switch); component test for tab switch and
  statements table rendering; removal assertions (no holders tab).
- Existing suites adjusted where they referenced the holders tab/endpoints.

## Rollout

1. Land MVs in prod via Tiger MCP (initial build ≈ initial REFRESH), verify
   row counts and spot-check AAPL/MSFT/JPM (incl. a financial with sparse
   lines).
2. Backend endpoint + tests; deploy `api` on Railway.
3. Frontend tab + holders removal; browser-verify on the dev server.
4. Drop holders MVs last (after the new tab is live), so a rollback never
   needs a 14-minute rebuild.

## Out of scope (v2 candidates)

Insider transactions section (data exists: `sec_insider_transactions`,
59.7k rows), IFRS/dei taxonomy fallbacks, interest coverage, segment data,
peer comparison table, analyst estimates (no data source yet).
