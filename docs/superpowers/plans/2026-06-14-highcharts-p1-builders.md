# Highcharts P1 — Port the 16 remaining ECharts builders → Highcharts Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. This is a **repetitive port** plan: each builder is ported by reading its existing ECharts source and producing the Highcharts equivalent following the validated `nav.ts` template + the per-builder mapping below. The "worked example" (`buildHcNavOption`) already exists and passed visual validation — replicate its shape.

**Goal:** Port the 16 remaining pure ECharts option builders in `src/lib/charts/*` to Highcharts Core builders in `src/lib/charts/hc/*` (each pure, Vitest-tested, Graphite-themed), and swap every `<EChart>` consumer to `<HighchartsChart>`, achieving visual + behavioral parity.

**Architecture:** Each HC builder is a pure function `(data, colors[, opts]) => Highcharts.Options` that sets only chart-specific content (series, series colors from `colors`, value formatting, special axes); the global Graphite theme (applied by the wrapper via `setOptions`) owns axis/grid/tooltip/legend/candlestick chrome. ECharts `visualMap` → Highcharts `colorAxis`; `markArea` → `plotBands`; regime stacked-timeline → `xrange`; `dataZoom` is NOT used here (that's the Stock price chart, P2). Builders that returned `EChartsOption | null` keep returning `Highcharts.Options | null`; consumers pass `isEmpty`/guard accordingly.

**Tech Stack:** Highcharts v13 (Core), TypeScript 5, Vitest 4 (node, `src/**/*.test.ts`), React 19 / Next 15.

**Working directory:** all commands from `E:/investintell-light-highcharts/frontend` (worktree, branch `feat/highcharts-charts-migration`). Commit there. Do NOT touch `E:/investintell-light` or `E:/investintell-light-grid`.

**Reference template (already merged, visually validated):** `src/lib/charts/hc/nav.ts` + `src/lib/charts/hc/theme.ts` + `src/lib/charts/hc/__fixtures__/colors.ts` (the `TEST_COLORS` fixture) + `src/lib/charts/hc/nav.test.ts`. Read these first. The matching ECharts sources live in `src/lib/charts/*.ts`; read each one before porting it.

**Per-builder rule:** the HC builder must reproduce the SOURCE builder's data mapping and special behavior (sorting, gates, label coloring, gain/loss coloring, fixed axis bounds). Tests mirror the source builder's tests where they exist (`src/lib/charts/*.test.ts`) and assert the data mapping + token colors + special cases (empty/null).

---

## File Structure

| New HC builder file | Ports source | Viz | Highcharts mapping / special handling |
|---|---|---|---|
| `hc/cumulative.ts` `buildHcCumulativeOption` | `cumulative.ts` | 2 lines (asset accent + benchmark muted) | `line` ×2; percent y (signed); colors `accent` / `barMute`; legend external (keep `legend.enabled:false`). |
| `hc/rolling.ts` `buildHcRollingOption` | `rolling.ts` | rolling line | `line`; opts `{ yPercent?, yMin?, yMax? }` → `yAxis` `labels` percent / `min`/`max`. |
| `hc/histogram.ts` `buildHcHistogramOption` | `histogram.ts` | bar histogram | `column`; x = bin midpoints (category, display only); uniform `colors.bar`. |
| `hc/distribution.ts` `buildHcDistributionOption` | `distribution.ts` | bar (screener) | `column`; per-point color: in-band → `accent`, else `bar`; y hidden, max 1; args `(distribution, band, dataType, colors)`. |
| `hc/contributions.ts` `buildHcRiskContributionsOption` | `contributions.ts` | horizontal bar | `bar` (inverted); sort asc (largest on top); percent data labels at bar end. |
| `hc/allocation.ts` `buildHcAllocationOption` | `allocation.ts` | donut | `pie` `innerSize:'65%'`; slice colors from `colors.categories`; data labels off (HTML legend beside). |
| `hc/scatter.ts` `buildHcScatterOption` | `scatter.ts` | scatter + regression line | `scatter` + `line` (`enableMouseTracking:false`); both axes percent; args `(scatter, regressionLine, labels, colors)`. |
| `hc/heatmap.ts` `buildHcHeatmapOption` | `heatmap.ts` | correlation heatmap | `heatmap` + `colorAxis` (continuous 0..1, `accentWash`→`accent`); per-cell label color flips above 0.55; y reversed. Needs `highcharts/modules/heatmap`. |
| `hc/performance.ts` `buildHcMonthlyReturnsOption` + `buildHcDrawdownOption` | `performance.ts` | heatmap (month×year, diverging) + line/area+band | monthly: `heatmap`+diverging `colorAxis` (`loss`→`grid`→`gain`), returns `null` when empty. drawdown: `area` (loss fill) + `xAxis.plotBands` for worst window, y `max:0`, returns `null` when empty/flat. |
| `hc/lookthrough.ts` `buildHcExposureBarsOption` | `lookthrough.ts` | stacked horizontal bar | `bar` `stacking:'normal'` (inverted); sort desc top-N (`opts.topN=10`); total% label at bar end; rich HTML tooltip; legend rect. |
| `hc/rebalance.ts` `buildHcDriftBandsOption` | `rebalance.ts` | horizontal bar + scatter + per-row band | `bar` + `scatter` (target ticks) + per-category `xAxis.plotBands` OR `yAxis` bands for tolerance; breach bars `loss`; rich HTML tooltip (deviation in pp); returns `null` when empty. Most complex — port carefully. |
| `hc/regime.ts` `buildHcRegimeStripOption` | `regime.ts` | regime timeline strip | `xrange` (one point per period; `x`/`x2` = start/end ms; color risk_on=`gain`@0.18 / risk_off=`loss`); x hidden; per-point tooltip; dedup legend; returns `null` when empty. Needs `highcharts/modules/xrange`. |
| `hc/stacked.ts` `buildHcStackedAreaOption` + `buildHcStackedPercentOption` + `buildHcMultiLineOption` | `stacked.ts` | stacked area+total / 100% area / multi-line | area `stacking:'normal'` + total `line` (accent, z-top); percent `stacking:'percent'` (y 0..1); multiline `line` (TOTAL series accent width 2.5 z:10). |

**Consumer swap sites** (replace `import { EChart }`/`buildXOption` with `HighchartsChart`/`buildHcXOption`, `<EChart option={o}/>` → `<HighchartsChart options={o}/>`, and for null-returning builders pass `isEmpty`/keep the existing null-guard):
`portfolio/StaticPortfolioView.tsx` (6), `portfolio/PortfolioOverviewView.tsx` (donut), `portfolio/PortfolioRebalanceSection.tsx` (drift), `stocks/StockAnalysisView.tsx` (cumulative/rolling×3/histogram — NOT the price chart, that's P2), `funds/FundProfileView.tsx` (monthly heatmap + drawdown — NOT the InteractiveChart, P2), `statistics/StockCorrelationView.tsx`, `statistics/BetaView.tsx`, `statistics/CorrelationView.tsx`, `statistics/ScenarioView.tsx` (4), `builder/ResultsPanel.tsx` (DonutChart ×2), `macro/MacroRegimeView.tsx`, `lookthrough/LookthroughPanel.tsx`, `screener/BuildTab.tsx`.

---

## Execution batches (each batch = one implementer dispatch → spec review → quality review)

### Task 1 (Batch A — simple line/bar/pie): cumulative, rolling, histogram, distribution, contributions, allocation
- [ ] **Step 1: Read** `hc/nav.ts`, `hc/theme.ts`, `hc/__fixtures__/colors.ts`, and the 6 ECharts sources (`cumulative.ts`, `rolling.ts`, `histogram.ts`, `distribution.ts`, `contributions.ts`, `allocation.ts`) + any `*.test.ts` siblings.
- [ ] **Step 2: For each builder, write the failing test** in `hc/<name>.test.ts` asserting: correct series `type`, data mapping from the source's inputs, token colors (e.g. `accent`/`bar`/`categories`), and special cases (sort order, in-band coloring for distribution, percent axis for rolling, empty input). Use `TEST_COLORS`. Run `npx vitest run src/lib/charts/hc/<name>.test.ts` → FAIL.
- [ ] **Step 3: Implement** `hc/<name>.ts` per the mapping table, mirroring the source's behavior, letting the global theme own chrome. Run the test → PASS.
- [ ] **Step 4:** `pnpm typecheck` → 0 errors.
- [ ] **Step 5: Commit** `feat(charts): port <names> builders to Highcharts Core` (one commit for the batch, or per builder).

### Task 2 (Batch B — scatter + colorAxis heatmaps): scatter, heatmap, performance (monthly + drawdown)
- [ ] Install heatmap module if needed: confirm `highcharts/modules/heatmap` import works (`node -e "require('highcharts/modules/heatmap')"`); the heatmap builder's consumer/wrapper must register it (add `highcharts/modules/heatmap` registration in `HighchartsChart` OR a one-time module loader — **decision: register heatmap + xrange modules inside `HighchartsChart`'s dynamic import** so any Core chart can use them; do this in Task 2 Step 1 and note it for the regime task).
- [ ] TDD each: scatter (`scatter`+silent `line`), heatmap (`heatmap`+`colorAxis` continuous, cell label flip >0.55, y reversed), monthlyReturns (`heatmap`+diverging `colorAxis`, `null` empty), drawdown (`area`+`plotBands` worst window, y max 0, `null` empty). Tests assert colorAxis stops, plotBands presence, null cases.
- [ ] typecheck; commit.

### Task 3 (Batch C — stacked + lookthrough): stacked (area/percent/multiline), lookthrough exposure bars
- [ ] TDD each per mapping (stacking modes, total line accent, top-N sort, stacked horizontal bar). typecheck; commit.

### Task 4 (Batch D — complex: regime + drift bands)
- [ ] Register `highcharts/modules/xrange` (in `HighchartsChart`, per Task 2 decision). TDD regime (`xrange`, period colors, dedup legend, `null` empty) and driftBands (`bar`+`scatter`+per-row band, breach `loss`, pp tooltip, `null` empty). These are the hardest — port carefully against source. typecheck; commit.

### Task 5 (Consumer swaps — by view, grouped)
- [ ] Swap each consumer file listed above from `EChart`→`HighchartsChart`, `buildX`→`buildHcX`. For null-returning builders, keep the existing null-guard (render the existing placeholder/`Card` when the option is `null`) or pass `isEmpty`. Do NOT touch the price `InteractiveChart` (P2). After each view: `pnpm typecheck && pnpm lint`. Run `pnpm test` (all builder tests pass). Commit per view or per small group.
- [ ] After all swaps: full gate `pnpm lint && pnpm typecheck && pnpm test` (expect all green; 70 + new builder tests).

### Task 6 (Visual parity check)
- [ ] Start `pnpm dev`; with Playwright (or hand to user), navigate real pages that now render Highcharts: `/portfolio` (StaticPortfolioView — donut/nav/cumulative/heatmap/contributions/histogram), `/stocks/<ticker>` (cumulative/rolling/histogram), `/funds/<id>` (monthly heatmap + drawdown), `/statistics`, `/macro` (regime strip), screener BuildTab distribution. Screenshot light + dark; confirm parity with the prior ECharts versions (no default titles, Graphite colors, gain/loss, colorAxis gradients, plotBands). Fix any visual regressions. (Auth/data: these pages need the backend + auth; if data isn't available in dev, validate the builders via a throwaway demo page like the P0 validation instead, then delete it.)

---

## Self-Review (run after writing the builders, before consumer swaps)

1. **Coverage:** all 16 builders from the spec migration map have an `hc/` file + test? (cumulative, rolling, histogram, distribution, contributions, allocation, scatter, heatmap, monthlyReturns, drawdown, exposureBars, driftBands, regimeStrip, stackedArea, stackedPercent, multiLine = 16.) ✓ when all present.
2. **Module registration:** heatmap + xrange modules registered once in `HighchartsChart` (not per-builder)? colorAxis available?
3. **Null parity:** every source builder that returned `| null` (drawdown, monthlyReturns, driftBands, regimeStrip) returns `| null` in HC, and its consumer guards it.
4. **Naming:** `buildHc<Name>Option` consistent with `buildHcNavOption`; consumers import the right name.
5. **No theme duplication:** builders do NOT re-set global chrome (axis grid colors, tooltip bg) — only chart-specific bits + series colors from `colors`.

---

## Notes
- This phase touches ONLY `src/lib/charts/hc/*` (new), `src/components/charts/HighchartsChart.tsx` (module registration), and the consumer view files. It does NOT remove `echarts`/`src/lib/charts/*` (P8) — old and new coexist until P8.
- The price chart (`InteractiveChart`/`ixchart`) is OUT of P1 — it's P2 (Highcharts Stock).
- If a builder reveals a missing token need, extend `ChartColors`/`chartColors()` + the `TEST_COLORS` fixture in the same task (note it in the report).
