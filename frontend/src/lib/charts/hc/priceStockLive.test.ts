import { describe, expect, it } from "vitest";

import { mergeTickIntoBars, parseTickTimeMs } from "@/lib/charts/hc/priceStockLive";
import type { PriceBar } from "@/lib/charts/hc/priceStock";

const DAY1 = Date.UTC(2024, 0, 2, 21);
const DAY2 = Date.UTC(2024, 0, 3, 14);

const BARS: PriceBar[] = [
  { t: Date.UTC(2024, 0, 2), o: 100, h: 105, l: 98, c: 102, v: 1000 },
];

describe("parseTickTimeMs", () => {
  it("parses an ISO time string", () => {
    expect(parseTickTimeMs("2024-01-03T14:30:00.000Z", DAY1)).toBe(
      Date.UTC(2024, 0, 3, 14, 30),
    );
  });

  it("falls back when the tick time is empty or invalid", () => {
    expect(parseTickTimeMs("", DAY1)).toBe(DAY1);
    expect(parseTickTimeMs("not-a-date", DAY1)).toBe(DAY1);
  });
});

describe("mergeTickIntoBars", () => {
  it("updates the latest bar when the tick is on the same UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 107, size: 50, timeMs: DAY1 });
    expect(next).toHaveLength(1);
    expect(next[0]).toEqual({
      t: BARS[0].t,
      o: 100,
      h: 107,
      l: 98,
      c: 107,
      v: 1050,
    });
    expect(BARS[0].c).toBe(102);
  });

  it("appends a new bar when the tick is on a later UTC date", () => {
    const next = mergeTickIntoBars(BARS, { price: 111, size: 75, timeMs: DAY2 });
    expect(next).toHaveLength(2);
    expect(next[1]).toEqual({
      t: Date.UTC(2024, 0, 3),
      o: 111,
      h: 111,
      l: 111,
      c: 111,
      v: 75,
    });
  });

  it("returns the same empty array when there are no bars", () => {
    const empty: PriceBar[] = [];
    expect(mergeTickIntoBars(empty, { price: 1, size: 1, timeMs: DAY1 })).toBe(empty);
  });
});
