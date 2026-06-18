/**
 * Pure option builder: fitted-normal distribution of daily NAV returns
 * (Highcharts Core / highcharts-more `areaspline`).
 *
 * Design source: Statistics.dc.html — the Scenario "Distribution" tab. The
 * mockup draws a smooth normal PDF for the sample mean/σ as an areaspline with
 * the ±1σ region shaded and Mean + VaR-95 reference lines, rather than the raw
 * return histogram.
 *
 * The live `/statistics/scenario` response exposes a `HistogramOut` (bin edges +
 * counts) and `var_95` (a POSITIVE decimal-fraction loss), but not the sample
 * mean/σ. We recover them from the histogram: mean and variance are estimated
 * from bin midpoints weighted by counts (Sheppard's correction is unnecessary
 * at this resolution). The VaR-95 plot line is drawn at `-var95` (the loss side).
 *
 * The global Graphite theme owns axis/grid/tooltip chrome; this builder sets the
 * two series (±1σ band + the PDF curve), the accent gradient fill, the percent
 * x-axis formatter, and the two reference plot lines.
 */
import type { Options, Point } from "highcharts";

import type { Histogram } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";

type Pair = [number, number];

/** Sample mean/σ of daily returns estimated from a counts histogram. */
export function momentsFromHistogram(histogram: Histogram): {
  mean: number;
  sd: number;
} {
  const { bin_edges, counts } = histogram;
  let total = 0;
  let sum = 0;
  let sumSq = 0;
  for (let i = 0; i < counts.length; i++) {
    const mid = (bin_edges[i] + bin_edges[i + 1]) / 2;
    const c = counts[i];
    total += c;
    sum += c * mid;
    sumSq += c * mid * mid;
  }
  if (total <= 0) return { mean: 0, sd: 1e-6 };
  const mean = sum / total;
  const variance = Math.max(sumSq / total - mean * mean, 0);
  return { mean, sd: Math.sqrt(variance) || 1e-6 };
}

/**
 * @param histogram  daily-return histogram (bin edges in decimal fractions)
 * @param var95      1-day VaR at 95% as a POSITIVE decimal fraction (loss)
 * @param colors     resolved Graphite tokens
 */
export function buildHcBellCurveOption(
  histogram: Histogram,
  var95: number,
  colors: ChartColors,
): Options {
  const { mean, sd } = momentsFromHistogram(histogram);

  // Sample 96 points across ±4σ; x carried in PERCENT units so the axis and
  // tooltip read naturally (0.5 = 0.5%), matching the mockup.
  const lo = mean - 4 * sd;
  const hi = mean + 4 * sd;
  const POINTS = 96;
  const step = (hi - lo) / POINTS;
  const pdf = (x: number): number =>
    Math.exp(-((x - mean) * (x - mean)) / (2 * sd * sd)) /
    (sd * Math.sqrt(2 * Math.PI));

  const curve: Pair[] = [];
  for (let i = 0; i <= POINTS; i++) {
    const x = lo + i * step;
    curve.push([+(x * 100).toFixed(4), +pdf(x).toFixed(6)]);
  }
  // ±1σ shaded sub-region of the same curve.
  const band: Pair[] = curve.filter(
    ([xPct]) => xPct >= (mean - sd) * 100 && xPct <= (mean + sd) * 100,
  );

  const meanPct = mean * 100;
  // var_95 is a positive loss fraction → the reference line sits on the loss side.
  const varPct = -var95 * 100;

  return {
    chart: { type: "areaspline", animation: false },
    legend: { enabled: false },
    xAxis: {
      title: { text: "Daily return" },
      labels: {
        formatter() {
          return formatPercent((this.value as number) / 100, 1);
        },
      },
      plotLines: [
        {
          value: meanPct,
          color: colors.textSecondary,
          width: 1,
          dashStyle: "Dash",
          zIndex: 5,
          label: {
            text: "Mean",
            style: { color: colors.textMuted, fontSize: "9px" },
            y: 12,
          },
        },
        {
          value: varPct,
          color: colors.loss,
          width: 1,
          dashStyle: "ShortDash",
          zIndex: 5,
          label: {
            text: "VaR 95",
            style: { color: colors.loss, fontSize: "9px" },
            y: 12,
          },
        },
      ],
    },
    yAxis: {
      title: { text: "Probability density" },
      labels: { enabled: false },
    },
    tooltip: {
      formatter(this: Point) {
        const z = ((this.x as number) / 100 - mean) / sd;
        return (
          `Daily return <b>${formatPercent((this.x as number) / 100, 2)}</b><br/>` +
          `z-score ${formatNumber(z, 2)} σ`
        );
      },
    },
    plotOptions: {
      areaspline: {
        marker: { enabled: false },
        states: { hover: { lineWidth: 2 } },
      },
    },
    series: [
      {
        type: "areaspline",
        name: "±1σ",
        data: band,
        color: colors.accent,
        lineWidth: 0,
        enableMouseTracking: false,
        fillOpacity: 0.18,
        zIndex: 1,
      },
      {
        type: "areaspline",
        name: "Distribution",
        data: curve,
        color: colors.accent,
        lineWidth: 2,
        fillColor: {
          linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
          stops: [
            [0, colors.accentWash],
            [1, "transparent"],
          ],
        },
        zIndex: 2,
      },
    ],
  };
}
