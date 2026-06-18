import { describe, expect, it } from "vitest";

import { buildHcRollingCorrelationAreaOption } from "@/lib/charts/hc/stats-rolling-area";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import type { SeriesPoint } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

const SERIES: SeriesPoint[] = [
  ["2024-01-01", 0.42],
  ["2024-01-02", -0.18],
  ["2024-01-03", 0.31],
];

describe("buildHcRollingCorrelationAreaOption", () => {
  it("chart type is area", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    expect((opt.chart as { type?: string }).type).toBe("area");
  });

  it("fixes the y-axis to the -1..1 correlation band with half-unit ticks", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const yAxis = opt.yAxis as { min?: number; max?: number; tickInterval?: number };
    expect(yAxis.min).toBe(-1);
    expect(yAxis.max).toBe(1);
    expect(yAxis.tickInterval).toBe(0.5);
  });

  it("draws a dashed zero reference plot line", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const lines = (opt.yAxis as { plotLines?: Array<{ value: number; dashStyle?: string }> })
      .plotLines!;
    expect(lines).toHaveLength(1);
    expect(lines[0].value).toBe(0);
    expect(lines[0].dashStyle).toBe("Dash");
  });

  it("maps SeriesPoint dates and values to series data", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const series = opt.series?.[0] as { data?: Array<[number, number]> };
    expect(series.data).toEqual([
      [dateToUtcMs("2024-01-01"), 0.42],
      [dateToUtcMs("2024-01-02"), -0.18],
      [dateToUtcMs("2024-01-03"), 0.31],
    ]);
  });

  it("fills toward zero (threshold 0) with an accent gradient", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const series = opt.series?.[0] as { threshold?: number; color?: string };
    expect(series.threshold).toBe(0);
    expect(series.color).toBe(TEST_COLORS.accent);
  });

  it("uses the provided label as the series name", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const series = opt.series?.[0] as { name?: string };
    expect(series.name).toBe("SPY × Port");
  });

  it("y-axis labels are formatted to one decimal", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(yAxis.labels!.formatter!.call({ value: 0.5 })).toBe(formatNumber(0.5, 1));
  });

  it("tooltip formatter includes the label and a 3-dp value", () => {
    const opt = buildHcRollingCorrelationAreaOption(SERIES, "SPY × Port", TEST_COLORS);
    const tooltip = opt.tooltip as { formatter?: (this: unknown) => string };
    const out = tooltip.formatter!.call({ x: dateToUtcMs("2024-01-01"), y: 0.421 });
    expect(out).toContain("SPY × Port");
    expect(out).toContain(formatNumber(0.421, 3));
  });
});
