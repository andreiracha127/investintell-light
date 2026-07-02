import { describe, expect, it } from "vitest";

import type { FoldMetrics, WalkForwardResponse } from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import {
  buildHcFoldMetricsOption,
  foldPeriods,
  type FoldPeriod,
} from "@/lib/charts/hc/foldMetrics";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";

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

const PERIODS: FoldPeriod[] = [
  { fold: 1, start: "2024-01-02", end: "2024-04-01" },
  { fold: 2, start: "2024-04-01", end: "2024-07-15" },
];

function response(overrides: Partial<WalkForwardResponse> = {}): WalkForwardResponse {
  return {
    folds: FOLDS,
    params: {
      objective: "min_cvar",
      n_obs: 500,
      n_splits_computed: 2,
      gap: 2,
      test_size: 63,
      min_train_size: 252,
      cost_bps: 10,
    },
    mean_sharpe: 0.45,
    std_sharpe: 0.75,
    positive_folds: 1,
    mean_turnover: 0.15,
    oos_curve: [
      ["2024-01-02", 1],
      ["2024-07-15", 1.05],
    ],
    fold_boundaries: ["2024-01-02", "2024-04-01"],
    ...overrides,
  };
}

describe("foldPeriods", () => {
  it("derives each fold's window from boundaries; last fold closes at the curve end", () => {
    expect(foldPeriods(response())).toEqual([
      { fold: 1, start: "2024-01-02", end: "2024-04-01" },
      { fold: 2, start: "2024-04-01", end: "2024-07-15" },
    ]);
  });

  it("returns empty when boundaries are missing or disagree with the fold count", () => {
    expect(foldPeriods(response({ fold_boundaries: [] }))).toEqual([]);
    expect(foldPeriods(response({ fold_boundaries: ["2024-01-02"] }))).toEqual([]);
  });
});

describe("buildHcFoldMetricsOption", () => {
  function option(metric: "net_return" | "sharpe" = "net_return") {
    return buildHcFoldMetricsOption(FOLDS, PERIODS, metric, TEST_COLORS);
  }

  function points(metric: "net_return" | "sharpe" = "net_return") {
    const series = option(metric).series?.[0] as {
      data?: Array<{ x: number; y: number; custom: { fold: number } }>;
    };
    return series.data ?? [];
  }

  it("uses a datetime axis with a step segment per fold (start + end points)", () => {
    expect((option().xAxis as { type?: string }).type).toBe("datetime");
    const data = points();
    expect(data).toHaveLength(4);
    expect(data[0]).toMatchObject({ x: dateToUtcMs("2024-01-02"), y: 0.04 });
    expect(data[1]).toMatchObject({ x: dateToUtcMs("2024-04-01"), y: 0.04 });
    expect(data[2]).toMatchObject({ x: dateToUtcMs("2024-04-01"), y: -0.03 });
    expect(data[3]).toMatchObject({ x: dateToUtcMs("2024-07-15"), y: -0.03 });
  });

  it("renders a left-step line with loss-toned zone below zero", () => {
    const series = option().series?.[0] as {
      type?: string;
      step?: string;
      zones?: Array<{ value?: number; color?: string }>;
    };
    expect(series.type).toBe("line");
    expect(series.step).toBe("left");
    expect(series.zones?.[0]).toMatchObject({ value: 0, color: TEST_COLORS.loss });
  });

  it("marks each fold start with an x-axis plot line", () => {
    const xAxis = option().xAxis as { plotLines?: Array<{ value?: number }> };
    expect(xAxis.plotLines?.map((line) => line.value)).toEqual([
      dateToUtcMs("2024-01-02"),
      dateToUtcMs("2024-04-01"),
    ]);
  });

  it("tooltip names the test period and shows its real date window", () => {
    const tooltip = option().tooltip as {
      formatter?: (this: {
        y: number;
        point: { custom?: { fold: number; start: string; end: string } };
      }) => string;
    };
    const out = tooltip.formatter!.call({
      y: 0.04,
      point: { custom: { fold: 1, start: "2024-01-02", end: "2024-04-01" } },
    });
    expect(out).toContain("Test period 1");
    expect(out).toContain(formatDate("2024-01-02"));
    expect(out).toContain(formatDate("2024-04-01"));
    expect(out).toContain(formatPercent(0.04, 1, { signed: true }));
  });

  it("formats net_return y-axis labels as percent and sharpe as numbers", () => {
    const percentLabels = (
      option("net_return").yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;
    expect(percentLabels?.formatter?.call({ value: 0.05 })).toBe(
      formatPercent(0.05, 0),
    );

    const sharpeLabels = (
      option("sharpe").yAxis as {
        labels?: { formatter?: (this: { value: number }) => string };
      }
    ).labels;
    expect(sharpeLabels?.formatter?.call({ value: 1.5 })).toBe(formatNumber(1.5, 1));
  });

  it("skips folds without a derived period instead of inventing dates", () => {
    const series = buildHcFoldMetricsOption(
      FOLDS,
      [PERIODS[0]],
      "net_return",
      TEST_COLORS,
    ).series?.[0] as { data?: unknown[] };
    expect(series.data).toHaveLength(2);
  });
});
