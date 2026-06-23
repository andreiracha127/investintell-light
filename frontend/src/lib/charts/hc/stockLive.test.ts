import { describe, expect, it } from "vitest";
import { mergeTickIntoBars, parseTickTimeMs } from "./stockLive";
import type { HistoryBar } from "@/lib/api/client";

const DAY = 86_400_000;
const bars: HistoryBar[] = [{ t: 0, o: 10, h: 12, l: 9, c: 11, v: 100 }];

describe("parseTickTimeMs", () => {
  it("parses ISO, falls back on junk", () => {
    expect(parseTickTimeMs("1970-01-01T00:00:00Z")).toBe(0);
    expect(parseTickTimeMs("", 42)).toBe(42);
    expect(parseTickTimeMs("nonsense", 7)).toBe(7);
  });
});

describe("mergeTickIntoBars", () => {
  it("updates the last bar on the same UTC day (no append)", () => {
    const r = mergeTickIntoBars(bars, { price: 13, size: 50, timeMs: 1000 });
    expect(r.appended).toBe(false);
    expect(r.bars).toHaveLength(1);
    expect(r.bars[0]).toMatchObject({ h: 13, l: 9, c: 13, v: 150 });
  });

  it("appends a new bar on a new UTC day", () => {
    const r = mergeTickIntoBars(bars, { price: 20, size: 5, timeMs: DAY + 1000 });
    expect(r.appended).toBe(true);
    expect(r.bars).toHaveLength(2);
    expect(r.bars[1]).toMatchObject({ t: DAY, o: 20, h: 20, l: 20, c: 20, v: 5 });
  });

  it("returns input unchanged when bars is empty", () => {
    expect(mergeTickIntoBars([], { price: 1, size: 1, timeMs: 1 })).toEqual({ bars: [], appended: false });
  });
});
