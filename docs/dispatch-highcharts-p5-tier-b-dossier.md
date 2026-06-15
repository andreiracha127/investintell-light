# Dispatch — Highcharts Migration P5 Tier B Dossier

**Date:** 2026-06-15  
**Repo:** `E:\investintell-light`  
**Branch:** current checkout is expected to be `main`. Verify before work.  
**Purpose:** continue the Highcharts/funds dossier plan after P3/P4, implementing P5: Backend Tier B endpoints plus dossier tabs/modals.

## Current Baseline

At dispatch creation time, current recent commits were:

- `65e6c87 feat(charts): consume range-aware timeseries endpoints` — P3 wiring.
- `dbad6de feat(funds): add Tier A dossier endpoints` — P4 backend Tier A.

The checkout already exposes P4 Tier A backend contracts:

- `/funds/scatter`
- `/funds/{instrument_id}/analysis`
- `/funds/{instrument_id}/holdings/top`
- `/funds/{instrument_id}/peers`

Do not assume the P4 frontend shell is complete just because the Tier A backend exists. P5 must begin by verifying the route/page actually has a dossier shell ready to receive the P5 tabs and modal.

## Preserve Dirty Work

Before editing, run:

```powershell
git status --short --branch
```

At the time this dispatch was written, these unrelated untracked files existed and must not be staged, removed, reformatted, or normalized unless the owner explicitly authorizes it:

- `.idea/AugmentWebviewStateStore.xml`
- `backend/_gate_vs_full_backtest.py`
- `backend/_navdata.csv`
- `backend/_navdata.err`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

## Read First

Read these files before coding:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/dispatch-highcharts-p3-p4-continuation.md`
4. `backend/app/api/routes/funds.py`
5. `backend/app/services/fund_analysis.py`
6. `backend/app/schemas/fund_analysis.py`
7. `frontend/src/app/funds/[id]/page.tsx`
8. `frontend/src/components/funds/FundProfileView.tsx`
9. `frontend/src/lib/api/client.ts`

Use repo truth over this dispatch if the code has moved. Record any drift before changing files.

## Required Opening Verification

Run:

```powershell
rg -n "P5|Tier B|style-drift|factors|entity-analytics|risk-timeseries|active-share|Deep Analysis" docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md
rg -n "funds/.*/(analysis|holdings/top|peers)|funds/scatter|fetchFundAnalysis|fetchFundPeers|fetchFundsScatter|fetchFundHoldingsTop|Tabs|Deep Analysis" backend/app frontend/src backend/openapi.json
rg -n "style-drift|factors|entity-analytics|risk-timeseries|active-share|fund_holdings_history_v|factor_model_fits|equity_characteristics_monthly|regime_composite_daily" backend/app frontend/src backend/openapi.json
```

Expected:

- P4 Tier A backend endpoints exist.
- P5 endpoints do not exist yet, unless another session has already started them.
- If P4 frontend shell/client fetchers are missing, either complete the minimal P4 shell needed to host P5 or stop and report the blocker. Do not fake P5 UI on top of only `FundProfileView`.

## P5 Scope

Implement P5 only:

- Backend Tier B:
  - `GET /funds/{id}/factors`
  - `GET /funds/{id}/style-drift?quarters=`
  - `GET /funds/{id}/entity-analytics?window=&benchmark_id=`
  - `GET /funds/{id}/risk-timeseries?from=&to=`
  - `GET /funds/{id}/active-share?benchmark_id=`
  - Any required MV/view extension for the above.
- Frontend dossier tabs/modals:
  - Performance
  - Holdings
  - Style
  - Factors
  - Peers
  - Deep Analysis modal

Do not implement P6 caching, P7 SEC/insider pipelines, or P8 removal of ECharts/ixchart in this dispatch.

## P5 Non-Scope

- No deploy unless explicitly requested.
- No PR unless explicitly requested.
- No fake or synthetic analytics to make empty tabs look complete.
- No broad design-system redesign.
- No removal of old chart libraries.
- No Tier C endpoints:
  - `/funds/{id}/institutional-reveal`
  - `/holdings/{cusip}/reverse-lookup`
  - populated `insider_data`

Before P7, Tier C panels must render explicit empty states.

## Backend Tasks

### 1. Define schemas

Extend `backend/app/schemas/fund_analysis.py` or add a focused schema module if it is already too large.

Required response families:

- `FundFactorsResponse`
  - `market_sensitivities`
  - `style_bias`
  - source metadata and as-of dates
- `FundStyleDriftResponse`
  - quarters/report dates
  - sector weights by period
  - empty-state reason when historical holdings are unavailable
- `FundEntityAnalyticsResponse`
  - `risk_statistics`
  - `drawdown` with `dates`, `values`, `worst_periods`
  - `capture` up/down
  - `rolling_returns.series` for `1M`, `3M`, `6M`, `1Y`
  - `distribution` with FD bins, skewness, kurtosis, VaR/CVaR
  - `return_statistics`
  - `tail_risk` with parametric VaR 90/95/99, modified VaR 95/99, ETL 95, STARR, Rachev, Jarque-Bera
  - `insider_data: null` until P7
- `FundRiskTimeseriesResponse`
  - drawdown in percent
  - conditional volatility in percent
  - regime bands shaped as `{time,value,regime}`
- `FundActiveShareResponse`
  - benchmark identity
  - active share value when computable
  - explicit empty-state reason otherwise

Keep Pydantic v2 types strict. Avoid untyped dict responses from routes.

### 2. Implement data access/services

Add focused service functions near `backend/app/services/fund_analysis.py` unless the file has become too large; if so, split Tier B into `fund_dossier_tier_b.py` and keep route imports clear.

Contract details from the spec:

- `/factors`
  - `market_sensitivities`: OLS of fund returns over `factor_model_fits`; include t-stat/significance where available.
  - `style_bias`: cross-sectional z-scores from `equity_characteristics_monthly`.
- `/style-drift`
  - Requires a new view or equivalent query over historical `sec_nport_holdings`.
  - Preferred view name: `fund_holdings_history_v`.
  - Aggregate sector weights by quarter/report date.
- `/entity-analytics`
  - Port the quant-engine style analytics from existing local helpers where possible.
  - Use 252 trading-day convention and `rf=0.04` unless current repo code already centralizes this differently.
  - Modified VaR is Cornish-Fisher.
  - Benchmark comes from `benchmark_id`; if unavailable, degrade explicitly.
- `/risk-timeseries`
  - Drawdown is NAV vs rolling/window max, output in percent.
  - Conditional volatility is GARCH(1,1) via `arch` if dependency is present or added.
  - If adding `arch`, use the repo's package manager and add tests/lockfile updates.
  - Regime labels map to `Expansion`, `Cautious`, `Stress`.
- `/active-share`
  - Only compute when benchmark resolves to a fund with N-PORT holdings.
  - Formula: `0.5 * sum(abs(w_portfolio - w_benchmark))`.
  - Otherwise return an empty state, not a fake zero.

Fail loud for missing fund, invalid benchmark, impossible windows, and oversized responses.

### 3. Add routes

In `backend/app/api/routes/funds.py`, add:

```text
GET /funds/{instrument_id}/factors
GET /funds/{instrument_id}/style-drift?quarters=
GET /funds/{instrument_id}/entity-analytics?window=&benchmark_id=
GET /funds/{instrument_id}/risk-timeseries?from=&to=
GET /funds/{instrument_id}/active-share?benchmark_id=
```

Use the existing P4 error style and status codes. Keep route order safe: literal routes such as `/funds/scatter` must stay before parameterized `/funds/{instrument_id}` routes.

### 4. Database view/migration

If P5 needs a new DB view or MV:

- Inspect existing migration conventions first.
- Create a reversible migration or SQL artifact according to repo practice.
- Do not run destructive SQL against production.
- If live DB privileges or source tables are unavailable, stop with a concrete blocker and the exact missing relation/permission.

### 5. Backend tests

Add/extend tests for:

- happy-path schema shape for each endpoint
- missing fund / invalid benchmark
- limit/window/quarter bounds
- active-share empty state
- style-drift empty state
- risk-timeseries percent scaling and regime relabel
- entity analytics tail-risk fields

Prefer deterministic fixtures and service-level tests for heavy analytics. Avoid fragile tests that require live DB unless the repo already marks them as integration.

## Frontend Tasks

### 1. Regenerate contracts

After backend route/schema changes:

- regenerate `backend/openapi.json`
- regenerate `frontend/src/lib/api/api.d.ts`
- update `frontend/src/lib/api/client.ts`

Add fetchers:

- `fetchFundFactors`
- `fetchFundStyleDrift`
- `fetchFundEntityAnalytics`
- `fetchFundRiskTimeseries`
- `fetchFundActiveShare`

Keep existing P4 fetchers intact.

### 2. Complete dossier tab wiring

Use the existing `frontend/src/app/funds/[id]/page.tsx` and funds components as the app surface.

Required tabs:

- `Performance`
  - P4 analysis charts plus P5 risk overlay where applicable.
- `Holdings`
  - P4 holdings/top plus active-share panel when benchmark is selected.
- `Style`
  - style-drift stacked area.
- `Factors`
  - style-bias radar or compact bar/radar equivalent.
  - factor sensitivities bars with significance/t-stat affordance.
- `Peers`
  - P4 peer table/scatter; do not invent P5 peer data unless backend supplies it.

Required modal:

- `Deep Analysis`
  - sections A-H from the spec:
    - risk stats
    - underwater/drawdown
    - capture
    - rolling returns
    - distribution + VaR/CVaR
    - return stats
    - tail-risk ladder
    - insider empty-state until P7

Use Graphite/Cockpit visual language: dense, analytical, no marketing hero, no nested cards. Make tabs linkable or at least stable in component state; avoid brittle local-only state if current routing already supports query params.

### 3. Charts

Use existing Highcharts wrappers/builders. If new builders are required, add pure builder functions under `frontend/src/lib/charts/hc/` with Vitest coverage.

Likely builders:

- style drift stacked area
- factor sensitivity bars
- style bias radar/bar
- risk overlay / drawdown
- tail-risk ladder

Keep all data computation in backend/services or pure adapters. Frontend should format and render, not recompute finance.

### 4. Empty/loading/error states

Every P5 panel needs:

- loading state
- explicit empty-state with source-aware reason
- error state preserving backend detail
- no fake placeholder metrics

Tier C content must say unavailable until P7, not silently disappear.

## Validation Gates

Backend:

```powershell
cd backend
python -m pytest tests -q
```

If the full backend suite has known unrelated failures, run targeted P5 tests plus the nearest existing funds/timeseries tests, and report exactly what was not run.

Frontend:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Browser:

- Start backend/frontend locally on free ports.
- Open a real fund dossier route.
- Verify all tabs render without blank charts.
- Open Deep Analysis modal.
- Exercise a benchmark selection/path for active share if the UI supports it.
- Verify light and dark themes if theme controls are available.
- Confirm no text overlap at desktop and mobile widths.
- In DevTools/network or logs, confirm P5 endpoints are actually called.

## Commit Discipline

Use focused commits. Suggested split:

```powershell
git commit -m "feat(funds): add Tier B dossier analytics endpoints"
git commit -m "feat(funds): wire Tier B dossier tabs and deep analysis"
```

Do not stage unrelated untracked files. Before every commit:

```powershell
git status --short
git diff --stat
```

## Stop Conditions

Stop and report instead of guessing if:

- P4 shell is missing and the required P5 UI host is unclear.
- Source relations like `factor_model_fits`, `equity_characteristics_monthly`, `sec_nport_holdings`, or `regime_composite_daily` are absent or inaccessible.
- `arch` cannot be installed or imported and no approved fallback exists.
- OpenAPI/type generation command is missing or fails in a way that changes unrelated contracts.
- Browser auth/data access blocks visual validation.

## Final Report Shape

Report in Portuguese:

1. Branch and final HEAD SHA(s).
2. Which P5 backend endpoints landed.
3. Which dossier tabs/modal sections are wired.
4. Exact gates run and results.
5. Browser evidence: route, viewport/theme, and endpoints observed.
6. Any blockers, skipped gates, or known unrelated dirty files.

Do not deploy, push, or open PR unless the owner explicitly asks.
