/**
 * Pure option builder: factor style-bias radar (Highcharts `polar`).
 *
 * Design source: Funds.dc.html — the dossier Factors tab, "Style bias ·
 * holdings-weighted z-score" panel (#ix-bias). The mockup draws a spider/radar
 * with one spoke per style factor (Value / Growth / Size / Quality / Yield, …),
 * concentric rings, an emphasized zero ring, and a single filled accent polygon
 * for the fund's z-scores.
 *
 * The mockup fell back to hand-drawn SVG only because `highcharts-more` (which
 * provides the polar `area` series) could not load offline. In the app the
 * wrapper registers `highcharts-more` globally, so this is a real polar chart.
 *
 * Consumes the same `FundFactors.style_bias` payload as `buildHcStyleBiasOption`
 * (the diverging-bar variant); nothing is recomputed here. The global Graphite
 * theme owns chrome — this builder sets only the polar pane, the symmetric
 * z-score axis, the accent-filled series, and the tooltip.
 */
import type { Options, Point } from "highcharts";

import type { FundFactors } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber } from "@/lib/format";

/** Round a magnitude up to a clean radar bound (≥ 2, integer). */
function radarBound(values: number[]): number {
  const peak = values.reduce((max, v) => Math.max(max, Math.abs(v)), 0);
  return Math.max(2, Math.ceil(peak));
}

export function buildHcFactorRadarOption(
  factors: FundFactors,
  colors: ChartColors,
): Options {
  const rows = factors.style_bias;
  const categories = rows.map((item) => item.factor);
  const zScores = rows.map((item) => item.z_score ?? 0);
  const bound = radarBound(zScores);

  return {
    chart: { polar: true, type: "area" },
    legend: { enabled: false },
    pane: { size: "82%", startAngle: 0 },
    xAxis: {
      categories,
      tickmarkPlacement: "on",
      lineWidth: 0,
      gridLineColor: colors.grid,
      labels: { style: { color: colors.textSecondary, fontSize: "10px" } },
    },
    yAxis: {
      gridLineInterpolation: "polygon",
      gridLineColor: colors.grid,
      lineWidth: 0,
      tickInterval: 1,
      min: -bound,
      max: bound,
      // Emphasize the zero ring — the neutral "no tilt" reference.
      plotLines: [
        { value: 0, color: colors.barMute, width: 1, dashStyle: "Dash" },
      ],
      labels: {
        formatter() {
          return formatNumber(this.value as number, 0);
        },
        style: { color: colors.textMuted, fontSize: "9px" },
      },
    },
    tooltip: {
      formatter(this: Point) {
        const row = rows[this.index];
        const raw =
          row?.value != null ? ` · raw ${formatNumber(row.value)}` : "";
        return `${this.x}<br/><b>z ${formatNumber(
          this.y as number,
          2,
        )}</b>${raw}`;
      },
    },
    plotOptions: {
      area: {
        marker: { enabled: true, radius: 3 },
        states: { hover: { lineWidth: 2 } },
      },
    },
    series: [
      {
        type: "area",
        name: "Style bias",
        data: zScores,
        color: colors.accent,
        lineWidth: 1.6,
        fillOpacity: 0.22,
        pointPlacement: "on",
      },
    ],
  };
}
