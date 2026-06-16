import { describe, expect, it } from "vitest";

import { buildHcDistributionOption } from "@/lib/charts/hc/distribution";
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
function series0(opt: ReturnType<typeof buildHcDistributionOption>) {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  return opt!.series![0] as any;
}

// ── tests ─────────────────────────────────────────────────────────────────────
describe("buildHcDistributionOption", () => {
  // ── basic structure ──────────────────────────────────────────────────────
  it("returns a column chart", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    expect(opt?.chart).toMatchObject({ type: "column" });
  });

  it("series type is column", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const s = series0(opt);
    expect(s.type).toBe("column");
  });

  it("maps counts_normalized to series data values", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const s = series0(opt);
    const values = (s.data as { y: number }[]).map((d) => d.y);
    expect(values).toEqual([0.5, 1.0, 0.25, 0.75]);
  });

  // ── in-band / out-of-band coloring ───────────────────────────────────────
  //   bin 0: [0, 0.1]  — hi=0.1 >= min=0.1 AND lo=0 <= max=0.25  → accent
  //   bin 1: [0.1, 0.2] — hi=0.2 >= 0.1 AND lo=0.1 <= 0.25       → accent
  //   bin 2: [0.2, 0.3] — hi=0.3 >= 0.1 AND lo=0.2 <= 0.25       → accent
  //   bin 3: [0.3, 0.4] — hi=0.4 >= 0.1 BUT lo=0.3 > max=0.25    → bar
  it("colors in-band bars with accent, out-of-band bars with bar", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const s = series0(opt);
    const colors = (s.data as { color: string }[]).map((d) => d.color);
    expect(colors[0]).toBe(TEST_COLORS.accent); // bin [0, 0.1]: hi==min => in-band
    expect(colors[1]).toBe(TEST_COLORS.accent); // bin [0.1, 0.2]
    expect(colors[2]).toBe(TEST_COLORS.accent); // bin [0.2, 0.3]: lo=0.2 <= max=0.25
    expect(colors[3]).toBe(TEST_COLORS.bar);    // bin [0.3, 0.4]: lo=0.3 > max=0.25
  });

  it("colors all bars accent when band is fully open (null/null)", () => {
    const opt = buildHcDistributionOption(
      DIST,
      { min: null, max: null },
      "percent",
      TEST_COLORS,
    );
    const s = series0(opt);
    const colors = (s.data as { color: string }[]).map((d) => d.color);
    expect(colors.every((c) => c === TEST_COLORS.accent)).toBe(true);
  });

  it("colors all bars bar when no bin overlaps the band", () => {
    // band [0.5, 0.9] — all bins end at 0.4, none reach 0.5
    const opt = buildHcDistributionOption(
      DIST,
      { min: 0.5, max: 0.9 },
      "percent",
      TEST_COLORS,
    );
    const s = series0(opt);
    const colors = (s.data as { color: string }[]).map((d) => d.color);
    expect(colors.every((c) => c === TEST_COLORS.bar)).toBe(true);
  });

  // ── x-axis labels (bin midpoints via formatMetricValue) ──────────────────
  it("sets xAxis categories to midpoint labels using formatMetricValue", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const xAxis = opt?.xAxis as { categories?: string[] };
    const expectedLabels = [0, 1, 2, 3].map((i) =>
      formatMetricValue((DIST.bin_edges[i] + DIST.bin_edges[i + 1]) / 2, "percent"),
    );
    expect(xAxis.categories).toEqual(expectedLabels);
  });

  it("uses formatMetricValue with the supplied dataType for labels", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "currency", TEST_COLORS);
    const xAxis = opt?.xAxis as { categories?: string[] };
    const expectedLabels = [0, 1, 2, 3].map((i) =>
      formatMetricValue((DIST.bin_edges[i] + DIST.bin_edges[i + 1]) / 2, "currency"),
    );
    expect(xAxis.categories).toEqual(expectedLabels);
  });

  // ── y-axis: hidden, max 1 ────────────────────────────────────────────────
  it("hides the yAxis and sets max to 1", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const yAxis = opt?.yAxis as { visible?: boolean; max?: number };
    expect(yAxis.visible).toBe(false);
    expect(yAxis.max).toBe(1);
  });

  // ── tooltip formatter ────────────────────────────────────────────────────
  it("tooltip formatter returns label and compact count", () => {
    const opt = buildHcDistributionOption(DIST, BAND, "percent", TEST_COLORS);
    const tooltip = opt?.tooltip as {
      // Real Highcharts runtime shape: this is Point, index lives directly on it.
      formatter?: (this: { index: number }) => string;
    };
    const out = tooltip.formatter!.call({ index: 1 });
    // label for bin 1 midpoint = 0.15
    const expectedLabel = formatMetricValue(0.15, "percent");
    expect(out).toContain(expectedLabel);
    expect(out).toContain(formatCompact(DIST.counts[1]));
    expect(out).toContain("companies");
  });

  // ── empty distribution ────────────────────────────────────────────────────
  it("returns empty series data for an empty distribution", () => {
    const empty: Distribution = {
      bin_edges: [],
      counts: [],
      counts_normalized: [],
    };
    const opt = buildHcDistributionOption(
      empty,
      { min: null, max: null },
      "percent",
      TEST_COLORS,
    );
    const s = series0(opt);
    expect(s.data).toEqual([]);
  });

  it("returns empty xAxis categories for an empty distribution", () => {
    const empty: Distribution = {
      bin_edges: [],
      counts: [],
      counts_normalized: [],
    };
    const opt = buildHcDistributionOption(
      empty,
      { min: null, max: null },
      "percent",
      TEST_COLORS,
    );
    const xAxis = opt?.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([]);
  });
});
