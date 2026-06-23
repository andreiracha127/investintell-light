import type { Chart, Point, Series } from "highcharts";
import type { HistoryBar } from "@/lib/api/client";
import {
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  toMainSeriesData,
  toVolumeSeriesData,
  type StockChartType,
} from "./stock";

export interface LiveTickInput { price: number; size: number; timeMs: number }
export interface MergeResult { bars: HistoryBar[]; appended: boolean }

export function parseTickTimeMs(time: string, fallback = Date.now()): number {
  if (!time) return fallback;
  const parsed = Date.parse(time);
  return Number.isFinite(parsed) ? parsed : fallback;
}

function utcDayStart(ms: number): number {
  const d = new Date(ms);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate());
}

export function mergeTickIntoBars(bars: HistoryBar[], tick: LiveTickInput): MergeResult {
  if (!bars.length) return { bars, appended: false };
  const last = bars[bars.length - 1];
  if (utcDayStart(last.t) === utcDayStart(tick.timeMs)) {
    const updated: HistoryBar = {
      ...last,
      h: Math.max(last.h, tick.price),
      l: Math.min(last.l, tick.price),
      c: tick.price,
      v: last.v + tick.size,
    };
    return { bars: [...bars.slice(0, -1), updated], appended: false };
  }
  return {
    bars: [...bars, {
      t: utcDayStart(tick.timeMs),
      o: tick.price, h: tick.price, l: tick.price, c: tick.price, v: tick.size,
    }],
    appended: true,
  };
}

function getSeries(chart: Chart, id: string): Series | undefined {
  const found = chart.get(id);
  return found && "setData" in found ? (found as Series) : undefined;
}
function lastPoint(s: Series): Point | undefined {
  return s.points?.length ? s.points[s.points.length - 1] : undefined;
}

export function applyTickToStockChart({
  chart, bar, appended, type, showVolume, redraw = false,
}: {
  chart: Chart; bar: HistoryBar; appended: boolean;
  type: StockChartType; showVolume: boolean; redraw?: boolean;
}): void {
  const price = getSeries(chart, STOCK_PRICE_ID);
  if (!price) return;
  const [pricePoint] = toMainSeriesData([bar], type);
  if (appended) price.addPoint(pricePoint, false, false);
  else lastPoint(price)?.update(pricePoint, false);

  if (showVolume) {
    const vol = getSeries(chart, STOCK_VOLUME_ID);
    if (vol) {
      const [volPoint] = toVolumeSeriesData([bar]);
      if (appended) vol.addPoint(volPoint, false, false);
      else lastPoint(vol)?.update(volPoint, false);
    }
  }
  if (redraw) chart.redraw(false);
}
