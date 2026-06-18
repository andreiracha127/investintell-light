import { describe, expect, it } from "vitest";

import { buildHcScreenerDistributionOption } from "@/lib/charts/hc/screener-distribution";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { Distribution } from "@/lib/api/client";
import { formatCompact, formatMetricValue } from "@/lib/format";

// ── fixtures ──────────────────────────────────────────────────────────────────
const DIST: Distribution = {
  bin_edges: [0, 0.1, 0.2, 0.3, 0.4],
  counts: [10, 20, 5, 15],
  counts_normalized: [0.5, 1.0, 0.25, 0.75],
};

const BAND = { min: 0.1, max: 0.25 };

// ── helpers ───────────────────────────────────────────────────────────────────
/** Extracts first series (column) from the option. */
function series0(opt: ReturnType<typeof buildHcScreenerDistributionOption>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return opt!.series![0] as any;
}

// ── tests ─────────────────────────────────────────────────────────────────────
describe("buildHcScreenerDistributionOption", () => {
  // ── basic structure ──────────────────────────────────────────────────────
  it("returns a column chart", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    expect(opt?.chart).toMatchObject({ type: "column" });
  });

  it("series type is column", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    expect(series0(opt).type).toBe("column");
  });

  it("plots REAL counts (not normalized) as series y-values", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const ys = (series0(opt).data as { y: number }[]).map((d) => d.y);
    expect(ys).toEqual([10, 20, 5, 15]);
  });

  it("places points at bin midpoints on a numeric x-axis", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const xs = (series0(opt).data as { x: number }[]).map((d) => d.x);
    [0.05, 0.15, 0.25, 0.35].forEach((expected, i) => expect(xs[i]).toBeCloseTo(expected, 10));
  });

  // ── in-band / out-of-band coloring ───────────────────────────────────────
  //   bin 0: [0, 0.1]  — hi=0.1 >= min=0.1 AND lo=0 <= max=0.25  → accent
  //   bin 1: [0.1, 0.2] — in range                                → accent
  //   bin 2: [0.2, 0.3] — lo=0.2 <= max=0.25                      → accent
  //   bin 3: [0.3, 0.4] — lo=0.3 > max=0.25                       → barMute
  it("colors in-band bars accent, out-of-band bars muted grey (barMute)", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const colors = (series0(opt).data as { color: string }[]).map((d) => d.color);
    expect(colors[0]).toBe(TEST_COLORS.accent);
    expect(colors[1]).toBe(TEST_COLORS.accent);
    expect(colors[2]).toBe(TEST_COLORS.accent);
    expect(colors[3]).toBe(TEST_COLORS.barMute);
  });

  it("colors all bars accent when the band is fully open (null/null)", () => {
    const opt = buildHcScreenerDistributionOption(DIST, { min: null, max: null }, "percent", TEST_COLORS);
    const colors = (series0(opt).data as { color: string }[]).map((d) => d.color);
    expect(colors.every((c) => c === TEST_COLORS.accent)).toBe(true);
  });

  it("colors all bars muted grey when no bin overlaps the band", () => {
    const opt = buildHcScreenerDistributionOption(DIST, { min: 0.5, max: 0.9 }, "percent", TEST_COLORS);
    const colors = (series0(opt).data as { color: string }[]).map((d) => d.color);
    expect(colors.every((c) => c === TEST_COLORS.barMute)).toBe(true);
  });

  // ── y-axis: visible "Companies" title ────────────────────────────────────
  it('titles the y-axis "Companies" and disallows decimals', () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const yAxis = opt?.yAxis as { title?: { text?: string }; allowDecimals?: boolean };
    expect(yAxis.title?.text).toBe("Companies");
    expect(yAxis.allowDecimals).toBe(false);
  });

  // ── x-axis: tickPositioner returns ~5 ticks across the domain ────────────
  it("x-axis tickPositioner returns 5 ticks spanning the bin domain", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const xAxis = opt?.xAxis as { tickPositioner?: () => number[] };
    const ticks = xAxis.tickPositioner!.call({});
    expect(ticks).toHaveLength(5);
    [0, 0.1, 0.2, 0.3, 0.4].forEach((expected, i) => expect(ticks[i]).toBeCloseTo(expected, 10));
  });

  it("x-axis label formatter uses formatMetricValue for the supplied dataType", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "currency", TEST_COLORS);
    const xAxis = opt?.xAxis as { labels?: { formatter?: (this: { value: number }) => string } };
    const out = xAxis.labels!.formatter!.call({ value: 0.2 });
    expect(out).toBe(formatMetricValue(0.2, "currency"));
  });

  // ── tooltip: bin range + count ────────────────────────────────────────────
  it("tooltip formatter shows the bin value range and a compact count", () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const tooltip = opt?.tooltip as { formatter?: (this: { x: number; y: number }) => string };
    // bar at midpoint 0.15, bin width 0.1 → range 0.10–0.20
    const out = tooltip.formatter!.call({ x: 0.15, y: 20 });
    expect(out).toContain(formatMetricValue(0.1, "percent"));
    expect(out).toContain(formatMetricValue(0.2, "percent"));
    expect(out).toContain(formatCompact(20));
    expect(out).toContain("companies");
  });

  it('tooltip uses the singular "company" for a count of 1', () => {
    const opt = buildHcScreenerDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const tooltip = opt?.tooltip as { formatter?: (this: { x: number; y: number }) => string };
    const out = tooltip.formatter!.call({ x: 0.35, y: 1 });
    expect(out).toContain("company");
    expect(out).not.toContain("companies");
  });

  // ── empty distribution ────────────────────────────────────────────────────
  it("returns empty series data for an empty distribution", () => {
    const empty: Distribution = { bin_edges: [], counts: [], counts_normalized: [] };
    const opt = buildHcScreenerDistributionOption(empty, { min: null, max: null }, "percent", TEST_COLORS);
    expect(series0(opt).data).toEqual([]);
  });

  it("does not set a column pointRange for an empty distribution", () => {
    const empty: Distribution = { bin_edges: [], counts: [], counts_normalized: [] };
    const opt = buildHcScreenerDistributionOption(empty, { min: null, max: null }, "percent", TEST_COLORS);
    const column = (opt?.plotOptions as { column?: { pointRange?: number } }).column;
    expect(column?.pointRange).toBeUndefined();
  });
});
