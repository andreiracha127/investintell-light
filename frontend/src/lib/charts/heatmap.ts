/**
 * Pure option builder: pairwise correlation heatmap.
 *
 * x/y axes carry the same ticker order as the backend matrix; the continuous
 * visualMap maps intensity onto accent-wash -> accent (Cockpit gradient), so
 * strong co-movement reads as the saturated accent. The map itself is hidden:
 * the page renders the matching gradient legend in the panel header. Cell
 * labels flip to the on-accent color once the fill gets dark enough.
 */
import type { EChartsOption } from "echarts";

import type { CorrelationMatrix } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";

type HeatmapCell = [number, number, number];

/** Above this correlation the accent fill is dark enough for light text. */
const LIGHT_LABEL_THRESHOLD = 0.55;

export function buildHeatmapOption(
  correlation: CorrelationMatrix,
  colors: ChartColors,
): EChartsOption {
  const cells = correlation.matrix.flatMap((row, y) =>
    row.map((value, x) => ({
      value: [x, y, value] as HeatmapCell,
      label: {
        color:
          value > LIGHT_LABEL_THRESHOLD ? colors.textOnAccent : colors.text,
      },
    })),
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
    grid: { left: 64, right: 16, top: 16, bottom: 40 },
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
      // Hidden — the page header carries the 0.0 → 1.0 gradient legend.
      // Values below 0 clamp onto the wash end; tooltips keep the exact value.
      show: false,
      type: "continuous",
      min: 0,
      max: 1,
      inRange: { color: [colors.accentWash, colors.accent] },
    },
    series: [
      {
        name: "Correlation",
        type: "heatmap",
        data: cells,
        label: {
          show: true,
          fontSize: 10,
          formatter: (params) =>
            formatNumber((params.value as HeatmapCell)[2]),
        },
        itemStyle: { borderColor: colors.grid, borderWidth: 1 },
        emphasis: { itemStyle: { borderColor: colors.text } },
      },
    ],
  };
}
