/**
 * Pure option builder: Treasury fiscal series explorer (Macro → Fiscal).
 *
 * Multi-series Highcharts Stock line chart over `/macro/fiscal` observations —
 * navigator + scrollbar for scrubbing up to 10 years of history. The global
 * Graphite theme (highchartsTheme) owns axis/grid/tooltip chrome; this builder
 * sets ONLY series, colors, legend, and value formatting.
 */
import type { Options, SeriesLineOptions } from "highcharts";

import type { FiscalCategory, FiscalSeries } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { dateToUtcMs, formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import { formatCompact, formatNumber } from "@/lib/format";

/**
 * Categories whose values read as percent rates. Only `rates` (average
 * interest rates on outstanding securities) is a percentage; `interest` is
 * federal interest EXPENSE in raw dollars, so it must format as a level, not
 * a percent — otherwise the y-axis/tooltip show values like "123,456,789.00%".
 */
const PERCENT_CATEGORIES: ReadonlySet<FiscalCategory> = new Set(["rates"]);

/** "RATE_10Y_TREASURY" → "10Y Treasury" (strip worker prefix, title-case). */
export function fiscalSeriesLabel(seriesId: string, prefix: string): string {
  const stripped = seriesId.startsWith(prefix)
    ? seriesId.slice(prefix.length)
    : seriesId;
  return stripped
    .split("_")
    .filter(Boolean)
    .map((word) =>
      /^\d/.test(word) || word.length <= 2
        ? word.toUpperCase()
        : word.charAt(0).toUpperCase() + word.slice(1).toLowerCase(),
    )
    .join(" ");
}

export interface FiscalOptionInput {
  series: FiscalSeries[];
  category: FiscalCategory;
  prefix: string;
  colors: ChartColors;
}

export function buildHcMacroFiscalOption({
  series,
  category,
  prefix,
  colors,
}: FiscalOptionInput): Options {
  const percent = PERCENT_CATEGORIES.has(category);
  const formatValue = (value: number): string =>
    percent ? `${formatNumber(value)}%` : formatCompact(value);

  const lineSeries: SeriesLineOptions[] = series.map((s, i) => ({
    type: "line",
    id: s.series_id,
    name: fiscalSeriesLabel(s.series_id, prefix),
    data: s.points.map((p) => [dateToUtcMs(p.obs_date), p.value]),
    color: colors.categories[i % colors.categories.length],
    lineWidth: 1.6,
    marker: { enabled: false },
    // Weekly/monthly observations gap widely; keep runs connected.
    gapSize: 0,
  }));

  return {
    chart: { type: "line" },
    legend: { enabled: true },
    rangeSelector: { enabled: false },
    navigator: { enabled: true },
    scrollbar: { enabled: true },
    xAxis: {
      type: "datetime",
      ordinal: false,
      crosshair: { width: 1, color: colors.grid },
    },
    yAxis: {
      opposite: true,
      labels: {
        formatter() {
          return formatValue(this.value as number);
        },
      },
    },
    tooltip: {
      shared: true,
      split: false,
      formatter() {
        const points = this.points ?? [];
        const rows = points
          .map(
            (p) =>
              `<span style="color:${p.color}">●</span> ${p.series.name}: <b>${formatValue(
                p.y as number,
              )}</b>`,
          )
          .join("<br/>");
        return `${formatTimestampDate(this.x)}<br/>${rows}`;
      },
    },
    series: lineSeries,
  };
}
