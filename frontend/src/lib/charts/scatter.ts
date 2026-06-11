/**
 * Pure option builder: daily-return scatter with the fitted regression line.
 *
 * Both axes are decimal-fraction daily returns rendered as percent. The
 * regression line arrives render-ready from the backend (two endpoints).
 */
import type { EChartsOption } from "echarts";

import type { BetaResponse } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatPercent } from "@/lib/format";

type Pair = [number, number];

export function buildScatterOption(
  scatter: Pair[],
  regressionLine: Pair[],
  labels: BetaResponse["labels"],
  colors: ChartColors,
): EChartsOption {
  const axis = (name: string) =>
    ({
      type: "value",
      name,
      nameLocation: "middle",
      nameTextStyle: { color: colors.textSecondary },
      scale: true,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatPercent(value, 1),
      },
    }) as const;

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (params) => {
        const [x, y] = (params as unknown as { value: Pair }).value;
        return `${labels.x}: ${formatPercent(x, 2, { signed: true })}<br/>${labels.y}: ${formatPercent(y, 2, { signed: true })}`;
      },
    },
    grid: { left: 64, right: 24, top: 24, bottom: 48 },
    xAxis: { ...axis(labels.x), nameGap: 32 },
    yAxis: { ...axis(labels.y), nameGap: 48 },
    series: [
      {
        name: "Daily returns",
        type: "scatter",
        data: scatter,
        symbolSize: 6,
        itemStyle: { color: colors.accentMuted, opacity: 0.8 },
      },
      {
        name: "Regression",
        type: "line",
        data: regressionLine,
        showSymbol: false,
        silent: true,
        lineStyle: { color: colors.accent, width: 2 },
        itemStyle: { color: colors.accent },
      },
    ],
  };
}
