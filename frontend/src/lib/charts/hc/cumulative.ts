/**
 * Pure option builder: cumulative return of asset vs benchmark (Highcharts Core).
 * Two `line` series on a shared date grid; y-axis percent-formatted.
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets
 * only series, colors, and value formatting.
 *
 * Config:
 *  - `growthOf100` — opt-in "Growth of $100" mode (Builder Risk tab): rebases
 *    each cumulative-return series to a $100 start (value = 100·(1+ret)),
 *    titles the y-axis "Growth of $100", `$`-formats ticks and the shared
 *    tooltip, enables an x crosshair, and dashes the benchmark line. Default
 *    off — Portfolio keeps the signed-percent presentation.
 */
import type { Options } from "highcharts";

import type { CumulativeReturns } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  compactDatetimeXAxis,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatPercent } from "@/lib/format";

export interface CumulativeConfig {
  /** Rebase to a $100 start with `$` ticks/tooltip and a dashed benchmark. */
  growthOf100?: boolean;
}

/** $-format a number to 2 dp (no token dependence — pure presentation). */
function dollars(value: number): string {
  return `$${value.toFixed(2)}`;
}

export function buildHcCumulativeOption(
  cumulative: CumulativeReturns,
  assetLabel: string,
  benchmarkLabel: string,
  colors: ChartColors,
  config: CumulativeConfig = {},
): Options {
  const growth = config.growthOf100 ?? false;
  // In growth mode each series is rebased so $100 invested tracks the curve.
  const toData = (series: CumulativeReturns["asset"]) =>
    growth
      ? toDatetimeData(series).map(([x, y]) => [x, 100 * (1 + (y as number))])
      : toDatetimeData(series);

  return {
    chart: { type: "line" },
    legend: { enabled: true },
    xAxis: growth
      ? { ...compactDatetimeXAxis(), crosshair: { width: 1, color: colors.barMute } }
      : compactDatetimeXAxis(),
    yAxis: {
      title: { text: growth ? "Growth of $100" : undefined },
      labels: {
        formatter() {
          return growth
            ? dollars(this.value as number)
            : formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        const header = formatTimestampDate(this.x);
        const rows = (this.points ?? [])
          .map(
            (pt) =>
              `<span style="color:${pt.series.color}">●</span> ${pt.series.name}: <b>${
                growth
                  ? dollars(pt.y as number)
                  : formatPercent(pt.y as number, 2, { signed: true })
              }</b>`,
          )
          .join("<br/>");
        return `${header}<br/>${rows}`;
      },
    },
    series: [
      {
        type: "line",
        name: benchmarkLabel,
        data: toData(cumulative.benchmark),
        color: colors.barMute,
        lineWidth: 2,
        marker: { enabled: false },
        ...(growth ? { dashStyle: "ShortDash" as const } : {}),
      },
      {
        type: "line",
        name: assetLabel,
        data: toData(cumulative.asset),
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
      },
    ],
  };
}
