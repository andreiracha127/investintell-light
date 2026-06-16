import { describe, expect, it } from "vitest";

import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import {
  buildHcMultiLineOption,
  buildHcStackedAreaOption,
  buildHcStackedPercentOption,
} from "@/lib/charts/hc/stacked";
import type { StackedSeries } from "@/lib/api/client";
import { formatCompact, formatCurrency, formatPercent } from "@/lib/format";

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

/**
 * Minimal shape of the real Highcharts shared-tooltip formatter context.
 * The hovered point carries the category-axis label/date and row index; the
 * shared `points` array holds one entry per series with its color, series
 * name, raw y value, and (for stacked charts) the normalised `percentage`.
 */
type TooltipCtx = {
  category: string | number;
  index: number;
  points?: Array<{
    color: string;
    series: { name: string };
    y: number;
    percentage?: number;
  }>;
};

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const SERIES_A: StackedSeries = {
  ticker: "AAPL",
  points: [
    ["2024-01-01", 1000],
    ["2024-01-02", 1100],
  ],
};

const SERIES_B: StackedSeries = {
  ticker: "CASH",
  points: [
    ["2024-01-01", 200],
    ["2024-01-02", 200],
  ],
};

const TOTAL: StackedSeries = {
  ticker: "TOTAL",
  points: [
    ["2024-01-01", 1200],
    ["2024-01-02", 1300],
  ],
};

const WEIGHT_A: StackedSeries = {
  ticker: "AAPL",
  points: [
    ["2024-01-01", 0.6],
    ["2024-01-02", 0.65],
  ],
};

const WEIGHT_B: StackedSeries = {
  ticker: "CASH",
  points: [
    ["2024-01-01", 0.4],
    ["2024-01-02", 0.35],
  ],
};

const PERF_A: StackedSeries = {
  ticker: "AAPL",
  points: [
    ["2024-01-01", 0.0],
    ["2024-01-02", 0.05],
  ],
};

const PERF_TOTAL: StackedSeries = {
  ticker: "TOTAL",
  points: [
    ["2024-01-01", 0.0],
    ["2024-01-02", 0.03],
  ],
};

// ---------------------------------------------------------------------------
// buildHcStackedAreaOption
// ---------------------------------------------------------------------------

describe("buildHcStackedAreaOption", () => {
  it("returns xAxis categories from first stacked series dates", () => {
    const opt = buildHcStackedAreaOption([SERIES_A, SERIES_B], TOTAL, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02"]);
  });

  it("falls back to total dates when stack is empty", () => {
    const opt = buildHcStackedAreaOption([], TOTAL, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02"]);
  });

  it("returns empty categories when both stack and total are null/empty", () => {
    const opt = buildHcStackedAreaOption([], null, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });

  it("creates an area series per stacked entry with stacking:normal", () => {
    const opt = buildHcStackedAreaOption([SERIES_A, SERIES_B], TOTAL, TEST_COLORS);
    const series = opt.series as Array<{ type?: string; stacking?: string; name?: string }>;
    const areaSeries = series.filter((s) => s.type === "area");
    expect(areaSeries).toHaveLength(2);
    expect(areaSeries[0].stacking).toBe("normal");
    expect(areaSeries[0].name).toBe("AAPL");
    expect(areaSeries[1].name).toBe("CASH");
  });

  it("maps series data values correctly", () => {
    const opt = buildHcStackedAreaOption([SERIES_A], null, TEST_COLORS);
    const series = opt.series as Array<{ data?: number[] }>;
    expect(series[0].data).toEqual([1000, 1100]);
  });

  it("uses categoryColor (skipping cat-1) for stacked series", () => {
    const opt = buildHcStackedAreaOption([SERIES_A, SERIES_B], null, TEST_COLORS);
    const series = opt.series as Array<{ color?: string }>;
    // categoryColor skips index 0 (accent anchor = cat-1) in the categories palette
    const palette = TEST_COLORS.categories.slice(1);
    expect(series[0].color).toBe(palette[0]);
    expect(series[1].color).toBe(palette[1]);
  });

  it("adds a line series for TOTAL with accent color when total is provided", () => {
    const opt = buildHcStackedAreaOption([SERIES_A], TOTAL, TEST_COLORS);
    const series = opt.series as Array<{ type?: string; color?: string; name?: string }>;
    const totalSeries = series.find((s) => s.name === "TOTAL");
    expect(totalSeries).toBeDefined();
    expect(totalSeries!.type).toBe("line");
    expect(totalSeries!.color).toBe(TEST_COLORS.accent);
  });

  it("TOTAL line data maps correctly", () => {
    const opt = buildHcStackedAreaOption([], TOTAL, TEST_COLORS);
    const series = opt.series as Array<{ name?: string; data?: number[] }>;
    const totalSeries = series.find((s) => s.name === "TOTAL");
    expect(totalSeries!.data).toEqual([1200, 1300]);
  });

  it("omits TOTAL series when total is null", () => {
    const opt = buildHcStackedAreaOption([SERIES_A], null, TEST_COLORS);
    const series = opt.series as Array<{ name?: string }>;
    expect(series.find((s) => s.name === "TOTAL")).toBeUndefined();
  });

  it("formats yAxis labels as compact currency", () => {
    const opt = buildHcStackedAreaOption([SERIES_A], null, TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 1200000 });
    expect(out).toBe(`$${formatCompact(1200000)}`);
  });

  it("renders the tooltip from the real shared context as currency", () => {
    const opt = buildHcStackedAreaOption([SERIES_A], null, TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: TooltipCtx) => string;
    };
    // Real shared-tooltip context: the date label is on this.point.category
    // (NOT this.x, which is the numeric category index), rows on this.points.
    const out = tooltip.formatter!.call({
      category: "2024-01-01",
      index: 0,
      points: [
        { color: "#f00", series: { name: "AAPL" }, y: 1000, percentage: 83.3 },
        { color: "#0f0", series: { name: "CASH" }, y: 200, percentage: 16.7 },
      ],
    });
    expect(out).toContain("2024-01-01");
    expect(out).toContain("AAPL");
    expect(out).toContain(formatCurrency(1000));
    expect(out).toContain("CASH");
    expect(out).toContain(formatCurrency(200));
  });

  it("draws the TOTAL line above the stacked areas (locked layering)", () => {
    const opt = buildHcStackedAreaOption([SERIES_A, SERIES_B], TOTAL, TEST_COLORS);
    const series = opt.series as Array<{ type?: string; name?: string; zIndex?: number }>;
    const areaSeries = series.filter((s) => s.type === "area");
    const totalSeries = series.find((s) => s.name === "TOTAL");
    expect(totalSeries!.zIndex).toBeDefined();
    for (const area of areaSeries) {
      expect(totalSeries!.zIndex!).toBeGreaterThan(area.zIndex ?? 0);
    }
  });
});

// ---------------------------------------------------------------------------
// buildHcStackedPercentOption
// ---------------------------------------------------------------------------

describe("buildHcStackedPercentOption", () => {
  it("returns xAxis categories from first series dates", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A, WEIGHT_B], TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02"]);
  });

  it("returns empty categories for empty input", () => {
    const opt = buildHcStackedPercentOption([], TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });

  it("creates area series with stacking:percent for each entry", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A, WEIGHT_B], TEST_COLORS);
    const series = opt.series as Array<{ type?: string; stacking?: string; name?: string }>;
    expect(series).toHaveLength(2);
    expect(series[0].type).toBe("area");
    expect(series[0].stacking).toBe("percent");
    expect(series[0].name).toBe("AAPL");
  });

  it("maps data values correctly", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A], TEST_COLORS);
    const series = opt.series as Array<{ data?: number[] }>;
    expect(series[0].data).toEqual([0.6, 0.65]);
  });

  it("uses categoryColor (skipping cat-1 anchor) for each series", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A, WEIGHT_B], TEST_COLORS);
    const series = opt.series as Array<{ color?: string }>;
    const palette = TEST_COLORS.categories.slice(1);
    expect(series[0].color).toBe(palette[0]);
    expect(series[1].color).toBe(palette[1]);
  });

  it("sets yAxis min to 0", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A], TEST_COLORS);
    const yAxis = opt.yAxis as { min?: number };
    expect(yAxis.min).toBe(0);
  });

  it("formats yAxis labels from the runtime-normalised 0..100 axis value", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A], TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    // stacking:"percent" normalises the axis to 0..100 at runtime, so the
    // formatter receives 50 (not the raw 0.5 fraction). It must NOT re-multiply.
    const out = yAxis.labels!.formatter!.call({ value: 50 });
    expect(out).toBe("50%");
  });

  it("renders the tooltip from the real shared context using stacked share", () => {
    const opt = buildHcStackedPercentOption([WEIGHT_A], TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: TooltipCtx) => string;
    };
    // Real shared-tooltip context: date on this.point.category, per-series rows
    // in this.points, and stacking:"percent" exposes the share as `percentage`.
    const out = tooltip.formatter!.call({
      category: "2024-01-01",
      index: 0,
      points: [
        { color: "#f00", series: { name: "AAPL" }, y: 0.6, percentage: 60 },
        { color: "#0f0", series: { name: "CASH" }, y: 0.4, percentage: 40 },
      ],
    });
    expect(out).toContain("2024-01-01");
    expect(out).toContain("AAPL");
    expect(out).toContain("60.0%");
    expect(out).toContain("CASH");
    expect(out).toContain("40.0%");
  });
});

// ---------------------------------------------------------------------------
// buildHcMultiLineOption
// ---------------------------------------------------------------------------

describe("buildHcMultiLineOption", () => {
  it("returns xAxis categories from first series dates", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02"]);
  });

  it("returns empty categories for empty input", () => {
    const opt = buildHcMultiLineOption([], TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });

  it("creates a line series for each entry", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const series = opt.series as Array<{ type?: string; name?: string }>;
    expect(series).toHaveLength(2);
    expect(series.every((s) => s.type === "line")).toBe(true);
  });

  it("maps data values correctly", () => {
    const opt = buildHcMultiLineOption([PERF_A], TEST_COLORS);
    const series = opt.series as Array<{ data?: number[] }>;
    expect(series[0].data).toEqual([0.0, 0.05]);
  });

  it("colors the TOTAL series with accent", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const series = opt.series as Array<{ name?: string; color?: string }>;
    const totalSeries = series.find((s) => s.name === "TOTAL");
    expect(totalSeries!.color).toBe(TEST_COLORS.accent);
  });

  it("colors non-TOTAL series using categoryColor skipping the anchor", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const series = opt.series as Array<{ name?: string; color?: string }>;
    const aapl = series.find((s) => s.name === "AAPL");
    const palette = TEST_COLORS.categories.slice(1);
    expect(aapl!.color).toBe(palette[0]);
  });

  it("gives TOTAL a higher zIndex (10) and thicker lineWidth (2.5)", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const series = opt.series as Array<{ name?: string; zIndex?: number; lineWidth?: number }>;
    const totalSeries = series.find((s) => s.name === "TOTAL");
    expect(totalSeries!.zIndex).toBe(10);
    expect(totalSeries!.lineWidth).toBe(2.5);
  });

  it("increments categoryIndex only for non-TOTAL series", () => {
    const s1: StackedSeries = { ticker: "A", points: [["2024-01-01", 0.01]] };
    const s2: StackedSeries = { ticker: "TOTAL", points: [["2024-01-01", 0.02]] };
    const s3: StackedSeries = { ticker: "B", points: [["2024-01-01", 0.03]] };
    const opt = buildHcMultiLineOption([s1, s2, s3], TEST_COLORS);
    const series = opt.series as Array<{ name?: string; color?: string }>;
    const palette = TEST_COLORS.categories.slice(1);
    const aColor = series.find((s) => s.name === "A")!.color;
    const bColor = series.find((s) => s.name === "B")!.color;
    expect(aColor).toBe(palette[0]);
    expect(bColor).toBe(palette[1]);
  });

  it("formats yAxis labels as percent with 0 dp", () => {
    const opt = buildHcMultiLineOption([PERF_A], TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 0.15 });
    expect(out).toBe(formatPercent(0.15, 0));
  });

  it("renders the tooltip from the real shared context as signed percent", () => {
    const opt = buildHcMultiLineOption([PERF_A, PERF_TOTAL], TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: TooltipCtx) => string;
    };
    // Real shared-tooltip context: date on this.point.category, per-series rows
    // in this.points; multi-line tooltips format the raw fraction (p.y) signed.
    const out = tooltip.formatter!.call({
      category: "2024-01-02",
      index: 1,
      points: [
        { color: "#f00", series: { name: "AAPL" }, y: 0.05, percentage: 62.5 },
        { color: "#00f", series: { name: "TOTAL" }, y: 0.03, percentage: 37.5 },
      ],
    });
    expect(out).toContain("2024-01-02");
    expect(out).toContain("AAPL");
    expect(out).toContain(formatPercent(0.05, 2, { signed: true }));
    expect(out).toContain("TOTAL");
    expect(out).toContain(formatPercent(0.03, 2, { signed: true }));
  });
});
