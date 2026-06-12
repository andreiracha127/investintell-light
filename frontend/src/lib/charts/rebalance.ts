/**
 * Pure option builder: rebalance drift bands chart.
 *
 * `buildDriftBandsOption` renders one horizontal row per position showing:
 *   - The tolerance band around the target (accent-wash markArea)
 *   - The target weight (accent scatter tick — one per row, anchored to that row)
 *   - The current weight (graphite bar; loss-colored when breach === true)
 *
 * Scale evidence: backend/app/schemas/rebalance.py docstring states
 * "Bandas e pesos em frações decimais (0.05 = 5 p.p.)". All PositionDriftOut
 * fields (current_weight, target_weight, drift_abs, drift_rel) are decimal
 * fractions. Converted to percent-points (× 100) for chart display only.
 *
 * Band formula (mirrors backend/app/rebalance/evaluator.py:131):
 *   breach = abs(drift_abs) > band_abs OR drift_rel > band_rel
 * A position is safe only when BOTH conditions are satisfied simultaneously,
 * so the safe zone is the INTERSECTION:
 *   half_band = min(band_abs, target × band_rel)   [fractions, before ×100]
 * This gives the exact symmetric zone around the target within which neither
 * band is breached.
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
 * Each row shows current weight as a bar, a per-row target tick (scatter
 * overlay anchored to [targetPct, ticker]) and a symmetric tolerance band
 * (markArea spans target ± min(band_abs, target × band_rel) — the exact
 * safe zone from the backend evaluator, see module JSDoc).
 * Bars for breached positions are rendered in colors.loss.
 *
 * @param drifts   PositionDriftOut[]; weights are decimal fractions.
 * @param colors   Design-token color bag (from chartColors()).
 * @param bandAbs  Policy band_abs (fraction, e.g. 0.05 = 5 p.p.).
 * @param bandRel  Policy band_rel (fraction, e.g. 0.25 = 25% of target).
 * @returns EChartsOption or null when drifts is empty.
 */
export function buildDriftBandsOption(
  drifts: PositionDrift[],
  colors: ChartColors,
  bandAbs: number,
  bandRel: number,
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

  // Band half-width per row: min(band_abs, target × band_rel) mirrors the
  // backend breach condition (evaluator.py:131): a position is safe iff BOTH
  // |drift| ≤ band_abs AND |drift| ≤ target × band_rel. We floor at 0.5pp
  // so the region is always visible even on tiny targets.
  const halfBandPct = rows.map((d) =>
    Math.max(
      Math.min(bandAbs, d.target_weight * bandRel) * 100,
      0.5,
    ),
  );

  // markArea: one shaded region per row centred on target ± halfBand.
  // Both corner objects carry explicit yAxis so ECharts never inherits
  // the wrong row's category axis name.
  const markAreaData: [object, object][] = rows.map((d, i) => [
    {
      yAxis: d.ticker,
      xAxis: parseFloat((targetPct[i]! - halfBandPct[i]!).toFixed(4)),
      itemStyle: { color: colors.accentWash },
    },
    {
      yAxis: d.ticker,
      xAxis: parseFloat((targetPct[i]! + halfBandPct[i]!).toFixed(4)),
    },
  ]);

  // Per-row target ticks: scatter series rendered as thin vertical lines
  // (symbol: "rect", symbolSize: [2, 16]) anchored to [targetPct, ticker].
  // Using a scatter overlay instead of markLine avoids the full-height
  // vertical line bug where a single-point markLine entry spans the entire
  // chart height rather than being clipped to one row.
  const targetScatterData = rows.map((d, i) => ({
    value: [targetPct[i], d.ticker],
    itemStyle: { color: colors.accent },
  }));

  const targetSeries: SeriesOption = {
    name: "Target weight",
    type: "scatter",
    xAxisIndex: 0,
    yAxisIndex: 0,
    symbol: "rect",
    symbolSize: [2, 18],
    data: targetScatterData,
    emphasis: { disabled: true },
    silent: true,
    z: 10,
  };

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
          value: number | [number, string];
          seriesIndex: number;
          seriesName: string;
        }>;
        const bar = params.find((p) => p.seriesName === "Current weight");
        if (!bar) return "";
        const row = rows[bar.dataIndex];
        if (!row) return "";

        const tgt = row.target_weight;
        const cur = row.current_weight;
        const dev = cur - tgt;
        const devSign = dev >= 0 ? "+" : "";
        const halfFrac = halfBandPct[bar.dataIndex]! / 100; // back to fraction for formatPercent
        const breachTag = row.breach
          ? `<span style="color:${colors.loss};font-weight:bold"> ● Out of band</span>`
          : "";

        return [
          `<div style="font-size:12px">`,
          `<b>${row.ticker}</b>${breachTag}`,
          `<br/>Current: <b>${formatPercent(cur, 2)}</b>`,
          `<br/>Target: <b>${formatPercent(tgt, 2)}</b>`,
          `<br/>Band: ${formatPercent(tgt - halfFrac, 2)} – ${formatPercent(tgt + halfFrac, 2)}`,
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
    series: [barSeries, targetSeries],
  };
}
