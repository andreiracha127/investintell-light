"use client";

/**
 * Stock Analysis page content — fetches the single render-ready payload from
 * `GET /stocks/{ticker}/analysis` via TanStack Query and draws it. The
 * frontend computes NO finance; every number comes from the backend.
 */
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  fetchStockAnalysis,
  isRangePreset,
  RANGE_PRESETS,
  type RangePreset,
  type StockAnalysis,
} from "@/lib/api/client";
import { buildCumulativeOption } from "@/lib/charts/cumulative";
import { buildHistogramOption } from "@/lib/charts/histogram";
import { buildPriceOption } from "@/lib/charts/price";
import { buildRollingOption } from "@/lib/charts/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import {
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { EChart } from "@/components/charts/EChart";

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

  const { data, error, isPending, refetch } = useQuery({
    queryKey: ["analysis", ticker, range, ROLLING_WINDOW],
    queryFn: ({ signal }) =>
      fetchStockAnalysis(ticker, { range, window: ROLLING_WINDOW }, signal),
    staleTime: 60 * 60 * 1000, // EOD data updates once per day; 1h prevents pointless refetches on range toggling
    retry: (failureCount, err) =>
      !(err instanceof ApiError && err.status >= 400 && err.status < 500) &&
      failureCount < 2,
  });

  const selectRange = (next: RangePreset) => {
    setRange(next);
    router.replace(`/stocks/${encodeURIComponent(ticker)}?range=${next}`, {
      scroll: false,
    });
  };

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
          className="mt-4 px-4 py-1.5 rounded-[6px] bg-surface-3 border border-border text-sm text-text-primary hover:border-accent-muted transition-colors"
        >
          Retry
        </button>
      </StatePanel>
    );
  }

  if (isPending || !data || !colors) {
    return <LoadingSkeleton />;
  }

  return <AnalysisContent data={data} colors={colors} range={range} onRangeChange={selectRange} />;
}

/* ── Loaded content ───────────────────────────────────────────────────────── */

function AnalysisContent({
  data,
  colors,
  range,
  onRangeChange,
}: {
  data: StockAnalysis;
  colors: ChartColors;
  range: RangePreset;
  onRangeChange: (range: RangePreset) => void;
}) {
  const { header, params, stats } = data;

  const priceOption = useMemo(
    () => buildPriceOption(data.candles, colors),
    [data.candles, colors],
  );
  const cumulativeOption = useMemo(
    () =>
      buildCumulativeOption(
        data.cumulative_returns,
        header.ticker,
        params.benchmark,
        colors,
      ),
    [data.cumulative_returns, header.ticker, params.benchmark, colors],
  );
  const volatilityOption = useMemo(
    () =>
      buildRollingOption(data.rolling_volatility, "Volatility", colors, {
        yPercent: true,
      }),
    [data.rolling_volatility, colors],
  );
  const betaOption = useMemo(
    () => buildRollingOption(data.rolling_beta, "Beta", colors),
    [data.rolling_beta, colors],
  );
  const correlationOption = useMemo(
    () =>
      buildRollingOption(data.rolling_correlation, "Correlation", colors, {
        yMin: -1,
        yMax: 1,
      }),
    [data.rolling_correlation, colors],
  );
  const histogramOption = useMemo(
    () => buildHistogramOption(data.histogram, colors),
    [data.histogram, colors],
  );

  const changeTone =
    header.change > 0
      ? "text-gain"
      : header.change < 0
        ? "text-loss"
        : "text-neutral-value";

  return (
    <div className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5">
      {/* ── Header row ── */}
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <div className="flex items-baseline gap-3">
            <h1 className="text-2xl font-bold tracking-tight text-text-primary">
              {header.ticker}
            </h1>
            {header.name && (
              <span className="text-sm text-text-secondary">{header.name}</span>
            )}
          </div>
          <div className="mt-1 flex items-baseline gap-3">
            <span className="tabular-nums text-[28px] font-bold text-text-primary">
              {formatCurrency(header.last_close)}
            </span>
            <span className={`tabular-nums text-[15px] font-semibold ${changeTone}`}>
              {formatCurrency(header.change, { signed: true })}{" "}
              ({formatPercent(header.change_pct, 2, { signed: true })})
            </span>
            <span className="px-2 py-0.5 rounded-[5px] bg-surface-2 border border-border text-[11px] text-text-secondary">
              EOD · {formatDate(header.as_of)}
            </span>
          </div>
        </div>

        {/* ── Range switcher ── */}
        <div
          role="group"
          aria-label="Date range"
          className="flex rounded-[7px] border border-border bg-surface-1 p-0.5"
        >
          {RANGE_PRESETS.map((preset) => (
            <button
              key={preset}
              type="button"
              onClick={() => onRangeChange(preset)}
              aria-pressed={preset === range}
              className={`px-3 py-1 rounded-[5px] text-[12px] font-medium transition-colors ${
                preset === range
                  ? "bg-surface-3 text-accent"
                  : "text-text-secondary hover:text-text-primary"
              }`}
            >
              {preset}
            </button>
          ))}
        </div>
      </div>

      {/* ── Price chart (candles + volume) ── */}
      <Card title="Price">
        <EChart option={priceOption} className="h-[420px] w-full" />
      </Card>

      {/* ── Cumulative returns vs benchmark ── */}
      <Card title={`Cumulative Return vs ${params.benchmark}`}>
        <EChart option={cumulativeOption} className="h-[300px] w-full" />
      </Card>

      {/* ── Rolling row ── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <Card title={`Rolling Volatility (${params.window}d)`}>
          <EChart option={volatilityOption} className="h-[200px] w-full" />
        </Card>
        <Card title={`Rolling Beta (${params.window}d)`}>
          <EChart option={betaOption} className="h-[200px] w-full" />
        </Card>
        <Card title={`Rolling Correlation (${params.window}d)`}>
          <EChart option={correlationOption} className="h-[200px] w-full" />
        </Card>
      </div>

      {/* ── Distribution + statistics ── */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <Card title="Daily Return Distribution">
          <EChart option={histogramOption} className="h-[280px] w-full" />
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
              tone={signTone(stats.total_return)}
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
    </div>
  );
}

function signTone(value: number): string {
  if (value > 0) return "text-gain";
  if (value < 0) return "text-loss";
  return "text-neutral-value";
}

/* ── Presentational helpers ───────────────────────────────────────────────── */

function Card({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="bg-surface-2 border border-border rounded-xl p-4">
      <h2 className="text-[11px] font-semibold tracking-[0.06em] uppercase text-text-muted mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function StatRow({
  label,
  value,
  tone = "text-text-primary",
  detail,
}: {
  label: string;
  value: string;
  tone?: string;
  detail?: string;
}) {
  return (
    <div className="flex items-baseline justify-between py-2 border-b border-border last:border-b-0">
      <dt className="text-[13px] text-text-secondary">{label}</dt>
      <dd className="text-right">
        <span className={`tabular-nums text-[13px] font-semibold ${tone}`}>
          {value}
        </span>
        {detail && (
          <span className="block tabular-nums text-[11px] text-text-muted">
            {detail}
          </span>
        )}
      </dd>
    </div>
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
      <div className="bg-surface-2 border border-border rounded-xl px-10 py-8 max-w-[520px] w-full text-center">
        <h1 className="text-lg font-bold text-text-primary mb-3">{title}</h1>
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
      className="px-6 py-5 max-w-[1400px] mx-auto flex flex-col gap-5 animate-pulse"
    >
      <div className="h-16 w-[320px] rounded-xl bg-surface-2" />
      <div className="h-[420px] rounded-xl bg-surface-2" />
      <div className="h-[300px] rounded-xl bg-surface-2" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        <div className="h-[200px] rounded-xl bg-surface-2" />
        <div className="h-[200px] rounded-xl bg-surface-2" />
        <div className="h-[200px] rounded-xl bg-surface-2" />
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        <div className="h-[280px] rounded-xl bg-surface-2" />
        <div className="h-[280px] rounded-xl bg-surface-2" />
      </div>
    </div>
  );
}
