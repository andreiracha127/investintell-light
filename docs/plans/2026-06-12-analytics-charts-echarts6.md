# Plan: Analytics charts — design system, sanitized copy, ECharts v6, English

Branch: `feature/analytics-charts-echarts6` (repo investintell-light).
Validated prototypes: `E:\investintell-datalake-workers\design\*.html` (visual reference only —
copy there is Portuguese; the app is **English**).

## Context

- Frontend: React 19 + Next.js 15.5 (App Router) + Tailwind 4 + ECharts (full bundle) + React Query.
- Chart pattern: pure option builders in `frontend/src/lib/charts/*.ts` taking data + `ChartColors`
  (from `lib/charts/theme.ts`, reads CSS tokens at runtime) → `EChartsOption`; rendered by
  `components/charts/EChart.tsx` (init/setOption/resize/dispose).
- API: typed fetch wrapper `lib/api/client.ts` over generated `lib/api/api.d.ts`. The new backend
  endpoints are ALREADY in `api.d.ts`: `/funds/{instrument_id}/lookthrough`,
  `/portfolios/{portfolio_id}/lookthrough`, `/macro/regime`,
  `/portfolios/{portfolio_id}/rebalance/policy`, `/portfolios/{portfolio_id}/rebalance/preview`.
- UI language: English, `Intl.NumberFormat("en-US")` via `lib/format.ts`.
- Quality gates (no frontend test runner in this repo — deliberate): `npm run typecheck`,
  `npm run lint`, `npm run build` (run from `frontend/`; repo uses pnpm workspace at root —
  `pnpm -C frontend ...` also works).
- Design system rules: light ground, single oxblood accent (highlight only), flat square forms,
  hairlines, tabular numerals, graphite categorical ramp (`colors.categories`, skip cat-1/accent
  for multi-series), gain/loss only for P&L semantics.

## Data-shape constraints (honest scope)

- Lookthrough = one snapshot (`report_date`) with `dimensions: {dim: ExposureItem[]}` where
  ExposureItem = {key, label, direct_pct, indirect_pct, total_pct}, plus `summary`
  (sum_pct_total, nondecomposable_fund_pct, derivatives_net_pct, unidentified_pct, coverage_pct,
  oldest_report_date, …). No time series → no stacked-area-over-quarters chart. Dimension switch
  is client-side (all dimensions arrive in one response) → instant re-render.
- MacroRegimeResponse = {detector, state, as_of, days_in_state, last_flip, signal{ratio, p20_5y,
  distance_pct, hyg_close, ief_close, n_window}, recent_flips[{date, state}]}. No ratio history →
  no ratio-vs-trigger line chart; build badge + KPI strip + flip timeline strip.
- RebalancePreviewResponse = {decision: no_action|drift_alert|proposal, calendar_due,
  macro_triggered, policy, drifts: PositionDriftOut[], proposal, invested_value, cash}. No weight
  history → drift is rendered per-position (current vs target with tolerance band), not over time.
- FundProfileResponse.nav = ~260 daily points (2 years) → monthly returns heatmap (2y) and
  drawdown (2y, worst window highlighted) computed client-side.

## Tasks

### Task 1 — Upgrade ECharts 5 → 6
- `frontend/package.json`: `"echarts": "^6"`; install via pnpm (workspace root lockfile).
- Fix any type/import breakage in `lib/charts/*.ts` and `components/charts/EChart.tsx`.
- Do NOT preemptively add v5-compat options; only fix what typecheck/build flags.
- Gates: typecheck, lint, build all green. Commit: `chore(frontend): upgrade echarts to v6`.

### Task 2 — Typed API surface for the new endpoints
- In `lib/api/client.ts`, following the existing operation-type + fetch-fn pattern, add:
  `getFundLookthrough(instrumentId, {dimension?})`, `getPortfolioLookthrough(portfolioId, …)`,
  `getMacroRegime()`, `getRebalancePolicy(portfolioId)`, `getRebalancePreview(portfolioId)`.
- Export response/element types (FundLookthrough, ExposureItem, LookthroughSummary, MacroRegime,
  RegimeFlip, RebalancePreview, PositionDrift, …) derived from `api.d.ts` (no hand-written shapes).
- Match existing error handling (ApiError, fail loud, no fallbacks).
- Gates green. Commit: `feat(frontend): typed client for lookthrough, macro regime, rebalance`.

### Task 3 — Look-through builders + fund profile section
- New `lib/charts/lookthrough.ts` (pure builders, JSDoc in the style of stacked.ts):
  - `buildExposureBarsOption(items, colors, {topN?})`: horizontal bars, two stacked segments per
    item — direct (colors.bar) + via funds (colors.barMute) — sorted by total desc, value labels
    `x.x%`. English legend: "Direct" / "Via funds".
  - `buildResidualWaterfallOption(summary, colors)`: waterfall to 100% — "Identified",
    "Funds without disclosure", "Derivatives (net)", "Unidentified" (loss color), total outline.
    Standard ECharts waterfall (transparent helper stack).
- `components/funds/` — new client component `FundLookthroughSection.tsx`:
  - React Query on `getFundLookthrough`; renders ONLY when the fund has lookthrough data (404 /
    empty → render nothing or a quiet empty note, follow how FundProfileView treats absent data).
  - Header "Consolidated exposure" + sub "Through underlying funds · as of {report_date}".
  - KPI row (existing KpiTile/StatRow patterns): Coverage, Decomposed total, Oldest report,
    Funds expanded.
  - Dimension switcher (segmented control, square-cut, follow existing UI patterns) —
    client-side switch across `dimensions` keys (e.g. asset_class, sector, currency, issuer);
    label keys in English ("Asset class", "Sector", "Currency", "Issuer").
  - Exposure bars chart + residual waterfall side by side (grid like existing sections).
- Wire into `FundProfileView.tsx` where sections live.
- Copy: sanitized English product copy only — no worker/table/internal names anywhere.
- Gates green. Commit: `feat(frontend): consolidated look-through section on fund profile`.

### Task 4 — Portfolio look-through + macro regime page
- Portfolio: reuse the same builders/section pattern for `getPortfolioLookthrough` inside the
  portfolio page (`app/portfolio/` views — find where overview sections render and add
  "Consolidated exposure" there). Extract shared pieces if trivially reusable
  (e.g. `components/lookthrough/LookthroughPanel.tsx` shared by fund + portfolio) — avoid copy-paste.
- New route `app/macro/page.tsx` ("Credit regime"):
  - Badge RISK-ON/RISK-OFF (status colors + wash, square pill), "since {last_flip} · {days} days".
  - KPI strip from signal: HYG/IEF ratio, Trigger (20th percentile), Distance to trigger,
    Window size, As of.
  - `lib/charts/regime.ts` → `buildRegimeStripOption(flips, colors, {from, to})`: timeline strip,
    pos-wash background, loss-colored risk-off bands derived from `recent_flips` transitions.
  - Explainer copy (English, product tone): "Binary credit-stress signal: risk-off when the
    HYG/IEF ratio crosses below the 20th percentile of the trailing five years."
- Add "Macro" to the AppShell nav (follow existing nav item pattern).
- Gates green. Commit: `feat(frontend): portfolio look-through + macro regime page`.

### Task 5 — Rebalance section on portfolio
- `lib/charts/rebalance.ts` → `buildDriftBandsOption(drifts, colors)`: one row per position —
  current weight vs target with tolerance band (accent wash markArea + accent target line,
  loss-colored marker when outside band). Per-position, not time series.
- Portfolio section "Rebalancing" (only when a policy exists; policy GET 404 → hide section):
  - Status KPI row: Decision ("Proposal" / "Drift alert" / "No action"), Reason (calendar/band/
    macro from calendar_due, drifts, macro_triggered), Turnover, Last evaluated.
  - Drift chart + proposal table (Asset | Current | Target | Δ | Action e.g. "Sell $23,842" —
    en-US currency) + triggers list (Calendar / Tolerance band / Credit regime) with status pills.
  - Note: "Proposals are never executed automatically."
- Gates green. Commit: `feat(frontend): rebalance drift and proposal section on portfolio`.

### Task 6 — Fund performance panels (monthly heatmap + drawdown)
- `lib/perf.ts` (pure, documented): `monthlyReturns(nav: FundNavPoint[])` →
  {year, month, value}[] (null-safe, partial months at series edges excluded);
  `drawdownSeries(nav)` → {dates, values(≤0), worst:{from,to,depth}}.
- Builders (check `lib/charts/heatmap.ts` first — REUSE it if it is generic enough, extending
  only if needed; otherwise add to a new `lib/charts/performance.ts`):
  - Monthly returns heatmap: month × year grid, gain/loss fill with magnitude opacity, yearly
    total column.
  - Drawdown line: loss-colored line+area, worst window shaded with its depth label.
- Two panels in FundProfileView ("Monthly returns", "Drawdown") using the already-fetched
  profile `nav` (no new fetch). Skip rendering when nav is too short (<13 months).
- Gates green. Commit: `feat(frontend): monthly returns heatmap and drawdown on fund profile`.

### Task 7 — Final review & polish
- Full pass: typecheck, lint, build; visual smoke via dev server on a fund with lookthrough,
  the portfolio page and /macro; ECharts v6 rendering sanity for the pre-existing builders.
- Final whole-implementation code review.

## Decisions log
- No frontend test runner exists in this repo (gates = typecheck/lint/build); we follow that
  convention instead of introducing one mid-feature.
- ECharts v6 (not v5): per owner request; upgrade isolated in Task 1.
- All new copy in English, sanitized product language (no internal worker/lock/table names).
- Charts that need history (exposure over time, ratio history, weight history) are out of scope
  until the backend exposes those series.
