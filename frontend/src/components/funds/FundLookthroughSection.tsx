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
import { useEffect, useMemo, useState } from "react";

import {
  ApiError,
  fetchFundLookthrough,
  type ExposureItem,
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
  activeDim,
  onDimChange,
  exposureOption,
  waterfallOption,
}: {
  dimensions: Record<string, ExposureItem[]>;
  activeDim: string;
  onDimChange: (dim: string) => void;
  exposureOption: ReturnType<typeof buildExposureBarsOption>;
  waterfallOption: ReturnType<typeof buildResidualWaterfallOption>;
}) {
  const dimKeys = Object.keys(dimensions);

  if (dimKeys.length === 0) return null;

  const activeItems = dimensions[activeDim] ?? [];

  return (
    <>
      {/* Dimension switcher — square-cut segmented control */}
      <div
        role="tablist"
        aria-label="Exposure dimension"
        className="mb-3 flex flex-wrap gap-px border border-border bg-border"
      >
        {dimKeys.map((key) => {
          const isActive = key === activeDim;
          return (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={isActive}
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

  // All hooks must be declared before any conditional returns (Rules of Hooks).

  // activeDim: useState(firstDim) is seeded before React Query resolves and
  // would stay "" forever. Seed via effect instead: once data arrives and
  // activeDim is still empty, pick the first dimension key.
  const [activeDim, setActiveDim] = useState<string>("");
  useEffect(() => {
    if (query.data && !activeDim) {
      setActiveDim(Object.keys(query.data.dimensions)[0] ?? "");
    }
  }, [query.data, activeDim]);

  // Both memos run unconditionally (Rules of Hooks). The results are only
  // consumed after all early returns, so query.data is guaranteed non-null
  // at that point. We guard with ?? [] / a no-op path to keep TypeScript happy
  // for the undefined case that never reaches the render.
  const exposureOption = useMemo(
    () =>
      buildExposureBarsOption(
        query.data?.dimensions[activeDim] ?? [],
        colors,
      ),
    [query.data, activeDim, colors],
  );

  const waterfallOption = useMemo(
    () =>
      query.data
        ? buildResidualWaterfallOption(query.data.summary, colors)
        : ({ series: [] } as ReturnType<typeof buildResidualWaterfallOption>),
    [query.data, colors],
  );

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
          activeDim={activeDim}
          onDimChange={setActiveDim}
          exposureOption={exposureOption}
          waterfallOption={waterfallOption}
        />
      </Card>
    </section>
  );
}
