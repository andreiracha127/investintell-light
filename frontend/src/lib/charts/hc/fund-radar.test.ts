import { describe, expect, it } from "vitest";

import { buildHcFactorRadarOption } from "@/lib/charts/hc/fund-radar";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { FundFactors } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

function makeFactors(): FundFactors {
  return {
    instrument_id: "fund-1",
    market_sensitivities: [],
    style_bias: [
      { factor: "Value", value: 0.7, z_score: 1.2, as_of: "2026-03-31" },
      { factor: "Growth", value: -0.3, z_score: -0.8, as_of: "2026-03-31" },
      { factor: "Size", value: 0.1, z_score: 0.4, as_of: "2026-03-31" },
      { factor: "Quality", value: 1.0, z_score: 2.6, as_of: "2026-03-31" },
      { factor: "Yield", value: -0.5, z_score: -1.1, as_of: "2026-03-31" },
    ],
    source_metadata: [],
  } as FundFactors;
}

describe("buildHcFactorRadarOption", () => {
  it("is a polar area chart", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    const chart = opt.chart as { polar?: boolean; type?: string };
    expect(chart.polar).toBe(true);
    expect(chart.type).toBe("area");
  });

  it("maps one category per style factor", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([
      "Value",
      "Growth",
      "Size",
      "Quality",
      "Yield",
    ]);
  });

  it("plots z-scores as the single series", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    expect(opt.series).toHaveLength(1);
    const s = opt.series?.[0] as { data?: number[]; color?: string };
    expect(s.data).toEqual([1.2, -0.8, 0.4, 2.6, -1.1]);
    expect(s.color).toBe(TEST_COLORS.accent);
  });

  it("uses a symmetric axis bound that clears the largest z-score", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    const yAxis = opt.yAxis as { min?: number; max?: number };
    // peak |z| = 2.6 → ceil 3
    expect(yAxis.max).toBe(3);
    expect(yAxis.min).toBe(-3);
  });

  it("never collapses the axis below ±2", () => {
    const flat = makeFactors();
    flat.style_bias = flat.style_bias.map((b) => ({ ...b, z_score: 0.1 }));
    const opt = buildHcFactorRadarOption(flat, TEST_COLORS);
    const yAxis = opt.yAxis as { min?: number; max?: number };
    expect(yAxis.max).toBe(2);
    expect(yAxis.min).toBe(-2);
  });

  it("emphasizes the zero ring with a plot line", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    const yAxis = opt.yAxis as { plotLines?: { value?: number }[] };
    expect(yAxis.plotLines?.[0]?.value).toBe(0);
  });

  it("treats a null z_score as zero", () => {
    const f = makeFactors();
    f.style_bias = [
      { factor: "Value", value: null, z_score: null, as_of: null },
    ];
    const opt = buildHcFactorRadarOption(f, TEST_COLORS);
    const s = opt.series?.[0] as { data?: number[] };
    expect(s.data).toEqual([0]);
  });

  it("tooltip formatter reports the z-score and raw value", () => {
    const opt = buildHcFactorRadarOption(makeFactors(), TEST_COLORS);
    const tooltip = opt.tooltip as { formatter?: (this: unknown) => string };
    const out = tooltip.formatter!.call({
      x: "Value",
      y: 1.2,
      index: 0,
    });
    expect(out).toContain("Value");
    expect(out).toContain(`z ${formatNumber(1.2, 2)}`);
    expect(out).toContain(`raw ${formatNumber(0.7)}`);
  });
});
