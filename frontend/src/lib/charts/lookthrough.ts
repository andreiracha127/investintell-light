/**
 * Pure option builders: consolidated look-through exposure charts.
 *
 * Two builders — exposure horizontal stacked bars (Direct + Via funds) and a
 * residual waterfall composing the NAV to 100%. No finance here — display
 * arrangement only.
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { ExposureItem, LookthroughSummary } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";

// ── Shared axis/grid defaults (horizontal bar orientation) ────────────────

const HBAR_GRID = { left: 160, right: 72, top: 32, bottom: 8 } as const;

// ── Exposure bars ─────────────────────────────────────────────────────────

/**
 * Horizontal stacked bar chart: one row per exposure item, two segments each —
 * Direct (colors.bar / graphite) and Via funds (colors.barMute / grey). Sorted
 * by total_pct descending; top-N rows shown (default 10). A value label at the
 * bar end shows the total formatted as "x.x%". Tooltip shows both segments and
 * the total.
 *
 * @param items     Exposure items for one dimension.
 * @param colors    Design-token color bag (from chartColors()).
 * @param opts.topN Maximum rows to render (default 10).
 */
export function buildExposureBarsOption(
  items: ExposureItem[],
  colors: ChartColors,
  opts: { topN?: number } = {},
): EChartsOption {
  const topN = opts.topN ?? 10;

  // Sort desc by total, take topN, then reverse so largest is at top
  // (ECharts category axis renders bottom-up).
  const sorted = [...items]
    .sort((a, b) => b.total_pct - a.total_pct)
    .slice(0, topN)
    .reverse();

  const labels = sorted.map((item) => item.label ?? item.key);

  const directSeries: SeriesOption = {
    name: "Direct",
    type: "bar",
    stack: "exposure",
    data: sorted.map((item) => item.direct_pct),
    barCategoryGap: "35%",
    itemStyle: { color: colors.bar },
    label: { show: false },
    emphasis: { disabled: true },
  };

  const viaFundsSeries: SeriesOption = {
    name: "Via funds",
    type: "bar",
    stack: "exposure",
    data: sorted.map((item) => item.indirect_pct),
    itemStyle: { color: colors.barMute },
    emphasis: { disabled: true },
    label: {
      show: true,
      position: "right",
      color: colors.textSecondary,
      // Show total (direct + indirect) at bar end using the formatter params.
      // ECharts passes the stacked value for the last segment; instead we
      // derive the row index from dataIndex and look up total_pct directly.
      formatter: (params) => {
        const row = sorted[params.dataIndex];
        if (!row) return "";
        return formatNumber(row.total_pct, 1) + "%";
      },
    },
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
          seriesName: string;
          dataIndex: number;
          value: number;
          marker: string;
          name: string;
        }>;
        if (!params.length) return "";
        const row = sorted[params[0].dataIndex];
        if (!row) return "";
        const lines = params.map(
          (p) =>
            `${p.marker}${p.seriesName}: <b>${formatNumber(p.value, 2)}%</b>`,
        );
        lines.push(
          `<span style="font-size:11px;color:${colors.textMuted}">Total: <b>${formatNumber(row.total_pct, 2)}%</b></span>`,
        );
        return `<div style="font-size:12px">${params[0].name}<br/>${lines.join("<br/>")}</div>`;
      },
    },
    legend: {
      top: 0,
      left: 0,
      textStyle: { color: colors.textSecondary },
      icon: "rect",
      itemWidth: 10,
      itemHeight: 10,
    },
    grid: HBAR_GRID,
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatNumber(value, 0) + "%",
      },
    },
    yAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: {
        color: colors.textSecondary,
        width: 148,
        overflow: "truncate",
      },
    },
    series: [directSeries, viaFundsSeries],
  };
}

// ── Residual waterfall ────────────────────────────────────────────────────

/**
 * Waterfall chart composing the NAV to its total look-through coverage:
 *
 *   Identified holdings  →  sum_pct_total minus residuals (clamped ≥ 0)
 *   Funds without disclosure  →  nondecomposable_fund_pct
 *   Derivatives (net)  →  derivatives_net_pct
 *   Unidentified  →  unidentified_pct  (colors.loss)
 *   ─────────────────────────────────────────────────────
 *   Total  →  outlined bar at sum_pct_total
 *
 * Uses the standard transparent-helper-stack waterfall technique: a
 * "placeholder" series provides the invisible offset; the visible series
 * stacks on top of it. All null values are treated as 0. Values in the
 * LookthroughSummary are PERCENT POINTS (94.6 = 94.6%), not fractions.
 *
 * Note: `derivatives_net_pct` can be negative (short exposure exceeds long).
 * For the purposes of this composition view the offset contribution of
 * derivatives is clamped to 0 so that cumulative offsets for subsequent bars
 * remain well-placed. The segment value itself and the "Total" bar (which uses
 * sum_pct_total directly) are unaffected — nothing misleads.
 */
export function buildResidualWaterfallOption(
  summary: LookthroughSummary,
  colors: ChartColors,
): EChartsOption {
  const total = summary.sum_pct_total ?? 0;
  const nondecomp = summary.nondecomposable_fund_pct ?? 0;
  const derivNet = summary.derivatives_net_pct ?? 0;
  const unidentified = summary.unidentified_pct ?? 0;

  // "Identified" = everything that is not one of the three residual categories.
  const identified = Math.max(0, total - nondecomp - derivNet - unidentified);

  const categories = [
    "Identified holdings",
    "Funds without disclosure",
    "Derivatives (net)",
    "Unidentified",
    "Total",
  ];

  // Waterfall values: each step's magnitude.
  const values = [identified, nondecomp, derivNet, unidentified, total];

  // Invisible offset for the helper series: cumulative sum before each step;
  // the final "Total" bar starts from 0 (outline bar).
  // derivNet is clamped to 0 for offset arithmetic — see JSDoc.
  const derivNetOffset = Math.max(0, derivNet);
  const offsets = [
    0,
    identified,
    identified + nondecomp,
    identified + nondecomp + derivNetOffset,
    0, // Total bar floats from 0
  ];

  // Colors per step.
  const stepColors = [
    colors.bar,
    colors.barMute,
    colors.barMute,
    colors.loss,
    "transparent", // Total bar color is set via borderColor in itemStyle
  ];

  // For the "Total" bar we want an outlined style, not a filled bar.
  const barData = values.map((v, i) => {
    if (i === categories.length - 1) {
      // Outlined "Total" bar: transparent fill, graphite border.
      return {
        value: v,
        itemStyle: {
          color: "transparent",
          borderColor: colors.bar,
          borderWidth: 2,
        },
      };
    }
    return {
      value: v,
      itemStyle: { color: stepColors[i] },
    };
  });

  // y-axis max: at least 100, or round the total up to the next 10.
  const yMax = Math.ceil(Math.max(100, total) / 10) * 10;

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
          seriesIndex: number;
          name: string;
          value: number;
          dataIndex: number;
        }>;
        // Only render the visible series (index 1), not the helper offset.
        const visible = params.find((p) => p.seriesIndex === 1);
        if (!visible) return "";
        return `<span style="font-size:12px">${visible.name}: <b>${formatNumber(visible.value, 2)}%</b></span>`;
      },
    },
    // Vertical layout: generous bottom margin for two-line wrapped labels,
    // slim left for the % axis, slim right for breathing room.
    grid: { left: 48, right: 16, top: 24, bottom: 64 },
    xAxis: {
      type: "category",
      data: categories,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: {
        color: colors.textSecondary,
        interval: 0,
        width: 72,
        overflow: "break",
      },
    },
    yAxis: {
      type: "value",
      min: 0,
      max: yMax,
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => formatNumber(value, 0) + "%",
      },
    },
    series: [
      {
        // Invisible offset (placeholder stack — now vertical bottom-offset).
        name: "_offset",
        type: "bar",
        stack: "waterfall",
        data: offsets,
        barCategoryGap: "40%",
        itemStyle: { color: "transparent", borderColor: "transparent" },
        tooltip: { show: false },
        silent: true,
      },
      {
        // Visible waterfall bars.
        name: "Exposure",
        type: "bar",
        stack: "waterfall",
        data: barData,
        label: {
          show: true,
          position: "top",
          color: colors.textSecondary,
          formatter: (params) =>
            formatNumber(params.value as number, 1) + "%",
        },
      },
    ],
  };
}
