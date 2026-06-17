"use client";

/**
 * Stock Analysis page content — fetches the single render-ready payload from
 * `GET /stocks/{ticker}/analysis` via TanStack Query and draws it. The
 * frontend computes NO finance; every number comes from the backend.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import {
  ApiError,
  fetchStockAnalysis,
  fetchStockTimeseries,
  isRangePreset,
  stockTimeseriesToHistoryBars,
  type HistoryBar,
  type RangePreset,
  type StockAnalysis,
} from "@/lib/api/client";
import { buildHcCumulativeOption } from "@/lib/charts/hc/cumulative";
import { buildHcHistogramOption } from "@/lib/charts/hc/histogram";
import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { InteractiveChart } from "@/components/charts/InteractiveChart";
import { AddToPortfolio } from "@/components/stocks/AddToPortfolio";
import { NewsPanel } from "@/components/stocks/NewsPanel";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { Card, KpiTile, StatRow, valueTone } from "@/components/ui/panels";

/** Rolling window in trading days — fixed at the backend default for now (F7 may add a control). */
const ROLLING_WINDOW = 63;

export function StockAnalysisView({
  ticker,
  initialRange,
}: {
  ticker: string;
  initialRange: RangePreset;
}) {
  const router = useRouter();
  const [range, setRange] = useState<RangePreset>(
    isRangePreset(initialRange) ? initialRange : "1Y",
  );

  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const { data, error, isPending, isFetching, isPlaceholderData, refetch } =
    useQuery({
    queryKey: ["analysis", ticker, range, ROLLING_WINDOW],
    queryFn: ({ signal }) =>
      fetchStockAnalysis(ticker, { range, window: ROLLING_WINDOW }, signal),
    staleTime: 60 * 60 * 1000, // EOD data updates once per day; 1h prevents pointless refetches on range toggling
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
    });

  const timeseries = useQuery({
    queryKey: ["stock-timeseries", ticker, range],
    queryFn: ({ signal }) => fetchStockTimeseries(ticker, range, signal),
    staleTime: 60 * 60 * 1000,
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
  });

  const selectRange = useCallback(
    (next: RangePreset) => {
      setRange(next);
      router.replace(`/stocks/${encodeURIComponent(ticker)}?range=${next}`, {
        scroll: false,
      });
    },
    [router, ticker],
  );

  if (error) {
    if (error instanceof ApiError && error.status === 404) {
      return (
        <StatePanel title="Ticker not found">
          <p className="text-sm text-text-secondary">
            No data available for{" "}
            <span className="font-semibold text-text-primary">{ticker}</span>.
            Check the symbol and try again.
          </p>
        </StatePanel>
      );
    }
    return (
      <StatePanel title="Failed to load analysis">
        <p className="text-sm text-loss break-words">{error.message}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-4 px-4 py-1.5 bg-field border border-border-strong text-sm font-semibold text-text-primary hover:bg-layer-hover transition-colors"
        >
          Retry
        </button>
      </StatePanel>
    );
  }

  if (isPending || !data || !colors) {
    return <LoadingSkeleton />;
  }

  // Com keepPreviousData, ao trocar `range` o `data` persiste (isPending=false)
  // mas `isFetching`/`isPlaceholderData` sinalizam a atualização em curso. Um
  // leve fade no conteúdo torna isso visível sem desmontar nenhum chart.
  const isRefreshing = (isFetching && !isPending) || isPlaceholderData;

  return (
    <div
      className={
        isRefreshing ? "opacity-60 transition-opacity" : "transition-opacity"
      }
      aria-busy={isRefreshing || undefined}
    >
      <AnalysisContent
        data={data}
        colors={colors}
        range={range}
        onRangeChange={selectRange}
        historyBars={
          timeseries.data ? stockTimeseriesToHistoryBars(timeseries.data) : []
        }
      />
    </div>
  );
}

/* ── Loaded content ───────────────────────────────────────────────────────── */

function AnalysisContent({
  data,
  colors,
  range,
  onRangeChange,
  historyBars,
}: {
  data: StockAnalysis;
  colors: ChartColors;
  range: RangePreset;
  onRangeChange: (range: RangePreset) => void;
  historyBars: HistoryBar[];
}) {
  const { header, params, stats } = data;

  const cumulativeOption = useMemo(
    () =>
      buildHcCumulativeOption(
        data.cumulative_returns,
        header.ticker,
        params.benchmark,
        colors,
      ),
    [data.cumulative_returns, header.ticker, params.benchmark, colors],
  );
  const volatilityOption = useMemo(
    () =>
      buildHcRollingOption(data.rolling_volatility, "Volatility", colors, {
        yPercent: true,
      }),
    [data.rolling_volatility, colors],
  );
  const betaOption = useMemo(
    () => buildHcRollingOption(data.rolling_beta, "Beta", colors),
    [data.rolling_beta, colors],
  );
  const correlationOption = useMemo(
    () =>
      buildHcRollingOption(data.rolling_correlation, "Correlation", colors, {
        yMin: -1,
        yMax: 1,
      }),
    [data.rolling_correlation, colors],
  );
  const histogramOption = useMemo(
    () => buildHcHistogramOption(data.histogram, colors),
    [data.histogram, colors],
  );

  const { ticks, status: feedStatus } = useLiveTicks([header.ticker]);
  const live = ticks[header.ticker];
  const shownLast = live?.price ?? header.last_close;
  // Baseline do live = header.last_close (último close do banco): durante o
  // pregão é o close de ontem → variação de HOJE. Sem tick, EOD do payload.
  const shownChange = live ? shownLast - header.last_close : header.change;
  const shownChangePct =
    live && header.last_close > 0 ? shownLast / header.last_close - 1 : header.change_pct;

  const changeTone =
    shownChange > 0
      ? "text-gain"
      : shownChange < 0
        ? "text-loss"
        : "text-neutral-value";

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      {/* ── Header row ── */}
      <div className="mb-[18px] flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex flex-wrap items-baseline gap-2.5">
            <h1 className="m-0 font-serif text-[clamp(24px,4vw,30px)] font-bold tracking-[-0.01em] text-text-primary">
              {header.ticker}
            </h1>
            {header.name && (
              <span className="text-[14px] text-text-secondary">{header.name}</span>
            )}
          </div>
          <div className="mt-2 flex flex-wrap items-baseline gap-3 tabular-nums">
            <span className="text-[30px] font-bold text-text-primary">
              {formatCurrency(shownLast)}
            </span>
            <span className={`text-[15px] font-bold ${changeTone}`}>
              {formatCurrency(shownChange, { signed: true })}{" "}
              ({formatPercent(shownChangePct, 2, { signed: true })})
            </span>
            <span className="border border-border bg-field px-[7px] py-[2px] text-[10.5px] text-text-muted">
              {feedStatus === "live" && live ? (
                <span className="text-gain">● LIVE</span>
              ) : (
                <>EOD · {formatDate(header.as_of)}</>
              )}
            </span>
            <AddToPortfolio ticker={header.ticker} />
          </div>
        </div>
      </div>

      {/* ── Interactive chart (Highcharts Stock + livefeed) ── */}
      <div className="mb-px">
        <InteractiveChart
          symbol={header.ticker}
          bars={historyBars}
          range={range}
          onRangeChange={onRangeChange}
        />
      </div>

      {/* ── KPI tiles (Carbon gray-gap grid) ── */}
      <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Ann. Volatility"
          value={formatPercent(stats.annualized_volatility)}
        />
        <KpiTile
          label={`Beta · ${params.benchmark}`}
          value={formatNumber(stats.beta)}
        />
        <KpiTile
          label={`Corr · ${params.benchmark}`}
          value={formatNumber(stats.correlation)}
        />
        <KpiTile
          label={`Total Return · ${range}`}
          value={formatPercent(stats.total_return, 2, { signed: true })}
          tone={valueTone(stats.total_return)}
        />
        <KpiTile
          label="Max Drawdown"
          value={formatPercent(stats.max_drawdown.depth)}
          tone="text-loss"
        />
        <KpiTile label="VaR 95 (1d)" value={formatPercent(stats.var_95)} />
      </div>

      {/* ── Cumulative returns vs benchmark ── */}
      <div className="mb-px">
        <Card
          title={`Cumulative Return vs ${params.benchmark}`}
          actions={
            <div className="flex gap-3.5 text-[10.5px] text-text-muted">
              <ChartLegend swatch="line-accent" label={header.ticker} />
              <ChartLegend swatch="line-grey" label={params.benchmark} />
            </div>
          }
        >
          <HighchartsChart options={cumulativeOption} className="h-[300px] w-full" />
        </Card>
      </div>

      {/* ── Rolling row ── */}
      <div className="mb-px grid grid-cols-1 gap-px bg-border lg:grid-cols-3">
        <Card title={`Rolling Volatility · ${params.window}d`}>
          <HighchartsChart options={volatilityOption} className="h-[200px] w-full" />
        </Card>
        <Card title={`Rolling Beta · ${params.window}d`}>
          <HighchartsChart options={betaOption} className="h-[200px] w-full" />
        </Card>
        <Card title={`Rolling Correlation · ${params.window}d`}>
          <HighchartsChart options={correlationOption} className="h-[200px] w-full" />
        </Card>
      </div>

      {/* ── Distribution + statistics ── */}
      <div className="grid grid-cols-1 gap-px bg-border lg:grid-cols-2">
        <Card title="Daily Return Distribution">
          <HighchartsChart options={histogramOption} className="h-[280px] w-full" />
        </Card>

        <Card title="Statistics">
          <dl>
            <StatRow
              label="Annualized Volatility"
              value={formatPercent(stats.annualized_volatility)}
            />
            <StatRow label="VaR 95 (1d)" value={formatPercent(stats.var_95)} />
            <StatRow label="VaR 99 (1d)" value={formatPercent(stats.var_99)} />
            <StatRow label="CVaR 95 (1d)" value={formatPercent(stats.cvar_95)} />
            <StatRow
              label="Total Return"
              value={formatPercent(stats.total_return, 2, { signed: true })}
              tone={valueTone(stats.total_return)}
            />
            <StatRow
              label={`Beta vs ${params.benchmark}`}
              value={formatNumber(stats.beta)}
            />
            <StatRow
              label={`Correlation vs ${params.benchmark}`}
              value={formatNumber(stats.correlation)}
            />
            <StatRow
              label="Max Drawdown"
              value={formatPercent(stats.max_drawdown.depth)}
              tone="text-loss"
              detail={`${formatDate(stats.max_drawdown.peak_date)} → ${formatDate(stats.max_drawdown.trough_date)}`}
            />
            <StatRow
              label="Best Day"
              value={formatPercent(stats.best_day.value, 2, { signed: true })}
              tone="text-gain"
              detail={formatDate(stats.best_day.date)}
            />
            <StatRow
              label="Worst Day"
              value={formatPercent(stats.worst_day.value, 2, { signed: true })}
              tone="text-loss"
              detail={formatDate(stats.worst_day.date)}
            />
          </dl>
        </Card>
      </div>

      {/* ── News (decorative — hides itself on error or when empty) ── */}
      <div className="mt-px">
        <NewsPanel ticker={header.ticker} />
      </div>
    </div>
  );
}

/* ── Presentational helpers ───────────────────────────────────────────────── */

/** Small legend entry: 10×2px accent/grey line. */
function ChartLegend({
  swatch,
  label,
}: {
  swatch: "line-accent" | "line-grey";
  label: string;
}) {
  return (
    <span className="flex items-center gap-[5px]">
      {swatch === "line-accent" && <span className="h-[2px] w-[10px] bg-accent" />}
      {swatch === "line-grey" && (
        <span className="h-[2px] w-[10px] bg-[var(--color-chart-bar-mute)]" />
      )}
      {label}
    </span>
  );
}

function StatePanel({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-center justify-center min-h-full px-6 py-10">
      <div className="w-full max-w-[520px] border border-border border-l-[3px] border-l-[var(--color-loss)] bg-surface-2 px-8 py-6">
        <h1 className="mb-3 text-lg font-bold text-text-primary">{title}</h1>
        {children}
      </div>
    </div>
  );
}

function LoadingSkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading analysis"
      className="mx-auto flex max-w-[1360px] animate-pulse flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5"
    >
      <div className="mb-[18px] h-16 w-[320px] border border-border bg-surface-2" />
      <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-[72px] bg-surface-2" />
        ))}
      </div>
      <div className="mb-px h-[420px] border border-border bg-surface-2" />
      <div className="mb-px h-[300px] border border-border bg-surface-2" />
      <div className="mb-px grid grid-cols-1 gap-px bg-border lg:grid-cols-3">
        <div className="h-[200px] bg-surface-2" />
        <div className="h-[200px] bg-surface-2" />
        <div className="h-[200px] bg-surface-2" />
      </div>
      <div className="grid grid-cols-1 gap-px bg-border lg:grid-cols-2">
        <div className="h-[280px] bg-surface-2" />
        <div className="h-[280px] bg-surface-2" />
      </div>
    </div>
  );
}
