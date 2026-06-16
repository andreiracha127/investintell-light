# Highcharts P2 Price Stock Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the canvas `InteractiveChart` price chart with Highcharts Stock while preserving price, NAV, indicators, range sync, live ticks, and adding multi-symbol compare.

**Architecture:** Keep `InteractiveChart` as the app-facing orchestrator, move all pure option construction into `frontend/src/lib/charts/hc/priceStock.ts`, and use Highcharts Stock native behavior for data grouping and stock-tools drawings. Keep the old `frontend/src/lib/ixchart/*` files in place for P8 cleanup, but do not import the canvas engine from the migrated chart.

**Tech Stack:** Next.js 15 App Router, React 19, TypeScript, TanStack Query v5, Highcharts v13 Stock ESM, Vitest pure `.test.ts` tests, existing Graphite chart tokens.

---

## Execution Preflight

Do this before Task 1 during the execution phase:

- Use `superpowers:using-git-worktrees`.
- Create an isolated worktree off `main`, for example `E:/investintell-light-highcharts-p2` on branch `feat/highcharts-p2-price`.
- Do not use `E:/investintell-light-highcharts`.
- If `frontend/node_modules` is missing in the new worktree, run:

```powershell
cd E:\investintell-light-highcharts-p2\frontend
pnpm install
```

Expected: dependencies link successfully from the local pnpm store or install normally.

---

## File Structure

- Create `frontend/src/lib/charts/hc/priceStock.ts`  
  Pure Highcharts Stock option builder, chart constants, compare helpers, range helpers, and data-shape conversion. No DOM, no React, no WebSocket.

- Create `frontend/src/lib/charts/hc/priceStock.test.ts`  
  Pure Vitest coverage for series mapping, data grouping, indicators, axes, log/percent, compare dedupe, and range preset inference.

- Create `frontend/src/lib/charts/hc/priceStockLive.ts`  
  Live tick merge and chart update helpers. Pure merge logic is testable; chart mutation helper is small and isolated.

- Create `frontend/src/lib/charts/hc/priceStockLive.test.ts`  
  Pure tests for same-day tick updates, new-day appends, OHLC/volume mutation, and empty input.

- Modify `frontend/src/components/charts/HighchartsStockChart.tsx`  
  Switch from `highcharts/highstock` UMD-ish entrypoint to `highcharts/esm/highstock.js`; register Stock modules via ESM before chart creation.

- Modify `frontend/src/app/layout.tsx`  
  Import Highcharts stock-tools and annotations CSS globally, because Next only accepts global CSS through app/root layout.

- Modify `frontend/src/components/charts/SymbolSearchInput.tsx`  
  Make `active` and `onClear` optional so the input can act as an additive compare picker while chips live in `InteractiveChart`.

- Replace `frontend/src/components/charts/InteractiveChart.tsx`  
  Remove canvas engine usage. Render `HighchartsStockChart`, use the pure builder, use `useQueries` for multiple compare histories, wire live ticks through `priceStockLive.ts`, and keep the public props stable.

- Consumers remain unchanged unless typecheck proves a necessary narrow adjustment:
  `frontend/src/components/stocks/StockAnalysisView.tsx` and `frontend/src/components/funds/FundProfileView.tsx`.

---

### Task 1: Pure Price Stock Builder

**Files:**
- Create: `frontend/src/lib/charts/hc/priceStock.ts`
- Create: `frontend/src/lib/charts/hc/priceStock.test.ts`

- [ ] **Step 1: Write the failing builder tests**

Create `frontend/src/lib/charts/hc/priceStock.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";

import {
  MAX_COMPARE_SERIES,
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  addCompareSelection,
  buildHcPriceStockOption,
  compareSelectionKey,
  dataGroupingForPeriod,
  rangePresetFromExtremes,
  removeCompareSelection,
  toMainSeriesData,
  toVolumeSeriesData,
  type PriceBar,
  type PriceCompareSelection,
} from "@/lib/charts/hc/priceStock";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";

const BARS: PriceBar[] = [
  { t: Date.UTC(2024, 0, 2), o: 100, h: 110, l: 95, c: 108, v: 1000 },
  { t: Date.UTC(2024, 0, 3), o: 108, h: 112, l: 101, c: 104, v: 1200 },
  { t: Date.UTC(2024, 0, 4), o: 104, h: 109, l: 99, c: 107, v: 900 },
];

const COMPARE: PriceCompareSelection = {
  key: "stock:MSFT:",
  symbol: "MSFT",
  label: "MSFT",
  kind: "stock",
  instrumentId: null,
};

describe("priceStock data conversion", () => {
  it("maps OHLC bars to candlestick data", () => {
    expect(toMainSeriesData(BARS, "candles")).toEqual([
      [BARS[0].t, 100, 110, 95, 108],
      [BARS[1].t, 108, 112, 101, 104],
      [BARS[2].t, 104, 109, 99, 107],
    ]);
  });

  it("maps line and area data to close values", () => {
    expect(toMainSeriesData(BARS, "line")).toEqual([
      [BARS[0].t, 108],
      [BARS[1].t, 104],
      [BARS[2].t, 107],
    ]);
    expect(toMainSeriesData(BARS, "area")).toEqual([
      [BARS[0].t, 108],
      [BARS[1].t, 104],
      [BARS[2].t, 107],
    ]);
  });

  it("maps volume data to [time, volume]", () => {
    expect(toVolumeSeriesData(BARS)).toEqual([
      [BARS[0].t, 1000],
      [BARS[1].t, 1200],
      [BARS[2].t, 900],
    ]);
  });
});

describe("priceStock option builder", () => {
  it("builds a candlestick stock chart with price and volume series", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "candles",
      period: "D",
      range: "1Y",
      overlays: { sma20: true, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ id?: string; type?: string; linkedTo?: string }>;
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "candlestick" });
    expect(series.some((s) => s.id === VOLUME_SERIES_ID && s.type === "column")).toBe(true);
    expect(series.some((s) => s.type === "sma" && s.linkedTo === PRICE_SERIES_ID)).toBe(true);
  });

  it("omits volume and OHLC-only series for NAV mode", () => {
    const opt = buildHcPriceStockOption({
      symbol: "FUNDX",
      bars: BARS,
      mode: "nav",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: true, sma50: false },
      panes: { volume: true, rsi: false },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ id?: string; type?: string }>;
    expect(series[0]).toMatchObject({ id: PRICE_SERIES_ID, type: "line" });
    expect(series.some((s) => s.id === VOLUME_SERIES_ID)).toBe(false);
  });

  it("adds RSI on a dedicated axis when enabled", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: true },
      scale: { log: false, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const series = opt.series as Array<{ type?: string; yAxis?: string }>;
    const axes = opt.yAxis as Array<{ id?: string }>;
    expect(series.some((s) => s.type === "rsi" && s.yAxis === "rsi-axis")).toBe(true);
    expect(axes.some((axis) => axis.id === "rsi-axis")).toBe(true);
  });

  it("uses logarithmic price axis only when log is active", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: true, pct: false },
      compares: [],
      compareData: {},
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const axes = opt.yAxis as Array<{ id?: string; type?: string }>;
    expect(axes.find((axis) => axis.id === "price-axis")?.type).toBe("logarithmic");
  });

  it("sets native percent compare when percent scale is active", () => {
    const opt = buildHcPriceStockOption({
      symbol: "AAPL",
      bars: BARS,
      mode: "ohlcv",
      type: "line",
      period: "D",
      range: "1Y",
      overlays: { sma20: false, sma50: false },
      panes: { volume: false, rsi: false },
      scale: { log: false, pct: true },
      compares: [COMPARE],
      compareData: { [COMPARE.key]: BARS },
      colors: TEST_COLORS,
      onVisibleRangeChange: vi.fn(),
    });
    const plotOptions = opt.plotOptions as { series?: { compare?: string } };
    const series = opt.series as Array<{ id?: string; type?: string; name?: string }>;
    expect(plotOptions.series?.compare).toBe("percent");
    expect(series.some((s) => s.id === "compare-stock:MSFT:" && s.name === "MSFT")).toBe(true);
  });

  it("selects native data grouping by period", () => {
    expect(dataGroupingForPeriod("D")).toMatchObject({ forced: false });
    expect(dataGroupingForPeriod("W")).toMatchObject({
      forced: true,
      units: [["week", [1]]],
    });
    expect(dataGroupingForPeriod("M")).toMatchObject({
      forced: true,
      units: [["month", [1]]],
    });
  });
});

describe("priceStock compare helpers", () => {
  it("dedupes compare selections and caps at MAX_COMPARE_SERIES", () => {
    const first = addCompareSelection([], {
      symbol: "MSFT",
      name: null,
      kind: "stock",
      instrument_id: null,
    });
    expect(first).toHaveLength(1);
    expect(addCompareSelection(first, {
      symbol: "MSFT",
      name: null,
      kind: "stock",
      instrument_id: null,
    })).toHaveLength(1);

    let many = first;
    for (let i = 0; i < MAX_COMPARE_SERIES + 3; i += 1) {
      many = addCompareSelection(many, {
        symbol: `T${i}`,
        name: null,
        kind: "stock",
        instrument_id: null,
      });
    }
    expect(many).toHaveLength(MAX_COMPARE_SERIES);
  });

  it("removes compare selections by stable key", () => {
    const selection = {
      symbol: "VFIAX",
      name: "Vanguard 500 Index",
      kind: "mutual_fund",
      instrument_id: "fund-1",
    } as const;
    const key = compareSelectionKey(selection);
    const next = addCompareSelection([], selection);
    expect(removeCompareSelection(next, key)).toEqual([]);
  });
});

describe("priceStock range helper", () => {
  it("returns MAX when the visible range covers almost the full data span", () => {
    expect(rangePresetFromExtremes(0, 950, 0, 1000)).toBe("MAX");
  });

  it("returns the nearest calendar preset for partial windows", () => {
    const day = 86_400_000;
    expect(rangePresetFromExtremes(0, 29 * day, 0, 1000 * day)).toBe("1M");
    expect(rangePresetFromExtremes(0, 185 * day, 0, 1000 * day)).toBe("6M");
    expect(rangePresetFromExtremes(0, 370 * day, 0, 2000 * day)).toBe("1Y");
    expect(rangePresetFromExtremes(0, 1800 * day, 0, 4000 * day)).toBe("5Y");
  });
});
```

- [ ] **Step 2: Run the builder tests to verify they fail**

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStock.test.ts
```

Expected: FAIL because `@/lib/charts/hc/priceStock` does not exist.

- [ ] **Step 3: Implement the pure builder**

Create `frontend/src/lib/charts/hc/priceStock.ts`:

```ts
import type { Options, SeriesOptionsType } from "highcharts";

import type { RangePreset, SymbolSearchResult } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";

export type PriceChartType = "candles" | "ohlc" | "line" | "area";
export type PricePeriod = "D" | "W" | "M";
export type PriceMode = "ohlcv" | "nav";

export interface PriceBar {
  t: number;
  o: number;
  h: number;
  l: number;
  c: number;
  v: number;
}

export interface PriceCompareSelection {
  key: string;
  symbol: string;
  label: string;
  kind: SymbolSearchResult["kind"];
  instrumentId: string | null;
}

export interface PriceStockOptionsInput {
  symbol: string;
  bars: PriceBar[];
  mode: PriceMode;
  type: PriceChartType;
  period: PricePeriod;
  range: RangePreset;
  overlays: { sma20: boolean; sma50: boolean };
  panes: { volume: boolean; rsi: boolean };
  scale: { log: boolean; pct: boolean };
  compares: PriceCompareSelection[];
  compareData: Record<string, PriceBar[]>;
  colors: ChartColors;
  onVisibleRangeChange?: (next: RangePreset) => void;
}

export const PRICE_SERIES_ID = "price-main";
export const VOLUME_SERIES_ID = "price-volume";
export const MAX_COMPARE_SERIES = 5;

const RANGE_MS: Record<Exclude<RangePreset, "MAX">, number> = {
  "1M": 30 * 86_400_000,
  "6M": 183 * 86_400_000,
  "1Y": 365 * 86_400_000,
  "5Y": 365 * 5 * 86_400_000,
};

export function toMainSeriesData(
  bars: PriceBar[],
  type: PriceChartType,
): Array<[number, number] | [number, number, number, number, number]> {
  if (type === "candles" || type === "ohlc") {
    return bars.map((bar) => [bar.t, bar.o, bar.h, bar.l, bar.c]);
  }
  return bars.map((bar) => [bar.t, bar.c]);
}

export function toVolumeSeriesData(bars: PriceBar[]): Array<[number, number]> {
  return bars.map((bar) => [bar.t, bar.v]);
}

export function dataGroupingForPeriod(period: PricePeriod) {
  if (period === "W") {
    return { enabled: true, forced: true, units: [["week", [1]]] };
  }
  if (period === "M") {
    return { enabled: true, forced: true, units: [["month", [1]]] };
  }
  return {
    enabled: true,
    forced: false,
    units: [
      ["day", [1]],
      ["week", [1]],
      ["month", [1]],
    ],
  };
}

export function compareSelectionKey(
  item: Pick<SymbolSearchResult, "kind" | "symbol" | "instrument_id">,
): string {
  return `${item.kind}:${item.symbol.toUpperCase()}:${item.instrument_id ?? ""}`;
}

export function toCompareSelection(item: SymbolSearchResult): PriceCompareSelection {
  return {
    key: compareSelectionKey(item),
    symbol: item.symbol.toUpperCase(),
    label: item.symbol.toUpperCase(),
    kind: item.kind,
    instrumentId: item.instrument_id,
  };
}

export function addCompareSelection(
  current: PriceCompareSelection[],
  item: SymbolSearchResult,
): PriceCompareSelection[] {
  const next = toCompareSelection(item);
  if (current.some((entry) => entry.key === next.key)) return current;
  if (current.length >= MAX_COMPARE_SERIES) return current;
  return [...current, next];
}

export function removeCompareSelection(
  current: PriceCompareSelection[],
  key: string,
): PriceCompareSelection[] {
  return current.filter((entry) => entry.key !== key);
}

export function rangePresetFromExtremes(
  min: number,
  max: number,
  dataMin: number,
  dataMax: number,
): RangePreset {
  const visible = Math.max(0, max - min);
  const total = Math.max(0, dataMax - dataMin);
  if (total > 0 && visible / total >= 0.9) return "MAX";

  let best: Exclude<RangePreset, "MAX"> = "1M";
  let bestDistance = Number.POSITIVE_INFINITY;
  for (const [preset, duration] of Object.entries(RANGE_MS) as Array<
    [Exclude<RangePreset, "MAX">, number]
  >) {
    const distance = Math.abs(Math.log(Math.max(1, visible)) - Math.log(duration));
    if (distance < bestDistance) {
      best = preset;
      bestDistance = distance;
    }
  }
  return best;
}

function stockSeriesType(type: PriceChartType): "candlestick" | "ohlc" | "line" | "area" {
  if (type === "candles") return "candlestick";
  return type;
}

function paneLayout(panes: { volume: boolean; rsi: boolean }) {
  const extra = Number(panes.volume) + Number(panes.rsi);
  if (extra === 0) return { priceHeight: "100%", volumeTop: "0%", rsiTop: "0%" };
  if (extra === 1) return { priceHeight: "72%", volumeTop: "74%", rsiTop: "74%" };
  return { priceHeight: "58%", volumeTop: "60%", rsiTop: "80%" };
}

function emptyNavigatorData(bars: PriceBar[]): Array<[number, number]> {
  return bars.map((bar) => [bar.t, bar.c]);
}

export function buildHcPriceStockOption(input: PriceStockOptionsInput): Options {
  const {
    symbol,
    bars,
    mode,
    type,
    period,
    overlays,
    panes,
    scale,
    compares,
    compareData,
    colors,
    onVisibleRangeChange,
  } = input;
  const safeType: PriceChartType =
    mode === "nav" && (type === "candles" || type === "ohlc") ? "line" : type;
  const dataGrouping = dataGroupingForPeriod(period);
  const showVolume = mode === "ohlcv" && panes.volume;
  const layout = paneLayout({ volume: showVolume, rsi: panes.rsi });
  const dataMin = bars[0]?.t ?? 0;
  const dataMax = bars[bars.length - 1]?.t ?? 0;

  const yAxis: NonNullable<Options["yAxis"]> = [
    {
      id: "price-axis",
      height: layout.priceHeight,
      type: scale.log ? "logarithmic" : "linear",
      labels: { align: "right", x: -4 },
      title: { text: undefined },
      resize: { enabled: true },
    },
  ];

  if (showVolume) {
    (yAxis as Array<Record<string, unknown>>).push({
      id: "volume-axis",
      top: layout.volumeTop,
      height: panes.rsi ? "18%" : "24%",
      offset: 0,
      labels: { align: "right", x: -4 },
      title: { text: undefined },
    });
  }

  if (panes.rsi) {
    (yAxis as Array<Record<string, unknown>>).push({
      id: "rsi-axis",
      top: layout.rsiTop,
      height: showVolume ? "18%" : "24%",
      min: 0,
      max: 100,
      offset: 0,
      labels: { align: "right", x: -4 },
      title: { text: undefined },
      plotLines: [
        { value: 30, color: colors.grid, width: 1 },
        { value: 70, color: colors.grid, width: 1 },
      ],
    });
  }

  const series: SeriesOptionsType[] = [
    {
      id: PRICE_SERIES_ID,
      type: stockSeriesType(safeType),
      name: symbol,
      data: toMainSeriesData(bars, safeType),
      yAxis: "price-axis",
      color: safeType === "area" ? colors.accent : colors.accent,
      lineColor: colors.accent,
      upColor: colors.gain,
      upLineColor: colors.gain,
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType,
  ];

  if (showVolume) {
    series.push({
      id: VOLUME_SERIES_ID,
      type: "column",
      name: "Volume",
      data: toVolumeSeriesData(bars),
      yAxis: "volume-axis",
      color: colors.barMute,
      dataGrouping,
      tooltip: { valueDecimals: 0 },
    } as SeriesOptionsType);
  }

  if (overlays.sma20) {
    series.push({
      type: "sma",
      name: "SMA20",
      linkedTo: PRICE_SERIES_ID,
      params: { period: 20 },
      color: colors.categories[2],
      lineWidth: 1,
      dataGrouping,
    } as SeriesOptionsType);
  }

  if (overlays.sma50) {
    series.push({
      type: "sma",
      name: "SMA50",
      linkedTo: PRICE_SERIES_ID,
      params: { period: 50 },
      color: colors.categories[3],
      lineWidth: 1,
      dataGrouping,
    } as SeriesOptionsType);
  }

  if (panes.rsi) {
    series.push({
      type: "rsi",
      name: "RSI 14",
      linkedTo: PRICE_SERIES_ID,
      yAxis: "rsi-axis",
      params: { period: 14 },
      color: colors.bar,
      dataGrouping,
    } as SeriesOptionsType);
  }

  compares.forEach((compare, index) => {
    const compareBars = compareData[compare.key] ?? [];
    series.push({
      id: `compare-${compare.key}`,
      type: "line",
      name: compare.label,
      data: toMainSeriesData(compareBars, "line"),
      yAxis: "price-axis",
      color: colors.categories[(index + 4) % colors.categories.length],
      lineWidth: 1.4,
      marker: { enabled: false },
      dataGrouping,
      tooltip: { valueDecimals: 2 },
    } as SeriesOptionsType);
  });

  return {
    chart: { spacingTop: 8, spacingRight: 8, spacingBottom: 8, spacingLeft: 8 },
    rangeSelector: {
      selected: undefined,
      inputEnabled: false,
      buttons: [
        { type: "month", count: 1, text: "1M" },
        { type: "month", count: 6, text: "6M" },
        { type: "year", count: 1, text: "1Y" },
        { type: "year", count: 5, text: "5Y" },
        { type: "all", text: "MAX" },
      ],
    },
    navigator: {
      enabled: true,
      series: { data: emptyNavigatorData(bars), color: colors.barMute },
    },
    scrollbar: { enabled: true },
    stockTools: { gui: { enabled: true } },
    navigation: { bindingsClassName: "highcharts-bindings-container" },
    xAxis: {
      ordinal: true,
      events: {
        afterSetExtremes(event) {
          if (!onVisibleRangeChange) return;
          const min = typeof event.min === "number" ? event.min : dataMin;
          const max = typeof event.max === "number" ? event.max : dataMax;
          onVisibleRangeChange(rangePresetFromExtremes(min, max, dataMin, dataMax));
        },
      },
    },
    yAxis,
    tooltip: {
      split: false,
      shared: true,
      valueDecimals: scale.pct ? 2 : undefined,
    },
    plotOptions: {
      series: {
        compare: scale.pct ? "percent" : undefined,
        dataGrouping,
        marker: { enabled: false },
        turboThreshold: 0,
      },
      candlestick: {
        color: colors.loss,
        upColor: colors.gain,
        lineColor: colors.loss,
        upLineColor: colors.gain,
      },
      ohlc: {
        color: colors.loss,
        upColor: colors.gain,
      },
      area: {
        fillColor: `${colors.accent}24`,
        threshold: null,
      },
    },
    series,
    credits: { enabled: false },
  };
}
```

- [ ] **Step 4: Run the builder tests to verify they pass**

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStock.test.ts
```

Expected: PASS for all tests in `priceStock.test.ts`.

- [ ] **Step 5: Run focused typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0. If Highcharts narrows a Stock option too far, isolate the cast inside `priceStock.ts` and keep the public input types unchanged.

- [ ] **Step 6: Commit builder task**

Run:

```powershell
git add frontend/src/lib/charts/hc/priceStock.ts frontend/src/lib/charts/hc/priceStock.test.ts
git commit -m "feat(charts): add Highcharts Stock price option builder"
```

Expected: commit includes only the builder and test.

---

### Task 2: Live Tick Merge Helpers

**Files:**
- Create: `frontend/src/lib/charts/hc/priceStockLive.ts`
- Create: `frontend/src/lib/charts/hc/priceStockLive.test.ts`

- [ ] **Step 1: Write the failing live helper tests**

Create `frontend/src/lib/charts/hc/priceStockLive.test.ts`:

```ts
import { describe, expect, it } from "vitest";

import { mergeTickIntoBars, parseTickTimeMs } from "@/lib/charts/hc/priceStockLive";
import type { PriceBar } from "@/lib/charts/hc/priceStock";

const DAY1 = Date.UTC(2024, 0, 2, 21);
const DAY2 = Date.UTC(2024, 0, 3, 14);

const BARS: PriceBar[] = [
  { t: Date.UTC(2024, 0, 2), o: 100, h: 105, l: 98, c: 102, v: 1000 },
];

describe("parseTickTimeMs", () => {
  it("parses an ISO time string", () => {
    expect(parseTickTimeMs("2024-01-03T14:30:00.000Z", DAY1)).toBe(
      Date.UTC(2024, 0, 3, 14, 30),
    );
  });

  it("falls back when the tick time is empty or invalid", () => {
    expect(parseTickTimeMs("", DAY1)).toBe(DAY1);
    expect(parseTickTimeMs("not-a-date", DAY1)).toBe(DAY1);
  });
});

describe("mergeTickIntoBars", () => {
  it("updates the latest bar when the tick is on the same UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 107, size: 50, timeMs: DAY1 });
    expect(next).toHaveLength(1);
    expect(next[0]).toEqual({
      t: BARS[0].t,
      o: 100,
      h: 107,
      l: 98,
      c: 107,
      v: 1050,
    });
    expect(BARS[0].c).toBe(102);
  });

  it("appends a new bar when the tick is on a later UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 111, size: 75, timeMs: DAY2 });
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({
      t: Date.UTC(2024, 0, 3),
      o: 111,
      h: 111,
      l: 111,
      c: 111,
      v: 75,
    });
  });

  it("returns the same empty array when there are no bars", () => {
    const empty: PriceBar[] = [];
    expect(mergeTickIntoBars(empty, { price: 1, size: 1, timeMs: DAY1 })).toBe(empty);
  });
});
```

- [ ] **Step 2: Run live helper tests to verify they fail**

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStockLive.test.ts
```

Expected: FAIL because `@/lib/charts/hc/priceStockLive` does not exist.

- [ ] **Step 3: Implement live helpers**

Create `frontend/src/lib/charts/hc/priceStockLive.ts`:

```ts
import type { Chart, Series } from "highcharts";

import {
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  toMainSeriesData,
  toVolumeSeriesData,
  type PriceBar,
  type PriceChartType,
  type PricePeriod,
} from "@/lib/charts/hc/priceStock";

export interface LiveTickInput {
  price: number;
  size: number;
  timeMs: number;
}

export function parseTickTimeMs(time: string, fallback = Date.now()): number {
  if (!time) return fallback;
  const parsed = Date.parse(time);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function utcDayStart(ms: number): number {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function sameUtcDay(a: number, b: number): boolean {
  return utcDayStart(a) === utcDayStart(b);
}

export function mergeTickIntoBars(bars: PriceBar[], tick: LiveTickInput): PriceBar[] {
  if (!bars.length) return bars;
  const last = bars[bars.length - 1];
  if (sameUtcDay(last.t, tick.timeMs)) {
    const updated: PriceBar = {
      ...last,
      h: Math.max(last.h, tick.price),
      l: Math.min(last.l, tick.price),
      c: tick.price,
      v: last.v + tick.size,
    };
    return [...bars.slice(0, -1), updated];
  }
  return [
    ...bars,
    {
      t: utcDayStart(tick.timeMs),
      o: tick.price,
      h: tick.price,
      l: tick.price,
      c: tick.price,
      v: tick.size,
    },
  ];
}

function getSeries(chart: Chart, id: string): Series | undefined {
  const found = chart.get(id);
  return found && "setData" in found ? (found as Series) : undefined;
}

export function applyBarsToLiveChart({
  chart,
  bars,
  type,
  period,
  showVolume,
}: {
  chart: Chart;
  bars: PriceBar[];
  type: PriceChartType;
  period: PricePeriod;
  showVolume: boolean;
}): void {
  const price = getSeries(chart, PRICE_SERIES_ID);
  if (!price) return;

  // In grouped W/M views, updating the base data and letting Stock regroup is
  // more reliable than trying to mutate a grouped point by hand.
  price.setData(toMainSeriesData(bars, type), false, false, false);

  if (showVolume) {
    getSeries(chart, VOLUME_SERIES_ID)?.setData(toVolumeSeriesData(bars), false, false, false);
  }

  if (period === "D") {
    chart.redraw(false);
  } else {
    chart.redraw(false);
  }
}
```

- [ ] **Step 4: Run live helper tests to verify they pass**

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStockLive.test.ts
```

Expected: PASS for all tests in `priceStockLive.test.ts`.

- [ ] **Step 5: Run focused typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 6: Commit live helper task**

Run:

```powershell
git add frontend/src/lib/charts/hc/priceStockLive.ts frontend/src/lib/charts/hc/priceStockLive.test.ts
git commit -m "feat(charts): add Highcharts Stock live tick helpers"
```

Expected: commit includes only live helper files.

---

### Task 3: Stock Wrapper ESM Modules and CSS

**Files:**
- Modify: `frontend/src/components/charts/HighchartsStockChart.tsx`
- Modify: `frontend/src/app/layout.tsx`

- [ ] **Step 1: Update the root layout CSS imports**

Modify the top imports of `frontend/src/app/layout.tsx` to include the stock-tools CSS after global app CSS and Carbon CSS:

```ts
import type { Metadata } from "next";
import { Geist_Mono } from "next/font/google";
import "./globals.css";
import "@carbon/styles/css/styles.min.css";
import "highcharts/css/annotations/popup.css";
import "highcharts/css/stocktools/gui.css";
import { Providers } from "./providers";
import { AppShell } from "@/components/shell/AppShell";
import { CarbonThemeBridge } from "@/components/shell/CarbonThemeBridge";
```

- [ ] **Step 2: Replace Stock wrapper dynamic imports with ESM registration**

Replace the async block inside `frontend/src/components/charts/HighchartsStockChart.tsx` with:

```ts
    void (async () => {
      // Use the ESM build so Stock modules register on the same Highcharts
      // singleton. The UMD module paths do not self-register under Turbopack.
      const mod = await import("highcharts/esm/highstock.js");
      await import("highcharts/esm/indicators/indicators.js");
      await import("highcharts/esm/indicators/rsi.js");
      await import("highcharts/esm/modules/annotations.js");
      await import("highcharts/esm/modules/stock-tools.js");
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
    })();
```

Keep the existing `ResizeObserver`, `chart.update`, empty overlay, and cleanup logic unchanged.

- [ ] **Step 3: Run typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 4: Run lint**

Run:

```powershell
cd frontend
pnpm lint
```

Expected: exit 0.

- [ ] **Step 5: Commit wrapper task**

Run:

```powershell
git add frontend/src/components/charts/HighchartsStockChart.tsx frontend/src/app/layout.tsx
git commit -m "feat(charts): register Highcharts Stock ESM modules"
```

Expected: commit includes only wrapper/layout changes.

---

### Task 4: Rewrite InteractiveChart on Highcharts Stock

**Files:**
- Modify: `frontend/src/components/charts/InteractiveChart.tsx`

- [ ] **Step 1: Replace canvas imports and constants**

In `frontend/src/components/charts/InteractiveChart.tsx`, remove imports from:

```ts
import { Chart } from "@/lib/ixchart/engine";
import { readIxTokens } from "@/lib/ixchart/tokens";
import { fmtP, fmtV } from "@/lib/ixchart/series";
import type { Bar, ChartType, DrawTool, Period } from "@/lib/ixchart/types";
```

Add these imports:

```ts
import { useQueries } from "@tanstack/react-query";
import type { Chart } from "highcharts";

import { HighchartsStockChart } from "@/components/charts/HighchartsStockChart";
import {
  addCompareSelection,
  buildHcPriceStockOption,
  removeCompareSelection,
  type PriceBar,
  type PriceChartType,
  type PriceCompareSelection,
  type PriceMode,
  type PricePeriod,
} from "@/lib/charts/hc/priceStock";
import {
  applyBarsToLiveChart,
  mergeTickIntoBars,
  parseTickTimeMs,
} from "@/lib/charts/hc/priceStockLive";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
```

Remove `TOOLS` and `RANGE_BARS`; stock-tools and Highcharts ranges own those behaviors now.

- [ ] **Step 2: Replace prop types and state**

Use these type constants and props:

```ts
const PERIODS: PricePeriod[] = ["D", "W", "M"];
const TYPES: { id: PriceChartType; label: string }[] = [
  { id: "candles", label: "Candles" },
  { id: "ohlc", label: "OHLC" },
  { id: "line", label: "Line" },
  { id: "area", label: "Area" },
];

export function InteractiveChart({
  symbol,
  bars,
  range,
  onRangeChange,
  mode = "ohlcv",
  className,
}: {
  symbol: string;
  bars: PriceBar[];
  range: RangePreset;
  onRangeChange: (next: RangePreset) => void;
  mode?: PriceMode;
  className?: string;
}) {
  const chartRef = useRef<Chart | null>(null);
  const [colors, setColors] = useState<ChartColors | null>(null);
  const [liveBars, setLiveBars] = useState<PriceBar[]>(bars);
  const liveBarsRef = useRef<PriceBar[]>(bars);
  const [period, setPeriod] = useState<PricePeriod>("D");
  const [type, setType] = useState<PriceChartType>(mode === "nav" ? "line" : "candles");
  const [overlays, setOverlays] = useState({ sma20: true, sma50: false });
  const [panes, setPanes] = useState({ volume: mode !== "nav", rsi: false });
  const [scale, setScale] = useState({ log: false, pct: false });
  const [compares, setCompares] = useState<PriceCompareSelection[]>([]);
  const [live, setLive] = useState(true);
  const [feed, setFeed] = useState<FeedStatus>("off");
```

- [ ] **Step 3: Add mode, colors, liveBars, and feed effects**

Add these effects after state declarations:

```ts
  useEffect(() => {
    setColors(chartColors());
  }, []);

  useEffect(() => {
    setLiveBars(bars);
    liveBarsRef.current = bars;
  }, [bars]);

  useEffect(() => {
    liveBarsRef.current = liveBars;
  }, [liveBars]);

  useEffect(() => {
    if (mode === "nav" && (type === "candles" || type === "ohlc")) {
      setType("line");
    }
    if (mode === "nav" && panes.volume) {
      setPanes((current) => ({ ...current, volume: false }));
    }
  }, [mode, panes.volume, type]);

  useEffect(() => onFeedStatus(setFeed), []);
```

- [ ] **Step 4: Add multi-compare queries**

Add compare queries with TanStack `useQueries`:

```ts
  const compareQueries = useQueries({
    queries: compares.map((compare) => ({
      queryKey: [
        "compare-history",
        compare.kind,
        compare.symbol,
        compare.instrumentId,
      ],
      queryFn: ({ signal }: { signal: AbortSignal }) =>
        compare.instrumentId &&
        (compare.kind === "mutual_fund" || compare.kind === "mmf")
          ? fetchFundHistory(compare.instrumentId, 2520, signal)
          : fetchStockHistory(compare.symbol, 2520, signal),
      staleTime: 60 * 60 * 1000,
    })),
  });

  const compareData = useMemo(() => {
    const out: Record<string, PriceBar[]> = {};
    compares.forEach((compare, index) => {
      const data = compareQueries[index]?.data;
      if (data?.bars?.length) out[compare.key] = data.bars;
    });
    return out;
  }, [compares, compareQueries]);
```

- [ ] **Step 5: Build Highcharts Stock options**

Add:

```ts
  const options = useMemo(() => {
    if (!colors) return null;
    return buildHcPriceStockOption({
      symbol,
      bars: liveBars,
      mode,
      type,
      period,
      range,
      overlays,
      panes,
      scale,
      compares,
      compareData,
      colors,
      onVisibleRangeChange: (next) => {
        if (next !== range) onRangeChange(next);
      },
    });
  }, [
    colors,
    symbol,
    liveBars,
    mode,
    type,
    period,
    range,
    overlays,
    panes,
    scale,
    compares,
    compareData,
    onRangeChange,
  ]);
```

- [ ] **Step 6: Add live tick bridge**

Add:

```ts
  useEffect(() => {
    if (!live || mode === "nav" || !symbol) return;
    return subscribeTicks(symbol, (tick) => {
      const timeMs = parseTickTimeMs(tick.time);
      setLiveBars((current) => {
        const next = mergeTickIntoBars(current, {
          price: tick.price,
          size: tick.size,
          timeMs,
        });
        liveBarsRef.current = next;
        if (chartRef.current) {
          applyBarsToLiveChart({
            chart: chartRef.current,
            bars: next,
            type,
            period,
            showVolume: mode === "ohlcv" && panes.volume,
          });
        }
        return next;
      });
    });
  }, [symbol, live, mode, type, period, panes.volume]);
```

- [ ] **Step 7: Replace JSX with Stock chart and controls**

Replace the returned JSX with:

```tsx
  const typeOptions =
    mode === "nav" ? TYPES.filter((entry) => entry.id === "line" || entry.id === "area") : TYPES;

  const btn = (active: boolean) =>
    `px-2 h-7 text-[11px] border-r border-border last:border-r-0 transition-colors ${
      active ? "bg-accent font-bold text-on-accent" : "text-text-muted hover:bg-layer-hover hover:text-text-primary"
    }`;

  const group = "flex items-stretch border border-border-strong";

  return (
    <div className={className}>
      <div className="flex flex-wrap items-center gap-2 border border-b-0 border-border bg-surface-1 px-2 py-1.5 text-[11px]">
        <div role="group" aria-label="Chart type" className={group}>
          {typeOptions.map((entry) => (
            <button
              key={entry.id}
              type="button"
              aria-pressed={type === entry.id}
              className={btn(type === entry.id)}
              onClick={() => setType(entry.id)}
            >
              {entry.label}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Period" className={group}>
          {PERIODS.map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={period === entry}
              className={btn(period === entry)}
              onClick={() => setPeriod(entry)}
            >
              {entry}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Range" className={group}>
          {RANGE_PRESETS.map((entry) => (
            <button
              key={entry}
              type="button"
              aria-pressed={range === entry}
              className={btn(range === entry)}
              onClick={() => onRangeChange(entry)}
            >
              {entry}
            </button>
          ))}
        </div>
        <div role="group" aria-label="Indicators" className={group}>
          <button
            type="button"
            aria-pressed={overlays.sma20}
            className={btn(overlays.sma20)}
            onClick={() => setOverlays((current) => ({ ...current, sma20: !current.sma20 }))}
          >
            SMA20
          </button>
          <button
            type="button"
            aria-pressed={overlays.sma50}
            className={btn(overlays.sma50)}
            onClick={() => setOverlays((current) => ({ ...current, sma50: !current.sma50 }))}
          >
            SMA50
          </button>
          {mode !== "nav" && (
            <button
              type="button"
              aria-pressed={panes.volume}
              className={btn(panes.volume)}
              onClick={() => setPanes((current) => ({ ...current, volume: !current.volume }))}
            >
              VOL
            </button>
          )}
          <button
            type="button"
            aria-pressed={panes.rsi}
            className={btn(panes.rsi)}
            onClick={() => setPanes((current) => ({ ...current, rsi: !current.rsi }))}
          >
            RSI
          </button>
        </div>
        <div role="group" aria-label="Scale" className={group}>
          <button
            type="button"
            aria-pressed={scale.log}
            className={btn(scale.log)}
            onClick={() => setScale((current) => ({ ...current, log: !current.log, pct: false }))}
          >
            Log
          </button>
          <button
            type="button"
            aria-pressed={scale.pct}
            className={btn(scale.pct)}
            onClick={() => setScale((current) => ({ ...current, pct: !current.pct, log: false }))}
          >
            %
          </button>
        </div>
        <SymbolSearchInput
          active={null}
          onSelect={(item) => {
            setCompares((current) => addCompareSelection(current, item));
            setScale((current) => ({ ...current, pct: true, log: false }));
          }}
        />
        <div className="flex flex-wrap items-center gap-1">
          {compares.map((compare) => (
            <button
              key={compare.key}
              type="button"
              className="h-7 border border-border-strong bg-field px-2 text-[11px] text-text-secondary hover:bg-layer-hover hover:text-text-primary"
              onClick={() => setCompares((current) => removeCompareSelection(current, compare.key))}
              aria-label={`Remove comparison ${compare.label}`}
            >
              {compare.label} x
            </button>
          ))}
        </div>
        <div className="flex-1" />
        {mode !== "nav" && (
          <button
            type="button"
            aria-pressed={live}
            onClick={() => setLive((value) => !value)}
            className={`flex h-7 items-center gap-1.5 border border-border-strong px-2 text-[11px] ${
              live && feed === "live" ? "text-gain" : "text-text-muted"
            }`}
          >
            <span
              className={`h-1.5 w-1.5 rounded-full ${
                live && feed === "live" ? "bg-gain" : "bg-border-strong"
              }`}
            />
            {live && feed === "live" ? "LIVE" : "EOD"}
          </button>
        )}
      </div>

      <div className="relative h-[58vh] min-h-[380px] border border-border bg-surface-1">
        {options ? (
          <HighchartsStockChart
            options={options}
            className="h-full w-full"
            isEmpty={liveBars.length === 0}
            emptyMessage="No price or NAV history in the synced window."
            onReady={(chart) => {
              chartRef.current = chart;
            }}
          />
        ) : (
          <div className="flex h-full items-center justify-center text-[13px] text-text-muted">
            Loading chart...
          </div>
        )}
      </div>
    </div>
  );
}
```

- [ ] **Step 8: Run typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0. Resolve only errors introduced by this task.

- [ ] **Step 9: Run lint**

Run:

```powershell
cd frontend
pnpm lint
```

Expected: exit 0.

- [ ] **Step 10: Commit chart rewrite task**

Run:

```powershell
git add frontend/src/components/charts/InteractiveChart.tsx
git commit -m "feat(charts): migrate InteractiveChart to Highcharts Stock"
```

Expected: commit includes only `InteractiveChart.tsx`.

---

### Task 5: Multi-Compare Input Compatibility

**Files:**
- Modify: `frontend/src/components/charts/SymbolSearchInput.tsx`
- Test through: `frontend/src/components/charts/InteractiveChart.tsx`

- [ ] **Step 1: Make `active` and `onClear` optional**

In `frontend/src/components/charts/SymbolSearchInput.tsx`, change the props signature to:

```ts
export function SymbolSearchInput({
  onSelect,
  onClear,
  active = null,
  placeholder = "Compare...",
}: {
  onSelect: (item: SymbolSearchResult) => void;
  onClear?: () => void;
  active?: string | null;
  placeholder?: string;
}) {
```

- [ ] **Step 2: Guard the clear button**

Replace the clear-button condition with:

```tsx
      {active && onClear && (
        <button
          type="button"
          aria-label={`Remove comparison ${active}`}
          className="text-[11px] text-text-muted hover:text-text-primary"
          onClick={onClear}
        >
          x
        </button>
      )}
```

- [ ] **Step 3: Run typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0. This also proves existing single-active callers still compile.

- [ ] **Step 4: Run lint**

Run:

```powershell
cd frontend
pnpm lint
```

Expected: exit 0.

- [ ] **Step 5: Commit input compatibility task**

Run:

```powershell
git add frontend/src/components/charts/SymbolSearchInput.tsx frontend/src/components/charts/InteractiveChart.tsx
git commit -m "feat(charts): support additive compare picker"
```

Expected: commit contains the optional prop change and any tiny resulting adjustment in `InteractiveChart.tsx`.

---

### Task 6: Focused Test and Consumer Gates

**Files:**
- Test: `frontend/src/lib/charts/hc/priceStock.test.ts`
- Test: `frontend/src/lib/charts/hc/priceStockLive.test.ts`
- Verify: `frontend/src/components/stocks/StockAnalysisView.tsx`
- Verify: `frontend/src/components/funds/FundProfileView.tsx`

- [ ] **Step 1: Run the new pure tests together**

Run:

```powershell
cd frontend
pnpm test src/lib/charts/hc/priceStock.test.ts src/lib/charts/hc/priceStockLive.test.ts
```

Expected: PASS for both new test files.

- [ ] **Step 2: Run typecheck**

Run:

```powershell
cd frontend
pnpm typecheck
```

Expected: exit 0.

- [ ] **Step 3: Run lint**

Run:

```powershell
cd frontend
pnpm lint
```

Expected: exit 0.

- [ ] **Step 4: Run all tests and classify known baseline**

Run:

```powershell
cd frontend
pnpm test
```

Expected: all pure `hc/*.test.ts` tests pass. If the two pre-existing screener `.test.tsx` files fail with the known `jsx: preserve` Vite React baseline, record the exact failing filenames and message in the task report without changing them.

- [ ] **Step 5: Run production build**

Run:

```powershell
cd frontend
pnpm build
```

Expected: exit 0.

- [ ] **Step 6: Return failures to the owning task**

If Step 1-5 fails, do not create a broad gate-only commit. Return to the task
that owns the failing file, make the fix there, rerun that task's command, and
commit with that task's file list. If all gates pass, create no commit in Task 6.

Expected: Task 6 ends with no new files staged.

---

### Task 7: Disposable Visual Demo and Cleanup

**Files:**
- Temporary create/delete: `frontend/src/app/__hc-p2-demo/page.tsx`

- [ ] **Step 1: Create a disposable demo page**

Create `frontend/src/app/__hc-p2-demo/page.tsx` with this content:

```tsx
"use client";

import { useMemo, useState } from "react";

import { InteractiveChart } from "@/components/charts/InteractiveChart";
import type { RangePreset } from "@/lib/api/client";
import type { PriceBar } from "@/lib/charts/hc/priceStock";

const BARS: PriceBar[] = Array.from({ length: 320 }, (_, index) => {
  const t = Date.UTC(2025, 0, 2 + index);
  const base = 100 + Math.sin(index / 14) * 8 + index * 0.05;
  const c = base + Math.sin(index / 5) * 2;
  return {
    t,
    o: base,
    h: Math.max(base, c) + 2,
    l: Math.min(base, c) - 2,
    c,
    v: 900_000 + index * 1200,
  };
});

export default function HighchartsP2DemoPage() {
  const [range, setRange] = useState<RangePreset>("1Y");
  const bars = useMemo(() => BARS, []);
  return (
    <main className="min-h-screen bg-surface-0 px-6 py-6">
      <InteractiveChart
        symbol="AAPL"
        bars={bars}
        range={range}
        onRangeChange={setRange}
      />
    </main>
  );
}
```

- [ ] **Step 2: Start the dev server**

Run:

```powershell
cd frontend
pnpm dev
```

Expected: Next starts on `http://localhost:3000` or reports the alternate port it selected.

- [ ] **Step 3: Visual check in browser**

Open `/__hc-p2-demo` and verify:

- candles render;
- navigator renders;
- stock-tools GUI renders;
- D/W/M buttons change grouping without blanking the chart;
- `1M`, `6M`, `1Y`, `5Y`, `MAX` range buttons change the visible window;
- SMA20 appears by default;
- VOL toggles;
- RSI toggles into its own pane;
- Log and `%` are mutually exclusive;
- compare input can add multiple chips;
- removing compare chips removes the series;
- light and dark themes both render readable chart chrome.

- [ ] **Step 4: Delete the disposable page**

Delete `frontend/src/app/__hc-p2-demo/page.tsx`.

Run:

```powershell
git status --short frontend/src/app/__hc-p2-demo/page.tsx
```

Expected: no staged or unstaged demo page remains.

- [ ] **Step 5: Stop the dev server**

Stop the `pnpm dev` process with `Ctrl+C`.

Expected: no dev server session remains running.

---

### Task 8: Final Branch Verification

**Files:**
- Verify branch state only.

- [ ] **Step 1: Run final frontend gates**

Run:

```powershell
cd frontend
pnpm typecheck
pnpm lint
pnpm test
pnpm build
```

Expected:

- `pnpm typecheck`: exit 0;
- `pnpm lint`: exit 0;
- `pnpm test`: pass except known pre-existing screener `.test.tsx` baseline if still present;
- `pnpm build`: exit 0.

- [ ] **Step 2: Check git status**

Run:

```powershell
git status --short --branch
```

Expected: clean except for unrelated pre-existing untracked files outside the P2 worktree scope.

- [ ] **Step 3: Show commit stack**

Run:

```powershell
git log --oneline main..HEAD
```

Expected: shows the P2 implementation commits from Tasks 1-6, and no unrelated files.

- [ ] **Step 4: Prepare finishing handoff**

Record in the final task report:

- worktree path;
- branch name;
- final HEAD SHA;
- exact gate outputs;
- whether `pnpm test` had the known screener baseline;
- confirmation that the disposable demo was deleted;
- confirmation that `frontend/src/lib/ixchart/*` was not removed.

No commit is needed for Task 8 unless a gate fix changed files.
