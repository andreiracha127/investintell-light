/**
 * Pure option builder: pairwise correlation heatmap (Highcharts Core).
 *
 * Two colour modes:
 *  - Legacy (default): a continuous 0..1 colorAxis mapping accent-wash -> accent,
 *    so strong positive co-movement reads as the saturated accent. Negative
 *    correlations clamp onto the wash end.
 *  - Diverging (`config.diverging`): a signed -1..+1 colorAxis — `negativeColor`
 *    at -1, `zeroColor` at 0, accent at +1 — so negative correlations read on
 *    their own (red/loss or blue) side instead of collapsing to the wash. Used by
 *    the Statistics and Builder correlation matrices.
 *
 * The colorAxis is hidden (`visible: false`): the page renders the matching
 * gradient legend in the panel header. Per-cell labels flip to the on-accent
 * colour once the fill gets dark enough (by |value| when diverging). The y-axis
 * is reversed so the unit diagonal runs from the top-left.
 *
 * The `highcharts/modules/heatmap` module is registered globally by the chart
 * wrapper — this pure builder only returns options.
 */
import type { Options } from "highcharts";
import type { Point } from "highcharts";

import type { CorrelationMatrix } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

/** Above this |correlation| the fill is dark enough for light text. */
const LIGHT_LABEL_THRESHOLD = 0.55;

/** Custom heatmap point fields not present on the base HC Point type. */
type HeatmapPoint = Point & { value: number };

export interface HeatmapConfig {
  /** Use a signed -1..+1 diverging scale instead of the legacy 0..1 ramp. */
  diverging?: boolean;
  /** Hue at value -1 when diverging (defaults to the loss colour). */
  negativeColor?: string;
  /** Hue at value 0 when diverging (defaults to the chart surface). */
  zeroColor?: string;
}

export function buildHcHeatmapOption(
  correlation: CorrelationMatrix,
  colors: ChartColors,
  config: HeatmapConfig = {},
): Options {
  const diverging = config.diverging ?? false;

  const data = correlation.matrix.flatMap((row, y) =>
    row.map((value, x) => ({
      x,
      y,
      value,
      dataLabels: {
        color:
          (diverging ? Math.abs(value) : value) > LIGHT_LABEL_THRESHOLD
            ? colors.textOnAccent
            : colors.text,
      },
    })),
  );

  const colorAxis = diverging
    ? {
        // Hidden — the page header carries the -1 -> 0 -> +1 gradient legend.
        visible: false,
        min: -1,
        max: 1,
        stops: [
          [0, config.negativeColor ?? colors.loss],
          [0.5, config.zeroColor ?? colors.surface],
          [1, colors.accent],
        ] as [number, string][],
      }
    : {
        // Hidden — the page header carries the 0.0 -> 1.0 gradient legend.
        // Values below 0 clamp onto the wash end; tooltips keep the exact value.
        visible: false,
        min: 0,
        max: 1,
        stops: [
          [0, colors.accentWash],
          [1, colors.accent],
        ] as [number, string][],
      };

  return {
    chart: { type: "heatmap" },
    legend: { enabled: false },
    xAxis: { categories: correlation.tickers },
    yAxis: {
      categories: correlation.tickers,
      title: { text: undefined },
      // Top-to-bottom row order so the unit diagonal runs from the top-left.
      reversed: true,
    },
    colorAxis,
    tooltip: {
      // HC tooltip formatter: `this` is the hovered Point directly.
      // For heatmap, x = column index, y = row index, value = cell value.
      formatter(this: Point) {
        const pt = this as unknown as HeatmapPoint;
        return `${correlation.tickers[pt.y ?? 0]} × ${correlation.tickers[pt.x]}: ${formatNumber(pt.value)}`;
      },
    },
    series: [
      {
        type: "heatmap",
        name: "Correlation",
        data,
        borderColor: colors.grid,
        borderWidth: 1,
        dataLabels: {
          enabled: true,
          // Legacy ECharts used fontSize:10; HC puts font size in style.
          style: { fontSize: "10px" },
          // HC dataLabels formatter: `this` is the Point itself.
          formatter(this: Point) {
            return formatNumber((this as unknown as HeatmapPoint).value);
          },
        },
        states: {
          hover: {
            borderWidth: 2,
            borderColor: colors.grid,
          },
        },
      },
    ],
  };
}
