/**
 * Pure option builder: rebalance drift bands chart.
 *
 * `buildDriftBandsOption` renders one horizontal row per position showing:
 *   - The tolerance band around the target (accent-wash markArea)
 *   - The target weight (accent markLine)
 *   - The current weight (graphite bar; loss-colored when breach === true)
 *
 * Scale evidence: backend/app/schemas/rebalance.py docstring states
 * "Bandas e pesos em frações decimais (0.05 = 5 p.p.)". All PositionDriftOut
 * fields (current_weight, target_weight, drift_abs, drift_rel) are decimal
 * fractions. Converted to percent-points (× 100) for chart display only.
 *
 * Empty/null drifts → returns null (caller hides the panel).
 */
import type { EChartsOption, SeriesOption } from "echarts";

import type { PositionDrift } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatPercent } from "@/lib/format";

const HBAR_GRID = { left: 72, right: 80, top: 16, bottom: 8 } as const;

/**
 * Build a drift-bands horizontal bar chart.
 *
 * Each row shows current weight as a bar plus a target line and a symmetric
 * tolerance band around it (± drift_abs, min ± 0.5pp for visibility).
 * Bars for breached positions are rendered in colors.loss.
 *
 * @param drifts  PositionDriftOut[]; weights are decimal fractions.
 * @param colors  Design-token color bag (from chartColors()).
 * @returns EChartsOption or null when drifts is empty.
 */
export function buildDriftBandsOption(
  drifts: PositionDrift[],
  colors: ChartColors,
): EChartsOption | null {
  if (!drifts || drifts.length === 0) return null;

  // Sort by target weight descending; reverse so ECharts bottom-up axis
  // puts the largest weight at the top of the chart.
  const rows = [...drifts]
    .sort((a, b) => b.target_weight - a.target_weight)
    .reverse();

  const labels = rows.map((d) => d.ticker);

  // Convert fractions → percent-points for display.
  const currentPct = rows.map((d) => parseFloat((d.current_weight * 100).toFixed(4)));
  const targetPct = rows.map((d) => parseFloat((d.target_weight * 100).toFixed(4)));

  // Band half-width per row: use drift_abs as the approximate band half-width.
  // drift_abs = |current - target| so it equals or understimates the actual
  // policy band_abs — for breached rows this gives exactly the breach margin,
  // for in-band rows it shows the actual deviation (smaller than the band).
  // We floor at 0.5pp so the band region is always visible.
  const halfBandPct = rows.map((d) =>
    Math.max(d.drift_abs * 100, 0.5),
  );

  // markArea: one shaded region per row centred on target ± halfBand.
  // Coordinates use the numeric (value) x-axis and category y-axis names.
  const markAreaData: [object, object][] = rows.map((d, i) => [
    {
      yAxis: d.ticker,
      xAxis: parseFloat((targetPct[i]! - halfBandPct[i]!).toFixed(4)),
      itemStyle: { color: colors.accentWash, opacity: 0.6 },
    },
    {
      yAxis: d.ticker,
      xAxis: parseFloat((targetPct[i]! + halfBandPct[i]!).toFixed(4)),
    },
  ]);

  // markLine: one vertical target line per row.
  // ECharts markLine on a bar series uses [{ xAxis, yAxis }, { xAxis, yAxis }]
  // pairs to draw a segment; a single-point entry draws a full-span line.
  const markLineData = rows.map((d, i) => ({
    xAxis: targetPct[i],
    lineStyle: { color: colors.accent, width: 1.5, type: "solid" as const },
    label: { show: false },
  }));

  const barSeries: SeriesOption = {
    name: "Current weight",
    type: "bar",
    data: currentPct.map((val, i) => ({
      value: val,
      itemStyle: { color: rows[i]?.breach ? colors.loss : colors.bar },
    })),
    barCategoryGap: "40%",
    emphasis: { disabled: true },
    markArea: {
      silent: true,
      data: markAreaData,
    },
    markLine: {
      silent: true,
      symbol: ["none", "none"],
      data: markLineData,
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
          dataIndex: number;
          value: number;
          seriesIndex: number;
        }>;
        const bar = params.find((p) => p.seriesIndex === 0);
        if (!bar) return "";
        const row = rows[bar.dataIndex];
        if (!row) return "";

        const tgt = row.target_weight;
        const cur = row.current_weight;
        const dev = cur - tgt;
        const devSign = dev >= 0 ? "+" : "";
        const bandHalf = halfBandPct[bar.dataIndex]! / 100; // back to fraction for formatPercent
        const breachTag = row.breach
          ? `<span style="color:${colors.loss};font-weight:bold"> ● Out of band</span>`
          : "";

        return [
          `<div style="font-size:12px">`,
          `<b>${row.ticker}</b>${breachTag}`,
          `<br/>Current: <b>${formatPercent(cur, 2)}</b>`,
          `<br/>Target: <b>${formatPercent(tgt, 2)}</b>`,
          `<br/>Band: ${formatPercent(tgt - bandHalf, 2)} – ${formatPercent(tgt + bandHalf, 2)}`,
          `<br/>Deviation: <b style="color:${row.breach ? colors.loss : colors.textSecondary}">${devSign}${(dev * 100).toFixed(2)}pp</b>`,
          `</div>`,
        ].join("");
      },
    },
    grid: HBAR_GRID,
    xAxis: {
      type: "value",
      splitLine: { lineStyle: { color: colors.grid } },
      axisLabel: {
        color: colors.textMuted,
        formatter: (value: number) => `${value.toFixed(0)}%`,
      },
    },
    yAxis: {
      type: "category",
      data: labels,
      axisLine: { lineStyle: { color: colors.grid } },
      axisTick: { show: false },
      axisLabel: {
        color: colors.textSecondary,
        width: 60,
        overflow: "truncate",
      },
    },
    series: [barSeries],
  };
}
