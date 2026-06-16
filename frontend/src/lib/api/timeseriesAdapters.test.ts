import { describe, expect, it } from "vitest";

import {
  fundTimeseriesToHistoryBars,
  fundTimeseriesToNavPoints,
  stockTimeseriesToHistoryBars,
  type FundTimeseries,
  type StockTimeseries,
} from "@/lib/api/client";

describe("timeseries compatibility adapters", () => {
  it("maps stock OHLC and volume arrays into legacy chart bars", () => {
    const t = Date.UTC(2026, 5, 11);
    const data: StockTimeseries = {
      id: "SPY",
      interval: "daily",
      ohlc: [[t, 100, 105, 98, 104]],
      volume: [[t, 12345]],
    };

    expect(stockTimeseriesToHistoryBars(data)).toEqual([
      { t, o: 100, h: 105, l: 98, c: 104, v: 12345 },
    ]);
  });

  it("maps fund NAV line arrays into legacy chart bars and NAV points", () => {
    const t = Date.UTC(2026, 5, 11);
    const data: FundTimeseries = {
      id: "fund-1",
      interval: "monthly",
      series: [[t, 306.2]],
    };

    expect(fundTimeseriesToHistoryBars(data)).toEqual([
      { t, o: 306.2, h: 306.2, l: 306.2, c: 306.2, v: 0 },
    ]);
    expect(fundTimeseriesToNavPoints(data)).toEqual([
      { date: "2026-06-11", nav: 306.2 },
    ]);
  });
});
