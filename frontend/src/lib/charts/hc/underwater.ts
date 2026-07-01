/**
 * Pure option builder: underwater (drawdown) area chart (Highcharts Core).
 *
 * Renders a ≤0 drawdown series as a loss-toned area filling down from the
 * zero line — the classic "underwater" plot. The global Graphite theme owns
 * axis/grid/tooltip chrome; this builder sets only the series, its fill, the
 * pinned-to-zero y-axis and percent formatting.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatPercent } from "@/lib/format";

export function buildHcUnderwaterOption(
  series: SeriesPoint[],
  label: string,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "area" },
    legend: { enabled: false },
    xAxis: {
      ...compactDatetimeXAxis(),
      crosshair: { width: 1, color: colors.grid },
    },
    yAxis: {
      // Drawdowns are ≤ 0 — pin the ceiling at zero so recoveries touch the top.
      max: 0,
      title: { text: "Drawdown" },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        return `${formatTimestampDate(this.x)}<br/><b>${formatPercent(
          this.y as number,
          2,
        )}</b>`;
      },
    },
    series: [
      {
        type: "area",
        name: label,
        data: toDatetimeData(series),
        color: colors.loss,
        fillOpacity: 0.18,
        threshold: 0,
        lineWidth: 1.4,
        marker: { enabled: false },
      },
    ],
  };
}
