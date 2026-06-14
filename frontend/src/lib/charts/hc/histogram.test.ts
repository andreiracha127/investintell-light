import { describe, expect, it } from "vitest";

import { buildHcHistogramOption } from "@/lib/charts/hc/histogram";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { Histogram } from "@/lib/api/client";
import { formatCompact, formatPercent } from "@/lib/format";

// ── fixtures ──────────────────────────────────────────────────────────────────
// 4 bins: edges have 5 values, midpoints are -0.015, -0.005, 0.005, 0.015
const HIST: Histogram = {
  bin_edges: [-0.02, -0.01, 0.0, 0.01, 0.02],
  counts: [5, 12, 20, 8],
  counts_normalized: [0.25, 0.6, 1.0, 0.4],
};

/** Extracts first series (column) from the option. */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function series0(opt: ReturnType<typeof buildHcHistogramOption>): any {
  return opt!.series![0];
}

// ── tests ──────────────────────────────────────────────────────────────────────
describe("buildHcHistogramOption", () => {
  // ── basic structure ────────────────────────────────────────────────────────
  it("returns a column chart", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    expect(opt.chart).toMatchObject({ type: "column" });
  });

  it("series type is column", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const s = series0(opt);
    expect(s.type).toBe("column");
  });

  it("series name is Days", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const s = series0(opt);
    expect(s.name).toBe("Days");
  });

  // ── data mapping ───────────────────────────────────────────────────────────
  it("maps counts to series data values", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const s = series0(opt);
    const values = (s.data as { y: number }[]).map((d: { y: number }) => d.y);
    expect(values).toEqual([5, 12, 20, 8]);
  });

  it("sets uniform bar color from colors.bar token on every bar", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const s = series0(opt);
    const colors = (s.data as { color: string }[]).map((d: { color: string }) => d.color);
    expect(colors.every((c: string) => c === TEST_COLORS.bar)).toBe(true);
  });

  // ── x-axis categories (bin midpoints as percent strings) ──────────────────
  it("sets xAxis categories to bin midpoint percent labels (1 dp)", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    const expected = [0, 1, 2, 3].map((i) =>
      formatPercent((HIST.bin_edges[i] + HIST.bin_edges[i + 1]) / 2, 1),
    );
    expect(xAxis.categories).toEqual(expected);
  });

  // ── y-axis formatter ───────────────────────────────────────────────────────
  it("formats y-axis labels with formatCompact", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 1234 });
    expect(out).toBe(formatCompact(1234));
  });

  // ── tooltip formatter ──────────────────────────────────────────────────────
  it("tooltip formatter returns midpoint label and compact count", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: string; y: number }) => string;
    };
    // x is the category label (midpoint percent string), y is the count
    const midLabel = formatPercent(
      (HIST.bin_edges[1] + HIST.bin_edges[2]) / 2,
      1,
    );
    const out = tooltip.formatter!.call({ x: midLabel, y: 12 });
    expect(out).toContain(midLabel);
    expect(out).toContain(formatCompact(12));
  });

  // ── opacity ───────────────────────────────────────────────────────────────
  it("applies opacity 0.75 to each bar", () => {
    const opt = buildHcHistogramOption(HIST, TEST_COLORS);
    const s = series0(opt);
    const opacities = (
      s.data as { opacity: number }[]
    ).map((d: { opacity: number }) => d.opacity);
    expect(opacities.every((o: number) => o === 0.75)).toBe(true);
  });

  // ── empty input ────────────────────────────────────────────────────────────
  it("returns empty series data for empty histogram", () => {
    const empty: Histogram = {
      bin_edges: [],
      counts: [],
      counts_normalized: [],
    };
    const opt = buildHcHistogramOption(empty, TEST_COLORS);
    const s = series0(opt);
    expect(s.data).toEqual([]);
  });

  it("returns empty xAxis categories for empty histogram", () => {
    const empty: Histogram = {
      bin_edges: [],
      counts: [],
      counts_normalized: [],
    };
    const opt = buildHcHistogramOption(empty, TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });

  // ── no null return for empty (histogram always returns Options) ───────────
  it("never returns null — returns a valid Options object even when empty", () => {
    const empty: Histogram = {
      bin_edges: [],
      counts: [],
      counts_normalized: [],
    };
    const opt = buildHcHistogramOption(empty, TEST_COLORS);
    expect(opt).not.toBeNull();
    expect(typeof opt).toBe("object");
  });
});
