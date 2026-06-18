/**
 * Pure option builder: contribution waterfall (Highcharts Core `waterfall`).
 *
 * One bar per holding showing its contribution to the period's portfolio P&L
 * (USD), bridged left→right from zero to the period total. Gains rise (gain
 * color), detractors fall (loss color); a final summed bar shows the net period
 * result in graphite. Used on the Performance tab — the rows are recomputed for
 * the range selected on the synthetic-NAV navigator above it.
 *
 * Chrome (axis/grid/tooltip styling) is owned by the global Graphite theme; the
 * builder sets only the series, token colors, and value/return formatting.
 */
import type { Options, PointOptionsObject } from "highcharts";

import type { ChartColors } from "@/lib/charts/chartColors";
import { formatCurrency, formatPercent } from "@/lib/format";

export interface ContributionRow {
  /** Holding ticker / label. */
  label: string;
  /** Contribution to the period P&L, in USD (signed). */
  value: number;
  /** Holding return over the period, decimal fraction (0.05 = 5%). */
  ret: number;
}

/**
 * Build a contribution waterfall.
 *
 * @param rows   Per-holding period contributions (USD, signed).
 * @param colors Design-token color bag (from chartColors()).
 */
export function buildHcContributionWaterfallOption(
  rows: ContributionRow[],
  colors: ChartColors,
): Options {
  const sorted = [...rows].sort((a, b) => b.value - a.value);

  const data: PointOptionsObject[] = sorted.map((row) => ({
    name: row.label,
    y: row.value,
    custom: { ret: row.ret },
  }));
  // Closing summed bar — the net period result, in graphite.
  data.push({ name: "Total", isSum: true, color: colors.bar });

  return {
    chart: { type: "waterfall" },
    legend: { enabled: false },
    xAxis: { type: "category", tickWidth: 0 },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return formatCurrency(this.value as number);
        },
      },
    },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              y: number;
              isSum?: boolean;
              options: { custom?: { ret?: number } };
            };
          }
        ).point;
        if (point.isSum) {
          return `<div style="font-size:12px"><b>Period result</b><br/>${formatCurrency(
            point.y,
            { signed: true },
          )}</div>`;
        }
        const ret = point.options.custom?.ret ?? 0;
        return [
          `<div style="font-size:12px">`,
          `<b>${point.name}</b>`,
          `<br/>${formatCurrency(point.y, { signed: true })}`,
          `<br/><span style="color:${point.y >= 0 ? colors.gain : colors.loss}">${formatPercent(
            ret,
            2,
            { signed: true },
          )} return</span>`,
          `</div>`,
        ].join("");
      },
    },
    plotOptions: {
      waterfall: {
        // Rises in gain, falls in loss; the sum point overrides to graphite.
        upColor: colors.gain,
        color: colors.loss,
        lineWidth: 1,
        borderWidth: 0,
        dataLabels: {
          enabled: true,
          formatter() {
            const y = this.y as number;
            return formatCurrency(y, { signed: true });
          },
          style: { color: colors.textMuted, fontWeight: "normal", textOutline: "none" },
        },
      },
    },
    series: [
      {
        type: "waterfall",
        name: "Contribution",
        data,
      },
    ],
  };
}
