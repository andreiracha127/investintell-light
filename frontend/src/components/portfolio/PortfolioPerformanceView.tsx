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
import { buildHcUnderwaterOption } from "@/lib/charts/hc/underwater";
import {
  compactDatetimeXAxis,
  dateToUtcMs,
  formatTimestampDate,
} from "@/lib/charts/hc/dateAxis";
import {
  navDrawdownSeries,
  navPointsFrom,
  navWindowStats,
} from "@/lib/portfolio/navAnalytics";
import {
  PERF_NAV_RANGES,
  sliceNavWindow,
  type NavRangeKey,
} from "@/lib/portfolio/navRanges";
import { usePortfolioNav } from "@/components/portfolio/usePortfolioNav";
import {
  formatCompact,
  formatCurrency,
  formatDate,
  formatNumber,
  formatPercent,
} from "@/lib/format";
import { InfoDot, KpiTile, valueTone } from "@/components/ui/panels";

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

  const { recon, response, isLoading, isError } = usePortfolioNav(portfolioId);
  const [range, setRange] = useState<NavRangeKey>("1Y");
  const navWindow = useMemo(
    () => sliceNavWindow(recon.nav, range),
    [recon.nav, range],
  );

  // Raw persisted points (nav index + dollar composition) over the same window.
  const windowPoints = useMemo(() => {
    const points = response?.points ?? [];
    const startTs = navWindow[0]?.[0];
    return startTs === undefined ? points : navPointsFrom(points, startTs);
  }, [response, navWindow]);
  const windowStats = useMemo(() => navWindowStats(windowPoints), [windowPoints]);

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

  // Underwater plot of the persisted NAV window.
  const underwaterOption = useMemo<Options | null>(() => {
    if (!colors || windowPoints.length < 2) return null;
    return buildHcUnderwaterOption(
      navDrawdownSeries(windowPoints),
      "NAV drawdown",
      colors,
    );
  }, [windowPoints, colors]);

  // Dollar composition: invested market value + cash stacked to total value.
  const compositionOption = useMemo<Options | null>(() => {
    if (!colors || windowPoints.length < 2) return null;
    return {
      chart: { type: "area" },
      legend: { enabled: true },
      xAxis: compactDatetimeXAxis({ crosshair: { color: colors.grid } }),
      yAxis: {
        title: { text: undefined },
        labels: {
          formatter() {
            return `$${formatCompact(this.value as number)}`;
          },
        },
      },
      tooltip: {
        shared: true,
        formatter() {
          const points = this.points ?? [];
          const total = points.reduce((acc, p) => acc + ((p.y as number) ?? 0), 0);
          const rows = points
            .map(
              (p) =>
                `<span style="color:${p.color}">●</span> ${p.series.name}: <b>${formatCurrency(
                  p.y as number,
                )}</b>`,
            )
            .join("<br/>");
          return `${formatTimestampDate(this.x)}<br/>${rows}<br/>Total: <b>${formatCurrency(total)}</b>`;
        },
      },
      plotOptions: {
        area: {
          stacking: "normal",
          lineWidth: 1,
          marker: { enabled: false },
          fillOpacity: 0.35,
        },
      },
      series: [
        {
          type: "area",
          name: "Invested",
          data: windowPoints.map((p) => [dateToUtcMs(p.date), p.market_value]),
          color: colors.accent,
        },
        {
          type: "area",
          name: "Cash",
          data: windowPoints.map((p) => [dateToUtcMs(p.date), p.cash]),
          color: colors.barMute,
        },
      ],
    };
  }, [windowPoints, colors]);

  const hasNav = recon.nav.length > 1;

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
              {PERF_NAV_RANGES.map((item) => {
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

      {/* NAV analytics KPI strip (derived from the persisted window) */}
      {windowPoints.length >= 2 && (
        <div className="grid gap-px border border-t-0 border-border bg-border [grid-template-columns:repeat(auto-fit,minmax(170px,1fr))]">
          <KpiTile
            label={`Return · ${range}`}
            value={
              windowStats.periodReturn !== null
                ? formatPercent(windowStats.periodReturn, 2, { signed: true })
                : "--"
            }
            tone={
              windowStats.periodReturn !== null
                ? valueTone(windowStats.periodReturn)
                : "text-text-primary"
            }
            tip="Total NAV return over the selected window."
          />
          <KpiTile
            label="CAGR"
            value={
              windowStats.cagr !== null
                ? formatPercent(windowStats.cagr, 2, { signed: true })
                : "--"
            }
            tone={
              windowStats.cagr !== null
                ? valueTone(windowStats.cagr)
                : "text-text-primary"
            }
            tip="Window return annualized over calendar time."
          />
          <KpiTile
            label="Ann. Volatility"
            value={
              windowStats.annualizedVolatility !== null
                ? formatPercent(windowStats.annualizedVolatility)
                : "--"
            }
            tip="Annualized standard deviation of daily NAV returns over the window."
          />
          <KpiTile
            label="Max Drawdown"
            value={
              windowStats.maxDrawdown
                ? formatPercent(windowStats.maxDrawdown.depth)
                : "0.00%"
            }
            tone={windowStats.maxDrawdown ? "text-loss" : "text-text-primary"}
            detail={
              windowStats.maxDrawdown
                ? `${formatDate(windowStats.maxDrawdown.peakDate)} → ${formatDate(windowStats.maxDrawdown.troughDate)}`
                : "no decline in window"
            }
            tip="Largest peak-to-trough NAV decline inside the selected window."
          />
        </div>
      )}

      {/* NAV drawdown + dollar composition */}
      {(underwaterOption || compositionOption) && (
        <div className="grid gap-px bg-border [grid-template-columns:repeat(auto-fit,minmax(320px,1fr))]">
          <section className="ix-pad flex flex-col border border-border bg-surface-2">
            <h3 className="ix-label m-0 flex items-center gap-1.5">
              NAV drawdown
              <InfoDot tip="How far the NAV sits below its running peak at each date — the classic underwater plot. 0 means a new high." />
            </h3>
            <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
              Decline from the running peak over the selected window.
            </p>
            {underwaterOption && (
              <HighchartsChart
                options={underwaterOption}
                className="h-[240px] w-full flex-1"
              />
            )}
          </section>
          <section className="ix-pad flex flex-col border border-border bg-surface-2">
            <h3 className="ix-label m-0 flex items-center gap-1.5">
              Value composition
              <InfoDot tip="Total portfolio value split into invested market value and cash, from the persisted daily ledger." />
            </h3>
            <p className="mb-2 mt-0.5 text-[11px] text-text-muted">
              Invested vs cash, stacked to total value.
            </p>
            {compositionOption && (
              <HighchartsChart
                options={compositionOption}
                className="h-[240px] w-full flex-1"
              />
            )}
          </section>
        </div>
      )}
    </div>
  );
}
