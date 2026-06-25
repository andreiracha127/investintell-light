import type { RangePreset } from "@/lib/api/client";

export const STOCK_DATA_STALE_TIME_MS = 60 * 60 * 1000;
export const STOCK_ROLLING_WINDOW = 63;

export const stockQueryKeys = {
  quote: (ticker: string) => ["stock-quote", ticker.toUpperCase()] as const,
  analysis: (ticker: string, range: RangePreset, window: number) =>
    ["analysis", ticker.toUpperCase(), range, window] as const,
  historyFull: (ticker: string) =>
    ["stock-history-full", ticker.toUpperCase()] as const,
};
