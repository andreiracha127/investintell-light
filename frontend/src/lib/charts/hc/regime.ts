/**
 * Pure option builder: credit regime timeline strip (Highcharts Core).
 *
 * Highcharts port of the legacy ECharts `buildRegimeStripOption`. Where the
 * ECharts version faked a proportional timeline with one stacked-bar series per
 * period, Highcharts has a native time range type: `xrange`. Each period is a
 * single point with `x`/`x2` = start/end epoch-ms, so its bar width is the
 * period's real wall-clock duration. All points sit on the single y=0 row.
 *
 * The global Graphite theme owns axis/grid/tooltip/legend chrome; this builder
 * sets only the series, per-point token colors (gain wash for risk_on, full
 * loss for risk_off), the hidden value x-axis, and the per-point tooltip.
 *
 * **Binary-state assumption (preserved from the source):** only `"risk_on"`
 * and `"risk_off"` are recognised. Any other state renders with the risk_off
 * styling/label (the source treated "not risk_on" as risk_off).
 *
 * The `highcharts/modules/xrange` module is registered globally by the chart
 * controller (HighchartsChart) — it is NOT registered here.
 *
 * Empty/null flips -> returns `null` (caller should hide the panel entirely).
 */
import type Highcharts from "highcharts";
import type { Options } from "highcharts";

import type { MacroRegime, RegimeFlip } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { compactDatetimeXAxis, dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import { formatDate, formatNumber } from "@/lib/format";

// ── Color math ─────────────────────────────────────────────────────────────

/**
 * Encode an alpha into a `#RRGGBB` token as an `rgba(r, g, b, a)` string.
 *
 * Highcharts `xrange` points have no per-point `opacity` option (it is silently
 * ignored), so the gain-wash for risk_on periods must be baked into the point
 * `color`. Pass-through any input that is not a 6-digit hex (e.g. already-rgba
 * or named colors) so the helper never corrupts an unexpected token.
 */
function withAlpha(hex: string, a: number): string {
  const m = /^#([0-9a-fA-F]{6})$/.exec(hex);
  if (!m) return hex;
  const int = parseInt(m[1], 16);
  const r = (int >> 16) & 0xff;
  const g = (int >> 8) & 0xff;
  const b = int & 0xff;
  return `rgba(${r}, ${g}, ${b}, ${a})`;
}

// ── Date math ──────────────────────────────────────────────────────────────

/**
 * Parse "YYYY-MM-DD" to a UTC epoch millisecond count.
 * Uses Date.UTC to avoid timezone-shift hazards (mirrors lib/perf.ts convention).
 */
function isoToUtcMs(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

/** Duration in whole days between two ISO date strings (end − start). */
function daysBetween(startIso: string, endIso: string): number {
  return Math.round((isoToUtcMs(endIso) - isoToUtcMs(startIso)) / 86_400_000);
}

// ── Period derivation ──────────────────────────────────────────────────────

interface RegimePeriod {
  /** ISO date of period start (= flip date). */
  start: string;
  /** ISO date of period end (= next flip date, or asOf for the last period). */
  end: string;
  state: string;
  durationDays: number;
}

/**
 * Derive contiguous periods from the flip list.
 *
 * Each flip record carries the date the state *changed to* `state`. Periods
 * run from one flip date to the next. The last period is closed by `asOf`.
 *
 * Returns [] for an empty/null flip list.
 */
function derivePeriods(flips: RegimeFlip[], asOf: string): RegimePeriod[] {
  if (!flips || flips.length === 0) return [];

  const sorted = [...flips].sort((a, b) => a.date.localeCompare(b.date));

  return sorted.map((flip, i) => {
    const start = flip.date;
    const end = sorted[i + 1]?.date ?? asOf;
    const durationDays = daysBetween(start, end);
    return { start, end, state: flip.state, durationDays };
  });
}

// ── Option builder ─────────────────────────────────────────────────────────

/** Faint wash applied to risk_on bars (mirrors the ECharts itemStyle.opacity). */
const RISK_ON_ALPHA = 0.18;

/**
 * Build a Highcharts option for the regime timeline strip.
 *
 * @param flips   Recent regime flip records from the API response.
 * @param colors  Design-token color bag.
 * @param asOf    ISO date string ("YYYY-MM-DD") used to close the final
 *                open-ended period (e.g. the API's `as_of` field). Falls back
 *                to today's date when not supplied.
 *
 * @returns A Highcharts `Options` ready to pass to `<HighchartsChart>`, or
 *          `null` when `flips` is empty (caller should hide the panel).
 */
export function buildHcRegimeStripOption(
  flips: RegimeFlip[],
  colors: ChartColors,
  asOf?: string,
): Options | null {
  // Fall back to today's ISO date if asOf is not supplied.
  const anchor = asOf ?? new Date().toISOString().slice(0, 10);

  const periods = derivePeriods(flips, anchor);

  if (periods.length === 0) {
    return null;
  }

  // One xrange point per period, all on the single y=0 row. `custom` carries
  // the raw period context for the tooltip formatter.
  const data = periods.map((period) => {
    const isRiskOn = period.state === "risk_on";
    return {
      x: isoToUtcMs(period.start),
      x2: isoToUtcMs(period.end),
      y: 0,
      name: isRiskOn ? "Risk-on" : "Risk-off",
      // xrange has no per-point `opacity`; bake the gain-wash alpha into color.
      color: isRiskOn ? withAlpha(colors.gain, RISK_ON_ALPHA) : colors.loss,
      custom: { start: period.start, end: period.end, days: period.durationDays },
    };
  });

  return {
    chart: { type: "xrange" },
    xAxis: {
      // Cumulative wall-clock time, but the raw axis ticks carry no
      // user-meaningful unit here; dates surface in the tooltip only.
      type: "datetime",
      visible: false,
    },
    yAxis: {
      // Single unlabeled row.
      title: { text: undefined },
      categories: ["regime"],
      min: 0,
      max: 0,
      visible: false,
    },
    legend: { enabled: true },
    tooltip: {
      // In Highcharts the tooltip formatter's `this` is the hovered Point
      // itself (TooltipFormatterCallbackFunction => `this: Point`). Read the
      // label and the custom period context directly off the point; cast
      // narrowly for the `custom` bag which is not on the base Point type.
      formatter(this: Highcharts.Point) {
        const { custom } = this as unknown as {
          custom?: { start?: string; end?: string; days?: number };
        };
        const label = this.name ?? "";
        const start = custom?.start ?? "";
        const end = custom?.end ?? "";
        const days = custom?.days ?? 0;
        return `<b>${label}</b><br/>${start} – ${end}<br/>${days} days`;
      },
    },
    series: [
      {
        type: "xrange",
        name: "Regime",
        // Per-point colors carry the risk_on/risk_off styling; do not let the
        // single series emit one legend item per point.
        showInLegend: false,
        // xrange bar height on the single category row.
        pointWidth: 28,
        borderWidth: 0,
        data,
        // Per-point data labels off; dates surface via tooltip only.
        dataLabels: { enabled: false },
      },
      // Deduplicated legend placeholders: exactly one Risk-on and one Risk-off
      // swatch, mirroring the source's two-entry legend.
      {
        type: "xrange",
        name: "Risk-on",
        // Match the alpha-encoded bar color so the swatch reads identically.
        color: withAlpha(colors.gain, RISK_ON_ALPHA),
        data: [],
      },
      {
        type: "xrange",
        name: "Risk-off",
        color: colors.loss,
        data: [],
      },
    ],
  };
}

type RegimeHistoryPoint = MacroRegime["history"][number];
type DatePoint = [string, number];

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function stateLabel(state: string): string {
  return state === "risk_on" ? "Risk-on" : "Risk-off";
}

function normalizeSeries(points: DatePoint[]): Array<[number, number]> {
  const first = points.find(([, value]) => Number.isFinite(value) && value > 0);
  if (!first) return [];
  const base = first[1];
  return points
    .filter(([, value]) => Number.isFinite(value))
    .map(([date, value]) => [dateToUtcMs(date), (value / base) * 100]);
}

function deriveRegimePlotBands(
  history: RegimeHistoryPoint[],
  minX: number,
  maxX: number,
  colors: ChartColors,
) {
  const sorted = [...history]
    .filter((point) => Number.isFinite(dateToUtcMs(point.date)))
    .sort((a, b) => a.date.localeCompare(b.date));
  const bands = [];
  for (let i = 0; i < sorted.length; i += 1) {
    const start = dateToUtcMs(sorted[i].date);
    if (start > maxX) break;
    if (start < minX) continue;
    const state = sorted[i].state;
    let j = i + 1;
    while (j < sorted.length && sorted[j].state === state) j += 1;
    const end = j < sorted.length ? dateToUtcMs(sorted[j].date) : maxX;
    bands.push({
      from: start,
      to: Math.min(end, maxX),
      color:
        state === "risk_off"
          ? withAlpha(colors.loss, 0.16)
          : withAlpha(colors.gain, 0.06),
      label:
        state === "risk_off"
          ? { text: "Risk-off", style: { color: colors.loss, fontSize: "10px" } }
          : undefined,
    });
    i = j - 1;
  }
  return bands;
}

export function buildHcMacroRotationOption(
  history: RegimeHistoryPoint[],
  colors: ChartColors,
): Options | null {
  const recent = history.slice(-126);
  if (recent.length === 0) return null;

  const data = recent.map((point, index) => {
    const pressure = clamp(point.vote_count, 0, 3);
    const prevPressure = index > 0 ? clamp(recent[index - 1].vote_count, 0, 3) : pressure;
    const appetite = 3 - pressure;
    const momentum = prevPressure - pressure;
    return {
      x: 96 + (appetite / 3) * 8,
      y: clamp(100 + momentum * 2.4, 96, 104),
      name: formatDate(point.date),
      custom: {
        date: point.date,
        state: point.state,
        voteCount: point.vote_count,
        votes: point.votes,
      },
    };
  });
  const latest = data[data.length - 1];

  return {
    chart: { type: "line", spacing: [10, 18, 12, 12] },
    legend: { enabled: false },
    title: { text: undefined },
    xAxis: {
      min: 96,
      max: 104,
      tickInterval: 2,
      gridLineWidth: 1,
      title: { text: "Risk appetite" },
      plotLines: [{ value: 100, width: 1, color: colors.textMuted, zIndex: 2 }],
      plotBands: [
        { from: 96, to: 100, color: withAlpha(colors.loss, 0.08) },
        { from: 100, to: 104, color: withAlpha(colors.gain, 0.08) },
      ],
    },
    yAxis: {
      min: 96,
      max: 104,
      tickInterval: 2,
      gridLineWidth: 1,
      title: { text: "Regime momentum" },
      plotLines: [{ value: 100, width: 1, color: colors.textMuted, zIndex: 2 }],
      plotBands: [
        { from: 96, to: 100, color: withAlpha(colors.accentMuted, 0.08) },
        { from: 100, to: 104, color: withAlpha(colors.accent, 0.05) },
      ],
    },
    tooltip: {
      formatter(this: Highcharts.Point) {
        const custom = (this as unknown as {
          custom?: {
            date?: string;
            state?: string;
            voteCount?: number;
            votes?: { credit?: boolean; trend?: boolean; nfci?: boolean };
          };
        }).custom;
        const votes = custom?.votes;
        return [
          `<b>${formatDate(custom?.date)}</b>`,
          `${stateLabel(custom?.state ?? "")} · ${custom?.voteCount ?? 0}/3 votes`,
          `Credit ${votes?.credit ? "on" : "off"} · Trend ${votes?.trend ? "on" : "off"} · NFCI ${votes?.nfci ? "on" : "off"}`,
        ].join("<br/>");
      },
    },
    annotations: [
      {
        draggable: "",
        labelOptions: {
          backgroundColor: "transparent",
          borderWidth: 0,
          style: { color: colors.textMuted, fontSize: "11px", fontWeight: "700" },
        },
        labels: [
          { text: "LAGGING", point: { x: 96.4, y: 96.5, xAxis: 0, yAxis: 0 } },
          { text: "IMPROVING", point: { x: 96.4, y: 103.5, xAxis: 0, yAxis: 0 } },
          { text: "LEADING", point: { x: 103.6, y: 103.5, xAxis: 0, yAxis: 0 } },
          { text: "WEAKENING", point: { x: 103.6, y: 96.5, xAxis: 0, yAxis: 0 } },
        ],
      },
    ],
    plotOptions: {
      series: {
        marker: { enabled: true, radius: 2.5 },
        states: { hover: { lineWidthPlus: 1 } },
      },
    },
    series: [
      {
        type: "line",
        name: "Regime path",
        data,
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: true, radius: 2.5 },
      },
      {
        type: "scatter",
        name: "Current",
        data: latest ? [{ ...latest, marker: { radius: 5, fillColor: colors.accent } }] : [],
        color: colors.accent,
      },
    ],
  };
}

export function buildHcMacroPerformanceOption({
  portfolio,
  asset,
  regimes,
  colors,
  portfolioLabel,
  assetLabel,
}: {
  portfolio: DatePoint[];
  asset: DatePoint[];
  regimes: RegimeHistoryPoint[];
  colors: ChartColors;
  portfolioLabel: string;
  assetLabel: string;
}): Options | null {
  const portfolioData = normalizeSeries(portfolio);
  const assetData = normalizeSeries(asset);
  const allTimes = [...portfolioData, ...assetData].map(([time]) => time);
  if (allTimes.length === 0) return null;
  const minX = Math.min(...allTimes);
  const maxX = Math.max(...allTimes);

  return {
    chart: { type: "line", zooming: { type: "x" } },
    legend: { enabled: true },
    xAxis: compactDatetimeXAxis({
      min: minX,
      max: maxX,
      plotBands: deriveRegimePlotBands(regimes, minX, maxX, colors),
    }),
    yAxis: {
      title: { text: "Indexed performance" },
      labels: {
        formatter() {
          return formatNumber(this.value as number, 0);
        },
      },
      plotLines: [{ value: 100, width: 1, color: colors.grid }],
    },
    tooltip: {
      shared: true,
      formatter() {
        const rows = (this.points ?? [])
          .map(
            (point) =>
              `<span style="color:${point.series.color}">●</span> ${point.series.name}: <b>${formatNumber(point.y as number, 2)}</b>`,
          )
          .join("<br/>");
        return `${formatDate(new Date(this.x as number).toISOString().slice(0, 10))}<br/>${rows}`;
      },
    },
    series: [
      {
        type: "line",
        name: portfolioLabel,
        data: portfolioData,
        color: colors.accent,
        lineWidth: 2.4,
        marker: { enabled: false },
        zIndex: 3,
      },
      {
        type: "line",
        name: assetLabel,
        data: assetData,
        color: colors.barMute,
        lineWidth: 1.8,
        marker: { enabled: false },
        zIndex: 2,
      },
    ],
  };
}
