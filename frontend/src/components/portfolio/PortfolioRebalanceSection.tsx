"use client";

/**
 * Rebalancing section for the portfolio overview page.
 *
 * Query 1: fetchRebalancePolicy — 404 means no policy configured → renders null.
 * Query 2: fetchRebalancePreview — enabled only when a policy exists.
 *
 * Scale note (verified against backend/app/schemas/rebalance.py docstring):
 *   "Bandas e pesos em frações decimais (0.05 = 5 p.p.), convenção do projeto;
 *    turnover em % (50.0 = metade do valor investido girado one-way)."
 *   - current_weight, target_weight, drift_abs, band_abs, band_rel → fractions
 *   - ProposalOut.weights → target weight fractions per ticker
 *   - RebalancePreviewResponse.invested_value → currency units
 *   - turnover_pct → already in percent-points (do NOT multiply × 100)
 *
 * ProposalOut carries only target weights (no per-trade currency amounts).
 * Trade dollar values are computed here as:
 *   trade_$ = (proposed_weight - current_weight) × invested_value
 * This is display-only arithmetic on backend-provided numbers; no finance.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  fetchRebalancePolicy,
  fetchRebalancePreview,
  type PositionDrift,
  type RebalancePreview,
  type RebalancePolicy,
} from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card } from "@/components/ui/panels";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { buildHcDriftBandsOption } from "@/lib/charts/hc/rebalance";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { formatCurrency, formatDate, formatNumber, formatPercent } from "@/lib/format";

// ── Optimizer label helpers ───────────────────────────────────────────────────

/** Map from backend objective strings to product copy. */
const OBJECTIVE_LABELS: Record<string, string> = {
  min_cvar:           "Minimum CVaR",
  min_vol:            "Minimum variance",
  erc:                "Equal risk contribution",
  max_diversification:"Maximum diversification",
  equal_weight:       "Equal weight",
  bl_utility:         "Black–Litterman utility",
};

/** Humanize an objective string: use label map, fall back to title-cased words. */
function humanizeObjective(raw: string): string {
  return OBJECTIVE_LABELS[raw] ?? raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

/**
 * Humanize a solver status string.
 * Returns `{ label, isOptimal }` so the caller can apply emphasis when not optimal.
 */
function humanizeSolverStatus(raw: string): { label: string; isOptimal: boolean } {
  if (raw === "optimal") return { label: "Converged", isOptimal: true };
  return {
    label: raw.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase()),
    isOptimal: false,
  };
}

// ── Decision pill ─────────────────────────────────────────────────────────────

/**
 * Square pill badge for the rebalance decision.
 *   proposal    → warn (accent) style
 *   drift_alert → loss style
 *   no_action   → neutral muted style
 */
function DecisionPill({ decision }: { decision: string }) {
  let label: string;
  let colorClass: string;

  switch (decision) {
    case "proposal":
      label = "Proposal";
      colorClass = "border-accent text-accent bg-accent/10";
      break;
    case "drift_alert":
      label = "Drift alert";
      colorClass = "border-loss text-loss bg-loss/10";
      break;
    default:
      label = "No action";
      colorClass = "border-border text-text-muted bg-surface-2";
  }

  return (
    <span
      aria-label={`Rebalance decision: ${label}`}
      className={`inline-block border px-2.5 py-0.5 text-[12px] font-bold uppercase tracking-[0.07em] ${colorClass}`}
    >
      {label}
    </span>
  );
}

// ── Trigger pill ──────────────────────────────────────────────────────────────

/** Small indicator pill for active triggers. */
function TriggerPill({ label }: { label: string }) {
  return (
    <span className="inline-block border border-border-strong bg-field px-2 py-0.5 text-[11px] text-text-secondary">
      {label}
    </span>
  );
}

// ── Policy summary line ───────────────────────────────────────────────────────

/**
 * Human-readable one-liner from a RebalancePolicy, e.g.:
 *   "Monthly · ±5.00% abs band · ±25.00% rel band"
 * Macro trigger appended when enabled.
 */
function policyLine(policy: RebalancePolicy): string {
  const freq =
    policy.frequency.charAt(0).toUpperCase() + policy.frequency.slice(1);
  // band_abs and band_rel are decimal fractions — formatPercent handles × 100.
  const absStr = formatPercent(policy.band_abs, 2);
  const relStr = formatPercent(policy.band_rel, 2);
  const macro = policy.macro_trigger_enabled ? " · Macro trigger on" : "";
  return `${freq} · ±${absStr} abs band · ±${relStr} rel band${macro}`;
}

// ── Proposal table ────────────────────────────────────────────────────────────

/**
 * Advisory trade table derived from ProposalOut.weights and the current drifts.
 *
 * ProposalOut.weights carries proposed target weights as decimal fractions.
 * It does NOT carry per-trade currency amounts, so we compute:
 *   trade_$ = (proposed_weight - current_weight) × invested_value
 * This is purely display arithmetic; "Buy" when positive, "Sell" when negative.
 */
function ProposalTable({
  preview,
}: {
  preview: RebalancePreview;
}) {
  const { proposal, drifts, invested_value } = preview;

  // Build rows: merge proposal weights with current weights from drifts.
  const currentByTicker = new Map<string, number>(
    drifts.map((d) => [d.ticker, d.current_weight]),
  );

  const rows = Object.entries(proposal.weights)
    .map(([ticker, proposedWeight]) => {
      const currentWeight = currentByTicker.get(ticker) ?? 0;
      // Trade dollar: (proposed - current) × invested_value
      // invested_value is in currency units (backend schema).
      const tradeDollars = (proposedWeight - currentWeight) * invested_value;
      const delta = proposedWeight - currentWeight;
      return { ticker, proposedWeight, currentWeight, delta, tradeDollars };
    })
    .filter((r) => Math.abs(r.tradeDollars) > 0.01) // skip noise
    .sort((a, b) => b.tradeDollars - a.tradeDollars);

  if (rows.length === 0) return null;

  // Turnover is already in percent-points from the backend.
  // Fallback: compute from deltas × 100 × 0.5 (one-way) if ever absent.
  const displayTurnover = proposal.turnover_pct;

  // Hoist solver status destructuring out of the JSX IIFE.
  const { label: statusLabel, isOptimal } = humanizeSolverStatus(proposal.solver_status);

  const TH_CLASS =
    "px-2.5 py-2 text-[11px] font-bold uppercase tracking-[0.07em] " +
    "text-text-muted border-b border-border bg-surface-2 text-right";
  const TH_LEFT = TH_CLASS + " text-left";
  const TD_CLASS = "px-2.5 py-2 text-[12px] tabular-nums text-right";
  const TD_LEFT = TD_CLASS + " text-left";

  return (
    <div className="mt-3">
      <div className="overflow-x-auto border border-border">
        <table className="w-full min-w-[460px] border-collapse">
          <thead>
            <tr>
              <th className={TH_LEFT}>Asset</th>
              <th className={TH_CLASS}>Current</th>
              <th className={TH_CLASS}>Target</th>
              <th className={TH_CLASS}>Δ</th>
              <th className={TH_CLASS}>Action</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row, i) => {
              const isBuy = row.tradeDollars > 0;
              const actionTone = isBuy ? "text-gain" : "text-loss";
              const actionLabel = isBuy
                ? `Buy ${formatCurrency(row.tradeDollars)}`
                : `Sell ${formatCurrency(-row.tradeDollars)}`;
              const deltaSign = row.delta >= 0 ? "+" : "";
              return (
                <tr
                  key={row.ticker}
                  className={`border-b border-border last:border-b-0 ${i % 2 === 1 ? "bg-zebra" : ""}`}
                >
                  <td className={TD_LEFT + " font-bold text-text-primary"}>
                    {row.ticker}
                  </td>
                  <td className={TD_CLASS + " text-text-secondary"}>
                    {formatPercent(row.currentWeight, 2)}
                  </td>
                  <td className={TD_CLASS + " text-text-secondary"}>
                    {formatPercent(row.proposedWeight, 2)}
                  </td>
                  <td
                    className={`${TD_CLASS} ${row.delta >= 0 ? "text-gain" : "text-loss"}`}
                  >
                    {deltaSign}{formatPercent(Math.abs(row.delta), 2)}
                  </td>
                  <td className={`${TD_CLASS} font-bold ${actionTone}`}>
                    {actionLabel}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* Footer: turnover + advisory disclaimer */}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[11px] text-text-muted">
        <span>
          {/* turnover_pct is already in percent-points per the backend schema */}
          Estimated turnover: <b>{formatNumber(displayTurnover, 1)}%</b>{" "}
          <>
            (one-way · {humanizeObjective(proposal.objective)} ·{" "}
            <span className={isOptimal ? undefined : "text-loss"}>
              {statusLabel}
            </span>
            )
          </>
        </span>
        <span className="tabular-nums">
          Portfolio invested value: {formatCurrency(invested_value)}
        </span>
      </div>
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function PortfolioRebalanceSection({
  portfolioId,
}: {
  portfolioId: number;
}) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  // Query 1: policy — 404 means "no policy configured", render nothing.
  const policyQuery = useQuery({
    queryKey: ["rebalance-policy", portfolioId],
    queryFn: ({ signal }) => fetchRebalancePolicy(portfolioId, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // Query 2: preview — enabled only once we know a policy exists.
  // isSuccess already narrows data to be defined; the !== undefined guard is redundant.
  const policyExists = policyQuery.isSuccess;
  const previewQuery = useQuery({
    queryKey: ["rebalance-preview", portfolioId],
    queryFn: ({ signal }) => fetchRebalancePreview(portfolioId, signal),
    enabled: policyExists,
    staleTime: 60_000,
    retry: retryPolicy,
  });

  // Memoize the chart option — depends on drifts data and resolved colors.
  const driftOption = useMemo(() => {
    if (!previewQuery.data || !colors) return null;
    const drifts: PositionDrift[] = previewQuery.data.drifts;
    const { band_abs, band_rel } = previewQuery.data.policy;
    return buildHcDriftBandsOption(drifts, colors, band_abs, band_rel);
  }, [previewQuery.data, colors]);

  // ── All hooks above this line — early returns below ──────────────────────

  // 404 → no policy configured; render nothing silently.
  if (
    policyQuery.isError &&
    policyQuery.error instanceof ApiError &&
    policyQuery.error.status === 404
  ) {
    return null;
  }

  if (policyQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading rebalancing data"
        className="h-[88px] animate-pulse bg-surface-2"
      />
    );
  }

  if (policyQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load rebalance policy"
        message={policyQuery.error.message}
        onRetry={() => policyQuery.refetch()}
      />
    );
  }

  const policy = policyQuery.data;

  // ── Render the card ───────────────────────────────────────────────────────

  const preview = previewQuery.data;

  // Derive "band breach" trigger from drifts (any position with breach: true).
  const hasBandBreach = preview?.drifts.some((d) => d.breach) ?? false;

  return (
    <section>
      <Card title="Rebalancing">
        {/* Status row: decision pill + trigger pills */}
        <div className="flex flex-wrap items-center gap-2">
          {preview ? (
            <>
              <DecisionPill decision={preview.decision} />
              {preview.calendar_due && <TriggerPill label="Calendar due" />}
              {preview.macro_triggered && <TriggerPill label="Macro triggered" />}
              {hasBandBreach && <TriggerPill label="Band breach" />}
            </>
          ) : previewQuery.isPending ? (
            <span
              aria-busy="true"
              className="inline-block h-[26px] w-[90px] animate-pulse bg-surface-2"
            />
          ) : null}
        </div>

        {/* Policy summary line */}
        <p className="mt-2 text-[12px] text-text-secondary">
          {policyLine(policy)}
          {policy.last_evaluated_at && (
            <>
              {" · "}
              <span className="text-text-muted">
                Last evaluated{" "}
                {formatDate(policy.last_evaluated_at.split("T")[0]!)}
              </span>
            </>
          )}
        </p>

        {/* Preview error (policy exists but preview failed) */}
        {previewQuery.isError && (
          <ErrorPanel
            title="Failed to load rebalance preview"
            message={previewQuery.error.message}
            onRetry={() => previewQuery.refetch()}
          />
        )}

        {/* Drift chart */}
        {preview && preview.drifts.length > 0 && colors && driftOption && (
          <div className="mt-4">
            <p className="mb-1 text-[11px] font-bold uppercase tracking-[0.07em] text-text-muted">
              Position drift
            </p>
            {/* Height calculated from row count: 32px per bar row + 40px grid margins,
                minimum 120px. The chart wrapper receives its height from here. */}
            <div
              style={{
                height: `${Math.max(120, preview.drifts.length * 32 + 40)}px`, // 32px per bar row + 40px grid margins
              }}
            >
              <HighchartsChart options={driftOption} className="h-full w-full" />
            </div>
          </div>
        )}

        {/* Proposal table */}
        {preview && preview.decision === "proposal" && (
          <ProposalTable preview={preview} />
        )}

        {/* Advisory disclaimer footnote */}
        <p className="mt-3 text-[11px] text-text-muted">
          Proposals are never executed automatically.
        </p>
      </Card>
    </section>
  );
}
