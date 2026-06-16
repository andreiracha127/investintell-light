/**
 * Pure option builder: screener metric distribution histogram (Highcharts Core).
 *
 * Ported from the ECharts `buildDistributionOption`. Bars come pre-normalised
 * from the backend (`counts_normalized` in 0..1). Bins that overlap the
 * selected [min, max] band are colored `colors.accent`; others use `colors.bar`.
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets
 * only the column series, per-point colors, x-axis categories (bin midpoints),
 * and the hidden y-axis with a fixed max of 1.
 */
import type { Options, Point } from "highcharts";

import type { Distribution } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatCompact, formatMetricValue } from "@/lib/format";

export function buildHcDistributionOption(
  distribution: Distribution,
  band: { min: number | null; max: number | null },
  dataType: string,
  colors: ChartColors,
): Options {
  const { bin_edges, counts, counts_normalized } = distribution;

  // A bin [lo, hi] overlaps the band when its hi >= band.min AND lo <= band.max.
  // A null bound means unbounded on that side.
  const inBand = (lo: number, hi: number): boolean =>
    (band.min === null || hi >= band.min) && (band.max === null || lo <= band.max);

  // Midpoint labels for the x-axis, formatted by dataType.
  const labels = counts.map((_, i) =>
    formatMetricValue((bin_edges[i] + bin_edges[i + 1]) / 2, dataType),
  );

  // Per-point data: normalized value + per-bar color.
  const data = counts_normalized.map((value, i) => ({
    y: value,
    color: inBand(bin_edges[i], bin_edges[i + 1]) ? colors.accent : colors.bar,
  }));

  return {
    chart: { type: "column" },
    legend: { enabled: false },
    xAxis: {
      categories: labels,
      tickWidth: 0,
      // Cap visible tick labels at ~6 so dense bins stay readable.
      tickInterval: Math.max(1, Math.ceil(labels.length / 6)),
    },
    yAxis: {
      visible: false,
      max: 1,
      title: { text: undefined },
    },
    tooltip: {
      // TooltipFormatterCallbackFunction has `this: Point`; on a category-axis
      // column chart `this.index` is the bar's ordinal position in the series.
      formatter(this: Point) {
        const i = this.index;
        return `${labels[i]} — ${formatCompact(counts[i])} companies`;
      },
    },
    plotOptions: {
      column: {
        groupPadding: 0.05,
        pointPadding: 0,
        borderWidth: 0,
      },
    },
    series: [
      {
        type: "column",
        name: "Companies",
        data,
      },
    ],
  };
}
