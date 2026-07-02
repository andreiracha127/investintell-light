/**
 * Pure option builder: walk-forward fold metrics on a real time axis.
 *
 * Each fold's metric is drawn as a step segment spanning its ACTUAL
 * out-of-sample window (irregular calendar lengths preserved), instead of
 * anonymous "F1..Fn" categories. Fold windows are derived 1:1 from backend
 * dates: `fold_boundaries[i]` is the first OOS date of fold i+1 and the last
 * fold closes at the final `oos_curve` date. The global Graphite theme owns
 * axis/grid/tooltip chrome.
 */
import type { Options } from "highcharts";

import type { FoldMetrics, WalkForwardResponse } from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { dateToUtcMs, formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import { formatNumber, formatPercent } from "@/lib/format";

export type FoldMetricKey = "net_return" | "sharpe";

export interface FoldPeriod {
  fold: number;
  /** First out-of-sample date of the fold (ISO). */
  start: string;
  /** Last out-of-sample date covered by the fold (ISO). */
  end: string;
}

/**
 * Derive each fold's test window from the backend's dated series.
 * Returns one period per fold, in fold order; empty when the response has no
 * boundaries (not enough history) or the shapes disagree.
 */
export function foldPeriods(data: WalkForwardResponse): FoldPeriod[] {
  const boundaries = data.fold_boundaries ?? [];
  const curve = data.oos_curve ?? [];
  if (boundaries.length === 0 || boundaries.length !== data.folds.length) {
    return [];
  }
  const lastDate = curve.length > 0 ? curve[curve.length - 1][0] : null;
  return data.folds.map((fold, i) => ({
    fold: fold.fold,
    start: boundaries[i],
    end: boundaries[i + 1] ?? lastDate ?? boundaries[i],
  }));
}

export function buildHcFoldMetricsOption(
  folds: FoldMetrics[],
  periods: FoldPeriod[],
  metric: FoldMetricKey,
  colors: ChartColors,
): Options {
  const isPercent = metric === "net_return";
  const valueOf = (fold: FoldMetrics) =>
    metric === "net_return" ? fold.net_return : fold.sharpe;
  const formatValue = (value: number) =>
    isPercent ? formatPercent(value, 1, { signed: true }) : formatNumber(value);

  const periodByFold = new Map(periods.map((p) => [p.fold, p]));

  // One step segment per fold over its real OOS window: a point at the window
  // start plus a closing point at the window end (same y), so irregular fold
  // lengths are visible on the shared calendar axis.
  const data: Array<{
    x: number;
    y: number;
    custom: { fold: number; start: string; end: string };
  }> = [];
  for (const fold of folds) {
    const period = periodByFold.get(fold.fold);
    if (!period) continue;
    const y = valueOf(fold);
    const custom = { fold: fold.fold, start: period.start, end: period.end };
    data.push({ x: dateToUtcMs(period.start), y, custom });
    data.push({ x: dateToUtcMs(period.end), y, custom });
  }

  return {
    chart: { type: "line" },
    legend: { enabled: false },
    xAxis: {
      type: "datetime",
      crosshair: { width: 1, color: colors.grid },
      // Fold starts double as re-optimization markers.
      plotLines: periods.map((p) => ({
        value: dateToUtcMs(p.start),
        color: colors.grid,
        width: 1,
        dashStyle: "Dash" as const,
      })),
    },
    yAxis: {
      title: { text: undefined },
      plotLines: [
        { value: 0, color: colors.textMuted, width: 1, dashStyle: "Dash", zIndex: 2 },
      ],
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
        const custom = (
          this as unknown as {
            point: { custom?: { fold: number; start: string; end: string } };
          }
        ).point.custom;
        const window = custom
          ? `${formatTimestampDate(custom.start)} → ${formatTimestampDate(custom.end)}<br/>`
          : "";
        const label = custom ? `Test period ${custom.fold}` : "Test period";
        return `<b>${label}</b><br/>${window}${formatValue(this.y as number)}`;
      },
    },
    series: [
      {
        type: "line",
        name: metric === "net_return" ? "Net return" : "Sharpe",
        step: "left",
        data,
        color: colors.accent,
        lineWidth: 2,
        marker: { enabled: false },
        // Signed metric: paint below-zero stretches in the loss tone.
        zones: [{ value: 0, color: colors.loss }, { color: colors.accent }],
        zoneAxis: "y",
      },
    ],
  };
}
