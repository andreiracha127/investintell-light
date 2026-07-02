import { describe, expect, it } from "vitest";

import {
  pricePointsFromLine,
  pricePointsFromOhlc,
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
  it("scales day and second epochs to milliseconds and leaves ms untouched", () => {
    expect(toMs(20_254)).toBe(20_254 * 86_400_000); // Unix day ordinal -> ms
    expect(toMs(1_700_000_000)).toBe(1_700_000_000_000); // seconds → ms
    expect(toMs(344_476_800_000)).toBe(344_476_800_000); // 1980 ms timestamp
    expect(toMs(1_700_000_000_000)).toBe(1_700_000_000_000); // already ms
    expect(toMs(1_700_000_000_000_000)).toBe(1_700_000_000_000); // micros → ms
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
    const { nav, navIndex, startTs, endTs } = reconstructNav(HOLDINGS, 1000);
    expect(startTs).toBe(D2);
    expect(endTs).toBe(D3);
    expect(nav).toEqual([
      [D2, 2350], // 10·110 + 5·50 + 1000
      [D3, 2500], // 10·120 + 5·60 + 1000
    ]);
    expect(navIndex).toEqual([
      [D2, 100],
      [D3, 106.383],
    ]);
  });

  it("returns an empty path when no holding has usable history", () => {
    expect(reconstructNav([], 1000)).toEqual({ nav: [], navIndex: [], startTs: 0, endTs: 0 });
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

  it("does not synthesize before portfolio inception and activates holdings by effective date", () => {
    const holdings: HoldingSeries[] = [
      {
        ticker: "AAA",
        name: "A",
        quantity: 10,
        effectiveFromTs: D1,
        points: [
          [D1, 100],
          [D2, 110],
          [D3, 120],
        ],
      },
      {
        ticker: "BBB",
        name: "B",
        quantity: 5,
        effectiveFromTs: D3,
        points: [
          [D2, 50],
          [D3, 60],
        ],
      },
    ];
    const { nav, navIndex, startTs } = reconstructNav(holdings, 0, {
      inceptionTs: D1,
    });

    expect(startTs).toBe(D1);
    expect(nav).toEqual([
      [D1, 1000],
      [D2, 1100],
      [D3, 1500],
    ]);
    expect(navIndex).toEqual([
      [D1, 100],
      [D2, 110],
      [D3, 150],
    ]);
  });
});
