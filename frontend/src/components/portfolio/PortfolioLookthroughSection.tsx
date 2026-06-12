"use client";

/**
 * Consolidated exposure section for the portfolio overview page.
 *
 * Fetches portfolio look-through data and delegates rendering to the shared
 * `LookthroughPanel`. 404 → renders nothing. Any other error is surfaced
 * via the standard error panel pattern.
 *
 * Shape note: PortfolioLookthroughResponse differs from FundLookthroughResponse:
 *   - No top-level `report_date` (uses `oldest_report_date` instead)
 *   - Has portfolio-level fields: total_value, cash_weight_pct, expanded_weight_pct,
 *     sum_pct_total, n_funds_expanded, unexpanded[]
 *   - summary is NOT a nested LookthroughSummaryOut — the portfolio response IS
 *     its own summary; we project it onto LookthroughSummaryOut-compatible props.
 *
 * LookthroughPanel accepts the shared `LookthroughSummary` shape. We project
 * the portfolio fields pragmatically: sum_pct_total → sum_pct_total, oldest_
 * report_date → oldest_report_date, coverage is not provided by the portfolio
 * endpoint (shows "—"). This is intentional — no leaky abstraction.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchPortfolioLookthrough } from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { LookthroughPanel } from "@/components/lookthrough/LookthroughPanel";
import { chartColors, type ChartColors } from "@/lib/charts/theme";
import { formatDate, formatNumber } from "@/lib/format";
import type { LookthroughSummary } from "@/lib/api/client";

export function PortfolioLookthroughSection({
  portfolioId,
}: {
  portfolioId: number;
}) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const query = useQuery({
    queryKey: ["portfolio-lookthrough", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioLookthrough(portfolioId, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // 404 or empty dimensions → render nothing silently.
  if (
    query.isError &&
    query.error instanceof ApiError &&
    query.error.status === 404
  ) {
    return null;
  }

  if (query.isPending) {
    return (
      <div
        aria-busy="true"
        aria-label="Loading consolidated exposure"
        className="h-[120px] bg-surface-2 animate-pulse"
      />
    );
  }

  if (query.isError) {
    return (
      <ErrorPanel
        title="Failed to load consolidated exposure"
        message={query.error.message}
        onRetry={() => query.refetch()}
      />
    );
  }

  const data = query.data;

  // No dimensions → nothing to show.
  if (Object.keys(data.dimensions).length === 0) return null;

  // Project portfolio response onto the shared LookthroughSummary shape.
  // Fields not provided by the portfolio endpoint remain null.
  const summary: LookthroughSummary = {
    sum_pct_total: data.sum_pct_total,
    direct_pct: null,
    indirect_pct: null,
    expanded_fund_pct: data.expanded_weight_pct,
    nondecomposable_fund_pct: null,
    derivatives_gross_pct: null,
    derivatives_net_pct: null,
    unidentified_pct: null,
    // Coverage is not present in the portfolio response; callers see "—".
    coverage_pct: null,
    n_holdings: null,
    n_children_expanded: data.n_funds_expanded,
    oldest_report_date: data.oldest_report_date,
  };

  return (
    <section>
      {/* Section header */}
      <div className="mb-3">
        <h2 className="ix-label m-0">Consolidated exposure</h2>
        <p className="text-[12px] text-text-secondary mt-0.5">
          Across all portfolio funds
          {data.oldest_report_date
            ? ` · as of ${formatDate(data.oldest_report_date)}`
            : ""}
          {data.cash_weight_pct > 0 && (
            <>
              {" "}
              <span className="text-text-muted">
                · cash {formatNumber(data.cash_weight_pct, 1)}%
              </span>
            </>
          )}
        </p>
      </div>

      {colors && (
        <LookthroughPanel
          dimensions={data.dimensions}
          summary={summary}
          reportDate={data.oldest_report_date}
          colors={colors}
          expandedLabel="Funds expanded"
          expandedCount={data.n_funds_expanded}
        />
      )}
    </section>
  );
}
