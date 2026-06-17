import type { Chart, Point, Series } from "highcharts";

import {
  PRICE_SERIES_ID,
  VOLUME_SERIES_ID,
  toMainSeriesData,
  toVolumeSeriesData,
  type PriceBar,
  type PriceChartType,
  type PricePeriod,
} from "@/lib/charts/hc/priceStock";

export interface LiveTickInput {
  price: number;
  size: number;
  timeMs: number;
}

export interface MergeTickResult {
  bars: PriceBar[];
  /** True when the tick started a new bar (append); false when it updated the last bar. */
  appended: boolean;
}

export function parseTickTimeMs(time: string, fallback = Date.now()): number {
  if (!time) return fallback;
  const parsed = Date.parse(time);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function utcDayStart(ms: number): number {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

function sameUtcDay(a: number, b: number): boolean {
  return utcDayStart(a) === utcDayStart(b);
}

/**
 * Merge a tick into a bar array, returning the next array plus whether a new
 * bar was appended (new UTC day) or the last bar was updated (same UTC day).
 */
export function mergeTickIntoBarsResult(
  bars: PriceBar[],
  tick: LiveTickInput,
): MergeTickResult {
  if (!bars.length) return { bars, appended: false };
  const last = bars[bars.length - 1];
  if (sameUtcDay(last.t, tick.timeMs)) {
    const updated: PriceBar = {
      ...last,
      h: Math.max(last.h, tick.price),
      l: Math.min(last.l, tick.price),
      c: tick.price,
      v: last.v + tick.size,
    };
    return { bars: [...bars.slice(0, -1), updated], appended: false };
  }
  return {
    bars: [
      ...bars,
      {
        t: utcDayStart(tick.timeMs),
        o: tick.price,
        h: tick.price,
        l: tick.price,
        c: tick.price,
        v: tick.size,
      },
    ],
    appended: true,
  };
}

export function mergeTickIntoBars(bars: PriceBar[], tick: LiveTickInput): PriceBar[] {
  return mergeTickIntoBarsResult(bars, tick).bars;
}

function getSeries(chart: Chart, id: string): Series | undefined {
  const found = chart.get(id);
  return found && "setData" in found ? (found as Series) : undefined;
}

function lastPoint(series: Series): Point | undefined {
  const points = series.points;
  return points && points.length ? points[points.length - 1] : undefined;
}

/**
 * Incrementally apply a single bar (the latest one) to the live chart without
 * replacing the whole data array. When `appended` is true the bar is added as a
 * new point; otherwise the trailing point is updated in place. Linked
 * indicators (SMA/RSI/volume-derived) recompute from the main series on redraw,
 * so they do not need manual updates. Pass `redraw: true` to redraw once after
 * applying; default is false so callers can coalesce redraws.
 */
export function applyTickToLiveChart({
  chart,
  bar,
  appended,
  type,
  showVolume,
  redraw = false,
}: {
  chart: Chart;
  bar: PriceBar;
  appended: boolean;
  type: PriceChartType;
  showVolume: boolean;
  redraw?: boolean;
}): void {
  const price = getSeries(chart, PRICE_SERIES_ID);
  if (!price) return;

  const [pricePoint] = toMainSeriesData([bar], type);
  if (appended) {
    price.addPoint(pricePoint, false, false);
  } else {
    lastPoint(price)?.update(pricePoint, false);
  }

  if (showVolume) {
    const volume = getSeries(chart, VOLUME_SERIES_ID);
    if (volume) {
      const [volumePoint] = toVolumeSeriesData([bar]);
      if (appended) {
        volume.addPoint(volumePoint, false, false);
      } else {
        lastPoint(volume)?.update(volumePoint, false);
      }
    }
  }

  if (redraw) chart.redraw(false);
}

export function applyBarsToLiveChart({
  chart,
  bars,
  type,
  period: _period,
  showVolume,
}: {
  chart: Chart;
  bars: PriceBar[];
  type: PriceChartType;
  period: PricePeriod;
  showVolume: boolean;
}): void {
  const price = getSeries(chart, PRICE_SERIES_ID);
  if (!price) return;

  price.setData(toMainSeriesData(bars, type), false, false, false);

  if (showVolume) {
    getSeries(chart, VOLUME_SERIES_ID)?.setData(toVolumeSeriesData(bars), false, false, false);
  }

  chart.redraw(false);
}
