"use client";

/**
 * Portfolio Performance tab — persisted portfolio NAV index as a clean
 * Highcharts Core time series. The NAV series is materialized by the backend
 * from the real transaction ledger; the frontend only reads and renders it.
 */
import { useEffect, useMemo, useState } from "react";
import type { Options } from "highcharts";

import { chartColors, type ChartColors } from "@/lib/charts/chartColors";
import { HighchartsChart } from "@/components/charts/HighchartsChart";
import { buildHcContributionBubbleOption } from "@/lib/charts/hc/bubble";
import { buildHcContributionWaterfallOption } from "@/lib/charts/hc/waterfall";
import { compactDatetimeXAxis, formatTimestampDate } from "@/lib/charts/hc/dateAxis";
import { periodContributions, periodTotal } from "@/lib/portfolio/performance";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import { formatCurrency, formatNumber, formatPercent } from "@/lib/format";
import { InfoDot, valueTone } from "@/components/ui/panels";

const NAV_TIP =
  "Persisted daily portfolio NAV index from the real transaction ledger and portfolio inception date.";

const PERF_RANGES = [
  { key: "1M", label: "1M", days: 31 },
  { key: "3M", label: "3M", days: 92 },
  { key: "6M", label: "6M", days: 184 },
  { key: "YTD", label: "YTD", days: null },
  { key: "1Y", label: "1Y", days: 366 },
  { key: "ALL", label: "All", days: Infinity },
] as const;

type PerfRangeKey = (typeof PERF_RANGES)[number]["key"];

function navWindowForRange(
  nav: Array<[number, number]>,
  range: PerfRangeKey,
): Array<[number, number]> {
  if (nav.length === 0 || range === "ALL") return nav;
  const end = nav[nav.length - 1]![0];
  let start: number;
  if (range === "YTD") {
    const endDate = new Date(end);
    start = Date.UTC(endDate.getUTCFullYear(), 0, 1);
  } else {
    const days = PERF_RANGES.find((item) => item.key === range)?.days ?? 366;
    start = end - Number(days) * 24 * 60 * 60 * 1000;
  }
  const windowed = nav.filter(([x]) => x >= start);
  return windowed.length > 1 ? windowed : nav.slice(-Math.min(2, nav.length));
}

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
  const [range, setRange] = useState<PerfRangeKey>("1Y");
  const navWindow = useMemo(
    () => navWindowForRange(recon.nav, range),
    [recon.nav, range],
  );

  const minTs = navWindow[0]?.[0] ?? recon.startTs;
  const maxTs = navWindow[navWindow.length - 1]?.[0] ?? recon.endTs;
  const contribs = useMemo(
    () => periodContributions(holdings, minTs, maxTs),
    [holdings, minTs, maxTs],
  );
  const periodResult = useMemo(() => periodTotal(contribs), [contribs]);
  const periodReturn =
    navWindow.length > 1
      ? navWindow[navWindow.length - 1]![1] / navWindow[0]![1] - 1
      : null;

  const navOption = useMemo<Options | null>(() => {
    if (!colors || navWindow.length === 0) return null;
    return {
      chart: { type: "line", height: 430, zooming: { type: "x" } },
      legend: { enabled: false },
      xAxis: compactDatetimeXAxis({
        crosshair: { color: colors.grid },
        tickPixelInterval: 96,
      }),
      yAxis: {
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
      plotOptions: {
        line: {
          animation: { duration: 900 },
          marker: {
            enabled: false,
            states: { hover: { enabled: true, radius: 3 } },
          },
          states: { hover: { lineWidthPlus: 0.8 } },
        },
      },
      series: [
        {
          type: "line",
          name: "NAV Index",
          data: navWindow,
          color: colors.accent,
          lineWidth: 2.3,
        },
      ],
    };
  }, [navWindow, colors]);

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
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="ix-label m-0 flex items-center gap-1.5">
            Portfolio NAV
            <InfoDot tip={NAV_TIP} />
          </h2>
          <div className="flex items-center gap-2.5">
            {periodReturn !== null && (
              <span className={`text-[12px] font-bold tabular-nums ${valueTone(periodReturn)}`}>
                {formatPercent(periodReturn, 2, { signed: true })}
              </span>
            )}
            <div
              role="group"
              aria-label="Performance NAV range"
              className="flex border border-border-strong"
            >
              {PERF_RANGES.map((item) => {
                const active = item.key === range;
                return (
                  <button
                    key={item.key}
                    type="button"
                    aria-pressed={active}
                    onClick={() => setRange(item.key)}
                    className={`h-[28px] border-r border-border-strong px-2.5 text-[11px] last:border-r-0 ${
                      active
                        ? "bg-accent font-bold text-on-accent"
                        : "text-text-muted hover:bg-layer-hover"
                    }`}
                  >
                    {item.label}
                  </button>
                );
              })}
            </div>
          </div>
        </div>
        {isLoading && !hasNav ? (
          <div
            aria-busy="true"
            aria-label="Loading NAV"
            className="h-[430px] animate-pulse bg-layer-active"
          />
        ) : navOption ? (
          <HighchartsChart
            options={navOption}
            className="h-[430px] w-full"
            isEmpty={!hasNav}
            emptyMessage={
              isError
                ? "Could not load materialized portfolio NAV."
                : "NAV not materialized."
            }
          />
        ) : (
          <div className="flex h-[430px] items-center justify-center px-4 text-center text-[13px] text-text-muted">
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
