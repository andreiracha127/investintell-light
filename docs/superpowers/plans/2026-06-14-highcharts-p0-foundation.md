# Highcharts P0 — Foundation (deps + wrappers + Graphite theme) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Install Highcharts and build the reusable foundation — a pure Graphite theme builder, a reference option-builder, and two React wrappers (Core + Stock) mirroring `DataGrid.tsx` — so every later phase can render Highcharts charts that match the design system.

**Architecture:** Twin "dumb" wrappers (`HighchartsChart` Core, `HighchartsStockChart` Stock) dynamically `import()` Highcharts (never SSR), create once into a ref, `update()` on option change, `reflow()` on resize, `destroy()` on unmount. Theming uses **Strategy 2**: the wrapper reads Graphite tokens at runtime via `chartColors()` and applies them globally with `Highcharts.setOptions(highchartsTheme(colors))`; the `AppShell` `key`-remount recomputes on theme switch. Chart content comes from **pure** builders in `src/lib/charts/hc/*` (Vitest-tested, no DOM), exactly like the existing ECharts builders and grid adapters.

**Tech Stack:** Next.js 15.5.19 (App Router, React 19), Highcharts (Core + Stock, one `highcharts` package), TypeScript 5, Vitest 4 (node env, `src/**/*.test.ts`), pnpm.

**Working directory:** all commands run from `E:/investintell-light-highcharts/frontend` (the isolated worktree on branch `feat/highcharts-charts-migration`). Commit on that branch.

**License note:** Highcharts is commercial; the repo already ships `@highcharts/grid-pro` (same vendor), so a license is assumed in place. No license work in this plan.

---

## File Structure

| File | Responsibility |
|---|---|
| `frontend/package.json` | Add `highcharts` dependency. |
| `frontend/src/lib/charts/hc/theme.ts` | **Pure** `highchartsTheme(colors): Highcharts.Options` — the global Graphite theme (palette, transparent bg, square/shadowless, token-bound axes/legend/tooltip, candlestick up/down). |
| `frontend/src/lib/charts/hc/theme.test.ts` | Unit tests for `highchartsTheme`. |
| `frontend/src/lib/charts/hc/__fixtures__/colors.ts` | `TEST_COLORS: ChartColors` fixture (Graphite light values) shared by `hc/*` tests. NOT a test file (not picked up by Vitest). |
| `frontend/src/lib/charts/hc/nav.ts` | **Pure** reference builder `buildHcNavOption(nav, colors): Highcharts.Options` — NAV line; the template the 16 other builders follow in P1. |
| `frontend/src/lib/charts/hc/nav.test.ts` | Unit tests for `buildHcNavOption`. |
| `frontend/src/components/charts/HighchartsChart.tsx` | Core wrapper (`Highcharts.chart`). |
| `frontend/src/components/charts/HighchartsStockChart.tsx` | Stock wrapper (`Highcharts.stockChart`). |

No existing files are modified in P0 (the wrappers/builders are additive; consumers are swapped in P1+). `echarts`/`ixchart` removal is P8.

---

## Task 1: Install Highcharts and verify import shape

**Files:**
- Modify: `frontend/package.json` (via package manager)

- [ ] **Step 1: Install the package**

Run (from `frontend/`):
```bash
pnpm add highcharts
```
Expected: `package.json` gains `"highcharts": "^12.x"` under `dependencies`; `pnpm-lock.yaml` updated.

- [ ] **Step 2: Verify both constructors are reachable**

Run (from `frontend/`):
```bash
node -e "const H=require('highcharts'); const S=require('highcharts/highstock'); console.log(typeof H.chart, typeof S.stockChart)"
```
Expected: `function function`.

If it prints `undefined` for either: the installed major changed the entry shape — check the Highcharts ESM docs (Context7 `resolve-library-id` → `highcharts`, topic "es modules") and adjust the import specifier used in Tasks 4–5 (e.g. `import Highcharts from "highcharts"` + `import "highcharts/modules/stock"`). Do not proceed until both constructors resolve.

- [ ] **Step 3: Commit**

```bash
git add package.json pnpm-lock.yaml
git commit -m "build(charts): add highcharts (core + stock) dependency"
```

---

## Task 2: Graphite theme builder (`hc/theme.ts`)

**Files:**
- Create: `frontend/src/lib/charts/hc/__fixtures__/colors.ts`
- Create: `frontend/src/lib/charts/hc/theme.test.ts`
- Create: `frontend/src/lib/charts/hc/theme.ts`

- [ ] **Step 1: Create the shared color fixture**

Create `frontend/src/lib/charts/hc/__fixtures__/colors.ts`:
```ts
import type { ChartColors } from "@/lib/charts/theme";

/** Graphite light-theme token values, for pure-builder unit tests. */
export const TEST_COLORS: ChartColors = {
  gain: "#198038",
  loss: "#a2191f",
  accent: "#7a1c24",
  accentMuted: "#6a181f",
  text: "#161616",
  textSecondary: "#525252",
  textMuted: "#6f6f6f",
  grid: "#ececec",
  surface: "#ffffff",
  accentWash: "#f4eaeb",
  textOnAccent: "#ffffff",
  bar: "#2b2f36",
  barMute: "#c4c8cf",
  categories: [
    "#7a1c24",
    "#2b2f36",
    "#565b63",
    "#7f858d",
    "#c4c8cf",
    "#d8dbe0",
    "#a08184",
    "#4d5560",
  ],
};
```

- [ ] **Step 2: Write the failing test**

Create `frontend/src/lib/charts/hc/theme.test.ts`:
```ts
import { describe, expect, it } from "vitest";

import { highchartsTheme } from "@/lib/charts/hc/theme";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";

describe("highchartsTheme", () => {
  it("uses the categorical palette as the series colors", () => {
    expect(highchartsTheme(TEST_COLORS).colors).toEqual(TEST_COLORS.categories);
  });

  it("renders a transparent, square, shadowless chart and tooltip", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.chart?.backgroundColor).toBe("transparent");
    expect(t.chart?.borderRadius).toBe(0);
    expect(t.tooltip?.shadow).toBe(false);
    expect(t.tooltip?.backgroundColor).toBe(TEST_COLORS.surface);
  });

  it("binds axis gridlines and labels to graphite tokens", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect((t.xAxis as { gridLineColor?: string }).gridLineColor).toBe(TEST_COLORS.grid);
    expect(
      (t.yAxis as { labels?: { style?: { color?: string } } }).labels?.style?.color,
    ).toBe(TEST_COLORS.textMuted);
  });

  it("maps candlestick up/down to gain/loss", () => {
    const t = highchartsTheme(TEST_COLORS);
    expect(t.plotOptions?.candlestick?.upColor).toBe(TEST_COLORS.gain);
    expect(t.plotOptions?.candlestick?.color).toBe(TEST_COLORS.loss);
  });

  it("disables credits", () => {
    expect(highchartsTheme(TEST_COLORS).credits?.enabled).toBe(false);
  });
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run (from `frontend/`):
```bash
npx vitest run src/lib/charts/hc/theme.test.ts
```
Expected: FAIL — cannot resolve `@/lib/charts/hc/theme` (module does not exist yet).

- [ ] **Step 4: Implement the theme builder**

Create `frontend/src/lib/charts/hc/theme.ts`:
```ts
/**
 * Pure Graphite theme for Highcharts. Returns a base `Options` applied globally
 * via `Highcharts.setOptions(...)` by the chart wrappers. Token-driven (takes a
 * ChartColors bag read from CSS custom properties) so light/dark/accent switches
 * flow through the AppShell key-remount, exactly like the ECharts builders.
 *
 * Pure: no DOM access — safe to unit test in node.
 */
import type { Options } from "highcharts";

import type { ChartColors } from "@/lib/charts/theme";

const SANS = 'Arial, "Arimo", "Helvetica Neue", ui-sans-serif, sans-serif';

export function highchartsTheme(colors: ChartColors): Options {
  const axis = {
    gridLineColor: colors.grid,
    lineColor: colors.grid,
    tickColor: colors.grid,
    labels: { style: { color: colors.textMuted, fontVariantNumeric: "tabular-nums" } },
    title: { style: { color: colors.textSecondary } },
  };
  return {
    colors: [...colors.categories],
    chart: {
      backgroundColor: "transparent",
      borderRadius: 0,
      animation: false,
      style: { fontFamily: SANS },
    },
    title: { style: { color: colors.text } },
    subtitle: { style: { color: colors.textSecondary } },
    xAxis: axis,
    yAxis: axis,
    legend: {
      itemStyle: { color: colors.text },
      itemHoverStyle: { color: colors.accent },
      itemHiddenStyle: { color: colors.textMuted },
    },
    tooltip: {
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      borderRadius: 0,
      shadow: false,
      style: { color: colors.text },
    },
    plotOptions: {
      series: { animation: false, borderRadius: 0 },
      candlestick: {
        color: colors.loss,
        upColor: colors.gain,
        lineColor: colors.loss,
        upLineColor: colors.gain,
      },
    },
    credits: { enabled: false },
  };
}
```

Note: `fontVariantNumeric` is passed through Highcharts' permissive `CSSObject` index signature onto the SVG text style — accepted by the types. If `tsc` rejects it on the installed major, wrap that `style` object with `as Highcharts.CSSObject`.

- [ ] **Step 5: Run the test to verify it passes**

Run (from `frontend/`):
```bash
npx vitest run src/lib/charts/hc/theme.test.ts
```
Expected: PASS (5 tests).

- [ ] **Step 6: Commit**

```bash
git add src/lib/charts/hc/theme.ts src/lib/charts/hc/theme.test.ts src/lib/charts/hc/__fixtures__/colors.ts
git commit -m "feat(charts): add Graphite Highcharts theme builder"
```

---

## Task 3: Reference builder (`hc/nav.ts`)

Ports `src/lib/charts/nav.ts` (`buildNavOption`, ECharts) to Highcharts. This is the canonical pattern the 16 remaining builders follow in P1: pure, takes `(data, colors)`, returns `Highcharts.Options`, sets only chart-specific bits (series color, value formatting) and lets the global theme own axes/grid/tooltip chrome.

**Files:**
- Create: `frontend/src/lib/charts/hc/nav.test.ts`
- Create: `frontend/src/lib/charts/hc/nav.ts`

- [ ] **Step 1: Write the failing test**

Create `frontend/src/lib/charts/hc/nav.test.ts`:
```ts
import { describe, expect, it } from "vitest";

import { buildHcNavOption } from "@/lib/charts/hc/nav";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { SeriesPoint } from "@/lib/api/client";

const NAV: SeriesPoint[] = [
  ["2024-01-01", 100],
  ["2024-01-02", 101.5],
];

describe("buildHcNavOption", () => {
  it("maps SeriesPoint dates to x categories and values to series data", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    expect((opt.xAxis as { categories?: string[] }).categories).toEqual([
      "2024-01-01",
      "2024-01-02",
    ]);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([100, 101.5]);
  });

  it("colors the NAV line with the accent token", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    const series = opt.series?.[0] as { color?: string; type?: string };
    expect(series.type).toBe("line");
    expect(series.color).toBe(TEST_COLORS.accent);
  });

  it("renders an empty series for empty input", () => {
    const opt = buildHcNavOption([], TEST_COLORS);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([]);
  });
});
```

- [ ] **Step 2: Run the test to verify it fails**

Run (from `frontend/`):
```bash
npx vitest run src/lib/charts/hc/nav.test.ts
```
Expected: FAIL — cannot resolve `@/lib/charts/hc/nav`.

- [ ] **Step 3: Implement the builder**

Create `frontend/src/lib/charts/hc/nav.ts`:
```ts
/**
 * Pure option builder: NAV line in currency units (Highcharts Core).
 * Reference template for the ECharts -> Highcharts builder migration (P1):
 * the global Graphite theme owns axis/grid/tooltip chrome; the builder sets
 * only the series, the accent color, and currency value formatting.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCurrency } from "@/lib/format";

export function buildHcNavOption(
  nav: SeriesPoint[],
  colors: ChartColors,
): Options {
  return {
    chart: { type: "line" },
    legend: { enabled: false },
    xAxis: {
      categories: nav.map((point) => point[0]),
      crosshair: true,
      tickWidth: 0,
    },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return formatCurrency(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        return `${this.x}<br/><b>${formatCurrency(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "line",
        name: "NAV",
        data: nav.map((point) => point[1]),
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
      },
    ],
  };
}
```

- [ ] **Step 4: Run the test to verify it passes**

Run (from `frontend/`):
```bash
npx vitest run src/lib/charts/hc/nav.test.ts
```
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/lib/charts/hc/nav.ts src/lib/charts/hc/nav.test.ts
git commit -m "feat(charts): add Highcharts NAV reference builder"
```

---

## Task 4: Core wrapper (`HighchartsChart.tsx`)

No unit test (the repo has no component/DOM tests — Vitest only runs `src/**/*.test.ts` in node; `EChart.tsx`/`DataGrid.tsx` are likewise untested and verified by typecheck + visual check). Verification = `tsc --noEmit` + `eslint`.

**Files:**
- Create: `frontend/src/components/charts/HighchartsChart.tsx`

- [ ] **Step 1: Implement the wrapper**

Create `frontend/src/components/charts/HighchartsChart.tsx`:
```tsx
"use client";

/**
 * Thin Highcharts Core wrapper: dynamically import highcharts (never SSR),
 * apply the Graphite theme globally, create the chart once into a ref,
 * update() on option change, reflow() on resize, destroy() on unmount.
 * Mirrors DataGrid.tsx. Chart content comes from pure builders in
 * `src/lib/charts/hc/*`.
 */
import { useEffect, useRef } from "react";
import type { Chart, Options } from "highcharts";

import { chartColors } from "@/lib/charts/theme";
import { highchartsTheme } from "@/lib/charts/hc/theme";

export function HighchartsChart({
  options,
  className,
  emptyMessage,
  isEmpty,
  onReady,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
  /** Consumer-decided empty state (Highcharts has no generic row count). */
  isEmpty?: boolean;
  onReady?: (chart: Chart) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  // Freshest options/callback for the async create, without re-running it.
  const latestOptions = useRef(options);
  latestOptions.current = options;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void import("highcharts").then((mod) => {
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      // Apply the token-driven Graphite theme globally before creating.
      Highcharts.setOptions(highchartsTheme(chartColors()));
      const chart = Highcharts.chart(containerRef.current, latestOptions.current);
      if (disposed) {
        chart.destroy();
        return;
      }
      chartRef.current = chart;
      onReadyRef.current?.(chart);
    });
    const observer = new ResizeObserver(() => chartRef.current?.reflow());
    observer.observe(el);
    return () => {
      disposed = true;
      observer.disconnect();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    // redraw + oneToOne: replace series/axes rather than merge-append.
    chart.update(options, true, true);
    onReadyRef.current?.(chart);
  }, [options]);

  const showEmpty = !!emptyMessage && !!isEmpty;

  return (
    <div className={`relative ${className ?? ""}`}>
      <div ref={containerRef} className="h-full w-full" />
      {showEmpty && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[13px] text-text-muted">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck and lint**

Run (from `frontend/`):
```bash
pnpm typecheck && pnpm lint
```
Expected: PASS (0 errors). If `mod.default` is typed as `unknown`/missing, change to `const Highcharts = mod.default ?? mod;` or `import * as Highcharts from "highcharts"` per the Task 1 Step 2 resolution.

- [ ] **Step 3: Commit**

```bash
git add src/components/charts/HighchartsChart.tsx
git commit -m "feat(charts): add HighchartsChart Core wrapper"
```

---

## Task 5: Stock wrapper (`HighchartsStockChart.tsx`)

Same lifecycle as Task 4, but imports the Stock bundle and uses `stockChart`. Modules (annotations, indicators) are added in P2 where needed — P0 ships the minimal Stock instance.

**Files:**
- Create: `frontend/src/components/charts/HighchartsStockChart.tsx`

- [ ] **Step 1: Implement the wrapper**

Create `frontend/src/components/charts/HighchartsStockChart.tsx`:
```tsx
"use client";

/**
 * Thin Highcharts Stock wrapper: dynamically import highcharts/highstock
 * (never SSR), apply the Graphite theme globally, create a stockChart once,
 * update() on option change, reflow() on resize, destroy() on unmount.
 * `onReady` exposes the live Chart so consumers can stream live ticks via
 * `chart.series[i].addPoint(...)` (P2). Mirrors HighchartsChart.
 */
import { useEffect, useRef } from "react";
import type { Chart, Options } from "highcharts";

import { chartColors } from "@/lib/charts/theme";
import { highchartsTheme } from "@/lib/charts/hc/theme";

export function HighchartsStockChart({
  options,
  className,
  emptyMessage,
  isEmpty,
  onReady,
}: {
  options: Options;
  className?: string;
  emptyMessage?: string;
  isEmpty?: boolean;
  onReady?: (chart: Chart) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<Chart | null>(null);
  const latestOptions = useRef(options);
  latestOptions.current = options;
  const onReadyRef = useRef(onReady);
  onReadyRef.current = onReady;

  useEffect(() => {
    let disposed = false;
    const el = containerRef.current;
    if (!el) return;
    void import("highcharts/highstock").then((mod) => {
      if (disposed || !containerRef.current) return;
      const Highcharts = mod.default;
      Highcharts.setOptions(highchartsTheme(chartColors()));
      const chart = Highcharts.stockChart(containerRef.current, latestOptions.current);
      if (disposed) {
        chart.destroy();
        return;
      }
      chartRef.current = chart;
      onReadyRef.current?.(chart);
    });
    const observer = new ResizeObserver(() => chartRef.current?.reflow());
    observer.observe(el);
    return () => {
      disposed = true;
      observer.disconnect();
      chartRef.current?.destroy();
      chartRef.current = null;
    };
  }, []);

  useEffect(() => {
    const chart = chartRef.current;
    if (!chart) return;
    chart.update(options, true, true);
    onReadyRef.current?.(chart);
  }, [options]);

  const showEmpty = !!emptyMessage && !!isEmpty;

  return (
    <div className={`relative ${className ?? ""}`}>
      <div ref={containerRef} className="h-full w-full" />
      {showEmpty && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center px-4 text-center text-[13px] text-text-muted">
          {emptyMessage}
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 2: Typecheck and lint**

Run (from `frontend/`):
```bash
pnpm typecheck && pnpm lint
```
Expected: PASS (0 errors). If `highcharts/highstock` has no type declarations on the installed major, fall back to `import("highcharts").then(...)` + register stock: `import("highcharts/modules/stock").then((m) => m.default(Highcharts))` before `Highcharts.stockChart` (per Task 1 Step 2 resolution).

- [ ] **Step 3: Commit**

```bash
git add src/components/charts/HighchartsStockChart.tsx
git commit -m "feat(charts): add HighchartsStockChart Stock wrapper"
```

---

## Task 6: Full P0 gate

**Files:** none (verification only).

- [ ] **Step 1: Run the full frontend gate**

Run (from `frontend/`):
```bash
pnpm lint && pnpm typecheck && pnpm test
```
Expected: lint 0 errors; typecheck 0 errors; Vitest all pass — the new `hc/theme.test.ts` (5) and `hc/nav.test.ts` (3) green, and **no regression** in the existing suite (the pre-existing `statistics` failures are unrelated and out of scope — confirm the count did not grow).

- [ ] **Step 2: Confirm clean tree**

Run (from `frontend/`):
```bash
git status --short
```
Expected: empty (everything committed across Tasks 1–5).

- [ ] **Step 3: (Optional) production build smoke**

Run (from `frontend/`):
```bash
pnpm build
```
Expected: build succeeds. Skip if time-constrained — lint+typecheck+test is the required gate. If the dynamic `import("highcharts")` triggers an SSR evaluation error, confirm both wrappers carry `"use client"` and the import lives inside `useEffect` (it does).

---

## Self-Review

**Spec coverage (against §4.1 / §8-P0 of the design):**
- Install `highcharts` (Core+Stock, one package) → Task 1. ✅
- `HighchartsChart` Core wrapper (dynamic import, race-guard, create-once, `update()`, `ResizeObserver→reflow`, `destroy`) → Task 4. ✅
- `HighchartsStockChart` Stock wrapper + `onReady` for live `addPoint` → Task 5. ✅
- `highchartsTheme.ts` (palette, transparent, square, no shadow, hairline, tabular-nums, token-bound, candlestick up/down) → Task 2. ✅
- Strategy-2 theme bridge (read `chartColors()` + `setOptions`, rely on AppShell remount) → Tasks 4/5. ✅
- Pure, Vitest-tested builders pattern established → Tasks 2/3. ✅
- Baseline green / no regression → Task 6. ✅
- Builder migration of the other 16, ixchart retirement, backend, caching, dossier → deferred to P1–P8 (out of P0 scope by design). ✅

**Placeholder scan:** No TBD/TODO; every code/command step shows full content. The Task 1/4/5 fallback notes are conditional remediations (concrete alternative code given), not placeholders.

**Type consistency:** `highchartsTheme(colors: ChartColors): Options` defined in Task 2, consumed identically in Tasks 4/5. `buildHcNavOption(nav: SeriesPoint[], colors: ChartColors): Options` consistent between Task 3 impl and test. `ChartColors` fields used (`grid`, `textMuted`, `surface`, `gain`, `loss`, `accent`, `categories`) all exist in `src/lib/charts/theme.ts`. Wrapper prop names (`options`, `className`, `emptyMessage`, `isEmpty`, `onReady`) consistent across both wrappers. `SeriesPoint = [string, number]` matches usage (`point[0]` date, `point[1]` value).

---

## Next Phases (own plans, written when reached)

P1 port the remaining 16 builders → `hc/*` + swap consumers · P2 ixchart → Highcharts Stock (price/live/drawing) · P3 `/timeseries` CAGG wiring + 730 removal · P4 backend Tier A + dossier shell · P5 backend Tier B + tabs/modals · P6 caching · P7 Tier C (13F + Form 4) · P8 remove echarts/ixchart + contract regen.
