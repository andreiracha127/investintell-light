import { describe, expect, it } from "vitest";

import type { FoldMetrics } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { buildHcFoldMetricsOption } from "@/lib/charts/hc/foldMetrics";
import { formatNumber, formatPercent } from "@/lib/format";

const FOLDS: FoldMetrics[] = [
  {
    fold: 1,
    train_size: 252,
    n_obs: 63,
    sharpe: 1.2,
    cvar_95: -0.02,
    max_drawdown: -0.05,
    turnover: 0.1,
    gross_return: 0.05,
    net_return: 0.04,
  },
  {
    fold: 2,
    train_size: 315,
    n_obs: 63,
    sharpe: -0.3,
    cvar_95: -0.03,
    max_drawdown: -0.08,
    turnover: 0.2,
    gross_return: -0.02,
    net_return: -0.03,
  },
];

function seriesData(metric: "net_return" | "sharpe") {
  const option = buildHcFoldMetricsOption(FOLDS, metric, TEST_COLORS);
  const series = option.series?.[0] as {
    data?: Array<{ y: number; color: string }>;
  };
  return series.data ?? [];
}

describe("buildHcFoldMetricsOption", () => {
  it("labels categories F1..Fn and maps one value per fold", () => {
    const option = buildHcFoldMetricsOption(FOLDS, "net_return", TEST_COLORS);

    expect((option.xAxis as { categories?: string[] }).categories).toEqual([
      "F1",
      "F2",
    ]);
    expect(seriesData("net_return").map((point) => point.y)).toEqual([
      0.04,
      -0.03,
    ]);
  });

  it("tints negative columns with the loss token", () => {
    const data = seriesData("net_return");

    expect(data[0]?.color).toBe(TEST_COLORS.bar);
    expect(data[1]?.color).toBe(TEST_COLORS.loss);
  });

  it("formats net_return y-axis labels as percent and sharpe as numbers", () => {
    const percentOption = buildHcFoldMetricsOption(
      FOLDS,
      "net_return",
      TEST_COLORS,
    );
    const percentLabels = (
      percentOption.yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;
    expect(percentLabels?.formatter?.call({ value: 0.05 })).toBe(
      formatPercent(0.05, 0),
    );

    const sharpeOption = buildHcFoldMetricsOption(FOLDS, "sharpe", TEST_COLORS);
    const sharpeLabels = (
      sharpeOption.yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;
    expect(sharpeLabels?.formatter?.call({ value: 1.5 })).toBe(
      formatNumber(1.5, 1),
    );
  });
});
