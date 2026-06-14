import { describe, expect, it } from "vitest";

import { buildHcNavOption } from "@/lib/charts/hc/nav";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { SeriesPoint } from "@/lib/api/client";

const NAV: SeriesPoint[] = [
  ["2024-01-01", 100],
  ["2024-01-02", 101.5],
];

describe("buildHcNavOption", () => {
  it("maps SeriesPoint dates to x categories and values to series data", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    expect((opt.xAxis as { categories?: string[] }).categories).toEqual(["2024-01-01", "2024-01-02"]);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([100, 101.5]);
  });

  it("colors the NAV line with the accent token", () => {
    const opt = buildHcNavOption(NAV, TEST_COLORS);
    const series = opt.series?.[0] as { color?: string; type?: string };
    expect(series.type).toBe("line");
    expect(series.color).toBe(TEST_COLORS.accent);
  });

  it("renders an empty series for empty input", () => {
    const opt = buildHcNavOption([], TEST_COLORS);
    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([]);
  });
});
