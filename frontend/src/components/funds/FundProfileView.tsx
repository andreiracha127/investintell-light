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
import { useEffect, useMemo, useState, type ReactNode } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { InteractiveChart } from "@/components/charts/InteractiveChart";
import { FundLookthroughSection } from "@/components/funds/FundLookthroughSection";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card, KpiTile, StatRow } from "@/components/ui/panels";
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
  fetchHoldingReverseLookup,
  fetchFundsScatter,
  fundTimeseriesToHistoryBars,
  type FundActiveShare,
  type FundAnalysis,
  type FundEntityAnalytics,
  type FundFactors,
  type FundHoldingsTop,
  type FundInstitutionalReveal,
  type HoldingReverseLookup,
  type FundPeers,
  type FundRisk,
  type FundRiskTimeseries,
  type FundStyleDrift,
  type Histogram,
  type RangePreset,
} from "@/lib/api/client";
import {
  buildHcFactorSensitivityOption,
  buildHcFundsScatterOption,
  buildHcInsiderSentimentOption,
  buildHcInstitutionalHolderOption,
  buildHcInstitutionalOverlapOption,
  buildHcRiskTimeseriesOption,
  buildHcStyleBiasOption,
  buildHcStyleDriftOption,
  buildHcTailRiskOption,
} from "@/lib/charts/hc/fundDossier";
import { buildHcHistogramOption } from "@/lib/charts/hc/histogram";
import { buildHcRollingOption } from "@/lib/charts/hc/rolling";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import {
  dossierQueryKeys,
  FUND_DOSSIER_DEFAULTS,
  FUND_DOSSIER_STALE_TIME_MS,
} from "@/lib/funds/dossierQueries";
import {
  formatCompact,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";

const TYPE_TAG: Record<string, string> = {
  etf: "ETF",
  mutual_fund: "Mutual fund",
  mmf: "Money market",
};

type TabId = "performance" | "holdings" | "style" | "factors" | "peers";

const TABS: { id: TabId; label: string }[] = [
  { id: "performance", label: "Performance" },
  { id: "holdings", label: "Holdings" },
  { id: "style", label: "Style" },
  { id: "factors", label: "Factors" },
  { id: "peers", label: "Peers" },
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
  const [relationshipsOpen, setRelationshipsOpen] = useState(false);
  const [benchmarkDraft, setBenchmarkDraft] = useState("");
  const [benchmarkId, setBenchmarkId] = useState("");
  const [selectedCusip, setSelectedCusip] = useState("");

  useEffect(() => {
    setActiveTab("performance");
    setRange("1Y");
    setDeepOpen(false);
    setRelationshipsOpen(false);
    setBenchmarkDraft("");
    setBenchmarkId("");
    setSelectedCusip("");
  }, [instrumentId]);

  const benchmarkQuery = benchmarkId ? { benchmark_id: benchmarkId } : {};
  const isPerformanceTab = activeTab === "performance";
  const isHoldingsTab = activeTab === "holdings";
  const isStyleTab = activeTab === "style";
  const isFactorsTab = activeTab === "factors";
  const isPeersTab = activeTab === "peers";

  const profileQuery = useQuery({
    queryKey: dossierQueryKeys.profile(instrumentId),
    queryFn: ({ signal }) => fetchFundProfile(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.profile,
    retry: retryPolicy,
  });

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

  const scatterQuery = useQuery({
    queryKey: dossierQueryKeys.scatter({
      limit: FUND_DOSSIER_DEFAULTS.scatterLimit,
    }),
    queryFn: ({ signal }) =>
      fetchFundsScatter({ limit: FUND_DOSSIER_DEFAULTS.scatterLimit }, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS.scatter,
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
    queryKey: dossierQueryKeys.riskTimeseries(instrumentId),
    queryFn: ({ signal }) => fetchFundRiskTimeseries(instrumentId, {}, signal),
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
    queryKey: dossierQueryKeys.activeShare(instrumentId, benchmarkQuery),
    queryFn: ({ signal }) =>
      fetchFundActiveShare(instrumentId, benchmarkQuery, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["active-share"],
    enabled: isHoldingsTab,
    retry: retryPolicy,
  });

  const institutionalRevealQuery = useQuery({
    queryKey: dossierQueryKeys.institutionalReveal(instrumentId),
    queryFn: ({ signal }) => fetchFundInstitutionalReveal(instrumentId, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["institutional-reveal"],
    enabled: relationshipsOpen,
    retry: retryPolicy,
  });

  const reverseLookupCusip =
    selectedCusip || institutionalRevealQuery.data?.overlap[0]?.cusip || "";

  const reverseLookupQuery = useQuery({
    queryKey: dossierQueryKeys.holdingReverseLookup(reverseLookupCusip),
    queryFn: ({ signal }) => fetchHoldingReverseLookup(reverseLookupCusip, signal),
    staleTime: FUND_DOSSIER_STALE_TIME_MS["holding-reverse-lookup"],
    enabled: relationshipsOpen && reverseLookupCusip.length > 0,
    retry: retryPolicy,
  });

  const chartBars = useMemo(
    () =>
      timeseriesQuery.data
        ? fundTimeseriesToHistoryBars(timeseriesQuery.data)
        : [],
    [timeseriesQuery.data],
  );

  const growthOption = useMemo(() => {
    if (!colors || !analysisQuery.data?.growth_of_100.length) return null;
    return buildHcRollingOption(
      analysisQuery.data.growth_of_100,
      "Growth of 100",
      colors,
    );
  }, [analysisQuery.data, colors]);

  const volatilityOption = useMemo(() => {
    if (!colors || !analysisQuery.data?.rolling_volatility.length) return null;
    return buildHcRollingOption(
      analysisQuery.data.rolling_volatility,
      "Volatility",
      colors,
      { yPercent: true },
    );
  }, [analysisQuery.data, colors]);

  const sharpeOption = useMemo(() => {
    if (!colors || !analysisQuery.data?.rolling_sharpe.length) return null;
    return buildHcRollingOption(analysisQuery.data.rolling_sharpe, "Sharpe", colors);
  }, [analysisQuery.data, colors]);

  const histogramOption = useMemo(() => {
    if (!colors || !analysisQuery.data) return null;
    return buildHcHistogramOption(analysisQuery.data.histogram, colors);
  }, [analysisQuery.data, colors]);

  const riskTimeseriesOption = useMemo(() => {
    if (!colors || !riskTimeseriesQuery.data) return null;
    if (riskTimeseriesQuery.data.empty_state) return null;
    return buildHcRiskTimeseriesOption(riskTimeseriesQuery.data, colors);
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

  const styleBiasOption = useMemo(() => {
    if (!colors || !factorsQuery.data?.style_bias.length) return null;
    return buildHcStyleBiasOption(factorsQuery.data, colors);
  }, [factorsQuery.data, colors]);

  const scatterOption = useMemo(() => {
    if (!colors || !scatterQuery.data || scatterQuery.data.count === 0) return null;
    return buildHcFundsScatterOption(scatterQuery.data, colors);
  }, [scatterQuery.data, colors]);

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

  const institutionalHolderOption = useMemo(() => {
    if (!colors || !institutionalRevealQuery.data?.top_holders.length) return null;
    if (institutionalRevealQuery.data.empty_state) return null;
    return buildHcInstitutionalHolderOption(institutionalRevealQuery.data, colors);
  }, [institutionalRevealQuery.data, colors]);

  const institutionalOverlapOption = useMemo(() => {
    if (!colors || !institutionalRevealQuery.data?.overlap.length) return null;
    if (institutionalRevealQuery.data.empty_state) return null;
    return buildHcInstitutionalOverlapOption(institutionalRevealQuery.data, colors);
  }, [institutionalRevealQuery.data, colors]);

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
      <div className="mx-auto max-w-[1400px] px-5 py-5">
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
      <div className="mx-auto max-w-[1400px] px-5 py-5">
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

  const applyBenchmark = (value = benchmarkDraft) => {
    setBenchmarkId(value.trim());
  };

  return (
    <div className="mx-auto max-w-[1400px] px-5 py-5">
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
            onClick={() => setRelationshipsOpen(true)}
            className="h-[32px] border border-border-strong bg-surface-2 px-3 text-[11px] font-bold uppercase tracking-[0.06em] text-text-secondary transition-colors hover:bg-layer-hover"
          >
            Relationships
          </button>
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
        <KpiTile label="AUM" value={money(fund.aum_usd)} />
        <KpiTile label="Expense" value={pct(fund.expense_ratio)} />
        <KpiTile label="Return 1Y" value={signedPct(risk?.return_1y)} tone={riskTone} />
        <KpiTile label="Vol 1Y" value={pct(risk?.volatility_1y)} />
        <KpiTile label="Sharpe 1Y" value={num(risk?.sharpe_1y)} />
        <KpiTile label="CVaR 95 12M" value={pct(risk?.cvar_95_12m)} />
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
          growthOption={growthOption}
          volatilityOption={volatilityOption}
          sharpeOption={sharpeOption}
          histogramOption={histogramOption}
          riskTimeseriesOption={riskTimeseriesOption}
          risk={risk}
          fundType={fund.fund_type}
          assetClass={fund.asset_class}
        />
      )}

      {activeTab === "holdings" && (
        <HoldingsTab
          instrumentId={fund.instrument_id}
          holdingsTopQuery={holdingsTopQuery}
          activeShareQuery={activeShareQuery}
          benchmarkDraft={benchmarkDraft}
          benchmarkId={benchmarkId}
          onBenchmarkDraftChange={setBenchmarkDraft}
          onApplyBenchmark={applyBenchmark}
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
        />
      )}

      {activeTab === "peers" && (
        <PeersTab
          peersQuery={peersQuery}
          scatterQuery={scatterQuery}
          scatterOption={scatterOption}
        />
      )}

      <p className="mt-4 text-[11px] text-text-muted">{fund.classification_note}</p>

      {deepOpen && (
        <DeepAnalysisModal
          entityAnalyticsQuery={entityAnalyticsQuery}
          benchmarkDraft={benchmarkDraft}
          benchmarkId={benchmarkId}
          onBenchmarkDraftChange={setBenchmarkDraft}
          onApplyBenchmark={applyBenchmark}
          onClose={() => setDeepOpen(false)}
          tailRiskOption={tailRiskOption}
          distributionOption={distributionOption}
          drawdownOption={deepDrawdownOption}
          insiderOption={insiderOption}
        />
      )}

      {relationshipsOpen && (
        <RelationshipsModal
          institutionalRevealQuery={institutionalRevealQuery}
          reverseLookupQuery={reverseLookupQuery}
          selectedCusip={reverseLookupCusip}
          onSelectCusip={setSelectedCusip}
          onClose={() => setRelationshipsOpen(false)}
          holderOption={institutionalHolderOption}
          overlapOption={institutionalOverlapOption}
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
  growthOption,
  volatilityOption,
  sharpeOption,
  histogramOption,
  riskTimeseriesOption,
  risk,
  fundType,
  assetClass,
}: {
  chartBars: ReturnType<typeof fundTimeseriesToHistoryBars>;
  fundLabel: string;
  range: RangePreset;
  onRangeChange: (range: RangePreset) => void;
  timeseriesQuery: UseQueryResult<unknown, Error>;
  analysisQuery: UseQueryResult<FundAnalysis, Error>;
  riskTimeseriesQuery: UseQueryResult<FundRiskTimeseries, Error>;
  growthOption: Highcharts.Options | null;
  volatilityOption: Highcharts.Options | null;
  sharpeOption: Highcharts.Options | null;
  histogramOption: Highcharts.Options | null;
  riskTimeseriesOption: Highcharts.Options | null;
  risk: FundRisk | null;
  fundType: string;
  assetClass: string | null;
}) {
  return (
    <div className="grid gap-4 lg:[grid-template-columns:minmax(0,2fr)_minmax(280px,1fr)]">
      <div className="flex flex-col gap-4">
        {chartBars.length > 0 ? (
          <InteractiveChart
            symbol={fundLabel}
            bars={chartBars}
            mode="nav"
            range={range}
            onRangeChange={onRangeChange}
          />
        ) : (
          <Card title="NAV">
            <QueryMessage
              query={timeseriesQuery}
              emptyMessage="No NAV history in the synced window."
              loadingMessage="Loading NAV history..."
            />
          </Card>
        )}

        <div className="grid gap-4 xl:grid-cols-2">
          <ChartCard
            title="Growth of 100"
            option={growthOption}
            query={analysisQuery}
            emptyMessage="No rebased performance series for this window."
          />
          <ChartCard
            title="Return histogram"
            option={histogramOption}
            query={analysisQuery}
            emptyMessage="No return distribution for this window."
          />
          <ChartCard
            title="Rolling volatility"
            option={volatilityOption}
            query={analysisQuery}
            emptyMessage="No rolling volatility for this window."
          />
          <ChartCard
            title="Rolling Sharpe"
            option={sharpeOption}
            query={analysisQuery}
            emptyMessage="No rolling Sharpe for this window."
          />
        </div>

        <ChartCard
          title="Drawdown and conditional volatility"
          subtitle={
            riskTimeseriesQuery.data
              ? riskTimeseriesQuery.data.volatility_model.toUpperCase()
              : undefined
          }
          option={riskTimeseriesOption}
          query={riskTimeseriesQuery}
          emptyMessage={
            riskTimeseriesQuery.data?.empty_state?.reason ??
            "No risk timeseries available for this fund."
          }
        />
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
  benchmarkDraft,
  benchmarkId,
  onBenchmarkDraftChange,
  onApplyBenchmark,
}: {
  instrumentId: string;
  holdingsTopQuery: UseQueryResult<FundHoldingsTop, Error>;
  activeShareQuery: UseQueryResult<FundActiveShare, Error>;
  benchmarkDraft: string;
  benchmarkId: string;
  onBenchmarkDraftChange: (value: string) => void;
  onApplyBenchmark: (value?: string) => void;
}) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(320px,1fr)]">
        <Card
          title="Top holdings"
          subtitle={
            holdingsTopQuery.data?.report_date
              ? `report ${formatDate(holdingsTopQuery.data.report_date)}`
              : undefined
          }
        >
          {holdingsTopQuery.data ? (
            <HoldingsTable data={holdingsTopQuery.data} />
          ) : (
            <QueryMessage
              query={holdingsTopQuery}
              emptyMessage="No N-PORT holdings synced for this fund."
              loadingMessage="Loading holdings..."
            />
          )}
        </Card>

        <div className="flex flex-col gap-4">
          <BenchmarkControl
            benchmarkDraft={benchmarkDraft}
            benchmarkId={benchmarkId}
            onBenchmarkDraftChange={onBenchmarkDraftChange}
            onApplyBenchmark={onApplyBenchmark}
          />
          <ActiveSharePanel query={activeShareQuery} />
          <Card title="Sector breakdown">
            {holdingsTopQuery.data ? (
              <SectorBreakdown data={holdingsTopQuery.data} />
            ) : (
              <QueryMessage
                query={holdingsTopQuery}
                emptyMessage="No sector exposure for this fund."
                loadingMessage="Loading sector exposure..."
              />
            )}
          </Card>
        </div>
      </div>

      <FundLookthroughSection instrumentId={instrumentId} />
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
    <div className="grid gap-4 xl:grid-cols-[minmax(0,2fr)_minmax(280px,1fr)]">
      <ChartCard
        title="Style drift"
        subtitle="N-PORT sectors"
        option={styleDriftOption}
        query={styleDriftQuery}
        emptyMessage={
          styleDriftQuery.data?.empty_state?.reason ??
          "No historical sector drift available for this fund."
        }
        className="h-[360px]"
      />
      <Card title="Source">
        {styleDriftQuery.data ? (
          <dl className="m-0">
            <StatRow label="Series" value={styleDriftQuery.data.series_id} />
            <StatRow label="Periods" value={String(styleDriftQuery.data.periods.length)} />
            <StatRow
              label="Status"
              value={styleDriftQuery.data.empty_state?.reason ?? "Available"}
            />
          </dl>
        ) : (
          <QueryMessage
            query={styleDriftQuery}
            emptyMessage="No style drift source metadata."
            loadingMessage="Loading style drift..."
          />
        )}
      </Card>
    </div>
  );
}

function FactorsTab({
  factorsQuery,
  factorSensitivityOption,
  styleBiasOption,
}: {
  factorsQuery: UseQueryResult<FundFactors, Error>;
  factorSensitivityOption: Highcharts.Options | null;
  styleBiasOption: Highcharts.Options | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-2">
      <ChartCard
        title="Market sensitivities"
        option={factorSensitivityOption}
        query={factorsQuery}
        emptyMessage="No factor sensitivities available."
        className="h-[320px]"
      />
      <ChartCard
        title="Style bias"
        option={styleBiasOption}
        query={factorsQuery}
        emptyMessage="No style-bias snapshot available."
        className="h-[320px]"
      />
      <Card title="Source metadata">
        {factorsQuery.data ? (
          factorsQuery.data.source_metadata.length > 0 ? (
            <dl className="m-0">
              {factorsQuery.data.source_metadata.map((source) => (
                <StatRow
                  key={source.source}
                  label={source.source}
                  value={source.as_of ? formatDate(source.as_of) : "--"}
                  detail={source.empty_state?.reason}
                />
              ))}
            </dl>
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">
              No source metadata returned.
            </p>
          )
        ) : (
          <QueryMessage
            query={factorsQuery}
            emptyMessage="No factor source metadata."
            loadingMessage="Loading factors..."
          />
        )}
      </Card>
    </div>
  );
}

function PeersTab({
  peersQuery,
  scatterQuery,
  scatterOption,
}: {
  peersQuery: UseQueryResult<FundPeers, Error>;
  scatterQuery: UseQueryResult<unknown, Error>;
  scatterOption: Highcharts.Options | null;
}) {
  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1.2fr)_minmax(0,1fr)]">
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
      <ChartCard
        title="Risk-return universe"
        option={scatterOption}
        query={scatterQuery}
        emptyMessage="No scatter payload returned for the funds universe."
        className="h-[360px]"
      />
    </div>
  );
}

function DeepAnalysisModal({
  entityAnalyticsQuery,
  benchmarkDraft,
  benchmarkId,
  onBenchmarkDraftChange,
  onApplyBenchmark,
  onClose,
  tailRiskOption,
  distributionOption,
  drawdownOption,
  insiderOption,
}: {
  entityAnalyticsQuery: UseQueryResult<FundEntityAnalytics, Error>;
  benchmarkDraft: string;
  benchmarkId: string;
  onBenchmarkDraftChange: (value: string) => void;
  onApplyBenchmark: (value?: string) => void;
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
    <div
      className="fixed inset-0 z-50 bg-[rgba(22,22,22,0.72)] px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-label="Deep fund analysis"
    >
      <div className="mx-auto flex max-h-[calc(100vh-48px)] max-w-[1180px] flex-col border border-border-strong bg-surface shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-border-strong px-4 py-3">
          <div>
            <h2 className="ix-title m-0 text-[22px]">Deep Analysis</h2>
            <p className="m-0 text-[12px] text-text-secondary">
              {data ? `${data.name} - ${data.window} - ${formatDate(data.as_of_date)}` : "Loading"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-[30px] min-w-[30px] border border-border-strong bg-surface-2 px-2 text-[14px] font-bold text-text-secondary hover:bg-layer-hover"
            aria-label="Close deep analysis"
          >
            x
          </button>
        </div>

        <div className="overflow-y-auto px-4 py-4">
          <div className="mb-4">
            <BenchmarkControl
              benchmarkDraft={benchmarkDraft}
              benchmarkId={benchmarkId}
              onBenchmarkDraftChange={onBenchmarkDraftChange}
              onApplyBenchmark={onApplyBenchmark}
            />
          </div>

          {!data ? (
            <QueryMessage
              query={entityAnalyticsQuery}
              emptyMessage="No deep-analysis payload returned."
              loadingMessage="Loading deep analysis..."
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <ModalSection title="Risk Statistics">
                <dl className="m-0 grid gap-px border border-border bg-border md:grid-cols-2">
                  <StatBlock label="Ann. return" value={pct(data.risk_statistics.annualized_return)} />
                  <StatBlock label="Ann. volatility" value={pct(data.risk_statistics.annualized_volatility)} />
                  <StatBlock label="Sharpe" value={num(data.risk_statistics.sharpe_ratio)} />
                  <StatBlock label="Sortino" value={num(data.risk_statistics.sortino_ratio)} />
                  <StatBlock label="Calmar" value={num(data.risk_statistics.calmar_ratio)} />
                  <StatBlock label="Observations" value={String(data.risk_statistics.n_observations)} />
                  <StatBlock label="Alpha" value={pct(data.risk_statistics.alpha)} />
                  <StatBlock label="Beta" value={num(data.risk_statistics.beta)} />
                  <StatBlock label="Tracking error" value={pct(data.risk_statistics.tracking_error)} />
                  <StatBlock label="Information ratio" value={num(data.risk_statistics.information_ratio)} />
                </dl>
              </ModalSection>

              <ModalSection title="Drawdown">
                {drawdownOption ? (
                  <HighchartsChart options={drawdownOption} className="h-[230px] w-full" />
                ) : (
                  <EmptyMessage message="No drawdown series for this window." />
                )}
                <dl className="m-0 mt-3">
                  <StatRow label="Max drawdown" value={pct(data.drawdown.max_drawdown)} />
                  <StatRow label="Current drawdown" value={pct(data.drawdown.current_drawdown)} />
                  {data.drawdown.worst_periods.slice(0, 3).map((period) => (
                    <StatRow
                      key={`${period.start_date}-${period.trough_date}`}
                      label={formatDate(period.trough_date)}
                      value={pct(period.depth)}
                      detail={`${formatDate(period.start_date)} - ${
                        period.end_date ? formatDate(period.end_date) : "open"
                      }`}
                    />
                  ))}
                </dl>
              </ModalSection>

              <ModalSection title="Capture">
                <dl className="m-0">
                  <StatRow label="Up capture" value={num(data.capture.up_capture, 1)} />
                  <StatRow label="Down capture" value={num(data.capture.down_capture, 1)} />
                  <StatRow label="Up periods" value={String(data.capture.up_periods)} />
                  <StatRow label="Down periods" value={String(data.capture.down_periods)} />
                  <StatRow
                    label="Benchmark"
                    value={data.capture.benchmark_label ?? data.capture.benchmark_id ?? "--"}
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

              <ModalSection title="Distribution">
                {distributionOption ? (
                  <HighchartsChart options={distributionOption} className="h-[230px] w-full" />
                ) : (
                  <EmptyMessage message="No return distribution for this window." />
                )}
                <dl className="m-0 mt-3">
                  <StatRow label="Skewness" value={num(data.distribution.skewness)} />
                  <StatRow label="Kurtosis" value={num(data.distribution.kurtosis)} />
                  <StatRow label="VaR 95" value={pct(data.distribution.var_95)} />
                  <StatRow label="CVaR 95" value={pct(data.distribution.cvar_95)} />
                </dl>
              </ModalSection>

              <ModalSection title="Return Statistics">
                <dl className="m-0">
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

              <ModalSection title="Tail Risk">
                {tailRiskOption ? (
                  <HighchartsChart options={tailRiskOption} className="h-[230px] w-full" />
                ) : (
                  <EmptyMessage message="No tail-risk ladder for this window." />
                )}
                <dl className="m-0 mt-3">
                  <StatRow label="STARR" value={num(data.tail_risk.starr)} />
                  <StatRow label="Rachev" value={num(data.tail_risk.rachev)} />
                  <StatRow label="Jarque-Bera" value={num(data.tail_risk.jarque_bera)} />
                  <StatRow label="JB p-value" value={num(data.tail_risk.jarque_bera_pvalue, 4)} />
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
                    <div className="mb-3 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(130px,1fr))]">
                      <KpiTile label="Buy value" value={money(data.insider_data.total_buy_value)} />
                      <KpiTile label="Sell value" value={money(data.insider_data.total_sell_value)} />
                      <KpiTile label="Net" value={money(data.insider_data.net_value)} />
                      <KpiTile label="Sentiment" value={num(data.insider_data.sentiment_score)} />
                      <KpiTile label="Issuers" value={String(data.insider_data.issuer_ciks?.length ?? 0)} />
                      <KpiTile label="As of" value={formatDate(data.insider_data.as_of)} />
                    </div>
                    {insiderOption ? (
                      <HighchartsChart options={insiderOption} className="h-[230px] w-full" />
                    ) : (
                      <EmptyMessage message="No insider sentiment quarters returned." />
                    )}
                  </>
                ) : (
                  <EmptyMessage message="No insider payload returned." />
                )}
              </ModalSection>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function RelationshipsModal({
  institutionalRevealQuery,
  reverseLookupQuery,
  selectedCusip,
  onSelectCusip,
  onClose,
  holderOption,
  overlapOption,
}: {
  institutionalRevealQuery: UseQueryResult<FundInstitutionalReveal, Error>;
  reverseLookupQuery: UseQueryResult<HoldingReverseLookup, Error>;
  selectedCusip: string;
  onSelectCusip: (cusip: string) => void;
  onClose: () => void;
  holderOption: Highcharts.Options | null;
  overlapOption: Highcharts.Options | null;
}) {
  const data = institutionalRevealQuery.data;
  return (
    <div
      className="fixed inset-0 z-50 bg-[rgba(22,22,22,0.72)] px-4 py-6"
      role="dialog"
      aria-modal="true"
      aria-label="Fund relationships"
    >
      <div className="mx-auto flex max-h-[calc(100vh-48px)] max-w-[1180px] flex-col border border-border-strong bg-surface shadow-2xl">
        <div className="flex items-center justify-between gap-3 border-b border-border-strong px-4 py-3">
          <div>
            <h2 className="ix-title m-0 text-[22px]">Relationships</h2>
            <p className="m-0 text-[12px] text-text-secondary">
              {data
                ? `${data.fund_name} - ${data.period ? formatDate(data.period) : "no 13F period"}`
                : "Loading"}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="h-[30px] min-w-[30px] border border-border-strong bg-surface-2 px-2 text-[14px] font-bold text-text-secondary hover:bg-layer-hover"
            aria-label="Close relationships"
          >
            x
          </button>
        </div>

        <div className="overflow-y-auto px-4 py-4">
          {!data ? (
            <QueryMessage
              query={institutionalRevealQuery}
              emptyMessage="No institutional reveal payload returned."
              loadingMessage="Loading institutional relationships..."
            />
          ) : data.empty_state ? (
            <EmptyStatePanel
              reason={data.empty_state.reason}
              source={data.empty_state.source}
            />
          ) : (
            <div className="grid gap-4 lg:grid-cols-2">
              <ModalSection title="Ranked Holders">
                {holderOption ? (
                  <HighchartsChart options={holderOption} className="h-[300px] w-full" />
                ) : (
                  <EmptyMessage message="No institutional holders returned." />
                )}
              </ModalSection>

              <ModalSection title="Institutional Overlap">
                {overlapOption ? (
                  <HighchartsChart options={overlapOption} className="h-[300px] w-full" />
                ) : (
                  <EmptyMessage message="No overlap securities returned." />
                )}
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {data.overlap.slice(0, 10).map((row) => (
                    <button
                      key={row.cusip}
                      type="button"
                      onClick={() => onSelectCusip(row.cusip)}
                      className={`h-[28px] border px-2 text-[11px] font-bold tabular-nums ${
                        selectedCusip === row.cusip
                          ? "border-accent bg-accent text-on-accent"
                          : "border-border-strong bg-surface-2 text-text-secondary hover:bg-layer-hover"
                      }`}
                    >
                      {row.cusip}
                    </button>
                  ))}
                </div>
              </ModalSection>

              <ModalSection title="Holder Network">
                <NetworkTable data={data} />
              </ModalSection>

              <ModalSection title="Reverse Lookup">
                <ReverseLookupPanel query={reverseLookupQuery} cusip={selectedCusip} />
              </ModalSection>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function NetworkTable({ data }: { data: FundInstitutionalReveal }) {
  if (data.holder_network.edges.length === 0) {
    return <EmptyMessage message="No holder-network edges returned." />;
  }
  const nodeLabel = new Map(data.holder_network.nodes.map((node) => [node.id, node.label]));
  return (
    <table className="w-full border-collapse ix-fs tabular-nums lining-nums">
      <thead>
        <tr className="bg-field">
          <Th>Source</Th>
          <Th>Target</Th>
          <Th align="right">Weight</Th>
        </tr>
      </thead>
      <tbody>
        {data.holder_network.edges.slice(0, 18).map((edge, index) => (
          <tr key={`${edge.source}-${edge.target}-${index}`} className="border-t border-border">
            <Td>{nodeLabel.get(edge.source) ?? edge.source}</Td>
            <Td>{nodeLabel.get(edge.target) ?? edge.target}</Td>
            <Td align="right">{edge.label === "fund holding" ? pct(edge.weight, 1) : money(edge.weight)}</Td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function ReverseLookupPanel({
  query,
  cusip,
}: {
  query: UseQueryResult<HoldingReverseLookup, Error>;
  cusip: string;
}) {
  if (!cusip) {
    return <EmptyMessage message="Select an overlap CUSIP to inspect reverse lookup." />;
  }
  const data = query.data;
  if (!data) {
    return (
      <QueryMessage
        query={query}
        emptyMessage="No reverse lookup payload returned."
        loadingMessage={`Loading ${cusip} reverse lookup...`}
      />
    );
  }
  if (data.empty_state) {
    return <EmptyStatePanel reason={data.empty_state.reason} source={data.empty_state.source} />;
  }
  return (
    <div className="space-y-3">
      <div className="grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(120px,1fr))]">
        <KpiTile label="CUSIP" value={data.cusip} />
        <KpiTile label="Institutions" value={String(data.institutions.length)} />
        <KpiTile label="Funds" value={String(data.fund_exposures.length)} />
        <KpiTile label="Period" value={formatDate(data.period)} />
      </div>
      <table className="w-full border-collapse ix-fs tabular-nums lining-nums">
        <thead>
          <tr className="bg-field">
            <Th>Institution</Th>
            <Th align="right">13F value</Th>
            <Th align="right">Shares</Th>
          </tr>
        </thead>
        <tbody>
          {data.institutions.slice(0, 8).map((institution) => (
            <tr key={institution.cik} className="border-t border-border">
              <Td>{institution.manager_name}</Td>
              <Td align="right">{money(institution.value_usd)}</Td>
              <Td align="right">{num(institution.shares, 0)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function ChartCard({
  title,
  subtitle,
  option,
  query,
  emptyMessage,
  className = "h-[260px]",
}: {
  title: string;
  subtitle?: string;
  option: Highcharts.Options | null;
  query: UseQueryResult<unknown, Error>;
  emptyMessage: string;
  className?: string;
}) {
  return (
    <Card title={title} subtitle={subtitle}>
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

function BenchmarkControl({
  benchmarkDraft,
  benchmarkId,
  onBenchmarkDraftChange,
  onApplyBenchmark,
}: {
  benchmarkDraft: string;
  benchmarkId: string;
  onBenchmarkDraftChange: (value: string) => void;
  onApplyBenchmark: (value?: string) => void;
}) {
  return (
    <section className="border border-border bg-surface-2 p-3">
      <div className="flex flex-wrap items-end gap-2">
        <label className="flex min-w-[220px] flex-1 flex-col gap-1">
          <span className="ix-label">Benchmark fund id</span>
          <input
            value={benchmarkDraft}
            onChange={(event) => onBenchmarkDraftChange(event.target.value)}
            className="h-[32px] border border-border-strong bg-field px-2 text-[12px] tabular-nums text-text-primary outline-none focus:border-accent"
            placeholder="UUID"
          />
        </label>
        <button
          type="button"
          onClick={() => onApplyBenchmark()}
          className="h-[32px] border border-border-strong bg-surface px-3 text-[11px] font-bold uppercase tracking-[0.06em] text-text-secondary hover:bg-layer-hover"
        >
          Apply
        </button>
        {benchmarkId && (
          <button
            type="button"
            onClick={() => {
              onBenchmarkDraftChange("");
              onApplyBenchmark("");
            }}
            className="h-[32px] border border-border-strong bg-surface px-3 text-[11px] font-bold uppercase tracking-[0.06em] text-text-secondary hover:bg-layer-hover"
          >
            Clear
          </button>
        )}
      </div>
      <p className="mt-2 text-[11px] tabular-nums text-text-muted">
        Active benchmark: {benchmarkId || "none"}
      </p>
    </section>
  );
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

function HoldingsTable({ data }: { data: FundHoldingsTop }) {
  if (data.top_holdings.length === 0) {
    return <EmptyMessage message="No top holdings returned." />;
  }

  return (
    <>
      <table className="w-full border-collapse ix-fs tabular-nums lining-nums">
        <thead>
          <tr className="bg-field">
            <Th className="w-10">#</Th>
            <Th>Issuer / Issue</Th>
            <Th>Sector</Th>
            <Th align="right">% NAV</Th>
          </tr>
        </thead>
        <tbody>
          {data.top_holdings.map((holding, index) => (
            <tr
              key={`${holding.rank}-${holding.cusip ?? holding.isin ?? index}`}
              className={`border-b border-border transition-colors hover:bg-accent-wash ${
                index % 2 === 1 ? "bg-zebra" : ""
              }`}
            >
              <Td className="text-text-muted">{holding.rank}</Td>
              <Td>
                <span className="block max-w-[360px] truncate">
                  {holding.issuer_name ?? "--"}
                </span>
                {(holding.cusip ?? holding.isin) && (
                  <span className="block text-[10px] tabular-nums text-text-muted">
                    {holding.cusip ? `CUSIP ${holding.cusip}` : `ISIN ${holding.isin}`}
                  </span>
                )}
              </Td>
              <Td className="text-text-secondary">
                <span className="block max-w-[220px] truncate">
                  {holding.sector_label ?? holding.gics_sector ?? holding.sector ?? "--"}
                </span>
              </Td>
              <Td align="right">
                {holding.pct_of_nav != null ? `${formatNumber(holding.pct_of_nav)}%` : "--"}
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-text-muted">
        {data.pct_of_nav_total != null
          ? `Reported holdings sum to ${formatNumber(data.pct_of_nav_total, 1)}% of NAV`
          : "Reported holdings total unavailable."}
      </p>
    </>
  );
}

function SectorBreakdown({ data }: { data: FundHoldingsTop }) {
  if (data.sector_breakdown.length === 0) {
    return <EmptyMessage message="No sector breakdown returned." />;
  }

  const max = Math.max(...data.sector_breakdown.map((item) => item.total_pct), 0);
  return (
    <div className="space-y-2">
      {data.sector_breakdown.map((item) => (
        <div key={item.key}>
          <div className="mb-1 flex items-center justify-between gap-3 text-[11px]">
            <span className="truncate text-text-secondary">{item.label}</span>
            <span className="tabular-nums font-bold text-text-primary">
              {formatNumber(item.total_pct)}%
            </span>
          </div>
          <div className="h-[8px] bg-field">
            <div
              className="h-full bg-accent"
              style={{ width: `${max > 0 ? (item.total_pct / max) * 100 : 0}%` }}
            />
          </div>
        </div>
      ))}
    </div>
  );
}

function PeersTable({ data }: { data: FundPeers }) {
  if (data.items.length === 0) {
    return <EmptyMessage message="No peers returned." />;
  }

  return (
    <>
      <table className="w-full border-collapse ix-fs tabular-nums lining-nums">
        <thead>
          <tr className="bg-field">
            <Th>Fund</Th>
            <Th align="right">Return 1Y</Th>
            <Th align="right">Vol 1Y</Th>
            <Th align="right">Sharpe</Th>
            <Th align="right">CVaR</Th>
          </tr>
        </thead>
        <tbody>
          {data.items.map((peer, index) => (
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
              <Td align="right">{signedPct(peer.return_1y)}</Td>
              <Td align="right">{pct(peer.volatility_1y)}</Td>
              <Td align="right">{num(peer.sharpe_1y)}</Td>
              <Td align="right">{pct(peer.cvar_95_12m)}</Td>
            </tr>
          ))}
        </tbody>
      </table>
      <p className="mt-2 text-[11px] text-text-muted">{data.classification_note}</p>
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

function ModalSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="border border-border bg-surface-2 p-3">
      <h3 className="ix-label m-0 mb-2">{title}</h3>
      {children}
    </section>
  );
}

function StatBlock({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface-2 px-3 py-2">
      <dt className="text-[10px] font-bold uppercase tracking-[0.06em] text-text-muted">
        {label}
      </dt>
      <dd className="m-0 mt-1 text-[15px] font-bold tabular-nums text-text-primary">
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

type RiskRow = { label: string; value: string; detail?: string };

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

  return (
    <>
      {common.map((row) => (
        <StatRow key={row.label} label={row.label} value={row.value} detail={row.detail} />
      ))}
      {byClass[cls].length > 0 && (
        <>
          <RiskGroupHeader>{RISK_CLASS_TITLE[cls]}</RiskGroupHeader>
          {byClass[cls].map((row) => (
            <StatRow key={row.label} label={row.label} value={row.value} detail={row.detail} />
          ))}
        </>
      )}
      <RiskGroupHeader>Peer comparison</RiskGroupHeader>
      {peers.map((row) => (
        <StatRow key={row.label} label={row.label} value={row.value} detail={row.detail} />
      ))}
      {(risk.empirical_duration != null ||
        risk.credit_beta != null ||
        risk.inflation_beta != null ||
        risk.crisis_alpha_score != null) && (
        <>
          <RiskGroupHeader>FI/Alt analytics</RiskGroupHeader>
          {risk.empirical_duration != null && (
            <StatRow label="Empirical duration" value={num(risk.empirical_duration)} />
          )}
          {risk.credit_beta != null && (
            <StatRow label="Credit beta" value={num(risk.credit_beta)} />
          )}
          {risk.inflation_beta != null && (
            <StatRow label="Inflation beta" value={num(risk.inflation_beta)} />
          )}
          {risk.crisis_alpha_score != null && (
            <StatRow label="Crisis alpha score" value={num(risk.crisis_alpha_score)} />
          )}
        </>
      )}
    </>
  );
}
