/**
 * Pure option builder: daily-return histogram bars (Highcharts Core).
 *
 * X-axis categories are bin midpoints computed from `bin_edges` and formatted
 * as percent strings (1 dp). All bars use a uniform graphite color
 * (colors.bar) at 0.75 opacity — the distribution shape carries the
 * information. Mirrors the ECharts buildHistogramOption exactly.
 */
import type { Options } from "highcharts";

import type { Histogram } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatCompact, formatPercent } from "@/lib/format";

export function buildHcHistogramOption(
  histogram: Histogram,
  colors: ChartColors,
): Options {
  const midpoints = histogram.counts.map(
    (_, i) => (histogram.bin_edges[i] + histogram.bin_edges[i + 1]) / 2,
  );

  const categories = midpoints.map((m) => formatPercent(m, 1));

  const data = histogram.counts.map((count) => ({
    y: count,
    color: colors.bar,
    opacity: 0.75,
  }));

  return {
    chart: { type: "column" },
    legend: { enabled: false },
    xAxis: {
      categories,
      crosshair: true,
      tickWidth: 0,
    },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return formatCompact(this.value as number);
        },
      },
    },
    tooltip: {
      shared: false,
      formatter() {
        return `${this.x}<br/><b>${formatCompact(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "column",
        name: "Days",
        data,
        pointPadding: 0,
        groupPadding: 0.06,
      },
    ],
  };
}
