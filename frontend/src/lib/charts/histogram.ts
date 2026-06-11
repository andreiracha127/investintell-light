/**
 * Pure option builder: daily-return histogram bars.
 *
 * X positions are bin MIDPOINTS computed from `bin_edges` — arithmetic for
 * display position only, not finance. Bars are loss-colored for negative
 * midpoints and gain-colored for positive ones.
 */
import type { EChartsOption } from "echarts";

import type { Histogram } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCompact, formatPercent } from "@/lib/format";

export function buildHistogramOption(
  histogram: Histogram,
  colors: ChartColors,
): EChartsOption {
  const midpoints = histogram.counts.map(
    (_, i) => (histogram.bin_edges[i] + histogram.bin_edges[i + 1]) / 2,
  );
  // Uniform graphite bars (Cockpit) — the distribution shape carries the
  // information; gain/loss colouring is reserved for actual P&L surfaces.
  const bars = histogram.counts.map((count) => ({
    value: count,
    itemStyle: { color: colors.bar, opacity: 0.75 },
  }));

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number" ? formatCompact(value) : String(value ?? ""),
    },
    grid: { left: 48, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      data: midpoints.map((m) => formatPercent(m, 1)),
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        fontSize: 10,
        formatter: (value: number) => formatCompact(value),
      },
    },
    series: [
      {
        name: "Days",
        type: "bar",
        data: bars,
        barCategoryGap: "12%",
      },
    ],
  };
}
