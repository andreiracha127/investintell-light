import { describe, expect, it } from "vitest";

import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { SeriesPoint } from "@/lib/api/client";
import { formatNumber, formatPercent } from "@/lib/format";

const SERIES: SeriesPoint[] = [
  ["2024-01-01", 0.12],
  ["2024-01-02", 0.15],
  ["2024-01-03", 0.11],
];

describe("buildHcRollingOption", () => {
  // ── Data mapping ─────────────────────────────────────────────────────────

  it("maps SeriesPoint dates to xAxis categories", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02", "2024-01-03"]);
  });

  it("maps SeriesPoint values to series data", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([0.12, 0.15, 0.11]);
  });

  it("uses the provided label as the series name", () => {
    const opt = buildHcRollingOption(SERIES, "Beta", TEST_COLORS);
    const series = opt.series?.[0] as { name?: string };
    expect(series.name).toBe("Beta");
  });

  // ── Series appearance ─────────────────────────────────────────────────────

  it("renders a line series", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const series = opt.series?.[0] as { type?: string };
    expect(series.type).toBe("line");
  });

  it("colors the line with the accent token", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const series = opt.series?.[0] as { color?: string };
    expect(series.color).toBe(TEST_COLORS.accent);
  });

  it("disables point markers", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const series = opt.series?.[0] as { marker?: { enabled?: boolean } };
    expect(series.marker?.enabled).toBe(false);
  });

  // ── Default axis formatting (no yPercent) ─────────────────────────────────

  it("formats y-axis labels as plain numbers by default", () => {
    const opt = buildHcRollingOption(SERIES, "Beta", TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 1.23 });
    expect(out).toBe(formatNumber(1.23));
  });

  it("formats tooltip values as plain numbers by default", () => {
    const opt = buildHcRollingOption(SERIES, "Beta", TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: string; y: number }) => string;
    };
    const out = tooltip.formatter!.call({ x: "2024-01-02", y: 0.15 });
    expect(out).toContain("2024-01-02");
    expect(out).toContain(formatNumber(0.15));
  });

  // ── yPercent mode ─────────────────────────────────────────────────────────

  it("formats y-axis labels as percent when yPercent=true", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS, {
      yPercent: true,
    });
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 0.12 });
    expect(out).toBe(formatPercent(0.12, 1));
  });

  it("formats tooltip values as percent when yPercent=true", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS, {
      yPercent: true,
    });
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: string; y: number }) => string;
    };
    const out = tooltip.formatter!.call({ x: "2024-01-01", y: 0.12 });
    expect(out).toContain("2024-01-01");
    expect(out).toContain(formatPercent(0.12, 1));
  });

  // ── Fixed y-axis bounds ────────────────────────────────────────────────────

  it("does not set yAxis min/max when bounds are omitted", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const yAxis = opt.yAxis as { min?: number; max?: number };
    expect(yAxis.min).toBeUndefined();
    expect(yAxis.max).toBeUndefined();
  });

  it("applies yMin and yMax to yAxis when provided (e.g. correlation -1..1)", () => {
    const opt = buildHcRollingOption(SERIES, "Correlation", TEST_COLORS, {
      yMin: -1,
      yMax: 1,
    });
    const yAxis = opt.yAxis as { min?: number; max?: number };
    expect(yAxis.min).toBe(-1);
    expect(yAxis.max).toBe(1);
  });

  it("applies only yMin when only yMin is provided", () => {
    const opt = buildHcRollingOption(SERIES, "Correlation", TEST_COLORS, {
      yMin: 0,
    });
    const yAxis = opt.yAxis as { min?: number; max?: number };
    expect(yAxis.min).toBe(0);
    expect(yAxis.max).toBeUndefined();
  });

  // ── Empty input ────────────────────────────────────────────────────────────

  it("returns empty series data for empty input", () => {
    const opt = buildHcRollingOption([], "Volatility", TEST_COLORS);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([]);
  });

  it("returns empty categories for empty input", () => {
    const opt = buildHcRollingOption([], "Volatility", TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });

  // ── Chart-level structure ─────────────────────────────────────────────────

  it("sets chart.type to line", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    expect((opt.chart as { type?: string }).type).toBe("line");
  });

  it("does not re-set global chrome (no axis grid colors, no tooltip background)", () => {
    const opt = buildHcRollingOption(SERIES, "Volatility", TEST_COLORS);
    const yAxis = opt.yAxis as Record<string, unknown>;
    expect(yAxis.gridLineColor).toBeUndefined();
    const tooltip = opt.tooltip as Record<string, unknown>;
    expect(tooltip.backgroundColor).toBeUndefined();
  });
});
