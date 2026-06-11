"use client";

/**
 * Scenario — historical replay of a persisted portfolio over a date window.
 *
 * `POST /statistics/scenario` returns everything render-ready: stacked $
 * value series (TOTAL drawn as an accent line on top of the stack), 100%
 * weight evolution, normalized asset performance, return histogram and the
 * statistics rail. The frontend computes NO finance.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postScenario,
  type ScenarioRequest,
  type ScenarioResponse,
} from "@/lib/api/client";
import {
  buildMultiLineOption,
  buildStackedAreaOption,
  buildStackedPercentOption,
} from "@/lib/charts/stacked";
import { buildHistogramOption } from "@/lib/charts/histogram";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatCurrency, formatDate, formatPercent } from "@/lib/format";
import { EChart } from "@/components/charts/EChart";
import { Card, StatRow } from "@/components/ui/panels";
import { DateRangeInputs, defaultDateRange } from "@/components/statistics/DateRangeInputs";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { ErrorPanel, ParamsPanel, RunButton } from "@/components/statistics/ui";

export function ScenarioView() {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [{ start, end }] = useState(defaultDateRange);
  const [startDate, setStartDate] = useState(start);
  const [endDate, setEndDate] = useState(end);

  const mutation = useMutation({
    // 4xx responses surface their backend `detail` verbatim; mutations never
    // retry (TanStack default), so a 422 fails loud exactly once.
    mutationFn: (body: ScenarioRequest) => postScenario(body),
  });

  const canRun = portfolioId !== null && startDate !== "" && endDate !== "";
  const onRun = () => {
    if (!canRun || mutation.isPending) return;
    mutation.mutate({
      portfolio_id: portfolioId,
      start_date: startDate,
      end_date: endDate,
    });
  };

  return (
    <StatisticsShell>
      <ParamsPanel>
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} />
        <DateRangeInputs
          start={startDate}
          end={endDate}
          onStartChange={setStartDate}
          onEndChange={setEndDate}
        />
        <RunButton
          pending={mutation.isPending}
          disabled={!canRun}
          onClick={onRun}
        />
      </ParamsPanel>

      {mutation.isPending ? (
        <ScenarioSkeleton />
      ) : mutation.isError ? (
        <ErrorPanel title="Scenario failed" message={mutation.error.message} />
      ) : mutation.data && colors ? (
        <Results data={mutation.data} colors={colors} />
      ) : (
        <p className="ix-pad ix-fs border border-border bg-surface-2 text-text-muted">
          Pick a portfolio and a date window, then press Run to replay the
          portfolio&apos;s current holdings over that period.
        </p>
      )}
    </StatisticsShell>
  );
}

/* ── Results ──────────────────────────────────────────────────────────────── */

function Results({
  data,
  colors,
}: {
  data: ScenarioResponse;
  colors: ChartColors;
}) {
  const { params, statistics: stats } = data;

  const navOption = useMemo(() => {
    const total = data.nav_cash.find((s) => s.ticker === "TOTAL") ?? null;
    const stack = data.nav_cash.filter((s) => s.ticker !== "TOTAL");
    return buildStackedAreaOption(stack, total, colors);
  }, [data.nav_cash, colors]);
  const weightsOption = useMemo(
    () => buildStackedPercentOption(data.weights_percent, colors),
    [data.weights_percent, colors],
  );
  const performanceOption = useMemo(
    () => buildMultiLineOption(data.asset_performance, colors),
    [data.asset_performance, colors],
  );
  const histogramOption = useMemo(
    () => buildHistogramOption(data.histogram, colors),
    [data.histogram, colors],
  );

  return (
    <div className="flex flex-col gap-px">
      <div className="ix-pad flex flex-wrap items-center gap-x-4 gap-y-2 border border-border bg-surface-2 py-2">
        <p className="m-0 tabular-nums text-[12px] text-text-muted">
          {params.name} · {formatDate(params.start_date)} →{" "}
          {formatDate(params.end_date)} · Cash: {formatCurrency(params.cash)}
        </p>
        {params.frequency === "weekly" && (
          <span
            title="The window is long, so line series are weekly (W-FRI); statistics stay daily."
            className="border border-border-strong bg-field px-1.5 py-px text-[10px] text-text-muted"
          >
            Weekly series · daily statistics
          </span>
        )}
      </div>

      <div className="grid grid-cols-1 items-start gap-px bg-border xl:grid-cols-[minmax(320px,380px)_1fr]">
        {/* ── Statistics rail ── */}
        <Card title="Statistics">
          <dl>
            <StatRow label="Start Date" value={formatDate(stats.start_date)} />
            <StatRow label="End Date" value={formatDate(stats.end_date)} />
            <StatRow
              label="Starting NAV"
              value={formatCurrency(stats.start_nav)}
            />
            <StatRow label="Ending NAV" value={formatCurrency(stats.end_nav)} />
            <StatRow
              label="Max NAV"
              value={formatCurrency(stats.max_nav.value)}
              detail={formatDate(stats.max_nav.date)}
            />
            <StatRow
              label="Min NAV"
              value={formatCurrency(stats.min_nav.value)}
              detail={formatDate(stats.min_nav.date)}
            />
            <StatRow
              label="Best 1D Return"
              value={formatPercent(stats.max_return.value, 2, { signed: true })}
              tone="text-gain"
              detail={formatDate(stats.max_return.date)}
            />
            <StatRow
              label="Worst 1D Return"
              value={formatPercent(stats.min_return.value, 2, { signed: true })}
              tone="text-loss"
              detail={formatDate(stats.min_return.date)}
            />
            <StatRow
              label="Annualized Volatility"
              value={formatPercent(stats.annualized_volatility)}
            />
            <StatRow label="VaR 95 (1d)" value={formatPercent(stats.var_95)} />
            <StatRow label="VaR 99 (1d)" value={formatPercent(stats.var_99)} />
          </dl>
        </Card>

        {/* ── Charts ── */}
        <div className="flex min-w-0 flex-col gap-px">
          <Card title="Portfolio Performance" subtitle="value by holding, $">
            <EChart option={navOption} className="h-[320px] w-full" />
          </Card>
          <Card title="Asset Weighting" subtitle="share of total value">
            <EChart option={weightsOption} className="h-[280px] w-full" />
          </Card>
          <Card title="Asset Performance" subtitle="cumulative return, rebased">
            <EChart option={performanceOption} className="h-[320px] w-full" />
          </Card>
          <Card title="Return Distribution" subtitle="daily returns">
            <EChart option={histogramOption} className="h-[260px] w-full" />
          </Card>
        </div>
      </div>
    </div>
  );
}

function ScenarioSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading scenario"
      className="grid animate-pulse grid-cols-1 gap-px xl:grid-cols-[minmax(320px,380px)_1fr]"
    >
      <div className="h-[520px] bg-surface-2" />
      <div className="flex flex-col gap-px">
        <div className="h-[380px] bg-surface-2" />
        <div className="h-[340px] bg-surface-2" />
        <div className="h-[380px] bg-surface-2" />
        <div className="h-[320px] bg-surface-2" />
      </div>
    </div>
  );
}
