/**
 * Pure option builder: NAV line in currency units (Highcharts Core).
 * Reference template for the ECharts -> Highcharts builder migration (P1):
 * the global Graphite theme owns axis/grid/tooltip chrome; the builder sets
 * only the series, the accent color, and currency value formatting.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatCurrency } from "@/lib/format";

export function buildHcNavOption(nav: SeriesPoint[], colors: ChartColors): Options {
  return {
    chart: { type: "line" },
    legend: { enabled: false },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return formatCurrency(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        return `${formatTimestampDate(this.x)}<br/><b>${formatCurrency(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "line",
        name: "NAV",
        data: toDatetimeData(nav),
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
      },
    ],
  };
}
