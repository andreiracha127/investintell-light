/**
 * Pure option builder: NAV line in currency units (Highcharts Core).
 * Reference template for the ECharts -> Highcharts builder migration (P1):
 * the global Graphite theme owns axis/grid/tooltip chrome; the builder sets
 * only the series, the accent color, and currency value formatting.
 *
 * Config:
 *  - `growthOf100` — opt-in "Growth of $100" mode (Builder Backtest OOS curve):
 *    rebases the series to a $100 start, renders it as an `areaspline` with an
 *    accent linear-gradient fill, titles the y-axis "Growth of $100" and
 *    `$`-formats ticks/tooltip. Default off — Portfolio keeps the currency NAV
 *    line.
 */
import type { Options } from "highcharts";

import type { SeriesPoint } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatCurrency } from "@/lib/format";

export interface NavConfig {
  /** Rebase to a $100 start and render as an accent-gradient areaspline. */
  growthOf100?: boolean;
}

/** $-format a number to 2 dp (pure presentation, no token dependence). */
function dollars(value: number): string {
  return `$${value.toFixed(2)}`;
}

/**
 * Rebase a series so its first finite value maps to 100 (Growth of $100).
 * Falls back to the raw values if the base is zero/non-finite.
 */
function rebaseTo100(data: Array<[number, number]>): Array<[number, number]> {
  const base = data.find(([, y]) => Number.isFinite(y) && y !== 0)?.[1];
  if (base == null) return data;
  return data.map(([x, y]) => [x, (y / base) * 100]);
}

export function buildHcNavOption(
  nav: SeriesPoint[],
  colors: ChartColors,
  config: NavConfig = {},
): Options {
  const growth = config.growthOf100 ?? false;
  const points = toDatetimeData(nav) as Array<[number, number]>;
  const data = growth ? rebaseTo100(points) : points;
  const fmt = growth ? dollars : (v: number) => formatCurrency(v);

  return {
    chart: { type: growth ? "areaspline" : "line" },
    legend: { enabled: false },
    xAxis: compactDatetimeXAxis(),
    yAxis: {
      title: { text: growth ? "Growth of $100" : undefined },
      labels: {
        formatter() {
          return fmt(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        return `${formatTimestampDate(this.x)}<br/><b>${fmt(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: growth ? "areaspline" : "line",
        name: growth ? "Out-of-sample" : "NAV",
        data,
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
        ...(growth
          ? {
              fillColor: {
                linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
                stops: [
                  [0, colors.accentWash],
                  [1, colors.surface],
                ] as [number, string][],
              },
            }
          : {}),
      },
    ],
  };
}
