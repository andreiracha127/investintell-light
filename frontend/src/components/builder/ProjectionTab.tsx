"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel } from "@/components/screener/shared";
import { KpiTile } from "@/components/ui/panels";
import {
  postPortfolioMonteCarlo,
  type MonteCarloStatistic,
  type OptimizeResponse,
  type PortfolioMonteCarloRequest,
  type PortfolioMonteCarloResponse,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import {
  buildHcBuilderProjectionLinesOption,
  buildHcBuilderProjectionOption,
  type ProjectionUnit,
} from "@/lib/charts/hc/builder-projection";
import { formatNumber, formatPercent } from "@/lib/format";

import { buildActiveWeights } from "./activeWeights";
import { ChartCard, TabSkeleton } from "./tabShared";

/** Plain-language label, axis title and chart heading per projected statistic. */
const STATISTICS: Array<{
  key: MonteCarloStatistic;
  label: string;
  axisTitle: string;
  chartTitle: string;
}> = [
  {
    key: "return",
    label: "Return",
    axisTitle: "Projected outcome",
    chartTitle: "Projected return — range of outcomes",
  },
  {
    key: "max_drawdown",
    label: "Worst drop",
    axisTitle: "Projected outcome",
    chartTitle: "Projected worst drop — range of outcomes",
  },
  {
    key: "sharpe",
    label: "Sharpe",
    axisTitle: "Projected Sharpe",
    chartTitle: "Projected Sharpe — range of outcomes",
  },
];

function statMeta(statistic: MonteCarloStatistic) {
  return STATISTICS.find((s) => s.key === statistic) ?? STATISTICS[0];
}

function unitFor(statistic: MonteCarloStatistic): ProjectionUnit {
  return statistic === "sharpe" ? "unitless" : "fraction";
}

export function ProjectionTab({
  result,
  colors,
}: {
  result: OptimizeResponse;
  colors: ChartColors | null;
}) {
  const activeWeights = useMemo(
    () => buildActiveWeights(result.weights),
    [result.weights],
  );
  const positions = useMemo(
    () =>
      activeWeights.positions.map((weight) => ({
        asset: weight.asset,
        weight: weight.weight,
      })),
    [activeWeights.positions],
  );

  const mutation = useMutation({
    mutationFn: (body: PortfolioMonteCarloRequest) =>
      postPortfolioMonteCarlo(body),
  });

  const run = (statistic: MonteCarloStatistic) => {
    mutation.mutate({
      positions,
      statistic,
      n_simulations: 10000,
      risk_free_rate: 0.04,
    });
  };

  const firedRef = useRef(false);
  useEffect(() => {
    if (firedRef.current || !activeWeights.isValid) return;
    firedRef.current = true;
    run("return");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeWeights.isValid]);

  const activeStatistic = mutation.variables?.statistic ?? "return";

  return (
    <div className="flex flex-col gap-px">
      <div className="ix-pad flex flex-wrap items-center justify-end gap-3 border border-border bg-surface-2">
        <div className="flex items-stretch border border-border-strong">
          {STATISTICS.map(({ key, label }) => (
            <button
              key={key}
              type="button"
              onClick={() => run(key)}
              aria-pressed={activeStatistic === key}
              disabled={mutation.isPending || !activeWeights.isValid}
              className={`h-[30px] px-3.5 text-[11px] font-bold uppercase tracking-[0.04em] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                activeStatistic === key
                  ? "bg-accent text-on-accent"
                  : "bg-field text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {!activeWeights.isValid ? (
        <ErrorPanel
          title="Cannot run projection"
          message="At least two active positions above the weight floor are required."
          onRetry={() => undefined}
        />
      ) : mutation.isIdle || mutation.isPending ? (
        <TabSkeleton label="Running Monte Carlo projection" />
      ) : mutation.isError ? (
        <ErrorPanel
          title="Projection failed"
          message={mutation.error.message}
          onRetry={() => run(activeStatistic)}
        />
      ) : (
        <ProjectionBody
          data={mutation.data}
          statistic={activeStatistic}
          colors={colors}
        />
      )}
    </div>
  );
}

function ProjectionBody({
  data,
  statistic,
  colors,
}: {
  data: PortfolioMonteCarloResponse;
  statistic: MonteCarloStatistic;
  colors: ChartColors | null;
}) {
  const unit = unitFor(statistic);
  const meta = statMeta(statistic);
  // Sharpe's per-horizon band narrows by design (a longer simulated track
  // record makes the risk-adjusted-return estimate more reliable, not less),
  // so a widening shaded cone would misrepresent it — use classic
  // one-line-per-percentile instead. Return / Worst drop keep the shaded cone,
  // which does widen with the horizon.
  const buildOption =
    statistic === "sharpe"
      ? buildHcBuilderProjectionLinesOption
      : buildHcBuilderProjectionOption;
  const coneOption = colors
    ? buildOption(data.confidence_bars, unit, colors, meta.axisTitle)
    : null;
  const last = data.confidence_bars[data.confidence_bars.length - 1] ?? null;
  const formatValue = (value: number) =>
    unit === "fraction"
      ? formatPercent(value, 1, { signed: true })
      : formatNumber(value, 2);

  return (
    <div className="flex flex-col gap-px">
      {data.degraded && (
        <p className="ix-fs m-0 border-l-[3px] border-loss bg-surface-2 px-2.5 py-1.5 text-loss">
          {data.degraded_reason ?? "Projection degraded."}
        </p>
      )}

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
        {last && (
          <>
            <KpiTile
              label="Median outcome"
              value={formatValue(last.pct_50)}
              detail={`${last.horizon} ahead`}
              tone="text-accent"
            />
            <KpiTile
              label="Likely range"
              value={`${formatValue(last.pct_5)} … ${formatValue(last.pct_95)}`}
              detail="5th–95th percentile"
            />
          </>
        )}
        <KpiTile
          label="History rank"
          value={
            data.historical_percentile_rank !== null
              ? `Percentile ${formatNumber(data.historical_percentile_rank, 0)}`
              : "—"
          }
          detail="realized vs. simulated"
        />
      </div>

      <ChartCard title={meta.chartTitle}>
        {coneOption ? (
          <HighchartsChart
            options={coneOption}
            className="h-[340px] w-full"
            isEmpty={data.confidence_bars.length === 0}
            emptyMessage="No projection horizons returned."
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
