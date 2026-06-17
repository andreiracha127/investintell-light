/**
 * Pure Graphite theme for Highcharts. Returns a base `Options` applied globally
 * via `Highcharts.setOptions(...)` by the chart wrappers. Token-driven (takes a
 * ChartColors bag read from CSS custom properties) so light/dark/accent switches
 * flow through the AppShell key-remount.
 *
 * Pure: no DOM access — safe to unit test in node.
 */
import type { Options, PlotSeriesOptions } from "highcharts";

import type { ChartColors } from "@/lib/charts/chartColors";

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
      animation: { duration: 350 },
      spacing: [8, 8, 8, 8],
      style: { fontFamily: SANS },
    },
    // text:undefined disables Highcharts' built-in default "Chart title".
    title: { text: undefined, style: { color: colors.text } },
    subtitle: { style: { color: colors.textSecondary } },
    xAxis: { ...axis },
    yAxis: { ...axis },
    legend: {
      align: "center",
      verticalAlign: "bottom",
      layout: "horizontal",
      itemDistance: 18,
      padding: 8,
      symbolHeight: 8,
      symbolRadius: 0,
      symbolWidth: 18,
      itemStyle: { color: colors.text },
      itemHoverStyle: { color: colors.accent },
      itemHiddenStyle: { color: colors.textMuted },
    },
    tooltip: {
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      borderRadius: 4,
      padding: 10,
      shadow: false,
      style: { color: colors.text, fontSize: "12px" },
    },
    plotOptions: {
      series: {
        animation: { duration: 350 },
        borderRadius: 2,
        states: { hover: { lineWidthPlus: 1 } },
        marker: { enabledThreshold: 3, radius: 2 },
      } as PlotSeriesOptions,
      column: { borderRadius: 2, groupPadding: 0.12, pointPadding: 0.04 },
      bar: { borderRadius: 2, groupPadding: 0.12, pointPadding: 0.04 },
      candlestick: {
        color: colors.loss,
        upColor: colors.gain,
        lineColor: colors.loss,
        upLineColor: colors.gain,
      },
    },
    rangeSelector: {
      buttonTheme: {
        fill: "none",
        stroke: colors.grid,
        style: { color: colors.textSecondary, fontWeight: "normal" },
        states: {
          hover: { fill: colors.accentWash, style: { color: colors.accent } },
          select: { fill: colors.accent, style: { color: colors.textOnAccent } },
        },
      },
      inputStyle: { color: colors.text },
      inputBoxBorderColor: colors.grid,
      labelStyle: { color: colors.textMuted },
    },
    navigator: {
      maskFill: `${colors.accent}26`,
      outlineColor: colors.grid,
      handles: { backgroundColor: colors.surface, borderColor: colors.barMute },
      series: { color: colors.barMute, lineColor: colors.barMute },
      xAxis: {
        gridLineColor: colors.grid,
        labels: { style: { color: colors.textMuted } },
      },
    },
    scrollbar: {
      barBackgroundColor: colors.barMute,
      barBorderColor: colors.grid,
      buttonBackgroundColor: colors.surface,
      buttonBorderColor: colors.grid,
      buttonArrowColor: colors.textMuted,
      trackBackgroundColor: colors.surface,
      trackBorderColor: colors.grid,
      rifleColor: colors.textMuted,
    },
    credits: { enabled: false },
  };
}
