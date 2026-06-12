/**
 * Pure option builder: consolidated look-through exposure chart.
 *
 * Horizontal stacked bars (Direct + Via funds). The residual composition
 * (unidentified / funds without disclosure) is reported as KPI tiles, not a
 * chart. No finance here — display arrangement only.
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { ExposureItem } from "@/lib/api/client";
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
