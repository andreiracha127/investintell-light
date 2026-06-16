/**
 * Pure option builder: cumulative return of asset vs benchmark (Highcharts Core).
 * Two `line` series on a shared date grid; y-axis percent-formatted.
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets
 * only series, colors, and value formatting.
 */
import type { Options } from "highcharts";

import type { CumulativeReturns } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

export function buildHcCumulativeOption(
  cumulative: CumulativeReturns,
  assetLabel: string,
  benchmarkLabel: string,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "line" },
    legend: { enabled: false },
    xAxis: {
      categories: cumulative.asset.map((p) => p[0]),
      crosshair: true,
      tickWidth: 0,
    },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        const header = `${this.x}`;
        const rows = (this.points ?? [])
          .map(
            (pt) =>
              `<span style="color:${pt.series.color}">●</span> ${pt.series.name}: <b>${formatPercent(pt.y as number, 2, { signed: true })}</b>`,
          )
          .join("<br/>");
        return `${header}<br/>${rows}`;
      },
    },
    series: [
      {
        type: "line",
        name: benchmarkLabel,
        data: cumulative.benchmark.map((p) => p[1]),
        color: colors.barMute,
        lineWidth: 2,
        marker: { enabled: false },
      },
      {
        type: "line",
        name: assetLabel,
        data: cumulative.asset.map((p) => p[1]),
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
      },
    ],
  };
}
