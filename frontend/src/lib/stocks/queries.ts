import type { RangePreset } from "@/lib/api/client";

export const STOCK_DATA_STALE_TIME_MS = 60 * 60 * 1000;
export const STOCK_ROLLING_WINDOW = 63;

/** Selectable rolling windows in TRADING days (backend accepts 10..252). */
export const STOCK_ROLLING_WINDOWS = [21, 63, 126, 252] as const;
export type StockRollingWindow = (typeof STOCK_ROLLING_WINDOWS)[number];

/** Full available daily history — the backend caps `bars` at 5000 (~20y). */
export const STOCK_HISTORY_BARS_MAX = 5000;

export const stockQueryKeys = {
  quote: (ticker: string) => ["stock-quote", ticker.toUpperCase()] as const,
  analysis: (ticker: string, range: RangePreset, window: number) =>
    ["analysis", ticker.toUpperCase(), range, window] as const,
  historyFull: (ticker: string, bars: number = STOCK_HISTORY_BARS_MAX) =>
    ["stock-history-full", ticker.toUpperCase(), bars] as const,
};
