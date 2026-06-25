import { describe, expect, it } from "vitest";

import { buildHcDriftBandsOption } from "@/lib/charts/hc/rebalance";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { PositionDrift } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

/**
 * Claude Design drift chart: a SINGLE signed-drift (current − target) bar per
 * position.
 *   - null on empty input
 *   - horizontal bar chart, sorted by signed drift (largest positive at top)
 *   - drift = (current − target) × 100, p.p.
 *   - bar loss-colored when |drift| > band_abs, else neutral graphite
 *   - 0 plotLine + ONE symmetric accent-wash ±band plotBand with a label
 *   - y-axis title "Drift vs. target (p.p.)"
 *   - per-bar signed p.p. data labels
 *   - rich tooltip with band-breach styling
 */

const BAND_ABS = 0.05; // 5 p.p.
const BAND_REL = 0.25; // 25% of target (accepted, not drawn)

const DRIFTS: PositionDrift[] = [
  // target 40%, current 47% -> drift +7 p.p. -> |7| > 5 -> breach
  {
    ticker: "AAA",
    current_weight: 0.47,
    target_weight: 0.4,
    drift_abs: 0.07,
    drift_rel: 0.175,
    breach: true,
    status: "urgent",
  },
  // target 35%, current 34% -> drift -1 p.p. -> within band
  {
    ticker: "BBB",
    current_weight: 0.34,
    target_weight: 0.35,
    drift_abs: -0.01,
    drift_rel: -0.0286,
    breach: false,
    status: "ok",
  },
  // target 25%, current 19% -> drift -6 p.p. -> |6| > 5 -> breach
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

  it("sorts categories by signed drift ascending (so largest positive draws on top)", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const cats = (opt.xAxis as { categories?: string[] }).categories;
    // drift: AAA +7, BBB -1, CCC -6 ; ascending -> CCC(-6), BBB(-1), AAA(+7)
    expect(cats).toEqual(["CCC", "BBB", "AAA"]);
  });

  it("uses sanitized display labels when provided instead of ticker categories", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL, {
      AAA: "Alpha Core",
      BBB: "Beta Income",
      CCC: "Credit Sleeve",
    })!;
    const cats = (opt.xAxis as { categories?: string[] }).categories;
    expect(cats).toEqual(["Credit Sleeve", "Beta Income", "Alpha Core"]);

    const tooltip = opt.tooltip as {
      formatter?: (this: { point: { index: number } }) => string;
    };
    const out = tooltip!.formatter!.call({ point: { index: 2 } });
    expect(out).toContain("Alpha Core");
    expect(out).not.toContain("<b>AAA</b>");
  });

  it("maps signed drift -> single bar series in p.p., coloring out-of-band rows with loss", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    expect(opt.series).toHaveLength(1);
    const bar = opt.series![0] as { type?: string; name?: string; data?: Array<{ y: number; color: string }> };
    expect(bar.type).toBe("bar");
    expect(bar.name).toBe("Drift");
    // order CCC, BBB, AAA -> drift -6, -1, +7
    expect(bar.data?.map((d) => d.y)).toEqual([-6, -1, 7]);
    // |drift| > 5 -> loss (CCC, AAA); BBB within band -> neutral
    expect(bar.data?.map((d) => d.color)).toEqual([
      TEST_COLORS.loss,
      TEST_COLORS.bar,
      TEST_COLORS.loss,
    ]);
  });

  it("titles the value axis 'Drift vs. target (p.p.)'", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const yAxis = opt.yAxis as { title?: { text?: string } };
    expect(yAxis.title?.text).toBe("Drift vs. target (p.p.)");
  });

  it("draws a single 0 plotLine and ONE symmetric accent-wash ±band with a label", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const yAxis = opt.yAxis as {
      plotLines?: Array<{ value: number }>;
      plotBands?: Array<{ from: number; to: number; color: string; label?: { text?: string } }>;
    };
    expect(yAxis.plotLines).toHaveLength(1);
    expect(yAxis.plotLines?.[0]?.value).toBe(0);
    expect(yAxis.plotBands).toHaveLength(1);
    const band = yAxis.plotBands![0]!;
    expect(band.from).toBeCloseTo(-5, 4);
    expect(band.to).toBeCloseTo(5, 4);
    expect(band.color).toBe(TEST_COLORS.accentWash);
    expect(band.label?.text).toContain("±5");
  });

  it("formats the value axis labels as signed integer percent-points", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const yAxis = opt.yAxis as { labels?: { formatter?: (this: { value: number }) => string } };
    expect(yAxis.labels!.formatter!.call({ value: 5 })).toBe("+5");
    expect(yAxis.labels!.formatter!.call({ value: -3 })).toBe("−3");
    expect(yAxis.labels!.formatter!.call({ value: 0 })).toBe("0");
  });

  it("renders per-bar signed p.p. data labels", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const dl = (opt.plotOptions?.bar?.dataLabels ?? {}) as {
      enabled?: boolean;
      formatter?: (this: { y: number }) => string;
    };
    expect(dl.enabled).toBe(true);
    expect(dl.formatter!.call({ y: 7 })).toBe("+7.0 p.p.");
    expect(dl.formatter!.call({ y: -6 })).toBe("−6.0 p.p.");
  });

  it("uses slim bars for the negative-stack drift treatment", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    expect(opt.plotOptions?.bar?.pointWidth).toBe(14);
    expect(opt.plotOptions?.bar?.borderRadius).toBe(2);
  });

  it("renders a rich tooltip with band-breach styling", () => {
    const opt = buildHcDriftBandsOption(DRIFTS, TEST_COLORS, BAND_ABS, BAND_REL)!;
    const tooltip = opt.tooltip as {
      formatter?: (this: { point: { index: number } }) => string;
    };
    // AAA at row index 2 (order CCC,BBB,AAA); breach, drift +7.00 p.p.
    const out = tooltip!.formatter!.call({ point: { index: 2 } });
    expect(out).toContain("AAA");
    expect(out).toContain("band breach");
    expect(out).toContain(TEST_COLORS.loss);
    expect(out).toContain("+7.00 p.p.");
    expect(out).toContain(formatPercent(0.47, 2)); // Current
    expect(out).toContain(formatPercent(0.4, 2)); // Target

    // BBB at row 1 is within band; drift -1.00 p.p. ; no breach tag
    const safe = tooltip!.formatter!.call({ point: { index: 1 } });
    expect(safe).toContain("BBB");
    expect(safe).not.toContain("band breach");
    expect(safe).toContain("−1.00 p.p.");

    // Out-of-range index -> blank string (empty-row guard).
    expect(tooltip!.formatter!.call({ point: { index: 99 } })).toBe("");
  });
});
