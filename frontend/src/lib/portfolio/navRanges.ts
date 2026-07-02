/**
 * Shared NAV range presets + windowing for the Overview mini-panel and the
 * Performance tab. Both screens plot the same persisted NAV series and must
 * cut a "1M"/"1Y"/etc. window with the same semantics — calendar days back
 * from the last point, not trading bars — so the two ranges never disagree
 * about what "1M" means for the same underlying NAV.
 */

const MS_PER_DAY = 24 * 60 * 60 * 1000;

export type NavRangeKey = "1M" | "3M" | "6M" | "YTD" | "1Y" | "ALL";

interface NavRangeDef {
  /** Calendar days back from the last point; "ytd" = since Jan 1 of the last
   * point's year; "all" = the full series. */
  days: number | "ytd" | "all";
}

const NAV_RANGE_DEFS: Record<NavRangeKey, NavRangeDef> = {
  "1M": { days: 31 },
  "3M": { days: 92 },
  "6M": { days: 184 },
  YTD: { days: "ytd" },
  "1Y": { days: 366 },
  ALL: { days: "all" },
};

export interface NavRangePreset {
  key: NavRangeKey;
  label: string;
}

/** Performance tab: full preset set. */
export const PERF_NAV_RANGES: readonly NavRangePreset[] = [
  { key: "1M", label: "1M" },
  { key: "3M", label: "3M" },
  { key: "6M", label: "6M" },
  { key: "YTD", label: "YTD" },
  { key: "1Y", label: "1Y" },
  { key: "ALL", label: "All" },
];

/** Overview mini-panel: fewer presets, same underlying semantics. */
export const OVERVIEW_NAV_RANGES: readonly NavRangePreset[] = [
  { key: "1M", label: "1M" },
  { key: "6M", label: "6M" },
  { key: "1Y", label: "1Y" },
  { key: "ALL", label: "Max" },
];

/**
 * Slice a `[tsMs, value]` NAV series to the window described by `key`,
 * anchored on the series' last point. Falls back to the last two points (or
 * fewer, if the series itself is shorter) when the calendar window would
 * otherwise collapse to 0-1 points — mirrors how a too-young portfolio still
 * gets a renderable (if short) line instead of an empty chart.
 */
export function sliceNavWindow<T extends [number, number]>(
  nav: readonly T[],
  key: NavRangeKey,
): T[] {
  if (nav.length === 0) return [...nav];
  const def = NAV_RANGE_DEFS[key];
  if (def.days === "all") return [...nav];

  const end = nav[nav.length - 1]![0];
  let start: number;
  if (def.days === "ytd") {
    const endDate = new Date(end);
    start = Date.UTC(endDate.getUTCFullYear(), 0, 1);
  } else {
    start = end - def.days * MS_PER_DAY;
  }

  const windowed = nav.filter(([ts]) => ts >= start);
  return windowed.length > 1 ? windowed : nav.slice(-Math.min(2, nav.length));
}
