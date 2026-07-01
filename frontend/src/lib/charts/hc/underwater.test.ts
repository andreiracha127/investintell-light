import { describe, expect, it } from "vitest";

import type { SeriesPoint } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import { buildHcUnderwaterOption } from "@/lib/charts/hc/underwater";
import { formatDate, formatPercent } from "@/lib/format";

const SERIES: SeriesPoint[] = [
  ["2024-01-01", 0],
  ["2024-01-02", -0.08],
  ["2024-01-03", -0.03],
];

describe("buildHcUnderwaterOption", () => {
  it("renders a single loss-toned area series", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    const series = opt.series?.[0] as {
      type?: string;
      color?: string;
      threshold?: number;
    };
    expect(series.type).toBe("area");
    expect(series.color).toBe(TEST_COLORS.loss);
    expect(series.threshold).toBe(0);
  });

  it("maps SeriesPoint dates and values to datetime pairs", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    const series = opt.series?.[0] as { data?: Array<[number, number]> };
    expect(series.data).toEqual([
      [dateToUtcMs("2024-01-01"), 0],
      [dateToUtcMs("2024-01-02"), -0.08],
      [dateToUtcMs("2024-01-03"), -0.03],
    ]);
  });

  it("pins the y-axis ceiling at zero", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    expect((opt.yAxis as { max?: number }).max).toBe(0);
  });

  it("formats y labels and tooltip values as percent", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(yAxis.labels!.formatter!.call({ value: -0.1 })).toBe(
      formatPercent(-0.1, 0),
    );
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: number; y: number }) => string;
    };
    const out = tooltip.formatter!.call({
      x: dateToUtcMs("2024-01-02"),
      y: -0.08,
    });
    expect(out).toContain(formatDate("2024-01-02"));
    expect(out).toContain(formatPercent(-0.08, 2));
  });

  it("uses a compact datetime x-axis", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    expect((opt.xAxis as { type?: string }).type).toBe("datetime");
  });

  it("returns empty series data for empty input", () => {
    const opt = buildHcUnderwaterOption([], "Drawdown", TEST_COLORS);
    expect((opt.series?.[0] as { data?: unknown[] }).data).toEqual([]);
  });

  it("does not re-set global chrome (theme owns grid/tooltip styling)", () => {
    const opt = buildHcUnderwaterOption(SERIES, "Drawdown", TEST_COLORS);
    expect((opt.yAxis as Record<string, unknown>).gridLineColor).toBeUndefined();
    expect((opt.tooltip as Record<string, unknown>).backgroundColor).toBeUndefined();
  });
});
