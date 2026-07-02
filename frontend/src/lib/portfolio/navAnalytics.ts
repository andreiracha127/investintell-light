/**
 * Analytics derived 1:1 from the persisted portfolio NAV series
 * (`GET /portfolios/{id}/nav`). The backend materializes daily NAV from the
 * real transaction ledger; everything here is arithmetic over those points —
 * no market data is invented client-side.
 */
import type { PortfolioNavPoint, SeriesPoint } from "@/lib/api/client";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";

const TRADING_DAYS_PER_YEAR = 252;
const MS_PER_DAY = 86_400_000;

export interface NavMaxDrawdown {
  /** Depth as a negative decimal fraction (−0.18 = −18%). */
  depth: number;
  peakDate: string;
  troughDate: string;
}

export interface NavWindowStats {
  /** Total return over the window (last/first − 1). */
  periodReturn: number | null;
  /** Annualized return from calendar time between first and last point. */
  cagr: number | null;
  /** Annualized standard deviation of daily NAV returns. */
  annualizedVolatility: number | null;
  maxDrawdown: NavMaxDrawdown | null;
}

/** Summary statistics for a windowed slice of the persisted NAV series. */
export function navWindowStats(points: PortfolioNavPoint[]): NavWindowStats {
  if (points.length < 2) {
    return {
      periodReturn: null,
      cagr: null,
      annualizedVolatility: null,
      maxDrawdown: null,
    };
  }

  const first = points[0];
  const last = points[points.length - 1];
  const periodReturn = first.nav > 0 ? last.nav / first.nav - 1 : null;

  const calendarDays =
    (dateToUtcMs(last.date) - dateToUtcMs(first.date)) / MS_PER_DAY;
  const cagr =
    periodReturn !== null && calendarDays > 0
      ? Math.pow(1 + periodReturn, 365 / calendarDays) - 1
      : null;

  // Daily returns between consecutive NAV points.
  const returns: number[] = [];
  for (let i = 1; i < points.length; i += 1) {
    const prev = points[i - 1].nav;
    if (prev > 0) returns.push(points[i].nav / prev - 1);
  }
  let annualizedVolatility: number | null = null;
  if (returns.length >= 2) {
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance =
      returns.reduce((a, b) => a + (b - mean) ** 2, 0) / (returns.length - 1);
    annualizedVolatility = Math.sqrt(variance) * Math.sqrt(TRADING_DAYS_PER_YEAR);
  }

  // Max drawdown over the window (running peak).
  let peakNav = Number.NEGATIVE_INFINITY;
  let peakDate = first.date;
  let maxDrawdown: NavMaxDrawdown | null = null;
  for (const point of points) {
    if (point.nav > peakNav) {
      peakNav = point.nav;
      peakDate = point.date;
    } else if (peakNav > 0) {
      const depth = point.nav / peakNav - 1;
      if (maxDrawdown === null || depth < maxDrawdown.depth) {
        maxDrawdown = { depth, peakDate, troughDate: point.date };
      }
    }
  }

  return { periodReturn, cagr, annualizedVolatility, maxDrawdown };
}

/** Underwater series (decline from running peak, ≤ 0) of the NAV window. */
export function navDrawdownSeries(points: PortfolioNavPoint[]): SeriesPoint[] {
  let peak = Number.NEGATIVE_INFINITY;
  return points.map((point) => {
    if (point.nav > peak) peak = point.nav;
    return [point.date, peak > 0 ? point.nav / peak - 1 : 0];
  });
}

/** Slice NAV points to those on/after the given UTC timestamp. */
export function navPointsFrom(
  points: PortfolioNavPoint[],
  startTs: number,
): PortfolioNavPoint[] {
  return points.filter((point) => dateToUtcMs(point.date) >= startTs);
}
