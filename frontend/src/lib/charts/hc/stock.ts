import type { HistoryBar } from "@/lib/api/client";

export const STOCK_PRICE_ID = "price-main";
export const STOCK_VOLUME_ID = "price-volume";

export type StockChartType = "candles" | "ohlc" | "line" | "area";
export type StockScale = { log: boolean; pct: boolean };

export interface StockCompare {
  key: string;
  label: string;
  bars: HistoryBar[];
}

export function toMainSeriesData(
  bars: HistoryBar[],
  type: StockChartType,
): Array<[number, number] | [number, number, number, number, number]> {
  if (type === "candles" || type === "ohlc") {
    return bars.map((b) => [b.t, b.o, b.h, b.l, b.c]);
  }
  return bars.map((b) => [b.t, b.c]);
}

export function toVolumeSeriesData(bars: HistoryBar[]): Array<[number, number]> {
  return bars.map((b) => [b.t, b.v]);
}
