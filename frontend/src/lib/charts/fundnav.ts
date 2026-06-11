/**
 * Pure option builder: fund NAV/share line over the decimated 2y series
 * served by GET /funds/{id}. Accent 2px line, Cockpit tokens (nav.ts style).
 */
import type { EChartsOption } from "echarts";

import type { FundNavPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCurrency } from "@/lib/format";

export function buildFundNavOption(
  nav: FundNavPoint[],
  colors: ChartColors,
): EChartsOption {
  const data: [string, number][] = nav
    .filter((p): p is FundNavPoint & { nav: number } => p.nav !== null)
    .map((p) => [p.date, p.nav]);
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
    grid: { left: 64, right: 16, top: 16, bottom: 28 },
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
        data,
        showSymbol: false,
        lineStyle: { color: colors.accent, width: 2 },
        itemStyle: { color: colors.accent },
      },
    ],
  };
}
