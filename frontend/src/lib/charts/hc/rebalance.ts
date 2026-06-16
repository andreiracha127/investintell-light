/**
 * Pure option builder: rebalance drift bands chart (Highcharts Core).
 *
 * Port of the legacy ECharts `buildDriftBandsOption` (src/lib/charts/rebalance.ts).
 * Renders one horizontal row per position showing:
 *   - the tolerance band around the target (accent-wash region) — ECharts
 *     markArea -> Highcharts yAxis.plotBands;
 *   - the target weight (accent scatter tick — one per row, anchored to that
 *     row's category index);
 *   - the current weight (graphite bar; loss-colored when breach === true).
 *
 * Highcharts `bar` is an inverted column: the xAxis carries the categories
 * (rendered vertically) and the yAxis is the horizontal VALUE axis. The
 * tolerance bands span value ranges, so they live on the yAxis as plotBands.
 *
 * Scale evidence (unchanged from source): all PositionDriftOut weight fields
 * are decimal fractions (0.05 = 5 p.p.). Converted to percent-points (× 100)
 * for chart display only.
 *
 * Band half-width per row mirrors the backend breach condition
 * (evaluator.py:131): a position is safe iff BOTH |drift| ≤ band_abs AND
 * |drift| ≤ target × band_rel, so the safe zone is the intersection:
 *   half_band = min(band_abs, target × band_rel)   [fractions, before ×100]
 * floored at 0.5pp so the region stays visible on tiny targets.
 *
 * The global Graphite theme owns axis grid / tooltip / legend chrome; this
 * builder sets only chart-specific content (series, token colors, value
 * formatting, plotBands).
 *
 * Empty/null drifts → returns null (caller hides the panel).
 */
import type { Options } from "highcharts";

import type { PositionDrift } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

/**
 * Build a drift-bands horizontal bar chart.
 *
 * @param drifts   PositionDriftOut[]; weights are decimal fractions.
 * @param colors   Design-token color bag (from chartColors()).
 * @param bandAbs  Policy band_abs (fraction, e.g. 0.05 = 5 p.p.).
 * @param bandRel  Policy band_rel (fraction, e.g. 0.25 = 25% of target).
 * @returns Highcharts Options or null when drifts is empty.
 */
export function buildHcDriftBandsOption(
  drifts: PositionDrift[],
  colors: ChartColors,
  bandAbs: number,
  bandRel: number,
): Options | null {
  if (!drifts || drifts.length === 0) return null;

  // Sort by target weight descending; reverse so the value axis puts the
  // largest weight at the top of the chart (Highcharts bar: first category is
  // drawn at the top). Net effect: ascending by target_weight.
  const rows = [...drifts]
    .sort((a, b) => b.target_weight - a.target_weight)
    .reverse();

  const labels = rows.map((d) => d.ticker);

  // Convert fractions → percent-points for display.
  const currentPct = rows.map((d) => parseFloat((d.current_weight * 100).toFixed(4)));
  const targetPct = rows.map((d) => parseFloat((d.target_weight * 100).toFixed(4)));

  // Band half-width per row, floored at 0.5pp (mirrors source).
  const halfBandPct = rows.map((d) =>
    Math.max(Math.min(bandAbs, d.target_weight * bandRel) * 100, 0.5),
  );

  // Tolerance bands: one accent-wash region per row, target ± halfBand. On the
  // value (y) axis. Highcharts plotBands span the full category axis; we anchor
  // them conceptually per row (same value math as the ECharts markArea).
  //
  // TODO(P1-parity): KNOWN VISUAL DIVERGENCE from the ECharts source. The legacy
  // markArea clipped each tolerance band to its own category row, so bands never
  // bled across rows. Highcharts yAxis.plotBands are full-width horizontal
  // stripes spanning ALL categories, so bands whose [from,to] value ranges
  // overlap will visually merge across rows (e.g. two positions with similar
  // targets). Per-row clipping (xAxis.plotBands keyed to a single category, or a
  // synthetic area series) is out of scope for P1; the value math below is
  // identical to the source, only the per-row clipping is dropped.
  const plotBands = rows.map((_, i) => ({
    from: parseFloat((targetPct[i]! - halfBandPct[i]!).toFixed(4)),
    to: parseFloat((targetPct[i]! + halfBandPct[i]!).toFixed(4)),
    color: colors.accentWash,
    zIndex: 0,
  }));

  // Per-row target ticks: scatter anchored to [categoryIndex, targetPct],
  // rendered as a thin vertical mark (square symbol).
  const targetData = rows.map((_, i) => ({ x: i, y: targetPct[i]! }));

  // Current weight bars; breached rows in loss color.
  const barData = rows.map((d, i) => ({
    y: currentPct[i]!,
    color: d.breach ? colors.loss : colors.bar,
  }));

  return {
    chart: { type: "bar" },
    legend: { enabled: false },
    xAxis: {
      categories: labels,
      tickWidth: 0,
    },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return `${Math.round(this.value as number)}%`;
        },
      },
      plotBands,
    },
    tooltip: {
      // The HC tooltip context has no `this.index`; the hovered point is
      // `this.point` and the category row index is `this.point.index`
      // (follows the distribution.ts convention). Reading `this.index` here
      // is the masked runtime bug: it is undefined on a category axis, so
      // rows[undefined] tripped the guard and the tooltip rendered blank.
      // `this` is the HC tooltip context (Point-like); cast narrowly to read
      // the row index off the hovered point.
      formatter() {
        const idx = (this as unknown as { point: { index: number } }).point.index;
        const row = rows[idx];
        if (!row) return "";

        const tgt = row.target_weight;
        const cur = row.current_weight;
        const dev = cur - tgt;
        const devSign = dev >= 0 ? "+" : "";
        const halfFrac = halfBandPct[idx]! / 100; // back to fraction for formatPercent
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
    series: [
      {
        type: "bar",
        name: "Current weight",
        data: barData,
        pointPadding: 0.2,
        groupPadding: 0,
      },
      {
        type: "scatter",
        name: "Target weight",
        data: targetData,
        color: colors.accent,
        marker: { symbol: "square", width: 2, height: 18, lineWidth: 0 },
        enableMouseTracking: false,
        zIndex: 10,
      },
    ],
  };
}
