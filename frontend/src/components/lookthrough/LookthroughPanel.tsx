"use client";

/**
 * Shared presentational panel for consolidated look-through data.
 *
 * Accepts already-fetched data ({dimensions, summary, reportDate}) and renders:
 *   - KPI row (coverage, decomposed, unidentified, oldest report, expanded)
 *   - ARIA tablist dimension switcher
 *   - Exposure horizontal bars (full width)
 *
 * The residual composition is communicated through the KPI tiles — it does
 * not warrant a chart of its own.
 *
 * Hooks are declared unconditionally (Rules of Hooks). The caller supplies a
 * `ChartColors` instance resolved after mount.
 */
import { useEffect, useMemo, useState } from "react";

import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { Card, KpiTile } from "@/components/ui/panels";
import {
  buildHcAssetClassPieOption,
  buildHcExposureBarsOption,
  buildHcIssuerParetoOption,
} from "@/lib/charts/hc/lookthrough";
import { type ChartColors } from "@/lib/charts/chartColors";
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

// ── Exposure chart block (pure, no hooks) ──────────────────────────────────

function ExposureCharts({
  dimensions,
  activeDim,
  onDimChange,
  exposureOption,
}: {
  dimensions: Record<string, ExposureItem[]>;
  activeDim: string;
  onDimChange: (dim: string) => void;
  exposureOption: ReturnType<typeof buildHcExposureBarsOption>;
}) {
  const dimKeys = Object.keys(dimensions);
  if (dimKeys.length === 0) return null;

  const activeItems = dimensions[activeDim] ?? [];
  // Issuer renders a vertical Pareto (concentration curve) in a taller 21:9
  // card; asset class renders an animated donut in a tall, roomy area; the
  // other dimensions keep the compact horizontal bars.
  const chartClassName =
    activeDim === "issuer"
      ? "aspect-[21/9] w-full"
      : activeDim === "asset_class"
        ? "h-[460px] w-full"
        : "h-[320px] w-full";

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

      {activeItems.length > 0 ? (
        <HighchartsChart options={exposureOption} className={chartClassName} />
      ) : (
        <p className="py-8 text-center text-[13px] text-text-muted">
          No exposure data for this dimension.
        </p>
      )}
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

  // Seed on data arrival AND re-seed when a new dimensions object no longer
  // contains the previously selected key (e.g. entity switch upstream).
  useEffect(() => {
    const keys = Object.keys(dimensions);
    if (!activeDim || !keys.includes(activeDim)) {
      setActiveDim(keys[0] ?? "");
    }
  }, [dimensions, activeDim]);

  const exposureOption = useMemo(() => {
    const items = dimensions[activeDim] ?? [];
    if (activeDim === "issuer") return buildHcIssuerParetoOption(items, colors);
    if (activeDim === "asset_class") return buildHcAssetClassPieOption(items, colors);
    return buildHcExposureBarsOption(items, colors);
  }, [dimensions, activeDim, colors]);

  return (
    <>
      {/* KPI row — includes the residual composition (no chart needed) */}
      <div className="mb-4 grid gap-px border border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(140px,1fr))]">
        <KpiTile label="Coverage" value={pct(summary.coverage_pct)} />
        <KpiTile label="Decomposed" value={pct(summary.sum_pct_total)} />
        <KpiTile label="Unidentified" value={pct(summary.unidentified_pct)} />
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

      {/* Chart */}
      <Card
        title="Exposure breakdown"
        subtitle={activeDim ? humanizeDimension(activeDim) : undefined}
      >
        <ExposureCharts
          dimensions={dimensions}
          activeDim={activeDim}
          onDimChange={setActiveDim}
          exposureOption={exposureOption}
        />
      </Card>
    </>
  );
}
