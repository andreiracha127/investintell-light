"use client";

/**
 * Consolidated exposure (look-through) for the portfolio page — Claude Design.
 *
 * Fetches portfolio look-through data and renders the design's exposure view:
 * a KPI strip, a dimension tab bar (asset class / sector / currency / issuer —
 * whatever the backend returns), and a look-through TREEMAP whose tile area is
 * each bucket's portfolio weight, split into Direct / Via funds leaves.
 *
 * The shared `LookthroughPanel` (bar variant) stays in use by the fund pages;
 * this view is portfolio-specific so the funds UI is untouched. 404 → renders
 * nothing; other errors use the standard error panel.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { ApiError, fetchPortfolioLookthrough } from "@/lib/api/client";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { buildHcExposureTreemapOption } from "@/lib/charts/hc/treemap";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { InfoDot, KpiTile } from "@/components/ui/panels";
import { formatDate, formatNumber } from "@/lib/format";

const LOOKTHROUGH_TIP =
  "“Look-through”: sees through each fund/ETF in the portfolio down to its final underlying holdings, aggregating true exposure by asset class, sector, currency and issuer.";

const DIM_LABELS: Record<string, string> = {
  asset_class: "Asset class",
  sector: "Sector",
  currency: "Currency",
  issuer: "Issuer",
  country: "Country",
  region: "Region",
};

function dimLabel(key: string): string {
  return (
    DIM_LABELS[key] ??
    key
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

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

  const [dim, setDim] = useState<string | null>(null);

  const query = useQuery({
    queryKey: ["portfolio-lookthrough", portfolioId],
    queryFn: ({ signal }) => fetchPortfolioLookthrough(portfolioId, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  const dims = useMemo(
    () => (query.data ? Object.keys(query.data.dimensions) : []),
    [query.data],
  );
  const activeDim = dim && dims.includes(dim) ? dim : (dims[0] ?? null);

  const treemapOption = useMemo(() => {
    if (!colors || !query.data || !activeDim) return null;
    return buildHcExposureTreemapOption(query.data.dimensions[activeDim] ?? [], colors, {
      traversable: true,
    });
  }, [colors, query.data, activeDim]);

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
  if (dims.length === 0) return null;

  // ── KPIs (computed defensively from the dimensions that exist) ──────────
  const currencyItems = data.dimensions.currency ?? [];
  const nonUsd = currencyItems
    .filter((i) => (i.label ?? i.key).toUpperCase() !== "USD")
    .reduce((sum, i) => sum + i.total_pct, 0);
  const assetItems = data.dimensions.asset_class ?? [];
  const intl = assetItems
    .filter((i) => /intl|international/i.test(i.label ?? i.key))
    .reduce((sum, i) => sum + i.total_pct, 0);

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
        {currencyItems.length > 0 && (
          <KpiTile
            label="Non-USD exposure"
            value={`${formatNumber(nonUsd, 1)}%`}
            tip="Sum of weights in currencies other than the US dollar."
          />
        )}
        {intl > 0 && (
          <KpiTile label="International equity" value={`${formatNumber(intl, 1)}%`} />
        )}
      </div>

      <div
        role="tablist"
        aria-label="Exposure dimension"
        className="flex flex-wrap gap-px border border-border bg-border"
      >
        {dims.map((key) => {
          const active = key === activeDim;
          return (
            <button
              key={key}
              role="tab"
              type="button"
              aria-selected={active}
              onClick={() => setDim(key)}
              className={`h-[34px] min-w-[120px] flex-1 border-b-2 px-3.5 text-[11px] font-bold uppercase tracking-[0.06em] ${
                active
                  ? "border-accent bg-[var(--color-accent-wash)] text-accent"
                  : "border-transparent bg-surface-2 text-text-secondary hover:bg-layer-hover"
              }`}
            >
              {dimLabel(key)}
            </button>
          );
        })}
      </div>

      <section className="ix-pad border border-t-0 border-border bg-surface-2">
        <div className="mb-1.5 flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="ix-label m-0">
            Look-through map · {activeDim ? dimLabel(activeDim) : ""} → holdings
          </h3>
          <span className="text-[10.5px] text-text-muted">
            Tile area = portfolio weight · click a group to zoom in, click the
            header to zoom out · groups split into Direct vs. Via funds
          </span>
        </div>
        {treemapOption && (
          <HighchartsChart
            options={treemapOption}
            className="h-[480px] w-full"
            isEmpty={(data.dimensions[activeDim ?? ""] ?? []).length === 0}
            emptyMessage="No exposure to map for this dimension."
          />
        )}
      </section>
    </div>
  );
}
