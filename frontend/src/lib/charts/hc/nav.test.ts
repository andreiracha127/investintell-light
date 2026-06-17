import { describe, expect, it } from "vitest";

import { buildHcNavOption } from "@/lib/charts/hc/nav";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import type { SeriesPoint } from "@/lib/api/client";
import { formatCurrency, formatDate } from "@/lib/format";

const NAV: SeriesPoint[] = [
  ["2024-01-01", 100],
  ["2024-01-02", 101.5],
];

describe("buildHcNavOption", () => {
  it("maps SeriesPoint dates to datetime x values and y values", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    expect((opt.xAxis as { type?: string }).type).toBe("datetime");
    const series = opt.series?.[0] as { data?: Array<[number, number]> };
    expect(series.data).toEqual([
      [dateToUtcMs("2024-01-01"), 100],
      [dateToUtcMs("2024-01-02"), 101.5],
    ]);
  });

  it("colors the NAV line with the accent token", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    const series = opt.series?.[0] as { color?: string; type?: string };
    expect(series.type).toBe("line");
    expect(series.color).toBe(TEST_COLORS.accent);
  });

  it("renders an empty series for empty input", () => {
    const opt = buildHcNavOption([], TEST_COLORS);
    const series = opt.series?.[0] as { data?: Array<[number, number]> };
    expect(series.data).toEqual([]);
  });

  it("formats the y-axis labels as currency", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 1234.5 });
    expect(out).toBe(formatCurrency(1234.5));
  });

  it("formats the tooltip with the date and the currency value", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    const tooltip = opt.tooltip as {
      formatter?: (this: { x: number; y: number }) => string;
    };
    const out = tooltip.formatter!.call({ x: dateToUtcMs("2024-01-02"), y: 101.5 });
    expect(out).toContain(formatDate("2024-01-02"));
    expect(out).toContain(formatCurrency(101.5));
  });
});
