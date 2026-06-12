/**
 * Performance series math — pure, typed, finance-adjacent helpers.
 *
 * Kept separate from lib/charts/* because these are computations over raw
 * data, not display-layer concerns. Chart option builders import from here
 * and do no arithmetic themselves.
 *
 * All inputs follow the FundNavPoint contract: `date` is an ISO-8601 date
 * string ("YYYY-MM-DD"), `nav` may be null (holiday-fill / missing data).
 *
 * TIMEZONE SAFETY: date components (year/month/day) are extracted by
 * splitting the ISO string on "-" — no `new Date(str)` call is made on a
 * bare date string, which would parse as UTC midnight and can shift to the
 * prior calendar day in negative-UTC environments. This mirrors the pattern
 * used in lib/format.ts, which appends "T00:00:00Z" before constructing a
 * Date only for display formatting, never for component arithmetic.
 */

import type { FundNavPoint } from "@/lib/api/client";

// ── Internal helpers ──────────────────────────────────────────────────────

interface DateParts {
  year: number;
  month: number; // 1-based
  day: number;
}

/** Parse "YYYY-MM-DD" into integer components. Never constructs a Date. */
function parseParts(iso: string): DateParts {
  const [y, m, d] = iso.split("-").map(Number);
  return { year: y, month: m, day: d };
}

// ── Monthly returns ───────────────────────────────────────────────────────

export interface MonthlyReturn {
  year: number;
  /** 1 = January … 12 = December */
  month: number;
  /** Compounded return as a decimal fraction (0.05 = +5%). */
  value: number;
}

/**
 * Compute month-end over previous month-end compounded returns from a
 * series of daily NAV observations.
 *
 * Algorithm:
 *   1. Filter out null-nav points and sort ascending by date.
 *   2. Group by (year, month); take the last valid NAV in each month as the
 *      month-end reference.
 *   3. For each month that has a known prior month-end, emit
 *      `(navEnd / navPrev) - 1`.
 *
 * Edge decisions:
 *   - The first month in the series is ALWAYS excluded: it has no prior
 *     month-end baseline so computing a return would require an arbitrary
 *     starting point. Callers should note this when displaying the oldest
 *     month label.
 *   - The current (potentially partial) month — i.e. the LAST month in the
 *     series — is INCLUDED only if it contains ≥ 2 valid nav observations
 *     AND there is a prior month-end, preventing a single-observation
 *     month-to-date figure from registering as a meaningful data point.
 *     All prior (closed) calendar months are emitted regardless of their
 *     observation count, because a single month-end NAV is sufficient to
 *     compute (navEnd / navPrev − 1). No `partial` flag is emitted: callers
 *     that need to distinguish MTD from full-month returns should check
 *     whether the last month in the series coincides with today.
 *   - Null navs are skipped at the individual-observation level; a month
 *     whose every observation is null produces no month-end reference and
 *     is silently dropped (no return emitted for that month either).
 *
 * @param nav  FundNavPoint array (any order, may contain null navs).
 * @returns    Monthly return records in ascending (year, month) order.
 */
export function monthlyReturns(nav: FundNavPoint[]): MonthlyReturn[] {
  // 1. Filter nulls, parse dates, sort ascending.
  const valid = nav
    .filter((p): p is FundNavPoint & { nav: number } => p.nav !== null)
    .map((p) => ({ parts: parseParts(p.date), nav: p.nav }))
    .sort((a, b) => {
      const ya = a.parts.year,
        yb = b.parts.year;
      if (ya !== yb) return ya - yb;
      const ma = a.parts.month,
        mb = b.parts.month;
      if (ma !== mb) return ma - mb;
      return a.parts.day - b.parts.day;
    });

  if (valid.length === 0) return [];

  // 2. Group by (year, month) — take last nav in each group as month-end.
  //    A Map keyed "YYYY-MM" preserves insertion order (ascending after sort).
  const monthMap = new Map<string, { year: number; month: number; nav: number; count: number }>();
  for (const pt of valid) {
    const key = `${pt.parts.year}-${String(pt.parts.month).padStart(2, "0")}`;
    const existing = monthMap.get(key);
    if (!existing) {
      monthMap.set(key, {
        year: pt.parts.year,
        month: pt.parts.month,
        nav: pt.nav,
        count: 1,
      });
    } else {
      // Later in the month (sorted asc) → overwrite nav, increment count.
      existing.nav = pt.nav;
      existing.count += 1;
    }
  }

  const months = Array.from(monthMap.values());
  if (months.length < 2) return [];

  // 3. Build returns: skip the first month (no prior baseline).
  const result: MonthlyReturn[] = [];
  for (let i = 1; i < months.length; i++) {
    const cur = months[i];
    const prev = months[i - 1];

    // Partial-month guard: applies ONLY to the last (potentially open) month.
    // Closed historical months always have a valid month-end NAV regardless
    // of how many intra-month observations were captured.
    if (i === months.length - 1 && cur.count < 2) continue;

    result.push({
      year: cur.year,
      month: cur.month,
      value: cur.nav / prev.nav - 1,
    });
  }

  return result;
}

// ── Drawdown series ───────────────────────────────────────────────────────

export interface DrawdownResult {
  /** ISO date strings, parallel to `values`. */
  dates: string[];
  /**
   * Running peak drawdown values as decimal fractions (≤ 0).
   * 0 = at a new all-time high; −0.15 = 15% below the running peak.
   */
  values: number[];
  /** Deepest peak-to-trough window. */
  worst: {
    /** Date of the running peak preceding the deepest trough. */
    from: string;
    /** Date of the deepest trough. */
    to: string;
    /** Depth as a decimal fraction (≤ 0). */
    depth: number;
  };
}

/**
 * Compute the running peak drawdown series from a daily NAV array.
 *
 * For each valid (non-null) NAV observation the drawdown is:
 *   `(nav - runningPeak) / runningPeak`   (≤ 0 by construction)
 *
 * Null nav observations are skipped; the drawdown series covers only dates
 * with valid nav.
 *
 * Returns null when the input contains fewer than 2 valid nav points
 * (drawdown is undefined with only one observation).
 *
 * @param nav  FundNavPoint array (any order, may contain null navs).
 */
export function drawdownSeries(nav: FundNavPoint[]): DrawdownResult | null {
  // Filter and sort ascending.
  const valid = nav
    .filter((p): p is FundNavPoint & { nav: number } => p.nav !== null)
    .sort((a, b) => a.date.localeCompare(b.date));

  if (valid.length < 2) return null;

  const dates: string[] = [];
  const values: number[] = [];

  let runningPeak = valid[0].nav;
  let peakDate = valid[0].date;

  let worstDepth = 0;
  let worstFrom = valid[0].date;
  let worstTo = valid[0].date;

  for (const pt of valid) {
    if (pt.nav > runningPeak) {
      runningPeak = pt.nav;
      peakDate = pt.date;
    }

    const dd = (pt.nav - runningPeak) / runningPeak;
    dates.push(pt.date);
    values.push(dd);

    if (dd < worstDepth) {
      worstDepth = dd;
      worstFrom = peakDate;
      worstTo = pt.date;
    }
  }

  return {
    dates,
    values,
    worst: { from: worstFrom, to: worstTo, depth: worstDepth },
  };
}
