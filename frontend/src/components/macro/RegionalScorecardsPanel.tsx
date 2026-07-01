"use client";

/**
 * Regional macro scorecards (Macro → Regional scorecards).
 *
 * Surfaces GET /macro/regional — per-region composites (0-100, 50 = historical
 * median) with their dimension breakdown and data-freshness weighting, exactly
 * as materialized by the macro_ingestion worker. No derived data: every score
 * and freshness status is rendered from the snapshot.
 */
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  fetchMacroRegional,
  type RegionScorecard,
} from "@/lib/api/client";
import { retryPolicy } from "@/components/screener/shared";
import { ErrorPanel, InfoDot } from "@/components/ui/panels";
import { formatDate, formatNumber, formatPercent } from "@/lib/format";

const REGION_LABELS: Record<string, string> = {
  US: "United States",
  EUROPE: "Europe",
  ASIA: "Asia",
  EM: "Emerging Markets",
};

/** Stable display order; unknown regions append alphabetically after these. */
const REGION_ORDER = ["US", "EUROPE", "ASIA", "EM"];

function orderedRegions(regions: Record<string, RegionScorecard>): RegionScorecard[] {
  const known = REGION_ORDER.filter((key) => key in regions).map((key) => regions[key]);
  const extra = Object.keys(regions)
    .filter((key) => !REGION_ORDER.includes(key))
    .sort()
    .map((key) => regions[key]);
  return [...known, ...extra];
}

function compositeTone(score: number): string {
  if (score >= 55) return "text-gain";
  if (score <= 45) return "text-loss";
  return "text-text-primary";
}

function dimensionLabel(key: string): string {
  return key
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

/** 0-100 dimension bar anchored on the 50 = historical-median midline. */
function DimensionBar({ label, score }: { label: string; score: number }) {
  const clamped = Math.max(0, Math.min(100, score));
  return (
    <div className="flex items-center gap-2">
      <span className="w-[96px] flex-none truncate text-[10.5px] text-text-secondary">
        {label}
      </span>
      <div className="relative h-[7px] min-w-0 flex-1 bg-surface-3">
        <div
          className={`h-full ${clamped >= 50 ? "bg-gain" : "bg-loss"}`}
          style={{ width: `${clamped}%` }}
        />
        <div className="absolute inset-y-0 left-1/2 w-px bg-border-strong" />
      </div>
      <span className="w-[30px] flex-none text-right text-[10.5px] font-bold tabular-nums text-text-primary">
        {formatNumber(clamped, 0)}
      </span>
    </div>
  );
}

function freshnessCounts(card: RegionScorecard): { fresh: number; decaying: number; stale: number } {
  const counts = { fresh: 0, decaying: 0, stale: 0 };
  for (const item of Object.values(card.data_freshness)) counts[item.status] += 1;
  return counts;
}

function RegionCard({ card }: { card: RegionScorecard }) {
  const dims = Object.entries(card.dimensions).sort(([a], [b]) => a.localeCompare(b));
  const fresh = freshnessCounts(card);
  return (
    <div className="ix-pad flex min-w-0 flex-col gap-3 bg-surface-2">
      <div className="flex items-baseline justify-between gap-2">
        <div className="min-w-0">
          <div className="text-[12.5px] font-bold text-text-primary">
            {REGION_LABELS[card.region] ?? card.region}
          </div>
          <div className="text-[10.5px] tabular-nums text-text-muted">
            Coverage {formatPercent(card.coverage, 0)}
          </div>
        </div>
        <div className="text-right">
          <div
            className={`text-[24px] font-bold leading-none tabular-nums ${compositeTone(card.composite_score)}`}
          >
            {formatNumber(card.composite_score, 0)}
          </div>
          <div className="text-[10px] uppercase tracking-[0.07em] text-text-muted">
            Composite
          </div>
        </div>
      </div>

      {dims.length > 0 && (
        <div className="flex flex-col gap-1.5">
          {dims.map(([key, dim]) => (
            <DimensionBar key={key} label={dimensionLabel(key)} score={dim.score} />
          ))}
        </div>
      )}

      <div className="mt-auto flex items-center gap-3 border-t border-border pt-2 text-[10.5px] tabular-nums text-text-muted">
        <span className="inline-flex items-center gap-1">
          <span className="h-[7px] w-[7px] rounded-full bg-gain" />
          {fresh.fresh} fresh
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-[7px] w-[7px] rounded-full bg-chart-bar-mute" />
          {fresh.decaying} decaying
        </span>
        <span className="inline-flex items-center gap-1">
          <span className="h-[7px] w-[7px] rounded-full bg-loss" />
          {fresh.stale} stale
        </span>
      </div>
    </div>
  );
}

export function RegionalScorecardsPanel() {
  const query = useQuery({
    queryKey: ["macro-regional"],
    queryFn: ({ signal }) => fetchMacroRegional(signal),
    staleTime: 300_000,
    retry: retryPolicy,
  });

  const notMaterialized =
    query.isError && query.error instanceof ApiError && query.error.status === 404;

  return (
    <section className="border border-t-0 border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <div className="flex items-center gap-1.5">
          <h2 className="ix-label m-0">Regional scorecards</h2>
          <InfoDot tip="Macro health by region: a 0–100 composite (50 = the region's own historical median) built from growth, credit-cycle and fiscal dimensions, weighted by how fresh each underlying series is." />
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
          className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]"
        >
          {Array.from({ length: 4 }).map((_, i) => (
            <div key={i} className="h-[220px] animate-pulse bg-surface-2" />
          ))}
        </div>
      ) : notMaterialized ? (
        <div className="px-[var(--ix-pad)] py-6 text-[13px] text-text-muted">
          Regional scorecards have not been materialized yet — the macro
          ingestion worker has not populated this dataset.
        </div>
      ) : query.isError ? (
        <div className="p-[var(--ix-pad)]">
          <ErrorPanel
            title="Failed to load regional scorecards"
            message={query.error.message}
            onRetry={() => query.refetch()}
          />
        </div>
      ) : (
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(240px,1fr))]">
          {orderedRegions(query.data.regions).map((card) => (
            <RegionCard key={card.region} card={card} />
          ))}
        </div>
      )}
    </section>
  );
}
