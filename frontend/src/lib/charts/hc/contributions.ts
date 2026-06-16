/**
 * Pure option builder: per-asset risk contributions as horizontal bars
 * (Highcharts Core, inverted bar chart).
 *
 * Sorts ascending so the largest contributor renders on top — Highcharts
 * bar (inverted column) renders categories bottom-up, mirroring the ECharts
 * category-axis behavior exactly.
 *
 * Returns a valid Options object for empty input (mirrors legacy behaviour:
 * buildRiskContributionsOption never returned null).
 */
import type { Options, Point } from "highcharts";

import type { RiskContribution } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

export function buildHcRiskContributionsOption(
  contributions: RiskContribution[],
  colors: ChartColors,
): Options {
  // Sort ascending: smallest at bottom, largest at top (Highcharts renders
  // bar series bottom-to-top, matching ECharts category axis bottom-up layout).
  const sorted = [...contributions].sort((a, b) => a.contribution - b.contribution);

  return {
    chart: { type: "bar" },
    legend: { enabled: false },
    xAxis: {
      // Ticker names on the category axis (horizontal axis after inversion).
      categories: sorted.map((c) => c.ticker),
      crosshair: false,
      tickWidth: 0,
      // Match legacy: axisLabel.color = colors.textSecondary.
      labels: {
        style: { color: colors.textSecondary },
      },
    },
    yAxis: {
      // Value axis (percent axis after inversion).
      title: { text: undefined },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: false,
      formatter(this: Point) {
        // On a category axis, this.category holds the ticker label.
        const label = this.category as string;
        return `${label}<br/><b>${formatPercent(this.y as number, 1)}</b>`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Risk contribution",
        data: sorted.map((c) => c.contribution),
        color: colors.bar,
        // Approximate legacy barCategoryGap:'35%' with HC spacing options.
        pointPadding: 0.1,
        groupPadding: 0,
        // Data label at bar end (mirrors ECharts label.position = "right").
        dataLabels: {
          enabled: true,
          // End-of-bar placement: align left means text starts at bar tip
          // (HC bar is inverted so "left" = toward the right of the screen).
          align: "left",
          inside: false,
          style: {
            // Match legacy label.color = colors.textSecondary.
            color: colors.textSecondary,
          },
          formatter() {
            return formatPercent(this.y as number, 1);
          },
        },
      },
    ],
  };
}
