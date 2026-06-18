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
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatNumber, formatPercent } from "@/lib/format";

export interface RollingAxisOptions {
  /** Format y values as percent (decimal-fraction input, e.g. 0.12 = 12%). */
  yPercent?: boolean;
  /** Fixed y-axis minimum (e.g. -1 for correlation). Omitted = auto-scale. */
  yMin?: number;
  /** Fixed y-axis maximum (e.g. 1 for correlation). Omitted = auto-scale. */
  yMax?: number;
  /** Optional y-axis title (e.g. "Volatility", "Growth of $100"). */
  yTitle?: string;
}

export function buildHcRollingOption(
  series: SeriesPoint[],
  label: string,
  colors: ChartColors,
  { yPercent = false, yMin, yMax, yTitle }: RollingAxisOptions = {},
): Options {
  const formatValue = (value: number): string =>
    yPercent ? formatPercent(value, 1) : formatNumber(value);

  return {
    chart: { type: "line" },
    legend: { enabled: false },
    // Hovering anywhere drops a vertical guide to the date — the mockup's
    // read-the-chart affordance. Colour only (grid chrome stays the theme's).
    xAxis: { ...compactDatetimeXAxis(), crosshair: { width: 1, color: colors.grid } },
    yAxis: {
      title: { text: yTitle },
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
        return `${formatTimestampDate(this.x)}<br/><b>${formatValue(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "line",
        name: label,
        data: toDatetimeData(series),
        color: colors.accent,
        lineWidth: 1.6,
        marker: { enabled: false },
      },
    ],
  };
}
