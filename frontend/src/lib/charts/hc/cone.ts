/**
 * Pure option builder: Monte Carlo confidence cone (Highcharts Core).
 *
 * Across projection horizons, three nested arearange bands (5-95, 10-90,
 * 25-75 percentiles) sit behind the median (pct_50) line. The caller selects
 * percent formatting for fraction-valued statistics or number formatting for
 * unitless statistics such as Sharpe.
 */
import type { Options } from "highcharts";

import type { ConfidenceBar } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";

export type ConeUnit = "fraction" | "unitless";

type PercentileKey =
  | "pct_5"
  | "pct_10"
  | "pct_25"
  | "pct_50"
  | "pct_75"
  | "pct_90"
  | "pct_95";

export function buildHcConeOption(
  bars: ConfidenceBar[],
  unit: ConeUnit,
  colors: ChartColors,
): Options {
  const categories = bars.map((bar) => bar.horizon);
  const formatValue = (value: number) =>
    unit === "fraction"
      ? formatPercent(value, 1, { signed: true })
      : formatNumber(value, 2);

  const band = (lowKey: PercentileKey, highKey: PercentileKey) =>
    bars.map((bar) => [bar[lowKey], bar[highKey]]);

  return {
    chart: { type: "arearange" },
    legend: { enabled: true },
    xAxis: { categories, crosshair: true, tickWidth: 0 },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return unit === "fraction"
            ? formatPercent(this.value as number, 0)
            : formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter() {
        const header = this.x == null ? "" : String(this.x);
        const rows = (this.points ?? [])
          .map((point) => {
            const rangePoint = (
              point as unknown as {
                point: { low?: number; high?: number };
              }
            ).point;
            if (
              typeof rangePoint.low === "number" &&
              typeof rangePoint.high === "number"
            ) {
              return `<span style="color:${point.series.color}">●</span> ${point.series.name}: <b>${formatValue(rangePoint.low)}</b> … <b>${formatValue(rangePoint.high)}</b>`;
            }
            return `<span style="color:${point.series.color}">●</span> ${point.series.name}: <b>${formatValue(point.y as number)}</b>`;
          })
          .join("<br/>");
        return `${header}<br/>${rows}`;
      },
    },
    series: [
      {
        type: "arearange",
        name: "5-95%",
        data: band("pct_5", "pct_95"),
        color: colors.accentWash,
        fillOpacity: 0.35,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 0,
      },
      {
        type: "arearange",
        name: "10-90%",
        data: band("pct_10", "pct_90"),
        color: colors.accentWash,
        fillOpacity: 0.6,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 1,
      },
      {
        type: "arearange",
        name: "25-75%",
        data: band("pct_25", "pct_75"),
        color: colors.accentMuted,
        fillOpacity: 0.75,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 2,
      },
      {
        type: "line",
        name: "Median",
        data: bars.map((bar) => bar.pct_50),
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: true, radius: 3 },
        zIndex: 3,
      },
    ],
  };
}
