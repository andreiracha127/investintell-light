# Builder result tabs — frontend (onda 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the Builder's static `ResultsPanel` into a four-tab workspace (Allocation · Risk · Backtest · Projection) that lazily wires the already-implemented `/portfolio/analysis`, `/backtest/walk-forward`, and the new `/monte-carlo/portfolio` quant endpoints, each tab fetching once on first open and resetting when a new optimization result arrives.

**Architecture:** Mirror the existing tab pattern in `FundProfileView.tsx` (a `ResultTabId` union, a `TABS` array, `useState`, `role="tab"`/`aria-selected` buttons reusing the same classes, conditional render). `ResultsPanel` becomes a thin tab wrapper; its current body moves verbatim into `AllocationTab`. Each data tab is an isolated component that fires one `useMutation` (the `postBuilderOptimize` idiom) on first mount, renders KPI tiles + Highcharts via existing/new pure builders, and surfaces 422s verbatim. Two new pure chart builders (`foldMetrics.ts`, `cone.ts`) follow the style of `histogram.ts`/`nav.ts`.

**Tech Stack:** Next.js 15 (React 19, client components), TanStack Query v5 (`useMutation`), Highcharts 13 Core via the `HighchartsChart` wrapper + pure builders under `src/lib/charts/hc/`, Tailwind v4 (Cockpit/Carbon tokens), Vitest 4 + Testing Library (jsdom per-file), `openapi-typescript` for the generated `api.d.ts`.

---

## Background facts collected from the codebase (read before starting)

These are verbatim from the current tree; do not re-derive them.

**Tab pattern template — `frontend/src/components/funds/FundProfileView.tsx`:**
- `type TabId = "performance" | "holdings" | "style" | "factors" | "peers";` (line 80) and `const TABS: { id: TabId; label: string }[] = [...]` (lines 82-88).
- `const [activeTab, setActiveTab] = useState<TabId>("performance");` (line 141).
- Reset-on-id-change effect (lines 149-157): `useEffect(() => { setActiveTab("performance"); ... }, [instrumentId]);`.
- The tab strip JSX (lines 523-542) — copy the wrapper and button classes verbatim:
  ```tsx
  <div className="mb-4 border-b border-border-strong">
    <div className="flex flex-wrap gap-1" role="tablist" aria-label="...">
      {TABS.map((tab) => (
        <button
          key={tab.id}
          type="button"
          role="tab"
          aria-selected={activeTab === tab.id}
          onClick={() => setActiveTab(tab.id)}
          className={`h-[34px] border border-b-0 px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors ${
            activeTab === tab.id
              ? "border-border-strong bg-surface-2 text-text-primary"
              : "border-transparent bg-transparent text-text-muted hover:bg-layer-hover hover:text-text-primary"
          }`}
        >
          {tab.label}
        </button>
      ))}
    </div>
  </div>
  ```
- Lazy fetch idiom: `useQuery({ ..., enabled: isHoldingsTab })`. We use `useMutation` (per spec) instead, fired from a per-tab mount effect.

**`ResultsPanel` (current) — `frontend/src/components/builder/ResultsPanel.tsx`:**
- Props (lines 99-113): `{ result: OptimizeResponse; objective: BuilderObjective; assetsByKey: Map<string, UniverseAsset>; base: BaseAllocation | null; colors: ChartColors | null; grouped: boolean }`. Exports `interface BaseAllocation`.
- Body = KPI tiles (lines 311-332), Save-as-portfolio block + weights table/`DataGrid` (lines 334-633), donuts (635-645), `MuDiagnostics` (647-654), `SelectionDiagnostics` (656-659). Helpers `csvField`, `Th`, `Donut`, `MuDiagnostics` live at the bottom (lines 664-755).
- Imports it needs that move with the body: `useMutation, useQueries` from `@tanstack/react-query`, `Link`, `useMemo, useState`, the client imports, `parseDecimal`, `buildHcAllocationOption`, `ChartColors`, `formatNumber, formatPercent`, `HighchartsChart`, `Card, KpiTile, valueTone`, the `screener/shared` button/label/input classes + `ErrorPanel`, `assetKey/assetName/assetTicker/UniverseAsset`, `SelectionDiagnostics`, `DataGrid`, `buildWeightsTree/WeightInput`, `weightsTreeGridOptions`.

**`BuilderView.tsx` renders `ResultsPanel` (lines 410-419):**
```tsx
<ResultsPanel
  key={mutation.submittedAt}
  result={mutation.data}
  objective={objective}
  assetsByKey={assetsByKey}
  base={mode === "simulate" ? base : null}
  colors={colors}
  grouped={mode === "universe"}
/>
```
`objective` and `constraints` used by the run are local to `BuilderView.onRun` (lines 199-233): `constraints = { cap: cap!==null?cap/100:null, min_weight: minWeight!==null?minWeight/100:null }`, `window_days: windowVal`. **`ResultsPanel` does NOT currently receive `constraints` or `windowDays`.** BacktestTab needs them → Task 2 adds two props (`constraints`, `windowDays`) to `ResultsPanel` and threads them from `BuilderView`. `ResultsPanel` is remounted on each new result by `key={mutation.submittedAt}`, so per-tab mutation state is naturally reset; we additionally reset on `result` identity inside `ResultsPanel` for safety (see Task 2).

**Chart builder signatures (verbatim):**
- `buildHcAllocationOption(slices: AllocationSlice[], colors): Options` — `allocation.ts`.
- `buildHcNavOption(nav: SeriesPoint[], colors): Options` — `nav.ts`. **Single line series, no plotLines.** OOS curve reuses this; fold-boundary `plotLines` are merged onto the returned `xAxis` in `BacktestTab` (see Task 5).
- `buildHcRiskContributionsOption(contributions: RiskContribution[], colors): Options` — `contributions.ts`. Input `{ ticker, contribution }[]`.
- `buildHcHeatmapOption(correlation: CorrelationMatrix, colors): Options` — `heatmap.ts`. Input `{ tickers, matrix }`.
- `buildHcCumulativeOption(cumulative: CumulativeReturns, assetLabel: string, benchmarkLabel: string, colors): Options` — `cumulative.ts`. **Input type is `CumulativeReturns = { asset: SeriesPoint[]; benchmark: SeriesPoint[] }`** (from `StockAnalysis["cumulative_returns"]`). The `/portfolio/analysis` response gives `benchmark_comparison: { portfolio, benchmark }`. RiskTab maps `{ asset: benchmark_comparison.portfolio, benchmark: benchmark_comparison.benchmark }` and passes labels `"Portfolio"` / `"SPY"`.
- Date helpers in `dateAxis.ts`: `compactDatetimeXAxis(overrides?)`, `toDatetimeData(points)`, `formatTimestampDate(value)`, `dateToUtcMs(date)`.
- `HighchartsChart` props: `{ options: Options; className?: string; emptyMessage?: string; isEmpty?: boolean; onReady? }`.

**API client (`frontend/src/lib/api/client.ts`):**
- `request<T>(path, signal?, init?, authMode?)` helper (lines 421-471); `init = { method, json }`.
- `postPortfolioAnalysis(body, signal?)` **already exists** (lines 519-527). `PortfolioAnalysisRequest`, `PortfolioAnalysis`, `CorrelationMatrix`, `RiskContribution` types already exported (lines 119-127).
- `postBuilderOptimize` (lines 1115-1123) is the function-shape template. Operation type aliases declared near the top (e.g. line 19, 41); response/request aliases near lines 279-294.
- `OptimizeResponse`, `WeightOut`, `BuilderObjective`, `BuilderAssetRef` exported (lines 281-289). `SeriesPoint = [string, number]` (line 299).

**Generated types present after regen (Task 1) — verbatim schema field names:**
- `PortfolioStats` (api.d.ts 4180): `annualized_volatility`, `var_95`, `var_99`, `cvar_95`, `total_return`, `beta`, `correlation`, `diversification_ratio`, `sharpe_ratio`, `sortino_ratio`, `information_ratio`, `effective_number_of_bets`, `max_drawdown: DrawdownOut` (has `.depth`), `best_day`, `worst_day`.
- `RiskContributionOut`: `{ ticker, contribution }`. `CorrelationMatrixOut`: `{ tickers, matrix }`. `BenchmarkComparison`: `{ portfolio: [string,number][]; benchmark: [string,number][] }`. `PositionIn`: `{ ticker, weight?, quantity? }`.
- `WalkForwardRequest`: `{ assets: (FundRefIn|EquityRefIn)[]; objective; constraints: ConstraintsIn; window_days?; n_splits; gap; test_size; min_train_size; cost_bps; risk_free_annual }`. `objective` enum: `equal_weight | min_vol | erc | max_diversification | min_cvar | bl_utility | max_return_cvar`.
- `WalkForwardResponse` (current): `{ folds: FoldMetricsOut[]; params: WalkForwardParams; mean_sharpe; std_sharpe; positive_folds; mean_turnover }`. **Onda-1 backend adds `oos_curve: [string,number][]` and `fold_boundaries: string[]`** — present only after the sibling backend plan + Task 1 regen.
- `FoldMetricsOut`: `{ fold, train_size, n_obs, sharpe, cvar_95, max_drawdown, turnover, gross_return, net_return }`.
- `WalkForwardParams`: `{ objective; n_obs; n_splits_computed; gap; test_size; min_train_size; cost_bps }`.
- `WeightOut`: `{ asset: FundRefIn|EquityRefIn; weight; ticker?; name?; asset_class?; strategy_label? }`.
- `ConfidenceBar`: `{ horizon; horizon_days; pct_5; pct_10; pct_25; pct_50; pct_75; pct_90; pct_95; mean }`.
- `MonteCarloResponse` (single-instrument, the template for the portfolio response): `{ params; percentiles; mean; median; std; historical_value; historical_horizon_days; historical_percentile_rank: number|null; confidence_bars: ConfidenceBar[]; degraded: boolean; degraded_reason: string|null }`.
- **`/monte-carlo/portfolio` does NOT exist yet** in api.d.ts; the sibling backend plan adds `PortfolioMonteCarloRequest` + `PortfolioMonteCarloResponse` and the route. The request (per the backend contract) is `{ positions: {asset: AssetRefIn, weight: number}[]; statistic; n_simulations; horizons?; risk_free_rate; seed?; window_days? }`.

**Test idiom (verbatim from `FundProfileView.test.tsx` / `FundUniverseCard.test.tsx`):**
- First line `// @vitest-environment jsdom`.
- `vi.mock("@/lib/api/client", async (importOriginal) => { const actual = await importOriginal<typeof import("@/lib/api/client")>(); return { ...actual, postX: vi.fn(), ... }; });` (keeps the real types/non-mocked exports).
- `vi.mock("@/components/charts/HighchartsChart", () => ({ HighchartsChart: () => <div data-testid="highcharts-chart" /> }));`.
- `vi.mock("@/lib/charts/chartColors", () => ({ chartColors: () => ({ ...token bag... }) }));` when the component reads colors at mount.
- Render inside `<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>`. `userEvent.setup()`, `waitFor`, `screen.findBy*`. `afterEach(() => { cleanup(); vi.clearAllMocks(); });`.
- Chart-builder unit tests: `import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";` and exercise formatters via `.call({ value })` / `.call({ x, y })` (see `nav.test.ts`).

**Commands:**
- Codegen: from repo root `cd backend && uv run python scripts/export_openapi.py` (writes `backend/openapi.json`), then `cd frontend && pnpm run types` (runs `openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts`).
- Frontend gate: `cd frontend && pnpm lint && pnpm run typecheck`.
- Tests: all `cd frontend && pnpm test`; one file `cd frontend && pnpm exec vitest run src/components/builder/RiskTab.test.tsx`.

**Open decision baked into this plan:** `ResultsSkeleton` is defined **locally** in `BuilderView.tsx` (lines 460-471) and is **not exported**. The spec says "reuse `ResultsSkeleton`/`ErrorPanel`". `ErrorPanel` is exported from `@/components/screener/shared` and is reused directly. For the per-tab loading state we add a tiny shared `TabSkeleton` in a new `tabShared.tsx` (so we don't widen `BuilderView`'s API surface or create an import cycle). If a reviewer prefers exporting `ResultsSkeleton`, that is an equivalent substitution.

---

## Task 1 — Regenerate `api.d.ts` from the onda-1 backend OpenAPI

Assumes the sibling backend plan (`oos_curve`/`fold_boundaries` on walk-forward + the new `/monte-carlo/portfolio` endpoint) is implemented.

> **Cross-plan reconciliation (read first):** The onda 1 backend makes walk-forward ACCEPT `max_return_cvar` (equilibrium mode) and adds a required `cvar_limit` to `WalkForwardRequest`. So the `BacktestTab` must NOT downgrade `max_return_cvar` — it sends `objective: max_return_cvar` + `cvar_limit` (only `bl_utility` is downgraded to `min_cvar`). The CVaR ceiling flows as a prop chain BuilderView → ResultsPanel → BacktestTab, parallel to `objective`: BuilderView holds `cvarLimitPct` from onda 0b, so pass `cvarLimitPct/100` (or `null`). Task 5 reflects this; also add `cvarLimit` to `ResultsPanel`'s props and to the `BacktestTab` call alongside `objective` when wiring Task 2.

**Files:**
- Modify: `frontend/src/lib/api/api.d.ts` (generated; do not hand-edit)
- (input) `backend/openapi.json` (regenerated by the script)

**Steps:**
- [x] Regenerate the OpenAPI schema: `cd backend && uv run python scripts/export_openapi.py`. Expected stdout: `Wrote <repo>/backend/openapi.json`.
- [x] Regenerate the typed client surface: `cd frontend && pnpm run types`. Expected: command exits 0 with no output (openapi-typescript writes the file silently).
- [x] Verify the new shapes landed:
  - `cd frontend && grep -nE 'oos_curve|fold_boundaries' src/lib/api/api.d.ts` → both appear inside the `WalkForwardResponse` schema (`oos_curve: [string, number][]`, `fold_boundaries: string[]`).
  - `cd frontend && grep -nE '"/monte-carlo/portfolio"|PortfolioMonteCarloRequest|PortfolioMonteCarloResponse' src/lib/api/api.d.ts` → the path object and both schemas appear.
- [x] Sanity gate: `cd frontend && pnpm run typecheck`. Expected exit 0 (existing `client.ts` consumers of `WalkForwardResponse`/`MonteCarloResponse` still compile — no breaking renames). If `typecheck` fails here, the backend contract diverged from this plan's assumptions — STOP and reconcile before continuing.

---

## Task 2 — Tab skeleton in `ResultsPanel` + extract `AllocationTab`

Convert `ResultsPanel` into the tab wrapper; move its current body unchanged into `AllocationTab`. Add `constraints`/`windowDays` props threaded from `BuilderView` (needed by BacktestTab). Add a small shared loading skeleton.

**Files:**
- Create: `frontend/src/components/builder/AllocationTab.tsx`
- Create: `frontend/src/components/builder/tabShared.tsx`
- Modify: `frontend/src/components/builder/ResultsPanel.tsx`
- Modify: `frontend/src/components/builder/BuilderView.tsx`
- Test: `frontend/src/components/builder/ResultsPanel.test.tsx`

**Steps:**

- [x] Create `frontend/src/components/builder/tabShared.tsx` — the per-tab loading skeleton and a shared constraints type. FULL code:
  ```tsx
  "use client";

  /**
   * Shared scaffolding for the Builder result tabs: a loading skeleton matching
   * the optimize ResultsSkeleton rhythm (KPI band + chart block) and the
   * constraints shape threaded from BuilderView into the Backtest tab.
   */

  /** Constraints the Builder run used, as decimal fractions (cap 0.25 = 25%). */
  export interface UsedConstraints {
    cap: number | null;
    min_weight: number | null;
  }

  /** Per-tab loading placeholder — mirrors BuilderView's ResultsSkeleton. */
  export function TabSkeleton({ label }: { label: string }) {
    return (
      <div
        aria-busy="true"
        aria-label={label}
        className="flex animate-pulse flex-col gap-px"
      >
        <div className="h-[84px] bg-surface-2" />
        <div className="h-[320px] bg-surface-2" />
      </div>
    );
  }
  ```

- [x] Create `frontend/src/components/builder/AllocationTab.tsx`. Move the **entire current body** of `ResultsPanel` (the `return (<div className="flex flex-col gap-px">…</div>)` and ALL local logic above it: `treeRows`, the save state/mutation, `saveRows`, `fundIds`, `profileQueries`, `profilesById`, `staleness`, `notional`, `rowState`, `onSave`, `setExecField`, `executedCount`/`referenceCount`, `rows`, `maxWeight`, `proposedDonut`, `currentDonut`, `exportCsv`) into a component `AllocationTab` with the SAME prop signature `ResultsPanel` has today plus the two new props. Move the bottom helpers (`csvField`, `Th`, `Donut`, `MuDiagnostics`) into this file too. Keep all imports that the body uses. The component header:
  ```tsx
  "use client";

  /**
   * Allocation tab — the original Builder results body: KPI tiles, the
   * proposed-weights table (or broad-mode tree grid), Current-vs-Proposed
   * donuts, μ diagnostics, selection diagnostics, CSV export and
   * Save-as-portfolio. Extracted verbatim from ResultsPanel (onda 1); no
   * behavior change.
   */
  import { useMutation, useQueries } from "@tanstack/react-query";
  import Link from "next/link";
  import { useMemo, useState } from "react";

  import {
    fetchFundProfile,
    postBuilderSave,
    type BuilderObjective,
    type BuilderSaveRequest,
    type FundProfile,
    type OptimizeResponse,
  } from "@/lib/api/client";
  import { parseDecimal } from "@/lib/parse";
  import { buildHcAllocationOption } from "@/lib/charts/hc/allocation";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { formatNumber, formatPercent } from "@/lib/format";
  import { HighchartsChart } from "@/components/charts/HighchartsChart";
  import { Card, KpiTile, valueTone } from "@/components/ui/panels";
  import {
    BUTTON_CLASS,
    BUTTON_PRIMARY_CLASS,
    ErrorPanel,
    FIELD_LABEL_CLASS,
    INPUT_CLASS,
  } from "@/components/screener/shared";

  import { assetKey, assetName, assetTicker, type UniverseAsset } from "./assets";
  import { SelectionDiagnostics } from "./SelectionDiagnostics";
  import { DataGrid } from "@/components/ui/DataGrid";
  import { buildWeightsTree, type WeightInput } from "@/lib/builder/weightsTree";
  import { weightsTreeGridOptions } from "@/lib/grid/weightsTreeGridOptions";
  import type { BaseAllocation } from "./ResultsPanel";

  export function AllocationTab({
    result,
    objective,
    assetsByKey,
    base,
    colors,
    grouped,
  }: {
    result: OptimizeResponse;
    objective: BuilderObjective;
    assetsByKey: Map<string, UniverseAsset>;
    base: BaseAllocation | null;
    colors: ChartColors | null;
    grouped: boolean;
  }) {
    // … MOVE the entire existing ResultsPanel body here verbatim …
  }

  // … MOVE csvField, Th, Donut, MuDiagnostics here verbatim …
  ```
  Notes: keep the `WeightRow`, `ExecutionInputs`, `EMPTY_EXECUTION`, `SAVE_WEIGHT_FLOOR`, `parseOptionalPositive`, `parseOptionalNonNegative`, `lastNav` helpers in this file (they only serve the allocation body). `AllocationTab` does NOT take `constraints`/`windowDays` (allocation doesn't use them).

- [x] Rewrite `frontend/src/components/builder/ResultsPanel.tsx` as the tab wrapper. Keep `export interface BaseAllocation` here (AllocationTab imports it from `./ResultsPanel`, matching the current export site so no other importer breaks). FULL new file:
  ```tsx
  "use client";

  /**
   * Builder results workspace (onda 1): a tabbed shell around the optimize
   * response. "Allocation" is the original results body; "Risk", "Backtest" and
   * "Projection" lazily wire the quant endpoints (one fetch on first open,
   * cached until a new optimize result remounts this panel). The tab strip
   * mirrors FundProfileView's pattern and button classes.
   */
  import { useState } from "react";

  import type { BuilderObjective, OptimizeResponse } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";

  import type { UniverseAsset } from "./assets";
  import { AllocationTab } from "./AllocationTab";
  import { RiskTab } from "./RiskTab";
  import { BacktestTab } from "./BacktestTab";
  import { ProjectionTab } from "./ProjectionTab";
  import type { UsedConstraints } from "./tabShared";

  /** Current allocation of the base portfolio (when seeded from a saved one). */
  export interface BaseAllocation {
    name: string;
    /** assetKey ("equity:<TICKER>") -> weight fraction by market value. */
    weights: Map<string, number>;
  }

  type ResultTabId = "allocation" | "risk" | "backtest" | "projection";

  const TABS: { id: ResultTabId; label: string }[] = [
    { id: "allocation", label: "Allocation" },
    { id: "risk", label: "Risk" },
    { id: "backtest", label: "Backtest" },
    { id: "projection", label: "Projection" },
  ];

  export function ResultsPanel({
    result,
    objective,
    constraints,
    windowDays,
    assetsByKey,
    base,
    colors,
    grouped,
  }: {
    result: OptimizeResponse;
    objective: BuilderObjective;
    constraints: UsedConstraints;
    /** Estimation window the run used (days); null = full history. */
    windowDays: number | null;
    assetsByKey: Map<string, UniverseAsset>;
    base: BaseAllocation | null;
    colors: ChartColors | null;
    grouped: boolean;
  }) {
    const [activeTab, setActiveTab] = useState<ResultTabId>("allocation");

    return (
      <div className="flex flex-col gap-px">
        <div className="border-b border-border-strong">
          <div
            className="flex flex-wrap gap-1"
            role="tablist"
            aria-label="Builder result tabs"
          >
            {TABS.map((tab) => (
              <button
                key={tab.id}
                type="button"
                role="tab"
                aria-selected={activeTab === tab.id}
                onClick={() => setActiveTab(tab.id)}
                className={`h-[34px] border border-b-0 px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors ${
                  activeTab === tab.id
                    ? "border-border-strong bg-surface-2 text-text-primary"
                    : "border-transparent bg-transparent text-text-muted hover:bg-layer-hover hover:text-text-primary"
                }`}
              >
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {activeTab === "allocation" && (
          <AllocationTab
            result={result}
            objective={objective}
            assetsByKey={assetsByKey}
            base={base}
            colors={colors}
            grouped={grouped}
          />
        )}
        {activeTab === "risk" && <RiskTab result={result} colors={colors} />}
        {activeTab === "backtest" && (
          <BacktestTab
            result={result}
            objective={objective}
            constraints={constraints}
            windowDays={windowDays}
            colors={colors}
          />
        )}
        {activeTab === "projection" && (
          <ProjectionTab result={result} colors={colors} />
        )}
      </div>
    );
  }
  ```
  Note on cache/reset: `BuilderView` already passes `key={mutation.submittedAt}`, so a new optimization fully remounts `ResultsPanel` (and every tab) → per-tab mutation state resets automatically and each data tab refetches on its next open. The conditional render also unmounts a tab when you leave it, so re-opening re-fires the mutation; that is acceptable per the spec ("lazy; cached until the result changes"). Each data tab additionally guards its mount-fire with a ref keyed to avoid double-firing under React 18/19 strict re-mounts (see Tasks 4-6).

- [x] Modify `BuilderView.tsx` to thread the new props. In `onRun` the `constraints` object already exists (lines 201-204). Pass them down. Replace the `<ResultsPanel … />` render (lines 410-419) with:
  ```tsx
  ) : mutation.data ? (
    <ResultsPanel
      key={mutation.submittedAt}
      result={mutation.data}
      objective={objective}
      constraints={{
        cap: cap !== null ? cap / 100 : null,
        min_weight: minWeight !== null ? minWeight / 100 : null,
      }}
      windowDays={windowVal}
      assetsByKey={assetsByKey}
      base={mode === "simulate" ? base : null}
      colors={colors}
      grouped={mode === "universe"}
    />
  ) : (
  ```
  `cap`, `minWeight`, `windowVal` are already computed in `BuilderView` (lines 174-176). Add the `UsedConstraints` import if helpful, but the inline object is structurally typed — no import strictly required.

- [x] Write the tab-shell test `frontend/src/components/builder/ResultsPanel.test.tsx`. It mocks the three data tabs to lightweight stubs (so this test stays about the shell) and asserts: Allocation renders by default, the four tabs exist with `role="tab"`, switching to Risk hides Allocation and shows Risk, and `aria-selected` tracks the active tab. FULL code:
  ```tsx
  // @vitest-environment jsdom
  import { cleanup, render, screen } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { afterEach, describe, expect, it, vi } from "vitest";

  import { ResultsPanel } from "./ResultsPanel";
  import type { OptimizeResponse } from "@/lib/api/client";

  vi.mock("./AllocationTab", () => ({
    AllocationTab: () => <div data-testid="allocation-tab" />,
  }));
  vi.mock("./RiskTab", () => ({ RiskTab: () => <div data-testid="risk-tab" /> }));
  vi.mock("./BacktestTab", () => ({
    BacktestTab: () => <div data-testid="backtest-tab" />,
  }));
  vi.mock("./ProjectionTab", () => ({
    ProjectionTab: () => <div data-testid="projection-tab" />,
  }));

  const RESULT = {
    weights: [],
    expected: { vol_ann: 0.1, cvar_95_in_sample: -0.02, return_ann_bl: null },
    diagnostics: {
      n_obs: 252,
      status: "optimal",
      mu_equilibrium: null,
      mu_posterior: null,
      selection: null,
    },
  } as unknown as OptimizeResponse;

  function renderPanel() {
    return render(
      <ResultsPanel
        result={RESULT}
        objective="min_cvar"
        constraints={{ cap: 0.25, min_weight: null }}
        windowDays={null}
        assetsByKey={new Map()}
        base={null}
        colors={null}
        grouped={false}
      />,
    );
  }

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe("ResultsPanel tab shell", () => {
    it("shows Allocation by default and exposes all four tabs", () => {
      renderPanel();
      expect(screen.getByTestId("allocation-tab")).toBeInTheDocument();
      for (const name of ["Allocation", "Risk", "Backtest", "Projection"]) {
        expect(screen.getByRole("tab", { name })).toBeInTheDocument();
      }
      expect(screen.getByRole("tab", { name: "Allocation" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });

    it("switches to Risk: hides Allocation, shows Risk, updates aria-selected", async () => {
      const user = userEvent.setup();
      renderPanel();
      await user.click(screen.getByRole("tab", { name: "Risk" }));
      expect(screen.queryByTestId("allocation-tab")).not.toBeInTheDocument();
      expect(screen.getByTestId("risk-tab")).toBeInTheDocument();
      expect(screen.getByRole("tab", { name: "Risk" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
      expect(screen.getByRole("tab", { name: "Allocation" })).toHaveAttribute(
        "aria-selected",
        "false",
      );
    });
  });
  ```

- [x] Run the shell test: `cd frontend && pnpm exec vitest run src/components/builder/ResultsPanel.test.tsx`. Expected: 2 passing.
- [x] Gate: `cd frontend && pnpm run typecheck`. Expected exit 0 (AllocationTab/Risk/Backtest/Projection imports resolve — they exist as stubs after Tasks 3-6; do this task's typecheck **after** Task 3-6 stubs land, or create empty placeholder components first. Recommended order: create one-line placeholder `RiskTab`/`BacktestTab`/`ProjectionTab` that `return null` so the shell compiles, then flesh them out in Tasks 4-6.).

---

## Task 3 — Client functions + types for the three tab endpoints

`postPortfolioAnalysis` already exists. Add `postBacktestWalkForward` and `postPortfolioMonteCarlo` (+ type aliases) mirroring `postBuilderOptimize` and the existing operation-alias block.

**Files:**
- Modify: `frontend/src/lib/api/client.ts`
- Test: `frontend/src/lib/api/client.backtestMonteCarlo.test.ts`

**Steps:**

- [x] Add operation aliases beside the existing ones (near line 41, in the `type …Operation = paths[…]` block):
  ```ts
  type BacktestWalkForwardOperation = paths["/backtest/walk-forward"]["post"];
  type PortfolioMonteCarloOperation = paths["/monte-carlo/portfolio"]["post"];
  ```
- [x] Add request/response type aliases beside the optimize aliases (near lines 279-294):
  ```ts
  export type WalkForwardRequest =
    BacktestWalkForwardOperation["requestBody"]["content"]["application/json"];
  export type WalkForwardResponse =
    BacktestWalkForwardOperation["responses"]["200"]["content"]["application/json"];
  export type FoldMetrics = WalkForwardResponse["folds"][number];

  export type PortfolioMonteCarloRequest =
    PortfolioMonteCarloOperation["requestBody"]["content"]["application/json"];
  export type PortfolioMonteCarloResponse =
    PortfolioMonteCarloOperation["responses"]["200"]["content"]["application/json"];
  /** Per-horizon percentile fan of the projected statistic. */
  export type ConfidenceBar = PortfolioMonteCarloResponse["confidence_bars"][number];
  /** Statistic the projection selector toggles. */
  export type MonteCarloStatistic = PortfolioMonteCarloRequest["statistic"];
  ```
- [x] Add the two functions next to `postBuilderOptimize` (after line 1123), mirroring its shape exactly:
  ```ts
  export function postBacktestWalkForward(
    body: WalkForwardRequest,
    signal?: AbortSignal,
  ): Promise<WalkForwardResponse> {
    return request<WalkForwardResponse>("/backtest/walk-forward", signal, {
      method: "POST",
      json: body,
    });
  }

  export function postPortfolioMonteCarlo(
    body: PortfolioMonteCarloRequest,
    signal?: AbortSignal,
  ): Promise<PortfolioMonteCarloResponse> {
    return request<PortfolioMonteCarloResponse>("/monte-carlo/portfolio", signal, {
      method: "POST",
      json: body,
    });
  }
  ```
- [x] Write `frontend/src/lib/api/client.backtestMonteCarlo.test.ts` (node env — no jsdom). It stubs `fetch` and asserts each function POSTs the right path/body and parses JSON, and that a non-OK response throws `ApiError` with the backend `detail`. Mirror the existing fail-loud contract (`request<T>` extracts `detail`). FULL code:
  ```ts
  import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

  import {
    ApiError,
    postBacktestWalkForward,
    postPortfolioMonteCarlo,
    type PortfolioMonteCarloRequest,
    type WalkForwardRequest,
  } from "@/lib/api/client";

  const fetchMock = vi.fn();

  beforeEach(() => {
    vi.stubGlobal("fetch", fetchMock);
    fetchMock.mockReset();
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  function okJson(body: unknown): Response {
    return {
      ok: true,
      status: 200,
      statusText: "OK",
      json: async () => body,
    } as unknown as Response;
  }

  function errJson(status: number, detail: string): Response {
    return {
      ok: false,
      status,
      statusText: "Unprocessable Entity",
      json: async () => ({ detail }),
    } as unknown as Response;
  }

  const WF_REQ: WalkForwardRequest = {
    assets: [{ kind: "equity", ticker: "SPY" }],
    objective: "min_cvar",
    constraints: { cap: 0.25 },
    n_splits: 5,
    gap: 2,
    test_size: 63,
    min_train_size: 252,
    cost_bps: 10,
    risk_free_annual: 0,
  };

  const MC_REQ: PortfolioMonteCarloRequest = {
    positions: [{ asset: { kind: "equity", ticker: "SPY" }, weight: 1 }],
    statistic: "return",
    n_simulations: 10000,
    risk_free_rate: 0.04,
  };

  describe("postBacktestWalkForward", () => {
    it("POSTs /backtest/walk-forward with the JSON body and parses the response", async () => {
      fetchMock.mockResolvedValue(okJson({ folds: [], mean_sharpe: 0 }));
      const out = await postBacktestWalkForward(WF_REQ);
      const [url, init] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/backtest/walk-forward");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual(WF_REQ);
      expect(out).toEqual({ folds: [], mean_sharpe: 0 });
    });

    it("throws ApiError carrying the backend detail on 422", async () => {
      fetchMock.mockResolvedValue(errJson(422, "insufficient history for the folds"));
      await expect(postBacktestWalkForward(WF_REQ)).rejects.toMatchObject({
        name: "ApiError",
        status: 422,
        message: "insufficient history for the folds",
      });
    });
  });

  describe("postPortfolioMonteCarlo", () => {
    it("POSTs /monte-carlo/portfolio with the JSON body and parses the response", async () => {
      fetchMock.mockResolvedValue(okJson({ confidence_bars: [], degraded: false }));
      const out = await postPortfolioMonteCarlo(MC_REQ);
      const [url, init] = fetchMock.mock.calls[0];
      expect(String(url)).toContain("/monte-carlo/portfolio");
      expect(init.method).toBe("POST");
      expect(JSON.parse(init.body as string)).toEqual(MC_REQ);
      expect(out).toEqual({ confidence_bars: [], degraded: false });
    });

    it("surfaces ApiError on a degraded-history 422", async () => {
      fetchMock.mockResolvedValue(errJson(422, "insufficient common history"));
      await expect(postPortfolioMonteCarlo(MC_REQ)).rejects.toBeInstanceOf(ApiError);
    });
  });
  ```
  Note: `postBacktestWalkForward`/`postPortfolioMonteCarlo` use the auth fetcher (`fetchWithAuth`) which wraps the global `fetch`; stubbing the global `fetch` is sufficient because `fetchWithAuth`'s `fetchImpl` closes over `(input, init) => fetch(input, init)`. The 401/403 retry path is not exercised here (200/422 only).
- [x] Run: `cd frontend && pnpm exec vitest run src/lib/api/client.backtestMonteCarlo.test.ts`. Expected: 4 passing.
- [x] Gate: `cd frontend && pnpm run typecheck`. Expected exit 0.

---

## Task 4 — `RiskTab` (POST /portfolio/analysis)

**Files:**
- Create: `frontend/src/components/builder/RiskTab.tsx`
- Test: `frontend/src/components/builder/RiskTab.test.tsx`

**Steps:**

- [x] Create `frontend/src/components/builder/RiskTab.tsx`. Behavior: on first mount fire `postPortfolioAnalysis` with `mode:"weights"`, `range:"1Y"`, `benchmark:"SPY"`, `positions` from each weight's resolvable ticker; fail-loud if any weight has no ticker. Render KPI tiles from `stats`, risk-contribution bars, correlation heatmap, cumulative curve. FULL code:
  ```tsx
  "use client";

  /**
   * Risk tab — decomposes the freshly-optimized portfolio via POST
   * /portfolio/analysis (mode=weights, benchmark SPY, range 1Y). The endpoint
   * indexes by TICKER, so every weight must resolve to one; if any does not we
   * fail loud rather than send an invalid request. The response is fully
   * render-ready — KPI tiles from stats, risk contributions, correlation
   * heatmap, and the portfolio-vs-benchmark cumulative curve.
   */
  import { useMutation } from "@tanstack/react-query";
  import { useEffect, useRef } from "react";

  import {
    postPortfolioAnalysis,
    type OptimizeResponse,
    type PortfolioAnalysis,
    type PortfolioAnalysisRequest,
    type WeightOut,
  } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { buildHcRiskContributionsOption } from "@/lib/charts/hc/contributions";
  import { buildHcHeatmapOption } from "@/lib/charts/hc/heatmap";
  import { buildHcCumulativeOption } from "@/lib/charts/hc/cumulative";
  import { formatNumber, formatPercent } from "@/lib/format";
  import { HighchartsChart } from "@/components/charts/HighchartsChart";
  import { Card, KpiTile, valueTone } from "@/components/ui/panels";
  import { ErrorPanel } from "@/components/screener/shared";

  import { TabSkeleton } from "./tabShared";

  /** Resolve a weight's ticker (fund universe rows echo .ticker; equities carry
   *  asset.ticker). Returns null when neither is present. */
  function weightTicker(w: WeightOut): string | null {
    if (w.ticker) return w.ticker;
    if (w.asset.kind === "equity") return w.asset.ticker;
    return null;
  }

  export function RiskTab({
    result,
    colors,
  }: {
    result: OptimizeResponse;
    colors: ChartColors | null;
  }) {
    const mutation = useMutation({
      mutationFn: (body: PortfolioAnalysisRequest) => postPortfolioAnalysis(body),
    });

    // Build the request once; surface unresolved tickers as a domain error.
    const missing = result.weights.filter((w) => weightTicker(w) === null).length;
    const positions = result.weights
      .map((w) => ({ ticker: weightTicker(w), weight: w.weight }))
      .filter((p): p is { ticker: string; weight: number } => p.ticker !== null);

    const firedRef = useRef(false);
    useEffect(() => {
      if (firedRef.current || missing > 0) return;
      firedRef.current = true;
      mutation.mutate({
        positions,
        mode: "weights",
        benchmark: "SPY",
        range: "1Y",
      });
      // Fire exactly once on mount; a new optimize result remounts this tab.
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    if (missing > 0) {
      return (
        <ErrorPanel
          title="Cannot analyze risk"
          message={`Could not resolve a ticker for ${missing} position${
            missing === 1 ? "" : "s"
          } — open this as a saved portfolio to analyze it.`}
          onRetry={() => undefined}
        />
      );
    }

    if (mutation.isPending || mutation.isIdle) {
      return <TabSkeleton label="Analyzing portfolio risk" />;
    }
    if (mutation.isError) {
      return (
        <ErrorPanel
          title="Risk analysis failed"
          message={mutation.error.message}
          onRetry={() =>
            mutation.mutate({ positions, mode: "weights", benchmark: "SPY", range: "1Y" })
          }
        />
      );
    }

    return <RiskBody data={mutation.data} colors={colors} />;
  }

  function RiskBody({
    data,
    colors,
  }: {
    data: PortfolioAnalysis;
    colors: ChartColors | null;
  }) {
    const { stats } = data;
    const contributionsOption = colors
      ? buildHcRiskContributionsOption(data.risk_contributions, colors)
      : null;
    const heatmapOption = colors
      ? buildHcHeatmapOption(data.correlation_matrix, colors)
      : null;
    const cumulativeOption = colors
      ? buildHcCumulativeOption(
          {
            asset: data.benchmark_comparison.portfolio,
            benchmark: data.benchmark_comparison.benchmark,
          },
          "Portfolio",
          "SPY",
          colors,
        )
      : null;

    return (
      <div className="flex flex-col gap-px">
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
          <KpiTile label="Vol (ann.)" value={formatPercent(stats.annualized_volatility)} tone="text-accent" />
          <KpiTile label="Sharpe" value={formatNumber(stats.sharpe_ratio)} />
          <KpiTile label="Sortino" value={formatNumber(stats.sortino_ratio)} />
          <KpiTile label="CVaR 95" value={formatPercent(stats.cvar_95)} detail="1-day, worst 5%" />
          <KpiTile label="Max drawdown" value={formatPercent(stats.max_drawdown.depth)} />
          <KpiTile label="Diversification" value={formatNumber(stats.diversification_ratio)} />
          <KpiTile
            label="Information ratio"
            value={formatNumber(stats.information_ratio)}
            tone={valueTone(stats.information_ratio)}
          />
          <KpiTile label="Beta (SPY)" value={formatNumber(stats.beta)} />
        </div>

        <Card title="Risk contribution by asset">
          {contributionsOption ? (
            <HighchartsChart
              options={contributionsOption}
              className="h-[320px] w-full"
              isEmpty={data.risk_contributions.length === 0}
              emptyMessage="No risk contributions returned."
            />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
          )}
        </Card>

        <Card title="Correlation matrix">
          {heatmapOption ? (
            <HighchartsChart
              options={heatmapOption}
              className="h-[360px] w-full"
              isEmpty={data.correlation_matrix.tickers.length === 0}
              emptyMessage="No correlation matrix returned."
            />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
          )}
        </Card>

        <Card title="Cumulative return — portfolio vs SPY">
          {cumulativeOption ? (
            <HighchartsChart
              options={cumulativeOption}
              className="h-[320px] w-full"
              isEmpty={data.benchmark_comparison.portfolio.length === 0}
              emptyMessage="No comparison series returned."
            />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
          )}
        </Card>
      </div>
    );
  }
  ```
  Note `mutation.isIdle` is included in the skeleton branch so the one-tick gap between mount and the `useEffect` firing renders the skeleton, not an empty frame.

- [x] Write `frontend/src/components/builder/RiskTab.test.tsx` covering loading→success, the 422 error path, the unresolved-ticker fail-loud path, and "fires the analysis exactly once". FULL code:
  ```tsx
  // @vitest-environment jsdom
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { cleanup, render, screen, waitFor } from "@testing-library/react";
  import { afterEach, describe, expect, it, vi } from "vitest";

  vi.mock("@/components/charts/HighchartsChart", () => ({
    HighchartsChart: () => <div data-testid="highcharts-chart" />,
  }));
  vi.mock("@/lib/api/client", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/lib/api/client")>();
    return { ...actual, postPortfolioAnalysis: vi.fn() };
  });

  import * as client from "@/lib/api/client";
  import { RiskTab } from "./RiskTab";
  import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
  import type { OptimizeResponse, PortfolioAnalysis } from "@/lib/api/client";

  const mocked = vi.mocked(client);

  function makeResult(weights: OptimizeResponse["weights"]): OptimizeResponse {
    return { weights } as unknown as OptimizeResponse;
  }

  const SPY_WEIGHT = {
    asset: { kind: "equity", ticker: "SPY" },
    weight: 0.6,
    ticker: "SPY",
  } as unknown as OptimizeResponse["weights"][number];
  const QQQ_WEIGHT = {
    asset: { kind: "equity", ticker: "QQQ" },
    weight: 0.4,
    ticker: "QQQ",
  } as unknown as OptimizeResponse["weights"][number];
  const FUND_NO_TICKER = {
    asset: { kind: "fund", id: "uuid-1" },
    weight: 0.4,
    ticker: null,
  } as unknown as OptimizeResponse["weights"][number];

  function makeAnalysis(): PortfolioAnalysis {
    return {
      stats: {
        annualized_volatility: 0.12,
        var_95: 0.02,
        var_99: 0.03,
        cvar_95: 0.03,
        total_return: 0.25,
        beta: 1,
        correlation: 0.95,
        diversification_ratio: 1.2,
        sharpe_ratio: 1.1,
        sortino_ratio: 1.3,
        information_ratio: 0.4,
        effective_number_of_bets: 1.8,
        max_drawdown: { depth: -0.08, peak_date: "2026-01-01", trough_date: "2026-03-01" },
        best_day: { date: "2026-01-05", value: 0.02 },
        worst_day: { date: "2026-02-05", value: -0.03 },
      },
      risk_contributions: [
        { ticker: "SPY", contribution: 0.6 },
        { ticker: "QQQ", contribution: 0.4 },
      ],
      correlation_matrix: { tickers: ["SPY", "QQQ"], matrix: [[1, 0.9], [0.9, 1]] },
      benchmark_comparison: {
        portfolio: [["2025-06-12", 0], ["2026-06-12", 0.25]],
        benchmark: [["2025-06-12", 0], ["2026-06-12", 0.2]],
      },
    } as unknown as PortfolioAnalysis;
  }

  function renderTab(result: OptimizeResponse) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <RiskTab result={result} colors={TEST_COLORS} />
      </QueryClientProvider>,
    );
  }

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe("RiskTab", () => {
    it("fires /portfolio/analysis once with weights and renders KPI tiles + charts", async () => {
      mocked.postPortfolioAnalysis.mockResolvedValue(makeAnalysis());
      renderTab(makeResult([SPY_WEIGHT, QQQ_WEIGHT]));

      await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1));
      expect(mocked.postPortfolioAnalysis).toHaveBeenCalledWith({
        positions: [
          { ticker: "SPY", weight: 0.6 },
          { ticker: "QQQ", weight: 0.4 },
        ],
        mode: "weights",
        benchmark: "SPY",
        range: "1Y",
      });

      expect(await screen.findByText("Sharpe")).toBeInTheDocument();
      expect(screen.getByText("Beta (SPY)")).toBeInTheDocument();
      expect(screen.getAllByTestId("highcharts-chart")).toHaveLength(3);
    });

    it("shows the verbatim 422 detail on failure", async () => {
      mocked.postPortfolioAnalysis.mockRejectedValue(
        new client.ApiError(422, "ticker SPY has no priced history"),
      );
      renderTab(makeResult([SPY_WEIGHT, QQQ_WEIGHT]));
      expect(
        await screen.findByText("ticker SPY has no priced history"),
      ).toBeInTheDocument();
    });

    it("fails loud (no request) when a weight has no resolvable ticker", async () => {
      renderTab(makeResult([SPY_WEIGHT, FUND_NO_TICKER]));
      expect(await screen.findByText(/Could not resolve a ticker for 1 position/)).toBeInTheDocument();
      expect(mocked.postPortfolioAnalysis).not.toHaveBeenCalled();
    });
  });
  ```

- [x] Run: `cd frontend && pnpm exec vitest run src/components/builder/RiskTab.test.tsx`. Expected: 3 passing.
- [x] Gate: `cd frontend && pnpm run typecheck && pnpm lint`. Expected exit 0.

---

## Task 5 — `BacktestTab` (POST /backtest/walk-forward) + `buildHcFoldMetricsOption`

**Files:**
- Create: `frontend/src/lib/charts/hc/foldMetrics.ts`
- Create: `frontend/src/components/builder/BacktestTab.tsx`
- Test: `frontend/src/lib/charts/hc/foldMetrics.test.ts`
- Test: `frontend/src/components/builder/BacktestTab.test.tsx`

**Steps:**

- [x] Create the vertical-column builder `frontend/src/lib/charts/hc/foldMetrics.ts`, styled after `histogram.ts` (a `column` chart, categories on the x-axis, percent y-axis). FULL code:
  ```ts
  /**
   * Pure option builder: per-fold metric as vertical columns (Highcharts Core).
   *
   * One column per walk-forward fold (x-axis category "F1", "F2", …) for a
   * chosen metric (net return or Sharpe). Gain/loss tinting for signed values;
   * the global Graphite theme owns axis/grid/tooltip chrome. Mirrors the
   * histogram.ts column style. Returns valid Options for empty input.
   */
  import type { Options } from "highcharts";

  import type { FoldMetrics } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { formatNumber, formatPercent } from "@/lib/format";

  export type FoldMetricKey = "net_return" | "sharpe";

  export function buildHcFoldMetricsOption(
    folds: FoldMetrics[],
    metric: FoldMetricKey,
    colors: ChartColors,
  ): Options {
    const isPercent = metric === "net_return";
    const categories = folds.map((f) => `F${f.fold}`);
    const data = folds.map((f) => {
      const y = metric === "net_return" ? f.net_return : f.sharpe;
      return { y, color: y >= 0 ? colors.bar : colors.loss };
    });

    const fmt = (v: number) => (isPercent ? formatPercent(v, 1, { signed: true }) : formatNumber(v));

    return {
      chart: { type: "column" },
      legend: { enabled: false },
      xAxis: { categories, crosshair: true, tickWidth: 0 },
      yAxis: {
        title: { text: undefined },
        labels: {
          formatter() {
            return isPercent
              ? formatPercent(this.value as number, 0)
              : formatNumber(this.value as number, 1);
          },
        },
      },
      tooltip: {
        shared: false,
        formatter() {
          return `${this.x}<br/><b>${fmt(this.y as number)}</b>`;
        },
      },
      series: [
        {
          type: "column",
          name: metric === "net_return" ? "Net return" : "Sharpe",
          data,
          pointPadding: 0.08,
          groupPadding: 0.06,
        },
      ],
    };
  }
  ```

- [x] Write `frontend/src/lib/charts/hc/foldMetrics.test.ts` (node env). FULL code:
  ```ts
  import { describe, expect, it } from "vitest";

  import { buildHcFoldMetricsOption } from "@/lib/charts/hc/foldMetrics";
  import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
  import type { FoldMetrics } from "@/lib/api/client";
  import { formatNumber, formatPercent } from "@/lib/format";

  const FOLDS: FoldMetrics[] = [
    { fold: 1, train_size: 252, n_obs: 63, sharpe: 1.2, cvar_95: -0.02, max_drawdown: -0.05, turnover: 0.1, gross_return: 0.05, net_return: 0.04 },
    { fold: 2, train_size: 315, n_obs: 63, sharpe: -0.3, cvar_95: -0.03, max_drawdown: -0.08, turnover: 0.2, gross_return: -0.02, net_return: -0.03 },
  ];

  describe("buildHcFoldMetricsOption", () => {
    it("labels categories F1..Fn and uses one column per fold", () => {
      const opt = buildHcFoldMetricsOption(FOLDS, "net_return", TEST_COLORS);
      expect((opt.xAxis as { categories?: string[] }).categories).toEqual(["F1", "F2"]);
      const series = opt.series?.[0] as { data?: Array<{ y: number; color: string }> };
      expect(series.data?.map((d) => d.y)).toEqual([0.04, -0.03]);
    });

    it("tints negative columns with the loss token", () => {
      const opt = buildHcFoldMetricsOption(FOLDS, "net_return", TEST_COLORS);
      const series = opt.series?.[0] as { data?: Array<{ y: number; color: string }> };
      expect(series.data?.[0].color).toBe(TEST_COLORS.bar);
      expect(series.data?.[1].color).toBe(TEST_COLORS.loss);
    });

    it("formats net_return y-axis labels as percent and sharpe as numbers", () => {
      const pct = buildHcFoldMetricsOption(FOLDS, "net_return", TEST_COLORS);
      const pctLabels = (pct.yAxis as { labels?: { formatter?: (this: { value: number }) => string } }).labels!;
      expect(pctLabels.formatter!.call({ value: 0.05 })).toBe(formatPercent(0.05, 0));

      const sh = buildHcFoldMetricsOption(FOLDS, "sharpe", TEST_COLORS);
      const shLabels = (sh.yAxis as { labels?: { formatter?: (this: { value: number }) => string } }).labels!;
      expect(shLabels.formatter!.call({ value: 1.5 })).toBe(formatNumber(1.5, 1));
    });
  });
  ```

- [x] Create `frontend/src/components/builder/BacktestTab.tsx`. Behavior: choose a backtest-safe objective (mu-free); if the run's objective is mu-based (`bl_utility` or `max_return_cvar`) fall back to `min_cvar` and show a visible note; fire `postBacktestWalkForward` once with `assets = result.weights.map(w => w.asset)`, the resolved objective, and the run's constraints; render KPI tiles, per-fold table, the fold column chart, and the OOS curve (`buildHcNavOption` + `plotLines` at `fold_boundaries`). FULL code:
  ```tsx
  "use client";

  /**
   * Backtest tab — walk-forward / out-of-sample validation of the optimization
   * PROCESS (re-optimizes the objective on each expanding fold), not a replay of
   * the exact weights. Views are never sent (Gate G5); a mu-based objective is
   * downgraded to min_cvar with a visible note. Renders consistency KPIs, the
   * per-fold table, a per-fold column chart, and the chained OOS equity curve
   * with re-optimization boundaries marked.
   */
  import { useMutation } from "@tanstack/react-query";
  import { useEffect, useMemo, useRef, useState } from "react";

  import {
    postBacktestWalkForward,
    type OptimizeResponse,
    type BuilderObjective,
    type WalkForwardRequest,
    type WalkForwardResponse,
  } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { buildHcNavOption } from "@/lib/charts/hc/nav";
  import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
  import {
    buildHcFoldMetricsOption,
    type FoldMetricKey,
  } from "@/lib/charts/hc/foldMetrics";
  import { formatNumber, formatPercent } from "@/lib/format";
  import { HighchartsChart } from "@/components/charts/HighchartsChart";
  import { Card, KpiTile } from "@/components/ui/panels";
  import { ErrorPanel } from "@/components/screener/shared";

  import { TabSkeleton, type UsedConstraints } from "./tabShared";

  /** Objectives the walk-forward backtest can run: the mu-free set PLUS
   *  max_return_cvar (equilibrium mode — the onda 1 backend threads w_mkt into
   *  the per-fold solve). Only bl_utility needs hindsight views, so it is the
   *  sole downgrade case. */
  const BACKTESTABLE: ReadonlySet<BuilderObjective> = new Set<BuilderObjective>([
    "min_cvar",
    "min_vol",
    "erc",
    "max_diversification",
    "equal_weight",
    "max_return_cvar",
  ]);

  export function BacktestTab({
    result,
    objective,
    constraints,
    windowDays,
    cvarLimit,
    colors,
  }: {
    result: OptimizeResponse;
    objective: BuilderObjective;
    constraints: UsedConstraints;
    windowDays: number | null;
    // Daily CVaR ceiling used in the optimization (decimal fraction); required
    // when backtesting max_return_cvar (the new default objective). Flows from
    // BuilderView → ResultsPanel → here, parallel to `objective`.
    cvarLimit: number | null;
    colors: ChartColors | null;
  }) {
    const downgraded = !BACKTESTABLE.has(objective);
    const backtestObjective: WalkForwardRequest["objective"] = downgraded
      ? "min_cvar"
      : (objective as WalkForwardRequest["objective"]);

    const body: WalkForwardRequest = useMemo(
      () => ({
        assets: result.weights.map((w) => w.asset),
        objective: backtestObjective,
        constraints: { cap: constraints.cap, min_weight: constraints.min_weight },
        window_days: windowDays,
        n_splits: 5,
        gap: 2,
        test_size: 63,
        min_train_size: 252,
        cost_bps: 10,
        risk_free_annual: 0,
        // max_return_cvar re-optimizes per fold off the equilibrium return and
        // needs the same daily CVaR ceiling the user chose (no regime tightening
        // in a historical backtest). Omitted for the mu-free objectives.
        ...(backtestObjective === "max_return_cvar" && cvarLimit != null
          ? { cvar_limit: cvarLimit }
          : {}),
      }),
      [result, backtestObjective, constraints, windowDays, cvarLimit],
    );

    const mutation = useMutation({
      mutationFn: (b: WalkForwardRequest) => postBacktestWalkForward(b),
    });

    const firedRef = useRef(false);
    useEffect(() => {
      if (firedRef.current) return;
      firedRef.current = true;
      mutation.mutate(body);
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    return (
      <div className="flex flex-col gap-px">
        <p className="ix-fs m-0 border-l-[3px] border-border-strong bg-surface-2 px-2.5 py-1.5 text-text-secondary">
          Validates the optimization process out-of-sample (re-optimizes each
          fold) — not a replay of these exact weights.
          {downgraded && (
            <>
              {" "}
              Backtest runs without views (Gate G5); objective adjusted to{" "}
              <span className="font-bold text-text-primary">min_cvar</span>.
            </>
          )}
        </p>

        {mutation.isPending || mutation.isIdle ? (
          <TabSkeleton label="Running walk-forward backtest" />
        ) : mutation.isError ? (
          <ErrorPanel
            title="Backtest failed"
            message={mutation.error.message}
            onRetry={() => mutation.mutate(body)}
          />
        ) : (
          <BacktestBody data={mutation.data} colors={colors} />
        )}
      </div>
    );
  }

  function BacktestBody({
    data,
    colors,
  }: {
    data: WalkForwardResponse;
    colors: ChartColors | null;
  }) {
    const [metric, setMetric] = useState<FoldMetricKey>("net_return");

    const foldOption = colors ? buildHcFoldMetricsOption(data.folds, metric, colors) : null;

    // OOS equity curve: reuse the NAV line builder, then merge fold-boundary
    // plotLines onto its xAxis (the builder has no plotLines of its own).
    const oosOption = useMemo(() => {
      if (!colors) return null;
      const base = buildHcNavOption(data.oos_curve, colors);
      const plotLines = data.fold_boundaries.map((date) => ({
        value: dateToUtcMs(date),
        color: colors.barMute,
        width: 1,
        dashStyle: "Dash" as const,
        zIndex: 3,
      }));
      return {
        ...base,
        xAxis: { ...(base.xAxis as object), plotLines },
      };
    }, [data.oos_curve, data.fold_boundaries, colors]);

    return (
      <div className="flex flex-col gap-px">
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
          <KpiTile label="Mean Sharpe" value={formatNumber(data.mean_sharpe)} tone="text-accent" />
          <KpiTile label="Sharpe std" value={formatNumber(data.std_sharpe)} />
          <KpiTile
            label="Positive folds"
            value={`${data.positive_folds} / ${data.params.n_splits_computed}`}
          />
          <KpiTile label="Mean turnover" value={formatPercent(data.mean_turnover)} />
        </div>

        <Card
          title="Per-fold metrics"
          actions={
            <div className="flex items-stretch border border-border-strong">
              {(
                [
                  ["net_return", "Net return"],
                  ["sharpe", "Sharpe"],
                ] as [FoldMetricKey, string][]
              ).map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setMetric(key)}
                  aria-pressed={metric === key}
                  className={`h-[28px] px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors ${
                    metric === key
                      ? "bg-accent text-on-accent"
                      : "bg-field text-text-secondary hover:bg-layer-hover"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        >
          {foldOption ? (
            <HighchartsChart
              options={foldOption}
              className="h-[300px] w-full"
              isEmpty={data.folds.length === 0}
              emptyMessage="No folds computed — not enough history for the splits."
            />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
          )}

          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[640px] border-collapse ix-fs tabular-nums lining-nums">
              <thead>
                <tr className="bg-field">
                  <Th align="left">Fold</Th>
                  <Th align="right">Train</Th>
                  <Th align="right">Obs</Th>
                  <Th align="right">Sharpe</Th>
                  <Th align="right">CVaR 95</Th>
                  <Th align="right">Max DD</Th>
                  <Th align="right">Turnover</Th>
                  <Th align="right">Net return</Th>
                </tr>
              </thead>
              <tbody>
                {data.folds.map((f, i) => (
                  <tr key={f.fold} className={`border-b border-border ${i % 2 === 1 ? "bg-zebra" : ""}`}>
                    <td className="ix-cell px-2.5 first:pl-[var(--ix-pad)] font-bold text-accent">F{f.fold}</td>
                    <td className="ix-cell px-2.5 text-right text-text-secondary">{formatNumber(f.train_size, 0)}</td>
                    <td className="ix-cell px-2.5 text-right text-text-secondary">{formatNumber(f.n_obs, 0)}</td>
                    <td className="ix-cell px-2.5 text-right">{formatNumber(f.sharpe)}</td>
                    <td className="ix-cell px-2.5 text-right">{formatPercent(f.cvar_95)}</td>
                    <td className="ix-cell px-2.5 text-right">{formatPercent(f.max_drawdown)}</td>
                    <td className="ix-cell px-2.5 text-right">{formatPercent(f.turnover)}</td>
                    <td className="ix-cell px-2.5 pr-[var(--ix-pad)] text-right font-bold">
                      {formatPercent(f.net_return, 2, { signed: true })}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>

        <Card title="Out-of-sample equity curve" subtitle="chained net of costs; dashes mark re-optimization">
          {oosOption ? (
            <HighchartsChart
              options={oosOption}
              className="h-[320px] w-full"
              isEmpty={data.oos_curve.length === 0}
              emptyMessage="No out-of-sample curve returned."
            />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
          )}
        </Card>
      </div>
    );
  }

  function Th({ align, children }: { align: "left" | "right"; children?: React.ReactNode }) {
    return (
      <th
        className={`whitespace-nowrap border-b border-b-border-strong px-2.5 py-[9px] ${
          align === "right" ? "text-right" : "text-left"
        } font-semibold text-text-secondary first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)]`}
      >
        {children}
      </th>
    );
  }
  ```
  (The `Th` helper is duplicated from the allocation table; it is tiny and local — acceptable, or extract to `tabShared.tsx` if a reviewer prefers. Keep it local to avoid scope creep.)

- [x] Write `frontend/src/components/builder/BacktestTab.test.tsx` covering loading→success (KPIs, table rows, charts present), the mu-based downgrade note + objective sent as `min_cvar`, metric-toggle re-rendering the column chart, and the 422 error path. FULL code:
  ```tsx
  // @vitest-environment jsdom
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { cleanup, render, screen, waitFor } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { afterEach, describe, expect, it, vi } from "vitest";

  vi.mock("@/components/charts/HighchartsChart", () => ({
    HighchartsChart: () => <div data-testid="highcharts-chart" />,
  }));
  vi.mock("@/lib/api/client", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/lib/api/client")>();
    return { ...actual, postBacktestWalkForward: vi.fn() };
  });

  import * as client from "@/lib/api/client";
  import { BacktestTab } from "./BacktestTab";
  import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
  import type {
    OptimizeResponse,
    WalkForwardResponse,
    BuilderObjective,
  } from "@/lib/api/client";

  const mocked = vi.mocked(client);

  const WEIGHTS = [
    { asset: { kind: "equity", ticker: "SPY" }, weight: 0.6, ticker: "SPY" },
    { asset: { kind: "equity", ticker: "QQQ" }, weight: 0.4, ticker: "QQQ" },
  ] as unknown as OptimizeResponse["weights"];

  function makeResult(): OptimizeResponse {
    return { weights: WEIGHTS } as unknown as OptimizeResponse;
  }

  function makeWalkForward(): WalkForwardResponse {
    return {
      folds: [
        { fold: 1, train_size: 252, n_obs: 63, sharpe: 1.2, cvar_95: -0.02, max_drawdown: -0.05, turnover: 0.1, gross_return: 0.05, net_return: 0.04 },
        { fold: 2, train_size: 315, n_obs: 63, sharpe: 0.8, cvar_95: -0.03, max_drawdown: -0.06, turnover: 0.15, gross_return: 0.03, net_return: 0.02 },
      ],
      params: { objective: "min_cvar", n_obs: 504, n_splits_computed: 2, gap: 2, test_size: 63, min_train_size: 252, cost_bps: 10 },
      mean_sharpe: 1,
      std_sharpe: 0.2,
      positive_folds: 2,
      mean_turnover: 0.12,
      oos_curve: [["2025-06-12", 1], ["2026-06-12", 1.06]],
      fold_boundaries: ["2025-06-12", "2025-12-12"],
    } as unknown as WalkForwardResponse;
  }

  function renderTab(objective: BuilderObjective) {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <BacktestTab
          result={makeResult()}
          objective={objective}
          constraints={{ cap: 0.25, min_weight: null }}
          windowDays={null}
          colors={TEST_COLORS}
        />
      </QueryClientProvider>,
    );
  }

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe("BacktestTab", () => {
    it("fires walk-forward once with the assets/objective/constraints and renders results", async () => {
      mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
      renderTab("min_vol");

      await waitFor(() => expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1));
      const sent = mocked.postBacktestWalkForward.mock.calls[0][0];
      expect(sent.objective).toBe("min_vol");
      expect(sent.assets).toEqual([
        { kind: "equity", ticker: "SPY" },
        { kind: "equity", ticker: "QQQ" },
      ]);
      expect(sent.constraints).toEqual({ cap: 0.25, min_weight: null });

      expect(await screen.findByText("Mean Sharpe")).toBeInTheDocument();
      expect(screen.getByText("2 / 2")).toBeInTheDocument(); // positive folds / n_splits_computed
      expect(screen.getByText("F1")).toBeInTheDocument();
      expect(screen.getByText("F2")).toBeInTheDocument();
    });

    it("downgrades a mu-based objective to min_cvar with a visible note", async () => {
      mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
      renderTab("bl_utility");

      await waitFor(() => expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1));
      expect(mocked.postBacktestWalkForward.mock.calls[0][0].objective).toBe("min_cvar");
      expect(screen.getByText(/objective adjusted to/i)).toBeInTheDocument();
    });

    it("toggling the metric keeps a single fired request (re-render only)", async () => {
      mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
      const user = userEvent.setup();
      renderTab("min_vol");

      expect(await screen.findByRole("button", { name: "Sharpe" })).toBeInTheDocument();
      await user.click(screen.getByRole("button", { name: "Sharpe" }));
      expect(screen.getByRole("button", { name: "Sharpe" })).toHaveAttribute("aria-pressed", "true");
      expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1);
    });

    it("shows the verbatim 422 detail on failure", async () => {
      mocked.postBacktestWalkForward.mockRejectedValue(
        new client.ApiError(422, "insufficient history for 5 folds"),
      );
      renderTab("min_vol");
      expect(await screen.findByText("insufficient history for 5 folds")).toBeInTheDocument();
    });
  });
  ```

- [x] Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/foldMetrics.test.ts src/components/builder/BacktestTab.test.tsx`. Expected: foldMetrics 3 + BacktestTab 4 passing.
- [x] Gate: `cd frontend && pnpm run typecheck && pnpm lint`. Expected exit 0.

---

## Task 6 — `ProjectionTab` (POST /monte-carlo/portfolio) + `buildHcConeOption`

**Files:**
- Create: `frontend/src/lib/charts/hc/cone.ts`
- Create: `frontend/src/components/builder/ProjectionTab.tsx`
- Test: `frontend/src/lib/charts/hc/cone.test.ts`
- Test: `frontend/src/components/builder/ProjectionTab.test.tsx`

**Steps:**

- [x] Create the confidence-cone builder `frontend/src/lib/charts/hc/cone.ts` — three nested `arearange` bands (5-95, 10-90, 25-75) plus a median (`pct_50`) line across horizons, styled after `cumulative.ts`/`nav.ts` (the global theme owns chrome; this sets series, colors, formatting). The x-axis is a category axis of horizon labels (`confidence_bars[].horizon`). FULL code:
  ```ts
  /**
   * Pure option builder: Monte Carlo confidence cone (Highcharts Core).
   *
   * Across the projection horizons, three nested arearange bands — 5–95, 10–90,
   * 25–75 percentiles — washed from faint to stronger accent, plus the median
   * (pct_50) as an accent line. The x-axis is a category axis of horizon labels.
   * Y values are decimal fractions for return/max_drawdown and unitless for
   * sharpe, so the caller passes whether to percent-format. Mirrors the
   * cumulative.ts line-chart style; the Graphite theme owns axis/grid/tooltip
   * chrome. Returns valid Options for empty input.
   */
  import type { Options } from "highcharts";

  import type { ConfidenceBar } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { formatNumber, formatPercent } from "@/lib/format";

  /** Whether the projected statistic is a fraction (percent-format) or unitless. */
  export type ConeUnit = "fraction" | "unitless";

  export function buildHcConeOption(
    bars: ConfidenceBar[],
    unit: ConeUnit,
    colors: ChartColors,
  ): Options {
    const categories = bars.map((b) => b.horizon);
    const fmt = (v: number) =>
      unit === "fraction" ? formatPercent(v, 1, { signed: true }) : formatNumber(v, 2);

    const band = (lo: keyof ConfidenceBar, hi: keyof ConfidenceBar) =>
      bars.map((b) => [b[lo] as number, b[hi] as number]);

    return {
      chart: { type: "arearange" },
      legend: { enabled: true },
      xAxis: { categories, crosshair: true, tickWidth: 0 },
      yAxis: {
        title: { text: undefined },
        labels: {
          formatter() {
            return unit === "fraction"
              ? formatPercent(this.value as number, 0)
              : formatNumber(this.value as number, 1);
          },
        },
      },
      tooltip: {
        shared: true,
        formatter() {
          const points = this.points ?? [];
          const header = (this.x as string) ?? "";
          const rows = points
            .map((pt) => {
              const low = (pt as unknown as { point: { low: number; high: number } }).point;
              if (low && typeof low.low === "number") {
                return `<span style="color:${pt.series.color}">●</span> ${pt.series.name}: <b>${fmt(low.low)}</b> … <b>${fmt(low.high)}</b>`;
              }
              return `<span style="color:${pt.series.color}">●</span> ${pt.series.name}: <b>${fmt(pt.y as number)}</b>`;
            })
            .join("<br/>");
          return `${header}<br/>${rows}`;
        },
      },
      series: [
        {
          type: "arearange",
          name: "5–95%",
          data: band("pct_5", "pct_95"),
          color: colors.accentWash,
          fillOpacity: 1,
          lineWidth: 0,
          marker: { enabled: false },
          zIndex: 0,
        },
        {
          type: "arearange",
          name: "10–90%",
          data: band("pct_10", "pct_90"),
          color: colors.accentWash,
          fillOpacity: 1,
          lineWidth: 0,
          marker: { enabled: false },
          zIndex: 1,
        },
        {
          type: "arearange",
          name: "25–75%",
          data: band("pct_25", "pct_75"),
          color: colors.accentMuted,
          fillOpacity: 0.5,
          lineWidth: 0,
          marker: { enabled: false },
          zIndex: 2,
        },
        {
          type: "line",
          name: "Median",
          data: bars.map((b) => b.pct_50),
          color: colors.accent,
          lineWidth: 2,
          marker: { enabled: true, radius: 3 },
          zIndex: 3,
        },
      ],
    };
  }
  ```
  Note: `arearange` is a Core series type bundled in the Highcharts ESM build the wrapper imports (the wrapper additionally registers heatmap/xrange/annotations; `arearange` ships in core `highcharts.js`). No extra module import is needed.

- [x] Write `frontend/src/lib/charts/hc/cone.test.ts` (node env). FULL code:
  ```ts
  import { describe, expect, it } from "vitest";

  import { buildHcConeOption } from "@/lib/charts/hc/cone";
  import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
  import type { ConfidenceBar } from "@/lib/api/client";
  import { formatPercent } from "@/lib/format";

  const BARS: ConfidenceBar[] = [
    { horizon: "1Y", horizon_days: 252, pct_5: -0.1, pct_10: -0.05, pct_25: 0, pct_50: 0.08, pct_75: 0.16, pct_90: 0.24, pct_95: 0.3, mean: 0.09 },
    { horizon: "5Y", horizon_days: 1260, pct_5: -0.2, pct_10: -0.1, pct_25: 0.1, pct_50: 0.5, pct_75: 0.9, pct_90: 1.3, pct_95: 1.6, mean: 0.55 },
  ];

  describe("buildHcConeOption", () => {
    it("uses horizon labels as categories and four series (3 bands + median)", () => {
      const opt = buildHcConeOption(BARS, "fraction", TEST_COLORS);
      expect((opt.xAxis as { categories?: string[] }).categories).toEqual(["1Y", "5Y"]);
      expect(opt.series).toHaveLength(4);
      const names = (opt.series ?? []).map((s) => (s as { name?: string }).name);
      expect(names).toEqual(["5–95%", "10–90%", "25–75%", "Median"]);
    });

    it("maps band series to [low, high] pairs and the median to scalars", () => {
      const opt = buildHcConeOption(BARS, "fraction", TEST_COLORS);
      const band595 = opt.series?.[0] as { data?: Array<[number, number]> };
      expect(band595.data).toEqual([[-0.1, 0.3], [-0.2, 1.6]]);
      const median = opt.series?.[3] as { data?: number[] };
      expect(median.data).toEqual([0.08, 0.5]);
    });

    it("percent-formats the y-axis for the fraction unit", () => {
      const opt = buildHcConeOption(BARS, "fraction", TEST_COLORS);
      const labels = (opt.yAxis as { labels?: { formatter?: (this: { value: number }) => string } }).labels!;
      expect(labels.formatter!.call({ value: 0.5 })).toBe(formatPercent(0.5, 0));
    });
  });
  ```

- [x] Create `frontend/src/components/builder/ProjectionTab.tsx`. Behavior: a statistic selector (`return`/`max_drawdown`/`sharpe`) drives the request; refetch on change; positions from each weight (`asset` + `weight`); render the cone, the longest-horizon summary (median + 5–95), `historical_percentile_rank`, and the `degraded`/`degraded_reason` note. FULL code:
  ```tsx
  "use client";

  /**
   * Projection tab — forward block-bootstrap Monte Carlo on the proposed
   * portfolio (POST /monte-carlo/portfolio). The statistic selector
   * (return / max drawdown / sharpe) refetches the same portfolio. Renders a
   * confidence cone across horizons, the longest-horizon summary, the
   * historical percentile rank, and any degraded reason. A scenario
   * distribution, not a guarantee.
   */
  import { useMutation } from "@tanstack/react-query";
  import { useEffect, useRef } from "react";

  import {
    postPortfolioMonteCarlo,
    type OptimizeResponse,
    type MonteCarloStatistic,
    type PortfolioMonteCarloRequest,
    type PortfolioMonteCarloResponse,
  } from "@/lib/api/client";
  import type { ChartColors } from "@/lib/charts/chartColors";
  import { buildHcConeOption, type ConeUnit } from "@/lib/charts/hc/cone";
  import { formatNumber, formatPercent } from "@/lib/format";
  import { HighchartsChart } from "@/components/charts/HighchartsChart";
  import { Card, KpiTile } from "@/components/ui/panels";
  import { ErrorPanel } from "@/components/screener/shared";

  import { TabSkeleton } from "./tabShared";

  const STATISTICS: [MonteCarloStatistic, string][] = [
    ["return", "Return"],
    ["max_drawdown", "Max drawdown"],
    ["sharpe", "Sharpe"],
  ];

  function unitFor(statistic: MonteCarloStatistic): ConeUnit {
    return statistic === "sharpe" ? "unitless" : "fraction";
  }

  export function ProjectionTab({
    result,
    colors,
  }: {
    result: OptimizeResponse;
    colors: ChartColors | null;
  }) {
    const mutation = useMutation({
      mutationFn: (body: PortfolioMonteCarloRequest) => postPortfolioMonteCarlo(body),
    });

    const positions = result.weights.map((w) => ({ asset: w.asset, weight: w.weight }));

    const run = (statistic: MonteCarloStatistic) =>
      mutation.mutate({
        positions,
        statistic,
        n_simulations: 10000,
        risk_free_rate: 0.04,
      });

    const firedRef = useRef(false);
    useEffect(() => {
      if (firedRef.current) return;
      firedRef.current = true;
      run("return");
      // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // The active statistic = what was last submitted (params echoes it), else "return".
    const activeStatistic =
      (mutation.variables?.statistic as MonteCarloStatistic | undefined) ?? "return";

    return (
      <div className="flex flex-col gap-px">
        <Card
          title="Forward projection"
          subtitle="block-bootstrap (21-day blocks), target weights held"
          actions={
            <div className="flex items-stretch border border-border-strong">
              {STATISTICS.map(([key, label]) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => run(key)}
                  aria-pressed={activeStatistic === key}
                  disabled={mutation.isPending}
                  className={`h-[28px] px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors disabled:opacity-50 ${
                    activeStatistic === key
                      ? "bg-accent text-on-accent"
                      : "bg-field text-text-secondary hover:bg-layer-hover"
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
          }
        >
          {mutation.isPending || mutation.isIdle ? (
            <TabSkeleton label="Running Monte Carlo projection" />
          ) : mutation.isError ? (
            <ErrorPanel
              title="Projection failed"
              message={mutation.error.message}
              onRetry={() => run(activeStatistic)}
            />
          ) : (
            <ProjectionBody
              data={mutation.data}
              statistic={activeStatistic}
              colors={colors}
            />
          )}
        </Card>
      </div>
    );
  }

  function ProjectionBody({
    data,
    statistic,
    colors,
  }: {
    data: PortfolioMonteCarloResponse;
    statistic: MonteCarloStatistic;
    colors: ChartColors | null;
  }) {
    const unit = unitFor(statistic);
    const coneOption = colors ? buildHcConeOption(data.confidence_bars, unit, colors) : null;
    const fmt = (v: number) =>
      unit === "fraction" ? formatPercent(v, 1, { signed: true }) : formatNumber(v, 2);

    const last = data.confidence_bars[data.confidence_bars.length - 1] ?? null;

    return (
      <div className="flex flex-col gap-3">
        {data.degraded && data.degraded_reason && (
          <p className="ix-fs m-0 border-l-[3px] border-loss bg-surface-2 px-2.5 py-1.5 text-loss">
            {data.degraded_reason}
          </p>
        )}

        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
          {last && (
            <>
              <KpiTile label={`Median @ ${last.horizon}`} value={fmt(last.pct_50)} tone="text-accent" />
              <KpiTile label={`5th–95th @ ${last.horizon}`} value={`${fmt(last.pct_5)} … ${fmt(last.pct_95)}`} />
            </>
          )}
          <KpiTile
            label="Historical rank"
            value={
              data.historical_percentile_rank !== null
                ? `${formatNumber(data.historical_percentile_rank, 0)}th pct`
                : "—"
            }
            detail="where the realized history falls"
          />
        </div>

        {coneOption ? (
          <HighchartsChart
            options={coneOption}
            className="h-[360px] w-full"
            isEmpty={data.confidence_bars.length === 0}
            emptyMessage="No projection horizons returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">Loading theme…</p>
        )}

        <p className="ix-fs m-0 text-text-muted">
          Block-bootstrap projection from the portfolio&apos;s common history with
          target weights held — a distribution of scenarios, not a guarantee.
        </p>
      </div>
    );
  }
  ```
  Note on the selector + refetch: each `run(statistic)` re-fires the same mutation, so the cone updates without changing the cache-by-result contract; `mutation.variables.statistic` is the source of truth for which segment is active (it reflects the in-flight or last request immediately).

- [x] Write `frontend/src/components/builder/ProjectionTab.test.tsx` covering loading→success (cone + summary tiles), statistic switch refetching with the new statistic, the degraded-reason note, and the 422 error path. FULL code:
  ```tsx
  // @vitest-environment jsdom
  import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
  import { cleanup, render, screen, waitFor } from "@testing-library/react";
  import userEvent from "@testing-library/user-event";
  import { afterEach, describe, expect, it, vi } from "vitest";

  vi.mock("@/components/charts/HighchartsChart", () => ({
    HighchartsChart: () => <div data-testid="highcharts-chart" />,
  }));
  vi.mock("@/lib/api/client", async (importOriginal) => {
    const actual = await importOriginal<typeof import("@/lib/api/client")>();
    return { ...actual, postPortfolioMonteCarlo: vi.fn() };
  });

  import * as client from "@/lib/api/client";
  import { ProjectionTab } from "./ProjectionTab";
  import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
  import type {
    OptimizeResponse,
    PortfolioMonteCarloResponse,
  } from "@/lib/api/client";

  const mocked = vi.mocked(client);

  const WEIGHTS = [
    { asset: { kind: "equity", ticker: "SPY" }, weight: 0.6, ticker: "SPY" },
    { asset: { kind: "fund", id: "uuid-1" }, weight: 0.4, ticker: null },
  ] as unknown as OptimizeResponse["weights"];

  function makeResult(): OptimizeResponse {
    return { weights: WEIGHTS } as unknown as OptimizeResponse;
  }

  function makeMonteCarlo(degraded = false): PortfolioMonteCarloResponse {
    return {
      params: {},
      percentiles: {},
      mean: 0.1,
      median: 0.09,
      std: 0.2,
      historical_value: 0.08,
      historical_horizon_days: 252,
      historical_percentile_rank: 62,
      confidence_bars: [
        { horizon: "1Y", horizon_days: 252, pct_5: -0.1, pct_10: -0.05, pct_25: 0, pct_50: 0.08, pct_75: 0.16, pct_90: 0.24, pct_95: 0.3, mean: 0.09 },
        { horizon: "10Y", horizon_days: 2520, pct_5: -0.2, pct_10: -0.1, pct_25: 0.2, pct_50: 1.0, pct_75: 1.8, pct_90: 2.6, pct_95: 3.2, mean: 1.1 },
      ],
      degraded,
      degraded_reason: degraded ? "flat NAV — projection uninformative" : null,
    } as unknown as PortfolioMonteCarloResponse;
  }

  function renderTab() {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    return render(
      <QueryClientProvider client={queryClient}>
        <ProjectionTab result={makeResult()} colors={TEST_COLORS} />
      </QueryClientProvider>,
    );
  }

  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  describe("ProjectionTab", () => {
    it("fires the projection with return + positions and renders the cone and summary", async () => {
      mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo());
      renderTab();

      await waitFor(() => expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(1));
      const sent = mocked.postPortfolioMonteCarlo.mock.calls[0][0];
      expect(sent.statistic).toBe("return");
      expect(sent.positions).toEqual([
        { asset: { kind: "equity", ticker: "SPY" }, weight: 0.6 },
        { asset: { kind: "fund", id: "uuid-1" }, weight: 0.4 },
      ]);

      expect(await screen.findByText("Median @ 10Y")).toBeInTheDocument();
      expect(screen.getByText("Historical rank")).toBeInTheDocument();
      expect(screen.getByTestId("highcharts-chart")).toBeInTheDocument();
    });

    it("switching the statistic refetches with the new statistic", async () => {
      mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo());
      const user = userEvent.setup();
      renderTab();

      await waitFor(() => expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(1));
      await user.click(screen.getByRole("button", { name: "Max drawdown" }));
      await waitFor(() => expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(2));
      expect(mocked.postPortfolioMonteCarlo.mock.calls[1][0].statistic).toBe("max_drawdown");
    });

    it("renders the degraded reason when present", async () => {
      mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo(true));
      renderTab();
      expect(
        await screen.findByText("flat NAV — projection uninformative"),
      ).toBeInTheDocument();
    });

    it("shows the verbatim 422 detail on failure", async () => {
      mocked.postPortfolioMonteCarlo.mockRejectedValue(
        new client.ApiError(422, "insufficient common history"),
      );
      renderTab();
      expect(await screen.findByText("insufficient common history")).toBeInTheDocument();
    });
  });
  ```

- [x] Run: `cd frontend && pnpm exec vitest run src/lib/charts/hc/cone.test.ts src/components/builder/ProjectionTab.test.tsx`. Expected: cone 3 + ProjectionTab 4 passing.
- [x] Gate: `cd frontend && pnpm run typecheck && pnpm lint`. Expected exit 0.

---

## Task 7 — Full-suite verification

**Files:** (none — verification only)

**Steps:**
- [x] Run the full frontend gate: `cd frontend && pnpm lint && pnpm run typecheck`. Expected exit 0, no errors.
- [x] Run the full test suite: `cd frontend && pnpm test`. Expected: all suites pass, including the new `ResultsPanel`, `RiskTab`, `BacktestTab`, `ProjectionTab`, `foldMetrics`, `cone`, and `client.backtestMonteCarlo` suites, with no regressions in the pre-existing `FundProfileView`/`FundUniverseCard`/chart-builder suites.
- [x] Confirm no `TODO`/placeholder text was left: `cd frontend && grep -rnE "TODO|FIXME|placeholder|PLACEHOLDER|\\.\\.\\.$" src/components/builder/AllocationTab.tsx src/components/builder/RiskTab.tsx src/components/builder/BacktestTab.tsx src/components/builder/ProjectionTab.tsx src/components/builder/tabShared.tsx src/lib/charts/hc/foldMetrics.ts src/lib/charts/hc/cone.ts` → no matches (other than the legitimate prose in comments, which the reviewer confirms are not stubs).

---

## Self-Review

**Spec coverage:**
- Tab skeleton in `ResultsPanel` mirroring `FundProfileView` (union `ResultTabId`, `TABS`, `useState`, `role="tab"`/`aria-selected`, same button classes, conditional render) — Task 2. ✓
- `AllocationTab` = verbatim extraction of the current `ResultsPanel` body, no behavior change — Task 2. ✓
- Lazy per-tab fetch via `useMutation`, fired once on first open, reset on new result (via `key={mutation.submittedAt}` remount + per-tab `firedRef`) — Tasks 2, 4, 5, 6. ✓
- Client: `postPortfolioAnalysis` confirmed pre-existing; `postBacktestWalkForward` + `postPortfolioMonteCarlo` + type aliases added mirroring `postBuilderOptimize`/`request<T>` — Task 3. ✓
- `RiskTab`: `/portfolio/analysis` (mode weights, SPY, 1Y), KPI tiles from `stats`, `buildHcRiskContributionsOption`, `buildHcHeatmapOption`, `buildHcCumulativeOption`; fail-loud on unresolved ticker — Task 4. ✓
- `BacktestTab`: `/backtest/walk-forward` (assets from `result.weights.map(w=>w.asset)`, objective+constraints), KPI tiles (mean_sharpe, positive_folds/n_splits_computed, mean_turnover), per-fold table, `buildHcFoldMetricsOption` column chart, OOS curve via `nav.ts` + `plotLines` at `fold_boundaries`; mu-based objective downgraded to `min_cvar` with visible note; views never sent — Task 5. ✓
- `ProjectionTab`: `/monte-carlo/portfolio` (positions from weights), statistic selector (return/max_drawdown/sharpe) refetching, `buildHcConeOption` arearange bands (5-95,10-90,25-75) + median, `historical_percentile_rank`, degraded reason — Task 6. ✓
- New builders `foldMetrics.ts` (vertical columns, styled on `histogram.ts`) and `cone.ts` (arearange + median, styled on `cumulative.ts`) — Tasks 5, 6. ✓
- Regenerate `api.d.ts` first (exact codegen command) — Task 1. ✓
- TDD per task: component tests (loading/error/success with fixtures; tab switching fetches once; reset on new result) + builder unit tests; full code shown — all tasks. ✓

**Placeholder scan:** No `...`/TODO left in shipped code. The single ellipsis marker is in Task 2's instruction "MOVE the entire existing ResultsPanel body here verbatim" (an explicit move directive, not code to ship); Task 7 greps to confirm no stubs remain. ✓

**Type consistency:**
- Tab ids: `ResultTabId = "allocation" | "risk" | "backtest" | "projection"` — used identically in `TABS` and the conditional render (Task 2). ✓
- Builder function names: `buildHcFoldMetricsOption` (foldMetrics.ts), `buildHcConeOption` (cone.ts) — referenced with the exact names in BacktestTab/ProjectionTab and their tests. ✓
- Client function names: `postPortfolioAnalysis` (existing), `postBacktestWalkForward`, `postPortfolioMonteCarlo` — consistent across client.ts, tabs, and tests. ✓
- Response field names verified against the contract + api.d.ts: `stats.{annualized_volatility, sharpe_ratio, sortino_ratio, cvar_95, max_drawdown.depth, diversification_ratio, information_ratio, beta}`; `risk_contributions[].{ticker, contribution}`; `correlation_matrix.{tickers, matrix}`; `benchmark_comparison.{portfolio, benchmark}` (mapped to `buildHcCumulativeOption`'s `{asset, benchmark}` — the one shape adaptation, called out in Task 4); `folds[].{fold, train_size, n_obs, sharpe, cvar_95, max_drawdown, turnover, gross_return, net_return}`; `params.n_splits_computed`; `mean_sharpe/std_sharpe/positive_folds/mean_turnover`; `oos_curve` ([date,number][]), `fold_boundaries` (date[]); `confidence_bars[].{horizon, horizon_days, pct_5..pct_95, pct_50, mean}`; `historical_percentile_rank`, `degraded`, `degraded_reason`. ✓
- `WalkForwardRequest.assets` is `(FundRefIn|EquityRefIn)[]` = `WeightOut.asset` type → `result.weights.map(w=>w.asset)` is type-correct. `objective` downgrade narrows to `WalkForwardRequest["objective"]`. ✓
- `PortfolioMonteCarloRequest.positions[].asset` is `AssetRefIn` = `WeightOut.asset` → `result.weights.map(w=>({asset:w.asset, weight:w.weight}))` is type-correct (covers tickerless funds, per spec). ✓

**Known follow-ups / open questions (also in the reply):**
1. `nav.ts` has **no plotLines parameter** — BacktestTab merges `xAxis.plotLines` onto the builder's returned options rather than changing the builder signature (keeps `nav.ts` reused unchanged, as the spec asks). If the reviewer wants the boundaries inside the builder, that is a small signature change instead.
2. `buildHcCumulativeOption` expects `CumulativeReturns = {asset, benchmark}`, but the analysis response field is `benchmark_comparison.{portfolio, benchmark}` — RiskTab maps `portfolio → asset`. No builder change needed.
3. `ResultsSkeleton` is **local + unexported** in `BuilderView`; this plan adds a `TabSkeleton` in `tabShared.tsx` instead of exporting it (avoids widening `BuilderView`'s surface). Equivalent substitution if a reviewer prefers exporting the original.
4. Package manager: both `package-lock.json` and `pnpm-lock.yaml` exist under `frontend/`, plus a root `pnpm-lock.yaml`; this plan standardizes on **pnpm** per the project gate/memory. If CI actually runs npm, swap `pnpm`→`npm run`/`npx` in every command.
