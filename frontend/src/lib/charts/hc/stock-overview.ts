/**
 * Pure option builders for the /stocks overview panels.
 *
 * These replace the old hand-rolled HTML bars with real Highcharts Core
 * charts while keeping the same data contract and dense cockpit-style read.
 */
import type { ColorString, GradientColorObject, Options, Point, SeriesBarOptions } from "highcharts";

import type { MarketBreadth, SectorPerf } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";

function gradient(from: string, to: string): GradientColorObject {
  return {
    linearGradient: { x1: 0, x2: 1, y1: 0, y2: 0 },
    stops: [
      [0, from],
      [1, to],
    ],
  };
}

function signedPercentLabel(value: number, dp = 2): string {
  return formatPercent(value, dp, { signed: true });
}

function alpha(color: string, hexAlpha: string): string {
  return color.startsWith("#") ? `${color}${hexAlpha}` : color;
}

export function buildHcSectorPerformanceOption(
  sectors: SectorPerf[],
  colors: ChartColors,
): Options | null {
  if (!sectors.length) return null;

  const maxAbs = Math.max(...sectors.map((s) => Math.abs(s.change_pct_median)), 0.001);
  const axisLimit = maxAbs * 1.18;
  const gain = gradient(alpha(colors.gain, "6f"), colors.gain);
  const loss = gradient(colors.loss, alpha(colors.loss, "70"));

  return {
    chart: {
      type: "bar",
      height: Math.max(292, sectors.length * 24 + 58),
      spacing: [6, 18, 4, 8],
    },
    title: { text: undefined },
    legend: { enabled: false },
    xAxis: {
      categories: sectors.map((s) => s.sector),
      tickWidth: 0,
      lineWidth: 0,
      labels: {
        style: { color: colors.textSecondary, fontSize: "12px" },
      },
    },
    yAxis: {
      min: -axisLimit,
      max: axisLimit,
      title: { text: undefined },
      gridLineColor: alpha(colors.grid, "90"),
      gridLineDashStyle: "ShortDot",
      tickAmount: 5,
      plotBands: [
        { from: -axisLimit, to: 0, color: alpha(colors.loss, "08") },
        { from: 0, to: axisLimit, color: alpha(colors.gain, "08") },
      ],
      plotLines: [{ value: 0, color: colors.textMuted, width: 1, zIndex: 4 }],
      labels: {
        enabled: false,
      },
    },
    tooltip: {
      formatter(this: Point) {
        const sector = this.category as string;
        const row = sectors.find((s) => s.sector === sector);
        const n = row ? `<br/><span>${formatNumber(row.n, 0)} constituents</span>` : "";
        return `<b>${sector}</b><br/>Median: <b>${signedPercentLabel(this.y as number)}</b>${n}`;
      },
    },
    plotOptions: {
      bar: {
        borderColor: colors.surface,
        borderRadius: 2,
        borderWidth: 1,
        pointPadding: 0.18,
        groupPadding: 0.12,
        dataLabels: {
          enabled: true,
          align: "left",
          inside: false,
          crop: false,
          overflow: "allow",
          x: 4,
          formatter() {
            return signedPercentLabel(this.y as number);
          },
          style: {
            color: colors.textSecondary,
            fontSize: "11px",
            fontWeight: "bold",
            textOutline: "none",
          },
        },
        states: {
          hover: {
            brightness: 0.16,
          },
        },
      },
      series: {
        animation: { duration: 850 },
      },
    },
    series: [
      {
        type: "bar",
        name: "Median change",
        data: sectors.map((s) => ({
          y: s.change_pct_median,
          color: (s.change_pct_median >= 0 ? gain : loss) as ColorString | GradientColorObject,
          custom: { constituents: s.n },
        })),
      },
    ],
  };
}

export function buildHcMarketBreadthOption(
  breadth: MarketBreadth,
  colors: ChartColors,
): Options {
  const total = breadth.tracked || 1;
  const advShare = breadth.advancing / total;
  const decShare = breadth.declining / total;

  return buildHcTwoSidedForceOption({
    negative: {
      name: "Declining",
      value: decShare,
      detail: `${formatNumber(breadth.declining, 0)} declining stocks`,
    },
    positive: {
      name: "Advancing",
      value: advShare,
      detail: `${formatNumber(breadth.advancing, 0)} advancing stocks`,
    },
    colors,
  });
}

export function buildHcVolumeBreadthOption(
  breadth: MarketBreadth,
  colors: ChartColors,
): Options {
  const upVolumeShare = breadth.up_volume_share;
  const downVolumeShare = Math.max(0, 1 - upVolumeShare);

  return buildHcTwoSidedForceOption({
    negative: {
      name: "Down-volume",
      value: downVolumeShare,
      detail: "Share of traded volume in declining or unchanged stocks",
    },
    positive: {
      name: "Up-volume",
      value: upVolumeShare,
      detail: "Share of traded volume in advancing stocks",
    },
    colors,
    positiveColor: gradient(alpha(colors.blue, "72"), colors.blue),
  });
}

function buildHcTwoSidedForceOption({
  negative,
  positive,
  colors,
  positiveColor,
}: {
  negative: { detail: string; name: string; value: number };
  positive: { detail: string; name: string; value: number };
  colors: ChartColors;
  positiveColor?: ColorString | GradientColorObject;
}): Options {
  const axisLimit = Math.max(negative.value, positive.value, 0.1) * 1.18;
  const gain = gradient(alpha(colors.gain, "72"), colors.gain);
  const loss = gradient(colors.loss, alpha(colors.loss, "72"));
  const forceSeries: SeriesBarOptions[] = [
    {
      type: "bar",
      name: negative.name,
      color: loss,
      data: [
        {
          y: -negative.value,
          custom: { detail: negative.detail },
        },
      ],
    },
    {
      type: "bar",
      name: positive.name,
      color: positiveColor ?? gain,
      data: [
        {
          y: positive.value,
          custom: { detail: positive.detail },
        },
      ],
    },
  ];

  return {
    chart: {
      type: "bar",
      height: 70,
      spacing: [2, 14, 2, 14],
    },
    title: { text: undefined },
    legend: { enabled: false },
    xAxis: {
      categories: [""],
      tickWidth: 0,
      lineWidth: 0,
      gridLineWidth: 0,
      labels: { enabled: false },
    },
    yAxis: {
      min: -axisLimit,
      max: axisLimit,
      title: { text: undefined },
      gridLineColor: alpha(colors.grid, "95"),
      gridLineDashStyle: "ShortDot",
      lineColor: colors.grid,
      lineWidth: 0,
      tickColor: colors.grid,
      tickLength: 0,
      tickPosition: "outside",
      tickWidth: 0,
      plotBands: [
        { from: -axisLimit, to: 0, color: alpha(colors.loss, "08") },
        { from: 0, to: axisLimit, color: alpha(colors.gain, "08") },
      ],
      plotLines: [{ value: 0, color: colors.textMuted, width: 1, zIndex: 4 }],
      labels: {
        enabled: false,
        style: { color: colors.textMuted, fontSize: "10px" },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const point = this as Point & { options?: { custom?: { detail?: string } } };
        return `<b>${this.series.name}</b><br/><span>${point.options?.custom?.detail ?? ""}</span><br/><b>${formatPercent(Math.abs(this.y as number), 0)}</b>`;
      },
    },
    plotOptions: {
      bar: {
        animation: { duration: 850 },
        borderColor: colors.surface,
        borderRadius: 2,
        borderWidth: 1,
        groupPadding: 0.34,
        pointPadding: 0,
        stacking: "normal",
        dataLabels: {
          enabled: true,
          inside: true,
          formatter() {
            const y = this.y as number | null;
            return y && Math.abs(y) >= 0.08 ? formatPercent(Math.abs(y), 0) : "";
          },
          style: {
            color: colors.textOnAccent,
            fontSize: "10px",
            fontWeight: "bold",
            textOutline: "none",
          },
        },
        states: {
          hover: {
            brightness: 0.16,
          },
        },
      },
    },
    series: forceSeries,
  };
}
