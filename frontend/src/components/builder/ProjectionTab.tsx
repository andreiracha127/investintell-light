"use client";

import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useRef } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel } from "@/components/screener/shared";
import { Card, KpiTile } from "@/components/ui/panels";
import {
  postPortfolioMonteCarlo,
  type MonteCarloStatistic,
  type OptimizeResponse,
  type PortfolioMonteCarloRequest,
  type PortfolioMonteCarloResponse,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { buildHcConeOption, type ConeUnit } from "@/lib/charts/hc/cone";
import { formatNumber, formatPercent } from "@/lib/format";

import { buildActiveWeights } from "./activeWeights";
import { TabSkeleton } from "./tabShared";

const STATISTICS: Array<[MonteCarloStatistic, string]> = [
  ["return", "Return"],
  ["max_drawdown", "Max drawdown"],
  ["sharpe", "Sharpe"],
];

function unitFor(statistic: MonteCarloStatistic): ConeUnit {
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
      <Card
        title="Forward projection"
        subtitle="block-bootstrap, target weights held"
        actions={
          <div className="flex items-stretch border border-border-strong">
            {STATISTICS.map(([key, label]) => (
              <button
                key={key}
                type="button"
                onClick={() => run(key)}
                aria-pressed={activeStatistic === key}
                disabled={mutation.isPending || !activeWeights.isValid}
                className={`h-[28px] px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors disabled:cursor-not-allowed disabled:opacity-50 ${
                  activeStatistic === key
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
      </Card>
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
  const coneOption = colors
    ? buildHcConeOption(data.confidence_bars, unit, colors)
    : null;
  const last = data.confidence_bars[data.confidence_bars.length - 1] ?? null;
  const formatValue = (value: number) =>
    unit === "fraction"
      ? formatPercent(value, 1, { signed: true })
      : formatNumber(value, 2);

  return (
    <div className="flex flex-col gap-3">
      {data.degraded && (
        <p className="ix-fs m-0 border-l-[3px] border-loss bg-surface-2 px-2.5 py-1.5 text-loss">
          {data.degraded_reason ?? "Projection degraded."}
        </p>
      )}

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        {last && (
          <>
            <KpiTile
              label={`Median @ ${last.horizon}`}
              value={formatValue(last.pct_50)}
              tone="text-accent"
            />
            <KpiTile
              label={`5th–95th @ ${last.horizon}`}
              value={`${formatValue(last.pct_5)} … ${formatValue(last.pct_95)}`}
            />
          </>
        )}
        <KpiTile
          label="Historical percentile rank"
          value={
            data.historical_percentile_rank !== null
              ? `Percentile ${formatNumber(data.historical_percentile_rank, 0)}`
              : "-"
          }
          detail="realized history vs bootstrap"
        />
      </div>

      {coneOption ? (
        <HighchartsChart
          options={coneOption}
          className="h-[360px] w-full"
          isEmpty={data.confidence_bars.length === 0}
          emptyMessage="No projection horizons returned."
        />
      ) : (
        <p className="py-8 text-center text-[13px] text-text-muted">
          Preparing chart
        </p>
      )}

      <p className="ix-fs m-0 text-text-muted">
        Block-bootstrap projection from the portfolio&apos;s common history with
        target weights held; this is a distribution of scenarios, not a
        guarantee.
      </p>
    </div>
  );
}
