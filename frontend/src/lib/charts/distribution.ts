/**
 * Pure option builder: screener metric distribution (universe histogram).
 *
 * Bars come pre-normalized from the backend (`counts_normalized` in 0..1);
 * the chart computes NO statistics. Bins overlapping the selected [min, max]
 * band are accent-colored (oxblood), the rest stay neutral graphite — the
 * explore-before-cut visual behind the Build inputs. Bin midpoints (display
 * position only) label the x axis via the shared metric formatter.
 */
import type { EChartsOption } from "echarts";

import type { Distribution } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCompact, formatMetricValue } from "@/lib/format";

export function buildDistributionOption(
  distribution: Distribution,
  band: { min: number | null; max: number | null },
  dataType: string,
  colors: ChartColors,
): EChartsOption {
  const { bin_edges, counts, counts_normalized } = distribution;

  // A bin [lo, hi] is "in band" when it overlaps the selected range; a null
  // bound is unbounded on that side.
  const inBand = (lo: number, hi: number) =>
    (band.min === null || hi >= band.min) && (band.max === null || lo <= band.max);

  const bars = counts_normalized.map((value, i) => ({
    value,
    itemStyle: {
      color: inBand(bin_edges[i], bin_edges[i + 1])
        ? colors.accent
        : colors.bar,
    },
  }));
  const labels = counts.map((_, i) =>
    formatMetricValue((bin_edges[i] + bin_edges[i + 1]) / 2, dataType),
  );

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (params) => {
        const first = Array.isArray(params) ? params[0] : params;
        const i = typeof first.dataIndex === "number" ? first.dataIndex : 0;
        return `${labels[i]} — ${formatCompact(counts[i])} companies`;
      },
    },
    grid: { left: 8, right: 8, top: 8, bottom: 22 },
    xAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: {
        color: colors.textMuted,
        fontSize: 10,
        // Cap at ~6 visible labels so dense bins stay readable.
        interval: Math.max(0, Math.ceil(labels.length / 6) - 1),
      },
    },
    yAxis: { type: "value", max: 1, show: false },
    series: [
      {
        name: "Companies",
        type: "bar",
        data: bars,
        barCategoryGap: "10%",
      },
    ],
  };
}
