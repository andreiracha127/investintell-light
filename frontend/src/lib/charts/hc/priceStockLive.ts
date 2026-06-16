import type { Chart, Series } from "highcharts";

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

export function mergeTickIntoBars(bars: PriceBar[], tick: LiveTickInput): PriceBar[] {
  if (!bars.length) return bars;
  const last = bars[bars.length - 1];
  if (sameUtcDay(last.t, tick.timeMs)) {
    const updated: PriceBar = {
      ...last,
      h: Math.max(last.h, tick.price),
      l: Math.min(last.l, tick.price),
      c: tick.price,
      v: last.v + tick.size,
    };
    return [...bars.slice(0, -1), updated];
  }
  return [
    ...bars,
    {
      t: utcDayStart(tick.timeMs),
      o: tick.price,
      h: tick.price,
      l: tick.price,
      c: tick.price,
      v: tick.size,
    },
  ];
}

function getSeries(chart: Chart, id: string): Series | undefined {
  const found = chart.get(id);
  return found && "setData" in found ? (found as Series) : undefined;
}

export function applyBarsToLiveChart({
  chart,
  bars,
  type,
  period,
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

  if (period === "D") {
    chart.redraw(false);
  } else {
    chart.redraw(false);
  }
}
