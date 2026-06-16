import { describe, expect, it } from "vitest";

import {
  buildHcMonthlyReturnsOption,
  buildHcDrawdownOption,
} from "@/lib/charts/hc/performance";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { DrawdownResult, MonthlyReturn } from "@/lib/perf";
import { formatDate, formatPercent } from "@/lib/format";

// ── Monthly returns heatmap ───────────────────────────────────────────────

const CELLS: MonthlyReturn[] = [
  { year: 2023, month: 2, value: -0.04 }, // |.04|
  { year: 2024, month: 1, value: 0.1 }, // max abs → intensity 1
  { year: 2024, month: 6, value: 0.02 },
];

type HeatPoint = {
  x: number;
  y: number;
  value: number;
  dataLabels?: { color?: string };
};

describe("buildHcMonthlyReturnsOption", () => {
  it("returns null for empty input", () => {
    expect(buildHcMonthlyReturnsOption([], TEST_COLORS)).toBeNull();
  });

  it("uses a heatmap series", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const series = opt.series?.[0] as { type?: string };
    expect(series.type).toBe("heatmap");
  });

  it("lists months on x and years descending on y", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const xAxis = opt.xAxis as { categories?: string[] };
    const yAxis = opt.yAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual([
      "Jan", "Feb", "Mar", "Apr", "May", "Jun",
      "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
    ]);
    // Years descending.
    expect(yAxis.categories).toEqual(["2024", "2023"]);
  });

  it("maps each cell to [month-1, yearIndex, value]", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const data = (opt.series?.[0] as { data?: HeatPoint[] }).data!;
    // 2024 is yIdx 0 (descending), 2023 is yIdx 1.
    const byVal = new Map(data.map((p) => [p.value, p]));
    expect(byVal.get(0.1)).toMatchObject({ x: 0, y: 0 }); // 2024 Jan
    expect(byVal.get(0.02)).toMatchObject({ x: 5, y: 0 }); // 2024 Jun
    expect(byVal.get(-0.04)).toMatchObject({ x: 1, y: 1 }); // 2023 Feb
  });

  it("drives cell color via a diverging colorAxis (loss → grid → gain)", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const colorAxis = opt.colorAxis as {
      min?: number;
      max?: number;
      stops?: Array<[number, string]>;
    };
    expect(colorAxis.min).toBe(-0.1); // -maxAbs
    expect(colorAxis.max).toBe(0.1); // maxAbs
    expect(colorAxis.stops).toEqual([
      [0, TEST_COLORS.loss],
      [0.5, TEST_COLORS.grid],
      [1, TEST_COLORS.gain],
    ]);
  });

  it("sets a light label on saturated cells and normal text otherwise", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const data = (opt.series?.[0] as { data?: HeatPoint[] }).data!;
    const byVal = new Map(data.map((p) => [p.value, p]));
    // intensity 1.0 > 0.6 → textOnAccent.
    expect(byVal.get(0.1)!.dataLabels?.color).toBe(TEST_COLORS.textOnAccent);
    // intensity 0.02/0.1 = 0.2 ≤ 0.6 → text.
    expect(byVal.get(0.02)!.dataLabels?.color).toBe(TEST_COLORS.text);
    // intensity 0.04/0.1 = 0.4 ≤ 0.6 → text.
    expect(byVal.get(-0.04)!.dataLabels?.color).toBe(TEST_COLORS.text);
  });

  it("formats the cell label to one decimal percent", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const series = opt.series?.[0] as {
      // In a dataLabels formatter `this` is the Point itself; the heatmap return
      // lives on the point's custom `value` field.
      dataLabels?: { formatter?: (this: { value: number }) => string };
    };
    const out = series.dataLabels!.formatter!.call({ value: 0.1234 });
    expect(out).toBe(formatPercent(0.1234, 1));
  });

  it("formats the tooltip as 'Mon YYYY: +x.xx%'", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const tooltip = opt.tooltip as {
      // The tooltip formatter `this` is the hovered Point: x/y are the category
      // indexes and `value` carries the return.
      formatter?: (this: { x: number; y: number; value: number }) => string;
    };
    // 2024 Jan, +10.00%
    const out = tooltip.formatter!.call({ x: 0, y: 0, value: 0.1 });
    expect(out).toContain("Jan");
    expect(out).toContain("2024");
    expect(out).toContain(formatPercent(0.1, 2, { signed: true }));
  });

  it("reverses the y-axis so the most-recent year renders at the top", () => {
    const opt = buildHcMonthlyReturnsOption(CELLS, TEST_COLORS)!;
    const yAxis = opt.yAxis as { categories?: string[]; reversed?: boolean };
    // Categories stay descending (newest first) and map to indexes 0..n; a
    // category axis renders index 0 at the bottom, so `reversed` lifts the
    // newest year (2024) to the top.
    expect(yAxis.categories).toEqual(["2024", "2023"]);
    expect(yAxis.reversed).toBe(true);
  });
});

// ── Drawdown area chart ────────────────────────────────────────────────────

const DD: DrawdownResult = {
  dates: ["2024-01-01", "2024-01-02", "2024-01-03"],
  values: [0, -0.05, -0.1],
  worst: { from: "2024-01-01", to: "2024-01-03", depth: -0.1 },
};

const FLAT_DD: DrawdownResult = {
  dates: ["2024-01-01", "2024-01-02"],
  values: [0, 0],
  worst: { from: "2024-01-01", to: "2024-01-01", depth: 0 },
};

describe("buildHcDrawdownOption", () => {
  it("returns null for null input", () => {
    expect(buildHcDrawdownOption(null, TEST_COLORS)).toBeNull();
  });

  it("returns null when there are no dates", () => {
    const empty: DrawdownResult = {
      dates: [],
      values: [],
      worst: { from: "", to: "", depth: 0 },
    };
    expect(buildHcDrawdownOption(empty, TEST_COLORS)).toBeNull();
  });

  it("uses an area series filled with the loss color", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    const series = opt.series?.[0] as { type?: string; color?: string };
    expect(series.type).toBe("area");
    expect(series.color).toBe(TEST_COLORS.loss);
  });

  it("maps dates to x categories and values to [date, value] data", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["2024-01-01", "2024-01-02", "2024-01-03"]);
    const data = (opt.series?.[0] as { data?: number[] }).data!;
    expect(data).toEqual([0, -0.05, -0.1]);
  });

  it("caps the y-axis at 0 and labels in percent", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    const yAxis = opt.yAxis as {
      max?: number;
      labels?: { formatter?: (this: { value: number }) => string };
    };
    expect(yAxis.max).toBe(0);
    const out = yAxis.labels!.formatter!.call({ value: -0.1 });
    expect(out).toBe(formatPercent(-0.1, 0));
  });

  it("marks the worst window with an xAxis plotBand from peak to trough", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    const bands = (opt.xAxis as { plotBands?: Array<{ from?: number; to?: number }> })
      .plotBands!;
    expect(bands).toHaveLength(1);
    // category indexes: from=0 (2024-01-01), to=2 (2024-01-03).
    expect(bands[0].from).toBe(0);
    expect(bands[0].to).toBe(2);
  });

  it("labels the plotBand with the worst depth", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    const band = (opt.xAxis as {
      plotBands?: Array<{ label?: { text?: string } }>;
    }).plotBands![0];
    expect(band.label?.text).toContain(formatPercent(-0.1, 2));
  });

  it("emits no plotBand for a flat (depth === 0) series", () => {
    const opt = buildHcDrawdownOption(FLAT_DD, TEST_COLORS)!;
    const bands = (opt.xAxis as { plotBands?: unknown[] }).plotBands;
    expect(bands === undefined || bands.length === 0).toBe(true);
  });

  it("formats the tooltip with the date and the percent value", () => {
    const opt = buildHcDrawdownOption(DD, TEST_COLORS)!;
    // The tooltip formatter `this` is the hovered Point. On a category x-axis
    // the ISO date lives on `category` (NOT `x`, which is the numeric index).
    const tooltip = opt.tooltip as {
      formatter?: (this: { category: string; y: number }) => string;
    };
    const out = tooltip.formatter!.call({ category: "2024-01-03", y: -0.1 });
    expect(out).toContain(formatDate("2024-01-03"));
    expect(out).toContain(formatPercent(-0.1, 2));
  });
});
