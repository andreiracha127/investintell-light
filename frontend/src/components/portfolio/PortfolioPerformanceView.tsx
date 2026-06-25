"use client";

/**
 * Portfolio Performance tab — persisted portfolio NAV index with a Highstock
 * navigator/range selector. The NAV series is materialized by the backend from
 * the real transaction ledger; the frontend only reads and renders it.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Options } from "highcharts";

import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { HighchartsStockChart } from "@/components/charts/HighchartsStockChart";
import { buildHcContributionBubbleOption } from "@/lib/charts/hc/bubble";
import { buildHcContributionWaterfallOption } from "@/lib/charts/hc/waterfall";
import { formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import { periodContributions, periodTotal } from "@/lib/portfolio/performance";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { formatCurrency, formatNumber } from "@/lib/format";
import { InfoDot, valueTone } from "@/components/ui/panels";

const NAV_TIP =
  "Persisted daily portfolio NAV index from the real transaction ledger and portfolio inception date.";

export function PortfolioPerformanceView({
  portfolioId,
}: {
  portfolioId: number;
}) {
  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const { holdings, recon, isLoading, isError } = usePortfolioNav(portfolioId);

  // Selected window (from the navigator). Null until the chart first reports
  // extremes; fall back to the full persisted path.
  const [extent, setExtent] = useState<{ min: number; max: number } | null>(null);
  const extentTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const onExtremes = useCallback((min: number, max: number) => {
    if (extentTimer.current) clearTimeout(extentTimer.current);
    extentTimer.current = setTimeout(() => setExtent({ min, max }), 120);
  }, []);
  useEffect(
    () => () => {
      if (extentTimer.current) clearTimeout(extentTimer.current);
    },
    [],
  );

  const minTs = extent?.min ?? recon.startTs;
  const maxTs = extent?.max ?? recon.endTs;
  const contribs = useMemo(
    () => periodContributions(holdings, minTs, maxTs),
    [holdings, minTs, maxTs],
  );
  const periodResult = useMemo(() => periodTotal(contribs), [contribs]);

  const navOption = useMemo<Options | null>(() => {
    if (!colors || recon.nav.length === 0) return null;
    const fill0 = `${colors.accent}30`;
    const fill1 = `${colors.accent}00`;
    return {
      chart: { height: 360 },
      rangeSelector: {
        enabled: true,
        selected: 4,
        inputEnabled: false,
        buttons: [
          { type: "month", count: 1, text: "1m" },
          { type: "month", count: 3, text: "3m" },
          { type: "month", count: 6, text: "6m" },
          { type: "ytd", text: "YTD" },
          { type: "year", count: 1, text: "1y" },
          { type: "all", text: "All" },
        ],
      },
      navigator: {
        enabled: true,
        // Match the main NAV series tone in the navigator preview (accent).
        maskFill: `${colors.accent}1a`,
        series: { color: colors.accent, lineWidth: 1, fillOpacity: 0.08 },
      },
      scrollbar: { enabled: false },
      xAxis: {
        type: "datetime",
        crosshair: true,
        events: {
          afterSetExtremes(e) {
            onExtremes(e.min, e.max);
          },
        },
      },
      yAxis: {
        opposite: true,
        title: { text: undefined },
        labels: {
          formatter() {
            return formatNumber(this.value as number, 0);
          },
        },
      },
      tooltip: {
        formatter() {
          const ctx = this as unknown as { x: number; y: number };
          return `${formatTimestampDate(ctx.x)}<br/>NAV Index: <b>${formatNumber(ctx.y, 2)}</b>`;
        },
      },
      series: [
        {
          type: "areaspline",
          name: "NAV Index",
          data: recon.nav,
          color: colors.accent,
          lineWidth: 1.8,
          marker: { enabled: false },
          fillColor: {
            linearGradient: { x1: 0, y1: 0, x2: 0, y2: 1 },
            stops: [
              [0, fill0],
              [1, fill1],
            ],
          },
        },
      ],
    };
  }, [recon.nav, colors, onExtremes]);

  const waterfallOption = useMemo<Options | null>(
    () =>
      colors
        ? buildHcContributionWaterfallOption(
            contribs.map((c) => ({ label: c.ticker, value: c.value, ret: c.ret })),
            colors,
          )
        : null,
    [contribs, colors],
  );
  const bubbleOption = useMemo<Options | null>(
    () =>
      colors
        ? buildHcContributionBubbleOption(
            contribs.map((c) => ({ ticker: c.ticker, value: c.value, ret: c.ret })),
            colors,
          )
        : null,
    [contribs, colors],
  );

  const hasNav = recon.nav.length > 1;
  const hasAttribution = holdings.length > 0;

  return (
    <div className="flex flex-col gap-px">
      {/* Persisted NAV with navigator + range selector */}
      <section className="ix-pad border border-border bg-surface-2">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="ix-label m-0 flex items-center gap-1.5">
            Portfolio NAV
            <InfoDot tip={NAV_TIP} />
          </h2>
        </div>
        {isLoading && !hasNav ? (
          <div
            aria-busy="true"
            aria-label="Loading NAV"
            className="h-[360px] animate-pulse bg-layer-active"
          />
        ) : navOption ? (
          <HighchartsStockChart
            options={navOption}
            className="h-[360px] w-full"
            isEmpty={!hasNav}
            emptyMessage={
              isError
                ? "Could not load materialized portfolio NAV."
                : "NAV not materialized."
            }
          />
        ) : (
          <div className="flex h-[360px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
            {isError
              ? "Could not load materialized portfolio NAV."
              : "NAV not materialized."}
          </div>
        )}
      </section>

      {/* Contribution waterfall + return-contributors bubble */}
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <section className="ix-pad flex flex-col border border-border bg-surface-2">
          <h3 className="ix-label m-0">Contribution to period result</h3>
          <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
            {hasAttribution ? (
              <>
                <span className="font-bold text-gain">contributors</span> /{" "}
                <span className="font-bold text-loss">detractors</span> · net{" "}
                <span className={`font-bold tabular-nums ${valueTone(periodResult)}`}>
                  {formatCurrency(periodResult, { signed: true })}
                </span>
              </>
            ) : (
              "Security-level attribution has not been materialized yet."
            )}
          </p>
          {waterfallOption && (
            <HighchartsChart
              options={waterfallOption}
              className="h-[300px] w-full flex-1"
              isEmpty={!hasAttribution}
              emptyMessage="Security-level attribution has not been materialized yet."
            />
          )}
        </section>
        <section className="ix-pad flex flex-col border border-border bg-surface-2">
          <h3 className="ix-label m-0">Return contributors</h3>
          <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
            {hasAttribution
              ? "By return contribution."
              : "Security-level attribution has not been materialized yet."}
          </p>
          {bubbleOption && (
            <HighchartsChart
              options={bubbleOption}
              className="h-[300px] w-full flex-1"
              isEmpty={!hasAttribution}
              emptyMessage="Security-level attribution has not been materialized yet."
            />
          )}
        </section>
      </div>
    </div>
  );
}
