import { describe, expect, it } from "vitest";

import { allocationSliceColor, buildHcAllocationOption } from "@/lib/charts/hc/allocation";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { AllocationSlice } from "@/lib/charts/types";
import { formatNumber } from "@/lib/format";

const SLICES: AllocationSlice[] = [
  { name: "Equity", value: 60 },
  { name: "Fixed Income", value: 30 },
  { name: "Cash", value: 10 },
];

const HIERARCHICAL_SLICES: AllocationSlice[] = [
  { assetClass: "equity", displayName: "Apple Inc.", name: "AAPL", value: 40 },
  { assetClass: "equity", displayName: "Alphabet Inc.", name: "GOOG", value: 35 },
  { assetClass: "fixed_income", name: "BND", value: 15 },
  { assetClass: "cash", name: "Cash", value: 10 },
];

describe("buildHcAllocationOption", () => {
  it("returns a pie series with the correct type", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const series = opt.series?.[0] as { type?: string };
    expect(series.type).toBe("pie");
  });

  it("maps AllocationSlice names and values into series data points", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const series = opt.series?.[0] as { data?: { name: string; y: number }[] };
    expect(series.data).toHaveLength(3);
    expect(series.data?.[0]).toMatchObject({ name: "Equity", y: 60 });
    expect(series.data?.[1]).toMatchObject({ name: "Fixed Income", y: 30 });
    expect(series.data?.[2]).toMatchObject({ name: "Cash", y: 10 });
  });

  it("cycles slice colors from colors.categories", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const series = opt.series?.[0] as {
      data?: { color?: string }[];
    };
    expect(series.data?.[0]?.color).toBe(TEST_COLORS.categories[0]);
    expect(series.data?.[1]?.color).toBe(TEST_COLORS.categories[1]);
    expect(series.data?.[2]?.color).toBe(TEST_COLORS.barMute);
  });

  it("cycles colors correctly when there are more slices than categories", () => {
    const many: AllocationSlice[] = TEST_COLORS.categories.map((_, i) => ({
      name: `Slice ${i}`,
      value: 10,
    }));
    // Add one more beyond the category count
    many.push({ name: "Extra", value: 5 });
    const opt = buildHcAllocationOption(many, TEST_COLORS);
    const series = opt.series?.[0] as { data?: { color?: string }[] };
    // The extra slice wraps around to index 0
    expect(series.data?.[TEST_COLORS.categories.length]?.color).toBe(
      TEST_COLORS.categories[0],
    );
  });

  it("returns a two-ring donut when asset classes are supplied", () => {
    const opt = buildHcAllocationOption(HIERARCHICAL_SLICES, TEST_COLORS);
    const inner = opt.series?.[0] as {
      data?: { name: string; y: number }[];
      name?: string;
      size?: string;
      type?: string;
    };
    const outer = opt.series?.[1] as {
      data?: { name: string; y: number }[];
      innerSize?: string;
      name?: string;
      type?: string;
    };

    expect(opt.series).toHaveLength(2);
    expect(inner).toMatchObject({ name: "Asset class", size: "58%", type: "pie" });
    expect(outer).toMatchObject({ innerSize: "60%", name: "Holding", type: "pie" });
    expect(inner.data?.map((point) => [point.name, point.y])).toEqual([
      ["Equity", 75],
      ["Fixed Income", 15],
      ["Cash", 10],
    ]);
    expect(outer.data?.map((point) => point.name)).toEqual(["AAPL", "GOOG", "BND", "Cash"]);
  });

  it("exposes allocationSliceColor so the HTML legend matches the outer ring", () => {
    expect(allocationSliceColor(HIERARCHICAL_SLICES[0], 0, TEST_COLORS)).toBe(TEST_COLORS.categories[0]);
    expect(allocationSliceColor(HIERARCHICAL_SLICES[3], 3, TEST_COLORS)).toBe(TEST_COLORS.barMute);
  });

  it("sets innerSize to 62% (donut hole) by default and honors an override", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    expect((opt.series?.[0] as { innerSize?: string }).innerSize).toBe("62%");
    const opt70 = buildHcAllocationOption(SLICES, TEST_COLORS, { innerSize: "70%" });
    expect((opt70.series?.[0] as { innerSize?: string }).innerSize).toBe("70%");
  });

  it("enables leader data labels (name + rounded %) when config.dataLabels is set", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS, { dataLabels: true });
    const series = opt.series?.[0] as {
      dataLabels?: { enabled?: boolean; formatter?: (this: { key: string; percentage?: number }) => string };
    };
    const dl = Array.isArray(series.dataLabels) ? series.dataLabels[0] : series.dataLabels;
    expect(dl?.enabled).toBe(true);
    expect(dl?.formatter?.call({ key: "Equity", percentage: 60 })).toBe("Equity 60%");
    expect(opt.chart?.spacing).toEqual([8, 76, 8, 76]);
  });

  it("keeps compact chart spacing when external data labels are disabled", () => {
    const opt = buildHcAllocationOption(HIERARCHICAL_SLICES, TEST_COLORS);
    expect(opt.chart?.spacing).toEqual([4, 4, 4, 4]);
  });

  it("adds a formatted value line to the tooltip when config.valueFormatter is set", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS, {
      valueFormatter: (v) => `$${v}`,
    });
    const tooltip = opt.tooltip as {
      pointFormatter?: (this: { key: string; percentage?: number; y?: number }) => string;
    };
    const out = tooltip.pointFormatter!.call({ key: "Equity", percentage: 60, y: 1234 });
    expect(out).toContain("$1234");
    expect(out).toContain("60.0% of portfolio");
  });

  it("adds display name and asset class to hierarchical tooltips", () => {
    const opt = buildHcAllocationOption(HIERARCHICAL_SLICES, TEST_COLORS, {
      valueFormatter: (v) => `$${v}`,
    });
    const tooltip = opt.tooltip as {
      pointFormatter?: (this: {
        key: string;
        name?: string;
        options: { custom?: { assetClass?: string; displayName?: string } };
        percentage?: number;
        y?: number;
      }) => string;
    };

    const out = tooltip.pointFormatter!.call({
      key: "AAPL",
      options: { custom: { assetClass: "Equity", displayName: "Apple Inc." } },
      percentage: 40,
      y: 1234,
    });
    expect(out).toContain("Apple Inc.");
    expect(out).toContain("Equity");
    expect(out).toContain("$1234");
  });

  it("disables data labels (legend is external HTML)", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const series = opt.series?.[0] as {
      dataLabels?: { enabled?: boolean } | { enabled?: boolean }[];
    };
    if (Array.isArray(series.dataLabels)) {
      expect(series.dataLabels[0]?.enabled).toBe(false);
    } else {
      expect(series.dataLabels?.enabled).toBe(false);
    }
  });

  it("returns empty data array for empty input (no null)", () => {
    const opt = buildHcAllocationOption([], TEST_COLORS);
    expect(opt).not.toBeNull();
    const series = opt.series?.[0] as { data?: unknown[] };
    expect(series.data).toEqual([]);
  });

  it("formats the tooltip as 'name  X.X%' using formatNumber(percent, 1)", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const tooltip = opt.tooltip as {
      pointFormatter?: (this: { key: string | number; percentage?: number }) => string;
    };
    // The formatter receives `this.key` (point name, string|number) and
    // `this.percentage` (Highcharts pie percent, 0–100) — real HC Point shape.
    const formatter = tooltip.pointFormatter;
    expect(formatter).toBeDefined();
    const out = formatter!.call({ key: "Equity", percentage: 60 });
    expect(out).toContain("Equity");
    expect(out).toContain(formatNumber(60, 1));
  });

  it("adds inter-slice borders (borderWidth:1, borderColor:surface) to the pie series", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    const series = opt.series?.[0] as {
      borderWidth?: number;
      borderColor?: string;
    };
    expect(series.borderWidth).toBe(1);
    expect(series.borderColor).toBe(TEST_COLORS.surface);
  });

  it("does not set global chrome (no backgroundColor, no gridLineColor)", () => {
    const opt = buildHcAllocationOption(SLICES, TEST_COLORS);
    // The builder must NOT set chart.backgroundColor — the global theme owns it
    const chart = opt.chart as Record<string, unknown> | undefined;
    expect(chart?.backgroundColor).toBeUndefined();
  });
});
