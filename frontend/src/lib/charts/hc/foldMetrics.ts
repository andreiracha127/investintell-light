/**
 * Pure option builder: per-fold metric as vertical columns (Highcharts Core).
 *
 * One column per walk-forward fold (x-axis category "F1", "F2", ...) for a
 * chosen metric. Gain/loss tinting for signed values; the global Graphite
 * theme owns axis/grid/tooltip chrome.
 */
import type { Options } from "highcharts";

import type { FoldMetrics } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { formatNumber, formatPercent } from "@/lib/format";

export type FoldMetricKey = "net_return" | "sharpe";

export function buildHcFoldMetricsOption(
  folds: FoldMetrics[],
  metric: FoldMetricKey,
  colors: ChartColors,
): Options {
  const isPercent = metric === "net_return";
  const categories = folds.map((fold) => `F${fold.fold}`);
  const data = folds.map((fold) => {
    const y = metric === "net_return" ? fold.net_return : fold.sharpe;
    return { y, color: y >= 0 ? colors.bar : colors.loss };
  });

  const formatValue = (value: number) =>
    isPercent ? formatPercent(value, 1, { signed: true }) : formatNumber(value);

  return {
    chart: { type: "column" },
    legend: { enabled: false },
    xAxis: { categories, crosshair: true, tickWidth: 0 },
    yAxis: {
      title: { text: undefined },
      labels: {
        formatter() {
          return isPercent
            ? formatPercent(this.value as number, 0)
            : formatNumber(this.value as number, 1);
        },
      },
    },
    tooltip: {
      shared: false,
      formatter() {
        return `${this.x}<br/><b>${formatValue(this.y as number)}</b>`;
      },
    },
    series: [
      {
        type: "column",
        name: metric === "net_return" ? "Net return" : "Sharpe",
        data,
        pointPadding: 0.08,
        groupPadding: 0.06,
      },
    ],
  };
}
