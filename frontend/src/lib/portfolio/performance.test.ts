import { describe, expect, it } from "vitest";

import {
  pricePointsFromLine,
  pricePointsFromOhlc,
  periodContributions,
  periodTotal,
  reconstructNav,
  toMs,
  type HoldingSeries,
} from "@/lib/portfolio/performance";

const D1 = Date.UTC(2026, 0, 1);
const D2 = Date.UTC(2026, 0, 2);
const D3 = Date.UTC(2026, 0, 3);

const HOLDINGS: HoldingSeries[] = [
  {
    ticker: "AAA",
    name: "Alpha",
    quantity: 10,
    points: [
      [D1, 100],
      [D2, 110],
      [D3, 120],
    ],
  },
  {
    // Starts one day later — the path must start where ALL holdings exist.
    ticker: "BBB",
    name: "Beta",
    quantity: 5,
    points: [
      [D2, 50],
      [D3, 60],
    ],
  },
];

describe("toMs", () => {
  it("scales second-epochs to milliseconds and leaves ms untouched", () => {
    expect(toMs(1_700_000_000)).toBe(1_700_000_000_000); // seconds → ms
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000); // already ms
  });
});

describe("pricePoints extractors", () => {
  it("takes the close column from an OHLC matrix", () => {
    const pts = pricePointsFromOhlc([
      [1_700_000_000, 1, 2, 0.5, 1.5],
      [1_700_086_400, 1.5, 2, 1, 1.8],
    ]);
    expect(pts).toEqual([
      [1_700_000_000_000, 1.5],
      [1_700_086_400_000, 1.8],
    ]);
  });

  it("takes the value column from a line matrix and drops malformed rows", () => {
    const pts = pricePointsFromLine([
      [1_700_000_000_000, 10],
      [1_700_086_400_000, Number.NaN],
    ]);
    expect(pts).toEqual([[1_700_000_000_000, 10]]);
  });
});

describe("reconstructNav", () => {
  it("starts at the latest first-timestamp and sums qty·price + cash", () => {
    const { nav, startTs, endTs } = reconstructNav(HOLDINGS, 1000);
    expect(startTs).toBe(D2);
    expect(endTs).toBe(D3);
    expect(nav).toEqual([
      [D2, 2350], // 10·110 + 5·50 + 1000
      [D3, 2500], // 10·120 + 5·60 + 1000
    ]);
  });

  it("returns an empty path when no holding has usable history", () => {
    expect(reconstructNav([], 1000)).toEqual({ nav: [], startTs: 0, endTs: 0 });
    expect(
      reconstructNav([{ ticker: "X", name: "X", quantity: 0, points: [[D1, 1]] }], 0).nav,
    ).toEqual([]);
  });

  it("forward-fills a holding that has no point on a given timestamp", () => {
    const holdings: HoldingSeries[] = [
      { ticker: "AAA", name: "A", quantity: 1, points: [[D1, 100], [D2, 110], [D3, 120]] },
      { ticker: "BBB", name: "B", quantity: 1, points: [[D1, 50], [D3, 70]] }, // no D2
    ];
    const { nav } = reconstructNav(holdings, 0);
    // At D2, BBB forward-fills its D1 price (50): 110 + 50 = 160.
    expect(nav).toEqual([
      [D1, 150],
      [D2, 160],
      [D3, 190],
    ]);
  });
});

describe("periodContributions / periodTotal", () => {
  it("computes qty·(end−start) per holding and a matching total", () => {
    const contribs = periodContributions(HOLDINGS, D2, D3);
    expect(contribs).toEqual([
      { ticker: "AAA", name: "Alpha", value: 100, ret: 120 / 110 - 1 },
      { ticker: "BBB", name: "Beta", value: 50, ret: 60 / 50 - 1 },
    ]);
    // Σ contributions == NAV(D3) − NAV(D2) == 2500 − 2350.
    expect(periodTotal(contribs)).toBe(150);
  });

  it("uses the first price when the period start precedes a holding's history", () => {
    const contribs = periodContributions(HOLDINGS, D1, D3);
    // BBB has no point at D1 → start price falls back to its first (50).
    const bbb = contribs.find((c) => c.ticker === "BBB");
    expect(bbb?.value).toBe(50); // 5·(60−50)
  });
});
