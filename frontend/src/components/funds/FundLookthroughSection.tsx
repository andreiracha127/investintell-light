"use client";

/**
 * Consolidated exposure section for the fund profile page.
 *
 * Fetches look-through data for the fund, renders a KPI row, a dimension
 * switcher, and two side-by-side charts: exposure horizontal bars (selected
 * dimension) and a residual waterfall. 404 → renders nothing (fund has no
 * decomposition data). Any other error follows the view's error panel pattern.
 */
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";

import {
  ApiError,
  fetchFundLookthrough,
  type ExposureItem,
  type LookthroughSummary,
} from "@/lib/api/client";
import { EChart } from "@/components/charts/EChart";
import { ErrorPanel, retryPolicy } from "@/components/screener/shared";
import { Card, KpiTile } from "@/components/ui/panels";
import {
  buildExposureBarsOption,
  buildResidualWaterfallOption,
} from "@/lib/charts/lookthrough";
import { type ChartColors } from "@/lib/charts/theme";
import { formatDate, formatNumber } from "@/lib/format";

// ── Dimension label map ───────────────────────────────────────────────────

const DIMENSION_LABELS: Record<string, string> = {
  asset_class: "Asset class",
  sector: "Sector",
  currency: "Currency",
  issuer: "Issuer",
};

/** Humanize an unknown dimension key: "equity_region" → "Equity region". */
function humanizeDimension(key: string): string {
  return DIMENSION_LABELS[key] ?? key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

// ── KPI formatters (null-safe) ────────────────────────────────────────────

function pct(value: number | null | undefined, dp = 1): string {
  return value !== null && value !== undefined
    ? formatNumber(value, dp) + "%"
    : "—";
}

function count(value: number | null | undefined): string {
  return value !== null && value !== undefined
    ? formatNumber(value, 0)
    : "—";
}

// ── Inner chart panel (pure, no hooks) ───────────────────────────────────

function ExposureCharts({
  dimensions,
  summary,
  colors,
  activeDim,
  onDimChange,
}: {
  dimensions: Record<string, ExposureItem[]>;
  summary: LookthroughSummary;
  colors: ChartColors;
  activeDim: string;
  onDimChange: (dim: string) => void;
}) {
  const dimKeys = Object.keys(dimensions);

  if (dimKeys.length === 0) return null;

  const activeItems = dimensions[activeDim] ?? [];

  const exposureOption = buildExposureBarsOption(activeItems, colors);
  const waterfallOption = buildResidualWaterfallOption(summary, colors);

  return (
    <>
      {/* Dimension switcher — square-cut segmented control */}
      <div className="mb-3 flex flex-wrap gap-px border border-border bg-border">
        {dimKeys.map((key) => {
          const isActive = key === activeDim;
          return (
            <button
              key={key}
              type="button"
              onClick={() => onDimChange(key)}
              className={[
                "h-[30px] px-3.5 text-[11px] font-bold uppercase tracking-[0.07em] transition-colors",
                isActive
                  ? "bg-accent-wash border-b-2 border-b-accent text-accent"
                  : "bg-surface-2 text-text-secondary hover:bg-layer-hover",
              ].join(" ")}
            >
              {humanizeDimension(key)}
            </button>
          );
        })}
      </div>

      {/* Charts: side-by-side on wide screens */}
      <div className="grid gap-4 lg:[grid-template-columns:2fr_1fr]">
        <div>
          {activeItems.length > 0 ? (
            <EChart option={exposureOption} className="h-[320px] w-full" />
          ) : (
            <p className="py-8 text-center text-[13px] text-text-muted">
              No exposure data for this dimension.
            </p>
          )}
        </div>
        <div>
          <EChart option={waterfallOption} className="h-[240px] w-full" />
        </div>
      </div>
    </>
  );
}

// ── Main section component ────────────────────────────────────────────────

export function FundLookthroughSection({
  instrumentId,
  colors,
}: {
  instrumentId: string;
  colors: ChartColors;
}) {
  const query = useQuery({
    queryKey: ["fund-lookthrough", instrumentId],
    queryFn: ({ signal }) => fetchFundLookthrough(instrumentId, {}, signal),
    staleTime: 60_000,
    retry: (failureCount, err) => {
      // Never retry 404 (fund has no decomposition data) or other 4xx.
      if (err instanceof ApiError && err.status === 404) return false;
      return retryPolicy(failureCount, err);
    },
  });

  // activeDim must be declared before any conditional returns (Rules of Hooks).
  // Initialise from live data once available; fall back to empty string.
  const firstDim = query.data ? Object.keys(query.data.dimensions)[0] ?? "" : "";
  const [activeDim, setActiveDim] = useState<string>(firstDim);

  // 404 → fund has no decomposition data; render nothing silently.
  if (query.isError && query.error instanceof ApiError && query.error.status === 404) {
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
  const { summary, dimensions, report_date } = data;

  return (
    <section>
      {/* Section header */}
      <div className="mb-3">
        <h2 className="ix-label m-0">Consolidated exposure</h2>
        <p className="text-[12px] text-text-secondary mt-0.5">
          Through underlying funds{" "}
          {report_date ? `· as of ${formatDate(report_date)}` : ""}
        </p>
      </div>

      {/* KPI row */}
      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile label="Coverage" value={pct(summary.coverage_pct)} />
        <KpiTile label="Decomposed" value={pct(summary.sum_pct_total)} />
        <KpiTile
          label="Oldest report"
          value={
            summary.oldest_report_date
              ? formatDate(summary.oldest_report_date)
              : "—"
          }
        />
        <KpiTile
          label="Funds expanded"
          value={count(summary.n_children_expanded)}
        />
      </div>

      {/* Charts */}
      <Card title="Exposure breakdown" subtitle={humanizeDimension(activeDim)}>
        <ExposureCharts
          dimensions={dimensions}
          summary={summary}
          colors={colors}
          activeDim={activeDim}
          onDimChange={setActiveDim}
        />
      </Card>
    </section>
  );
}
