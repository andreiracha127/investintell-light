"use client";

/**
 * Consolidated exposure (look-through) for the portfolio page — Claude Design.
 *
 * Fetches one portfolio look-through hierarchy and renders the exposure view:
 * a KPI strip plus one Sunburst replacing the old four heavy dimension tabs.
 *
 * The shared `LookthroughPanel` (bar variant) stays in use by the fund pages;
 * this view is portfolio-specific so the funds UI is untouched. 404 → renders
 * nothing; other errors use the standard error panel.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  fetchPortfolioLookthroughTree,
} from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { buildHcExposureSunburstOption } from "@/lib/charts/hc/sunburst";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { InfoDot, KpiTile } from "@/components/ui/panels";
import { formatDate, formatNumber } from "@/lib/format";

const LOOKTHROUGH_TIP =
  "“Look-through”: sees through each fund/ETF in the portfolio down to its final underlying holdings, aggregating true exposure by asset class, source series and CUSIP.";

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
    queryKey: ["portfolio-lookthrough-sunburst", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioLookthroughTree(portfolioId, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  const assetItems = query.data?.dimensions.asset_class ?? [];
  const tree = query.data?.tree ?? [];
  const sunburstOption = useMemo(() => {
    if (!colors || !query.data) return null;
    return buildHcExposureSunburstOption(tree, assetItems, colors);
  }, [colors, query.data, tree, assetItems]);

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
        className="h-[480px] animate-pulse bg-surface-2"
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
  if (tree.length === 0 && assetItems.length === 0) return null;

  // ── KPIs (computed defensively from the dimensions that exist) ──────────
  const securityCount = tree.filter(
    (node) => node.kind === "cusip" || node.kind === "security",
  ).length;
  const assetClassCount = tree.filter((node) => node.kind === "asset_class").length;

  return (
    <div className="flex flex-col gap-px">
      <div>
        <h2 className="ix-label m-0 flex items-center gap-1.5">
          Consolidated exposure
          <InfoDot tip={LOOKTHROUGH_TIP} />
        </h2>
        <p className="mt-0.5 text-[12px] text-text-secondary">
          Aggregating the final holdings of every fund in the portfolio
          {data.oldest_report_date ? ` · as of ${formatDate(data.oldest_report_date)}` : ""}
        </p>
      </div>

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile
          label="Decomposed"
          value={`${formatNumber(data.sum_pct_total, 1)}%`}
          tip="Share of portfolio value mapped down to its final holdings."
        />
        <KpiTile
          label="Funds expanded"
          value={formatNumber(data.n_funds_expanded, 0)}
          tip="Funds/ETFs whose final holdings were looked through."
        />
        <KpiTile label="Cash weight" value={`${formatNumber(data.cash_weight_pct, 1)}%`} />
        <KpiTile
          label="Asset classes"
          value={formatNumber(assetClassCount || assetItems.length, 0)}
        />
        <KpiTile
          label="Final holdings"
          value={formatNumber(securityCount, 0)}
          tip="Visible final holdings in the bounded drilldown tree."
        />
      </div>

      <section className="border border-border bg-surface-2 px-5 pb-6 pt-7">
        <div className="mb-4 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="ix-label m-0">
            Look-through sunburst
          </h3>
          <span className="text-[10.5px] text-text-muted">
            Asset class → series ID → CUSIP
          </span>
        </div>
        {sunburstOption && (
          <HighchartsChart
            options={sunburstOption}
            className="h-[520px] w-full md:h-[640px]"
            isEmpty={tree.length === 0}
            emptyMessage="No exposure hierarchy available."
          />
        )}
      </section>
    </div>
  );
}
