/**
 * Pure option builder: Builder → Projection percentile fan (Highcharts Core).
 *
 * Claude Design upgrade of the Monte-Carlo cone for the Builder workspace.
 * Across projection horizons, three nested arearange bands (5–95, 10–90,
 * 25–75 percentiles) sit behind an emphasized median line, with titled axes,
 * a zero reference line, signed-percent (or unitless) ticks and a rich
 * per-horizon tooltip. The caller selects percent formatting for
 * fraction-valued statistics (Return / Worst drop) or plain-number formatting
 * for unitless statistics such as Sharpe.
 *
 * Mirrors the `cone.ts` contract (ConfidenceBar[] + ConeUnit) so it is a
 * drop-in for the Builder ProjectionTab. Global chrome (tooltip background,
 * grid, animation) is owned by the Graphite theme applied via setOptions.
 */
import type { Options } from "highcharts";

import type { ConfidenceBar } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";

export type ProjectionUnit = "fraction" | "unitless";

type PercentileKey =
  | "pct_5"
  | "pct_10"
  | "pct_25"
  | "pct_50"
  | "pct_75"
  | "pct_90"
  | "pct_95";

export function buildHcBuilderProjectionOption(
  bars: ConfidenceBar[],
  unit: ProjectionUnit,
  colors: ChartColors,
  axisTitle = "Projected outcome",
): Options {
  const categories = bars.map((bar) => bar.horizon);
  const isFraction = unit === "fraction";

  const formatValue = (value: number) =>
    isFraction
      ? formatPercent(value, 1, { signed: true })
      : formatNumber(value, 2);
  const formatTick = (value: number) =>
    isFraction
      ? formatPercent(value, 0, { signed: true })
      : formatNumber(value, 1);

  const band = (lowKey: PercentileKey, highKey: PercentileKey) =>
    bars.map((bar) => [bar[lowKey], bar[highKey]]);

  return {
    chart: { type: "arearange" },
    legend: { enabled: true },
    xAxis: {
      categories,
      crosshair: true,
      tickWidth: 0,
      title: {
        text: "Horizon",
      },
    },
    yAxis: {
      title: { text: axisTitle },
      labels: {
        formatter() {
          return formatTick(this.value as number);
        },
      },
      plotLines: [
        {
          value: 0,
          color: colors.textMuted,
          width: 1,
          dashStyle: "Dash",
          zIndex: 2,
        },
      ],
    },
    tooltip: {
      shared: true,
      useHTML: true,
      formatter() {
        const header = this.x == null ? "" : String(this.x);
        const points = this.points ?? [];
        const row = (label: string, value: number, bold = false) =>
          `<span style="color:${colors.textMuted}">${label}</span> ${
            bold ? "<b>" : ""
          }${formatValue(value)}${bold ? "</b>" : ""}`;

        // Prefer the explicit per-bar percentiles for a complete read-out.
        const idx = points.length
          ? (points[0] as unknown as { point: { index: number } }).point.index
          : 0;
        const bar = bars[idx];
        if (!bar) {
          const rows = points
            .map((point) => {
              const rangePoint = (
                point as unknown as { point: { low?: number; high?: number } }
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
        }
        return [
          `<b>${header}</b>`,
          row("95th", bar.pct_95),
          row("75th", bar.pct_75),
          `<span style="color:${colors.accent}">●</span> ${row("Median", bar.pct_50, true)}`,
          row("25th", bar.pct_25),
          row("5th", bar.pct_5),
        ].join("<br/>");
      },
    },
    series: [
      {
        type: "arearange",
        name: "5–95%",
        data: band("pct_5", "pct_95"),
        color: colors.accentWash,
        fillOpacity: 0.35,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 0,
      },
      {
        type: "arearange",
        name: "10–90%",
        data: band("pct_10", "pct_90"),
        color: colors.accentWash,
        fillOpacity: 0.6,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 1,
      },
      {
        type: "arearange",
        name: "25–75%",
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
        lineWidth: 2.4,
        marker: { enabled: true, radius: 3 },
        zIndex: 3,
      },
    ],
  };
}
