/**
 * Pure option builder: pairwise correlation heatmap.
 *
 * x/y axes carry the same ticker order as the backend matrix; the continuous
 * visualMap maps -1..1 onto loss -> surface -> gain so anti-correlation reads
 * red and co-movement reads green on the dark theme.
 */
import type { EChartsOption } from "echarts";

import type { CorrelationMatrix } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";

type HeatmapCell = [number, number, number];

export function buildHeatmapOption(
  correlation: CorrelationMatrix,
  colors: ChartColors,
): EChartsOption {
  const cells: HeatmapCell[] = correlation.matrix.flatMap((row, y) =>
    row.map((value, x): HeatmapCell => [x, y, value]),
  );

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      position: "top",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (params) => {
        // Item-trigger tooltip on a heatmap always carries a single cell.
        const [x, y, value] = (params as unknown as { value: HeatmapCell })
          .value;
        return `${correlation.tickers[y]} × ${correlation.tickers[x]}: ${formatNumber(value)}`;
      },
    },
    grid: { left: 64, right: 16, top: 16, bottom: 64 },
    xAxis: {
      type: "category",
      data: correlation.tickers,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textSecondary },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: correlation.tickers,
      // Top-to-bottom row order so the unit diagonal runs from the top-left.
      inverse: true,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textSecondary },
      splitArea: { show: false },
    },
    visualMap: {
      type: "continuous",
      min: -1,
      max: 1,
      calculable: false,
      orient: "horizontal",
      left: "center",
      bottom: 0,
      itemWidth: 10,
      itemHeight: 120,
      inRange: { color: [colors.loss, colors.surface, colors.gain] },
      textStyle: { color: colors.textMuted },
    },
    series: [
      {
        name: "Correlation",
        type: "heatmap",
        data: cells,
        label: {
          show: true,
          color: colors.text,
          formatter: (params) =>
            formatNumber((params.value as HeatmapCell)[2]),
        },
        itemStyle: { borderColor: colors.grid, borderWidth: 1 },
        emphasis: { itemStyle: { borderColor: colors.accent } },
      },
    ],
  };
}
