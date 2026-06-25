"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { XAxisOptions } from "highcharts";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel } from "@/components/screener/shared";
import { KpiTile } from "@/components/ui/panels";
import {
  postBacktestWalkForward,
  type BuilderObjective,
  type OptimizeResponse,
  type WalkForwardRequest,
  type WalkForwardResponse,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import {
  buildHcFoldMetricsOption,
  type FoldMetricKey,
} from "@/lib/charts/hc/foldMetrics";
import { buildHcNavOption } from "@/lib/charts/hc/nav";
import { formatNumber, formatPercent } from "@/lib/format";

import { ChartCard, TabSkeleton, type UsedConstraints } from "./tabShared";

const BACKTESTABLE: ReadonlySet<BuilderObjective> = new Set<BuilderObjective>([
  "min_cvar",
  "min_vol",
  "erc",
  "max_diversification",
  "equal_weight",
  "max_return_cvar",
]);

export function BacktestTab({
  result,
  objective,
  constraints,
  windowDays,
  cvarLimit,
  colors,
}: {
  result: OptimizeResponse;
  objective: BuilderObjective;
  constraints: UsedConstraints;
  windowDays: number | null;
  cvarLimit: number | null;
  colors: ChartColors | null;
}) {
  const downgraded = !BACKTESTABLE.has(objective);
  const backtestObjective: WalkForwardRequest["objective"] = downgraded
    ? "min_cvar"
    : objective;

  const body: WalkForwardRequest = useMemo(
    () => ({
      assets: result.weights.map((weight) => weight.asset),
      objective: backtestObjective,
      constraints: {
        cap: constraints.cap,
        min_weight: constraints.min_weight,
      },
      window_days: windowDays,
      n_splits: 5,
      gap: 2,
      test_size: 63,
      min_train_size: 252,
      cost_bps: 10,
      risk_free_annual: 0,
      ...(backtestObjective === "max_return_cvar" && cvarLimit != null
        ? { cvar_limit: cvarLimit }
        : {}),
    }),
    [result.weights, backtestObjective, constraints.cap, constraints.min_weight, windowDays, cvarLimit],
  );

  const mutation = useMutation({
    mutationFn: (requestBody: WalkForwardRequest) =>
      postBacktestWalkForward(requestBody),
  });

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current) return;
    firedRef.current = true;
    mutation.mutate(body);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-px">
      {downgraded && (
        <p className="ix-fs m-0 border-l-[3px] border-border-strong bg-surface-2 px-3 py-2 text-text-secondary">
          Backtest objective adjusted to{" "}
          <span className="font-bold text-text-primary">min_cvar</span>.
        </p>
      )}

      {mutation.isIdle || mutation.isPending ? (
        <TabSkeleton label="Running walk-forward backtest" />
      ) : mutation.isError ? (
        <ErrorPanel
          title="Backtest failed"
          message={mutation.error.message}
          onRetry={() => mutation.mutate(body)}
        />
      ) : (
        <BacktestBody data={mutation.data} colors={colors} />
      )}
    </div>
  );
}

function BacktestBody({
  data,
  colors,
}: {
  data: WalkForwardResponse;
  colors: ChartColors | null;
}) {
  const [metric, setMetric] = useState<FoldMetricKey>("net_return");
  const oosCurve = useMemo(() => data.oos_curve ?? [], [data.oos_curve]);
  const foldBoundaries = useMemo(
    () => data.fold_boundaries ?? [],
    [data.fold_boundaries],
  );

  const foldOption = colors
    ? buildHcFoldMetricsOption(data.folds, metric, colors)
    : null;

  const oosOption = useMemo(() => {
    if (!colors) return null;

    const base = buildHcNavOption(oosCurve, colors, { growthOf100: true });
    const plotLines = foldBoundaries.map((date) => ({
      value: dateToUtcMs(date),
      color: colors.barMute,
      width: 1,
      dashStyle: "Dash" as const,
      zIndex: 3,
    }));

    return {
      ...base,
      xAxis: {
        ...(base.xAxis as XAxisOptions),
        plotLines,
      },
    };
  }, [colors, oosCurve, foldBoundaries]);

  return (
    <div className="flex flex-col gap-px">
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Average Sharpe"
          value={formatNumber(data.mean_sharpe)}
          tip="Mean risk-adjusted return across all test periods."
          tone="text-accent"
        />
        <KpiTile
          label="Consistency"
          value={`±${formatNumber(data.std_sharpe)}`}
          tip="Standard deviation of Sharpe across periods — lower means steadier."
        />
        <KpiTile
          label="Profitable periods"
          value={`${data.positive_folds} / ${data.params.n_splits_computed}`}
        />
        <KpiTile
          label="Average turnover"
          value={formatPercent(data.mean_turnover)}
          tip="Share of the portfolio traded each re-optimization — a proxy for trading cost."
        />
      </div>

      <ChartCard
        title="Return path by test period"
        subtitle="periods"
        actions={
          <div className="flex items-stretch border border-border-strong">
            {(
              [
                ["net_return", "Net return"],
                ["sharpe", "Sharpe"],
              ] satisfies Array<[FoldMetricKey, string]>
            ).map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => setMetric(key)}
                aria-pressed={metric === key}
                className={`h-[28px] px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors ${
                  metric === key
                    ? "bg-accent text-on-accent"
                    : "bg-field text-text-secondary hover:bg-layer-hover"
                }`}
              >
                {label}
              </button>
            ))}
          </div>
        }
      >
        {foldOption ? (
          <HighchartsChart
            options={foldOption}
            className="h-[300px] w-full"
            isEmpty={data.folds.length === 0}
            emptyMessage="No folds computed - not enough history for the splits."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}

        <div className="mt-3 overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse ix-fs tabular-nums lining-nums">
            <thead>
              <tr className="bg-zebra">
                <Th align="left">Period</Th>
                <Th align="right">Sharpe</Th>
                <Th align="right">Worst-case loss</Th>
                <Th align="right">Max drawdown</Th>
                <Th align="right">Turnover</Th>
                <Th align="right">Net return</Th>
              </tr>
            </thead>
            <tbody>
              {data.folds.map((fold, index) => (
                <tr
                  key={fold.fold}
                  className={`border-b border-border ${
                    index % 2 === 1 ? "bg-zebra" : ""
                  }`}
                >
                  <td className="ix-cell px-2.5 first:pl-[var(--ix-pad)] font-bold text-accent">
                    Period {fold.fold}
                  </td>
                  <td className="ix-cell px-2.5 text-right">
                    {formatNumber(fold.sharpe)}
                  </td>
                  <td className="ix-cell px-2.5 text-right">
                    {formatPercent(fold.cvar_95)}
                  </td>
                  <td className="ix-cell px-2.5 text-right">
                    {formatPercent(fold.max_drawdown)}
                  </td>
                  <td className="ix-cell px-2.5 text-right">
                    {formatPercent(fold.turnover)}
                  </td>
                  <td className="ix-cell px-2.5 pr-[var(--ix-pad)] text-right font-bold">
                    {formatPercent(fold.net_return, 2, { signed: true })}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </ChartCard>

      <ChartCard
        title="Out-of-sample growth"
        subtitle="net of costs"
      >
        {oosOption ? (
          <HighchartsChart
            options={oosOption}
            className="h-[320px] w-full"
            isEmpty={oosCurve.length === 0}
            emptyMessage="No out-of-sample curve returned."
          />
        ) : (
          <p className="py-8 text-center text-[13px] text-text-muted">
            Preparing chart
          </p>
        )}
      </ChartCard>
    </div>
  );
}

function Th({
  align,
  children,
}: {
  align: "left" | "right";
  children: ReactNode;
}) {
  return (
    <th
      className={`whitespace-nowrap border-b border-b-border-strong px-2.5 py-[9px] ${
        align === "right" ? "text-right" : "text-left"
      } font-semibold text-text-secondary first:pl-[var(--ix-pad)] last:pr-[var(--ix-pad)]`}
    >
      {children}
    </th>
  );
}
