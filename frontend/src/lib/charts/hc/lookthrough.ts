/**
 * Pure Highcharts option builder: consolidated look-through exposure chart.
 *
 * Horizontal stacked bars (Direct + Via funds), one row per exposure item.
 * Ported 1:1 from the ECharts `buildExposureBarsOption` — same sort/topN gate,
 * same label/total-percent coloring, same null fallback. No finance here, only
 * display arrangement. Chrome (axis grid/tooltip/legend styling) is owned by the
 * global Graphite theme; this builder sets only chart-specific content.
 *
 * Highcharts mapping notes vs ECharts source:
 * - ECharts horizontal bar = Highcharts `chart.type: "bar"` with `inverted: true`.
 * - ECharts category yAxis (row labels) -> Highcharts xAxis (the category axis on
 *   an inverted bar chart). ECharts value xAxis (percent) -> Highcharts yAxis.
 * - ECharts `stack: "exposure"` -> `plotOptions.bar.stacking: "normal"`.
 * - The total-% label rides the outer ("Via funds") series, looked up by point
 *   index, exactly like the source derives the row from `dataIndex`.
 */
import type { Options, Point } from "highcharts";

import type { ExposureItem } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/theme";
import { formatNumber } from "@/lib/format";

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
export function buildHcExposureBarsOption(
  items: ExposureItem[],
  colors: ChartColors,
  opts: { topN?: number } = {},
): Options {
  const topN = opts.topN ?? 10;

  // Sort desc by total, take topN, then reverse so largest renders at the top.
  // (Both ECharts category axis and Highcharts inverted bar render bottom-up,
  // so the reverse keeps the largest row at the top in both libraries.)
  const sorted = [...items]
    .sort((a, b) => b.total_pct - a.total_pct)
    .slice(0, topN)
    .reverse();

  const labels = sorted.map((item) => item.label ?? item.key);

  return {
    chart: { type: "bar", inverted: true },
    legend: {
      enabled: true,
      align: "left",
      verticalAlign: "top",
      symbolRadius: 0,
    },
    xAxis: {
      type: "category",
      categories: labels,
    },
    yAxis: {
      type: "linear",
      title: { text: undefined },
      labels: {
        formatter() {
          return formatNumber(this.value as number, 0) + "%";
        },
      },
    },
    plotOptions: {
      bar: { stacking: "normal" },
      series: { states: { hover: { enabled: false }, inactive: { enabled: false } } },
    },
    tooltip: {
      useHTML: true,
      shared: true,
      formatter(this: Point) {
        const points = (this as unknown as { points?: Point[] }).points ?? [];
        if (!points.length) return "";
        const idx = this.index;
        const row = sorted[idx];
        if (!row) return "";
        const lines = points.map(
          (p) =>
            `<span style="color:${String(p.color)}">■</span> ${p.series.name}: <b>${formatNumber(p.y as number, 2)}%</b>`,
        );
        lines.push(
          `<span style="font-size:11px;color:${colors.textMuted}">Total: <b>${formatNumber(row.total_pct, 2)}%</b></span>`,
        );
        const name = (this.category as string | undefined) ?? "";
        return `<div style="font-size:12px">${name}<br/>${lines.join("<br/>")}</div>`;
      },
    },
    series: [
      {
        type: "bar",
        name: "Direct",
        data: sorted.map((item) => item.direct_pct),
        color: colors.bar,
        dataLabels: { enabled: false },
      },
      {
        type: "bar",
        name: "Via funds",
        data: sorted.map((item) => item.indirect_pct),
        color: colors.barMute,
        dataLabels: {
          enabled: true,
          // Show total (direct + indirect) at the bar end. Highcharts stacks
          // the label on the outer segment; we derive the row from the point
          // index and look up total_pct directly, mirroring the source.
          style: { color: colors.textSecondary, fontWeight: "normal" },
          formatter(this: Point) {
            const idx = this.index;
            const row = sorted[idx];
            if (!row) return "";
            return formatNumber(row.total_pct, 1) + "%";
          },
        },
      },
    ],
  };
}
