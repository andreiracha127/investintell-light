"use client";

/**
 * Drift / alerts section for the portfolio overview page (Sprint C).
 *
 * Loads the latest persisted drift evaluation via GET /portfolios/{id}/alerts
 * and renders a status badge (green ok / orange maintenance / red urgent) plus
 * three small breach lists: position drift, asset-class breach, and overlap.
 *
 * The frontend computes NO finance: every number (weights, drifts, exposures,
 * caps) is read straight off the backend payload. Weights/drifts/exposures are
 * decimal fractions (0.30 = 30%); formatPercent handles the × 100.
 *
 * Breach item shapes are typed locally from the documented contract — the
 * backend serializes them as opaque dicts (BreachesView.*_breaches: list[dict]),
 * so we cast at the boundary and read defensively.
 */
import { useQuery } from "@tanstack/react-query";

import { getPortfolioAlerts, type PortfolioAlerts } from "@/lib/api/client";
import { Card } from "@/components/ui/panels";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { formatDate, formatPercent } from "@/lib/format";

// ── Breach item shapes (documented contract; backend serializes as dict) ──────

type PositionDriftItem = {
  ticker: string;
  current_weight?: number;
  target_weight?: number;
  drift_abs?: number;
  drift_rel?: number;
  breach?: boolean;
  status?: string;
};

type ClassBreachItem = {
  asset_class: string;
  current_weight?: number;
  min_weight?: number | null;
  max_weight?: number | null;
  kind?: "below_min" | "above_max" | string;
};

type OverlapBreachItem = {
  security_key: string;
  exposure?: number;
  overlap_cap?: number;
};

// ── Status badge ──────────────────────────────────────────────────────────────

const STATUS_META: Record<
  string,
  { label: string; colorClass: string }
> = {
  ok: { label: "OK", colorClass: "border-gain text-gain bg-gain/10" },
  maintenance: {
    label: "Maintenance",
    colorClass: "border-accent text-accent bg-accent/10",
  },
  urgent: { label: "Urgent", colorClass: "border-loss text-loss bg-loss/10" },
};

/** Square status pill colored by worst_status (unknown → neutral). */
function StatusBadge({ status }: { status: string }) {
  const meta = STATUS_META[status] ?? {
    label: status,
    colorClass: "border-border text-text-muted bg-surface-2",
  };
  return (
    <span
      aria-label={`Drift status: ${status}`}
      className={`inline-block border px-2.5 py-0.5 text-[12px] font-bold uppercase tracking-[0.07em] ${meta.colorClass}`}
    >
      {meta.label}
    </span>
  );
}

// ── Breach lists ──────────────────────────────────────────────────────────────

const LIST_LABEL_CLASS =
  "mb-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted";
const ROW_CLASS =
  "flex items-center justify-between gap-3 border-b border-border py-1.5 text-[12px] last:border-b-0";

/** Optional fraction → percent text, or "—" when absent. */
function pctOrDash(value: number | null | undefined, dp = 1): string {
  return value == null ? "—" : formatPercent(value, dp);
}

function PositionDriftList({ items }: { items: PositionDriftItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <p className={LIST_LABEL_CLASS}>Position drift</p>
      <ul className="m-0 list-none p-0">
        {items.map((d) => (
          <li key={d.ticker} className={ROW_CLASS}>
            <span className="font-bold text-text-primary">{d.ticker}</span>
            <span className="tabular-nums text-text-secondary">
              {pctOrDash(d.current_weight)} → {pctOrDash(d.target_weight)}
              {d.drift_abs != null && (
                <span className="ml-2 font-bold text-loss">
                  Δ {pctOrDash(d.drift_abs)}
                </span>
              )}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ClassBreachList({ items }: { items: ClassBreachItem[] }) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <p className={LIST_LABEL_CLASS}>Asset-class breach</p>
      <ul className="m-0 list-none p-0">
        {items.map((c) => {
          const bound =
            c.kind === "below_min"
              ? `min ${pctOrDash(c.min_weight)}`
              : `max ${pctOrDash(c.max_weight)}`;
          return (
            <li key={c.asset_class} className={ROW_CLASS}>
              <span className="capitalize text-text-primary">
                {c.asset_class.replace(/_/g, " ")}
              </span>
              <span className="tabular-nums text-text-secondary">
                {pctOrDash(c.current_weight)}{" "}
                <span className="text-text-muted">({bound})</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function OverlapBreachList({
  items,
  reportDate,
}: {
  items: OverlapBreachItem[];
  reportDate: string | null | undefined;
}) {
  if (items.length === 0) return null;
  return (
    <div className="mt-3">
      <p className={LIST_LABEL_CLASS}>
        Overlap
        {reportDate && (
          <span className="ml-2 font-normal normal-case tracking-normal text-text-muted">
            as of {formatDate(reportDate)}
          </span>
        )}
      </p>
      <ul className="m-0 list-none p-0">
        {items.map((o) => (
          <li key={o.security_key} className={ROW_CLASS}>
            <span className="font-bold text-text-primary">{o.security_key}</span>
            <span className="tabular-nums text-text-secondary">
              {pctOrDash(o.exposure)}{" "}
              <span className="text-text-muted">
                (cap {pctOrDash(o.overlap_cap)})
              </span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}

// ── Main section ──────────────────────────────────────────────────────────────

export function PortfolioDriftSection({
  portfolioId,
}: {
  portfolioId: number;
}) {
  const alertsQuery = useQuery({
    queryKey: ["portfolio", portfolioId, "alerts"],
    queryFn: ({ signal }) => getPortfolioAlerts(portfolioId, signal),
    staleTime: 300_000, // ~5 min
    retry: retryPolicy,
  });

  if (alertsQuery.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading drift alerts"
        className="h-[88px] animate-pulse bg-surface-2"
      />
    );
  }
  if (alertsQuery.isError) {
    return (
      <ErrorPanel
        title="Failed to load drift alerts"
        message={alertsQuery.error.message}
        onRetry={() => alertsQuery.refetch()}
      />
    );
  }

  const alerts: PortfolioAlerts = alertsQuery.data;
  const breaches = alerts.breaches ?? {};
  const positionDrifts = (breaches.position_drifts ??
    []) as PositionDriftItem[];
  const classBreaches = (breaches.class_breaches ?? []) as ClassBreachItem[];
  const overlapBreaches = (breaches.overlap_breaches ??
    []) as OverlapBreachItem[];

  const hasBreaches =
    positionDrifts.length > 0 ||
    classBreaches.length > 0 ||
    overlapBreaches.length > 0;

  return (
    <section>
      <Card title="Drift & alerts">
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={alerts.worst_status} />
          {alerts.evaluated_at ? (
            <span className="text-[12px] text-text-muted">
              Last evaluated {formatDate(alerts.evaluated_at.split("T")[0]!)}
            </span>
          ) : (
            <span className="text-[12px] text-text-muted">
              Not yet evaluated
            </span>
          )}
        </div>

        {hasBreaches ? (
          <>
            <PositionDriftList items={positionDrifts} />
            <ClassBreachList items={classBreaches} />
            <OverlapBreachList
              items={overlapBreaches}
              reportDate={breaches.overlap_report_date}
            />
          </>
        ) : (
          <p className="mt-3 text-[12px] text-text-secondary">
            No drift alerts.
          </p>
        )}
      </Card>
    </section>
  );
}
