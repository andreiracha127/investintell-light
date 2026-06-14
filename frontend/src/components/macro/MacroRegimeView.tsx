"use client";

/**
 * Macro regime view — vote2of3 ensemble dashboard.
 *
 * Fetches GET /macro/regime (worker regime_composite) and renders:
 *   - Title + explainer
 *   - State badge (RISK-ON / RISK-OFF) with "since" and "days in state"
 *   - Vote breakdown chips (credit / trend / nfci) + vote count
 *   - KPI tiles (credit-vote provenance + NFCI)
 *   - Timeline strip chart of recent regime flips
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import type { Options } from "highcharts";

import { ApiError, fetchMacroRegime } from "@/lib/api/client";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card, KpiTile, PageTitle, valueTone } from "@/components/ui/panels";
import { buildHcRegimeStripOption } from "@/lib/charts/hc/regime";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatDate, formatNumber } from "@/lib/format";

// ── State badge ────────────────────────────────────────────────────────────

/**
 * Square-cut pill badge: border + wash background + status text.
 * RISK-ON → gain colors. RISK-OFF → loss colors.
 */
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

// ── Vote chip ──────────────────────────────────────────────────────────────

/**
 * One signal's vote. Active (firing → defensive) reads in loss tone; inactive
 * is muted. The ensemble flips to risk-off when ≥2 chips are active.
 */
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

// ── KPI helper (null-safe) ─────────────────────────────────────────────────

function num(value: number | null | undefined, dp: number): string {
  return value !== null && value !== undefined
    ? formatNumber(value, dp)
    : "—";
}

// ── Main view component ────────────────────────────────────────────────────

export function MacroRegimeView() {
  // Design tokens readable only from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const query = useQuery({
    queryKey: ["macro-regime"],
    queryFn: ({ signal }) => fetchMacroRegime(signal),
    staleTime: 300_000, // regime changes slowly — 5 min cache is appropriate
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // All hooks before early returns.
  const stripOption = useMemo<Options | null>(() => {
    if (!query.data || !colors) return null;
    return buildHcRegimeStripOption(query.data.recent_flips, colors, query.data.as_of);
  }, [query.data, colors]);

  // 404 → regime not materialized yet.
  if (
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 404
  ) {
    return (
      <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
        <PageTitle title="Macro regime" />
        <div className="border border-border bg-surface-2 ix-pad text-[13px] text-text-secondary">
          Regime data not available — the signal has not been populated yet.
        </div>
      </div>
    );
  }

  if (query.isPending) {
    return (
      <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
        <PageTitle title="Macro regime" />
        <div
          aria-busy="true"
          aria-label="Loading regime data"
          className="flex flex-col gap-px"
        >
          <div className="h-[88px] bg-surface-2 animate-pulse" />
          <div className="h-[240px] bg-surface-2 animate-pulse" />
        </div>
      </div>
    );
  }

  if (query.isError) {
    return (
      <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
        <PageTitle title="Macro regime" />
        <ErrorPanel
          title="Failed to load regime data"
          message={query.error.message}
          onRetry={() => query.refetch()}
        />
      </div>
    );
  }

  const data = query.data;
  const { signal, votes } = data;

  /**
   * distance_pct scale: computed in backend/app/api/routes/macro.py as
   *   100.0 * (ratio - p20_5y) / p20_5y
   * This is already in percent-points (e.g. 5.2 means the credit ratio is 5.2%
   * above the 20th-percentile trigger). Display with 2dp, no conversion.
   */
  const distancePctDisplay =
    signal.distance_pct !== null && signal.distance_pct !== undefined
      ? `${formatNumber(signal.distance_pct, 2)} pp`
      : "—";

  return (
    <div className="mx-auto max-w-[1360px] px-[clamp(14px,3vw,28px)] pb-10 pt-5">
      <PageTitle
        title="Macro regime"
        meta="Vote ensemble (vote2of3): risk-off when at least two of credit (HYG/IEF), trend (SPY vs 10-month average) and NFCI fire together."
      />

      {/* State badge + since/days row */}
      <div className="mb-4 flex flex-wrap items-center gap-3">
        <StateBadge state={data.state} />
        <span className="text-[13px] text-text-secondary tabular-nums">
          {data.last_flip
            ? `since ${formatDate(data.last_flip)} · ${data.days_in_state} days`
            : `${data.days_in_state} days in state`}
        </span>
      </div>

      {/* Vote breakdown */}
      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-[12px] uppercase tracking-[0.06em] text-text-secondary">
          Votes {data.vote_count}/3
        </span>
        <VoteChip label="Credit" active={votes.credit} />
        <VoteChip label="Trend" active={votes.trend} />
        <VoteChip label="NFCI" active={votes.nfci} />
      </div>

      {/* KPI tiles — credit-vote provenance + NFCI */}
      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile label="HYG/IEF ratio" value={num(signal.ratio, 3)} />
        <KpiTile label="Credit trigger (p20)" value={num(signal.p20_5y, 3)} />
        <KpiTile
          label="Distance to trigger"
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

      {/* Timeline strip — gated solely on stripOption (null when no periods). */}
      {stripOption && (
        <Card title="Regime history">
          <HighchartsChart options={stripOption} className="h-[160px] w-full" />
        </Card>
      )}
    </div>
  );
}
