import { describe, expect, it } from "vitest";

import {
  buildHcBellCurveOption,
  momentsFromHistogram,
} from "@/lib/charts/hc/stats-bellcurve";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { Histogram } from "@/lib/api/client";

// Symmetric histogram centered on 0 with edges in decimal-fraction units.
const HISTOGRAM: Histogram = {
  bin_edges: [-0.03, -0.02, -0.01, 0, 0.01, 0.02, 0.03],
  counts: [1, 4, 10, 10, 4, 1],
  counts_normalized: [0.1, 0.4, 1, 1, 0.4, 0.1],
};

describe("momentsFromHistogram", () => {
  it("estimates ~zero mean for a symmetric histogram", () => {
    const { mean } = momentsFromHistogram(HISTOGRAM);
    expect(Math.abs(mean)).toBeLessThan(1e-9);
  });

  it("estimates a positive standard deviation", () => {
    const { sd } = momentsFromHistogram(HISTOGRAM);
    expect(sd).toBeGreaterThan(0);
  });

  it("returns a safe sd floor for empty counts", () => {
    const { mean, sd } = momentsFromHistogram({
      bin_edges: [0, 1],
      counts: [0],
      counts_normalized: [0],
    });
    expect(mean).toBe(0);
    expect(sd).toBeGreaterThan(0);
  });
});

describe("buildHcBellCurveOption", () => {
  it("chart type is areaspline", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    expect((opt.chart as { type?: string }).type).toBe("areaspline");
  });

  it("returns two series: the ±1σ band and the distribution curve", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    expect(opt.series).toHaveLength(2);
    const names = (opt.series as Array<{ name: string }>).map((s) => s.name);
    expect(names).toEqual(["±1σ", "Distribution"]);
  });

  it("the ±1σ band disables mouse tracking", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    const band = opt.series?.[0] as { enableMouseTracking?: boolean };
    expect(band.enableMouseTracking).toBe(false);
  });

  it("the curve is a non-empty list of [x, density] pairs", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    const curve = opt.series?.[1] as { data?: Array<[number, number]> };
    expect(curve.data!.length).toBeGreaterThan(10);
    expect(curve.data![0]).toHaveLength(2);
  });

  it("draws Mean and VaR 95 reference plot lines, VaR on the loss side", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    const lines = (opt.xAxis as { plotLines?: Array<{ value: number; label?: { text?: string } }> })
      .plotLines!;
    const labels = lines.map((l) => l.label?.text);
    expect(labels).toContain("Mean");
    expect(labels).toContain("VaR 95");
    const varLine = lines.find((l) => l.label?.text === "VaR 95")!;
    // var_95 = 0.02 (positive loss) → line at -2(%)
    expect(varLine.value).toBeCloseTo(-2, 6);
  });

  it("x-axis labels are percent-formatted from percent-scaled values", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    const xAxis = opt.xAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(xAxis.labels!.formatter!.call({ value: 1 })).toContain("%");
  });

  it("colors the curve with the accent token", () => {
    const opt = buildHcBellCurveOption(HISTOGRAM, 0.02, TEST_COLORS);
    const curve = opt.series?.[1] as { color?: string };
    expect(curve.color).toBe(TEST_COLORS.accent);
  });
});
