"use client";

/**
 * Shared presentational panel for consolidated look-through data.
 *
 * Accepts already-fetched data ({dimensions, summary, reportDate}) and renders:
 *   - KPI row (coverage, decomposed, oldest report, funds/children expanded)
 *   - ARIA tablist dimension switcher
 *   - Exposure horizontal bars + residual waterfall side-by-side
 *
 * Hooks are declared unconditionally (Rules of Hooks). The caller supplies a
 * `ChartColors` instance resolved after mount.
 */
import { useEffect, useMemo, useState } from "react";

import { EChart } from "@/components/charts/EChart";
import { Card, KpiTile } from "@/components/ui/panels";
import {
  buildExposureBarsOption,
  buildResidualWaterfallOption,
} from "@/lib/charts/lookthrough";
import { type ChartColors } from "@/lib/charts/theme";
import { formatDate, formatNumber } from "@/lib/format";
import type { ExposureItem, LookthroughSummary } from "@/lib/api/client";

// ── Dimension label map ────────────────────────────────────────────────────

const DIMENSION_LABELS: Record<string, string> = {
  asset_class: "Asset class",
  sector: "Sector",
  currency: "Currency",
  issuer: "Issuer",
};

/** Humanize an unknown dimension key: "equity_region" → "Equity region". */
function humanizeDimension(key: string): string {
  return (
    DIMENSION_LABELS[key] ??
    key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase())
  );
}

// ── KPI formatters (null-safe) ─────────────────────────────────────────────

function pct(value: number | null | undefined, dp = 1): string {
  return value !== null && value !== undefined
    ? formatNumber(value, dp) + "%"
    : "—";
}

function count(value: number | null | undefined): string {
  return value !== null && value !== undefined ? formatNumber(value, 0) : "—";
}

// ── Exposure charts block (pure, no hooks) ─────────────────────────────────

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

// ── Props ──────────────────────────────────────────────────────────────────

export interface LookthroughPanelProps {
  /** Exposure items keyed by dimension name. */
  dimensions: Record<string, ExposureItem[]>;
  /** Summary stats (coverage, residuals, etc.). */
  summary: LookthroughSummary;
  /**
   * ISO date string for the "as of" line. Optional: both FundLookthrough
   * (report_date required) and PortfolioLookthrough (oldest_report_date
   * nullable) converge here — callers pass null/undefined when absent.
   */
  reportDate: string | null | undefined;
  /** Design-token color bag (from chartColors(), resolved after mount). */
  colors: ChartColors;
  /** Number of funds/children expanded — label differs by context. */
  expandedLabel: string;
  expandedCount: number | null | undefined;
}

// ── Panel ──────────────────────────────────────────────────────────────────

export function LookthroughPanel({
  dimensions,
  summary,
  reportDate,
  colors,
  expandedLabel,
  expandedCount,
}: LookthroughPanelProps) {
  // All hooks unconditionally before any conditional returns.
  const [activeDim, setActiveDim] = useState<string>("");

  useEffect(() => {
    if (!activeDim) {
      setActiveDim(Object.keys(dimensions)[0] ?? "");
    }
  }, [dimensions, activeDim]);

  const exposureOption = useMemo(
    () => buildExposureBarsOption(dimensions[activeDim] ?? [], colors),
    [dimensions, activeDim, colors],
  );

  const waterfallOption = useMemo(
    () => buildResidualWaterfallOption(summary, colors),
    [summary, colors],
  );

  return (
    <>
      {/* KPI row */}
      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile label="Coverage" value={pct(summary.coverage_pct)} />
        <KpiTile label="Decomposed" value={pct(summary.sum_pct_total)} />
        <KpiTile
          label="Oldest report"
          value={
            summary.oldest_report_date
              ? formatDate(summary.oldest_report_date)
              : reportDate
                ? formatDate(reportDate)
                : "—"
          }
        />
        <KpiTile label={expandedLabel} value={count(expandedCount)} />
      </div>

      {/* Charts */}
      <Card
        title="Exposure breakdown"
        subtitle={activeDim ? humanizeDimension(activeDim) : undefined}
      >
        <ExposureCharts
          dimensions={dimensions}
          activeDim={activeDim}
          onDimChange={setActiveDim}
          exposureOption={exposureOption}
          waterfallOption={waterfallOption}
        />
      </Card>
    </>
  );
}
