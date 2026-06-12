/**
 * Pure option builder: credit regime timeline strip.
 *
 * `buildRegimeStripOption` renders a horizontal timeline from a list of
 * regime flips: each contiguous period between flips is rendered as a
 * stacked-bar segment on a time axis. Risk-on periods use a faint gain wash;
 * risk-off periods use the solid loss color.
 *
 * Implementation: a custom series of two stacked bars (risk_on / risk_off),
 * each taking value 1 for their respective period and 0 otherwise, on a
 * category axis of derived period labels. This is simpler and more robust
 * than a time-axis scatter because ECharts stacked bars on a category axis
 * are guaranteed to align and fill without gaps.
 *
 * **Binary-state assumption:** the builder only recognises `"risk_on"` and
 * `"risk_off"` states. Any period whose `state` is neither renders as a gap
 * (both series carry value 0 for that category), which is visible as an empty
 * bar slot. Unknown states are intentionally not collapsed or merged.
 *
 * Empty/null flips → returns `null` (caller should hide the panel entirely).
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { RegimeFlip } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatDate } from "@/lib/format";

// ── Period derivation ──────────────────────────────────────────────────────

interface RegimePeriod {
  /** ISO date of period start (= flip date). */
  start: string;
  /** ISO date of period end (= next flip date, or "present" label). */
  end: string | null;
  state: string;
}

/**
 * Derive contiguous periods from the flip list.
 *
 * Each flip record carries the date the state *changed to* `state`. Periods
 * run from one flip date to the next. The last period is open-ended (end=null).
 *
 * Returns [] for an empty/null flip list.
 */
function derivePeriods(flips: RegimeFlip[]): RegimePeriod[] {
  if (!flips || flips.length === 0) return [];

  // Sort ascending by date so periods are chronological.
  const sorted = [...flips].sort((a, b) => a.date.localeCompare(b.date));

  return sorted.map((flip, i) => ({
    start: flip.date,
    end: sorted[i + 1]?.date ?? null,
    state: flip.state,
  }));
}

/** Human-readable x-axis category label for a period. */
function periodLabel(period: RegimePeriod, asOf?: string): string {
  const start = formatDate(period.start);
  if (period.end === null) {
    // Close the open-ended final period with the as-of anchor when available.
    return asOf ? `${start} – ${formatDate(asOf)}` : `${start} →`;
  }
  return `${start} – ${formatDate(period.end)}`;
}

// ── Option builder ─────────────────────────────────────────────────────────

/**
 * Build an ECharts option for the regime timeline strip.
 *
 * @param flips   Recent regime flip records from the API response.
 * @param colors  Design-token color bag.
 * @param asOf    ISO date string used to close the final open-ended period
 *                (e.g. the API's `as_of` field). When provided, the last
 *                period label shows "YYYY-MM-DD – YYYY-MM-DD" instead of
 *                "YYYY-MM-DD →". Has no effect when `flips` is empty.
 *
 * @returns An EChartsOption ready to pass to `<EChart>`, or `null` when
 *          `flips` is empty (caller should hide the panel entirely).
 */
export function buildRegimeStripOption(
  flips: RegimeFlip[],
  colors: ChartColors,
  asOf?: string,
): EChartsOption | null {
  const periods = derivePeriods(flips);

  if (periods.length === 0) {
    return null;
  }

  const categories = periods.map((p) => periodLabel(p, asOf));

  // For each period: risk_on series value = 1 if state is risk_on, else 0.
  // risk_off series value = 1 if state is risk_off, else 0.
  // Stacked, they always sum to 1 and fill the full bar height.
  const riskOnValues = periods.map((p) =>
    p.state === "risk_on" ? 1 : 0,
  );
  const riskOffValues = periods.map((p) =>
    p.state === "risk_off" ? 1 : 0,
  );

  const riskOnSeries: SeriesOption = {
    name: "Risk-on",
    type: "bar",
    stack: "regime",
    data: riskOnValues,
    itemStyle: { color: colors.gain, opacity: 0.18 },
    emphasis: { disabled: true },
    label: { show: false },
  };

  const riskOffSeries: SeriesOption = {
    name: "Risk-off",
    type: "bar",
    stack: "regime",
    data: riskOffValues,
    itemStyle: { color: colors.loss },
    emphasis: { disabled: true },
    label: { show: false },
  };

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "shadow" },
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (paramsRaw) => {
        const params = paramsRaw as Array<{
          name: string;
          seriesName: string;
          value: number;
          dataIndex: number;
        }>;
        // Find which series is active for this period.
        const active = params.find((p) => p.value === 1);
        if (!active) return "";
        const stateLabel =
          active.seriesName === "Risk-on" ? "RISK-ON" : "RISK-OFF";
        return `<span style="font-size:12px">${params[0].name}<br/><b>${stateLabel}</b></span>`;
      },
    },
    legend: {
      top: 0,
      right: 0,
      textStyle: { color: colors.textSecondary },
      icon: "rect",
      itemWidth: 10,
      itemHeight: 10,
    },
    grid: { left: 16, right: 16, top: 28, bottom: 56 },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: {
        color: colors.textMuted,
        rotate: 35,
        interval: 0,
        fontSize: 10,
        overflow: "truncate",
        width: 90,
      },
    },
    yAxis: {
      type: "value",
      show: false,
      min: 0,
      max: 1,
    },
    series: [riskOnSeries, riskOffSeries],
  };
}
