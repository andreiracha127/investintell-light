/**
 * Pure option builder: credit regime timeline strip.
 *
 * `buildRegimeStripOption` renders a horizontal timeline from a list of
 * regime flips where each period's bar width is PROPORTIONAL to its duration
 * in days. This is achieved with a single-row stacked horizontal bar chart:
 * one series per period, each with value = duration in days (so the visual
 * width is proportional to time). Periods are colored gain-wash for risk_on
 * and loss for risk_off.
 *
 * Implementation: y-axis has a single category ("regime"). Each period
 * becomes its own named series with `stack: "timeline"` so all periods
 * accumulate left-to-right. The x-axis is a value axis of cumulative days
 * whose labels are hidden (the raw day-count has no user-meaningful unit);
 * date context is surfaced per-segment in the tooltip.
 *
 * Empty/null flips → option with empty series (panel should hide).
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { RegimeFlip } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";

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
 * Returns [] for an empty/null flip list or when asOf is missing.
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

/**
 * Build an ECharts option for the regime timeline strip.
 *
 * Each period is rendered as a separate stacked-bar series so its bar width
 * is proportional to its duration in days. Risk-on periods are colored with a
 * faint gain wash; risk-off periods use the full loss color.
 *
 * @param flips   Recent regime flip records from the API response.
 * @param colors  Design-token color bag.
 * @param asOf    The "as of" date used to close the last open period (ISO "YYYY-MM-DD").
 *
 * @returns An EChartsOption ready to pass to `<EChart>`. When `flips` is
 *          empty the option carries empty series so the chart renders blank.
 */
export function buildRegimeStripOption(
  flips: RegimeFlip[],
  colors: ChartColors,
  asOf?: string,
): EChartsOption {
  // Fall back to today's ISO date if asOf is not supplied.
  const anchor =
    asOf ?? new Date().toISOString().slice(0, 10);

  const periods = derivePeriods(flips, anchor);

  if (periods.length === 0) {
    return {
      animation: false,
      backgroundColor: "transparent",
      series: [],
    };
  }

  // One series per period; all stacked on the single "regime" row.
  const series: SeriesOption[] = periods.map((period, i) => {
    const isRiskOn = period.state === "risk_on";
    return {
      // Unique name — used internally; legend entries are deduplicated below.
      name: isRiskOn ? "Risk-on" : "Risk-off",
      id: `period-${i}`,
      type: "bar",
      stack: "timeline",
      barWidth: 28,
      data: [period.durationDays],
      itemStyle: {
        color: isRiskOn ? colors.gain : colors.loss,
        opacity: isRiskOn ? 0.18 : 1,
      },
      emphasis: { disabled: true },
      label: { show: false },
      // Tooltip formatter receives this series' data.
      tooltip: {
        trigger: "item",
        backgroundColor: colors.surface,
        borderColor: colors.grid,
        textStyle: { color: colors.text },
        formatter: () => {
          const stateLabel = isRiskOn ? "Risk-on" : "Risk-off";
          return (
            `<span style="font-size:12px">` +
            `<b>${stateLabel}</b><br/>` +
            `${period.start} – ${period.end}<br/>` +
            `${period.durationDays} days` +
            `</span>`
          );
        },
      },
    };
  });

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      // Each series declares its own formatter above; this global trigger
      // activates the nearest-item tooltip on hover.
      trigger: "item",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
    },
    legend: {
      // Deduplicate: show only one entry per label (Risk-on / Risk-off).
      data: ["Risk-on", "Risk-off"],
      top: 0,
      right: 0,
      textStyle: { color: colors.textSecondary },
      icon: "rect",
      itemWidth: 10,
      itemHeight: 10,
    },
    grid: { left: 16, right: 16, top: 28, bottom: 16 },
    xAxis: {
      type: "value",
      // The x-axis accumulates raw day-counts — not meaningful as displayed
      // numbers. Hide all axis decorations; dates surface in the tooltip only.
      show: false,
    },
    yAxis: {
      type: "category",
      data: ["regime"],
      show: false,
    },
    series,
  };
}
