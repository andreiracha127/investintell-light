"use client";

/**
 * Portfolio Performance tab — synthetic NAV (reconstructed from the current
 * holdings' real price histories) with a Highstock navigator/range selector,
 * and two breakdowns that follow the selected range: a contribution waterfall
 * and a packed-bubble of return contributors.
 *
 * The frontend computes the reconstruction (no portfolio NAV endpoint exists),
 * but only from backend-provided per-holding closes × current quantities. The
 * navigator's `afterSetExtremes` drives the selected [min,max]; the waterfall
 * and bubble recompute for that window (cash cancels, so the per-holding
 * contributions sum exactly to NAV(max) − NAV(min)).
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import type { Options } from "highcharts";

import { type PortfolioOverview } from "@/lib/api/client";
import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { HighchartsStockChart } from "@/components/charts/HighchartsStockChart";
import { buildHcContributionBubbleOption } from "@/lib/charts/hc/bubble";
import { buildHcContributionWaterfallOption } from "@/lib/charts/hc/waterfall";
import { formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import { periodContributions, periodTotal } from "@/lib/portfolio/performance";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { formatCompact, formatCurrency } from "@/lib/format";
import { InfoDot, valueTone } from "@/components/ui/panels";

const NAV_TIP =
  "Reconstructed portfolio value over time from the current holdings — illustrative, not a booked track record.";

export function PortfolioPerformanceView({
  overview,
}: {
  overview: PortfolioOverview;
}) {
  const positions = overview.positions;

  // Design tokens are only readable from the DOM — resolve after mount.
  const [colors, setColors] = useState<ChartColors | null>(null);
  useEffect(() => {
    setColors(chartColors());
  }, []);

  const { holdings, recon, isLoading, isError } = usePortfolioNav(overview);

  // Selected window (from the navigator). Null until the chart first reports
  // extremes; fall back to the full reconstructed path.
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
      navigator: { enabled: true },
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
            return `$${formatCompact(this.value as number)}`;
          },
        },
      },
      tooltip: {
        formatter() {
          const ctx = this as unknown as { x: number; y: number };
          return `${formatTimestampDate(ctx.x)}<br/>NAV: <b>${formatCurrency(ctx.y)}</b>`;
        },
      },
      series: [
        {
          type: "areaspline",
          name: "NAV",
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

  if (positions.length === 0) {
    return (
      <section className="ix-pad border border-border bg-surface-2">
        <p className="text-center text-[13px] text-text-muted">
          Add positions to reconstruct this portfolio&apos;s performance.
        </p>
      </section>
    );
  }

  const hasNav = recon.nav.length > 1;

  return (
    <div className="flex flex-col gap-px">
      {/* Synthetic NAV with navigator + range selector */}
      <section className="ix-pad border border-border bg-surface-2">
        <div className="mb-2 flex flex-wrap items-baseline justify-between gap-2">
          <h2 className="ix-label m-0 flex items-center gap-1.5">
            Synthetic NAV
            <InfoDot tip={NAV_TIP} />
          </h2>
          <span className="text-[10.5px] text-text-muted">
            Pick a range or drag the navigator — the breakdown below follows your selection
          </span>
        </div>
        {isLoading && !hasNav ? (
          <div
            aria-busy="true"
            aria-label="Reconstructing NAV"
            className="h-[360px] animate-pulse bg-layer-active"
          />
        ) : navOption ? (
          <HighchartsStockChart
            options={navOption}
            className="h-[360px] w-full"
            isEmpty={!hasNav}
            emptyMessage={
              isError
                ? "Could not load price history for some holdings."
                : "Not enough price history to reconstruct a NAV."
            }
          />
        ) : (
          <div className="flex h-[360px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
            {isError
              ? "Could not load price history for some holdings."
              : "Not enough price history to reconstruct a NAV."}
          </div>
        )}
      </section>

      {/* Contribution waterfall + return-contributors bubble */}
      <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
        <section className="ix-pad flex flex-col border border-border bg-surface-2">
          <h3 className="ix-label m-0">Contribution to period result</h3>
          <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
            Per-holding P&amp;L bridging the selected period ·{" "}
            <span className="font-bold text-gain">contributors</span> /{" "}
            <span className="font-bold text-loss">detractors</span> · net{" "}
            <span className={`font-bold tabular-nums ${valueTone(periodResult)}`}>
              {formatCurrency(periodResult, { signed: true })}
            </span>
          </p>
          {waterfallOption && (
            <HighchartsChart
              options={waterfallOption}
              className="h-[300px] w-full flex-1"
              isEmpty={!hasNav}
              emptyMessage="No contribution in this period."
            />
          )}
        </section>
        <section className="ix-pad flex flex-col border border-border bg-surface-2">
          <h3 className="ix-label m-0">Return contributors</h3>
          <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
            Bubble area ∝ contribution to total return · synced to the range above
          </p>
          {bubbleOption && (
            <HighchartsChart
              options={bubbleOption}
              className="h-[300px] w-full flex-1"
              isEmpty={!hasNav}
              emptyMessage="No contribution in this period."
            />
          )}
        </section>
      </div>
    </div>
  );
}
