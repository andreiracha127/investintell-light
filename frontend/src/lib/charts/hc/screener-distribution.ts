/**
 * Pure option builder: screener metric distribution histogram — upgraded
 * "reads at a glance" variant (Highcharts Core).
 *
 * Design source: Screener.dc.html (`ensureDist`, distribution panel section).
 * Differences from the legacy `buildHcDistributionOption`:
 *   • plots REAL company counts (not normalized 0..1) with a visible
 *     "Companies" y-axis title, so the bar heights mean something;
 *   • x-axis labels are formatted by `dataType` (`%`, `$`, compact) and capped
 *     at ~5 ticks via a tickPositioner over the bin range;
 *   • bins overlapping the selected [min, max] band are filled with the accent
 *     colour; out-of-range bins use the muted grey bar (`colors.barMute`);
 *   • a rich tooltip names the bin range and its company count
 *     ("12% – 16% · 34 companies").
 *
 * The global Graphite theme owns the rest of the chrome (font, tooltip frame,
 * background). This builder is pure (no DOM) and unit-tested.
 */
import type { Options, Point } from "highcharts";

import type { Distribution } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatCompact, formatMetricValue } from "@/lib/format";

export function buildHcScreenerDistributionOption(
  distribution: Distribution,
  band: { min: number | null; max: number | null },
  dataType: string,
  colors: ChartColors,
): Options {
  const { bin_edges, counts } = distribution;

  // A bin [lo, hi] overlaps the band when its hi >= band.min AND lo <= band.max.
  // A null bound means unbounded on that side.
  const inBand = (lo: number, hi: number): boolean =>
    (band.min === null || hi >= band.min) && (band.max === null || lo <= band.max);

  // Per-point data plotted at the bin MIDPOINT on a numeric x-axis, so the
  // tickPositioner + formatter can render real values rather than ordinals.
  const data = counts.map((count, i) => {
    const lo = bin_edges[i];
    const hi = bin_edges[i + 1];
    return {
      x: (lo + hi) / 2,
      y: count,
      color: inBand(lo, hi) ? colors.accent : colors.barMute,
    };
  });

  // Bin width (for tooltip range + column pointRange). Empty dist → 0.
  const binWidth =
    bin_edges.length >= 2 ? bin_edges[1] - bin_edges[0] : 0;

  // Domain extent for the tick positioner: first/last edge.
  const lo0 = bin_edges.length > 0 ? bin_edges[0] : 0;
  const hi0 = bin_edges.length > 0 ? bin_edges[bin_edges.length - 1] : 1;

  return {
    chart: { type: "column" },
    legend: { enabled: false },
    xAxis: {
      tickWidth: 0,
      // ~5 evenly spaced ticks across the value domain.
      tickPositioner() {
        const out: number[] = [];
        for (let i = 0; i <= 4; i++) out.push(lo0 + ((hi0 - lo0) * i) / 4);
        return out;
      },
      labels: {
        formatter() {
          return formatMetricValue(this.value as number, dataType);
        },
      },
    },
    yAxis: {
      title: { text: "Companies" },
      allowDecimals: false,
    },
    tooltip: {
      // TooltipFormatterCallbackFunction has `this: Point`; on a numeric-axis
      // column chart `this.x` is the bar's midpoint value.
      formatter(this: Point) {
        const center = this.x as number;
        const half = binWidth / 2;
        const count = this.y as number;
        const range = `${formatMetricValue(center - half, dataType)} – ${formatMetricValue(center + half, dataType)}`;
        const noun = count === 1 ? "company" : "companies";
        return `<b>${range}</b><br/>${formatCompact(count)} ${noun}`;
      },
    },
    plotOptions: {
      column: {
        groupPadding: 0,
        pointPadding: 0.02,
        borderWidth: 0,
        ...(binWidth > 0 ? { pointRange: binWidth } : {}),
      },
    },
    series: [
      {
        type: "column",
        name: "Companies",
        data,
      },
    ],
  };
}
