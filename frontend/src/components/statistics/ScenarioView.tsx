"use client";

/**
 * Scenario — historical replay of a persisted portfolio over a date window.
 *
 * `POST /statistics/scenario` returns everything render-ready: stacked $
 * value series (TOTAL drawn as an accent line on top of the stack), 100%
 * weight evolution, normalized asset performance, return histogram and the
 * statistics rail. The frontend computes NO finance.
 *
 * Design source: Statistics.dc.html — the four chart views share one panel
 * behind a tab strip (Performance / Weights / Asset return / Distribution),
 * the Distribution tab drawing a fitted-normal bell curve of daily NAV
 * returns. The statistics rail carries inline help dots and a Sharpe/Sortino
 * row beneath the risk figures.
 */
import { useMutation } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";

import {
  postScenario,
  type ScenarioRequest,
  type ScenarioResponse,
} from "@/lib/api/client";
import {
  buildHcMultiLineOption,
  buildHcStackedAreaOption,
  buildHcStackedPercentOption,
} from "@/lib/charts/hc/stacked";
import { buildHcBellCurveOption } from "@/lib/charts/hc/stats-bellcurve";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, StatRow } from "@/components/ui/panels";
import { DateRangeInputs, defaultDateRange } from "@/components/statistics/DateRangeInputs";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { StatisticsShell } from "@/components/statistics/StatisticsShell";
import { ErrorPanel, LABEL_CLASS, ParamsPanel, RunButton } from "@/components/statistics/ui";

/** Local-time ISO date (YYYY-MM-DD). */
function toIsoDate(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

/** Quick-range presets: trailing windows ending today. "All" reaches back a
 * decade so it spans any persisted portfolio's full price history. */
const QUICK_RANGES: ReadonlyArray<{ key: string; label: string; months: number }> = [
  { key: "3m", label: "3M", months: 3 },
  { key: "6m", label: "6M", months: 6 },
  { key: "all", label: "All", months: 120 },
];

/**
 * Segmented control that snaps the Scenario date window to a trailing range.
 * Design source: Statistics.dc.html — a Carbon segmented control beside the
 * Start/End inputs; selecting a preset sets End=today and Start=today−window.
 */
function QuickRange({
  onSelect,
}: {
  onSelect: (start: string, end: string) => void;
}) {
  const apply = (months: number) => {
    const end = new Date();
    const start = new Date(end);
    start.setMonth(start.getMonth() - months);
    onSelect(toIsoDate(start), toIsoDate(end));
  };
  return (
    <div className={LABEL_CLASS}>
      Quick range
      <div
        role="group"
        aria-label="Quick range"
        className="flex h-[34px] border border-border-strong"
      >
        {QUICK_RANGES.map((r, index) => (
          <button
            key={r.key}
            type="button"
            onClick={() => apply(r.months)}
            className={`h-full whitespace-nowrap bg-field px-3 text-[12.5px] font-medium text-text-secondary transition-colors hover:bg-layer-hover ${
              index > 0 ? "border-l border-border-strong" : ""
            }`}
          >
            {r.label}
          </button>
        ))}
      </div>
    </div>
  );
}

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
        <QuickRange
          onSelect={(start, end) => {
            setStartDate(start);
            setEndDate(end);
          }}
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

type ChartTab = "perf" | "weights" | "perf2" | "dist";

const CHART_TABS: ReadonlyArray<{ key: ChartTab; label: string; hint: string }> = [
  { key: "perf", label: "Performance", hint: "Stacked holding value, $ — Total drawn on top." },
  { key: "weights", label: "Weights", hint: "Each holding's share of total value." },
  { key: "perf2", label: "Asset return", hint: "Cumulative return, rebased to 100." },
  { key: "dist", label: "Distribution", hint: "Fitted normal of daily NAV returns." },
];

function Results({
  data,
  colors,
}: {
  data: ScenarioResponse;
  colors: ChartColors;
}) {
  const { params, statistics: stats } = data;
  const [tab, setTab] = useState<ChartTab>("perf");

  const navOption = useMemo(() => {
    const total = data.nav_cash.find((s) => s.ticker === "TOTAL") ?? null;
    const stack = data.nav_cash.filter((s) => s.ticker !== "TOTAL");
    return buildHcStackedAreaOption(stack, total, colors);
  }, [data.nav_cash, colors]);
  const weightsOption = useMemo(
    () => buildHcStackedPercentOption(data.weights_percent, colors),
    [data.weights_percent, colors],
  );
  const performanceOption = useMemo(
    () => buildHcMultiLineOption(data.asset_performance, colors),
    [data.asset_performance, colors],
  );
  const distributionOption = useMemo(
    () => buildHcBellCurveOption(data.histogram, stats.var_95, colors),
    [data.histogram, stats.var_95, colors],
  );

  // Holding count: nav_cash carries one series per position plus TOTAL/CASH.
  const holdCount = data.nav_cash.filter(
    (s) => s.ticker !== "TOTAL" && s.ticker !== "CASH",
  ).length;

  const option =
    tab === "perf"
      ? navOption
      : tab === "weights"
        ? weightsOption
        : tab === "perf2"
          ? performanceOption
          : distributionOption;
  const hint = CHART_TABS.find((t) => t.key === tab)!.hint;

  return (
    <div className="flex flex-col gap-px">
      <div className="ix-pad flex flex-wrap items-center gap-x-3 gap-y-2 border border-border bg-surface-2 py-2.5">
        <p className="m-0 tabular-nums text-[12px] text-text-secondary">
          {params.name} · {formatDate(params.start_date)} →{" "}
          {formatDate(params.end_date)} · Cash invested: {formatCurrency(params.cash)}
        </p>
        <span className="border border-border-strong bg-field px-1.5 py-px text-[10px] text-text-muted">
          {holdCount} holdings
        </span>
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
              tip="Standard deviation of daily returns scaled to one year (× √252)."
            />
            <StatRow
              label="VaR 95 (1d)"
              value={formatPercent(stats.var_95)}
              tip="Value at Risk — the daily loss the portfolio exceeds only 5% of the time."
            />
            <StatRow
              label="VaR 99 (1d)"
              value={formatPercent(stats.var_99)}
              tip="Value at Risk — the daily loss the portfolio exceeds only 1% of the time."
            />
            <StatRow
              label="Sharpe Ratio"
              value={formatNumber(stats.sharpe_ratio, 2)}
              tip="Annualized excess return per unit of total volatility (4% risk-free)."
            />
            <StatRow
              label="Sortino Ratio"
              value={formatNumber(stats.sortino_ratio, 2)}
              tip="Annualized excess return per unit of downside deviation (4% risk-free)."
            />
          </dl>
        </Card>

        {/* ── Tabbed chart panel ── */}
        <Card title="Charts" subtitle={hint}>
          <div
            role="tablist"
            aria-label="Scenario charts"
            className="mb-2.5 flex border-b border-border"
          >
            {CHART_TABS.map((t) => {
              const active = t.key === tab;
              return (
                <button
                  key={t.key}
                  type="button"
                  role="tab"
                  aria-selected={active}
                  onClick={() => setTab(t.key)}
                  className={`-mb-px border-0 border-b-2 bg-transparent px-3.5 py-2 text-[12.5px] transition-colors ${
                    active
                      ? "border-accent font-bold text-accent"
                      : "border-transparent text-text-muted hover:text-text-primary"
                  }`}
                >
                  {t.label}
                </button>
              );
            })}
          </div>
          <HighchartsChart options={option} className="h-[380px] w-full" />
        </Card>
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
      <div className="h-[520px] bg-surface-2" />
    </div>
  );
}
