/**
 * Pure option builder: COMBO regime per-class bands (Highcharts Core).
 *
 * One horizontal range bar per asset class showing the regime-driven
 * `[min_weight, max_weight]` envelope the min-CVaR optimizer allocates inside.
 * Mirrors the drift-bands builder (`buildHcDriftBandsOption`, rebalance.ts): a
 * horizontal `columnrange`, token colors only, decimal-fraction weights shown as
 * percent for the axis/labels.
 *
 * Classes are drawn in the canonical order equity → fixed_income →
 * alternatives → cash (Highcharts bar/columnrange draws the FIRST category at
 * the top, so the array is reversed for the axis to keep equity on top). Only
 * the classes present in `bands` are shown.
 *
 * The global Graphite theme owns axis grid / tooltip / legend chrome; this
 * builder sets only chart-specific content (series, token colors, value
 * formatting). Empty bands → returns null (caller renders the haven tilt or an
 * empty-state instead).
 */
import type { Options } from "highcharts";

import type { ChartColors } from "@/lib/charts/chartColors";
import { formatPercent } from "@/lib/format";

export interface MacroBand {
  asset_class: string;
  min_weight: number;
  max_weight: number;
}

/** Canonical asset-class order (matches backend taa_bands.ASSET_CLASSES). */
const CLASS_ORDER = ["equity", "fixed_income", "alternatives", "cash"] as const;

/** Human label for an asset-class code. */
const CLASS_LABEL: Record<string, string> = {
  equity: "Equity",
  fixed_income: "Fixed income",
  alternatives: "Alternatives",
  cash: "Cash",
};

/**
 * Build a horizontal range chart of per-class regime bands.
 *
 * @param bands  Per-class `[min_weight, max_weight]`; weights are decimal
 *               fractions (0.52 = 52%).
 * @param colors Design-token color bag (from chartColors()).
 * @returns Highcharts Options or null when `bands` is empty.
 */
export function buildHcMacroBandsOption(
  bands: MacroBand[],
  colors: ChartColors,
): Options | null {
  if (!bands || bands.length === 0) return null;

  const byClass = new Map(bands.map((b) => [b.asset_class, b]));
  // Present classes in canonical order, then any extras not in the canon.
  const ordered = [
    ...CLASS_ORDER.filter((c) => byClass.has(c)),
    ...bands.map((b) => b.asset_class).filter((c) => !CLASS_ORDER.includes(c as never)),
  ];

  const categories = ordered.map((c) => c);
  const data = ordered.map((c) => {
    const b = byClass.get(c)!;
    return [b.min_weight, b.max_weight];
  });

  return {
    chart: { type: "columnrange", inverted: true },
    legend: { enabled: false },
    xAxis: {
      categories,
      tickWidth: 0,
      labels: {
        formatter() {
          const c = String(this.value);
          return CLASS_LABEL[c] ?? c;
        },
        style: { color: colors.textSecondary, fontSize: "10px" },
      },
    },
    yAxis: {
      min: 0,
      title: {
        text: "Allowed weight band",
        style: { color: colors.textSecondary, fontSize: "10px" },
      },
      labels: {
        formatter() {
          return `${Math.round((this.value as number) * 100)}%`;
        },
      },
    },
    tooltip: {
      formatter() {
        const idx = (this as unknown as { point: { index: number } }).point.index;
        const cls = ordered[idx];
        const b = cls ? byClass.get(cls) : undefined;
        if (!b) return "";
        return [
          `<div style="font-size:12px">`,
          `<b>${CLASS_LABEL[cls] ?? cls}</b>`,
          `<br/>Min: <b>${formatPercent(b.min_weight, 1)}</b>`,
          `<br/>Max: <b>${formatPercent(b.max_weight, 1)}</b>`,
          `</div>`,
        ].join("");
      },
    },
    plotOptions: {
      columnrange: {
        borderWidth: 0,
        color: colors.accent,
        dataLabels: {
          enabled: true,
          inside: false,
          formatter() {
            // columnrange exposes both ends; label the upper extent.
            const high = (this as unknown as { y: number }).y;
            return `${Math.round(high * 100)}%`;
          },
          style: { color: colors.textSecondary, fontSize: "9px" },
        },
      },
    },
    series: [
      {
        type: "columnrange",
        name: "Weight band",
        data,
      },
    ],
  };
}
