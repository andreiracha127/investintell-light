/**
 * Pure option builders for the P5 fund dossier panels.
 *
 * Data arrives render-ready from the backend. These builders only map typed
 * payloads into Highcharts options and apply Graphite colors.
 */
import type { Options, Point, XAxisPlotBandsOptions } from "highcharts";

import type {
  FundEntityAnalytics,
  FundFactors,
  FundInstitutionalReveal,
  FundPeers,
  FundRiskTimeseries,
  FundStyleDrift,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  DAY_MS,
  compactDatetimeXAxis,
  dateToUtcMs,
  formatTimestampDate,
  toDatetimeData,
} from "@/lib/charts/hc/dateAxis";
import { formatNumber, formatPercent } from "@/lib/format";

function categoryColor(colors: ChartColors, index: number): string {
  return colors.categories[index % colors.categories.length];
}

function pointDates(points: [string, number][]): string[] {
  return points.map(([date]) => date);
}

function percentPoint(value: number, dp = 1): string {
  return `${formatNumber(value, dp)}%`;
}

function paddedPercentBounds(
  values: [string, number][],
  mode: "positive" | "drawdown",
): { min?: number; max?: number } {
  const ys = values.map(([, value]) => value).filter(Number.isFinite);
  if (ys.length === 0) return {};
  if (mode === "positive") {
    const max = Math.max(...ys, 0);
    return { min: 0, max: Math.max(5, Math.ceil((max * 1.18) / 5) * 5) };
  }
  const min = Math.min(...ys, 0);
  return { min: Math.min(-1, Math.floor((min * 1.12) / 5) * 5), max: 0 };
}

export function buildHcStyleDriftOption(
  drift: FundStyleDrift,
  colors: ChartColors,
): Options {
  const sectors = Array.from(
    new Set(
      drift.periods.flatMap((period) =>
        period.sectors.map((sector) => sector.sector),
      ),
    ),
  );

  return {
    chart: { type: "area" },
    legend: {
      layout: "vertical",
      align: "right",
      verticalAlign: "middle",
      itemMarginTop: 1,
      itemMarginBottom: 1,
      itemStyle: { fontSize: "11px" },
      symbolHeight: 8,
      symbolWidth: 8,
    },
    xAxis: { ...compactDatetimeXAxis(), crosshair: { width: 1, color: colors.grid } },
    yAxis: {
      title: { text: "% of holdings" },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      formatter(this: Point) {
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        return (
          `${formatTimestampDate(this.x as number)}<br/>` +
          points
            .map(
              (point) =>
                `<span style="color:${String(point.color)}">●</span> ${
                  point.series.name
                }: <b>${formatPercent(point.y as number, 1)}</b>`,
            )
            .join("<br/>")
        );
      },
    },
    plotOptions: {
      area: {
        stacking: "normal",
        marker: { enabled: false },
        fillOpacity: 0.42,
      },
    },
    series: sectors.map((sector, index) => ({
      type: "area" as const,
      name: sector,
      data: drift.periods.map(
        (period) =>
          [
            dateToUtcMs(period.report_date),
            period.sectors.find((item) => item.sector === sector)?.weight ?? 0,
          ] as [number, number],
      ),
      color: categoryColor(colors, index),
      lineWidth: 1,
    })),
  };
}

export function buildHcFactorSensitivityOption(
  factors: FundFactors,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "bar", spacing: [10, 16, 14, 8] },
    xAxis: {
      categories: factors.market_sensitivities.map((item) => item.factor),
      tickWidth: 0,
      lineWidth: 0,
      labels: { style: { color: colors.textSecondary, fontSize: "11px" } },
    },
    yAxis: {
      title: { text: "Beta vs. factor" },
      gridLineColor: colors.grid,
      plotLines: [{ value: 0, color: colors.textMuted, width: 1 }],
      labels: {
        formatter() {
          return formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const row = factors.market_sensitivities[this.index];
        const t = row?.t_stat != null ? ` · t ${formatNumber(row.t_stat)}` : "";
        return `${this.category}<br/><b>${formatNumber(
          this.y as number,
        )}</b>${t}${row?.significance ?? ""}`;
      },
    },
    plotOptions: {
      bar: {
        borderRadius: 2,
        groupPadding: 0.16,
        pointPadding: 0.24,
        pointWidth: 14,
        dataLabels: {
          enabled: true,
          formatter() {
            return formatNumber(this.y as number, 2);
          },
          style: {
            color: colors.textSecondary,
            fontSize: "10px",
            fontWeight: "700",
            textOutline: "none",
          },
        },
      },
    },
    series: [
      {
        type: "bar",
        name: "Beta",
        data: factors.market_sensitivities.map((item) => ({
          y: item.beta ?? 0,
          color: (item.beta ?? 0) >= 0 ? colors.accent : colors.barMute,
        })),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcStyleBiasOption(
  factors: FundFactors,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "bar", spacing: [10, 16, 14, 8] },
    xAxis: {
      categories: factors.style_bias.map((item) =>
        item.factor.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
      ),
      tickWidth: 0,
      lineWidth: 0,
      labels: { style: { color: colors.textSecondary, fontSize: "11px" } },
    },
    yAxis: {
      title: { text: "Z-score (σ)" },
      gridLineColor: colors.grid,
      plotLines: [{ value: 0, color: colors.textMuted, width: 1 }],
      labels: {
        formatter() {
          return formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const row = factors.style_bias[this.index];
        const raw = row?.value != null ? ` · raw ${formatNumber(row.value)}` : "";
        return `${this.category}<br/><b>z ${formatNumber(
          this.y as number,
        )}</b>${raw}`;
      },
    },
    plotOptions: {
      bar: {
        borderRadius: 2,
        groupPadding: 0.16,
        pointPadding: 0.24,
        pointWidth: 14,
        dataLabels: {
          enabled: true,
          formatter() {
            return formatNumber(this.y as number, 2);
          },
          style: {
            color: colors.textSecondary,
            fontSize: "10px",
            fontWeight: "700",
            textOutline: "none",
          },
        },
      },
    },
    series: [
      {
        type: "bar",
        name: "Z-score",
        data: factors.style_bias.map((item) => ({
          y: item.z_score ?? 0,
          color:
            (item.z_score ?? 0) >= 0
              ? colors.gain
              : colors.loss,
        })),
        borderWidth: 0,
      },
    ],
  };
}

function regimeBands(
  risk: FundRiskTimeseries,
  colors: ChartColors,
): XAxisPlotBandsOptions[] {
  const byDate = new Map(
    risk.regime_bands.map((band) => [band.time, band.regime] as const),
  );
  const dates = pointDates(risk.drawdown);
  const bands: XAxisPlotBandsOptions[] = [];
  dates.forEach((date) => {
    const regime = byDate.get(date);
    if (!regime) return;
    const color =
      regime === "Stress"
        ? colors.loss
        : regime === "Cautious"
          ? colors.accentMuted
          : colors.gain;
    bands.push({
      from: dateToUtcMs(date) - DAY_MS / 2,
      to: dateToUtcMs(date) + DAY_MS / 2,
      color: `${color}1f`,
    });
  });
  return bands;
}

export function buildHcRiskTimeseriesOption(
  risk: FundRiskTimeseries,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "line" },
    xAxis: {
      ...compactDatetimeXAxis({ plotBands: regimeBands(risk, colors) }),
      crosshair: { width: 1, color: colors.grid },
    },
    yAxis: [
      {
        title: { text: "Percent" },
        labels: {
          formatter() {
            return `${formatNumber(this.value as number, 0)}%`;
          },
        },
      },
    ],
    tooltip: {
      shared: true,
      valueSuffix: "%",
    },
    series: [
      {
        type: "area",
        name: "Drawdown",
        data: toDatetimeData(risk.drawdown),
        color: colors.loss,
        fillOpacity: 0.18,
        marker: { enabled: false },
      },
      {
        type: "line",
        name: "Conditional volatility",
        data: toDatetimeData(risk.conditional_volatility),
        color: colors.accent,
        marker: { enabled: false },
      },
    ],
  };
}

export interface HcRiskSynchronizedPane {
  id: "conditional-volatility" | "fund-drawdown" | "benchmark-drawdown";
  title: string;
  subtitle?: string;
  option: Options;
  isEmpty: boolean;
  emptyMessage: string;
}

function riskSyncPaneOption({
  name,
  data,
  colors,
  color,
  yTitle,
  mode,
  plotBands,
  showXAxisLabels,
  area,
}: {
  name: string;
  data: [string, number][];
  colors: ChartColors;
  color: string;
  yTitle: string;
  mode: "positive" | "drawdown";
  plotBands?: XAxisPlotBandsOptions[];
  showXAxisLabels: boolean;
  area?: boolean;
}): Options {
  const bounds = paddedPercentBounds(data, mode);
  return {
    chart: { type: area ? "area" : "line", spacing: [6, 12, 6, 6] },
    legend: { enabled: false },
    title: { text: undefined },
    xAxis: {
      ...compactDatetimeXAxis({
        ...(plotBands ? { plotBands } : {}),
        crosshair: { width: 1, color: colors.textMuted, dashStyle: "ShortDot" },
        labels: { enabled: showXAxisLabels },
      }),
    },
    yAxis: {
      title: { text: yTitle },
      ...(bounds.min !== undefined ? { min: bounds.min } : {}),
      ...(bounds.max !== undefined ? { max: bounds.max } : {}),
      labels: {
        formatter() {
          return percentPoint(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: false,
      useHTML: true,
      formatter() {
        return `${formatTimestampDate(this.x)}<br/><span style="color:${color}">●</span> ${name}: <b>${percentPoint(
          this.y as number,
          2,
        )}</b>`;
      },
    },
    plotOptions: {
      series: {
        animation: { duration: 450 },
        states: { inactive: { opacity: 1 } },
      },
      area: {
        threshold: 0,
      },
    },
    series: [
      {
        type: area ? "area" : "line",
        name,
        data: toDatetimeData(data),
        color,
        lineWidth: area ? 1.5 : 1.8,
        fillOpacity: area ? 0.18 : undefined,
        marker: { enabled: false },
      },
    ],
  };
}

export function buildHcRiskSynchronizedOptions(
  risk: FundRiskTimeseries,
  colors: ChartColors,
): HcRiskSynchronizedPane[] {
  const model = risk.volatility_model.toUpperCase();
  const benchmarkDrawdown = risk.benchmark_drawdown ?? [];
  const benchmarkLabel = risk.benchmark_label ?? "Benchmark";
  return [
    {
      id: "conditional-volatility",
      title: "Conditional volatility",
      subtitle: model,
      option: riskSyncPaneOption({
        name: "Conditional volatility",
        data: risk.conditional_volatility,
        colors,
        color: colors.accent,
        yTitle: "Ann. vol",
        mode: "positive",
        plotBands: regimeBands(risk, colors),
        showXAxisLabels: false,
      }),
      isEmpty: risk.conditional_volatility.length === 0,
      emptyMessage: "No conditional volatility series for this window.",
    },
    {
      id: "fund-drawdown",
      title: "Fund drawdown",
      option: riskSyncPaneOption({
        name: "Fund drawdown",
        data: risk.drawdown,
        colors,
        color: colors.loss,
        yTitle: "Drawdown",
        mode: "drawdown",
        showXAxisLabels: false,
        area: true,
      }),
      isEmpty: risk.drawdown.length === 0,
      emptyMessage: "No fund drawdown series for this window.",
    },
    {
      id: "benchmark-drawdown",
      title: "Benchmark drawdown",
      subtitle: benchmarkLabel,
      option: riskSyncPaneOption({
        name: benchmarkLabel,
        data: benchmarkDrawdown,
        colors,
        color: colors.textMuted,
        yTitle: "Drawdown",
        mode: "drawdown",
        showXAxisLabels: true,
        area: true,
      }),
      isEmpty: benchmarkDrawdown.length === 0,
      emptyMessage:
        risk.benchmark_empty_state?.reason ??
        "No benchmark drawdown series for this window.",
    },
  ];
}

export function buildHcTailRiskOption(
  analytics: FundEntityAnalytics,
  colors: ChartColors,
): Options {
  const tail = analytics.tail_risk;
  const rows = [
    ["Param VaR 90", tail.var_parametric_90],
    ["Param VaR 95", tail.var_parametric_95],
    ["Param VaR 99", tail.var_parametric_99],
    ["Modified VaR 95", tail.var_modified_95],
    ["Modified VaR 99", tail.var_modified_99],
    ["ETL 95", tail.etl_95],
  ] as const;

  return {
    chart: { type: "bar", spacing: [8, 12, 8, 8] },
    xAxis: {
      categories: rows.map(([label]) => label),
      tickWidth: 0,
      lineWidth: 0,
      labels: { style: { color: colors.textMuted, fontSize: "11px" } },
    },
    yAxis: {
      title: { text: "Daily loss" },
      min: 0,
      gridLineColor: colors.grid,
      labels: {
        formatter() {
          return formatPercent((this.value as number) / 100, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        return `${this.category}<br/><b>${formatPercent(
          (this.y as number) / 100,
          2,
        )}</b>`;
      },
    },
    plotOptions: {
      bar: {
        borderWidth: 0,
        borderRadius: 2,
        pointWidth: 10,
        groupPadding: 0.16,
        dataLabels: {
          enabled: true,
          formatter() {
            return formatPercent((this.y as number) / 100, 2);
          },
          style: {
            color: colors.text,
            fontSize: "10px",
            fontWeight: "700",
            textOutline: "none",
          },
        },
      },
    },
    series: [
      {
        type: "bar",
        name: "Tail risk",
        data: rows.map(([, value]) => (value ?? 0) * 100),
        color: colors.accent,
        showInLegend: false,
      },
    ],
  };
}

export function buildHcInsiderSentimentOption(
  analytics: FundEntityAnalytics,
  colors: ChartColors,
): Options {
  const rows = analytics.insider_data?.quarters ?? [];
  const chronological = [...rows].reverse();
  return {
    chart: { type: "column" },
    xAxis: {
      categories: chronological.map((row) => row.quarter),
      tickWidth: 0,
      crosshair: true,
    },
    yAxis: {
      title: { text: "Insider value ($)" },
      labels: {
        formatter() {
          return formatNumber(this.value as number, 0);
        },
      },
    },
    tooltip: {
      shared: true,
      valuePrefix: "$",
      valueDecimals: 0,
    },
    plotOptions: { column: { borderWidth: 0 } },
    series: [
      {
        type: "column",
        name: "Buy value",
        data: chronological.map((row) => row.buy_value),
        color: colors.gain,
      },
      {
        type: "column",
        name: "Sell value",
        data: chronological.map((row) => row.sell_value),
        color: colors.loss,
      },
      {
        type: "line",
        name: "Net",
        data: chronological.map((row) => row.net_value),
        color: colors.accent,
        marker: { enabled: true, radius: 3 },
      },
    ],
  };
}

export function buildHcInstitutionalHolderOption(
  reveal: FundInstitutionalReveal,
  colors: ChartColors,
): Options {
  const holders = reveal.top_holders.slice(0, 12);
  return {
    chart: { type: "bar" },
    xAxis: {
      categories: holders.map((holder) => holder.manager_name),
      tickWidth: 0,
    },
    yAxis: {
      title: { text: "Reported value" },
      labels: {
        formatter() {
          return `$${formatNumber(this.value as number, 0)}`;
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const holder = holders[this.index];
        return (
          `${holder?.manager_name ?? "Institution"}<br/>` +
          `<b>$${formatNumber(this.y as number, 0)}</b><br/>` +
          `${holder?.holding_count ?? 0} matched holdings`
        );
      },
    },
    series: [
      {
        type: "bar",
        name: "13F value",
        data: holders.map((holder) => ({
          y: holder.value_usd ?? 0,
          color: colors.bar,
        })),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcInstitutionalOverlapOption(
  reveal: FundInstitutionalReveal,
  colors: ChartColors,
): Options {
  const rows = reveal.overlap.slice(0, 12);
  return {
    chart: { type: "column" },
    xAxis: {
      categories: rows.map((row) => row.name ?? row.cusip),
      tickWidth: 0,
      crosshair: true,
    },
    yAxis: [
      {
        title: { text: "Institutional value" },
        labels: {
          formatter() {
            return `$${formatNumber(this.value as number, 0)}`;
          },
        },
      },
    ],
    tooltip: {
      formatter(this: Point) {
        const row = rows[this.index];
        return (
          `${row?.name ?? row?.cusip ?? "Holding"}<br/>` +
          `<b>$${formatNumber(this.y as number, 0)}</b><br/>` +
          `${row?.institution_count ?? 0} institutions`
        );
      },
    },
    series: [
      {
        type: "column",
        name: "Institutional value",
        data: rows.map((row) => ({
          y: row.institutional_value_usd ?? 0,
          color: colors.bar,
        })),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcPeerBubbleOption(
  peers: FundPeers,
  colors: ChartColors,
): Options {
  const rows = peers.items
    .slice(0, 20)
    .filter(
      (peer) =>
        peer.return_1y != null &&
        peer.volatility_1y != null &&
        peer.sharpe_1y != null,
    );

  return {
    chart: { type: "bubble", spacing: [12, 18, 12, 10] },
    legend: { enabled: false },
    xAxis: {
      title: { text: "Volatility 1Y" },
      min: 0,
      gridLineColor: colors.grid,
      labels: {
        formatter() {
          return formatPercent(this.value as number, 1);
        },
      },
    },
    yAxis: {
      title: { text: "Sharpe 1Y" },
      gridLineColor: colors.grid,
      plotLines: [{ value: 0, color: colors.barMute, width: 1 }],
      labels: {
        formatter() {
          return formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const peer = rows[this.index];
        return (
          `${peer?.name ?? "Peer"}<br/>` +
          `Return 1Y: <b>${formatPercent(peer?.return_1y ?? 0, 2, { signed: true })}</b><br/>` +
          `Vol 1Y: <b>${formatPercent(peer?.volatility_1y ?? 0, 2)}</b><br/>` +
          `Sharpe: <b>${formatNumber(peer?.sharpe_1y ?? 0, 2)}</b>`
        );
      },
    },
    plotOptions: {
      bubble: {
        minSize: 24,
        maxSize: 92,
        marker: {
          lineColor: colors.surface,
          lineWidth: 1.5,
          fillOpacity: 0.82,
        },
        dataLabels: {
          enabled: true,
          formatter() {
            return this.name ?? "";
          },
          allowOverlap: false,
          style: {
            color: colors.text,
            fontSize: "9px",
            fontWeight: "700",
            textOutline: "none",
          },
        },
      },
    },
    series: [
      {
        type: "bubble",
        name: "Peers",
        data: rows.map((peer) => ({
          id: peer.instrument_id,
          name: peer.ticker ?? peer.name,
          x: peer.volatility_1y ?? 0,
          y: peer.sharpe_1y ?? 0,
          z: Math.max(Math.abs(peer.return_1y ?? 0), 0.002) * 100,
          color: peer.is_target
            ? colors.accent
            : (peer.return_1y ?? 0) < 0
              ? colors.loss
              : colors.gain,
        })),
      },
    ],
  };
}
