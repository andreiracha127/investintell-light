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
  FundRiskTimeseries,
  FundStyleDrift,
  FundsScatter,
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
    chart: { type: "bar" },
    xAxis: {
      categories: factors.market_sensitivities.map((item) => item.factor),
      tickWidth: 0,
    },
    yAxis: {
      title: { text: "Beta vs. factor" },
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
    chart: { type: "bar" },
    xAxis: {
      categories: factors.style_bias.map((item) => item.factor),
      tickWidth: 0,
    },
    yAxis: {
      title: { text: "Z-score (σ)" },
      plotLines: [{ value: 0, color: colors.grid, width: 1 }],
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
    chart: { type: "column" },
    xAxis: { categories: rows.map(([label]) => label), tickWidth: 0 },
    yAxis: {
      title: { text: "Daily loss" },
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
    series: [
      {
        type: "column",
        name: "Tail risk",
        data: rows.map(([, value]) => (value ?? 0) * 100),
        color: colors.accent,
        borderWidth: 0,
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
        data: holders.map((holder, index) => ({
          y: holder.value_usd ?? 0,
          color: categoryColor(colors, index),
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
        data: rows.map((row, index) => ({
          y: row.institutional_value_usd ?? 0,
          color: categoryColor(colors, index),
        })),
        borderWidth: 0,
      },
    ],
  };
}

export function buildHcFundsScatterOption(
  scatter: FundsScatter,
  colors: ChartColors,
): Options {
  return {
    chart: { type: "scatter" },
    xAxis: {
      title: { text: "Volatility 1Y" },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 1);
        },
      },
    },
    yAxis: {
      title: { text: "Return 1Y" },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 1);
        },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const index = this.index;
        const name = scatter.names[index] ?? "Fund";
        const tail = scatter.tail_risks[index];
        return (
          `${name}<br/>` +
          `Return: <b>${formatPercent(this.y as number, 2, { signed: true })}</b><br/>` +
          `Vol: <b>${formatPercent(this.x as number, 2)}</b><br/>` +
          `CVaR: <b>${tail != null ? formatPercent(tail, 2) : "—"}</b>`
        );
      },
    },
    series: [
      {
        type: "scatter",
        name: "Funds",
        data: scatter.instrument_ids.map((id, index) => ({
          id,
          x: scatter.volatilities[index],
          y: scatter.expected_returns[index],
          color: categoryColor(colors, index),
        })),
        marker: { radius: 4 },
      },
    ],
  };
}
