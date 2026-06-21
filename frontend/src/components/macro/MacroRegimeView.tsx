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
  stockTimeseriesToHistoryBars,
  type FundTimeseries,
  type MacroRegime,
  type RangePreset,
  type StockTimeseries,
  type SymbolSearchResult,
} from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { SymbolSearchInput } from "@/components/charts/SymbolSearchInput";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { PortfolioSelect } from "@/components/statistics/PortfolioSelect";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { InfoDot, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import {
  buildHcMacroPerformanceOption,
  type MacroPerformanceView,
} from "@/lib/charts/hc/regime";
import { buildHcMacroRrgOption } from "@/lib/charts/hc/macro-rrg";
import { buildHcMacroBandsOption } from "@/lib/charts/hc/macro-bands";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";

type DatePoint = [string, number];
type RegimeHistoryPoint = MacroRegime["history"][number];
type MacroQuadrantBlock = NonNullable<MacroRegime["macro_quadrant"]>;

const PERIODS: RangePreset[] = ["1M", "6M", "1Y", "5Y", "MAX"];

/** Tail spacing / momentum look-back per period for the RRG sweep. */
const RRG_STEP: Record<RangePreset, number> = {
  "1M": 2,
  "6M": 5,
  "1Y": 8,
  "5Y": 16,
  MAX: 20,
};

const RANGE_WORD: Record<RangePreset, string> = {
  "1M": "past month",
  "6M": "past 6 months",
  "1Y": "past year",
  "5Y": "past 5 years",
  MAX: "full history",
};

const RANGE_DAYS: Record<RangePreset, number> = {
  "1M": 21,
  "6M": 126,
  "1Y": 252,
  "5Y": 1260,
  MAX: Number.MAX_SAFE_INTEGER,
};

const DEFAULT_ASSET: SymbolSearchResult = {
  symbol: "SPY",
  name: "SPDR S&P 500 ETF Trust",
  kind: "stock",
  instrument_id: null,
};

const VOTE_TIPS: Record<"credit" | "trend" | "nfci", string> = {
  credit:
    "Credit appetite. Compares a high-yield bond ETF (HYG) to safe Treasuries (IEF). When investors get nervous they sell high-yield, the ratio falls below its 5-year trigger, and this vote turns on.",
  trend:
    "Price trend. Turns on when the credit-appetite ratio drops below its medium-term moving average — momentum is rolling over.",
  nfci: "Financial conditions. Based on the Chicago Fed's NFCI. A positive reading means conditions are tighter than average, and this vote turns on.",
};

const RULE_TIP =
  "Risk-off is called when at least 2 of the 3 signals — Credit, Trend and Financial conditions — are active at the same time.";

// ── Small derivations ───────────────────────────────────────────────────────

function isoToUtcMs(iso: string): number {
  const [y, m, d] = iso.split("-").map(Number);
  return Date.UTC(y, m - 1, d);
}

function daysBetween(startIso: string, endIso: string): number {
  return Math.round((isoToUtcMs(endIso) - isoToUtcMs(startIso)) / 86_400_000);
}

function formatPp(value: number | null | undefined, dp = 2): string {
  if (value === null || value === undefined) return "--";
  return `${value > 0 ? "+" : ""}${value.toFixed(dp)} pp`;
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

/** History sliced to the selected period window. */
function sliceHistory(history: RegimeHistoryPoint[], range: RangePreset): RegimeHistoryPoint[] {
  const k = RANGE_DAYS[range];
  return history.slice(Math.max(0, history.length - k));
}

function navToDatePoints(nav: Array<[number, number]>): DatePoint[] {
  return nav.map(([time, value]) => [new Date(time).toISOString().slice(0, 10), value]);
}

function sliceDatePoints(points: DatePoint[], range: RangePreset): DatePoint[] {
  if (range === "MAX") return points;
  const k = RANGE_DAYS[range];
  return points.slice(Math.max(0, points.length - k));
}

interface RegimeSegment {
  start: string;
  end: string;
  state: string;
  voteAtStart: number;
}

/** Contiguous same-state runs of a history slice (start → next flip / asOf). */
function derivePeriods(history: RegimeHistoryPoint[], asOf: string): RegimeSegment[] {
  const out: RegimeSegment[] = [];
  for (let i = 0; i < history.length; ) {
    const state = history[i].state;
    const start = history[i].date;
    const voteAtStart = history[i].vote_count;
    let j = i + 1;
    while (j < history.length && history[j].state === state) j += 1;
    const end = j < history.length ? history[j].date : asOf;
    out.push({ start, end, state, voteAtStart });
    i = j;
  }
  return out;
}

// ── View ────────────────────────────────────────────────────────────────────

type FlipSortKey = "date" | "dur" | "vote";

export function MacroRegimeView() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  const [range, setRange] = useState<RangePreset>("1Y");
  const [portfolioId, setPortfolioId] = useState<number | null>(null);
  const [asset, setAsset] = useState<SymbolSearchResult>(DEFAULT_ASSET);
  const [perfView, setPerfView] = useState<MacroPerformanceView>("indexed");
  const [flipSort, setFlipSort] = useState<{ key: FlipSortKey; dir: "asc" | "desc" }>({
    key: "date",
    dir: "desc",
  });

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
  const portfolioNav = usePortfolioNav(portfolioId);

  const assetQuery = useQuery<FundTimeseries | StockTimeseries>({
    queryKey: ["macro-asset-timeseries", asset.kind, asset.symbol, asset.instrument_id, range],
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
    const sliced = sliceHistory(macroQuery.data.history, range);
    const darkTheme =
      typeof document !== "undefined" &&
      document.documentElement.dataset.theme === "dark";
    return buildHcMacroRrgOption(sliced, colors, { step: RRG_STEP[range], darkTheme });
  }, [macroQuery.data, colors, range]);

  const assetPoints = useMemo<DatePoint[]>(() => {
    if (!assetQuery.data) return [];
    return asset.instrument_id
      ? fundToDatePoints(assetQuery.data as FundTimeseries)
      : stockToDatePoints(assetQuery.data as StockTimeseries);
  }, [asset.instrument_id, assetQuery.data]);

  const performanceOption = useMemo<Options | null>(() => {
    if (!colors || !macroQuery.data) return null;
    return buildHcMacroPerformanceOption({
      portfolio: sliceDatePoints(navToDatePoints(portfolioNav.recon.nav), range),
      asset: assetPoints,
      regimes: macroQuery.data.history,
      colors,
      portfolioLabel: portfolioQuery.data?.name ?? "Portfolio",
      assetLabel: assetLabel(asset),
      view: perfView,
    });
  }, [
    asset,
    assetPoints,
    colors,
    macroQuery.data,
    perfView,
    portfolioNav.recon.nav,
    portfolioQuery.data?.name,
    range,
  ]);

  const bandsOption = useMemo<Options | null>(() => {
    const mq = macroQuery.data?.macro_quadrant;
    if (!colors || !mq || mq.bands.length === 0) return null;
    return buildHcMacroBandsOption(mq.bands, colors);
  }, [macroQuery.data, colors]);

  // 404 → empty state.
  if (
    macroQuery.isError &&
    macroQuery.error instanceof ApiError &&
    macroQuery.error.status === 404
  ) {
    return (
      <MacroShell>
        <PageTitle title="Market regime" meta={HERO_SUBTITLE} />
        <EmptyState onRetry={() => macroQuery.refetch()} />
      </MacroShell>
    );
  }

  if (macroQuery.isPending) {
    return (
      <MacroShell>
        <PageTitle title="Market regime" meta={HERO_SUBTITLE} />
        <LoadingSkeleton />
      </MacroShell>
    );
  }

  if (macroQuery.isError) {
    return (
      <MacroShell>
        <PageTitle title="Market regime" meta={HERO_SUBTITLE} />
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
  const isOff = data.state === "risk_off";

  // Trend KPI: ratio vs its trailing mean (continuous momentum proxy).
  const trendVal = trendMomentum(data.history);

  return (
    <MacroShell>
      <PageTitle title="Market regime" meta={HERO_SUBTITLE}>
        <span className="inline-flex items-center gap-1.5 border border-border bg-field px-2.5 py-[5px] text-[11px] text-text-muted">
          <span title="Signals are recomputed once daily after the US market close." className="border-b border-dotted border-text-muted">
            Daily signal
          </span>
          · As of {formatDate(data.as_of)}
        </span>
      </PageTitle>

      {/* ── Status hero ── */}
      <section className="border border-border bg-surface-2">
        <div className="flex flex-wrap items-center gap-[18px] px-[18px] py-[var(--ix-pad)]">
          <div className="flex min-w-0 items-center gap-4">
            <StateBadge state={data.state} />
            <div className="flex min-w-0 flex-col gap-[3px]">
              <span className="text-[13px] font-bold text-text-primary">
                {isOff ? "Markets are risk-off" : "Markets are risk-on"}
              </span>
              <span className="text-[11.5px] tabular-nums text-text-muted">
                {data.last_flip
                  ? `In this regime ${data.days_in_state} days · since ${formatDate(data.last_flip)}`
                  : `In this regime ${data.days_in_state} days`}
              </span>
            </div>
          </div>

          <div className="ml-auto flex flex-wrap items-center gap-[14px]">
            <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
              Vote ensemble
              <InfoDot tip={RULE_TIP} />
            </span>
            <span
              className={`border border-border-strong bg-field px-[9px] py-[3px] text-[12px] font-bold tabular-nums ${
                data.vote_count >= 2 ? "text-loss" : "text-text-primary"
              }`}
            >
              {data.vote_count} / 3 active
            </span>
            <div className="flex flex-wrap gap-[7px]">
              <VoteChip label="Credit" active={votes.credit} tip={VOTE_TIPS.credit} />
              <VoteChip label="Trend" active={votes.trend} tip={VOTE_TIPS.trend} />
              <VoteChip label="Conditions" active={votes.nfci} tip={VOTE_TIPS.nfci} />
            </div>
          </div>
        </div>
      </section>

      {/* ── KPI tiles ── */}
      <div className="grid gap-px border border-t-0 border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
        <KpiTile
          label="Composite"
          value={`${data.vote_count} / 3`}
          tone={data.vote_count >= 2 ? "text-loss" : "text-gain"}
          detail={isOff ? "risk-off votes active" : "risk-on composite"}
          tip={RULE_TIP}
        />
        <KpiTile
          label="Credit"
          value={num(signal.ratio, 3)}
          detail="HYG / IEF ratio"
          tip="The price of a high-yield bond ETF (HYG) divided by safe Treasuries (IEF). A falling ratio signals investors are pulling back from risk."
        />
        <KpiTile
          label="Financial Conditions"
          value={num(signal.nfci, 2)}
          tone={
            signal.nfci !== null && signal.nfci !== undefined
              ? signal.nfci > 0
                ? "text-loss"
                : "text-gain"
              : "text-text-primary"
          }
          detail="NFCI index"
          tip="Chicago Fed National Financial Conditions Index. Above zero = tighter than average (headwind); below zero = looser than average (tailwind)."
        />
        <KpiTile
          label="Trend"
          value={trendVal === null ? "--" : `${trendVal > 0 ? "+" : ""}${trendVal.toFixed(2)}%`}
          tone={
            trendVal === null
              ? "text-text-primary"
              : trendVal < -0.8
                ? "text-loss"
                : trendVal > 0
                  ? "text-gain"
                  : "text-text-primary"
          }
          detail={trendVal !== null && trendVal < -0.8 ? "below average" : "above average"}
          tip="Price trend of the credit-appetite ratio versus its medium-term moving average. Below average (negative) means momentum is rolling over, and the Trend vote turns on."
        />
        <KpiTile
          label="Risk-Off Trigger"
          value={num(signal.p20_5y, 3)}
          detail="5-year 20th percentile"
          tip="The level the credit-appetite ratio sits below only 20% of the time over the last 5 years. Dropping under it switches the credit vote on."
        />
        <KpiTile
          label="Distance to Trigger"
          value={formatPp(signal.distance_pct, 2)}
          tone={
            signal.distance_pct !== null && signal.distance_pct !== undefined
              ? valueTone(signal.distance_pct)
              : "text-text-primary"
          }
          detail={
            signal.distance_pct !== null && signal.distance_pct !== undefined && signal.distance_pct < 0
              ? "below trigger"
              : "above trigger"
          }
          tip="How far today's ratio sits above (or below) the risk-off trigger, in percentage points. Negative means the credit vote is already active."
        />
      </div>

      {/* ── Controls bar ── */}
      <div className="flex flex-wrap items-end gap-[18px] border border-t-0 border-border bg-surface-2 px-[var(--ix-pad)] py-3">
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
            Period
          </span>
          <div role="group" aria-label="Period" className="flex h-[34px] border border-border-strong">
            {PERIODS.map((period, i) => {
              const active = range === period;
              return (
                <button
                  key={period}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setRange(period)}
                  className={`px-[13px] text-[11.5px] font-bold transition-colors ${
                    i === 0 ? "" : "border-l border-border-strong"
                  } ${
                    active
                      ? "bg-accent text-on-accent"
                      : "bg-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {period === "MAX" ? "Max" : period}
                </button>
              );
            })}
          </div>
        </div>
        <PortfolioSelect value={portfolioId} onChange={setPortfolioId} label="Portfolio" />
        <label className="flex min-w-[200px] flex-col gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
          Compare against
          <SymbolSearchInput
            active={assetLabel(asset)}
            placeholder="ETF, MF or stock"
            onSelect={setAsset}
            onClear={() => setAsset(DEFAULT_ASSET)}
          />
        </label>
      </div>

      {/* ── Charts row ── */}
      <div className="grid items-stretch gap-px border border-t-0 border-border bg-border [grid-template-columns:minmax(300px,2fr)_minmax(420px,3fr)]">
        {/* Regime rotation */}
        <section className="min-w-0 bg-surface-2 p-[var(--ix-pad)]">
          <div className="mb-1 flex items-center gap-1.5">
            <h2 className="ix-label m-0">Regime rotation</h2>
            <InfoDot tip="A market-cycle rotation graph. Each signal — and their composite — traces a tail through the four regime phases: Recovery and Expansion (improving momentum), Slowdown and Contraction (weakening). Rightward = more risk appetite, upward = improving momentum." />
          </div>
          <p className="mb-2 text-[11px] text-text-secondary">
            Signals and their composite, rotated over the selected period.
          </p>
          <div className="mb-2 flex flex-wrap items-center gap-[14px]">
            {colors &&
              ROT_LEGEND(colors).map((l) => (
                <span key={l.label} className="inline-flex items-center gap-1.5">
                  <span
                    className="h-[3px] w-[15px] rounded-[2px]"
                    style={{ background: l.color }}
                  />
                  <span className="text-[11px] font-bold text-text-secondary">{l.label}</span>
                </span>
              ))}
          </div>
          {rotationOption ? (
            <HighchartsChart options={rotationOption} className="h-[440px] w-full" />
          ) : (
            <div className="flex h-[440px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
              No regime history for the selected period.
            </div>
          )}
        </section>

        {/* Portfolio vs benchmark */}
        <section className="min-w-0 bg-surface-2 p-[var(--ix-pad)]">
          <div className="mb-1 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-1.5">
              <h2 className="ix-label m-0">Portfolio vs benchmark</h2>
              <InfoDot tip="Both lines start at 100 so you can compare growth on the same scale. Shaded vertical bands mark risk-off windows. Switch to Drawdown to see declines from each prior peak." />
            </div>
            <div role="group" aria-label="Chart view" className="flex h-[28px] border border-border-strong">
              {(["indexed", "drawdown"] as const).map((v, i) => {
                const active = perfView === v;
                return (
                  <button
                    key={v}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setPerfView(v)}
                    className={`px-[13px] text-[11.5px] font-bold capitalize transition-colors ${
                      i === 0 ? "" : "border-l border-border-strong"
                    } ${
                      active
                        ? "bg-accent text-on-accent"
                        : "bg-transparent text-text-secondary hover:text-text-primary"
                    }`}
                  >
                    {v}
                  </button>
                );
              })}
            </div>
          </div>
          <div className="mb-2 flex flex-wrap items-center gap-[14px] text-[11px] text-text-secondary">
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[3px] w-[13px] bg-accent" />
              {portfolioQuery.data?.name ?? "Portfolio"}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[3px] w-[13px] bg-chart-bar-mute" />
              {assetLabel(asset)}
            </span>
            <span className="inline-flex items-center gap-1.5">
              <span className="h-[11px] w-[14px] border border-loss/30 bg-loss/15" />
              Risk-off window
            </span>
            <span className="ml-auto text-text-muted">Drag to zoom</span>
          </div>
          <PerformancePanel
            portfolioError={portfolioQuery.isError ? portfolioQuery.error.message : null}
            onPortfolioRetry={() => portfolioQuery.refetch()}
            portfolioHistoryError={
              canAnalyzePortfolio && portfolioNav.isError
                ? "Could not load price history for some portfolio holdings."
                : null
            }
            onPortfolioHistoryRetry={portfolioNav.refetch}
            assetError={assetQuery.isError ? assetQuery.error.message : null}
            onAssetRetry={() => assetQuery.refetch()}
            canAnalyze={canAnalyzePortfolio}
            isPending={(canAnalyzePortfolio && portfolioNav.isLoading) || assetQuery.isPending}
            option={performanceOption}
          />
        </section>
      </div>

      {/* ── COMBO regime allocator: live gate + quadrant + bands ── */}
      <RegimeCombo macroQuadrant={data.macro_quadrant ?? null} bandsOption={bandsOption} />

      {/* ── Regime timeline strip ── */}
      <RegimeTimeline data={data} range={range} />

      {/* ── Recent regime changes ── */}
      <RecentChanges
        data={data}
        sort={flipSort}
        onSort={(key) =>
          setFlipSort((prev) =>
            prev.key === key
              ? { key, dir: prev.dir === "asc" ? "desc" : "asc" }
              : { key, dir: "desc" },
          )
        }
      />
    </MacroShell>
  );
}

const HERO_SUBTITLE =
  "A risk-on / risk-off read on markets, decided by a vote of three independent signals.";

/**
 * Composite legend swatches for the RRG. Credit reads blue and Conditions amber
 * (theme-aware), matching `buildHcMacroRrgOption`; Composite uses the design
 * accent and Trend the gain token. Blue/amber have no design token (the palette
 * is graphite + accent), so they use the same Carbon hues as the chart builder.
 */
function ROT_LEGEND(colors: ChartColors): Array<{ label: string; color: string }> {
  return [
    { label: "Composite", color: colors.accent },
    { label: "Credit", color: colors.blue },
    { label: "Trend", color: colors.gain },
    { label: "Conditions", color: colors.amber },
  ];
}

/** Latest ratio vs its 120-bar trailing mean, in percent (Trend KPI). */
function trendMomentum(history: RegimeHistoryPoint[]): number | null {
  const ratios = history
    .map((p) => p.signal.ratio)
    .filter((r): r is number => r !== null && r !== undefined);
  if (ratios.length === 0) return null;
  const window = Math.min(120, ratios.length);
  const recent = ratios.slice(-window);
  const mean = recent.reduce((a, b) => a + b, 0) / recent.length;
  if (mean === 0) return null;
  const last = ratios[ratios.length - 1];
  return (last / mean - 1) * 100;
}

// ── Sub-components ───────────────────────────────────────────────────────────

function StateBadge({ state }: { state: string }) {
  const isOn = state === "risk_on";
  const label = isOn ? "RISK-ON" : "RISK-OFF";
  const tone = isOn ? "border-gain text-gain bg-gain/10" : "border-loss text-loss bg-loss/10";
  return (
    <span
      aria-label={`Current regime: ${label}`}
      className={`inline-flex items-center gap-2 border-2 px-4 py-2 text-[16px] font-bold tracking-[0.06em] ${tone}`}
    >
      <span className="h-[9px] w-[9px] rounded-full bg-current" />
      {label}
    </span>
  );
}

function VoteChip({ label, active, tip }: { label: string; active: boolean; tip: string }) {
  const cls = active
    ? "border-loss text-loss bg-loss/10"
    : "border-border-strong text-text-muted bg-field";
  return (
    <span
      aria-label={`${label} signal ${active ? "active" : "inactive"}`}
      className={`inline-flex items-center gap-[7px] whitespace-nowrap border px-2.5 py-1 text-[11.5px] font-bold ${cls}`}
    >
      <span
        className={`h-[7px] w-[7px] rounded-full ${active ? "bg-loss opacity-100" : "bg-text-muted opacity-40"}`}
      />
      {label}
      <InfoDot tip={tip} />
    </span>
  );
}

// ── COMBO regime allocator section ───────────────────────────────────────────

const QUADRANT_LABEL: Record<string, string> = {
  recovery: "Recovery",
  expansion: "Expansion",
  slowdown: "Slowdown",
  contraction: "Contraction",
};

const COMBINED_REGIME_LABEL: Record<string, string> = {
  RISK_ON: "Risk-on bands",
  RISK_OFF: "Risk-off bands",
  INFLATION: "Inflation bands",
  STAG_GOLD: "Gold haven (slowdown)",
};

const GATE_TIPS = {
  rule: "A live, debounced risk-off gate. Enters risk-off only after at least 2 of 3 cross-asset signals (trend, credit, drawdown) hold for 21 consecutive days; exits symmetrically. This gate drives the per-asset-class allocation bands.",
  trend: "Trend. Turns on when the S&P 500 trades below its 200-day moving average.",
  credit:
    "Credit. Turns on when the high-yield / Treasury ratio (HYG/IEF) trades below its 60-day moving average.",
  drawdown: "Drawdown. Turns on when the S&P 500 is at least 6% below its trailing 63-day high.",
  quadrant:
    "Growth × inflation clock. Growth is the S&P 500's 126-day return; inflation is the TIP/IEF breakeven's 126-day momentum. Slowdown (growth down, inflation up) routes to a gold-led haven.",
  bands:
    "The per-asset-class weight envelope the optimizer allocates within. Set by the live gate (risk-off) or the macro quadrant, then widened (×1.5) and clamped to policy bounds.",
  haven:
    "Conviction target for a stagflationary slowdown: a gold-led haven that replaces the bond sleeve. The realized tilt depends on which of these instruments are in the chosen universe.",
} as const;

function quadrantLabel(q: string | null | undefined): string {
  if (!q) return "n/a";
  return QUADRANT_LABEL[q.toLowerCase()] ?? q;
}

/** A signed score formatted as a percentage (growth/inflation momentum). */
function scoreLabel(score: number | null | undefined): string {
  if (score === null || score === undefined) return "--";
  return `${score > 0 ? "+" : ""}${(score * 100).toFixed(1)}%`;
}

function GateVoteChip({ label, active, tip }: { label: string; active: boolean; tip: string }) {
  return <VoteChip label={label} active={active} tip={tip} />;
}

function RegimeCombo({
  macroQuadrant,
  bandsOption,
}: {
  macroQuadrant: MacroQuadrantBlock | null;
  bandsOption: Options | null;
}) {
  if (!macroQuadrant) {
    return (
      <section className="border border-t-0 border-border bg-surface-2 p-[var(--ix-pad)]">
        <div className="mb-1 flex items-center gap-1.5">
          <h2 className="ix-label m-0">Regime allocator</h2>
          <InfoDot tip={GATE_TIPS.rule} />
        </div>
        <p className="m-0 text-[12px] text-text-muted">
          The regime gate has not been populated yet — allocation bands will appear once the
          gate worker has run.
        </p>
      </section>
    );
  }

  const { gate, quadrant, combined_regime, growth_state, inflation_state } = macroQuadrant;
  const growthScore = macroQuadrant.growth_score;
  const inflationScore = macroQuadrant.inflation_score;
  const haven = macroQuadrant.haven_tilt;
  const isHaven = combined_regime === "STAG_GOLD";
  const regimeLabel = COMBINED_REGIME_LABEL[combined_regime] ?? combined_regime;
  const gateOff = gate?.state === "risk_off";

  return (
    <section className="border border-t-0 border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <div className="flex items-center gap-1.5">
          <h2 className="ix-label m-0">Regime allocator</h2>
          <InfoDot tip={GATE_TIPS.rule} />
        </div>
        <span className="text-[11px] text-text-muted">
          Live gate sets the per-class allocation bands · {combined_regime}
        </span>
      </div>

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(280px,1fr))]">
        {/* Gate + quadrant facts */}
        <div className="flex flex-col gap-4 bg-surface-2 p-[var(--ix-pad)]">
          {/* Live gate */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-wrap items-center gap-[10px]">
              <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
                Live gate
                <InfoDot tip={GATE_TIPS.rule} />
              </span>
              <span
                className={`inline-flex items-center gap-2 border px-2.5 py-[3px] text-[12px] font-bold ${
                  gate
                    ? gateOff
                      ? "border-loss text-loss bg-loss/10"
                      : "border-gain text-gain bg-gain/10"
                    : "border-border-strong text-text-muted bg-field"
                }`}
              >
                {gate ? (gateOff ? "RISK-OFF" : "RISK-ON") : "n/a"}
              </span>
              {gate && (
                <span className="text-[11px] tabular-nums text-text-muted">
                  {gate.vote_count}/3 votes · {gate.dwell_days} days latched
                </span>
              )}
            </div>
            {gate && (
              <div className="flex flex-wrap gap-[7px]">
                <GateVoteChip label="Trend" active={gate.trend_vote} tip={GATE_TIPS.trend} />
                <GateVoteChip label="Credit" active={gate.credit_vote} tip={GATE_TIPS.credit} />
                <GateVoteChip
                  label="Drawdown"
                  active={gate.drawdown_vote}
                  tip={GATE_TIPS.drawdown}
                />
              </div>
            )}
          </div>

          {/* Quadrant + scores */}
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
              Macro quadrant
              <InfoDot tip={GATE_TIPS.quadrant} />
            </span>
            <span className="text-[15px] font-bold text-text-primary">
              {quadrantLabel(quadrant)}
            </span>
            <div className="flex flex-wrap gap-x-[18px] gap-y-1 text-[11.5px] text-text-secondary">
              <span>
                Growth{" "}
                <b className="tabular-nums text-text-primary">
                  {scoreLabel(growthScore)}
                </b>{" "}
                <span className="text-text-muted">({growth_state ?? "--"})</span>
              </span>
              <span>
                Inflation{" "}
                <b className="tabular-nums text-text-primary">
                  {scoreLabel(inflationScore)}
                </b>{" "}
                <span className="text-text-muted">({inflation_state ?? "--"})</span>
              </span>
            </div>
            <span className="mt-1 inline-flex w-fit items-center gap-1.5 border border-border-strong bg-field px-2.5 py-[3px] text-[12px] font-bold text-text-primary">
              {regimeLabel}
              <span className="font-normal text-text-muted">· {combined_regime}</span>
            </span>
          </div>
        </div>

        {/* Bands chart OR haven tilt */}
        <div className="flex flex-col bg-surface-2 p-[var(--ix-pad)]">
          {isHaven ? (
            <div className="flex flex-col gap-2">
              <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
                Haven target tilt
                <InfoDot tip={GATE_TIPS.haven} />
              </span>
              {haven && Object.keys(haven).length > 0 ? (
                <ul className="m-0 flex flex-col gap-1.5 p-0">
                  {Object.entries(haven)
                    .sort((a, b) => b[1] - a[1])
                    .map(([ticker, weight]) => (
                      <li
                        key={ticker}
                        className="flex items-center justify-between border-b border-border pb-1.5 text-[12.5px] last:border-0"
                      >
                        <span className="font-bold text-text-primary">{ticker}</span>
                        <span className="tabular-nums text-text-secondary">
                          {formatPercent(weight, 0)}
                        </span>
                      </li>
                    ))}
                </ul>
              ) : (
                <p className="m-0 text-[12px] text-text-muted">No haven instruments available.</p>
              )}
              <p className="m-0 mt-1 text-[11px] text-text-muted">
                Conviction target — the realized tilt depends on the chosen universe.
              </p>
            </div>
          ) : (
            <>
              <div className="mb-1 flex items-center gap-1.5">
                <span className="text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
                  Allocation bands
                </span>
                <InfoDot tip={GATE_TIPS.bands} />
              </div>
              {bandsOption ? (
                <HighchartsChart options={bandsOption} className="h-[240px] w-full" />
              ) : (
                <div className="flex h-[240px] items-center justify-center px-4 text-center text-[12px] text-text-muted">
                  No allocation bands for the current regime.
                </div>
              )}
            </>
          )}
        </div>
      </div>
    </section>
  );
}

function PerformancePanel({
  portfolioError,
  onPortfolioRetry,
  portfolioHistoryError,
  onPortfolioHistoryRetry,
  assetError,
  onAssetRetry,
  canAnalyze,
  isPending,
  option,
}: {
  portfolioError: string | null;
  onPortfolioRetry: () => void;
  portfolioHistoryError: string | null;
  onPortfolioHistoryRetry: () => void;
  assetError: string | null;
  onAssetRetry: () => void;
  canAnalyze: boolean;
  isPending: boolean;
  option: Options | null;
}) {
  if (portfolioError) {
    return <ErrorPanel title="Portfolio failed" message={portfolioError} onRetry={onPortfolioRetry} />;
  }
  if (portfolioHistoryError) {
    return (
      <ErrorPanel
        title="Portfolio history failed"
        message={portfolioHistoryError}
        onRetry={onPortfolioHistoryRetry}
      />
    );
  }
  if (assetError) {
    return <ErrorPanel title="Asset history failed" message={assetError} onRetry={onAssetRetry} />;
  }
  if (!canAnalyze) {
    return (
      <div className="flex h-[440px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
        Select a portfolio with at least two positions.
      </div>
    );
  }
  if (isPending) {
    return <div className="h-[440px] animate-pulse bg-surface-3" />;
  }
  if (option) {
    return <HighchartsChart options={option} className="h-[440px] w-full" />;
  }
  return (
    <div className="flex h-[440px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
      No aligned series for the selected period.
    </div>
  );
}

function RegimeTimeline({ data, range }: { data: MacroRegime; range: RangePreset }) {
  const sliced = sliceHistory(data.history, range);
  if (sliced.length === 0) return null;

  const segs = derivePeriods(sliced, data.as_of);
  const startMs = isoToUtcMs(sliced[0].date);
  const endMs = isoToUtcMs(sliced[sliced.length - 1].date);
  const total = Math.max(1, endMs - startMs);
  const flipsInWindow = Math.max(0, segs.length - 1);
  const isOff = data.state === "risk_off";

  return (
    <section className="border border-t-0 border-border bg-surface-2 p-[var(--ix-pad)]">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
        <h2 className="ix-label m-0">Regime timeline</h2>
        <div className="flex items-center gap-[14px] text-[11px] text-text-secondary">
          <span className="inline-flex items-center gap-1.5">
            <span className="h-[11px] w-[13px] border border-gain bg-gain-muted" />
            Risk-on
          </span>
          <span className="inline-flex items-center gap-1.5">
            <span className="h-[11px] w-[13px] bg-loss" />
            Risk-off
          </span>
        </div>
      </div>
      <div className="flex h-[34px] w-full overflow-hidden border border-border">
        {segs.map((seg, i) => {
          const width = ((isoToUtcMs(seg.end) - isoToUtcMs(seg.start)) / total) * 100;
          const on = seg.state === "risk_on";
          return (
            <div
              key={`${seg.start}-${i}`}
              title={`${on ? "Risk-on" : "Risk-off"} · ${formatDate(seg.start)} → ${formatDate(seg.end)} · ${daysBetween(seg.start, seg.end)} days`}
              className={`h-full transition-[filter] hover:brightness-95 ${on ? "bg-gain-muted" : "bg-loss"}`}
              style={{ flex: `0 0 ${width}%` }}
            />
          );
        })}
      </div>
      <div className="mt-1.5 flex justify-between text-[10.5px] tabular-nums text-text-muted">
        <span>{formatDate(sliced[0].date)}</span>
        <span>{formatDate(sliced[Math.floor(sliced.length / 2)].date)}</span>
        <span>{formatDate(sliced[sliced.length - 1].date)}</span>
      </div>
      <div className="mt-2.5 text-[11.5px] text-text-secondary">
        {flipsInWindow} regime {flipsInWindow === 1 ? "change" : "changes"} over the{" "}
        {RANGE_WORD[range]} · currently {isOff ? "Risk-off" : "Risk-on"} for {data.days_in_state}{" "}
        days.
      </div>
    </section>
  );
}

interface FlipRow {
  date: string;
  fromState: string;
  toState: string;
  dur: number;
  vote: number | null;
}

function RecentChanges({
  data,
  sort,
  onSort,
}: {
  data: MacroRegime;
  sort: { key: FlipSortKey; dir: "asc" | "desc" };
  onSort: (key: FlipSortKey) => void;
}) {
  const rows = useMemo<FlipRow[]>(() => buildFlipRows(data), [data]);

  const sorted = useMemo(() => {
    const copy = [...rows];
    copy.sort((a, b) => {
      let x: number;
      let y: number;
      if (sort.key === "date") {
        x = Date.parse(a.date);
        y = Date.parse(b.date);
      } else if (sort.key === "dur") {
        x = a.dur;
        y = b.dur;
      } else {
        x = a.vote ?? -1;
        y = b.vote ?? -1;
      }
      return sort.dir === "asc" ? x - y : y - x;
    });
    return copy.slice(0, 10);
  }, [rows, sort]);

  const columns: Array<{ key: FlipSortKey | "change"; label: string; align: "left" | "right" }> = [
    { key: "date", label: "Date", align: "left" },
    { key: "change", label: "Change", align: "left" },
    { key: "dur", label: "Held for", align: "right" },
    { key: "vote", label: "Votes at flip", align: "right" },
  ];

  return (
    <section className="border border-t-0 border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <h2 className="ix-label m-0">Recent regime changes</h2>
        <span className="text-[11px] tabular-nums text-text-muted">
          {sorted.length} most recent
        </span>
      </div>
      {rows.length === 0 ? (
        <div className="flex h-[120px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
          No regime changes recorded yet.
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full border-collapse text-[length:var(--ix-fs)] tabular-nums">
            <thead>
              <tr className="border-b border-border-strong bg-zebra">
                {columns.map((col) => {
                  const sortable = col.key !== "change";
                  const isSorted = sortable && col.key === sort.key;
                  return (
                    <th
                      key={col.key}
                      scope="col"
                      tabIndex={sortable ? 0 : undefined}
                      aria-sort={
                        isSorted ? (sort.dir === "asc" ? "ascending" : "descending") : "none"
                      }
                      onClick={sortable ? () => onSort(col.key as FlipSortKey) : undefined}
                      onKeyDown={
                        sortable
                          ? (e) => {
                              if (e.key === "Enter" || e.key === " ") {
                                e.preventDefault();
                                onSort(col.key as FlipSortKey);
                              }
                            }
                          : undefined
                      }
                      className={`px-[14px] py-[9px] text-[10px] font-bold uppercase tracking-[0.05em] ${
                        col.align === "right" ? "text-right" : "text-left"
                      } ${sortable ? "cursor-pointer select-none" : ""} ${
                        isSorted ? "text-text-primary" : "text-text-muted"
                      } ${sortable ? "hover:text-text-primary" : ""}`}
                    >
                      <span className="inline-flex items-center gap-1">
                        {col.label}
                        {isSorted && (
                          <span className="text-[9px] text-accent">
                            {sort.dir === "asc" ? "▲" : "▼"}
                          </span>
                        )}
                      </span>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row, i) => (
                <tr
                  key={`${row.date}-${i}`}
                  className={`border-t border-border transition-colors hover:bg-layer-hover ${
                    i % 2 ? "bg-zebra" : "bg-surface-2"
                  }`}
                >
                  <td className="whitespace-nowrap px-[14px] py-[var(--ix-cell)] text-text-secondary">
                    {formatDate(row.date)}
                  </td>
                  <td className="px-[14px] py-[var(--ix-cell)]">
                    <span className="inline-flex items-center gap-[7px]">
                      <span className="text-[11px] text-text-muted">
                        {row.fromState === "risk_off" ? "Risk-off" : "Risk-on"}
                      </span>
                      <span className="text-text-muted">→</span>
                      <span
                        className={`font-bold ${row.toState === "risk_off" ? "text-loss" : "text-gain"}`}
                      >
                        {row.toState === "risk_off" ? "Risk-off" : "Risk-on"}
                      </span>
                    </span>
                  </td>
                  <td className="px-[14px] py-[var(--ix-cell)] text-right text-text-primary">
                    {row.dur} days
                  </td>
                  <td className="px-[14px] py-[var(--ix-cell)] text-right text-text-secondary">
                    {row.vote === null ? "--" : `${row.vote}/3`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/**
 * Recent regime changes from `recent_flips`. Each flip is the date the state
 * changed *to* `state`; held-for runs to the next flip (or `as_of`). The flip
 * list carries no vote count, so we look it up from `history` by date where
 * present and degrade to `null` ("--") otherwise.
 */
function buildFlipRows(data: MacroRegime): FlipRow[] {
  const flips = [...data.recent_flips].sort((a, b) => a.date.localeCompare(b.date));
  if (flips.length === 0) return [];

  const voteByDate = new Map<string, number>();
  for (const point of data.history) voteByDate.set(point.date, point.vote_count);

  const rows: FlipRow[] = [];
  for (let i = 0; i < flips.length; i += 1) {
    const flip = flips[i];
    const prevState = i > 0 ? flips[i - 1].state : flip.state === "risk_off" ? "risk_on" : "risk_off";
    const end = flips[i + 1]?.date ?? data.as_of;
    rows.push({
      date: flip.date,
      fromState: prevState,
      toState: flip.state,
      dur: daysBetween(flip.date, end),
      vote: voteByDate.get(flip.date) ?? null,
    });
  }
  return rows;
}

// ── States & shell ──────────────────────────────────────────────────────────

function LoadingSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading regime data" className="flex flex-col gap-px">
      <div className="h-[118px] animate-pulse bg-surface-2" />
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
        {Array.from({ length: 5 }).map((_, i) => (
          <div key={i} className="h-[84px] animate-pulse bg-surface-2" />
        ))}
      </div>
      <div className="mt-2 h-[60px] animate-pulse bg-surface-2" />
      <div className="mt-2 grid gap-px bg-border [grid-template-columns:0.85fr_1.35fr]">
        <div className="h-[440px] animate-pulse bg-surface-2" />
        <div className="h-[440px] animate-pulse bg-surface-2" />
      </div>
    </div>
  );
}

function EmptyState({ onRetry }: { onRetry: () => void }) {
  return (
    <div className="flex flex-col items-center gap-3 border border-border bg-surface-2 px-4 py-16 text-center">
      <svg
        width="34"
        height="34"
        viewBox="0 0 24 24"
        fill="none"
        aria-hidden="true"
        className="text-text-muted"
      >
        <circle cx="12" cy="12" r="9" stroke="currentColor" strokeWidth="1.4" />
        <path
          d="M7 13.5C8.4 10.5 9.7 8.5 12 8.5s3.6 2 5 5"
          stroke="currentColor"
          strokeWidth="1.4"
          fill="none"
        />
      </svg>
      <div className="max-w-[380px] text-[14px] text-text-secondary">
        The regime signal has not been populated yet — no vote history is available to display.
      </div>
      <button
        type="button"
        onClick={onRetry}
        className="border border-border-strong bg-field px-4 py-[7px] text-[12.5px] font-bold text-text-primary transition-colors hover:bg-layer-hover"
      >
        Reload
      </button>
    </div>
  );
}

function MacroShell({ children }: { children: React.ReactNode }) {
  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">{children}</div>
  );
}
