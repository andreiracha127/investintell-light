/**
 * Pure option builders: stacked area charts for the scenario page (Highcharts Core).
 *
 * Behavioral parity with the legacy ECharts builders in src/lib/charts/stacked.ts.
 * The global Graphite theme (highchartsTheme) owns axis/grid/tooltip/legend chrome;
 * these builders set only series data, colors, value formatting, and axis bounds.
 *
 * Three builders:
 *  - buildHcStackedAreaOption  — stacking:"normal" area series + optional TOTAL line
 *  - buildHcStackedPercentOption — stacking:"percent" area series (0-100% axis)
 *  - buildHcMultiLineOption    — plain line series; TOTAL gets accent color + zIndex 10
 */
import type { Options, Point } from "highcharts";

import type { StackedSeries } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatCompact, formatCurrency, formatNumber, formatPercent } from "@/lib/format";

/**
 * Per-asset categorical color. Skips cat-1 (the accent anchor) so asset
 * series never collide with the accent-colored TOTAL line; the same index
 * yields the same color across the scenario charts (shared backend order).
 */
function categoryColor(colors: ChartColors, index: number): string {
  const palette = colors.categories.slice(1);
  return palette[index % palette.length];
}

/**
 * Stacked $-value areas (one per position, plus CASH), with an optional
 * un-stacked TOTAL line drawn on top in the accent color.
 */
export function buildHcStackedAreaOption(
  stack: StackedSeries[],
  total: StackedSeries | null,
  colors: ChartColors,
): Options {
  const series: Options["series"] = stack.map((entry, index) => {
    const color = categoryColor(colors, index);
    return {
      type: "area",
      name: entry.ticker,
      data: toDatetimeData(entry.points),
      stacking: "normal",
      color,
      lineWidth: 0.6,
      marker: { enabled: false },
      fillOpacity: 0.85,
      // Explicit base layer so the accent TOTAL line (zIndex 5) always draws
      // on top of the stacked areas regardless of series add-order.
      zIndex: 1,
    };
  });

  if (total) {
    series.push({
      type: "line",
      name: total.ticker,
      data: toDatetimeData(total.points),
      color: colors.accent,
      lineWidth: 2,
      marker: { enabled: false },
      zIndex: 5,
    });
  }

  return {
    chart: { type: "area" },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      title: { text: "Value (USD)" },
      labels: {
        formatter() {
          return `$${formatCompact(this.value as number)}`;
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const header = `${formatTimestampDate(this.x as number)}<br/>`;
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        const rows = points
          .map(
            (p) =>
              `<span style="color:${String(p.color)}">●</span> ${p.series.name}: <b>${formatCurrency(p.y as number)}</b>`,
          )
          .join("<br/>");
        return header + rows;
      },
    },
    series,
  };
}

/**
 * Weight evolution stacked to 100%. Inputs are decimal fractions that sum to
 * 1 across series per date; the axis renders 0–100%.
 */
export function buildHcStackedPercentOption(
  series: StackedSeries[],
  colors: ChartColors,
): Options {
  return {
    chart: { type: "area" },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      title: { text: "Weight" },
      min: 0,
      max: 100,
      labels: {
        // stacking:"percent" normalises the y-axis to 0..100 at runtime, so
        // `this.value` is already 0,20,40,...,100 — NOT the raw 0..1 fraction.
        // Render it directly; do not re-multiply via formatPercent.
        formatter() {
          return `${Math.round(this.value as number)}%`;
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const header = `${formatTimestampDate(this.x as number)}<br/>`;
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        const rows = points
          .map(
            // For stacking:"percent", `p.y` is the raw fraction; the rendered
            // stacked share is `p.percentage` (already 0..100). Use the share.
            (p) =>
              `<span style="color:${String(p.color)}">●</span> ${p.series.name}: <b>${formatNumber(p.percentage ?? 0, 1)}%</b>`,
          )
          .join("<br/>");
        return header + rows;
      },
    },
    series: series.map((entry, index) => {
      const color = categoryColor(colors, index);
      return {
        type: "area" as const,
        name: entry.ticker,
        data: toDatetimeData(entry.points),
        stacking: "percent",
        color,
        lineWidth: 1,
        marker: { enabled: false },
        fillOpacity: 0.45,
      };
    }),
  };
}

/**
 * Multi-line normalized performance (cumulative return rebased to 0): one
 * categorical line per asset, with the TOTAL series accent-colored on top.
 */
export function buildHcMultiLineOption(
  series: StackedSeries[],
  colors: ChartColors,
): Options {
  let categoryIndex = 0;

  return {
    chart: { type: "line" },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      // The series are cumulative returns "rebased to 100": the baseline (0%
      // cumulative return) is the rebasing anchor. A dashed plotLine marks it,
      // and the tooltip reports each series' signed delta vs that baseline.
      title: { text: "Rebased to 100" },
      plotLines: [
        {
          value: 0,
          color: colors.textMuted,
          width: 1,
          dashStyle: "Dash",
          zIndex: 2,
        },
      ],
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const header = `${formatTimestampDate(this.x as number)}<br/>`;
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        const rows = points
          .map(
            // `p.y` is the cumulative return from the rebasing baseline, i.e.
            // the signed delta vs baseline; render it signed.
            (p) =>
              `<span style="color:${String(p.color)}">●</span> ${p.series.name}: <b>${formatPercent(p.y as number, 2, { signed: true })}</b>`,
          )
          .join("<br/>");
        return header + rows;
      },
    },
    series: series.map((entry) => {
      const isTotal = entry.ticker === "TOTAL";
      const color = isTotal ? colors.accent : categoryColor(colors, categoryIndex++);
      return {
        type: "line" as const,
        name: entry.ticker,
        data: toDatetimeData(entry.points),
        color,
        lineWidth: isTotal ? 2.5 : 1.5,
        marker: { enabled: false },
        ...(isTotal && { zIndex: 10 }),
      };
    }),
  };
}
