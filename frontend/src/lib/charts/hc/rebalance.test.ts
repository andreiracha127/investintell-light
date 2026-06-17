import { describe, expect, it } from "vitest";

import { buildHcDriftBandsOption } from "@/lib/charts/hc/rebalance";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { PositionDrift } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

/**
 * Mirrors the legacy ECharts assertions in src/lib/charts/rebalance.ts:
 *   - null on empty input
 *   - sort by target_weight DESC then reverse() (net: ASC by target)
 *   - fractions -> percent-points (x100, 4dp)
 *   - half-band = max(min(bandAbs, target*bandRel)*100, 0.5)
 *   - bar = current weight; breach -> colors.loss else colors.bar
 *   - scatter = per-row target tick in colors.accent
 *   - tolerance bands per row (yAxis.plotBands) accent-wash
 *   - rich pp tooltip
 */

const BAND_ABS = 0.05; // 5 p.p.
const BAND_REL = 0.25; // 25% of target

const DRIFTS: PositionDrift[] = [
  // target 40%, current 47% -> drift_abs 0.07 > band_abs 0.05 -> breach
  {
    ticker: "AAA",
    current_weight: 0.47,
    target_weight: 0.4,
    drift_abs: 0.07,
    drift_rel: 0.175,
    breach: true,
    status: "urgent",
  },
  // target 35%, current 34% -> within band -> safe
  {
    ticker: "BBB",
    current_weight: 0.34,
    target_weight: 0.35,
    drift_abs: -0.01,
    drift_rel: -0.0286,
    breach: false,
    status: "ok",
  },
  // target 25%, current 19% -> safe
  {
    ticker: "CCC",
    current_weight: 0.19,
    target_weight: 0.25,
    drift_abs: -0.06,
    drift_rel: -0.24,
    breach: false,
    status: "ok",
  },
];

describe("buildHcDriftBandsOption", () => {
  it("returns null on empty input", () => {
    expect(buildHcDriftBandsOption([], TEST_COLORS, BAND_ABS, BAND_REL)).toBeNull();
  });

  it("uses a horizontal bar chart", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    expect(opt.chart?.type).toBe("bar");
  });

  it("sorts rows by target_weight DESC then reverse (net ASC) for the category axis", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const cats = (opt.xAxis as { categories?: string[] }).categories;
    // target weights: AAA .40, BBB .35, CCC .25 ; sort desc -> AAA,BBB,CCC ; reverse -> CCC,BBB,AAA
    expect(cats).toEqual(["CCC", "BBB", "AAA"]);
  });

  it("maps current weight -> bar series in percent-points, coloring breaches with loss", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const bar = opt.series?.find((s) => (s as { type?: string }).type === "bar") as {
      data?: Array<{ y: number; color: string }>;
      name?: string;
    };
    expect(bar.name).toBe("Current weight");
    // order CCC, BBB, AAA -> current 19, 34, 47
    expect(bar.data?.map((d) => d.y)).toEqual([19, 34, 47]);
    // CCC safe -> bar, BBB safe -> bar, AAA breach -> loss
    expect(bar.data?.map((d) => d.color)).toEqual([
      TEST_COLORS.bar,
      TEST_COLORS.bar,
      TEST_COLORS.loss,
    ]);
  });

  it("maps target weight -> scatter ticks in accent, anchored to each row index", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const scatter = opt.series?.find((s) => (s as { type?: string }).type === "scatter") as {
      data?: Array<{ x: number; y: number }>;
      color?: string;
      name?: string;
    };
    expect(scatter.name).toBe("Target weight");
    expect(scatter.color).toBe(TEST_COLORS.accent);
    // order CCC, BBB, AAA -> target 25, 35, 40 ; x = category index, y = targetPct
    expect(scatter.data).toEqual([
      { x: 0, y: 25 },
      { x: 1, y: 35 },
      { x: 2, y: 40 },
    ]);
  });

  it("emits one accent-wash tolerance band per row on the value (y) axis", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const bands = (opt.yAxis as { plotBands?: Array<{ from: number; to: number; color: string }> })
      .plotBands;
    expect(bands).toHaveLength(3);
    expect(bands?.every((b) => b.color === TEST_COLORS.accentWash)).toBe(true);
    // CCC: target 25, half = min(5, 25*0.25=6.25)=5 -> [20,30]
    expect(bands?.[0]?.from).toBeCloseTo(20, 4);
    expect(bands?.[0]?.to).toBeCloseTo(30, 4);
    // AAA: target 40, half = min(5, 40*0.25=10)=5 -> [35,45]
    expect(bands?.[2]?.from).toBeCloseTo(35, 4);
    expect(bands?.[2]?.to).toBeCloseTo(45, 4);
  });

  it("floors the half-band at 0.5pp for tiny targets", () => {
    const tiny: PositionDrift[] = [
      {
        ticker: "TINY",
        current_weight: 0.001,
        target_weight: 0.001,
        drift_abs: 0,
        drift_rel: 0,
        breach: false,
        status: "ok",
      },
    ];
    const opt = buildHcDriftBandsOption(tiny, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const bands = (opt.yAxis as { plotBands?: Array<{ from: number; to: number }> }).plotBands;
    // target 0.1pp; min(5, 0.1*0.25=0.025)=0.025 -> floored to 0.5 -> [-0.4, 0.6]
    expect(bands?.[0]?.from).toBeCloseTo(-0.4, 4);
    expect(bands?.[0]?.to).toBeCloseTo(0.6, 4);
  });

  it("formats the value axis labels as integer percent", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const yAxis = opt.yAxis as { labels?: { formatter?: (this: { value: number }) => string } };
    expect(yAxis.labels!.formatter!.call({ value: 25 })).toBe("25%");
    expect(yAxis.labels!.formatter!.call({ value: 12.7 })).toBe("13%");
  });

  it("renders a rich pp deviation tooltip with breach styling", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    // The REAL Highcharts tooltip context exposes the hovered point as
    // `this.point` and the category row index as `this.point.index`. The old
    // test called `.call({ index })`, which matched the buggy `this.index`
    // read and masked the blank-tooltip bug. Drive it with the true shape.
    const tooltip = opt.tooltip as {
      formatter?: (this: { point: { index: number } }) => string;
    };
    // AAA is at row index 2 (order CCC,BBB,AAA); breach=true, dev = .47-.40 = +0.07 = +7.00pp
    const out = tooltip!.formatter!.call({ point: { index: 2 } });
    expect(out).toContain("AAA");
    expect(out).toContain("Out of band");
    expect(out).toContain(TEST_COLORS.loss);
    expect(out).toContain("+7.00pp");
    expect(out).toContain(formatPercent(0.47, 2)); // Current
    expect(out).toContain(formatPercent(0.4, 2)); // Target

    // CCC at row 0 is safe; dev = .19-.25 = -0.06 = -6.00pp ; no breach tag
    const safe = tooltip!.formatter!.call({ point: { index: 0 } });
    expect(safe).toContain("CCC");
    expect(safe).not.toContain("Out of band");
    expect(safe).toContain("-6.00pp");

    // Empty-row guard: an out-of-range index resolves to no row -> blank string
    // (this is the path the `this.index` bug used to hit on EVERY hover).
    const empty = tooltip!.formatter!.call({ point: { index: 99 } });
    expect(empty).toBe("");
  });
});
