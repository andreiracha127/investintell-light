"use client";

/**
 * Global macro risk indicators (Macro → Global conditions).
 *
 * Surfaces GET /macro/global-indicators — four 0-100 scores materialized by
 * the macro_ingestion worker. Polarity varies by field: geopolitical risk and
 * energy stress are risk measures (higher = worse), commodity stress reflects
 * market stress, USD strength is directional (neither pole is "bad").
 */
import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchMacroGlobalIndicators } from "@/lib/api/client";
import { retryPolicy } from "@/components/screener/shared";
import { ErrorPanel, InfoDot } from "@/components/ui/panels";
import { formatDate, formatNumber } from "@/lib/format";

interface IndicatorSpec {
  key: "geopolitical_risk_score" | "energy_stress" | "commodity_stress" | "usd_strength";
  label: string;
  tip: string;
  /** Risk polarity: high scores read as stress (loss tone). */
  risk: boolean;
}

const INDICATORS: IndicatorSpec[] = [
  {
    key: "geopolitical_risk_score",
    label: "Geopolitical Risk",
    tip: "Percentile-ranked geopolitical risk (0–100). Higher means today's headline risk sits further above its own history.",
    risk: true,
  },
  {
    key: "energy_stress",
    label: "Energy Stress",
    tip: "Energy market stress (0–100). Higher readings flag disorderly moves in oil and gas prices.",
    risk: true,
  },
  {
    key: "commodity_stress",
    label: "Commodity Stress",
    tip: "Broad commodity market stress (0–100). Elevated values often accompany inflation shocks and supply disruptions.",
    risk: true,
  },
  {
    key: "usd_strength",
    label: "USD Strength",
    tip: "US dollar strength versus its own history (0–100). Directional — a strong dollar tightens global funding but is not inherently risk-off.",
    risk: false,
  },
];

function scoreTone(score: number, risk: boolean): string {
  if (!risk) return "text-text-primary";
  if (score >= 66) return "text-loss";
  if (score >= 33) return "text-text-primary";
  return "text-gain";
}

/** Flat 0-100 meter — hairline track, tone-matched fill (square system). */
function ScoreMeter({ score, risk }: { score: number; risk: boolean }) {
  const clamped = Math.max(0, Math.min(100, score));
  const fill = !risk
    ? "bg-chart-bar"
    : clamped >= 66
      ? "bg-loss"
      : clamped >= 33
        ? "bg-chart-bar"
        : "bg-gain";
  return (
    <div
      role="meter"
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={Math.round(clamped)}
      className="mt-2 h-[5px] w-full bg-surface-3"
    >
      <div className={`h-full ${fill}`} style={{ width: `${clamped}%` }} />
    </div>
  );
}

export function GlobalIndicatorsPanel() {
  const query = useQuery({
    queryKey: ["macro-global-indicators"],
    queryFn: ({ signal }) => fetchMacroGlobalIndicators(signal),
    staleTime: 300_000,
    retry: retryPolicy,
  });

  const notMaterialized =
    query.isError && query.error instanceof ApiError && query.error.status === 404;

  return (
    <section className="border border-t-0 border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <div className="flex items-center gap-1.5">
          <h2 className="ix-label m-0">Global conditions</h2>
          <InfoDot tip="Worldwide risk backdrop in four 0–100 scores: geopolitics, energy, commodities and the dollar. Scores are percentile ranks against each series' own history." />
        </div>
        {query.data && (
          <span className="text-[11px] tabular-nums text-text-muted">
            As of {formatDate(query.data.as_of_date)}
          </span>
        )}
      </div>

      {query.isPending ? (
        <div
          aria-busy="true"
          className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]"
        >
          {INDICATORS.map((spec) => (
            <div key={spec.key} className="h-[96px] animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : notMaterialized ? (
        <div className="px-[var(--ix-pad)] py-6 text-[13px] text-text-muted">
          Global indicators have not been materialized yet — the macro ingestion
          worker has not populated this dataset.
        </div>
      ) : query.isError ? (
        <div className="p-[var(--ix-pad)]">
          <ErrorPanel
            title="Failed to load global indicators"
            message={query.error.message}
            onRetry={() => query.refetch()}
          />
        </div>
      ) : (
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(180px,1fr))]">
          {INDICATORS.map((spec) => {
            const score = query.data[spec.key];
            return (
              <div key={spec.key} className="ix-pad bg-surface-2">
                <div className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.08em] text-text-muted">
                  <span>{spec.label}</span>
                  <InfoDot tip={spec.tip} />
                </div>
                <div
                  className={`mt-1.5 text-[20px] font-bold tabular-nums ${scoreTone(score, spec.risk)}`}
                >
                  {formatNumber(score, 0)}
                  <span className="ml-1 text-[11px] font-normal text-text-muted">/ 100</span>
                </div>
                <ScoreMeter score={score} risk={spec.risk} />
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}
