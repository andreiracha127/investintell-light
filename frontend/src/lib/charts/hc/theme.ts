/**
 * Pure Graphite theme for Highcharts. Returns a base `Options` applied globally
 * via `Highcharts.setOptions(...)` by the chart wrappers. Token-driven (takes a
 * ChartColors bag read from CSS custom properties) so light/dark/accent switches
 * flow through the AppShell key-remount, exactly like the ECharts builders.
 *
 * Pure: no DOM access — safe to unit test in node.
 */
import type { Options, PlotSeriesOptions } from "highcharts";

import type { ChartColors } from "@/lib/charts/theme";

const SANS = 'Arial, "Arimo", "Helvetica Neue", ui-sans-serif, sans-serif';

export function highchartsTheme(colors: ChartColors): Options {
  const axis = {
    gridLineColor: colors.grid,
    lineColor: colors.grid,
    tickColor: colors.grid,
    labels: { style: { color: colors.textMuted, fontVariantNumeric: "tabular-nums" } },
    title: { style: { color: colors.textSecondary } },
  };
  return {
    colors: [...colors.categories],
    chart: {
      backgroundColor: "transparent",
      borderRadius: 0,
      animation: false,
      style: { fontFamily: SANS },
    },
    title: { style: { color: colors.text } },
    subtitle: { style: { color: colors.textSecondary } },
    xAxis: axis,
    yAxis: axis,
    legend: {
      itemStyle: { color: colors.text },
      itemHoverStyle: { color: colors.accent },
      itemHiddenStyle: { color: colors.textMuted },
    },
    tooltip: {
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      borderRadius: 0,
      shadow: false,
      style: { color: colors.text },
    },
    plotOptions: {
      // `borderRadius` is column/bar-specific on the v13 PlotSeriesOptions type;
      // keep the square-corner runtime value via a narrow cast.
      series: { animation: false, borderRadius: 0 } as PlotSeriesOptions,
      candlestick: {
        color: colors.loss,
        upColor: colors.gain,
        lineColor: colors.loss,
        upLineColor: colors.gain,
      },
    },
    credits: { enabled: false },
  };
}
