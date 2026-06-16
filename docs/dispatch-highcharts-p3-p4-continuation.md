# Dispatch — Highcharts Migration P3/P4 Continuation

**Date:** 2026-06-15  
**Repo:** `E:\investintell-light`  
**Branch:** current checkout is `main` unless `git status --branch` says otherwise.  
**Purpose:** continue the Highcharts migration plan from a fresh session, closing P3 first and then starting P4 only after P3 gates are green.

## Read First

1. `AGENTS.md`
2. `docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md`
3. `docs/superpowers/plans/2026-06-14-highcharts-p0-foundation.md`
4. `docs/superpowers/plans/2026-06-14-highcharts-p1-builders.md`
5. `docs/superpowers/plans/2026-06-15-highcharts-p2-price-stock.md`

Use repo truth over stale plan prose. Before editing, run:

```powershell
git status --short --branch
rg -n "P3|P4|/timeseries|NAV_WINDOW_DAYS|Backend Tier A|dossier" docs/superpowers/specs/2026-06-14-highcharts-charts-migration-design.md
rg -n "fetchStockHistory|fetchFundHistory|fetchStockTimeseries|fetchFundTimeseries|/timeseries|/history" frontend/src backend/app backend/openapi.json
```

Preserve unrelated dirty work. At the time this dispatch was written, these untracked files existed and should not be removed or normalized unless the owner explicitly authorizes it:

- `.idea/AugmentWebviewStateStore.xml`
- `backend/_gate_vs_full_backtest.py`
- `backend/_navdata.csv`
- `backend/_navdata.err`
- `docs/superpowers/plans/2026-06-13-highcharts-grid-plan4-universe-checkbox.md`

## Current Verified Status

P3 is partial:

- Backend `/stocks/{ticker}/timeseries` exists and uses range-aware daily/weekly/monthly CAGG.
- Backend `/funds/{instrument_id}/timeseries` exists and uses range-aware daily/weekly/monthly CAGG.
- `backend/openapi.json` and `frontend/src/lib/api/api.d.ts` include the timeseries paths.
- The optimizer 730-day default gate has already been removed in `backend/app/optimizer/data.py` (`DEFAULT_WINDOW_DAYS = None`) and the builder contract accepts `window_days: int | None = None`.

P3 is not complete:

- `frontend/src/lib/api/client.ts` still exposes `fetchStockHistory` and `fetchFundHistory`, but no `fetchStockTimeseries` or `fetchFundTimeseries`.
- `frontend/src/components/stocks/StockAnalysisView.tsx` still fetches chart bars via `fetchStockHistory(ticker, 2520, signal)`.
- `frontend/src/components/funds/FundProfileView.tsx` still fetches chart bars via `fetchFundHistory(instrumentId, 2520, signal)`.
- `frontend/src/components/charts/InteractiveChart.tsx` still fetches compare data via `/history`.
- `backend/app/services/funds_catalog.py` still has `NAV_WINDOW_DAYS = 365 * 2` and `NAV_TARGET_POINTS = 260` for profile NAV.

P4 is not implemented:

- No backend routes for `/funds/{id}/analysis`, `/funds/{id}/holdings/top`, `/funds/{id}/peers`, or `/funds/scatter`.
- No client fetchers for those endpoints.
- `frontend/src/app/funds/[id]/page.tsx` still renders `FundProfileView` directly, not a dossier shell with tabs.

Do not treat P6 caching as unblocked until P4 is actually implemented.

## Scope

Primary goal: close P3.

Secondary goal, only after P3 is committed and green: start P4 with a narrow Backend Tier A slice. Do not implement P5, P6, P7, or P8 in this dispatch.

## P3 Implementation Tasks

### 1. Add frontend timeseries fetchers

In `frontend/src/lib/api/client.ts`:

- Add operation types for:
  - `paths["/stocks/{ticker}/timeseries"]["get"]`
  - `paths["/funds/{instrument_id}/timeseries"]["get"]`
- Add exported response/data types for the Highcharts stock/fund timeseries payloads.
- Add `fetchStockTimeseries(ticker, range, signal?)`.
- Add `fetchFundTimeseries(instrumentId, range, signal?)`.
- Preserve existing `fetchStockHistory` and `fetchFundHistory` for compatibility until P8 removes old contracts.

### 2. Wire chart consumers to `/timeseries?range=`

Update:

- `frontend/src/components/stocks/StockAnalysisView.tsx`
- `frontend/src/components/funds/FundProfileView.tsx`
- `frontend/src/components/charts/InteractiveChart.tsx`

Expected behavior:

- Query keys include `range`.
- Range button changes refetch from `/timeseries?range=<preset>`, not client-only zoom over fixed `2520` bars.
- Compare series in `InteractiveChart` also use the matching `/timeseries?range=` endpoint for stock vs fund.
- Keep public component props stable where practical.
- Do not reintroduce the canvas `ixchart` engine if P2 already migrated it away in the live checkout; inspect first.

If current P2 code is still not fully landed, do the smallest compatibility adapter: convert the timeseries response into the shape the current chart component expects, and document the bridge in a short comment.

### 3. Resolve profile NAV depth

Inspect real consumers of `fund.nav` from `GET /funds/{id}`. Then choose the least risky route:

- Preferred: parameterize `NAV_WINDOW_DAYS` / `NAV_TARGET_POINTS` in `backend/app/services/funds_catalog.py` and expose a route/query path that keeps profile payloads bounded while allowing long-history consumers to use `/timeseries`.
- Acceptable for P3 if the UI no longer relies on profile NAV for charts: leave profile NAV bounded, but add a code comment and test proving charts use `/funds/{id}/timeseries?range=MAX` for full depth.

Do not remove the catalog eligibility filter in `funds_v`; the design explicitly says that `current_date - 730` there is not the chart depth gate.

### 4. Regenerate API contracts if needed

If route signatures or schemas change, regenerate:

- `backend/openapi.json`
- `frontend/src/lib/api/api.d.ts`

Use the repo's existing generation command. If no command is obvious, find it with:

```powershell
rg -n "openapi|api.d.ts|openapi-typescript|generate" package.json backend frontend scripts docs
```

## P3 Gates

Run at minimum:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Run backend tests that cover timeseries/catalog behavior:

```powershell
cd backend
python -m pytest tests -q
```

If the full backend suite is too slow or has known unrelated failures, run targeted tests first and report the exact skipped wider gate. Do not claim full green unless it was run.

Browser verification:

- Start the frontend dev server on a free port.
- Open at least one stock page and one fund page with real IDs already known in the repo/tests.
- Toggle `1M`, `6M`, `1Y`, `5Y`, `MAX`.
- Confirm requests hit `/timeseries?range=` and charts update without blank canvas/SVG.
- Check light and dark theme once if a theme switch is available.

Commit P3 as a single focused commit, for example:

```powershell
git add frontend/src/lib/api/client.ts frontend/src/components/stocks/StockAnalysisView.tsx frontend/src/components/funds/FundProfileView.tsx frontend/src/components/charts/InteractiveChart.tsx backend/app/services/funds_catalog.py backend/openapi.json frontend/src/lib/api/api.d.ts
git commit -m "feat(charts): consume range-aware timeseries endpoints"
```

Adjust the file list to the actual diff. Do not include unrelated untracked files.

## P4 Start Criteria

Only proceed to P4 after:

- P3 commit exists.
- P3 gates are run and results are recorded.
- `git diff --stat HEAD` is clean except intentional follow-up files.

## P4 Narrow Slice

Implement Backend Tier A first. Keep the UI shell minimal until backend contracts are real.

Required endpoints from the design:

- `GET /funds/{id}/analysis?range=&window=`
- `GET /funds/{id}/holdings/top`
- `GET /funds/{id}/peers?limit=`
- `GET /funds/scatter?limit=`

Implementation guidance:

- Mirror the existing stock analysis pattern in `backend/app/api/routes/stocks.py` and `backend/app/services/stock_analysis.py`.
- Reuse analytics helpers where available: `backend/app/analytics/_series.py`, `rolling.py`, `risk.py`, `distribution.py`.
- Use live fund sources already documented in the repo: `nav_timeseries`, `funds_v`, `fund_risk_latest_mv`, `fund_holdings_v` / look-through services.
- Add Pydantic v2 schemas under `backend/app/schemas/` instead of returning untyped dicts.
- Add tests for success, missing fund, insufficient data, and limit bounds.
- Regenerate OpenAPI/types after backend routes land.

For the frontend P4 shell:

- Create a dossier shell for `frontend/src/app/funds/[id]` only after backend routes exist.
- Keep it Graphite/Cockpit styled and dense, not a marketing page.
- Minimum shell: header + tabs for `Performance`, `Holdings`, `Style`, `Factors`, `Peers`; only wire tabs with real P4 data. For P5-only data, show empty/coming-soon states without fake values.
- Do not implement P5 endpoints or Deep Analysis modal in this dispatch.

P4 commit message suggestion:

```powershell
git commit -m "feat(funds): add Tier A dossier endpoints"
```

## Final Report Shape

Report in Portuguese:

1. Branch and final HEAD SHA.
2. Whether P3 is complete, with exact gates and browser evidence.
3. Whether P4 was started/completed, with endpoint list and tests.
4. Any skipped gates or known unrelated failures.
5. Deployment status only if explicitly requested in the fresh session.

Do not open a PR or deploy unless the owner explicitly asks.
