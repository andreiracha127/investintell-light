/**
 * Pure option builders: fund performance analytics charts (Highcharts Core).
 *
 * Ports lib/charts/performance.ts (ECharts) to Highcharts with behavioral
 * parity. Two builders — monthly returns heatmap (month × year grid) and
 * drawdown area chart. Neither performs any arithmetic; they consume the
 * output of lib/perf.ts and produce render-ready Highcharts `Options`.
 *
 * The global Graphite theme (hc/theme.ts) owns axis/grid/tooltip/legend
 * chrome. These builders set only chart-specific content: series, the
 * gain/loss/diverging colors taken from the `colors` param, value
 * formatting, the diverging colorAxis (ECharts visualMap), and the
 * worst-window plotBands (ECharts markArea).
 */
import type Highcharts from "highcharts";
import type { Options } from "highcharts";

import type { DrawdownResult, MonthlyReturn } from "@/lib/perf";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatDate, formatPercent } from "@/lib/format";

// ── Month × year heatmap ─────────────────────────────────────────────────

// At this relative-intensity threshold the cell is dark enough to warrant a light label.
const LIGHT_LABEL_THRESHOLD = 0.6;

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
] as const;

/**
 * Build a monthly returns heatmap (month on x-axis, year descending on y).
 *
 * Each cell is colored by a diverging colorAxis (loss → grid → gain), with
 * `min = -maxAbs` / `max = maxAbs` so 0 maps to the neutral grid midpoint and
 * the most extreme month reads as the full token color. The cell label is the
 * return formatted to one decimal place; its color flips to the on-accent
 * token once the cell's relative intensity passes a contrast threshold.
 * Returns null when `cells` is empty.
 *
 * @param cells   Monthly return records from monthlyReturns().
 * @param colors  Design-token color bag from chartColors().
 * @returns Highcharts Options, or null when `cells` is empty.
 */
export function buildHcMonthlyReturnsOption(
  cells: MonthlyReturn[],
  colors: ChartColors,
): Options | null {
  if (cells.length === 0) return null;

  // Derive the sorted list of years (descending on y-axis).
  const yearSet = new Set(cells.map((c) => c.year));
  const years = Array.from(yearSet).sort((a, b) => b - a); // descending
  const yearIndex = new Map(years.map((y, i) => [y, i]));

  // Maximum absolute return for opacity/intensity scaling.
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.value)));

  const data = cells.map((c) => {
    const xIdx = c.month - 1; // 0..11
    const yIdx = yearIndex.get(c.year) ?? 0;
    // Relative intensity [0, 1] used only for adaptive label contrast.
    const intensity = maxAbs > 0 ? Math.abs(c.value) / maxAbs : 0;
    // Label: light (on-accent) when cell is saturated; normal text for pale cells.
    const labelColor = intensity > LIGHT_LABEL_THRESHOLD ? colors.textOnAccent : colors.text;
    return {
      x: xIdx,
      y: yIdx,
      value: c.value,
      dataLabels: { color: labelColor },
    };
  });

  return {
    chart: { type: "heatmap" },
    legend: { enabled: false },
    // ECharts visualMap → Highcharts colorAxis. Symmetric diverging scale:
    // loss (red) at the low end → neutral grid at 0 → gain (green) at the high
    // end. Stops are normalized 0..1 over [min, max]; 0.5 maps to value 0.
    colorAxis: {
      min: -maxAbs,
      max: maxAbs,
      stops: [
        [0, colors.loss],
        [0.5, colors.grid],
        [1, colors.gain],
      ],
    },
    xAxis: {
      categories: [...MONTH_LABELS],
      tickWidth: 0,
    },
    yAxis: {
      categories: years.map(String),
      title: { text: undefined },
      // `years` is descending (newest first) and maps to category indexes 0..n.
      // A category y-axis renders index 0 at the bottom, so reverse it to put
      // the most-recent year row at the TOP (typical month×year heatmap layout).
      reversed: true,
    },
    tooltip: {
      // In this Highcharts version the tooltip formatter `this` is the hovered
      // Point. x/y are the (month, year) category indexes; the heatmap return
      // lives on the custom `value` field (not on the base Point type).
      formatter(this: Highcharts.Point) {
        const point = this as unknown as { x: number; y: number; value: number };
        const month = MONTH_LABELS[point.x] ?? "";
        const year = years[point.y] ?? "";
        return `${month} ${year}: <b>${formatPercent(point.value, 2, { signed: true })}</b>`;
      },
    },
    series: [
      {
        type: "heatmap",
        name: "Monthly return",
        data,
        borderColor: colors.grid,
        borderWidth: 1,
        dataLabels: {
          enabled: true,
          // In a dataLabels formatter `this` is the Point itself; the heatmap
          // return lives on the custom `value` field, not on the base type.
          formatter(this: Highcharts.Point) {
            const value = (this as unknown as { value: number }).value;
            return formatPercent(value, 1);
          },
        },
      },
    ],
  };
}

// ── Drawdown area chart ───────────────────────────────────────────────────

/**
 * Build a drawdown area chart from a DrawdownResult.
 *
 * The series is rendered as a filled area using `colors.loss`. The y-axis is
 * capped at 0 (drawdowns are ≤ 0) and labeled in percent (fractions → ×100 via
 * the label formatter; the data stays fractional so tooltips share one scale).
 * An xAxis plotBand (ECharts markArea) shades the worst drawdown window from
 * peak to trough, but only when there is an actual drawdown (depth < 0): a
 * monotonic NAV yields depth === 0 and must render no "Worst: 0.00%" band.
 * Returns null when `dd` is null or has no data.
 *
 * @param dd      Drawdown result from drawdownSeries().
 * @param colors  Design-token color bag from chartColors().
 * @returns Highcharts Options, or null when `dd` is null/empty.
 */
export function buildHcDrawdownOption(
  dd: DrawdownResult | null,
  colors: ChartColors,
): Options | null {
  if (!dd || dd.dates.length === 0) return null;

  // Worst-window plotBand: only when an actual drawdown exists (depth < 0).
  // Category axis → plotBand bounds are the date indexes within dd.dates.
  const hasDrawdown = dd.worst.depth < 0;
  const fromIdx = dd.dates.indexOf(dd.worst.from);
  const toIdx = dd.dates.indexOf(dd.worst.to);

  return {
    chart: { type: "area" },
    legend: { enabled: false },
    xAxis: {
      categories: [...dd.dates],
      tickWidth: 0,
      ...(hasDrawdown && {
        plotBands: [
          {
            from: fromIdx,
            to: toIdx,
            // Faint loss tint (≈0.1 opacity) — parity with the ECharts markArea fill.
            color: `${colors.loss}1a`,
            borderColor: colors.loss,
            borderWidth: 1,
            label: {
              text: `Worst: ${formatPercent(dd.worst.depth, 2)}`,
              style: { color: colors.loss },
            },
          },
        ],
      }),
    },
    yAxis: {
      max: 0,
      title: { text: undefined },
      labels: {
        formatter() {
          return formatPercent(this.value as number, 0);
        },
      },
    },
    tooltip: {
      // The tooltip formatter `this` is the hovered Point. On a category x-axis
      // `this.x` is the numeric index — NOT the date — so read the ISO date from
      // the point's `category` (string|number on a category axis).
      formatter(this: Highcharts.Point) {
        const date = String(this.category ?? "");
        return `${formatDate(date)}<br/><b>${formatPercent(this.y as number, 2)}</b>`;
      },
    },
    series: [
      {
        type: "area",
        name: "Drawdown",
        data: [...dd.values],
        color: colors.loss,
        lineWidth: 1.5,
        fillOpacity: 0.2,
        marker: { enabled: false },
      },
    ],
  };
}
