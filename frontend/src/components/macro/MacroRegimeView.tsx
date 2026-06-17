"use client";

import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Options } from "highcharts";

import {
  ApiError,
  fetchFundTimeseries,
  fetchMacroRegime,
  fetchPortfolioOverview,
  fetchStockTimeseries,
  postPortfolioAnalysis,
  stockTimeseriesToHistoryBars,
  type FundTimeseries,
  type MacroRegime,
  type PortfolioAnalysisRequest,
  type RangePreset,
  type StockTimeseries,
  type SymbolSearchResult,
} from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import {
  buildHcMacroPerformanceOption,
  buildHcMacroRotationOption,
} from "@/lib/charts/hc/regime";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatDate, formatNumber } from "@/lib/format";

type DatePoint = [string, number];

const PERIODS: RangePreset[] = ["1M", "6M", "1Y", "5Y", "MAX"];

const DEFAULT_ASSET: SymbolSearchResult = {
  symbol: "SPY",
  name: "SPDR S&P 500 ETF Trust",
  kind: "stock",
  instrument_id: null,
};

function StateBadge({ state }: { state: string }) {
  const isRiskOn = state === "risk_on";
  const label = isRiskOn ? "RISK-ON" : "RISK-OFF";
  const colorClasses = isRiskOn
    ? "border-gain text-gain bg-gain/10"
    : "border-loss text-loss bg-loss/10";

  return (
    <span
      aria-label={`Current regime: ${label}`}
      className={`inline-block border px-3 py-1 text-[13px] font-bold uppercase tracking-[0.08em] ${colorClasses}`}
    >
      {label}
    </span>
  );
}

function VoteChip({ label, active }: { label: string; active: boolean }) {
  const cls = active
    ? "border-loss text-loss bg-loss/10"
    : "border-border text-text-secondary bg-surface-2";
  return (
    <span
      aria-label={`${label} vote: ${active ? "active" : "inactive"}`}
      className={`inline-flex items-center gap-1.5 border px-2.5 py-1 text-[12px] font-semibold uppercase tracking-[0.06em] ${cls}`}
    >
      <span
        className={`inline-block h-1.5 w-1.5 rounded-full ${active ? "bg-loss" : "bg-text-secondary/40"}`}
      />
      {label}
    </span>
  );
}

function num(value: number | null | undefined, dp: number): string {
  return value !== null && value !== undefined ? formatNumber(value, dp) : "--";
}

function stockToDatePoints(data: StockTimeseries): DatePoint[] {
  return stockTimeseriesToHistoryBars(data).map((bar) => [
    new Date(bar.t).toISOString().slice(0, 10),
    bar.c,
  ]);
}

function fundToDatePoints(data: FundTimeseries): DatePoint[] {
  return data.series
    .filter((point) => point.length >= 2)
    .map(([date, value]) => [new Date(date).toISOString().slice(0, 10), value]);
}

function assetLabel(asset: SymbolSearchResult): string {
  return asset.symbol || asset.name || "Asset";
}

function buildPortfolioRequest(
  positions: Array<{ ticker: string; quantity: number }>,
  range: RangePreset,
  benchmark: string,
): PortfolioAnalysisRequest {
  return {
    mode: "quantities",
    range,
    benchmark,
    positions: positions.map((position) => ({
      ticker: position.ticker,
      quantity: position.quantity,
    })),
  };
}

export function MacroRegimeView() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  const [range, setRange] = useState<RangePreset>("1Y");
  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [asset, setAsset] = useState<SymbolSearchResult>(DEFAULT_ASSET);

  useEffect(() => {
    setColors(chartColors());
  }, []);

  const macroQuery = useQuery({
    queryKey: ["macro-regime"],
    queryFn: ({ signal }) => fetchMacroRegime(signal),
    staleTime: 300_000,
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  const portfolioQuery = useQuery({
    queryKey: ["portfolio-overview", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioOverview(portfolioId as number, signal),
    enabled: portfolioId !== null,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  const canAnalyzePortfolio =
    (portfolioQuery.data?.positions.length ?? 0) >= 2 && asset.symbol.length > 0;

  const portfolioAnalysisQuery = useQuery({
    queryKey: ["macro-portfolio-analysis", portfolioId, range, asset.symbol],
    queryFn: ({ signal }) =>
      postPortfolioAnalysis(
        buildPortfolioRequest(
          portfolioQuery.data?.positions ?? [],
          range,
          asset.symbol.toUpperCase(),
        ),
        signal,
      ),
    enabled: canAnalyzePortfolio,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  const assetQuery = useQuery<FundTimeseries | StockTimeseries>({
    queryKey: [
      "macro-asset-timeseries",
      asset.kind,
      asset.symbol,
      asset.instrument_id,
      range,
    ],
    queryFn: ({ signal }) =>
      asset.instrument_id
        ? fetchFundTimeseries(asset.instrument_id, range, signal)
        : fetchStockTimeseries(asset.symbol.toUpperCase(), range, signal),
    enabled: asset.symbol.length > 0,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  const rotationOption = useMemo<Options | null>(() => {
    if (!colors || !macroQuery.data?.history) return null;
    return buildHcMacroRotationOption(macroQuery.data.history, colors);
  }, [macroQuery.data, colors]);

  const assetPoints = useMemo<DatePoint[]>(() => {
    if (!assetQuery.data) return [];
    return asset.instrument_id
      ? fundToDatePoints(assetQuery.data as FundTimeseries)
      : stockToDatePoints(assetQuery.data as StockTimeseries);
  }, [asset.instrument_id, assetQuery.data]);

  const performanceOption = useMemo<Options | null>(() => {
    if (!colors || !macroQuery.data || !portfolioAnalysisQuery.data) return null;
    return buildHcMacroPerformanceOption({
      portfolio: portfolioAnalysisQuery.data.nav,
      asset: assetPoints,
      regimes: macroQuery.data.history,
      colors,
      portfolioLabel: portfolioQuery.data?.name ?? "Portfolio",
      assetLabel: assetLabel(asset),
    });
  }, [
    asset,
    assetPoints,
    colors,
    macroQuery.data,
    portfolioAnalysisQuery.data,
    portfolioQuery.data?.name,
  ]);

  if (
    macroQuery.isError &&
    macroQuery.error instanceof ApiError &&
    macroQuery.error.status === 404
  ) {
    return (
      <MacroShell>
        <PageTitle title="Macro regime" />
        <div className="border border-border bg-surface-2 ix-pad text-[13px] text-text-secondary">
          Regime data not available — the signal has not been populated yet.
        </div>
      </MacroShell>
    );
  }

  if (macroQuery.isPending) {
    return (
      <MacroShell>
        <PageTitle title="Macro regime" />
        <div aria-busy="true" aria-label="Loading regime data" className="grid gap-px">
          <div className="h-[108px] bg-surface-2 animate-pulse" />
          <div className="h-[360px] bg-surface-2 animate-pulse" />
          <div className="h-[420px] bg-surface-2 animate-pulse" />
        </div>
      </MacroShell>
    );
  }

  if (macroQuery.isError) {
    return (
      <MacroShell>
        <PageTitle title="Macro regime" />
        <ErrorPanel
          title="Failed to load regime data"
          message={macroQuery.error.message}
          onRetry={() => macroQuery.refetch()}
        />
      </MacroShell>
    );
  }

  const data = macroQuery.data as MacroRegime;
  const { signal, votes } = data;
  const distancePctDisplay =
    signal.distance_pct !== null && signal.distance_pct !== undefined
      ? `${formatNumber(signal.distance_pct, 2)} pp`
      : "--";

  return (
    <MacroShell>
      <PageTitle
        title="Macro regime"
        meta="Vote ensemble: risk-off when at least two of credit, trend and NFCI are active."
      />

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StateBadge state={data.state} />
        <span className="text-[13px] text-text-secondary tabular-nums">
          {data.last_flip
            ? `since ${formatDate(data.last_flip)} · ${data.days_in_state} days`
            : `${data.days_in_state} days in state`}
        </span>
        <span className="text-[12px] uppercase tracking-[0.06em] text-text-secondary">
          Votes {data.vote_count}/3
        </span>
        <VoteChip label="Credit" active={votes.credit} />
        <VoteChip label="Trend" active={votes.trend} />
        <VoteChip label="NFCI" active={votes.nfci} />
      </div>

      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile label="HYG/IEF ratio" value={num(signal.ratio, 3)} />
        <KpiTile label="Credit trigger" value={num(signal.p20_5y, 3)} />
        <KpiTile
          label="Distance"
          value={distancePctDisplay}
          tone={
            signal.distance_pct !== null && signal.distance_pct !== undefined
              ? valueTone(signal.distance_pct)
              : "text-text-primary"
          }
        />
        <KpiTile label="NFCI" value={num(signal.nfci, 2)} />
        <KpiTile label="As of" value={formatDate(data.as_of)} />
      </div>

      <div className="mb-4 flex flex-wrap items-end gap-3 border border-border bg-surface-1 ix-pad">
        <div className="flex flex-col gap-1">
          <span className="text-[11px] font-semibold uppercase tracking-[0.06em] text-text-secondary">
            Period
          </span>
          <div className="flex flex-wrap gap-1">
            {PERIODS.map((period) => (
              <button
                key={period}
                type="button"
                onClick={() => setRange(period)}
                className={`h-7 border px-2 text-[11px] font-semibold ${
                  range === period
                    ? "border-accent bg-accent text-text-on-accent"
                    : "border-border-strong bg-field text-text-secondary hover:text-text-primary"
                }`}
              >
                {period}
              </button>
            ))}
          </div>
        </div>
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} label="Active portfolio" />
        <label className="flex flex-col gap-1 text-[11px] font-semibold uppercase tracking-[0.06em] text-text-secondary">
          Asset
          <SymbolSearchInput
            active={assetLabel(asset)}
            placeholder="ETF, MF or stock"
            onSelect={setAsset}
            onClear={() => setAsset(DEFAULT_ASSET)}
          />
        </label>
      </div>

      <div className="grid gap-4 xl:grid-cols-[minmax(340px,0.85fr)_minmax(560px,1.35fr)]">
        {rotationOption && (
          <Card title="Regime rotation">
            <HighchartsChart options={rotationOption} className="h-[390px] w-full" />
          </Card>
        )}

        <Card title="Portfolio vs asset · regime overlay">
          {portfolioQuery.isError ? (
            <ErrorPanel
              title="Portfolio failed"
              message={portfolioQuery.error.message}
              onRetry={() => portfolioQuery.refetch()}
            />
          ) : portfolioAnalysisQuery.isError ? (
            <ErrorPanel
              title="Portfolio replay failed"
              message={portfolioAnalysisQuery.error.message}
              onRetry={() => portfolioAnalysisQuery.refetch()}
            />
          ) : assetQuery.isError ? (
            <ErrorPanel
              title="Asset history failed"
              message={assetQuery.error.message}
              onRetry={() => assetQuery.refetch()}
            />
          ) : !canAnalyzePortfolio ? (
            <div className="flex h-[420px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
              Select a portfolio with at least two positions.
            </div>
          ) : portfolioAnalysisQuery.isPending || assetQuery.isPending ? (
            <div className="h-[420px] animate-pulse bg-surface-2" />
          ) : performanceOption ? (
            <HighchartsChart options={performanceOption} className="h-[420px] w-full" />
          ) : (
            <div className="flex h-[420px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
              No aligned series for the selected period.
            </div>
          )}
        </Card>
      </div>
    </MacroShell>
  );
}

function MacroShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      {children}
    </div>
  );
}
