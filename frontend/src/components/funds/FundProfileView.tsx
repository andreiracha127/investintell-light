"use client";

/**
 * Fund dossier profile.
 *
 * The first viewport keeps the fund identity, KPI tiles, and active NAV chart.
 * The tab strip wires the P4/P5 dossier endpoints directly, while all chart
 * configuration remains in pure Highcharts builders under src/lib/charts/hc/.
 */
import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Chart } from "highcharts";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { InteractiveChart } from "@/components/charts/InteractiveChart";
import { FundLookthroughSection } from "@/components/funds/FundLookthroughSection";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import {
  Card,
  InfoDot,
  KpiTile,
  PAGE_CONTAINER_CLASS,
  StatRow,
} from "@/components/ui/panels";
import {
  fetchFundActiveShare,
  fetchFundAnalysis,
  fetchFundEntityAnalytics,
  fetchFundFactors,
  fetchFundHoldingsTop,
  fetchFundInstitutionalReveal,
  fetchFundPeers,
  fetchFundProfile,
  fetchFundRiskTimeseries,
  fetchFundStyleDrift,
  fetchFundTimeseries,
  fundTimeseriesToHistoryBars,
  type FundActiveShare,
  type FundAnalysis,
  type FundEntityAnalytics,
  type FundFactors,
  type FundHoldingsTop,
  type FundInstitutionalReveal,
  type FundPeers,
  type FundRisk,
  type FundRiskTimeseries,
  type FundStyleDrift,
  type Histogram,
  type RangePreset,
} from "@/lib/api/client";
import {
  buildHcFactorSensitivityOption,
  buildHcInsiderSentimentOption,
  buildHcInstitutionalHolderOption,
  buildHcInstitutionalOverlapOption,
  buildHcPeerBubbleOption,
  buildHcRiskSynchronizedOptions,
  buildHcStyleBiasOption,
  buildHcStyleDriftOption,
  buildHcTailRiskOption,
  type HcRiskSynchronizedPane,
} from "@/lib/charts/hc/fundDossier";
import { buildHcFactorRadarOption } from "@/lib/charts/hc/fund-radar";
import { buildHcHistogramOption } from "@/lib/charts/hc/histogram";
import { buildHcBellCurveOption } from "@/lib/charts/hc/stats-bellcurve";
import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  dossierQueryKeys,
  FUND_DOSSIER_DEFAULTS,
  FUND_DOSSIER_STALE_TIME_MS,
} from "@/lib/funds/dossierQueries";
import { visibleClassificationNote } from "@/lib/funds/classificationNote";
import {
  formatCompact,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { compactUsd, titleCase } from "@/lib/grid/holdersGridOptions";

const TYPE_TAG: Record<string, string> = {
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "Money market",
};

type TabId =
  | "performance"
  | "holdings"
  | "style"
  | "factors"
  | "peers"
  | "institutional";

const TABS: { id: TabId; label: string }[] = [
  { id: "performance", label: "Performance" },
  { id: "holdings", label: "Holdings" },
  { id: "style", label: "Style" },
  { id: "factors", label: "Factors" },
  { id: "peers", label: "Peers" },
  { id: "institutional", label: "Institutional" },
];

function pct(value: number | null | undefined, dp = 2): string {
  return value !== null && value !== undefined ? formatPercent(value, dp) : "--";
}

function num(value: number | null | undefined, dp = 2): string {
  return value !== null && value !== undefined ? formatNumber(value, dp) : "--";
}

function signedPct(value: number | null | undefined): string {
  return value !== null && value !== undefined
    ? formatPercent(value, 2, { signed: true })
    : "--";
}

function displayText(value: string | null | undefined): string | null {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function isUuidLike(value: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
    value,
  );
}

function benchmarkLabelText(value: string | null | undefined): string | null {
  const text = displayText(value);
  if (!text || isUuidLike(text)) return null;
  return text;
}

function benchmarkDisplayLabel(
  benchmarkId: string,
  activeShare: FundActiveShare | null | undefined,
  entityAnalytics: FundEntityAnalytics | null | undefined,
  fallbackLabel?: string | null,
): string {
  const selected = displayText(benchmarkId);
  if (!selected) return "none";
  return (
    benchmarkLabelText(activeShare?.benchmark_name) ??
    benchmarkLabelText(entityAnalytics?.capture.benchmark_label) ??
    benchmarkLabelText(fallbackLabel) ??
    (isUuidLike(selected) ? "resolving..." : selected)
  );
}

function proxyTicker(value: string | null | undefined): string {
  return displayText(value)?.toUpperCase() ?? "";
}

function proxyBenchmarkLabel(
  name: string | null | undefined,
  ticker: string,
): string | null {
  const label = benchmarkLabelText(name);
  if (label && ticker) return `${label} (${ticker})`;
  return label ?? (ticker || null);
}

function benchmarkMetricLabel(
  benchmarkId: string | null | undefined,
  label: string | null | undefined,
  fallbackLabel?: string,
): string {
  const resolved = benchmarkLabelText(label) ?? benchmarkLabelText(fallbackLabel);
  if (resolved && resolved !== "none" && resolved !== "resolving...") return resolved;

  const selected = displayText(benchmarkId);
  if (!selected || isUuidLike(selected)) return "--";
  return selected;
}

function money(value: number | null | undefined): string {
  return value !== null && value !== undefined ? `$${formatCompact(value)}` : "--";
}

function errorMessage(query: UseQueryResult<unknown, Error>): string | null {
  return query.isError ? query.error.message : null;
}

function toDistributionHistogram(
  distribution: FundEntityAnalytics["distribution"],
): Histogram {
  const max = Math.max(0, ...distribution.bin_counts);
  return {
    bin_edges: distribution.bin_edges,
    counts: distribution.bin_counts,
    counts_normalized:
      max > 0 ? distribution.bin_counts.map((count) => count / max) : [],
  };
}

function toSeries(
  dates: string[],
  values: number[],
): [string, number][] {
  return dates.map((date, index) => [date, values[index] ?? 0]);
}

function latestPoint(series: [string, number][]): [string, number] | null {
  return series.length > 0 ? series[series.length - 1] : null;
}

export function FundProfileView({ instrumentId }: { instrumentId: string }) {
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const [activeTab, setActiveTab] = useState<TabId>("performance");
  const [range, setRange] = useState<RangePreset>("1Y");
  const [deepOpen, setDeepOpen] = useState(false);
  const [benchmarkId, setBenchmarkId] = useState("");

  useEffect(() => {
    setActiveTab("performance");
    setRange("1Y");
    setDeepOpen(false);
    setBenchmarkId("");
  }, [instrumentId]);

  // Escape closes the Deep Analysis side panel.
  useEffect(() => {
    if (!deepOpen) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setDeepOpen(false);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [deepOpen]);

  const benchmarkQuery = benchmarkId ? { benchmark_id: benchmarkId } : {};
  const isPerformanceTab = activeTab === "performance";
  const isHoldingsTab = activeTab === "holdings";
  const isStyleTab = activeTab === "style";
  const isFactorsTab = activeTab === "factors";
  const isPeersTab = activeTab === "peers";
  const isInstitutionalTab = activeTab === "institutional";

  const profileQuery = useQuery({
    queryKey: dossierQueryKeys.profile(instrumentId),
    queryFn: ({ signal }) => fetchFundProfile(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.profile,
    retry: retryPolicy,
  });
  const resolvedBenchmark = profileQuery.data?.benchmark;
  const autoBenchmarkTicker = proxyTicker(resolvedBenchmark?.proxy_ticker);
  const autoBenchmarkLabel = proxyBenchmarkLabel(
    resolvedBenchmark?.name,
    autoBenchmarkTicker,
  );
  const autoBenchmarkInstrumentId = resolvedBenchmark?.proxy_instrument_id ?? null;

  useEffect(() => {
    if (benchmarkId || !autoBenchmarkInstrumentId) return;
    setBenchmarkId(autoBenchmarkInstrumentId);
  }, [benchmarkId, autoBenchmarkInstrumentId]);

  const timeseriesQuery = useQuery({
    queryKey: dossierQueryKeys.timeseries(instrumentId, { range }),
    queryFn: ({ signal }) => fetchFundTimeseries(instrumentId, range, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.timeseries,
    enabled: isPerformanceTab,
    retry: retryPolicy,
  });

  const analysisQuery = useQuery({
    queryKey: dossierQueryKeys.analysis(instrumentId, {
      range,
      window: FUND_DOSSIER_DEFAULTS.analysisWindow,
    }),
    queryFn: ({ signal }) =>
      fetchFundAnalysis(
        instrumentId,
        { range, window: FUND_DOSSIER_DEFAULTS.analysisWindow },
        signal,
      ),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.analysis,
    enabled: isPerformanceTab,
    retry: retryPolicy,
  });

  const holdingsTopQuery = useQuery({
    queryKey: dossierQueryKeys.holdingsTop(instrumentId, {
      limit: FUND_DOSSIER_DEFAULTS.holdingsTopLimit,
    }),
    queryFn: ({ signal }) =>
      fetchFundHoldingsTop(
        instrumentId,
        { limit: FUND_DOSSIER_DEFAULTS.holdingsTopLimit },
        signal,
      ),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["holdings-top"],
    enabled: isHoldingsTab,
    retry: retryPolicy,
  });

  const peersQuery = useQuery({
    queryKey: dossierQueryKeys.peers(instrumentId, {
      limit: FUND_DOSSIER_DEFAULTS.peersLimit,
    }),
    queryFn: ({ signal }) =>
      fetchFundPeers(
        instrumentId,
        { limit: FUND_DOSSIER_DEFAULTS.peersLimit },
        signal,
      ),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.peers,
    enabled: isPeersTab,
    retry: retryPolicy,
  });

  const factorsQuery = useQuery({
    queryKey: dossierQueryKeys.factors(instrumentId),
    queryFn: ({ signal }) => fetchFundFactors(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.factors,
    enabled: isFactorsTab,
    retry: retryPolicy,
  });

  const styleDriftQuery = useQuery({
    queryKey: dossierQueryKeys.styleDrift(instrumentId, {
      quarters: FUND_DOSSIER_DEFAULTS.styleDriftQuarters,
    }),
    queryFn: ({ signal }) =>
      fetchFundStyleDrift(
        instrumentId,
        { quarters: FUND_DOSSIER_DEFAULTS.styleDriftQuarters },
        signal,
      ),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["style-drift"],
    enabled: isStyleTab,
    retry: retryPolicy,
  });

  const riskTimeseriesQuery = useQuery({
    queryKey: dossierQueryKeys.riskTimeseries(instrumentId, benchmarkQuery),
    queryFn: ({ signal }) =>
      fetchFundRiskTimeseries(instrumentId, benchmarkQuery, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["risk-timeseries"],
    enabled: isPerformanceTab,
    retry: retryPolicy,
  });

  const entityAnalyticsQuery = useQuery({
    queryKey: dossierQueryKeys.entityAnalytics(instrumentId, {
      window: FUND_DOSSIER_DEFAULTS.entityWindow,
      ...benchmarkQuery,
    }),
    queryFn: ({ signal }) =>
      fetchFundEntityAnalytics(
        instrumentId,
        { window: FUND_DOSSIER_DEFAULTS.entityWindow, ...benchmarkQuery },
        signal,
      ),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["entity-analytics"],
    enabled: deepOpen,
    retry: retryPolicy,
  });

  const activeShareQuery = useQuery({
    queryKey: dossierQueryKeys.activeShare(instrumentId),
    queryFn: ({ signal }) => fetchFundActiveShare(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["active-share"],
    enabled: isHoldingsTab,
    retry: retryPolicy,
  });

  const institutionalRevealQuery = useQuery({
    queryKey: dossierQueryKeys.institutionalReveal(instrumentId),
    queryFn: ({ signal }) => fetchFundInstitutionalReveal(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["institutional-reveal"],
    enabled: isInstitutionalTab,
    retry: retryPolicy,
  });

  const chartBars = useMemo(
    () =>
      timeseriesQuery.data
        ? fundTimeseriesToHistoryBars(timeseriesQuery.data)
        : [],
    [timeseriesQuery.data],
  );

  const histogramOption = useMemo(() => {
    if (!colors || !analysisQuery.data) return null;
    return buildHcHistogramOption(analysisQuery.data.histogram, colors);
  }, [analysisQuery.data, colors]);

  const rollingVolatilityOption = useMemo(() => {
    if (!colors || !analysisQuery.data?.rolling_volatility.length) return null;
    return buildHcRollingOption(
      analysisQuery.data.rolling_volatility,
      "Rolling volatility",
      colors,
      { yPercent: true },
    );
  }, [analysisQuery.data, colors]);

  const rollingSharpeOption = useMemo(() => {
    if (!colors || !analysisQuery.data?.rolling_sharpe.length) return null;
    return buildHcRollingOption(
      analysisQuery.data.rolling_sharpe,
      "Rolling Sharpe",
      colors,
    );
  }, [analysisQuery.data, colors]);

  // Return distribution: fitted-normal bell with ±1σ shading and Mean / VaR-95
  // reference lines (Funds.dc.html #ix-dist). `stats.var_95` is a signed loss
  // fraction; the bell builder wants the positive magnitude.
  const distributionBellOption = useMemo(() => {
    if (!colors || !analysisQuery.data) return null;
    return buildHcBellCurveOption(
      analysisQuery.data.histogram,
      Math.abs(analysisQuery.data.stats.var_95 ?? 0),
      colors,
    );
  }, [analysisQuery.data, colors]);

  const riskSyncPanes = useMemo(() => {
    if (!colors || !riskTimeseriesQuery.data) return null;
    if (
      riskTimeseriesQuery.data.drawdown.length === 0 &&
      riskTimeseriesQuery.data.conditional_volatility.length === 0
    ) {
      return null;
    }
    return buildHcRiskSynchronizedOptions(riskTimeseriesQuery.data, colors);
  }, [riskTimeseriesQuery.data, colors]);

  const styleDriftOption = useMemo(() => {
    if (!colors || !styleDriftQuery.data) return null;
    if (styleDriftQuery.data.empty_state || styleDriftQuery.data.periods.length === 0) {
      return null;
    }
    return buildHcStyleDriftOption(styleDriftQuery.data, colors);
  }, [styleDriftQuery.data, colors]);

  const factorSensitivityOption = useMemo(() => {
    if (!colors || !factorsQuery.data?.market_sensitivities.length) return null;
    return buildHcFactorSensitivityOption(factorsQuery.data, colors);
  }, [factorsQuery.data, colors]);

  const institutionalHolderOption = useMemo(() => {
    const reveal = institutionalRevealQuery.data;
    if (!colors || !reveal || reveal.empty_state || reveal.top_holders.length === 0) {
      return null;
    }
    return buildHcInstitutionalHolderOption(reveal, colors);
  }, [institutionalRevealQuery.data, colors]);

  const institutionalOverlapOption = useMemo(() => {
    const reveal = institutionalRevealQuery.data;
    if (!colors || !reveal || reveal.empty_state || reveal.overlap.length === 0) {
      return null;
    }
    return buildHcInstitutionalOverlapOption(reveal, colors);
  }, [institutionalRevealQuery.data, colors]);

  const styleBiasOption = useMemo(() => {
    if (!colors || !factorsQuery.data?.style_bias.length) return null;
    return buildHcStyleBiasOption(factorsQuery.data, colors);
  }, [factorsQuery.data, colors]);

  // Factors tab style-bias spider/radar (Funds.dc.html #ix-bias). Needs at least
  // three spokes to read as a polygon; below that the diverging bars carry it.
  const factorRadarOption = useMemo(() => {
    if (!colors || !factorsQuery.data || factorsQuery.data.style_bias.length < 3) {
      return null;
    }
    return buildHcFactorRadarOption(factorsQuery.data, colors);
  }, [factorsQuery.data, colors]);

  const peerBubbleOption = useMemo(() => {
    if (!colors || !peersQuery.data || peersQuery.data.items.length === 0) return null;
    return buildHcPeerBubbleOption(peersQuery.data, colors);
  }, [peersQuery.data, colors]);

  const tailRiskOption = useMemo(() => {
    if (!colors || !entityAnalyticsQuery.data) return null;
    return buildHcTailRiskOption(entityAnalyticsQuery.data, colors);
  }, [entityAnalyticsQuery.data, colors]);

  const insiderOption = useMemo(() => {
    const analytics = entityAnalyticsQuery.data;
    const insider = analytics?.insider_data;
    if (!colors || !analytics || !insider?.quarters?.length) return null;
    if (insider.empty_state) return null;
    return buildHcInsiderSentimentOption(analytics, colors);
  }, [entityAnalyticsQuery.data, colors]);

  const distributionOption = useMemo(() => {
    if (!colors || !entityAnalyticsQuery.data) return null;
    const distribution = entityAnalyticsQuery.data.distribution;
    if (distribution.bin_edges.length < 2 || distribution.bin_counts.length === 0) {
      return null;
    }
    return buildHcHistogramOption(toDistributionHistogram(distribution), colors);
  }, [entityAnalyticsQuery.data, colors]);

  const deepDrawdownOption = useMemo(() => {
    if (!colors || !entityAnalyticsQuery.data) return null;
    const { dates, values } = entityAnalyticsQuery.data.drawdown;
    if (dates.length === 0) return null;
    return buildHcRollingOption(toSeries(dates, values), "Drawdown", colors, {
      yPercent: true,
      yMax: 0,
    });
  }, [entityAnalyticsQuery.data, colors]);

  if (profileQuery.isPending) {
    return (
      <div className={PAGE_CONTAINER_CLASS}>
        <div
          aria-busy="true"
          aria-label="Loading fund profile"
          className="h-[480px] animate-pulse bg-surface-2"
        />
      </div>
    );
  }

  if (profileQuery.isError) {
    return (
      <div className={PAGE_CONTAINER_CLASS}>
        <ErrorPanel
          title="Failed to load fund"
          message={profileQuery.error.message}
          onRetry={() => profileQuery.refetch()}
        />
      </div>
    );
  }

  const fund = profileQuery.data;
  const risk = fund.risk;
  const riskTone =
    risk?.return_1y != null
      ? risk.return_1y > 0
        ? "text-gain"
        : risk.return_1y < 0
          ? "text-loss"
          : "text-text-primary"
      : "text-text-primary";

  const activeBenchmarkLabel = benchmarkDisplayLabel(
    benchmarkId,
    activeShareQuery.data,
    entityAnalyticsQuery.data,
    autoBenchmarkLabel,
  );

  return (
    <div className={PAGE_CONTAINER_CLASS}>
      <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
        <div>
          <Link
            href="/funds"
            className="text-[11px] font-bold uppercase tracking-[0.08em] text-text-muted hover:text-accent"
          >
            Funds
          </Link>
          <div className="mt-1 flex flex-wrap items-baseline gap-3">
            <h1 className="ix-title m-0 text-[clamp(22px,3.5vw,28px)]">
              {fund.name}
            </h1>
            {fund.ticker && (
              <span className="text-[15px] font-bold tabular-nums text-accent">
                {fund.ticker}
              </span>
            )}
          </div>
          <div className="mb-1.5 mt-2 h-[3px] w-[34px] bg-accent" />
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            <Tag>{TYPE_TAG[fund.fund_type] ?? fund.fund_type}</Tag>
            <Tag>{fund.strategy_label}</Tag>
            {fund.asset_class && <Tag>{fund.asset_class.replace("_", " ")}</Tag>}
            {fund.is_index && <Tag>Index</Tag>}
          </div>
          <p className="mt-2 text-[12px] text-text-secondary">
            Data as of {formatDate(fund.source_calc_date)} - NAV through{" "}
            {formatDate(fund.source_nav_max_date)}
            {fund.primary_benchmark ? ` - Benchmark: ${fund.primary_benchmark}` : ""}
          </p>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={() => setDeepOpen(true)}
            className="h-[32px] border border-accent bg-accent px-3 text-[11px] font-bold uppercase tracking-[0.06em] text-on-accent transition-colors hover:bg-accent-muted"
          >
            Deep Analysis
          </button>
        </div>
      </div>

      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(150px,1fr))]">
        <KpiTile label="Net assets" value={money(fund.aum_usd)} />
        <KpiTile
          label="Expense ratio"
          value={pct(fund.expense_ratio)}
          tip="Annual fee charged by the fund, as a percent of assets."
        />
        <KpiTile label="Return 1Y" value={signedPct(risk?.return_1y)} tone={riskTone} />
        <KpiTile
          label="Volatility 1Y"
          value={pct(risk?.volatility_1y)}
          tip="Annualized standard deviation of returns — how widely the value swings over a year."
        />
        <KpiTile
          label="Sharpe 1Y"
          value={num(risk?.sharpe_1y)}
          tip="Return earned per unit of risk. Higher is better; above 1.0 is strong."
        />
        <KpiTile
          label="Exp. shortfall"
          value={pct(risk?.cvar_95_12m)}
          tip="Expected shortfall (CVaR 95): the average loss on the worst 5% of days — a more conservative tail measure than Value-at-Risk."
        />
      </div>

      <div className="mb-4 border-b border-border-strong">
        <div className="flex flex-wrap gap-1" role="tablist" aria-label="Fund dossier tabs">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              type="button"
              role="tab"
              aria-selected={activeTab === tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`h-[34px] border border-b-0 px-3 text-[11px] font-bold uppercase tracking-[0.06em] transition-colors ${
                activeTab === tab.id
                  ? "border-border-strong bg-surface-2 text-text-primary"
                  : "border-transparent bg-transparent text-text-muted hover:bg-layer-hover hover:text-text-primary"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </div>
      </div>

      {activeTab === "performance" && (
        <PerformanceTab
          chartBars={chartBars}
          fundLabel={fund.ticker ?? fund.name}
          range={range}
          onRangeChange={setRange}
          timeseriesQuery={timeseriesQuery}
          analysisQuery={analysisQuery}
          riskTimeseriesQuery={riskTimeseriesQuery}
          histogramOption={histogramOption}
          distributionBellOption={distributionBellOption}
          riskSyncPanes={riskSyncPanes}
          risk={risk}
          fundType={fund.fund_type}
          assetClass={fund.asset_class}
          rollingVolatilityOption={rollingVolatilityOption}
          rollingSharpeOption={rollingSharpeOption}
          monthlyReturns={analysisQuery.data?.monthly_returns ?? []}
        />
      )}

      {activeTab === "holdings" && (
        <HoldingsTab
          instrumentId={fund.instrument_id}
          holdingsTopQuery={holdingsTopQuery}
          activeShareQuery={activeShareQuery}
        />
      )}

      {activeTab === "style" && (
        <StyleTab
          styleDriftQuery={styleDriftQuery}
          styleDriftOption={styleDriftOption}
        />
      )}

      {activeTab === "factors" && (
        <FactorsTab
          factorsQuery={factorsQuery}
          factorSensitivityOption={factorSensitivityOption}
          styleBiasOption={styleBiasOption}
          factorRadarOption={factorRadarOption}
        />
      )}

      {activeTab === "peers" && (
        <PeersTab
          peersQuery={peersQuery}
          bubbleOption={peerBubbleOption}
        />
      )}

      {activeTab === "institutional" && (
        <InstitutionalTab
          revealQuery={institutionalRevealQuery}
          holderOption={institutionalHolderOption}
          overlapOption={institutionalOverlapOption}
        />
      )}

      {visibleClassificationNote(fund.classification_note) && (
        <p className="mt-4 text-[11px] text-text-muted">
          {visibleClassificationNote(fund.classification_note)}
        </p>
      )}

      {deepOpen && (
        <DeepAnalysisModal
          entityAnalyticsQuery={entityAnalyticsQuery}
          benchmarkId={benchmarkId}
          activeBenchmarkLabel={activeBenchmarkLabel}
          onClose={() => setDeepOpen(false)}
          tailRiskOption={tailRiskOption}
          distributionOption={distributionOption}
          drawdownOption={deepDrawdownOption}
          insiderOption={insiderOption}
        />
      )}

    </div>
  );
}

function PerformanceTab({
  chartBars,
  fundLabel,
  range,
  onRangeChange,
  timeseriesQuery,
  analysisQuery,
  riskTimeseriesQuery,
  histogramOption,
  distributionBellOption,
  riskSyncPanes,
  risk,
  fundType,
  assetClass,
  rollingVolatilityOption,
  rollingSharpeOption,
  monthlyReturns,
}: {
  chartBars: ReturnType<typeof fundTimeseriesToHistoryBars>;
  fundLabel: string;
  range: RangePreset;
  onRangeChange: (range: RangePreset) => void;
  timeseriesQuery: UseQueryResult<unknown, Error>;
  analysisQuery: UseQueryResult<FundAnalysis, Error>;
  riskTimeseriesQuery: UseQueryResult<FundRiskTimeseries, Error>;
  histogramOption: Highcharts.Options | null;
  distributionBellOption: Highcharts.Options | null;
  riskSyncPanes: HcRiskSynchronizedPane[] | null;
  risk: FundRisk | null;
  fundType: string;
  assetClass: string | null;
  rollingVolatilityOption: Highcharts.Options | null;
  rollingSharpeOption: Highcharts.Options | null;
  monthlyReturns: [string, number][];
}) {
  const isRefreshing =
    (timeseriesQuery.isFetching && !timeseriesQuery.isPending) ||
    (analysisQuery.isFetching && !analysisQuery.isPending);

  return (
    <div className="grid gap-4 lg:[grid-template-columns:minmax(0,2fr)_minmax(280px,1fr)]">
      <div className="flex flex-col gap-4">
        {chartBars.length > 0 ? (
          <div className="relative">
            {isRefreshing ? (
              <span className="absolute right-2 top-2 z-10 bg-surface px-2 py-0.5 text-[11px] text-text-muted">
                Updating…
              </span>
            ) : null}
            <div
              className={
                isRefreshing ? "opacity-60 transition-opacity" : "transition-opacity"
              }
            >
              <InteractiveChart
                symbol={fundLabel}
                bars={chartBars}
                mode="nav"
                range={range}
                onRangeChange={onRangeChange}
              />
            </div>
          </div>
        ) : (
          <Card title="NAV">
            <QueryMessage
              query={timeseriesQuery}
              emptyMessage="No NAV history in the synced window."
              loadingMessage="Loading NAV history..."
            />
          </Card>
        )}

        <ChartCard
          title="Return distribution"
          subtitle="daily"
          option={distributionBellOption ?? histogramOption}
          query={analysisQuery}
          emptyMessage="No return distribution for this window."
        />

        <SynchronizedRiskCharts
          panes={riskSyncPanes}
          query={riskTimeseriesQuery}
          emptyMessage={
            riskTimeseriesQuery.data?.empty_state?.reason ??
            "No risk timeseries available for this fund."
          }
        />

        <div className="grid gap-4 xl:grid-cols-2">
          <ChartCard
            title="Rolling volatility"
            subtitle="annualized"
            option={rollingVolatilityOption}
            query={analysisQuery}
            emptyMessage="No rolling volatility series for this window."
          />
          <ChartCard
            title="Rolling Sharpe"
            subtitle="zero risk-free rate"
            option={rollingSharpeOption}
            query={analysisQuery}
            emptyMessage="No rolling Sharpe series for this window."
          />
        </div>

        <Card title="Monthly returns">
          {monthlyReturns.length > 0 ? (
            <MonthlyReturnsTable data={monthlyReturns} />
          ) : (
            <QueryMessage
              query={analysisQuery}
              emptyMessage="No monthly returns for this window."
              loadingMessage="Loading monthly returns..."
            />
          )}
        </Card>
      </div>

      <div className="flex flex-col gap-4">
        <Card
          title="Performance stats"
          subtitle={analysisQuery.data ? analysisQuery.data.params.range : undefined}
        >
          {analysisQuery.data ? (
            <div className="grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(120px,1fr))]">
              <KpiTile
                label="Total return"
                value={signedPct(analysisQuery.data.stats.total_return)}
              />
              <KpiTile
                label="Ann. vol"
                value={pct(analysisQuery.data.stats.annualized_volatility)}
              />
              <KpiTile label="VaR 95" value={pct(analysisQuery.data.stats.var_95)} />
              <KpiTile label="CVaR 95" value={pct(analysisQuery.data.stats.cvar_95)} />
              <KpiTile
                label="Max drawdown"
                value={pct(analysisQuery.data.stats.max_drawdown.depth)}
              />
              <KpiTile
                label="Worst day"
                value={signedPct(analysisQuery.data.stats.worst_day.value)}
                detail={formatDate(analysisQuery.data.stats.worst_day.date)}
              />
            </div>
          ) : (
            <QueryMessage
              query={analysisQuery}
              emptyMessage="No performance statistics for this window."
              loadingMessage="Loading performance statistics..."
            />
          )}
        </Card>

        <Card title="Risk snapshot" subtitle={risk ? `calc ${formatDate(risk.calc_date)}` : undefined}>
          {risk ? (
            <dl className="m-0">
              <RiskRows risk={risk} fundType={fundType} assetClass={assetClass} />
            </dl>
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">
              No risk snapshot synced for this fund.
            </p>
          )}
        </Card>
      </div>
    </div>
  );
}

function HoldingsTab({
  instrumentId,
  holdingsTopQuery,
  activeShareQuery,
}: {
  instrumentId: string;
  holdingsTopQuery: UseQueryResult<FundHoldingsTop, Error>;
  activeShareQuery: UseQueryResult<FundActiveShare, Error>;
}) {
  return (
    <div className="flex flex-col gap-4">
      <Card
        title="Top holdings"
        subtitle={holdingsTopQuery.data?.report_date ? formatDate(holdingsTopQuery.data.report_date) : undefined}
      >
        {holdingsTopQuery.data ? (
          <TopHoldingsTable data={holdingsTopQuery.data} />
        ) : (
          <QueryMessage
            query={holdingsTopQuery}
            emptyMessage="No top holdings returned for this fund."
            loadingMessage="Loading top holdings..."
          />
        )}
      </Card>
      <FundLookthroughSection
        instrumentId={instrumentId}
        holdingsTop={holdingsTopQuery.data}
      />
      <ActiveSharePanel query={activeShareQuery} />
    </div>
  );
}

function TopHoldingsTable({ data }: { data: FundHoldingsTop }) {
  const holdings = data.top_holdings;
  if (holdings.length === 0) {
    return <EmptyMessage message="No top holdings returned." />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-[640px] w-full border-collapse ix-fs tabular-nums lining-nums">
        <thead>
          <tr className="bg-field">
            <Th align="right">#</Th>
            <Th>Issuer</Th>
            <Th>Sector</Th>
            <Th align="right">% of NAV</Th>
            <Th align="right">Market value</Th>
          </tr>
        </thead>
        <tbody>
          {holdings.map((holding, index) => (
            <tr
              key={holding.cusip ?? holding.isin ?? `${holding.rank}`}
              className={`border-b border-border transition-colors hover:bg-accent-wash ${
                index % 2 === 1 ? "bg-zebra" : ""
              }`}
            >
              <Td align="right" className="text-text-muted">{holding.rank}</Td>
              <Td>
                <span className="block max-w-[280px] truncate font-bold">
                  {holding.issuer_name ?? holding.cusip ?? holding.isin ?? "—"}
                </span>
                {(holding.cusip ?? holding.isin) && (
                  <span className="block text-[10px] text-text-muted">
                    {holding.cusip ?? holding.isin}
                  </span>
                )}
              </Td>
              <Td>{holding.sector_label ?? holding.gics_sector ?? holding.sector ?? "—"}</Td>
              <Td align="right">
                {holding.pct_of_nav !== null
                  ? `${formatNumber(holding.pct_of_nav, 2)}%`
                  : "—"}
              </Td>
              <Td align="right">
                {holding.market_value !== null
                  ? `$${formatCompact(holding.market_value)}`
                  : "—"}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

const MONTH_LABELS = [
  "Jan", "Feb", "Mar", "Apr", "May", "Jun",
  "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
];

/**
 * `monthly_returns` arrives as a flat [month_end_date, fraction] series
 * (see FundAnalysisResponse). Reshape it into a year x month grid so it
 * reads like a standard monthly-returns table; months without a data point
 * (partial years) render as a dash rather than a fabricated zero.
 */
function MonthlyReturnsTable({ data }: { data: [string, number][] }) {
  const byYear = new Map<number, (number | null)[]>();
  for (const [date, value] of data) {
    const parsed = new Date(`${date.slice(0, 10)}T00:00:00Z`);
    if (Number.isNaN(parsed.getTime())) continue;
    const year = parsed.getUTCFullYear();
    const month = parsed.getUTCMonth();
    const row = byYear.get(year) ?? new Array<number | null>(12).fill(null);
    row[month] = value;
    byYear.set(year, row);
  }
  const years = Array.from(byYear.keys()).sort((a, b) => b - a);

  if (years.length === 0) {
    return <EmptyMessage message="No monthly returns returned." />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="min-w-[760px] w-full border-collapse ix-fs tabular-nums lining-nums">
        <thead>
          <tr className="bg-field">
            <Th align="right">Year</Th>
            {MONTH_LABELS.map((label) => (
              <Th key={label} align="right">{label}</Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {years.map((year, index) => (
            <tr
              key={year}
              className={`border-b border-border ${index % 2 === 1 ? "bg-zebra" : ""}`}
            >
              <Td align="right" className="font-bold">{year}</Td>
              {(byYear.get(year) ?? []).map((value, month) => (
                <Td
                  key={month}
                  align="right"
                  className={
                    value === null
                      ? "text-text-muted"
                      : value > 0
                        ? "text-gain"
                        : value < 0
                          ? "text-loss"
                          : ""
                  }
                >
                  {value !== null ? formatPercent(value, 1, { signed: true }) : "—"}
                </Td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function StyleTab({
  styleDriftQuery,
  styleDriftOption,
}: {
  styleDriftQuery: UseQueryResult<FundStyleDrift, Error>;
  styleDriftOption: Highcharts.Options | null;
}) {
  return (
    <ChartCard
      title="Style drift"
      subtitle="N-PORT sectors"
      option={styleDriftOption}
      query={styleDriftQuery}
      emptyMessage={
        styleDriftQuery.data?.empty_state?.reason ??
        "No historical sector drift available for this fund."
      }
      className="mx-auto aspect-[21/9] max-w-[1040px]"
    />
  );
}

function FactorsTab({
  factorsQuery,
  factorSensitivityOption,
  styleBiasOption,
  factorRadarOption,
}: {
  factorsQuery: UseQueryResult<FundFactors, Error>;
  factorSensitivityOption: Highcharts.Options | null;
  styleBiasOption: Highcharts.Options | null;
  factorRadarOption: Highcharts.Options | null;
}) {
  return (
    <div className="grid items-stretch gap-px bg-border xl:grid-cols-[minmax(280px,0.8fr)_minmax(520px,1.2fr)]">
      <ChartCard
        title="Market sensitivities"
        subtitle="beta"
        option={factorSensitivityOption}
        query={factorsQuery}
        emptyMessage="No factor sensitivities available."
        tip="How strongly the fund moves with each driver. A market beta of 1.0 tracks the index; positive size / value tilts mean a small-cap or value lean."
        className="h-[420px]"
      />
      <ChartCard
        title="Style bias"
        subtitle="holdings-weighted z-score"
        option={factorRadarOption ?? styleBiasOption}
        query={factorsQuery}
        emptyMessage="No style-bias snapshot available."
        className="h-[420px]"
      />
    </div>
  );
}

function PeersTab({
  peersQuery,
  bubbleOption,
}: {
  peersQuery: UseQueryResult<FundPeers, Error>;
  bubbleOption: Highcharts.Options | null;
}) {
  const targetPeer = peersQuery.data?.items.find((peer) => peer.is_target)
    ?? peersQuery.data?.items[0]
    ?? null;

  return (
    <div className="grid gap-4">
      <Card
        title="Peer cohort"
        subtitle={peersQuery.data ? peersQuery.data.cohort_label : undefined}
      >
        {peersQuery.data ? (
          <PeersTable data={peersQuery.data} />
        ) : (
          <QueryMessage
            query={peersQuery}
            emptyMessage="No peer cohort returned for this fund."
            loadingMessage="Loading peers..."
          />
        )}
      </Card>

      <Card title="Peer bubble map" subtitle="Volatility, Sharpe and 1Y return scale">
        {peersQuery.data ? (
          <div className="grid gap-3">
            {targetPeer && (
              <div className="grid gap-px border border-border bg-border md:grid-cols-4">
                <KpiTile label="Focus" value={targetPeer.ticker ?? targetPeer.name} />
                <KpiTile label="Return 1Y" value={signedPct(targetPeer.return_1y)} />
                <KpiTile label="Vol 1Y" value={pct(targetPeer.volatility_1y)} />
                <KpiTile label="Sharpe" value={num(targetPeer.sharpe_1y)} />
              </div>
            )}
            {bubbleOption ? (
              <HighchartsChart options={bubbleOption} className="h-[420px] w-full" />
            ) : (
              <EmptyMessage message="No peer bubble payload returned for this cohort." />
            )}
          </div>
        ) : (
          <QueryMessage
            query={peersQuery}
            emptyMessage="No peer cohort returned for this fund."
            loadingMessage="Loading peer bubble..."
          />
        )}
      </Card>
    </div>
  );
}

function DeepAnalysisModal({
  entityAnalyticsQuery,
  benchmarkId,
  activeBenchmarkLabel,
  onClose,
  tailRiskOption,
  distributionOption,
  drawdownOption,
  insiderOption,
}: {
  entityAnalyticsQuery: UseQueryResult<FundEntityAnalytics, Error>;
  benchmarkId: string;
  activeBenchmarkLabel: string;
  onClose: () => void;
  tailRiskOption: Highcharts.Options | null;
  distributionOption: Highcharts.Options | null;
  drawdownOption: Highcharts.Options | null;
  insiderOption: Highcharts.Options | null;
}) {
  const data = entityAnalyticsQuery.data;
  const rollingReturns = data
    ? Object.entries(data.rolling_returns.series).map(([window, series]) => ({
        window,
        latest: latestPoint(series),
      }))
    : [];

  return (
    <SidePanel
      title="Deep Analysis"
      subtitle={
        data
          ? `${data.name} · ${data.window} · ${formatDate(data.as_of_date)}`
          : "Loading"
      }
      ariaLabel="Deep fund analysis"
      closeLabel="Close deep analysis"
      onClose={onClose}
      wide
    >
      <div className="overflow-y-auto bg-surface px-5 py-5">
        {!data ? (
          <QueryMessage
            query={entityAnalyticsQuery}
            emptyMessage="No deep-analysis payload returned."
            loadingMessage="Loading deep analysis..."
          />
        ) : (
          <div className="flex flex-col gap-px">
            <ModalSection title="Risk Statistics" className="bg-surface-2">
              <dl className="m-0 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
                <StatBlock label="Ann. return" value={pct(data.risk_statistics.annualized_return)} />
                <StatBlock label="Ann. volatility" value={pct(data.risk_statistics.annualized_volatility)} />
                <StatBlock label="Sharpe" value={num(data.risk_statistics.sharpe_ratio)} />
                <StatBlock label="Sortino" value={num(data.risk_statistics.sortino_ratio)} />
                <StatBlock label="Calmar" value={num(data.risk_statistics.calmar_ratio)} />
                <StatBlock label="Max drawdown" value={pct(data.drawdown.max_drawdown)} />
                <StatBlock label="Alpha" value={pct(data.risk_statistics.alpha)} />
                <StatBlock label="Beta" value={num(data.risk_statistics.beta)} />
                <StatBlock label="Tracking error" value={pct(data.risk_statistics.tracking_error)} />
                <StatBlock label="Information ratio" value={num(data.risk_statistics.information_ratio)} />
              </dl>
            </ModalSection>

            <div className="grid gap-px bg-border">
              <ModalSection title="Drawdown">
                <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_minmax(300px,0.38fr)]">
                  <DeepChartFrame className="h-[360px] xl:h-[420px]">
                    {drawdownOption ? (
                      <HighchartsChart options={drawdownOption} className="h-full w-full" />
                    ) : (
                      <EmptyMessage message="No drawdown series for this window." />
                    )}
                  </DeepChartFrame>
                  <div className="grid gap-px border border-border bg-border sm:grid-cols-2 lg:grid-cols-1">
                    <StatBlock label="Max drawdown" value={pct(data.drawdown.max_drawdown)} />
                    <StatBlock label="Current drawdown" value={pct(data.drawdown.current_drawdown)} />
                    {data.drawdown.worst_periods.slice(0, 4).map((period) => (
                      <div
                        key={`${period.start_date}-${period.trough_date}`}
                        className="bg-surface-2 px-3 py-2"
                      >
                        <div className="flex items-baseline justify-between gap-3">
                          <span className="text-[11px] font-bold uppercase tracking-[0.06em] text-text-muted">
                            {formatDate(period.trough_date)}
                          </span>
                          <span className="tabular-nums font-bold text-loss">
                            {pct(period.depth)}
                          </span>
                        </div>
                        <div className="mt-1 text-right text-[11px] text-text-muted">
                          {formatDate(period.start_date)} - {period.end_date ? formatDate(period.end_date) : "open"}
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              </ModalSection>
            </div>

            <div className="grid gap-px bg-border lg:grid-cols-2">
              <ModalSection title="Capture">
                <dl className="m-0">
                  <StatRow label="Up capture" value={num(data.capture.up_capture, 1)} />
                  <StatRow label="Down capture" value={num(data.capture.down_capture, 1)} />
                  <StatRow label="Up periods" value={String(data.capture.up_periods)} />
                  <StatRow label="Down periods" value={String(data.capture.down_periods)} />
                  <StatRow
                    label="Benchmark"
                    value={benchmarkMetricLabel(
                      data.capture.benchmark_id ?? benchmarkId,
                      data.capture.benchmark_label,
                      activeBenchmarkLabel,
                    )}
                  />
                  {data.capture.empty_state && (
                    <StatRow label="Status" value={data.capture.empty_state.reason} />
                  )}
                </dl>
              </ModalSection>

              <ModalSection title="Rolling Returns">
                {rollingReturns.length > 0 ? (
                  <dl className="m-0">
                    {rollingReturns.map(({ window, latest }) => (
                      <StatRow
                        key={window}
                        label={window}
                        value={latest ? signedPct(latest[1]) : "--"}
                        detail={latest ? formatDate(latest[0]) : undefined}
                      />
                    ))}
                  </dl>
                ) : (
                  <EmptyMessage message="No rolling-return series for this window." />
                )}
              </ModalSection>
            </div>

            <div className="grid gap-px bg-border xl:grid-cols-[minmax(0,1.1fr)_minmax(360px,0.9fr)]">
              <ModalSection title="Distribution">
                <DeepChartFrame className="h-[320px]">
                  {distributionOption ? (
                    <HighchartsChart options={distributionOption} className="h-full w-full" />
                  ) : (
                    <EmptyMessage message="No return distribution for this window." />
                  )}
                </DeepChartFrame>
                <dl className="m-0 mt-3 grid gap-px border border-border bg-border sm:grid-cols-4">
                  <StatBlock label="Skewness" value={num(data.distribution.skewness)} />
                  <StatBlock label="Kurtosis" value={num(data.distribution.kurtosis)} />
                  <StatBlock label="VaR 95" value={pct(data.distribution.var_95)} />
                  <StatBlock label="CVaR 95" value={pct(data.distribution.cvar_95)} />
                </dl>
              </ModalSection>

              <ModalSection title="Return Statistics">
                <dl className="m-0 grid gap-x-4 md:grid-cols-2">
                  <StatRow label="Arithmetic mean monthly" value={pct(data.return_statistics.arithmetic_mean_monthly)} />
                  <StatRow label="Geometric mean monthly" value={pct(data.return_statistics.geometric_mean_monthly)} />
                  <StatRow label="Avg monthly gain" value={pct(data.return_statistics.avg_monthly_gain)} />
                  <StatRow label="Avg monthly loss" value={pct(data.return_statistics.avg_monthly_loss)} />
                  <StatRow label="Gain/loss ratio" value={num(data.return_statistics.gain_loss_ratio)} />
                  <StatRow label="Downside deviation" value={pct(data.return_statistics.downside_deviation)} />
                  <StatRow label="Semi deviation" value={pct(data.return_statistics.semi_deviation)} />
                  <StatRow label="Omega ratio" value={num(data.return_statistics.omega_ratio)} />
                  <StatRow label="Up percentage ratio" value={pct(data.return_statistics.up_percentage_ratio)} />
                  <StatRow label="Down percentage ratio" value={pct(data.return_statistics.down_percentage_ratio)} />
                </dl>
              </ModalSection>
            </div>

            <div className="grid gap-px bg-border xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
              <ModalSection title="Tail Risk">
                <DeepChartFrame className="h-[260px]">
                  {tailRiskOption ? (
                    <HighchartsChart options={tailRiskOption} className="h-full w-full" />
                  ) : (
                    <EmptyMessage message="No tail-risk ladder for this window." />
                  )}
                </DeepChartFrame>
                <dl className="m-0 mt-3 grid gap-px border border-border bg-border sm:grid-cols-4">
                  <StatBlock label="STARR" value={num(data.tail_risk.starr)} />
                  <StatBlock label="Rachev" value={num(data.tail_risk.rachev)} />
                  <StatBlock label="Jarque-Bera" value={num(data.tail_risk.jarque_bera)} />
                  <StatBlock label="JB p-value" value={num(data.tail_risk.jarque_bera_pvalue, 4)} />
                </dl>
              </ModalSection>

              <ModalSection title="Insider">
                {data.insider_data?.empty_state ? (
                  <EmptyStatePanel
                    reason={data.insider_data.empty_state.reason}
                    source={data.insider_data.empty_state.source}
                  />
                ) : data.insider_data ? (
                  <>
                    <div className="mb-3 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(120px,1fr))]">
                      <KpiTile label="Buy value" value={money(data.insider_data.total_buy_value)} />
                      <KpiTile label="Sell value" value={money(data.insider_data.total_sell_value)} />
                      <KpiTile label="Net" value={money(data.insider_data.net_value)} />
                      <KpiTile label="Sentiment" value={num(data.insider_data.sentiment_score)} />
                      <KpiTile label="Issuers" value={String(data.insider_data.issuer_ciks?.length ?? 0)} />
                      <KpiTile label="As of" value={formatDate(data.insider_data.as_of)} />
                    </div>
                    <DeepChartFrame className="h-[260px]">
                      {insiderOption ? (
                        <HighchartsChart options={insiderOption} className="h-full w-full" />
                      ) : (
                        <EmptyMessage message="No insider sentiment quarters returned." />
                      )}
                    </DeepChartFrame>
                  </>
                ) : (
                  <EmptyMessage message="No insider payload returned." />
                )}
              </ModalSection>
            </div>
          </div>
        )}
      </div>
    </SidePanel>
  );
}

function SynchronizedRiskCharts({
  panes,
  query,
  emptyMessage,
}: {
  panes: HcRiskSynchronizedPane[] | null;
  query: UseQueryResult<FundRiskTimeseries, Error>;
  emptyMessage: string;
}) {
  const chartsRef = useRef(new Map<string, Chart>());

  function syncPointer(
    event: React.MouseEvent<HTMLDivElement> | React.TouchEvent<HTMLDivElement>,
  ) {
    const sourceEvent = event.nativeEvent;
    for (const chart of chartsRef.current.values()) {
      const series = chart.series.find((item) => item.visible && item.points.length > 0);
      if (!series) continue;
      const pointerEvent = chart.pointer.normalize(sourceEvent);
      const point = series.searchPoint(pointerEvent, true);
      if (!point) continue;
      point.onMouseOver();
      chart.tooltip?.refresh(point);
      chart.xAxis[0]?.drawCrosshair(pointerEvent, point);
    }
  }

  function clearPointer() {
    for (const chart of chartsRef.current.values()) {
      chart.tooltip?.hide(0);
      chart.xAxis[0]?.hideCrosshair();
    }
  }

  return (
    <Card title="Drawdown and conditional volatility" subtitle="synchronized">
      {panes ? (
        <div
          className="divide-y divide-border"
          onMouseMove={syncPointer}
          onMouseLeave={clearPointer}
          onTouchMove={syncPointer}
          onTouchEnd={clearPointer}
        >
          {panes.map((pane) => (
            <div key={pane.id} className="py-3 first:pt-0 last:pb-0">
              <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
                <h3 className="ix-label m-0">
                  {pane.title}
                  {pane.subtitle && (
                    <span className="ml-2 font-normal normal-case tracking-normal text-text-secondary">
                      {pane.subtitle}
                    </span>
                  )}
                </h3>
              </div>
              <HighchartsChart
                options={pane.option}
                className="h-[190px] w-full"
                emptyMessage={pane.emptyMessage}
                isEmpty={pane.isEmpty}
                onReady={(chart) => {
                  chartsRef.current.set(pane.id, chart);
                }}
              />
            </div>
          ))}
        </div>
      ) : (
        <QueryMessage query={query} emptyMessage={emptyMessage} />
      )}
    </Card>
  );
}

/**
 * Institutional tab — 13F reveal for the fund's holdings: which institutions
 * hold the same securities (`top_holders`), and where the fund's book overlaps
 * the most institutional money (`overlap`). Data comes straight from
 * GET /funds/{id}/institutional-reveal; `empty_state.reason` explains gaps.
 */
function InstitutionalTab({
  revealQuery,
  holderOption,
  overlapOption,
}: {
  revealQuery: UseQueryResult<FundInstitutionalReveal, Error>;
  holderOption: Highcharts.Options | null;
  overlapOption: Highcharts.Options | null;
}) {
  const reveal = revealQuery.data ?? null;
  const emptyReason =
    reveal?.empty_state?.reason ??
    "No institutional positions matched to this fund's holdings.";
  const asOf = reveal
    ? (() => {
        const reported = reveal.period ? formatDate(reveal.period) : null;
        const holdings = reveal.holdings_report_date
          ? formatDate(reveal.holdings_report_date)
          : null;
        if (reported && holdings && reported !== holdings) {
          return `Reported as of ${reported} · holdings ${holdings}`;
        }
        const anchor = reported ?? holdings;
        return anchor ? `Reported as of ${anchor}` : undefined;
      })()
    : undefined;

  return (
    <div className="grid gap-4">
      <div className="grid items-stretch gap-px bg-border xl:grid-cols-2">
        <ChartCard
          title="Top institutional holders"
          subtitle={asOf}
          option={holderOption}
          query={revealQuery}
          emptyMessage={emptyReason}
          tip="Largest institutional managers holding the securities in this fund's portfolio, ranked by reported value across matched holdings."
          className="h-[420px]"
        />
        <ChartCard
          title="Institutional overlap"
          subtitle="by security"
          option={overlapOption}
          query={revealQuery}
          emptyMessage={emptyReason}
          tip="The fund's holdings ranked by how much institutional money sits in the same securities — where the fund crowds with institutions."
          className="h-[420px]"
        />
      </div>

      {reveal && !reveal.empty_state && reveal.top_holders.length > 0 && (
        <Card
          title="Holder detail"
          subtitle={`${reveal.top_holders.length} managers`}
        >
          <div className="overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-[length:var(--ix-fs)] tabular-nums">
              <thead>
                <tr>
                  <Th>Manager</Th>
                  <Th align="right">Reported value</Th>
                  <Th align="right">Shares</Th>
                  <Th align="right">Matched holdings</Th>
                  <Th align="right">Report date</Th>
                </tr>
              </thead>
              <tbody>
                {reveal.top_holders.map((holder, i) => (
                  <tr
                    key={holder.cik}
                    className={`border-b border-border last:border-b-0 ${
                      i % 2 === 1 ? "bg-zebra" : ""
                    }`}
                  >
                    <Td className="font-bold text-text-primary">
                      {titleCase(holder.manager_name)}
                    </Td>
                    <Td align="right">{compactUsd(holder.value_usd ?? null)}</Td>
                    <Td align="right">
                      {holder.shares !== null && holder.shares !== undefined
                        ? formatCompact(holder.shares)
                        : "--"}
                    </Td>
                    <Td align="right">{String(holder.holding_count)}</Td>
                    <Td align="right" className="text-text-secondary">
                      {holder.report_date ? formatDate(holder.report_date) : "--"}
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  option,
  query,
  emptyMessage,
  tip,
  className = "h-[260px]",
}: {
  title: string;
  subtitle?: string;
  option: Highcharts.Options | null;
  query: UseQueryResult<unknown, Error>;
  emptyMessage: string;
  tip?: string;
  className?: string;
}) {
  return (
    <Card
      title={title}
      subtitle={subtitle}
      actions={tip ? <InfoDot tip={tip} /> : undefined}
    >
      {option ? (
        <HighchartsChart options={option} className={`${className} w-full`} />
      ) : (
        <QueryMessage query={query} emptyMessage={emptyMessage} />
      )}
    </Card>
  );
}

function QueryMessage({
  query,
  emptyMessage,
  loadingMessage = "Loading...",
}: {
  query: UseQueryResult<unknown, Error>;
  emptyMessage: string;
  loadingMessage?: string;
}) {
  const message = query.isPending
    ? loadingMessage
    : errorMessage(query) ?? emptyMessage;
  return (
    <p
      className={`py-8 text-center text-[13px] ${
        query.isError ? "text-loss" : "text-text-muted"
      }`}
    >
      {message}
    </p>
  );
}

function EmptyMessage({ message }: { message: string }) {
  return <p className="py-6 text-center text-[13px] text-text-muted">{message}</p>;
}

function ActiveSharePanel({ query }: { query: UseQueryResult<FundActiveShare, Error> }) {
  return (
    <Card title="Active share">
      {query.data ? (
        query.data.empty_state ? (
          <EmptyStatePanel
            reason={query.data.empty_state.reason}
            source={query.data.empty_state.source}
          />
        ) : (
          <div className="grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(120px,1fr))]">
            <KpiTile label="Active share" value={pct(query.data.active_share)} />
            <KpiTile label="Overlap" value={pct(query.data.overlap)} />
            <KpiTile label="Portfolio positions" value={String(query.data.n_portfolio_positions)} />
            <KpiTile
              label="Benchmark"
              value={benchmarkMetricLabel(
                query.data.benchmark_series_id,
                query.data.benchmark_name,
              )}
            />
            <KpiTile label="Benchmark positions" value={String(query.data.n_benchmark_positions)} />
            <KpiTile label="Common positions" value={String(query.data.n_common_positions)} />
            <KpiTile label="As of" value={formatDate(query.data.as_of_date)} />
          </div>
        )
      ) : (
        <QueryMessage
          query={query}
          emptyMessage="No active-share payload returned."
          loadingMessage="Loading active share..."
        />
      )}
    </Card>
  );
}

function EmptyStatePanel({ reason, source }: { reason: string; source?: string | null }) {
  return (
    <div className="border border-border bg-field px-3 py-4 text-[13px] text-text-secondary">
      <p className="m-0">{reason}</p>
      {source && <p className="m-0 mt-1 text-[11px] text-text-muted">{source}</p>}
    </div>
  );
}

function PeersTable({ data }: { data: FundPeers }) {
  if (data.items.length === 0) {
    return <EmptyMessage message="No peers returned." />;
  }

  return (
    <>
      <div className="overflow-x-auto">
        <table className="min-w-[980px] w-full border-collapse ix-fs tabular-nums lining-nums">
          <thead>
            <tr className="bg-field">
              <Th>Fund</Th>
              <Th>Strategy</Th>
              <Th align="right">Expense</Th>
              <Th align="right">Return 1Y</Th>
              <Th align="right">Vol 1Y</Th>
              <Th align="right">Sharpe</Th>
              <Th align="right">Max DD</Th>
              <Th align="right">CVaR</Th>
            </tr>
          </thead>
          <tbody>
            {data.items.slice(0, 20).map((peer, index) => (
              <tr
                key={peer.instrument_id}
                className={`border-b border-border transition-colors hover:bg-accent-wash ${
                  peer.is_target ? "bg-accent-wash" : index % 2 === 1 ? "bg-zebra" : ""
                }`}
              >
                <Td>
                  <Link href={`/funds/${peer.instrument_id}`} className="font-bold hover:text-accent">
                    {peer.ticker ?? peer.name}
                  </Link>
                  <span className="block max-w-[280px] truncate text-[10px] text-text-muted">
                    {peer.name}
                  </span>
                </Td>
                <Td>{peer.strategy_label}</Td>
                <Td align="right">{pct(peer.expense_ratio)}</Td>
                <Td align="right">{signedPct(peer.return_1y)}</Td>
                <Td align="right">{pct(peer.volatility_1y)}</Td>
                <Td align="right">{num(peer.sharpe_1y)}</Td>
                <Td align="right">{pct(peer.max_drawdown_1y)}</Td>
                <Td align="right">{pct(peer.cvar_95_12m)}</Td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {visibleClassificationNote(data.classification_note) && (
        <p className="mt-2 text-[11px] text-text-muted">
          {visibleClassificationNote(data.classification_note)}
        </p>
      )}
    </>
  );
}

function Th({
  children,
  align = "left",
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  const alignClass = align === "right" ? "text-right" : "text-left";
  return (
    <th
      className={`border-b border-border-strong px-2.5 py-[7px] ${alignClass} text-[11px] font-semibold text-text-secondary ${className}`}
    >
      {children}
    </th>
  );
}

function Td({
  children,
  align = "left",
  className = "",
}: {
  children: ReactNode;
  align?: "left" | "right";
  className?: string;
}) {
  const alignClass = align === "right" ? "text-right" : "text-left";
  return <td className={`ix-cell px-2.5 ${alignClass} ${className}`}>{children}</td>;
}

/**
 * Right-docked side panel (Funds.dc.html Deep analysis / Ownership drawers).
 * Backdrop click and Escape (wired in the parent) close it; the panel itself
 * stops propagation. The sticky serif header carries the title, a muted
 * subtitle, and the × close affordance.
 */
function SidePanel({
  title,
  subtitle,
  ariaLabel,
  closeLabel,
  onClose,
  wide = false,
  children,
}: {
  title: string;
  subtitle?: string;
  ariaLabel: string;
  closeLabel: string;
  onClose: () => void;
  wide?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      className="fixed inset-0 z-50 flex justify-end bg-[rgba(22,22,22,0.58)]"
      onClick={onClose}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={ariaLabel}
        onClick={(event) => event.stopPropagation()}
        className={`ix-thin-scroll flex h-full flex-col overflow-y-auto border-l border-border-strong bg-surface shadow-2xl ${
          wide ? "w-[min(1180px,96vw)]" : "w-[min(720px,94vw)]"
        }`}
      >
        <div className="sticky top-0 z-[5] flex items-center justify-between gap-3 border-b border-border bg-surface-2 px-5 py-3.5">
          <div className="min-w-0">
            <h2 className="ix-title m-0 text-[18px]">{title}</h2>
            {subtitle && (
              <p className="m-0 truncate text-[11px] text-text-muted">{subtitle}</p>
            )}
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label={closeLabel}
            className="flex h-[30px] min-w-[30px] items-center justify-center border border-border-strong bg-surface-2 px-2 text-[16px] font-bold leading-none text-text-secondary hover:bg-layer-hover"
          >
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}

function ModalSection({
  title,
  className = "",
  children,
}: {
  title: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <section className={`border border-border bg-surface-2 p-3 ${className}`}>
      <h3 className="ix-label m-0 mb-2">{title}</h3>
      {children}
    </section>
  );
}

function DeepChartFrame({
  children,
  className = "",
}: {
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={`border border-border bg-field p-2 ${className}`}>
      {children}
    </div>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-2 px-3 py-2.5">
      <dt className="text-[10px] font-bold uppercase tracking-[0.06em] text-text-muted">
        {label}
      </dt>
      <dd className="m-0 mt-1 text-[16px] font-bold tabular-nums text-text-primary">
        {value}
      </dd>
    </div>
  );
}

function Tag({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex h-[20px] items-center border border-border-strong bg-field px-2 text-[10px] font-bold uppercase tracking-[0.05em] text-text-secondary">
      {children}
    </span>
  );
}

type RiskRow = { label: string; value: string; detail?: string; tip?: string };

/**
 * One catalog of plain-language tooltips for the dossier's technical risk
 * rows (Funds.dc.html / revised/FundRiskSnapshot.tsx RISK_COPY). The data
 * layer stays field-keyed; the wording is reviewed in one place.
 */
const RISK_TIP: Record<string, string> = {
  "Max drawdown 1Y":
    "The largest peak-to-trough decline over the past year — the worst loss an investor would have sat through.",
  "VaR 95 1M":
    "Value-at-Risk: a loss this size or worse is expected on the worst 5% of days. A rough floor for a normal bad day.",
  "CVaR 95 1M":
    "Expected shortfall (CVaR): average loss on the worst 5% of days. More conservative than VaR because it measures how bad the tail actually is.",
  "Sortino 1Y":
    "Like Sharpe, but only counts downside moves as risk — it doesn't penalize upside volatility.",
  "Calmar 3Y":
    "Return relative to the worst peak-to-trough loss. Higher means smoother recovery from drawdowns.",
  "Alpha 1Y":
    "Return above what the benchmark exposure alone would predict — the manager's value-add after market risk.",
  "Beta 1Y":
    "How strongly the fund moves with its benchmark. 1.0 tracks it; above 1 amplifies the swings, below 1 is calmer.",
  "Info ratio 1Y":
    "Excess return over the benchmark per unit of tracking error — the consistency of out-performance.",
  "Tracking error 1Y":
    "How far the fund's returns stray from the benchmark. Low means index-like; high means it goes its own way.",
  "Downside capture 1Y":
    "Share of the benchmark's down moves the fund takes on. Below 100% means it cushions losses.",
  "Upside capture 1Y":
    "Share of the benchmark's up moves the fund captures. Above 100% means it beats the market in rallies.",
  "Empirical duration":
    "Estimated sensitivity to rate moves from the fund's own return history — its effective interest-rate exposure.",
  "Credit beta":
    "Sensitivity to credit-spread moves — how much the fund swings when corporate risk premia widen or tighten.",
};

function riskClass(
  fundType: string,
  assetClass: string | null,
): "equity" | "fixed_income" | "cash" | "alternatives" {
  if (fundType === "mmf") return "cash";
  const cls = (assetClass ?? "").toLowerCase();
  if (cls.includes("fixed") || cls.includes("bond")) return "fixed_income";
  if (cls.includes("alternative")) return "alternatives";
  return "equity";
}

const RISK_CLASS_TITLE: Record<ReturnType<typeof riskClass>, string> = {
  equity: "Equity analytics",
  fixed_income: "Fixed income analytics",
  cash: "Cash analytics",
  alternatives: "Alternatives analytics",
};

function RiskGroupHeader({ children }: { children: ReactNode }) {
  return (
    <div className="mt-3 border-b border-border-strong pb-1 text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
      {children}
    </div>
  );
}

function RiskRows({
  risk,
  fundType,
  assetClass,
}: {
  risk: FundRisk;
  fundType: string;
  assetClass: string | null;
}) {
  const common: RiskRow[] = [
    { label: "Return 1M", value: pct(risk.return_1m) },
    { label: "Return 3M", value: pct(risk.return_3m) },
    { label: "Return 3Y ann.", value: pct(risk.return_3y_ann) },
    { label: "Return 5Y ann.", value: pct(risk.return_5y_ann) },
    { label: "Max drawdown 1Y", value: pct(risk.max_drawdown_1y) },
    { label: "Max drawdown 3Y", value: pct(risk.max_drawdown_3y) },
    { label: "Sharpe 3Y", value: num(risk.sharpe_3y) },
    { label: "Sortino 1Y", value: num(risk.sortino_1y) },
    { label: "Calmar 3Y", value: num(risk.calmar_ratio_3y) },
    { label: "VaR 95 1M", value: pct(risk.var_95_1m) },
    { label: "CVaR 95 1M", value: pct(risk.cvar_95_1m) },
    { label: "CVaR 99 EVT", value: pct(risk.cvar_99_evt) },
  ];

  const cls = riskClass(fundType, assetClass);
  const byClass: Record<typeof cls, RiskRow[]> = {
    equity: [
      { label: "Alpha 1Y", value: pct(risk.alpha_1y) },
      { label: "Beta 1Y", value: num(risk.beta_1y) },
      { label: "Info ratio 1Y", value: num(risk.information_ratio_1y) },
      { label: "Tracking error 1Y", value: pct(risk.tracking_error_1y) },
      { label: "Downside capture 1Y", value: num(risk.downside_capture_1y, 1) },
      { label: "Upside capture 1Y", value: num(risk.upside_capture_1y, 1) },
      { label: "Equity corr. 252d", value: num(risk.equity_correlation_252d) },
    ],
    fixed_income: [],
    cash: [],
    alternatives: [
      { label: "Equity corr. 252d", value: num(risk.equity_correlation_252d) },
      { label: "Downside capture 1Y", value: num(risk.downside_capture_1y, 1) },
      { label: "Upside capture 1Y", value: num(risk.upside_capture_1y, 1) },
    ],
  };

  const peers: RiskRow[] = [
    {
      label: "Peer Sharpe pctl",
      value: num(risk.peer_sharpe_pctl, 0),
      ...(risk.peer_count !== null && {
        detail: `${risk.peer_count} peers - ${risk.peer_strategy_label ?? "--"}`,
      }),
    },
    { label: "Peer Sortino pctl", value: num(risk.peer_sortino_pctl, 0) },
    { label: "Peer return pctl", value: num(risk.peer_return_pctl, 0) },
    { label: "Peer drawdown pctl", value: num(risk.peer_drawdown_pctl, 0) },
    { label: "Manager score", value: num(risk.manager_score) },
    { label: "Elite", value: risk.elite_flag === null ? "--" : risk.elite_flag ? "Yes" : "No" },
  ];

  const renderRow = (row: RiskRow) => (
    <StatRow
      key={row.label}
      label={row.label}
      value={row.value}
      detail={row.detail}
      tip={row.tip ?? RISK_TIP[row.label]}
    />
  );

  return (
    <>
      {common.map(renderRow)}
      {byClass[cls].length > 0 && (
        <>
          <RiskGroupHeader>{RISK_CLASS_TITLE[cls]}</RiskGroupHeader>
          {byClass[cls].map(renderRow)}
        </>
      )}
      <RiskGroupHeader>Peer comparison</RiskGroupHeader>
      {peers.map(renderRow)}
      {(risk.empirical_duration != null ||
        risk.credit_beta != null ||
        risk.inflation_beta != null ||
        risk.crisis_alpha_score != null) && (
        <>
          <RiskGroupHeader>FI/Alt analytics</RiskGroupHeader>
          {risk.empirical_duration != null &&
            renderRow({ label: "Empirical duration", value: num(risk.empirical_duration) })}
          {risk.credit_beta != null &&
            renderRow({ label: "Credit beta", value: num(risk.credit_beta) })}
          {risk.inflation_beta != null &&
            renderRow({ label: "Inflation beta", value: num(risk.inflation_beta) })}
          {risk.crisis_alpha_score != null &&
            renderRow({ label: "Crisis alpha score", value: num(risk.crisis_alpha_score) })}
        </>
      )}
    </>
  );
}
