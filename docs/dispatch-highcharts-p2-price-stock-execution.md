# Dispatch - Execute Highcharts P2 Price Stock

**Date:** 2026-06-15  
**Repo:** `E:\investintell-light`  
**Plan source:** `docs/superpowers/plans/2026-06-15-highcharts-p2-price-stock.md`  
**Plan commit:** `683232d docs: plan highcharts p2 price stock`  
**Purpose:** execute P2 before P8 by migrating the live `InteractiveChart` from the custom canvas `ixchart` engine to Highcharts Stock.

## Decision

Run P2 before P8.

P8 removes `echarts`, `ixchart`, old builders, and dead chart code. That cleanup is unsafe while `frontend/src/components/charts/InteractiveChart.tsx` still imports `@/lib/ixchart/*`. P2 is therefore a formal blocker for P8.

## Current Baseline

At dispatch creation time, the active checkout was:

- branch: `feat/highcharts-p6-cache-ssr`
- recent committed P6 work:
  - `d862361 feat(funds): add cached dossier route handlers`
  - `ea30bd9 feat(funds): hydrate dossier queries on first paint`
- P7 dispatch:
  - `2cc1f02 docs: add Highcharts P7 SEC dispatch`
- P7 execution, now complete per owner and current log:
  - `8aeda11 feat(funds): add Tier C institutional endpoints`
  - `99c6f31 feat(funds): wire Tier C dossier relationships`

P7 is no longer considered pending dirty work for this dispatch. The remaining blocker for P8 is the live `InteractiveChart` dependency on `ixchart`.

## Preserve Dirty Work

Before any work, run:

```powershell
git status --short --branch
```

At dispatch update time after P7 completion, the current checkout had only unrelated untracked files plus this P2 dispatch file. Preserve unrelated files.

Known unrelated untracked files:

- `.idea/AugmentWebviewStateStore.xml`
- `backend/_gate_vs_full_backtest.py`
- `backend/_navdata.csv`
- `backend/_navdata.err`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

## Recommended Execution Surface

Use a clean worktree for P2. This is still recommended even after P7 completion because P2 is a focused frontend chart migration and should not mix with future P7/P8 follow-up work.

From `E:\investintell-light`:

```powershell
git worktree add E:\investintell-light-p2 -b feat/highcharts-p2-price-stock HEAD
cd E:\investintell-light-p2
git status --short --branch
```

If branch name already exists, pick a unique branch name such as `feat/highcharts-p2-price-stock-2`. Do not stash, reset, or clean the primary worktree unless the owner explicitly asks.

## Read First

In the clean P2 worktree, read:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/superpowers/plans/2026-06-15-highcharts-p2-price-stock.md`
4. `frontend/src/components/charts/InteractiveChart.tsx`
5. `frontend/src/components/charts/HighchartsStockChart.tsx`
6. `frontend/src/components/charts/SymbolSearchInput.tsx`
7. `frontend/src/lib/livefeed/client.ts`
8. `frontend/src/lib/api/client.ts`
9. `frontend/src/components/stocks/StockAnalysisView.tsx`
10. `frontend/src/components/funds/FundProfileView.tsx`

Use repo truth over stale plan snippets. The plan predates P3/P6 execution, so adapt where timeseries fetchers and dossier cache code already exist.

## Required Opening Verification

Run:

```powershell
rg -n "ixchart|Chart |readIxTokens|fmtP|fmtV|ChartType|DrawTool|Period" frontend/src/components/charts/InteractiveChart.tsx frontend/src/lib/livefeed/client.ts
rg -n "HighchartsStockChart|stock-tools|annotations|gui.css|popup.css|highstock" frontend/src/components/charts frontend/src/app/layout.tsx
rg --files frontend/src/lib/charts/hc | rg "priceStock|priceStockLive|theme|test"
rg -n "fetchStockTimeseries|fetchFundTimeseries|InteractiveChart" frontend/src/components/stocks/StockAnalysisView.tsx frontend/src/components/funds/FundProfileView.tsx frontend/src/lib/api/client.ts
```

Expected at dispatch creation:

- `InteractiveChart.tsx` still imports `Chart`, `readIxTokens`, `fmtP`, `fmtV`, and ixchart types.
- `frontend/src/lib/livefeed/client.ts` still imports `Tick` from `@/lib/ixchart/types`.
- `priceStock.ts` and `priceStockLive.ts` do not exist yet.
- `fetchStockTimeseries` and `fetchFundTimeseries` exist and should be reused.

## P2 Scope

Implement only P2:

- Keep `InteractiveChart` as the app-facing component API.
- Replace canvas `ixchart` rendering with `HighchartsStockChart`.
- Add pure Highcharts Stock option builder logic in `frontend/src/lib/charts/hc/priceStock.ts`.
- Add live tick merge helpers in `frontend/src/lib/charts/hc/priceStockLive.ts`.
- Register required Highcharts Stock modules/CSS.
- Preserve price/NAV display, range sync, compare, live ticks, indicators, and drawing affordances as much as Highcharts Stock supports natively.
- Add multi-symbol compare support per the existing plan.

Do not remove `frontend/src/lib/ixchart/*` in P2. P8 removes it after P2 is green and no imports remain.

## P2 Non-Scope

- No P8 cleanup.
- No deletion of `echarts`.
- No backend changes.
- No deploy unless explicitly requested.
- No P7 SEC/Tier C edits.
- No broad redesign of stock/fund pages.
- No changes to query contracts beyond using existing timeseries data.

## Execution Tasks

### Task 1 - Pure Price Stock Builder

Follow the plan section `Task 1: Pure Price Stock Builder`.

Create:

- `frontend/src/lib/charts/hc/priceStock.ts`
- `frontend/src/lib/charts/hc/priceStock.test.ts`

Requirements:

- Convert stock/fund timeseries payloads into Highcharts Stock series inputs.
- Build candlestick/line/area/volume compare options.
- Support native Highcharts range/dataGrouping behavior.
- Include helpers for compare selection add/remove.
- Keep builder pure: no DOM, no React, no WebSocket.

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStock.test.ts
pnpm typecheck
```

Commit suggestion:

```powershell
git add frontend/src/lib/charts/hc/priceStock.ts frontend/src/lib/charts/hc/priceStock.test.ts
git commit -m "feat(charts): add Highcharts Stock price option builder"
```

### Task 2 - Live Tick Helpers

Follow the plan section `Task 2: Live Tick Merge Helpers`.

Create:

- `frontend/src/lib/charts/hc/priceStockLive.ts`
- `frontend/src/lib/charts/hc/priceStockLive.test.ts`

Additional current-repo requirement:

- Move or duplicate the `Tick` type currently imported by `frontend/src/lib/livefeed/client.ts` from `@/lib/ixchart/types` into a non-ixchart location.
- Preferred: export a small `LiveTick` type from `priceStockLive.ts` or create `frontend/src/lib/livefeed/types.ts`.
- Update `frontend/src/lib/livefeed/client.ts` so it no longer imports from `@/lib/ixchart/types`.

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStockLive.test.ts
pnpm typecheck
```

Commit suggestion:

```powershell
git add frontend/src/lib/charts/hc/priceStockLive.ts frontend/src/lib/charts/hc/priceStockLive.test.ts frontend/src/lib/livefeed/client.ts
git commit -m "feat(charts): add Highcharts Stock live tick helpers"
```

### Task 3 - Stock Wrapper Modules and CSS

Follow the plan section `Task 3: Stock Wrapper ESM Modules and CSS`.

Modify:

- `frontend/src/components/charts/HighchartsStockChart.tsx`
- `frontend/src/app/layout.tsx`

Requirements:

- Register/use the Highcharts Stock ESM build consistently.
- Load required modules for annotations/stock tools/indicators according to the installed Highcharts package shape.
- Import stock-tools/annotations CSS globally through the Next root layout if required by the package.
- Keep the wrapper thin and client-only.
- Preserve Graphite theme application via `highchartsTheme(chartColors())`.

Run:

```powershell
cd frontend
pnpm typecheck
pnpm lint
```

Commit suggestion:

```powershell
git add frontend/src/components/charts/HighchartsStockChart.tsx frontend/src/app/layout.tsx
git commit -m "feat(charts): register Highcharts Stock ESM modules"
```

### Task 4 - Rewrite InteractiveChart

Follow the plan section `Task 4: Rewrite InteractiveChart on Highcharts Stock`.

Modify:

- `frontend/src/components/charts/InteractiveChart.tsx`

Must remove imports from:

```ts
@/lib/ixchart/engine
@/lib/ixchart/tokens
@/lib/ixchart/series
@/lib/ixchart/types
```

Requirements:

- Render `HighchartsStockChart`.
- Use `priceStock.ts` for options.
- Use `priceStockLive.ts` for live tick merging.
- Use existing `fetchStockTimeseries` and `fetchFundTimeseries`.
- Preserve existing public props so `StockAnalysisView` and `FundProfileView` do not need broad rewrites.
- Keep range changes controlled by parent `range`/`onRangeChange`.
- Keep NAV mode supported for fund pages.
- Keep compare support for stocks and funds.
- Prefer native Highcharts Stock controls for data grouping, zoom, drawing/annotations, and indicators as agreed.

Run:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test src/lib/charts/hc/priceStock.test.ts src/lib/charts/hc/priceStockLive.test.ts
```

Commit suggestion:

```powershell
git add frontend/src/components/charts/InteractiveChart.tsx
git commit -m "feat(charts): migrate InteractiveChart to Highcharts Stock"
```

### Task 5 - Additive Compare Picker

Follow the plan section `Task 5: Multi-Compare Input Compatibility`.

Modify only if needed:

- `frontend/src/components/charts/SymbolSearchInput.tsx`
- `frontend/src/components/charts/InteractiveChart.tsx`

Current `SymbolSearchInput` requires `active` and `onClear`. Make them optional if the additive multi-compare UI needs chips to live in `InteractiveChart`.

Run:

```powershell
cd frontend
pnpm typecheck
pnpm lint
```

Commit suggestion:

```powershell
git add frontend/src/components/charts/SymbolSearchInput.tsx frontend/src/components/charts/InteractiveChart.tsx
git commit -m "feat(charts): support additive compare picker"
```

### Task 6 - Focused Gates

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStock.test.ts src/lib/charts/hc/priceStockLive.test.ts
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

If full `pnpm test` has unrelated failures, report exact failing tests and prove the P2 tests pass.

### Task 7 - Browser Verification

Start the app on a free port. Verify at least:

- `/stocks/<known ticker>`
- `/funds/<known fund id>`

Browser checks:

- chart renders nonblank
- light/dark theme works if control is available
- range changes update the chart
- stock page candlestick/line/area modes work if exposed
- fund page NAV mode works
- compare add/remove works for at least two symbols
- live tick path does not throw when `NEXT_PUBLIC_LIVEFEED_WS_URL` is unset
- no console/runtime errors from Highcharts module registration
- no obvious text overlap on desktop and mobile widths

If auth/data blocks local browser validation, create and delete the disposable demo route described in the plan. Do not leave demo files committed.

### Task 8 - Final No-Ixchart-Import Gate

P2 is complete only when:

```powershell
rg -n "@/lib/ixchart|from \\\".*ixchart|from '.*ixchart" frontend/src/components/charts/InteractiveChart.tsx frontend/src/lib/livefeed frontend/src/components/stocks frontend/src/components/funds
```

returns no live imports.

Also run:

```powershell
rg -n "@/lib/ixchart|from \\\".*ixchart|from '.*ixchart" frontend/src
```

Expected after P2:

- no live imports from app/runtime code
- `frontend/src/lib/ixchart/*` may still exist on disk for P8 cleanup

Do not remove `frontend/src/lib/ixchart/*` in P2 unless the owner explicitly expands scope.

## Validation Gates

Minimum final gates:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Recommended smoke:

```powershell
rg -n "ixchart|EChart|echarts" frontend/src/components/charts frontend/src/components/stocks frontend/src/components/funds frontend/src/lib/livefeed
```

Interpretation:

- `InteractiveChart` and livefeed must not import `ixchart`.
- `echarts` cleanup is P8, so old ECharts builders may still exist until P8.

## Stop Conditions

Stop and report instead of guessing if:

- the current worktree is dirty and no clean worktree/branch is available
- Highcharts package import paths differ from the P2 plan and cannot be resolved quickly
- stock-tools/annotations modules fail to register and browser runtime errors persist
- `InteractiveChart` public props would require broad stock/fund page rewrites
- live ticks require a type/protocol change beyond moving off `ixchart`
- the branch used for P2 does not include the completed P7 commits and the owner expects P2 to build on top of them

## Final Report Shape

Report in Portuguese:

1. Branch/worktree path and final HEAD SHA.
2. Commit stack for P2.
3. Whether `InteractiveChart` and livefeed are free of `ixchart` imports.
4. Exact gates run and results.
5. Browser evidence for stock and fund pages.
6. Any skipped gates or unrelated dirty files preserved.
7. Explicitly state that `frontend/src/lib/ixchart/*` still exists for P8 cleanup unless P8 was separately authorized.

Do not deploy, push, open PR, or start P8 unless the owner explicitly asks.
