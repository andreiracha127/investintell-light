/**
 * Pure option builder: small rolling-metric line chart (volatility, beta,
 * correlation). Reused across the rolling row with per-metric axis options.
 */
import type { EChartsOption } from "echarts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";

export interface RollingAxisOptions {
  /** Format y values as percent (decimal-fraction input). */
  yPercent?: boolean;
  /** Fixed y bounds (e.g. -1..1 for correlation); omitted = auto-scale. */
  yMin?: number;
  yMax?: number;
}

export function buildRollingOption(
  series: SeriesPoint[],
  label: string,
  colors: ChartColors,
  { yPercent = false, yMin, yMax }: RollingAxisOptions = {},
): EChartsOption {
  const formatValue = (value: number) =>
    yPercent ? formatPercent(value, 1) : formatNumber(value);

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number" ? formatValue(value) : String(value ?? ""),
    },
    grid: { left: 52, right: 12, top: 12, bottom: 24 },
    xAxis: {
      type: "category",
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted, fontSize: 10 },
    },
    yAxis: {
      type: "value",
      scale: true,
      min: yMin,
      max: yMax,
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        fontSize: 10,
        formatter: (value: number) => formatValue(value),
      },
    },
    series: [
      {
        name: label,
        type: "line",
        data: series,
        showSymbol: false,
        lineStyle: { color: colors.accent, width: 1.6 },
        itemStyle: { color: colors.accent },
      },
    ],
  };
}
