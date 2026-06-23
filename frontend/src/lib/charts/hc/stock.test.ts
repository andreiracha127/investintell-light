import { describe, expect, it } from "vitest";
import {
  STOCK_PRICE_ID,
  STOCK_VOLUME_ID,
  toMainSeriesData,
  toVolumeSeriesData,
} from "./stock";
import type { HistoryBar } from "@/lib/api/client";

const BARS: HistoryBar[] = [
  { t: 1, o: 10, h: 12, l: 9, c: 11, v: 100 },
  { t: 2, o: 11, h: 13, l: 10, c: 12, v: 200 },
];

describe("stock series data", () => {
  it("ids are stable", () => {
    expect(STOCK_PRICE_ID).toBe("price-main");
    expect(STOCK_VOLUME_ID).toBe("price-volume");
  });

  it("candles/ohlc map to [t,o,h,l,c]", () => {
    expect(toMainSeriesData(BARS, "candles")).toEqual([
      [1, 10, 12, 9, 11],
      [2, 11, 13, 10, 12],
    ]);
    expect(toMainSeriesData(BARS, "ohlc")[0]).toEqual([1, 10, 12, 9, 11]);
  });

  it("line/area map to [t,c]", () => {
    expect(toMainSeriesData(BARS, "line")).toEqual([[1, 11], [2, 12]]);
    expect(toMainSeriesData(BARS, "area")[1]).toEqual([2, 12]);
  });

  it("volume maps to [t,v]", () => {
    expect(toVolumeSeriesData(BARS)).toEqual([[1, 100], [2, 200]]);
  });
});
