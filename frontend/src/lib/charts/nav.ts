/**
 * Pure option builder: portfolio NAV line in currency units.
 */
import type { EChartsOption } from "echarts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCurrency } from "@/lib/format";

export function buildNavOption(
  nav: SeriesPoint[],
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
        typeof value === "number" ? formatCurrency(value) : String(value ?? ""),
    },
    grid: { left: 80, right: 16, top: 16, bottom: 28 },
    xAxis: {
      type: "category",
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted },
    },
    yAxis: {
      type: "value",
      scale: true,
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatCurrency(value),
      },
    },
    series: [
      {
        name: "NAV",
        type: "line",
        data: nav,
        showSymbol: false,
        lineStyle: { color: colors.accent, width: 2 },
        itemStyle: { color: colors.accent },
        areaStyle: { color: colors.accentMuted, opacity: 0.12 },
      },
    ],
  };
}
