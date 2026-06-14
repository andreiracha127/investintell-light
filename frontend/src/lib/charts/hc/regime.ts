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

import type { RegimeFlip } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";

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
