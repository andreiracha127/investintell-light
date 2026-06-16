import { describe, expect, it } from "vitest";

import { buildHcExposureBarsOption } from "@/lib/charts/hc/lookthrough";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { ExposureItem } from "@/lib/api/client";
import { formatNumber } from "@/lib/format";

const ITEMS: ExposureItem[] = [
  { key: "us", label: "United States", direct_pct: 20, indirect_pct: 10, total_pct: 30 },
  { key: "eu", label: "Europe", direct_pct: 5, indirect_pct: 45, total_pct: 50 },
  { key: "jp", label: null, direct_pct: 8, indirect_pct: 2, total_pct: 10 },
];

describe("buildHcExposureBarsOption", () => {
  it("renders an inverted stacked horizontal bar chart", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const chart = opt.chart as { type?: string; inverted?: boolean };
    expect(chart.type).toBe("bar");
    expect(chart.inverted).toBe(true);
    const plot = opt.plotOptions as { bar?: { stacking?: string } };
    expect(plot.bar?.stacking).toBe("normal");
  });

  it("emits two stacked series: Direct and Via funds", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{ name?: string; type?: string; stacking?: string }>;
    expect(series).toHaveLength(2);
    expect(series[0].name).toBe("Direct");
    expect(series[1].name).toBe("Via funds");
    expect(series[0].type).toBe("bar");
    expect(series[1].type).toBe("bar");
  });

  it("sorts desc by total_pct and reverses so the largest is last (top of inverted axis)", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    // sorted desc: eu(50), us(30), jp(10) -> reversed: jp, us, eu
    const categories = (opt.xAxis as { categories?: string[] }).categories;
    expect(categories).toEqual(["jp", "United States", "Europe"]);
  });

  it("maps category labels (label ?? key) in sorted+reversed order", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const categories = (opt.xAxis as { categories?: string[] }).categories;
    // sorted desc by total: eu(50), us(30), jp(10); reversed: jp, us, eu
    // jp label is null -> falls back to key "jp"
    expect(categories).toEqual(["jp", "United States", "Europe"]);
  });

  it("maps direct_pct and indirect_pct into the two series in the same order", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{ data?: number[] }>;
    // reversed order: jp, us, eu
    expect(series[0].data).toEqual([8, 20, 5]); // direct
    expect(series[1].data).toEqual([2, 10, 45]); // indirect
  });

  it("colors Direct with the bar token and Via funds with the barMute token", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{ color?: string }>;
    expect(series[0].color).toBe(TEST_COLORS.bar);
    expect(series[1].color).toBe(TEST_COLORS.barMute);
  });

  it("shows the total label only on the Via funds (outer) series", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{ dataLabels?: { enabled?: boolean } }>;
    expect(series[0].dataLabels?.enabled).toBe(false);
    expect(series[1].dataLabels?.enabled).toBe(true);
  });

  it("formats the total data label as the row total_pct with 1dp + %", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{
      dataLabels?: { formatter?: (this: { index: number }) => string };
    }>;
    const fmt = series[1].dataLabels!.formatter!;
    // reversed order: index 0 = jp(10), 1 = us(30), 2 = eu(50)
    expect(fmt.call({ index: 0 })).toBe(formatNumber(10, 1) + "%");
    expect(fmt.call({ index: 2 })).toBe(formatNumber(50, 1) + "%");
  });

  it("returns an empty total label when the row index is out of range", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const series = opt.series as Array<{
      dataLabels?: { formatter?: (this: { index: number }) => string };
    }>;
    const fmt = series[1].dataLabels!.formatter!;
    expect(fmt.call({ index: 99 })).toBe("");
  });

  it("formats the value (x) axis labels as integer percent", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 25 });
    expect(out).toBe(formatNumber(25, 0) + "%");
  });

  it("uses a category axis for the row labels and a value axis for percent", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    expect((opt.xAxis as { type?: string }).type).toBe("category");
    expect((opt.yAxis as { type?: string }).type).toBe("linear");
  });

  it("honors opts.topN (default 10, here 2)", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS, { topN: 2 });
    const categories = (opt.xAxis as { categories?: string[] }).categories;
    // sorted desc: eu(50), us(30) -> top2 -> reversed: us, eu
    expect(categories).toEqual(["United States", "Europe"]);
    const series = opt.series as Array<{ data?: number[] }>;
    expect(series[0].data).toEqual([20, 5]);
  });

  it("renders the legend with a rect symbol and does not re-set theme-owned chrome", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const legend = opt.legend as { enabled?: boolean; symbolRadius?: number; itemStyle?: { color?: string } };
    expect(legend.enabled).toBe(true);
    expect(legend.symbolRadius).toBe(0);
    // legend.itemStyle.color is theme-owned chrome; the builder must NOT re-set it.
    expect(legend.itemStyle?.color).toBeUndefined();
  });

  it("renders empty series data for empty input", () => {
    const opt = buildHcExposureBarsOption([], TEST_COLORS);
    const categories = (opt.xAxis as { categories?: string[] }).categories;
    expect(categories).toEqual([]);
    const series = opt.series as Array<{ data?: number[] }>;
    expect(series[0].data).toEqual([]);
    expect(series[1].data).toEqual([]);
  });

  it("renders a rich HTML tooltip showing both segments and the total", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const tooltip = opt.tooltip as {
      useHTML?: boolean;
      // The real HC context: this.points is an array of point contexts,
      // this.point is the hovered Point (has .index and .category on a category axis).
      formatter?: (this: {
        points: Array<{ series: { name: string }; y: number; color: string }>;
        index: number;
        category: string;
      }) => string;
    };
    expect(tooltip.useHTML).toBe(true);
    const out = tooltip.formatter!.call({
      // index 1 in reversed order = us(direct 20, indirect 10, total 30)
      points: [
        { series: { name: "Direct" }, y: 20, color: TEST_COLORS.bar },
        { series: { name: "Via funds" }, y: 10, color: TEST_COLORS.barMute },
      ],
      index: 1,
      category: "United States",
    });
    expect(out).toContain("United States");
    expect(out).toContain("Direct");
    expect(out).toContain("Via funds");
    expect(out).toContain(formatNumber(20, 2) + "%");
    expect(out).toContain(formatNumber(10, 2) + "%");
    expect(out).toContain("Total");
    expect(out).toContain(formatNumber(30, 2) + "%");
  });

  it("returns an empty tooltip string when there are no points", () => {
    const opt = buildHcExposureBarsOption(ITEMS, TEST_COLORS);
    const tooltip = opt.tooltip as {
      // Real HC shared-tooltip context: this.point is always defined.
      formatter?: (this: {
        points: Array<unknown>;
        index: number;
        category: string;
      }) => string;
    };
    expect(
      tooltip.formatter!.call({ points: [], index: 0, category: "" }),
    ).toBe("");
  });
});
