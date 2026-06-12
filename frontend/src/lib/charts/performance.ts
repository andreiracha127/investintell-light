/**
 * Pure option builders: fund performance analytics charts.
 *
 * Two builders — monthly returns heatmap (month × year grid) and drawdown
 * area chart. Neither performs any arithmetic; they consume the output of
 * lib/perf.ts and produce render-ready EChartsOption objects.
 *
 * Why a new file rather than reusing lib/charts/heatmap.ts:
 *   The existing buildHeatmapOption is tailored for pairwise correlation
 *   (accent→accentWash gradient, continuous visualMap over [0,1], square
 *   symmetric layout). The monthly returns heatmap needs gain/loss semantics
 *   with opacity scaled by absolute value, a month×year categorical layout,
 *   sparse data (missing months emit no cell), and percent labels. The two
 *   builders share no implementation surface — a fresh builder is cleaner
 *   than a generalization that would add many conditionals to heatmap.ts.
 */
import type { EChartsOption } from "echarts";

import type { DrawdownResult, MonthlyReturn } from "@/lib/perf";
import type { ChartColors } from "@/lib/charts/theme";
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
 * Each cell is colored gain (positive return) or loss (negative return) at
 * an opacity proportional to `|value| / max(|values|)` so the most extreme
 * month reads as the full token color. The cell label is the return formatted
 * to one decimal place. Months absent from `cells` produce no cell (ECharts
 * heatmap sparse data: data points outside the min/max range are simply not
 * rendered).
 *
 * @param cells   Monthly return records from monthlyReturns().
 * @param colors  Design-token color bag from chartColors().
 * @returns EChartsOption, or null when `cells` is empty.
 */
export function buildMonthlyReturnsOption(
  cells: MonthlyReturn[],
  colors: ChartColors,
): EChartsOption | null {
  if (cells.length === 0) return null;

  // Derive the sorted list of years (descending on y-axis).
  const yearSet = new Set(cells.map((c) => c.year));
  const years = Array.from(yearSet).sort((a, b) => b - a); // descending
  const yearIndex = new Map(years.map((y, i) => [y, i]));

  // Maximum absolute return for opacity scaling.
  const maxAbs = Math.max(...cells.map((c) => Math.abs(c.value)));

  // Build data entries: [xIndex (month-1), yIndex (year desc), value].
  // Cell color is driven by the hidden visualMap below; per-cell label color
  // is set via the ECharts per-point label override (visualMap does not touch it).
  type HeatCell = {
    value: [number, number, number];
    label: { color: string };
  };

  const data: HeatCell[] = cells.map((c) => {
    const xIdx = c.month - 1; // 0..11
    const yIdx = yearIndex.get(c.year) ?? 0;
    // Relative intensity [0, 1] used only for adaptive label contrast.
    const intensity = maxAbs > 0 ? Math.abs(c.value) / maxAbs : 0;
    // Label: light (on-accent) when cell is saturated; normal text for pale cells.
    const labelColor = intensity > LIGHT_LABEL_THRESHOLD ? colors.textOnAccent : colors.text;

    return {
      value: [xIdx, yIdx, c.value],
      label: { color: labelColor },
    };
  });

  return {
    animation: false,
    backgroundColor: "transparent",
    // ECharts 6 requires a visualMap for heatmap series. A hidden continuous
    // visualMap drives cell color; per-cell label.color overrides are unaffected.
    visualMap: {
      show: false,
      type: "continuous",
      min: -maxAbs,
      max: maxAbs,
      inRange: {
        // loss (red) → neutral surface → gain (green): symmetric diverging scale.
        color: [colors.loss, colors.grid, colors.gain],
      },
    },
    tooltip: {
      position: "top",
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (params) => {
        const { value } = params as unknown as { value: [number, number, number] };
        const [xIdx, yIdx, ret] = value;
        const month = MONTH_LABELS[xIdx] ?? "";
        const year = years[yIdx] ?? "";
        return `${month} ${year}: <b>${formatPercent(ret, 2, { signed: true })}</b>`;
      },
    },
    grid: { left: 52, right: 16, top: 8, bottom: 36 },
    xAxis: {
      type: "category",
      data: MONTH_LABELS as unknown as string[],
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textSecondary, fontSize: 11 },
      splitArea: { show: false },
    },
    yAxis: {
      type: "category",
      data: years.map(String),
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textSecondary, fontSize: 11 },
      splitArea: { show: false },
    },
    series: [
      {
        // Cell color is driven by the hidden visualMap above.
        // Per-cell label.color is set on each data point independently.
        name: "Monthly return",
        type: "heatmap",
        data,
        label: {
          show: true,
          fontSize: 10,
          formatter: (params) => {
            const [, , ret] = params.value as [number, number, number];
            return formatPercent(ret, 1);
          },
        },
        itemStyle: { borderColor: colors.grid, borderWidth: 1 },
        emphasis: {
          itemStyle: { borderColor: colors.text, borderWidth: 1, opacity: 1 },
        },
      },
    ],
  };
}

// ── Drawdown area chart ───────────────────────────────────────────────────

/**
 * Build a drawdown area chart from a DrawdownResult.
 *
 * The series is rendered as a line + filled area using `colors.loss`. The
 * y-axis shows percent values (fractions → ×100 via the axisLabel formatter;
 * the data stays in fraction form so tooltips and markArea share one scale).
 * A `markArea` shades the worst drawdown window (from peak to trough) with
 * the depth labeled in the shading.
 *
 * @param dd      Drawdown result from drawdownSeries().
 * @param colors  Design-token color bag from chartColors().
 * @returns EChartsOption, or null when `dd` is null or has no data.
 */
export function buildDrawdownOption(
  dd: DrawdownResult | null,
  colors: ChartColors,
): EChartsOption | null {
  if (!dd || dd.dates.length === 0) return null;

  const data: [string, number][] = dd.dates.map((date, i) => [date, dd.values[i]]);

  return {
    animation: false,
    backgroundColor: "transparent",
    tooltip: {
      trigger: "axis",
      axisPointer: { type: "cross" },
      backgroundColor: colors.surface,
      borderColor: colors.grid,
      textStyle: { color: colors.text },
      formatter: (paramsRaw) => {
        const params = paramsRaw as unknown as Array<{
          axisValue: string;
          value: [string, number];
          marker: string;
        }>;
        if (!params.length) return "";
        const [date, val] = params[0].value;
        return `${formatDate(date)}<br/>${params[0].marker} <b>${formatPercent(val, 2)}</b>`;
      },
    },
    grid: { left: 64, right: 16, top: 24, bottom: 28 },
    xAxis: {
      type: "category",
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: { color: colors.textMuted, fontSize: 11 },
      boundaryGap: false,
    },
    yAxis: {
      type: "value",
      scale: false,
      max: 0,
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        // Fractions → percent display; data stays fractional.
        formatter: (v: number) => formatPercent(v, 0),
      },
    },
    series: [
      {
        name: "Drawdown",
        type: "line",
        data,
        showSymbol: false,
        lineStyle: { color: colors.loss, width: 1.5 },
        itemStyle: { color: colors.loss },
        areaStyle: { color: colors.loss, opacity: 0.2 },
        // Only render the worst-drawdown shading when there is an actual
        // drawdown (depth < 0). A monotonic NAV produces depth === 0 and
        // the "Worst: 0.00%" label must never be rendered.
        ...(dd.worst.depth < 0 && {
          markArea: {
            silent: true,
            itemStyle: {
              color: colors.loss,
              opacity: 0.1,
              borderColor: colors.loss,
              borderWidth: 1,
              borderType: "dashed",
            },
            label: {
              show: true,
              position: "top",
              color: colors.loss,
              fontSize: 11,
              formatter: () =>
                `Worst: ${formatPercent(dd.worst.depth, 2)}`,
            },
            data: [
              [
                { xAxis: dd.worst.from },
                { xAxis: dd.worst.to },
              ],
            ],
          },
        }),
      },
    ],
  };
}
