/**
 * Pure option builders: Builder → Projection percentile fan (Highcharts Core).
 *
 * Claude Design upgrade of the Monte-Carlo cone for the Builder workspace.
 * `buildHcBuilderProjectionOption` draws three nested arearange bands (5–95,
 * 10–90, 25–75 percentiles, one color family at increasing opacity for a
 * smooth gradient) behind an emphasized median line. `buildHcBuilderProjectionLinesOption`
 * is the classic alternative — one line per percentile window, no shaded
 * area — used for statistics (Sharpe) where a widening shaded cone would
 * misleadingly imply growing uncertainty that isn't there. Both share titled
 * axes, a zero reference line, signed-percent (or unitless) ticks and a rich
 * per-horizon tooltip; the caller selects percent formatting for
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

function valueFormatter(unit: ProjectionUnit) {
  return (value: number) =>
    unit === "fraction"
      ? formatPercent(value, 1, { signed: true })
      : formatNumber(value, 2);
}

function tickFormatter(unit: ProjectionUnit) {
  return (value: number) =>
    unit === "fraction"
      ? formatPercent(value, 0, { signed: true })
      : formatNumber(value, 1);
}

export function buildHcBuilderProjectionOption(
  bars: ConfidenceBar[],
  unit: ProjectionUnit,
  colors: ChartColors,
  axisTitle = "Projected outcome",
): Options {
  const categories = bars.map((bar) => bar.horizon);

  // Median rendered in a distinct hue from the accent-family bands (mockup uses
  // Carbon blue) — the themed --color-chart-blue token.
  const medianColor = colors.blue;

  const formatValue = valueFormatter(unit);
  const formatTick = tickFormatter(unit);

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
        text: "Months · history → forecast",
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
          `<span style="color:${medianColor}">●</span> ${row("Median", bar.pct_50, true)}`,
          row("25th", bar.pct_25),
          row("5th", bar.pct_5),
        ].join("<br/>");
      },
    },
    series: [
      // Same color family (accentWash) at progressively higher opacity for all
      // three bands — a continuous gradient instead of a jump between two
      // distinct color tokens, which read as a hard edge between the 10–90%
      // and 25–75% bands.
      {
        type: "arearange",
        name: "5–95%",
        data: band("pct_5", "pct_95"),
        color: colors.accentWash,
        fillOpacity: 0.22,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 0,
      },
      {
        type: "arearange",
        name: "10–90%",
        data: band("pct_10", "pct_90"),
        color: colors.accentWash,
        fillOpacity: 0.4,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 1,
      },
      {
        type: "arearange",
        name: "25–75%",
        data: band("pct_25", "pct_75"),
        color: colors.accentWash,
        fillOpacity: 0.6,
        lineWidth: 0,
        marker: { enabled: false },
        zIndex: 2,
      },
      {
        type: "line",
        name: "Median",
        data: bars.map((bar) => bar.pct_50),
        color: medianColor,
        lineWidth: 2.4,
        marker: { enabled: true, radius: 3, fillColor: medianColor },
        zIndex: 3,
      },
    ],
  };
}

/**
 * Classic line-per-percentile variant: no shaded area, just one line per
 * percentile window plus the median. Use this instead of
 * `buildHcBuilderProjectionOption` for statistics whose per-horizon spread
 * narrows over time by design (e.g. Sharpe — a longer simulated track record
 * makes the risk-adjusted-return estimate *more* reliable, not less), where a
 * widening shaded cone would visually imply growing uncertainty that isn't
 * actually there.
 */
export function buildHcBuilderProjectionLinesOption(
  bars: ConfidenceBar[],
  unit: ProjectionUnit,
  colors: ChartColors,
  axisTitle = "Projected outcome",
): Options {
  const categories = bars.map((bar) => bar.horizon);
  const medianColor = colors.blue;
  const formatValue = valueFormatter(unit);
  const formatTick = tickFormatter(unit);

  const LINES: Array<{
    key: PercentileKey;
    name: string;
    color: string;
    dashStyle: "Solid" | "Dash" | "ShortDot";
    lineWidth: number;
  }> = [
    { key: "pct_95", name: "95th", color: colors.accentWash, dashStyle: "ShortDot", lineWidth: 1.4 },
    { key: "pct_75", name: "75th", color: colors.accentMuted, dashStyle: "Dash", lineWidth: 1.6 },
    { key: "pct_50", name: "Median", color: medianColor, dashStyle: "Solid", lineWidth: 2.4 },
    { key: "pct_25", name: "25th", color: colors.accentMuted, dashStyle: "Dash", lineWidth: 1.6 },
    { key: "pct_5", name: "5th", color: colors.accentWash, dashStyle: "ShortDot", lineWidth: 1.4 },
  ];

  return {
    chart: { type: "line" },
    legend: { enabled: true },
    xAxis: {
      categories,
      crosshair: true,
      tickWidth: 0,
      title: {
        text: "Months · history → forecast",
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
        const idx = this.points?.length
          ? (this.points[0] as unknown as { point: { index: number } }).point.index
          : 0;
        const bar = bars[idx];
        if (!bar) return "";
        const row = (label: string, value: number, bold = false) =>
          `<span style="color:${colors.textMuted}">${label}</span> ${
            bold ? "<b>" : ""
          }${formatValue(value)}${bold ? "</b>" : ""}`;
        return [
          `<b>${header}</b>`,
          row("95th", bar.pct_95),
          row("75th", bar.pct_75),
          `<span style="color:${medianColor}">●</span> ${row("Median", bar.pct_50, true)}`,
          row("25th", bar.pct_25),
          row("5th", bar.pct_5),
        ].join("<br/>");
      },
    },
    series: LINES.map((line) => ({
      type: "line",
      name: line.name,
      data: bars.map((bar) => bar[line.key]),
      color: line.color,
      dashStyle: line.dashStyle,
      lineWidth: line.lineWidth,
      marker: { enabled: line.key === "pct_50", radius: 3, fillColor: medianColor },
      zIndex: line.key === "pct_50" ? 3 : 1,
    })),
  };
}
