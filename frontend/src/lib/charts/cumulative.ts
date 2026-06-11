/**
 * Pure option builder: cumulative return of asset vs benchmark.
 * Two lines on a shared date grid; y-axis percent-formatted.
 */
import type { EChartsOption } from "echarts";

import type { CumulativeReturns } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatPercent } from "@/lib/format";

export function buildCumulativeOption(
  cumulative: CumulativeReturns,
  assetLabel: string,
  benchmarkLabel: string,
  colors: ChartColors,
): EChartsOption {
  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number"
          ? formatPercent(value, 2, { signed: true })
          : String(value ?? ""),
    },
    legend: {
      top: 0,
      right: 8,
      textStyle: { color: colors.textSecondary },
      icon: "roundRect",
      itemWidth: 12,
      itemHeight: 3,
    },
    grid: { left: 64, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: "category",
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted },
    },
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatPercent(value, 0),
      },
    },
    series: [
      {
        name: assetLabel,
        type: "line",
        data: cumulative.asset,
        showSymbol: false,
        lineStyle: { color: colors.accent, width: 2 },
        itemStyle: { color: colors.accent },
      },
      {
        name: benchmarkLabel,
        type: "line",
        data: cumulative.benchmark,
        showSymbol: false,
        lineStyle: { color: colors.textMuted, width: 1.5 },
        itemStyle: { color: colors.textMuted },
      },
    ],
  };
}
