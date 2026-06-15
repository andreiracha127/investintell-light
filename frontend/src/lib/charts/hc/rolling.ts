/**
 * Pure option builder: small rolling-metric line chart (volatility, beta,
 * correlation) — Highcharts Core port of the ECharts rolling builder.
 *
 * The global Graphite theme (highchartsTheme) owns axis/grid/tooltip chrome.
 * This builder sets ONLY: series, series color, value formatting, and the
 * optional fixed y-axis bounds.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber, formatPercent } from "@/lib/format";

export interface RollingAxisOptions {
  /** Format y values as percent (decimal-fraction input, e.g. 0.12 = 12%). */
  yPercent?: boolean;
  /** Fixed y-axis minimum (e.g. -1 for correlation). Omitted = auto-scale. */
  yMin?: number;
  /** Fixed y-axis maximum (e.g. 1 for correlation). Omitted = auto-scale. */
  yMax?: number;
}

export function buildHcRollingOption(
  series: SeriesPoint[],
  label: string,
  colors: ChartColors,
  { yPercent = false, yMin, yMax }: RollingAxisOptions = {},
): Options {
  const formatValue = (value: number): string =>
    yPercent ? formatPercent(value, 1) : formatNumber(value);

  return {
    chart: { type: "line" },
    xAxis: {
      categories: series.map((p) => p[0]),
      crosshair: true,
      tickWidth: 0,
    },
    yAxis: {
      title: { text: undefined },
      ...(yMin !== undefined ? { min: yMin } : {}),
      ...(yMax !== undefined ? { max: yMax } : {}),
      labels: {
        formatter() {
          return formatValue(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        return `${this.x}<br/><b>${formatValue(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "line",
        name: label,
        data: series.map((p) => p[1]),
        color: colors.accent,
        lineWidth: 1.6,
        marker: { enabled: false },
      },
    ],
  };
}
