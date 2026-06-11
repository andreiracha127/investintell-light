/**
 * Pure option builder: per-asset risk contributions as horizontal bars.
 *
 * Largest contributor renders on top (ECharts lays category axes bottom-up,
 * so the data is sorted ascending). Values are fractions of total portfolio
 * risk and sum to 1.
 */
import type { EChartsOption } from "echarts";

import type { RiskContribution } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatPercent } from "@/lib/format";

export function buildRiskContributionsOption(
  contributions: RiskContribution[],
  colors: ChartColors,
): EChartsOption {
  const sorted = [...contributions].sort(
    (a, b) => a.contribution - b.contribution,
  );

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number" ? formatPercent(value, 1) : String(value ?? ""),
    },
    grid: { left: 64, right: 56, top: 8, bottom: 28 },
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatPercent(value, 0),
      },
    },
    yAxis: {
      type: "category",
      data: sorted.map((c) => c.ticker),
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textSecondary },
    },
    series: [
      {
        name: "Risk contribution",
        type: "bar",
        data: sorted.map((c) => c.contribution),
        barCategoryGap: "35%",
        // Flat square graphite bars — Cockpit style (no rounded corners).
        itemStyle: { color: colors.bar },
        label: {
          show: true,
          position: "right",
          color: colors.textSecondary,
          formatter: (params) => formatPercent(params.value as number, 1),
        },
      },
    ],
  };
}
