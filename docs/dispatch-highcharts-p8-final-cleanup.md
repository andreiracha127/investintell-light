# Dispatch - Highcharts Migration P8 Final Cleanup

**Date:** 2026-06-15  
**Repo:** `E:\investintell-light`  
**Branch:** current checkout is expected to be `main`. Verify before work.  
**Purpose:** execute P8 from the Highcharts/fund dossier migration: remove the legacy ECharts and `ixchart` codepaths, clean stale references, and regenerate final API contracts if the current checkout needs it.

## Current Baseline

At dispatch creation time, current recent commits on `main` were:

- `28bab82 feat(charts): add Highcharts Stock price option builder`
- `ff2e937 feat(charts): add Highcharts Stock live tick helpers`
- `293e2ad feat(charts): register Highcharts Stock ESM modules`
- `fb76029 feat(charts): migrate InteractiveChart to Highcharts Stock`
- `104453e feat(charts): support additive compare picker`
- `fc07910 feat(funds): add Tier B dossier analytics endpoints`
- `02e9394 feat(funds): wire Tier B dossier tabs and deep analysis`
- `d862361 feat(funds): add cached dossier route handlers`
- `ea30bd9 feat(funds): hydrate dossier queries on first paint`
- `98992f6 fix(funds): widen funds grid layout`

The owner reported P7 as complete. At dispatch creation time, the inspected `main` log did not show an obvious P7 Tier C commit, so verify the actual target branch before starting if this cleanup is expected to land on top of P7.

P8 depends on P1/P2/P5 per the design spec. P2 is now implemented on `main`; do not re-run the price chart migration inside P8.

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
- `docs/dispatch-highcharts-p2-price-stock-execution.md`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

## Read First

Read these files before coding:

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/superpowers/plans/2026-06-14-highcharts-p0-foundation.md`
4. `docs/superpowers/plans/2026-06-14-highcharts-p1-builders.md`
5. `docs/superpowers/plans/2026-06-15-highcharts-p2-price-stock.md`
6. `frontend/package.json`
7. `frontend/src/components/charts/InteractiveChart.tsx`
8. `frontend/src/components/charts/HighchartsChart.tsx`
9. `frontend/src/components/charts/HighchartsStockChart.tsx`
10. `frontend/src/lib/charts/theme.ts`
11. `frontend/src/lib/charts/hc/`
12. `frontend/src/lib/livefeed/client.ts`

Use repo truth over this dispatch if the code has moved. Record any drift before changing files.

## Required Opening Verification

Run:

```powershell
rg -n "Limpeza final|P8|echarts|ixchart|price\\.ts" docs/superpowers/specs docs/superpowers/plans docs
rg -n "from \"@/lib/charts/(?!hc)|from '@/lib/charts/(?!hc)|@/lib/ixchart|echarts|EChart|buildPriceOption" frontend/src frontend/package.json frontend/package-lock.json pnpm-lock.yaml --pcre2
rg --files frontend/src/lib/charts frontend/src/lib/ixchart frontend/src/components/charts
pnpm --dir frontend why echarts
git log --oneline -n 30
```

Expected at dispatch creation time:

- `echarts` is still in `frontend/package.json`, `frontend/package-lock.json`, and `pnpm-lock.yaml`.
- `frontend/src/components/charts/EChart.tsx` still imports `echarts`.
- Legacy ECharts builders still exist under `frontend/src/lib/charts/*.ts`, including dead `price.ts`.
- `frontend/src/lib/ixchart/*` still exists.
- `frontend/src/lib/livefeed/client.ts` still imports `Tick` from `@/lib/ixchart/types`.
- Live Highcharts code still imports shared `chartColors` / `ChartColors` from `@/lib/charts/theme`.
- `AllocationSlice` is still reused from the legacy ECharts allocation builder by Highcharts code.

## P8 Scope

Implement only final cleanup:

- remove the ECharts runtime dependency
- remove the old ECharts wrapper `frontend/src/components/charts/EChart.tsx`
- remove old ECharts builders under `frontend/src/lib/charts/*.ts`
- remove dead `frontend/src/lib/charts/price.ts`
- remove `frontend/src/lib/ixchart/*`
- move shared chart tokens/types out of legacy ECharts files before deleting them
- update stale comments that incorrectly describe current Highcharts behavior
- regenerate final OpenAPI/frontend types only if the current branch has backend contract drift or generated files are stale
- run grep gates proving no live ECharts/ixchart imports remain

Do not implement P7, redesign charts, replace Highcharts behavior, change dossier analytics, deploy, push, or open a PR.

## Non-Scope

- No new chart features.
- No visual parity work beyond preserving current Highcharts behavior.
- No broad dependency upgrades.
- No backend schema changes unless contract regeneration reveals a current committed drift.
- No removal of Highcharts migration notes inside historical docs/plans.
- No staging unrelated untracked files.

## Implementation Tasks

### 1. Move shared chart tokens to a neutral module

`frontend/src/lib/charts/theme.ts` is not purely legacy: current Highcharts wrappers/builders import `chartColors` and `ChartColors` from it.

Create a neutral module before deleting the legacy folder entry, for example:

- `frontend/src/lib/charts/chartColors.ts`

Move the existing `ChartColors` type and `chartColors()` implementation there. Update imports in:

- `frontend/src/components/charts/HighchartsChart.tsx`
- `frontend/src/components/charts/HighchartsStockChart.tsx`
- `frontend/src/components/charts/InteractiveChart.tsx`
- all current `frontend/src/lib/charts/hc/**`
- current app components that call `chartColors()`

After this step, `rg -n "@/lib/charts/theme" frontend/src` should return nothing unless a historical comment remains in a deleted/renamed file.

### 2. Move shared chart input types out of legacy builders

Highcharts allocation code currently reuses `AllocationSlice` from `frontend/src/lib/charts/allocation.ts`. Move shared input types to a neutral module before deleting the ECharts builder, for example:

- `frontend/src/lib/charts/types.ts`

At minimum move:

- `AllocationSlice`

Then update:

- `frontend/src/lib/charts/hc/allocation.ts`
- `frontend/src/lib/charts/hc/allocation.test.ts`
- `frontend/src/components/portfolio/PortfolioOverviewView.tsx`

If other legacy builders expose types still consumed by live code, move those too. Do not leave live imports from legacy ECharts builders.

### 3. Move live tick types out of `ixchart`

`frontend/src/lib/livefeed/client.ts` still imports `Tick` from `@/lib/ixchart/types`.

Move `Tick` to a neutral livefeed/chart type module before deleting `ixchart`, for example:

- `frontend/src/lib/livefeed/types.ts`

Update all imports. If `Bar`, `Period`, `DrawTool`, or `ChartType` are still needed by the migrated Highcharts Stock code, move only the still-live types to neutral modules and leave engine-only types behind for deletion.

### 4. Delete legacy ECharts and ixchart code

After steps 1-3 are green, remove:

- `frontend/src/components/charts/EChart.tsx`
- legacy ECharts builders in `frontend/src/lib/charts/*.ts`
- `frontend/src/lib/ixchart/engine.ts`
- `frontend/src/lib/ixchart/series.ts`
- `frontend/src/lib/ixchart/series.test.ts`
- `frontend/src/lib/ixchart/tokens.ts`
- `frontend/src/lib/ixchart/types.ts`

Keep:

- `frontend/src/components/charts/HighchartsChart.tsx`
- `frontend/src/components/charts/HighchartsStockChart.tsx`
- `frontend/src/components/charts/InteractiveChart.tsx` current Highcharts version
- `frontend/src/components/charts/SymbolSearchInput.tsx`
- `frontend/src/lib/charts/hc/**`
- the new neutral chart token/type modules created above

### 5. Remove `echarts` from package manifests and lockfiles

Remove `echarts` from `frontend/package.json`.

This repo currently has both a root `pnpm-lock.yaml` and `frontend/package-lock.json`. Preserve both lockfiles unless the owner says otherwise.

Recommended approach:

```powershell
pnpm --dir frontend remove echarts
npm --prefix frontend install --package-lock-only
```

Inspect the resulting diffs before committing. If the package manager behavior is different in the current checkout, use the repo's actual convention and record it in the final report.

### 6. Clean stale live comments

Update comments in live source that still imply ECharts or ixchart own the current runtime. At dispatch creation time, inspect at least:

- `frontend/src/components/ui/DataGrid.tsx`
- `frontend/src/components/shell/AppShell.tsx`
- `frontend/src/components/portfolio/PortfolioRebalanceSection.tsx`
- `frontend/src/lib/api/client.ts`
- `frontend/src/lib/charts/hc/**`

Do not remove useful migration-history comments in docs. For code comments under `hc/**`, keep them if they explain parity with the old builder; remove or reword only misleading runtime statements.

### 7. Regenerate final contracts if needed

P8 has no intended backend contract change. Still, the design asks for final contract regeneration. Run the generation commands and inspect diffs:

```powershell
cd backend
uv run python scripts/export_openapi.py
cd ..\frontend
pnpm types
```

If `backend/openapi.json` and `frontend/src/lib/api/api.d.ts` change unexpectedly, inspect the diff before including it. Do not commit unrelated schema churn blindly.

## Required Grep Gates

After implementation, these commands must be clean or explained:

```powershell
rg -n "from \"echarts\"|from 'echarts'|import \\* as echarts|EChartsOption|<EChart|EChart\\(" frontend/src --pcre2
rg -n "@/lib/ixchart|from \"@/lib/charts/(allocation|contributions|cumulative|distribution|heatmap|histogram|lookthrough|nav|performance|price|rebalance|regime|rolling|scatter|stacked|theme)\"|from '@/lib/charts/(allocation|contributions|cumulative|distribution|heatmap|histogram|lookthrough|nav|performance|price|rebalance|regime|rolling|scatter|stacked|theme)'" frontend/src --pcre2
rg -n "\"echarts\"|echarts@" frontend/package.json frontend/package-lock.json pnpm-lock.yaml
```

Historical docs may still mention ECharts/ixchart. Do not treat docs mentions as a failure unless they are stale dispatch instructions for the current phase.

## Tests and Validation

Frontend gates:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Targeted tests worth running first while iterating:

```powershell
cd frontend
pnpm test src/lib/charts/hc
pnpm test src/lib/livefeed
```

Backend gates are not required unless contract regeneration or backend files change. If backend contract files change, run the nearest backend tests plus any existing OpenAPI/export smoke test:

```powershell
cd backend
python -m pytest tests/test_health.py -q
```

Browser validation:

- Start frontend on a free port.
- Open one stock analysis page and verify the Highcharts Stock price chart renders and range/compare controls still work.
- Open one fund dossier page and verify dossier charts render without blank panels.
- Open portfolio/statistics/macro/screener pages that use Highcharts Core builders.
- Check light/dark theme once if theme controls are available; `chartColors()` must still pick up `AppShell` remount/theme changes.
- Confirm no console errors mention missing `echarts`, missing `ixchart`, or missing chart token modules.

## Commit Discipline

Prefer a focused split if the diff is large:

```powershell
git commit -m "refactor(charts): move shared chart types out of legacy builders"
git commit -m "chore(charts): remove legacy echarts and ixchart code"
```

A single commit is acceptable if the diff is compact:

```powershell
git commit -m "chore(charts): remove legacy echarts and ixchart cleanup"
```

Before every commit:

```powershell
git status --short
git diff --stat
git diff --cached --name-only
```

Do not stage unrelated untracked files listed in this dispatch.

## Stop Conditions

Stop and report instead of guessing if:

- The target branch does not contain the P2 Highcharts Stock migration.
- The owner expects P8 to be based on a P7 branch that is not current checkout.
- Any live import from `@/lib/ixchart` remains after moving types.
- Any live import from deleted legacy `@/lib/charts/*` remains.
- Removing `echarts` changes package manager files outside the expected package/lock manifests.
- Contract regeneration changes unrelated API schemas and the cause is unclear.
- Full frontend build fails for an unrelated reason that cannot be separated from the cleanup.

## Final Report Shape

Report in Portuguese:

1. Branch and final HEAD SHA(s).
2. Files/modules removed.
3. Where shared `chartColors`, `ChartColors`, `AllocationSlice`, and `Tick` live now.
4. Exact grep gates and results.
5. Exact validation gates run and results.
6. Browser evidence for stock, fund dossier, and at least one Highcharts Core page.
7. Any skipped gates, contract diffs, or unrelated dirty files.

Do not deploy, push, or open PR unless the owner explicitly asks.
