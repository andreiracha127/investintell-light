/**
 * Pure option builders: stacked area charts for the scenario page.
 *
 * All input series share the same date grid (backend contract), so the x-axis
 * categories come from the first series and each stacked series contributes
 * values only. No finance here — display arrangement only.
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { StackedSeries } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCompact, formatCurrency, formatPercent } from "@/lib/format";

/**
 * Per-asset categorical color. Skips cat-1 (the accent anchor) so asset
 * series never collide with the accent-colored TOTAL line; the same index
 * yields the same color across the scenario charts (shared backend order).
 */
function categoryColor(colors: ChartColors, index: number): string {
  const palette = colors.categories.slice(1);
  return palette[index % palette.length];
}

function baseAxes(dates: string[], colors: ChartColors) {
  return {
    grid: { left: 64, right: 16, top: 32, bottom: 28 },
    xAxis: {
      type: "category",
      data: dates,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted },
    },
    legend: {
      top: 0,
      right: 8,
      textStyle: { color: colors.textSecondary },
      icon: "rect",
      itemWidth: 10,
      itemHeight: 2,
    },
  } satisfies Partial<EChartsOption>;
}

/**
 * Stacked $-value areas (one per position, plus CASH), with an optional
 * un-stacked TOTAL line drawn on top in the accent color.
 */
export function buildStackedAreaOption(
  stack: StackedSeries[],
  total: StackedSeries | null,
  colors: ChartColors,
): EChartsOption {
  const dates = (stack[0] ?? total)?.points.map(([date]) => date) ?? [];

  const stackedSeries: SeriesOption[] = stack.map((series, index) => {
    const color = categoryColor(colors, index);
    return {
      name: series.ticker,
      type: "line",
      stack: "value",
      data: series.points.map(([, value]) => value),
      showSymbol: false,
      lineStyle: { color, width: 1 },
      itemStyle: { color },
      areaStyle: { color, opacity: 0.35 },
    };
  });

  if (total) {
    stackedSeries.push({
      name: total.ticker,
      type: "line",
      data: total.points.map(([, value]) => value),
      showSymbol: false,
      lineStyle: { color: colors.accent, width: 2 },
      itemStyle: { color: colors.accent },
    });
  }

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number" ? formatCurrency(value) : String(value ?? ""),
    },
    ...baseAxes(dates, colors),
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => `$${formatCompact(value)}`,
      },
    },
    series: stackedSeries,
  };
}

/**
 * Weight evolution stacked to 100%. Inputs are decimal fractions that sum to
 * 1 across series per date; the axis renders 0-100%.
 */
export function buildStackedPercentOption(
  series: StackedSeries[],
  colors: ChartColors,
): EChartsOption {
  const dates = series[0]?.points.map(([date]) => date) ?? [];

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number"
          ? formatPercent(value, 1)
          : String(value ?? ""),
    },
    ...baseAxes(dates, colors),
    yAxis: {
      type: "value",
      min: 0,
      max: 1,
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatPercent(value, 0),
      },
    },
    series: series.map((entry, index): SeriesOption => {
      const color = categoryColor(colors, index);
      return {
        name: entry.ticker,
        type: "line",
        stack: "weight",
        data: entry.points.map(([, value]) => value),
        showSymbol: false,
        lineStyle: { color, width: 1 },
        itemStyle: { color },
        areaStyle: { color, opacity: 0.45 },
      };
    }),
  };
}

/**
 * Multi-line normalized performance (cumulative return rebased to 0): one
 * categorical line per asset, with the TOTAL series accent-colored on top.
 */
export function buildMultiLineOption(
  series: StackedSeries[],
  colors: ChartColors,
): EChartsOption {
  const dates = series[0]?.points.map(([date]) => date) ?? [];
  let categoryIndex = 0;

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      valueFormatter: (value) =>
        typeof value === "number"
          ? formatPercent(value, 2, { signed: true })
          : String(value ?? ""),
    },
    ...baseAxes(dates, colors),
    yAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatPercent(value, 0),
      },
    },
    series: series.map((entry): SeriesOption => {
      const isTotal = entry.ticker === "TOTAL";
      const color = isTotal
        ? colors.accent
        : categoryColor(colors, categoryIndex++);
      return {
        name: entry.ticker,
        type: "line",
        data: entry.points.map(([, value]) => value),
        showSymbol: false,
        lineStyle: { color, width: isTotal ? 2.5 : 1.5 },
        itemStyle: { color },
        ...(isTotal && { z: 10 }),
      };
    }),
  };
}
