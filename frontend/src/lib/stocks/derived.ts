/**
 * Series transforms derived 1:1 from backend payloads (no market data is
 * invented here — every input point comes from the API).
 */
import type { SeriesPoint } from "@/lib/api/client";

/**
 * Underwater (drawdown) series from a cumulative-return series.
 *
 * Input points are the backend's `cumulative_returns` values (decimal
 * fractions, 0.12 = +12% since range start). Each output value is the decline
 * from the running peak of the implied wealth level `1 + r`, ≤ 0 by
 * construction (0 at each new high).
 */
export function drawdownFromCumulative(series: SeriesPoint[]): SeriesPoint[] {
  let peak = Number.NEGATIVE_INFINITY;
  return series.map(([date, ret]) => {
    const level = 1 + ret;
    if (level > peak) peak = level;
    return [date, peak > 0 ? level / peak - 1 : 0];
  });
}
