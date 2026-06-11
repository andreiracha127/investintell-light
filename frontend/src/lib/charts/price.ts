/**
 * Pure option builder: candlestick + volume chart (two stacked grids,
 * shared dataZoom, axis crosshair tooltip). No state, no React.
 */
import type { EChartsOption } from "echarts";

import type { Candle } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatCompact, formatCurrency } from "@/lib/format";

export function buildPriceOption(
  candles: Candle[],
  colors: ChartColors,
): EChartsOption {
  const dates = candles.map((c) => c.date);
  // ECharts candlestick item order: [open, close, low, high].
  const ohlc = candles.map((c) => [c.open, c.close, c.low, c.high]);
  const volumes = candles.map((c) => ({
    value: c.volume,
    itemStyle: {
      color: c.close >= c.open ? colors.gain : colors.loss,
      opacity: 0.45,
    },
  }));

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
    axisPointer: { link: [{ xAxisIndex: "all" }] },
    grid: [
      { left: 72, right: 16, top: 16, height: "56%" },
      { left: 72, right: 16, top: "76%", height: "12%" },
    ],
    xAxis: [
      {
        type: "category",
        gridIndex: 0,
        data: dates,
        axisLine: { lineStyle: { color: colors.grid } },
        axisTick: { show: false },
        axisLabel: { show: false },
      },
      {
        type: "category",
        gridIndex: 1,
        data: dates,
        axisLine: { lineStyle: { color: colors.grid } },
        axisTick: { show: false },
        axisLabel: { color: colors.textMuted },
      },
    ],
    yAxis: [
      {
        type: "value",
        gridIndex: 0,
        scale: true,
        splitLine: { lineStyle: { color: colors.grid } },
        axisLabel: {
          color: colors.textMuted,
          formatter: (value: number) => formatCurrency(value),
        },
      },
      {
        type: "value",
        gridIndex: 1,
        splitNumber: 2,
        splitLine: { show: false },
        axisLabel: {
          color: colors.textMuted,
          formatter: (value: number) => formatCompact(value),
        },
      },
    ],
    dataZoom: [
      { type: "inside", xAxisIndex: [0, 1], start: 0, end: 100 },
      {
        type: "slider",
        xAxisIndex: [0, 1],
        bottom: 6,
        height: 18,
        borderColor: colors.grid,
        fillerColor: "transparent",
        handleStyle: { color: colors.accentMuted },
        moveHandleStyle: { color: colors.accentMuted },
        dataBackground: {
          lineStyle: { color: colors.textMuted },
          areaStyle: { color: colors.grid },
        },
        textStyle: { color: colors.textMuted },
      },
    ],
    series: [
      {
        name: "Price",
        type: "candlestick",
        xAxisIndex: 0,
        yAxisIndex: 0,
        data: ohlc,
        itemStyle: {
          color: colors.gain,
          color0: colors.loss,
          borderColor: colors.gain,
          borderColor0: colors.loss,
        },
      },
      {
        name: "Volume",
        type: "bar",
        xAxisIndex: 1,
        yAxisIndex: 1,
        data: volumes,
        tooltip: {
          valueFormatter: (value) =>
            typeof value === "number" ? formatCompact(value) : String(value ?? ""),
        },
      },
    ],
  };
}
