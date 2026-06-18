/**
 * Pure option builder: rolling correlation as a gradient area (Highcharts Core).
 *
 * Design source: Statistics.dc.html — the Correlation tool renders the rolling
 * r series as an accent area with `threshold: 0` (so it fills toward the zero
 * line), a fixed −1..1 y-axis, and a dashed zero reference line. This replaces
 * the plain line used by the generic `buildHcRollingOption` for this page only.
 *
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets the
 * single area series, its vertical accent gradient, the fixed correlation bounds
 * with a half-unit tick, and the zero plot line.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatNumber } from "@/lib/format";

export function buildHcRollingCorrelationAreaOption(
  series: SeriesPoint[],
  label: string,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "area" },
    legend: { enabled: false },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      title: { text: "Correlation (r)" },
      min: -1,
      max: 1,
      tickInterval: 0.5,
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
          return formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter() {
        return `${formatTimestampDate(this.x)}<br/>${label}: <b>${formatNumber(this.y as number, 3)}</b>`;
      },
    },
    series: [
      {
        type: "area",
        name: label,
        data: toDatetimeData(series),
        color: colors.accent,
        lineWidth: 1.8,
        marker: { enabled: false },
        threshold: 0,
        fillColor: {
          linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
          stops: [
            [0, colors.accentWash],
            [1, "transparent"],
          ],
        },
      },
    ],
  };
}
