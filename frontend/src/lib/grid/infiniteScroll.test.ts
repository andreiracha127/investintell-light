import { describe, expect, it } from "vitest";

import {
  isNearBottom,
  loadedCount,
  nextPageParam,
} from "./infiniteScroll";

interface Page {
  total: number;
  rows: unknown[];
}

const rowCount = (p: Page) => p.rows.length;
const page = (total: number, n: number): Page => ({
  total,
  rows: Array.from({ length: n }),
});

describe("loadedCount", () => {
  it("sums the row counts across pages", () => {
    expect(loadedCount([page(10, 4), page(10, 3)], rowCount)).toBe(7);
  });

  it("is 0 for no pages", () => {
    expect(loadedCount<Page>([], rowCount)).toBe(0);
  });
});

describe("nextPageParam", () => {
  it("returns the next 1-based index while rows remain", () => {
    const pages = [page(250, 100)];
    expect(nextPageParam(pages[0], pages, rowCount)).toBe(2);
  });

  it("keeps incrementing across multiple loaded pages", () => {
    const pages = [page(250, 100), page(250, 100)];
    expect(nextPageParam(pages[1], pages, rowCount)).toBe(3);
  });

  it("stops (undefined) once loaded count reaches total", () => {
    const pages = [page(200, 100), page(200, 100)];
    expect(nextPageParam(pages[1], pages, rowCount)).toBeUndefined();
  });

  it("stops when a single page already covers the total", () => {
    const pages = [page(40, 40)];
    expect(nextPageParam(pages[0], pages, rowCount)).toBeUndefined();
  });

  it("uses the LAST page's total (handles a shrinking total)", () => {
    // total dropped to 80 while 100 rows were already loaded → no more fetches.
    const pages = [page(100, 100), page(80, 0)];
    expect(nextPageParam(pages[1], pages, rowCount)).toBeUndefined();
  });

  it("keeps advancing on an empty mid-stream page (deterministic-paging assumption)", () => {
    // An empty page below total does not raise `loaded`, so we still ask for
    // the next index — the backend is trusted to return rows until loaded≥total.
    const pages = [page(250, 100), page(250, 0)];
    expect(nextPageParam(pages[1], pages, rowCount)).toBe(3);
  });
});

describe("isNearBottom", () => {
  const threshold = 100;

  it("is true at the exact threshold distance", () => {
    // scrollTop + clientHeight = 900; scrollHeight - threshold = 900.
    expect(
      isNearBottom(
        { scrollTop: 500, clientHeight: 400, scrollHeight: 1000 },
        threshold,
      ),
    ).toBe(true);
  });

  it("is true past the bottom (overscroll)", () => {
    expect(
      isNearBottom(
        { scrollTop: 700, clientHeight: 400, scrollHeight: 1000 },
        threshold,
      ),
    ).toBe(true);
  });

  it("is false far from the bottom", () => {
    expect(
      isNearBottom(
        { scrollTop: 0, clientHeight: 400, scrollHeight: 1000 },
        threshold,
      ),
    ).toBe(false);
  });
});
