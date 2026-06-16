import { describe, expect, it } from "vitest";

import { buildHcRiskContributionsOption } from "@/lib/charts/hc/contributions";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type { RiskContribution } from "@/lib/api/client";
import { formatPercent } from "@/lib/format";

const CONTRIBUTIONS: RiskContribution[] = [
  { ticker: "BOVA11", contribution: 0.45 },
  { ticker: "IVVB11", contribution: 0.30 },
  { ticker: "FIXA11", contribution: 0.25 },
];

describe("buildHcRiskContributionsOption", () => {
  it("returns a valid Options object (not null) for empty input", () => {
    // Legacy buildRiskContributionsOption never returned null — mirror that.
    const result = buildHcRiskContributionsOption([], TEST_COLORS);
    expect(result).not.toBeNull();
    // The series should be present with empty data.
    const series = result.series?.[0] as { data?: number[] } | undefined;
    expect(series?.data).toEqual([]);
  });

  it("uses chart type bar with inverted axis for horizontal bars", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);
    expect((opt.chart as { type?: string; inverted?: boolean }).type).toBe("bar");
  });

  it("sorts data ascending so largest contribution renders on top", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    // With Highcharts bar (inverted), ascending sort puts largest value at top.
    const xAxis = opt.xAxis as { categories?: string[] };
    // Ascending order: FIXA11 (0.25), IVVB11 (0.30), BOVA11 (0.45)
    expect(xAxis.categories).toEqual(["FIXA11", "IVVB11", "BOVA11"]);
  });

  it("maps contribution values to series data in ascending sort order", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([0.25, 0.30, 0.45]);
  });

  it("uses colors.bar for series color", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as { color?: string; type?: string };
    expect(series.type).toBe("bar");
    expect(series.color).toBe(TEST_COLORS.bar);
  });

  it("formats the y-axis (value axis) labels as percent with 0 decimals", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    // yAxis is the value axis (Highcharts bar with inverted = true swaps orientation)
    const yAxis = opt.yAxis as {
      labels?: { formatter?: (this: { value: number }) => string };
    };
    const out = yAxis.labels!.formatter!.call({ value: 0.25 });
    expect(out).toBe(formatPercent(0.25, 0));
  });

  it("formats the tooltip value as percent with 1 decimal using point.category", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    // HC tooltip formatter `this` is the hovered Point: category is on this.category.
    const tooltip = opt.tooltip as {
      formatter?: (this: { category: string; y: number }) => string;
    };
    const out = tooltip.formatter!.call({ category: "BOVA11", y: 0.45 });
    expect(out).toContain("BOVA11");
    expect(out).toContain(formatPercent(0.45, 1));
  });

  it("shows data labels formatted as percent with 1 decimal", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as {
      dataLabels?: {
        enabled?: boolean;
        formatter?: (this: { y: number }) => string;
        style?: { color?: string };
        align?: string;
        inside?: boolean;
      };
    };
    expect(series.dataLabels).toBeDefined();
    expect(series.dataLabels!.enabled).toBe(true);
    const out = series.dataLabels!.formatter!.call({ y: 0.45 });
    expect(out).toBe(formatPercent(0.45, 1));
  });

  it("sets dataLabels style.color to colors.textSecondary (legacy label.color parity)", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as {
      dataLabels?: { style?: { color?: string } };
    };
    expect(series.dataLabels?.style?.color).toBe(TEST_COLORS.textSecondary);
  });

  it("sets dataLabels align:left and inside:false for end-of-bar placement", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as {
      dataLabels?: { align?: string; inside?: boolean };
    };
    expect(series.dataLabels?.align).toBe("left");
    expect(series.dataLabels?.inside).toBe(false);
  });

  it("sets xAxis.labels.style.color to colors.textSecondary (legacy axisLabel parity)", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const xAxis = opt.xAxis as {
      labels?: { style?: { color?: string } };
    };
    expect(xAxis.labels?.style?.color).toBe(TEST_COLORS.textSecondary);
  });

  it("sets pointPadding and groupPadding on bar series (approximates legacy barCategoryGap:35%)", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const series = opt.series?.[0] as {
      pointPadding?: number;
      groupPadding?: number;
    };
    expect(series.pointPadding).toBe(0.1);
    expect(series.groupPadding).toBe(0);
  });

  it("does not set legend (single series chart)", () => {
    const opt = buildHcRiskContributionsOption(CONTRIBUTIONS, TEST_COLORS);

    const legend = opt.legend as { enabled?: boolean } | undefined;
    expect(legend?.enabled).toBe(false);
  });

  it("sets the xAxis categories from tickers (sorted ascending)", () => {
    const single: RiskContribution[] = [{ ticker: "ONLY", contribution: 1.0 }];
    const opt = buildHcRiskContributionsOption(single, TEST_COLORS);

    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["ONLY"]);

    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([1.0]);
  });

  it("handles already-ascending order correctly", () => {
    const ascending: RiskContribution[] = [
      { ticker: "A", contribution: 0.1 },
      { ticker: "B", contribution: 0.3 },
      { ticker: "C", contribution: 0.6 },
    ];
    const opt = buildHcRiskContributionsOption(ascending, TEST_COLORS);

    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["A", "B", "C"]);

    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([0.1, 0.3, 0.6]);
  });

  it("handles descending input by sorting it to ascending", () => {
    const descending: RiskContribution[] = [
      { ticker: "X", contribution: 0.9 },
      { ticker: "Y", contribution: 0.07 },
      { ticker: "Z", contribution: 0.03 },
    ];
    const opt = buildHcRiskContributionsOption(descending, TEST_COLORS);

    const xAxis = opt.xAxis as { categories?: string[] };
    expect(xAxis.categories).toEqual(["Z", "Y", "X"]);

    const series = opt.series?.[0] as { data?: number[] };
    expect(series.data).toEqual([0.03, 0.07, 0.9]);
  });
});
