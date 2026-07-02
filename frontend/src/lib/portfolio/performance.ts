/**
 * Synthetic portfolio NAV + per-holding contribution — reconstructed from the
 * CURRENT holdings' real price histories.
 *
 * The backend exposes no portfolio-level NAV time series, so the Performance
 * tab rebuilds one the way the design describes it: "reconstructed portfolio
 * value over time from the current holdings — illustrative, not a booked track
 * record". Each holding's quantity is held constant and multiplied by its
 * historical close (funds: NAV/line series; stocks: OHLC close); summed across
 * holdings plus cash gives NAV(t). Contribution over a selected range is each
 * holding's quantity × (priceEnd − priceStart); cash cancels, so the holding
 * contributions sum exactly to NAV(max) − NAV(min).
 *
 * Pure: no DOM, no network — safe to unit test in node. The component layer
 * fetches the histories (useQueries) and feeds them in as HoldingSeries.
 */

export interface HoldingSeries {
  ticker: string;
  name: string;
  /** Current quantity held (constant across the reconstructed path). */
  quantity: number;
  /** First date this holding is known to be active; null means portfolio inception. */
  effectiveFromTs?: number | null;
  /** [tsMs, price] ascending by timestamp. */
  points: Array<[number, number]>;
}

export interface NavReconstruction {
  /** [tsMs, nav] ascending. Empty when no holding has usable history. */
  nav: Array<[number, number]>;
  /** [tsMs, index] ascending, rebased so the first reconstructed point is 100. */
  navIndex: Array<[number, number]>;
  /** First timestamp where every holding has at least one price (ms). */
  startTs: number;
  /** Last timestamp on the reconstructed path (ms). */
  endTs: number;
}

/** Normalize a numeric date/epoch variant to milliseconds. */
export function toMs(t: number): number {
  // Some backend/DB adapters expose dates as Unix day ordinals. Treat small
  // integers as days, otherwise a value like 20_200 renders as a raw x-axis.
  if (t > 0 && t < 100_000) return Math.round(t * 86_400_000);
  // Epoch seconds are ~1e9 today. Milliseconds can be ~3e11 for older listings
  // (AAPL 1980), so don't use the common 1e12 shortcut here.
  if (t < 10_000_000_000) return Math.round(t * 1000);
  if (t < 10_000_000_000_000) return Math.round(t);
  if (t < 10_000_000_000_000_000) return Math.round(t / 1000);
  return Math.round(t / 1_000_000);
}

export interface ReconstructNavConfig {
  /** Portfolio inception timestamp in ms. When set, never synthesize before it. */
  inceptionTs?: number | null;
}

/** Extract [tsMs, close] points from an OHLC matrix ([t, o, h, l, c][]). */
export function pricePointsFromOhlc(ohlc: number[][]): Array<[number, number]> {
  return ohlc
    .filter((row) => row.length >= 5 && Number.isFinite(row[4]))
    .map((row) => [toMs(row[0]!), row[4]!] as [number, number]);
}

/** Extract [tsMs, value] points from a line matrix ([t, value][]). */
export function pricePointsFromLine(series: number[][]): Array<[number, number]> {
  return series
    .filter((row) => row.length >= 2 && Number.isFinite(row[1]))
    .map((row) => [toMs(row[0]!), row[1]!] as [number, number]);
}

const usableHoldings = (holdings: HoldingSeries[]): HoldingSeries[] =>
  holdings.filter((h) => h.quantity > 0 && h.points.length > 0);

function holdingEffectiveFrom(holding: HoldingSeries, fallbackTs: number): number {
  return holding.effectiveFromTs ?? fallbackTs;
}

/**
 * Reconstruct the synthetic NAV path: NAV(t) = Σ qtyᵢ·priceᵢ(t) + cash, where
 * priceᵢ(t) is forward-filled (last close at-or-before t). The path starts at
 * portfolio inception when provided; otherwise it falls back to the latest
 * first price across holdings.
 */
export function reconstructNav(
  holdings: HoldingSeries[],
  cash: number,
  config: ReconstructNavConfig = {},
): NavReconstruction {
  const usable = usableHoldings(holdings);
  if (usable.length === 0) return { nav: [], navIndex: [], startTs: 0, endTs: 0 };

  const defaultStartTs = Math.max(...usable.map((h) => h.points[0]![0]));
  const startTs = config.inceptionTs ?? defaultStartTs;
  const tsSet = new Set<number>([startTs]);
  for (const h of usable) {
    const effectiveFrom = holdingEffectiveFrom(h, startTs);
    if (effectiveFrom >= startTs) tsSet.add(effectiveFrom);
    for (const [ts] of h.points) {
      if (ts >= startTs) tsSet.add(ts);
    }
  }
  const allTs = [...tsSet].sort((a, b) => a - b);

  // One advancing pointer per holding (allTs is ascending), so each holding's
  // forward-filled price is found in a single linear pass.
  const cursor = usable.map(() => 0);
  const nav: Array<[number, number]> = allTs.map((ts) => {
    let sum = cash;
    usable.forEach((h, hi) => {
      if (ts < holdingEffectiveFrom(h, startTs)) return;
      let j = cursor[hi]!;
      while (j + 1 < h.points.length && h.points[j + 1]![0] <= ts) j++;
      cursor[hi] = j;
      sum += h.quantity * h.points[j]![1];
    });
    return [ts, parseFloat(sum.toFixed(2))];
  });
  const base = nav[0]?.[1] ?? 0;
  const navIndex =
    base > 0
      ? nav.map(
          ([ts, value]) =>
            [ts, parseFloat(((value / base) * 100).toFixed(4))] as [number, number],
        )
      : [];

  return { nav, navIndex, startTs, endTs: allTs[allTs.length - 1]! };
}
