/**
 * Pure option builder: rebalance drift chart (Highcharts Core) — Claude Design.
 *
 * One horizontal bar per position showing the SIGNED drift (current − target)
 * in percent-points. Per the Claude Design mockup this replaces the older
 * current-vs-target bars + target ticks:
 *   - bars are loss-colored when |drift| exceeds the tolerance band, else a
 *     neutral graphite tone;
 *   - a single 0 plotLine marks "on target";
 *   - ONE accent-wash plotBand spans the symmetric tolerance ±band, labeled
 *     "band ±N p.p.";
 *   - each bar carries a signed p.p. data label;
 *   - the value axis is titled "Drift vs. target (p.p.)".
 *
 * Scale: all PositionDriftOut weight fields are decimal fractions (0.05 = 5
 * p.p.). `drift_abs` is the signed (current − target) drift; we recompute from
 * current/target for robustness and convert × 100 for display only. Rows are
 * sorted by drift descending (largest positive drift at the top).
 *
 * The tolerance band shown is the policy ABSOLUTE band (`bandAbs`), matching the
 * mockup's single ±band region. `bandRel` is part of the breach test the
 * backend already evaluated (we read `breach` for per-bar coloring), so it is
 * accepted for signature stability but not drawn as a second band.
 *
 * The global Graphite theme owns axis grid / tooltip / legend chrome; this
 * builder sets only chart-specific content (series, token colors, value
 * formatting, plotBand/plotLine).
 *
 * Empty/null drifts → returns null (caller hides the panel).
 */
import type { Options } from "highcharts";

import type { PositionDrift } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

/** Signed p.p. string, e.g. +3.2 / −1.0 (true minus glyph). */
function ppLabel(pp: number, dp = 1): string {
  const sign = pp > 0 ? "+" : pp < 0 ? "−" : "";
  return `${sign}${Math.abs(pp).toFixed(dp)} p.p.`;
}

/**
 * Build a signed-drift horizontal bar chart.
 *
 * @param drifts   PositionDriftOut[]; weights are decimal fractions.
 * @param colors   Design-token color bag (from chartColors()).
 * @param bandAbs  Policy band_abs (fraction, e.g. 0.05 = 5 p.p.) — the ±band.
 * @param bandRel  Policy band_rel (fraction); accepted for signature stability.
 * @returns Highcharts Options or null when drifts is empty.
 */
export function buildHcDriftBandsOption(
  drifts: PositionDrift[],
  colors: ChartColors,
  bandAbs: number,
  bandRel: number,
  labelsByTicker: Record<string, string> = {},
): Options | null {
  if (!drifts || drifts.length === 0) return null;

  // Sort by signed drift descending (largest positive at the top of the bar
  // chart — Highcharts bar draws the first category at the top), mirroring the
  // mockup's `_drifts().sort((a,b)=>b.drift-a.drift)` then bar inversion.
  const rows = [...drifts]
    .map((d) => ({ ...d, drift: d.current_weight - d.target_weight }))
    .sort((a, b) => a.drift - b.drift);

  const labelFor = (ticker: string) => labelsByTicker[ticker.toUpperCase()] ?? ticker;
  const labels = rows.map((d) => labelFor(d.ticker));
  const bandPct = bandAbs * 100;

  // Signed drift (p.p.); breached rows in loss color, others neutral graphite.
  const barData = rows.map((d) => ({
    y: parseFloat((d.drift * 100).toFixed(4)),
    color: Math.abs(d.drift) > bandAbs ? colors.loss : colors.bar,
  }));

  return {
    chart: {
      type: "bar",
      spacing: [10, 18, 16, 8],
    },
    legend: { enabled: false },
    xAxis: {
      categories: labels,
      tickWidth: 0,
      lineWidth: 0,
      labels: {
        style: {
          color: colors.textSecondary,
          fontSize: "11px",
          textOverflow: "ellipsis",
        },
      },
    },
    yAxis: {
      gridLineColor: colors.grid,
      title: {
        text: "Drift vs. target (p.p.)",
        style: { color: colors.textSecondary, fontSize: "10px" },
      },
      labels: {
        formatter() {
          const v = this.value as number;
          return `${v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(Math.round(v))}`;
        },
      },
      // 0 = "on target".
      plotLines: [{ value: 0, color: colors.textMuted, width: 1, zIndex: 3 }],
      // ONE symmetric accent-wash tolerance band ±bandPct.
      plotBands: [
        {
          from: parseFloat((-bandPct).toFixed(4)),
          to: parseFloat(bandPct.toFixed(4)),
          color: colors.accentWash,
          zIndex: 0,
          label: {
            text: `band ${ppLabel(bandPct, 0).replace("+", "±")}`,
            align: "right",
            x: -4,
            y: 12,
            style: { color: colors.textMuted, fontSize: "9px" },
          },
        },
      ],
    },
    tooltip: {
      // HC category-axis tooltip: hovered row index is `this.point.index`.
      formatter() {
        const idx = (this as unknown as { point: { index: number } }).point.index;
        const row = rows[idx];
        if (!row) return "";
        const breach = Math.abs(row.drift) > bandAbs;
        const tone = breach ? colors.loss : colors.textSecondary;
        const breachTag = breach
          ? `<br/><span style="color:${colors.loss}">band breach</span>`
          : "";
        return [
          `<div style="font-size:12px">`,
          `<b>${labelFor(row.ticker)}</b>`,
          `<br/>Current: <b>${formatPercent(row.current_weight, 2)}</b>`,
          `<br/>Target: <b>${formatPercent(row.target_weight, 2)}</b>`,
          `<br/>Drift: <b style="color:${tone}">${ppLabel(row.drift * 100, 2)}</b>`,
          breachTag,
          `</div>`,
        ].join("");
      },
    },
    plotOptions: {
      bar: {
        borderRadius: 2,
        groupPadding: 0.18,
        pointPadding: 0.22,
        pointWidth: 14,
        dataLabels: {
          enabled: true,
          allowOverlap: false,
          crop: false,
          overflow: "allow",
          formatter() {
            return ppLabel(this.y as number, 1);
          },
          style: {
            color: colors.textSecondary,
            fontWeight: "bold",
            fontSize: "10px",
            textOutline: "none",
          },
        },
      },
    },
    series: [{ type: "bar", name: "Drift", data: barData }],
  };
}
