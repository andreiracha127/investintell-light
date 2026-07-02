"use client";

/**
 * Treasury fiscal series explorer (Macro → Fiscal data).
 *
 * Surfaces GET /macro/fiscal — the full treasury_ingestion history (up to ten
 * years) as an interactive Highcharts Stock chart with navigator + scrollbar.
 * Category and lookback are server-side query params; zooming/scrubbing inside
 * the fetched window is client-side via the navigator.
 */
import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Options } from "highcharts";

import {
  ApiError,
  fetchMacroFiscal,
  type FiscalCategory,
} from "@/lib/api/client";
import { HighchartsStockChart } from "@/components/charts/HighchartsStockChart";
import { retryPolicy } from "@/components/screener/shared";
import { ErrorPanel, InfoDot } from "@/components/ui/panels";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { buildHcMacroFiscalOption } from "@/lib/charts/hc/macro-fiscal";

const CATEGORIES: Array<{ key: FiscalCategory; label: string; tip: string }> = [
  {
    key: "rates",
    label: "Rates",
    tip: "Average interest rates on outstanding Treasury securities, by instrument.",
  },
  {
    key: "debt",
    label: "Debt",
    tip: "Total public debt outstanding and its components, in dollars.",
  },
  {
    key: "auctions",
    label: "Auctions",
    tip: "Treasury auction results — issuance metrics per security type.",
  },
  {
    key: "fx",
    label: "FX",
    tip: "Treasury reference exchange rates for major currencies.",
  },
  {
    key: "interest",
    label: "Interest",
    tip: "Interest expense on the federal debt.",
  },
];

/** One InfoDot next to "Category" summarizes all five — matches the page's
 *  flat InfoDot pattern instead of native `title=` tooltips on the buttons. */
const CATEGORY_TIP = CATEGORIES.map((cat) => `${cat.label}: ${cat.tip}`).join(" ");

const LOOKBACKS: Array<{ label: string; days: number }> = [
  { label: "1Y", days: 365 },
  { label: "3Y", days: 1095 },
  { label: "5Y", days: 1825 },
  { label: "10Y", days: 3650 },
];

export function FiscalExplorerPanel() {
  const [colors, setColors] = useState<ChartColors | null>(null);
  const [category, setCategory] = useState<FiscalCategory>("rates");
  const [lookbackDays, setLookbackDays] = useState<number>(1825);

  useEffect(() => {
    setColors(chartColors());
  }, []);

  const query = useQuery({
    queryKey: ["macro-fiscal", category, lookbackDays],
    queryFn: ({ signal }) =>
      fetchMacroFiscal({ category, lookback_days: lookbackDays }, signal),
    staleTime: 300_000,
    retry: retryPolicy,
  });

  const option = useMemo<Options | null>(() => {
    if (!colors || !query.data) return null;
    return buildHcMacroFiscalOption({
      series: query.data.series,
      category: query.data.category as FiscalCategory,
      prefix: query.data.prefix,
      colors,
    });
  }, [colors, query.data]);

  const notMaterialized =
    query.isError && query.error instanceof ApiError && query.error.status === 404;

  const pointCount = useMemo(
    () => query.data?.series.reduce((acc, s) => acc + s.points.length, 0) ?? 0,
    [query.data],
  );

  return (
    <section className="border border-t-0 border-border bg-surface-2">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border px-[var(--ix-pad)] py-3">
        <div className="flex items-center gap-1.5">
          <h2 className="ix-label m-0">US fiscal data</h2>
          <InfoDot tip="Official US Treasury fiscal series — rates, debt outstanding, auction results, FX rates and interest expense — with up to ten years of history. Drag the navigator below the chart to scrub through time." />
        </div>
        {query.data && (
          <span className="text-[11px] tabular-nums text-text-muted">
            {query.data.series.length} series · {pointCount.toLocaleString()} observations
          </span>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-[18px] border-b border-border px-[var(--ix-pad)] py-3">
        <div className="flex flex-col gap-1.5">
          <span className="flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
            Category
            <InfoDot tip={CATEGORY_TIP} />
          </span>
          <div role="group" aria-label="Fiscal category" className="flex h-[34px] border border-border-strong">
            {CATEGORIES.map((cat, i) => {
              const active = category === cat.key;
              return (
                <button
                  key={cat.key}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setCategory(cat.key)}
                  className={`px-[13px] text-[11.5px] font-bold transition-colors ${
                    i === 0 ? "" : "border-l border-border-strong"
                  } ${
                    active
                      ? "bg-accent text-on-accent"
                      : "bg-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {cat.label}
                </button>
              );
            })}
          </div>
        </div>
        <div className="flex flex-col gap-1.5">
          <span className="text-[10px] font-bold uppercase tracking-[0.07em] text-text-muted">
            Lookback
          </span>
          <div role="group" aria-label="Lookback" className="flex h-[34px] border border-border-strong">
            {LOOKBACKS.map((lb, i) => {
              const active = lookbackDays === lb.days;
              return (
                <button
                  key={lb.label}
                  type="button"
                  aria-pressed={active}
                  onClick={() => setLookbackDays(lb.days)}
                  className={`px-[13px] text-[11.5px] font-bold transition-colors ${
                    i === 0 ? "" : "border-l border-border-strong"
                  } ${
                    active
                      ? "bg-accent text-on-accent"
                      : "bg-transparent text-text-secondary hover:text-text-primary"
                  }`}
                >
                  {lb.label}
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <div className="p-[var(--ix-pad)]">
        {query.isPending || (!option && !query.isError) ? (
          <div aria-busy="true" className="h-[380px] animate-pulse bg-surface-3" />
        ) : notMaterialized ? (
          <div className="flex h-[120px] items-center px-2 text-[13px] text-text-muted">
            No fiscal data materialized for this category yet — the treasury
            ingestion worker has not populated it.
          </div>
        ) : query.isError ? (
          <ErrorPanel
            title="Failed to load fiscal data"
            message={query.error.message}
            onRetry={() => query.refetch()}
          />
        ) : (
          option && (
            <HighchartsStockChart
              options={option}
              className="h-[380px] w-full"
              isEmpty={query.data.series.length === 0}
              emptyMessage="No observations in the selected window."
            />
          )
        )}
      </div>
    </section>
  );
}
