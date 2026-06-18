import { describe, expect, it } from "vitest";

import type { ConfidenceBar } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { buildHcConeOption } from "@/lib/charts/hc/cone";
import { formatPercent } from "@/lib/format";

const BARS: ConfidenceBar[] = [
  {
    horizon: "1Y",
    horizon_days: 252,
    pct_5: -0.1,
    pct_10: -0.05,
    pct_25: 0,
    pct_50: 0.08,
    pct_75: 0.16,
    pct_90: 0.24,
    pct_95: 0.3,
    mean: 0.09,
  },
  {
    horizon: "5Y",
    horizon_days: 1260,
    pct_5: -0.2,
    pct_10: -0.1,
    pct_25: 0.1,
    pct_50: 0.5,
    pct_75: 0.9,
    pct_90: 1.3,
    pct_95: 1.6,
    mean: 0.55,
  },
];

describe("buildHcConeOption", () => {
  it("uses horizon labels as categories and returns three bands plus median", () => {
    const option = buildHcConeOption(BARS, "fraction", TEST_COLORS);

    expect((option.xAxis as { categories?: string[] }).categories).toEqual([
      "1Y",
      "5Y",
    ]);
    expect(option.series).toHaveLength(4);
    expect((option.series ?? []).map((series) => series.name)).toEqual([
      "5-95%",
      "10-90%",
      "25-75%",
      "Median",
    ]);
  });

  it("maps band series to low-high pairs and median to scalar values", () => {
    const option = buildHcConeOption(BARS, "fraction", TEST_COLORS);
    const band595 = option.series?.[0] as { data?: Array<[number, number]> };
    const band1090 = option.series?.[1] as { data?: Array<[number, number]> };
    const band2575 = option.series?.[2] as { data?: Array<[number, number]> };
    const median = option.series?.[3] as { data?: number[] };

    expect(band595.data).toEqual([
      [-0.1, 0.3],
      [-0.2, 1.6],
    ]);
    expect(band1090.data).toEqual([
      [-0.05, 0.24],
      [-0.1, 1.3],
    ]);
    expect(band2575.data).toEqual([
      [0, 0.16],
      [0.1, 0.9],
    ]);
    expect(median.data).toEqual([0.08, 0.5]);
  });

  it("uses distinct opacity for the nested bands", () => {
    const option = buildHcConeOption(BARS, "fraction", TEST_COLORS);
    const band595 = option.series?.[0] as { fillOpacity?: number };
    const band1090 = option.series?.[1] as { fillOpacity?: number };
    const band2575 = option.series?.[2] as { fillOpacity?: number };

    expect(band595.fillOpacity).toBeLessThan(band1090.fillOpacity ?? 0);
    expect(band1090.fillOpacity).toBeLessThan(band2575.fillOpacity ?? 0);
  });

  it("percent-formats the y-axis for fraction units", () => {
    const option = buildHcConeOption(BARS, "fraction", TEST_COLORS);
    const labels = (
      option.yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;

    expect(labels?.formatter?.call({ value: 0.5 })).toBe(
      formatPercent(0.5, 0),
    );
  });

  it("can register the arearange series module used by the cone", async () => {
    const mod = await import("highcharts/esm/highcharts.js");
    await import("highcharts/esm/highcharts-more.js");
    const Highcharts = mod.default as unknown as {
      SeriesRegistry?: { seriesTypes?: Record<string, unknown> };
    };

    expect(Highcharts.SeriesRegistry?.seriesTypes?.arearange).toBeDefined();
  });
});
