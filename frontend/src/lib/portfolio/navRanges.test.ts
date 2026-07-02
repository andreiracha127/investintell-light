import { describe, expect, it } from "vitest";

import {
  OVERVIEW_NAV_RANGES,
  PERF_NAV_RANGES,
  sliceNavWindow,
} from "@/lib/portfolio/navRanges";

const DAY = 24 * 60 * 60 * 1000;

/** A daily NAV series from `start` (UTC ms) spanning `count` days. */
function series(start: number, count: number): Array<[number, number]> {
  return Array.from({ length: count }, (_, i) => [start + i * DAY, 100 + i]);
}

describe("sliceNavWindow", () => {
  it("returns the input unchanged for an empty series", () => {
    expect(sliceNavWindow([], "1M")).toEqual([]);
  });

  it("ALL returns the full series regardless of length", () => {
    const nav = series(Date.UTC(2020, 0, 1), 900);
    expect(sliceNavWindow(nav, "ALL")).toEqual(nav);
  });

  it("1M keeps only points within 31 calendar days of the last point", () => {
    const nav = series(Date.UTC(2026, 0, 1), 400); // ~13 months
    const windowed = sliceNavWindow(nav, "1M");
    const end = nav[nav.length - 1]![0];
    expect(windowed.every(([ts]) => ts >= end - 31 * DAY)).toBe(true);
    expect(windowed[windowed.length - 1]).toEqual(nav[nav.length - 1]);
    expect(windowed.length).toBeLessThan(nav.length);
    expect(windowed.length).toBeGreaterThan(1);
  });

  it("1Y and 6M cut different calendar windows off the same series", () => {
    const nav = series(Date.UTC(2024, 0, 1), 800);
    const oneYear = sliceNavWindow(nav, "1Y");
    const sixMonths = sliceNavWindow(nav, "6M");
    expect(oneYear.length).toBeGreaterThan(sixMonths.length);
  });

  it("YTD slices from Jan 1 (UTC) of the last point's year", () => {
    const nav = series(Date.UTC(2024, 0, 1), 800); // crosses into 2026
    const windowed = sliceNavWindow(nav, "YTD");
    const end = nav[nav.length - 1]![0];
    const endYear = new Date(end).getUTCFullYear();
    expect(windowed.every(([ts]) => ts >= Date.UTC(endYear, 0, 1))).toBe(true);
  });

  it("falls back to the last two points when the calendar window is too tight", () => {
    // Only two points, 400 days apart — "1M" alone would keep just the last one.
    const nav: Array<[number, number]> = [
      [Date.UTC(2025, 0, 1), 100],
      [Date.UTC(2026, 1, 5), 110],
    ];
    expect(sliceNavWindow(nav, "1M")).toEqual(nav);
  });

  it("falls back to the single point when the series itself has only one", () => {
    const nav: Array<[number, number]> = [[Date.UTC(2026, 0, 1), 100]];
    expect(sliceNavWindow(nav, "1M")).toEqual(nav);
  });
});

describe("preset labels", () => {
  it("Performance keeps its full six-preset set", () => {
    expect(PERF_NAV_RANGES.map((r) => r.key)).toEqual([
      "1M",
      "3M",
      "6M",
      "YTD",
      "1Y",
      "ALL",
    ]);
  });

  it("Overview keeps its smaller four-preset set with its own 'Max' label", () => {
    expect(OVERVIEW_NAV_RANGES.map((r) => r.key)).toEqual(["1M", "6M", "1Y", "ALL"]);
    expect(OVERVIEW_NAV_RANGES.find((r) => r.key === "ALL")?.label).toBe("Max");
  });
});
