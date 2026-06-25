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
  fetchStockHistory,
  fetchStockQuote,
  isRangePreset,
  type HistoryBar,
  type RangePreset,
  type StockAnalysis,
  type StockQuote,
} from "@/lib/api/client";
import { buildHcBellCurveOption } from "@/lib/charts/hc/stats-bellcurve";
import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { StockChart } from "@/components/charts/StockChart";
import { AddToPortfolio } from "@/components/stocks/AddToPortfolio";
import { HoldersTab } from "@/components/stocks/HoldersTab";
import { NewsPanel } from "@/components/stocks/NewsPanel";
import { useLiveTicks } from "@/lib/livefeed/useLiveTicks";
import { Card, KpiTile, StatRow, valueTone } from "@/components/ui/panels";
import {
  STOCK_DATA_STALE_TIME_MS,
  STOCK_ROLLING_WINDOW,
  stockQueryKeys,
} from "@/lib/stocks/queries";

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

  const quote = useQuery({
    queryKey: stockQueryKeys.quote(ticker),
    queryFn: ({ signal }) => fetchStockQuote(ticker, signal),
    staleTime: STOCK_DATA_STALE_TIME_MS,
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
  });

  const { data, error, isPending, isFetching, isPlaceholderData, refetch } =
    useQuery({
    queryKey: stockQueryKeys.analysis(ticker, range, STOCK_ROLLING_WINDOW),
    queryFn: ({ signal }) =>
      fetchStockAnalysis(
        ticker,
        { range, window: STOCK_ROLLING_WINDOW },
        signal,
      ),
    staleTime: STOCK_DATA_STALE_TIME_MS,
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
    });

  // Full daily history, NOT keyed on range: the native StockChart zooms
  // client-side over the whole window, so changing the range preset must not
  // refetch bars (only the `analysis` KPIs above are range-scoped).
  const history = useQuery({
    queryKey: stockQueryKeys.historyFull(ticker),
    queryFn: ({ signal }) => fetchStockHistory(ticker, 2520, signal),
    staleTime: STOCK_DATA_STALE_TIME_MS,
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
    const fastHeader = data?.header ?? quote.data;
    if (fastHeader) {
      return (
        <div className="mx-auto flex max-w-[1360px] flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
          <StockHeaderBar header={fastHeader} />
          <AnalysisBodySkeleton />
        </div>
      );
    }
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
        historyBars={history.data?.bars ?? []}
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
  const [tab, setTab] = useState<"analysis" | "holders">("analysis");

  const volatilityOption = useMemo(
    () =>
      buildHcRollingOption(data.rolling_volatility, "Volatility", colors, {
        yPercent: true,
        yTitle: "Annualized",
      }),
    [data.rolling_volatility, colors],
  );
  const betaOption = useMemo(
    () =>
      buildHcRollingOption(data.rolling_beta, "Beta", colors, {
        yTitle: `vs ${params.benchmark}`,
      }),
    [data.rolling_beta, colors, params.benchmark],
  );
  const correlationOption = useMemo(
    () =>
      buildHcRollingOption(data.rolling_correlation, "Correlation", colors, {
        yMin: -1,
        yMax: 1,
        yTitle: `vs ${params.benchmark}`,
      }),
    [data.rolling_correlation, colors, params.benchmark],
  );
  // Fitted-normal bell curve of the daily-return distribution (mean/σ derived
  // from the histogram by the shared builder), matching Stocks.dc.html.
  const distributionOption = useMemo(
    () => buildHcBellCurveOption(data.histogram, stats.var_95, colors),
    [data.histogram, stats.var_95, colors],
  );

  return (
    <div className="mx-auto flex max-w-[1360px] flex-col px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <StockHeaderBar header={header} />

      {/* ── Tab bar (Analysis | Holders) ── */}
      <div className="mb-px flex gap-px border-b border-border" role="tablist">
        {(["analysis", "holders"] as const).map((id) => (
          <button
            key={id}
            type="button"
            role="tab"
            aria-selected={tab === id}
            onClick={() => setTab(id)}
            className={`px-4 py-2 text-[13px] font-semibold capitalize transition-colors ${
              tab === id
                ? "border-b-2 border-b-accent text-text-primary"
                : "border-b-2 border-b-transparent text-text-secondary hover:text-text-primary"
            }`}
          >
            {id}
          </button>
        ))}
      </div>

      {tab === "holders" ? (
        <div className="mt-px">
          <HoldersTab ticker={header.ticker} />
        </div>
      ) : (
      <>
      {/* ── Interactive chart (native Highstock + livefeed) ── */}
      <div className="mb-px">
        <StockChart
          symbol={header.ticker}
          bars={historyBars}
          initialRange={range}
          onRangeChange={onRangeChange}
          className="w-full aspect-[16/10] min-h-[380px] max-h-[70vh]"
          isEmpty={historyBars.length === 0}
          emptyMessage="No price history in the synced window."
        />
      </div>

      {/* ── KPI tiles (Carbon gray-gap grid) ── */}
      <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile
          label="Ann. Volatility"
          value={formatPercent(stats.annualized_volatility)}
          tip="Annualized standard deviation of daily returns — higher means larger price swings."
        />
        <KpiTile
          label={`Beta · ${params.benchmark}`}
          value={formatNumber(stats.beta)}
          tip={`Sensitivity to ${params.benchmark}: 1.0 moves in line, >1 amplifies, <1 dampens.`}
        />
        <KpiTile
          label={`Corr · ${params.benchmark}`}
          value={formatNumber(stats.correlation)}
          tip={`Correlation of daily returns with ${params.benchmark} (−1 to +1).`}
        />
        <KpiTile
          label={`Total Return · ${range}`}
          value={formatPercent(stats.total_return, 2, { signed: true })}
          tone={valueTone(stats.total_return)}
          tip="Cumulative price return over the selected range."
        />
        <KpiTile
          label="Max Drawdown"
          value={formatPercent(stats.max_drawdown.depth)}
          tone="text-loss"
          tip="Largest peak-to-trough decline over the range."
        />
        <KpiTile
          label="VaR 95 (1d)"
          value={formatPercent(stats.var_95)}
          tip="Value at Risk: the daily loss not expected to be exceeded 95% of the time."
        />
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
          <HighchartsChart options={distributionOption} className="h-[280px] w-full" />
        </Card>

        <Card title="Statistics">
          <dl>
            <StatRow
              label="Annualized Volatility"
              value={formatPercent(stats.annualized_volatility)}
              tip="Annualized standard deviation of daily returns — higher means larger price swings."
            />
            <StatRow
              label="VaR 95 (1d)"
              value={formatPercent(stats.var_95)}
              tip="The daily loss not expected to be exceeded 95% of the time."
            />
            <StatRow
              label="VaR 99 (1d)"
              value={formatPercent(stats.var_99)}
              tip="The daily loss not expected to be exceeded 99% of the time."
            />
            <StatRow
              label="CVaR 95 (1d)"
              value={formatPercent(stats.cvar_95)}
              tip="Expected loss on the worst 5% of days (the average tail beyond VaR 95)."
            />
            <StatRow
              label="Total Return"
              value={formatPercent(stats.total_return, 2, { signed: true })}
              tone={valueTone(stats.total_return)}
            />
            <StatRow
              label={`Beta vs ${params.benchmark}`}
              value={formatNumber(stats.beta)}
              tip={`Sensitivity to ${params.benchmark}: 1.0 moves in line, >1 amplifies, <1 dampens.`}
            />
            <StatRow
              label={`Correlation vs ${params.benchmark}`}
              value={formatNumber(stats.correlation)}
              tip={`Correlation of daily returns with ${params.benchmark} (−1 to +1).`}
            />
            <StatRow
              label="Max Drawdown"
              value={formatPercent(stats.max_drawdown.depth)}
              tone="text-loss"
              detail={`${formatDate(stats.max_drawdown.peak_date)} → ${formatDate(stats.max_drawdown.trough_date)}`}
              tip="Largest peak-to-trough decline over the range."
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
      </>
      )}
    </div>
  );
}

function StockHeaderBar({ header }: { header: StockQuote }) {
  const { ticks, status: feedStatus } = useLiveTicks([header.ticker]);
  const live = ticks[header.ticker];
  const shownLast = live?.price ?? header.last_close;
  // Baseline do live = header.last_close (ultimo close do banco): durante o
  // pregao e o close de ontem -> variacao de HOJE. Sem tick, EOD do payload.
  const shownChange = live ? shownLast - header.last_close : header.change;
  const shownChangePct =
    live && header.last_close > 0
      ? shownLast / header.last_close - 1
      : header.change_pct;

  const changeTone =
    shownChange > 0
      ? "text-gain"
      : shownChange < 0
        ? "text-loss"
        : "text-neutral-value";

  return (
    <div className="mb-[18px] flex flex-wrap items-start justify-between gap-4">
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
          {feedStatus === "live" && live ? (
            <span className="inline-flex items-center gap-1.5 border border-border bg-field px-2 py-[3px] text-[11px] text-text-muted">
              <span className="h-[7px] w-[7px] rounded-full bg-gain animate-pulse" />
              <span className="font-bold text-gain">LIVE</span>
            </span>
          ) : (
            <span className="border border-border bg-field px-[7px] py-[2px] text-[10.5px] text-text-muted">
              EOD · {formatDate(header.as_of)}
            </span>
          )}
        </div>
      </div>
      <AddToPortfolio ticker={header.ticker} price={shownLast} variant="button" />
    </div>
  );
}

/* ── Presentational helpers ───────────────────────────────────────────────── */

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

function AnalysisBodySkeleton() {
  return (
    <div
      aria-busy="true"
      aria-label="Loading analysis details"
      className="animate-pulse"
    >
      <div className="mb-px h-9 border-b border-border bg-surface-2" />
      <div className="mb-px h-[420px] border border-border bg-surface-2" />
      <div className="mb-px grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        {Array.from({ length: 6 }, (_, i) => (
          <div key={i} className="h-[72px] bg-surface-2" />
        ))}
      </div>
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
