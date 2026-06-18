/**
 * Pure option builder: return-contributors packed bubble (Highcharts
 * `packedbubble`, registered via highcharts-more).
 *
 * One bubble per holding; bubble area ∝ |contribution to period return|,
 * colored gain (positive) / loss (negative). Used beside the contribution
 * waterfall on the Performance tab and recomputed for the selected NAV range.
 *
 * Chrome (tooltip styling) is owned by the global Graphite theme; the builder
 * sets only the series, token colors, and value/return formatting.
 */
import type { Options, PointOptionsObject } from "highcharts";

import type { ChartColors } from "@/lib/charts/chartColors";
import { formatCurrency, formatPercent } from "@/lib/format";

export interface BubbleItem {
  /** Holding ticker / label. */
  ticker: string;
  /** Contribution to the period P&L, in USD (signed). */
  value: number;
  /** Holding return over the period, decimal fraction (0.05 = 5%). */
  ret: number;
}

/**
 * Build a packed-bubble chart of return contributors.
 *
 * @param items  Per-holding contributions (USD, signed).
 * @param colors Design-token color bag (from chartColors()).
 */
export function buildHcContributionBubbleOption(
  items: BubbleItem[],
  colors: ChartColors,
): Options {
  // Bubble size is magnitude; drop zero-contribution holdings (no area).
  const data: PointOptionsObject[] = items
    .filter((item) => Math.abs(item.value) > 0)
    .sort((a, b) => Math.abs(b.value) - Math.abs(a.value))
    .map((item) => ({
      name: item.ticker,
      value: Math.abs(item.value),
      color: item.value >= 0 ? colors.gain : colors.loss,
      custom: { contribution: item.value, ret: item.ret },
    }));

  return {
    chart: { type: "packedbubble" },
    legend: { enabled: false },
    tooltip: {
      useHTML: true,
      formatter() {
        const point = (
          this as unknown as {
            point: {
              name: string;
              options: { custom?: { contribution?: number; ret?: number } };
            };
          }
        ).point;
        const contribution = point.options.custom?.contribution ?? 0;
        const ret = point.options.custom?.ret ?? 0;
        return [
          `<div style="font-size:12px">`,
          `<b>${point.name}</b>`,
          `<br/>${formatCurrency(contribution, { signed: true })}`,
          `<br/><span style="color:${contribution >= 0 ? colors.gain : colors.loss}">${formatPercent(
            ret,
            2,
            { signed: true },
          )} return</span>`,
          `</div>`,
        ].join("");
      },
    },
    plotOptions: {
      packedbubble: {
        minSize: "30%",
        maxSize: "120%",
        zMin: 0,
        layoutAlgorithm: {
          gravitationalConstant: 0.05,
          splitSeries: false,
          seriesInteraction: false,
          dragBetweenSeries: false,
          parentNodeLimit: true,
        },
        marker: { fillOpacity: 0.55, lineWidth: 1.5 },
        dataLabels: {
          enabled: true,
          format: "{point.name}",
          filter: { property: "value", operator: ">", value: 1 },
          style: {
            color: colors.text,
            textOutline: "none",
            fontWeight: "bold",
            fontSize: "11px",
          },
        },
      },
    },
    series: [
      {
        type: "packedbubble",
        name: "Contribution",
        data,
      },
    ],
  };
}
