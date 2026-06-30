import { describe, expect, it } from "vitest";

import type { ConfidenceBar } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import {
  buildHcBuilderProjectionLinesOption,
  buildHcBuilderProjectionOption,
} from "@/lib/charts/hc/builder-projection";
import { formatNumber, formatPercent } from "@/lib/format";

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

describe("buildHcBuilderProjectionOption", () => {
  it("uses horizon labels as categories and returns three bands plus median", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);

    expect((option.xAxis as { categories?: string[] }).categories).toEqual([
      "1Y",
      "5Y",
    ]);
    expect(option.series).toHaveLength(4);
    expect((option.series ?? []).map((series) => series.name)).toEqual([
      "5–95%",
      "10–90%",
      "25–75%",
      "Median",
    ]);
  });

  it("maps band series to low-high pairs and median to scalar values", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    const band595 = option.series?.[0] as { data?: Array<[number, number]> };
    const median = option.series?.[3] as { data?: number[] };

    expect(band595.data).toEqual([
      [-0.1, 0.3],
      [-0.2, 1.6],
    ]);
    expect(median.data).toEqual([0.08, 0.5]);
  });

  it("uses distinct opacity for the nested bands", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    const band595 = option.series?.[0] as { fillOpacity?: number };
    const band1090 = option.series?.[1] as { fillOpacity?: number };
    const band2575 = option.series?.[2] as { fillOpacity?: number };

    expect(band595.fillOpacity).toBeLessThan(band1090.fillOpacity ?? 0);
    expect(band1090.fillOpacity).toBeLessThan(band2575.fillOpacity ?? 0);
  });

  it("renders a zero reference plot line on the value axis", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    const plotLines = (
      option.yAxis as { plotLines?: Array<{ value?: number }> }
    ).plotLines;

    expect(plotLines?.some((line) => line.value === 0)).toBe(true);
  });

  it("uses the supplied axis title", () => {
    const option = buildHcBuilderProjectionOption(
      BARS,
      "fraction",
      TEST_COLORS,
      "Projected Sharpe",
    );
    expect((option.yAxis as { title?: { text?: string } }).title?.text).toBe(
      "Projected Sharpe",
    );
  });

  it("signed-percent-formats the y-axis for fraction units", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    const labels = (
      option.yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;

    expect(labels?.formatter?.call({ value: 0.5 })).toBe(
      formatPercent(0.5, 0, { signed: true }),
    );
  });

  it("titles the x-axis 'Months · history → forecast'", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    expect((option.xAxis as { title?: { text?: string } }).title?.text).toBe(
      "Months · history → forecast",
    );
  });

  it("draws the median in the distinct blue token (not the accent)", () => {
    const option = buildHcBuilderProjectionOption(BARS, "fraction", TEST_COLORS);
    const median = option.series?.[3] as { color?: string };
    expect(median.color).toBe(TEST_COLORS.blue);
    expect(median.color).not.toBe(TEST_COLORS.accent);
  });

  it("number-formats the y-axis for unitless units", () => {
    const option = buildHcBuilderProjectionOption(BARS, "unitless", TEST_COLORS);
    const labels = (
      option.yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;

    expect(labels?.formatter?.call({ value: 1.25 })).toBe(formatNumber(1.25, 1));
  });
});

describe("buildHcBuilderProjectionLinesOption", () => {
  it("renders one line per percentile window plus the median, no shaded area", () => {
    const option = buildHcBuilderProjectionLinesOption(BARS, "fraction", TEST_COLORS);

    expect(option.chart?.type).toBe("line");
    const series = (option.series ?? []) as Array<{ name?: string; type?: string }>;
    expect(series.map((s) => s.name)).toEqual([
      "95th",
      "75th",
      "Median",
      "25th",
      "5th",
    ]);
    expect(series.every((s) => s.type === "line")).toBe(true);
  });

  it("maps each line series to the matching percentile across horizons", () => {
    const option = buildHcBuilderProjectionLinesOption(BARS, "fraction", TEST_COLORS);
    const p95 = option.series?.[0] as { data?: number[] };
    const median = option.series?.[2] as { data?: number[] };
    const p5 = option.series?.[4] as { data?: number[] };

    expect(p95.data).toEqual([0.3, 1.6]);
    expect(median.data).toEqual([0.08, 0.5]);
    expect(p5.data).toEqual([-0.1, -0.2]);
  });

  it("draws the median in the distinct blue token, solid and thicker than the percentile lines", () => {
    const option = buildHcBuilderProjectionLinesOption(BARS, "fraction", TEST_COLORS);
    const median = option.series?.[2] as {
      color?: string;
      dashStyle?: string;
      lineWidth?: number;
    };
    const p75 = option.series?.[1] as { lineWidth?: number };

    expect(median.color).toBe(TEST_COLORS.blue);
    expect(median.dashStyle).toBe("Solid");
    expect(median.lineWidth ?? 0).toBeGreaterThan(p75.lineWidth ?? 0);
  });

  it("uses the supplied axis title", () => {
    const option = buildHcBuilderProjectionLinesOption(
      BARS,
      "unitless",
      TEST_COLORS,
      "Projected Sharpe",
    );
    expect((option.yAxis as { title?: { text?: string } }).title?.text).toBe(
      "Projected Sharpe",
    );
  });
});
