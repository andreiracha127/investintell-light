"use client";

/**
 * Consolidated exposure (look-through) for the portfolio page.
 *
 * Fetches one portfolio look-through hierarchy and renders the exposure view:
 * a KPI strip plus the shared Sunburst + Grid exposure map. 404 → renders
 * nothing; other errors use the standard error panel.
 */
import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import {
  ApiError,
  fetchPortfolioLookthroughTree,
} from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { ExposureSunburstGrid } from "@/components/lookthrough/ExposureSunburstGrid";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { InfoDot, KpiTile } from "@/components/ui/panels";
import { formatDate, formatNumber } from "@/lib/format";

const LOOKTHROUGH_TIP =
  "Final holdings aggregated across funds and ETFs.";

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

  const data = query.data;

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

  if (!data) return null;
  const assetItems = data.dimensions.asset_class ?? [];
  const tree = data.tree;
  if (tree.length === 0 && assetItems.length === 0) return null;

  // ── KPIs (computed defensively from the dimensions that exist) ──────────
  const parentIds = new Set(
    tree
      .map((node) => node.parent_id)
      .filter((id): id is string => Boolean(id)),
  );
  const securityCount = tree.filter((node) => !parentIds.has(node.id)).length;
  const assetClassCount = tree.filter((node) => node.kind === "asset_class").length;
  const residualPositionPct = data.unexpanded
    .reduce((sum, position) => sum + position.weight_pct, 0);
  const decomposedPct = Math.min(
    100,
    Math.max(0, data.expanded_weight_pct + residualPositionPct + data.cash_weight_pct),
  );

  return (
    <div className="flex flex-col gap-px">
      <div>
        <h2 className="ix-label m-0 flex items-center gap-1.5">
          Consolidated exposure
          <InfoDot tip={LOOKTHROUGH_TIP} />
        </h2>
        <p className="mt-0.5 text-[12px] text-text-secondary">
          {data.oldest_report_date ? `As of ${formatDate(data.oldest_report_date)}` : "Latest"}
        </p>
      </div>

      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile
          label="Decomposed"
          value={`${formatNumber(decomposedPct, 1)}%`}
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

      {colors && (
        <ExposureSunburstGrid
          title="Exposure map"
          subtitle="Asset class / fund / holding"
          rootName="Portfolio"
          tree={tree}
          assetItems={assetItems}
          colors={colors}
        />
      )}
    </div>
  );
}
