/**
 * Pure option builder: daily-return scatter with the fitted regression line
 * (Highcharts Core).
 *
 * Both axes are decimal-fraction daily returns rendered as percent. The
 * regression line arrives render-ready from the backend (two endpoints).
 * Ported from the ECharts builder in src/lib/charts/scatter.ts.
 *
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets
 * only the series, colors, percent formatters, and axis titles.
 */
import type { Options, Point } from "highcharts";

import type { BetaResponse } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

type Pair = [number, number];

export function buildHcScatterOption(
  scatter: Pair[],
  regressionLine: Pair[],
  labels: BetaResponse["labels"],
  colors: ChartColors,
): Options {
  return {
    chart: { type: "scatter", animation: false },
    xAxis: {
      title: { text: labels.x },
      startOnTick: false,
      endOnTick: false,
      minPadding: 0,
      maxPadding: 0,
      labels: {
        formatter() {
          return formatPercent(this.value as number, 1);
        },
      },
    },
    yAxis: {
      title: { text: labels.y },
      startOnTick: false,
      endOnTick: false,
      minPadding: 0,
      maxPadding: 0,
      labels: {
        formatter() {
          return formatPercent(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        return (
          `${labels.x}: ${formatPercent(this.x as number, 2, { signed: true })}<br/>` +
          `${labels.y}: ${formatPercent(this.y as number, 2, { signed: true })}`
        );
      },
    },
    series: [
      {
        type: "scatter",
        name: "Daily returns",
        data: scatter,
        color: colors.accent,
        marker: { radius: 3 },
        opacity: 0.65,
      },
      {
        type: "line",
        name: "Regression",
        data: regressionLine,
        color: colors.bar,
        lineWidth: 1.5,
        marker: { enabled: false },
        enableMouseTracking: false,
      },
    ],
  };
}
