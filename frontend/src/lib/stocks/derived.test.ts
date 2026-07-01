import { describe, expect, it } from "vitest";

import type { SeriesPoint } from "@/lib/api/client";
import { drawdownFromCumulative } from "@/lib/stocks/derived";

describe("drawdownFromCumulative", () => {
  it("returns 0 at every new high", () => {
    const series: SeriesPoint[] = [
      ["2024-01-01", 0],
      ["2024-01-02", 0.05],
      ["2024-01-03", 0.1],
    ];
    expect(drawdownFromCumulative(series).map(([, v]) => v)).toEqual([0, 0, 0]);
  });

  it("measures the decline from the running peak, not from the start", () => {
    const series: SeriesPoint[] = [
      ["2024-01-01", 0],
      ["2024-01-02", 0.25], // peak level 1.25
      ["2024-01-03", 0.0], // level 1.00 → 1.00/1.25 − 1 = −0.20
    ];
    const out = drawdownFromCumulative(series);
    expect(out[2][1]).toBeCloseTo(-0.2, 10);
  });

  it("recovers to 0 when a new peak is set after a drawdown", () => {
    const series: SeriesPoint[] = [
      ["2024-01-01", 0],
      ["2024-01-02", -0.1],
      ["2024-01-03", 0.05],
    ];
    const out = drawdownFromCumulative(series);
    expect(out[1][1]).toBeCloseTo(-0.1, 10);
    expect(out[2][1]).toBe(0);
  });

  it("keeps dates aligned with the input", () => {
    const series: SeriesPoint[] = [
      ["2024-01-01", 0],
      ["2024-01-02", -0.02],
    ];
    expect(drawdownFromCumulative(series).map(([d]) => d)).toEqual([
      "2024-01-01",
      "2024-01-02",
    ]);
  });

  it("handles an empty series", () => {
    expect(drawdownFromCumulative([])).toEqual([]);
  });

  it("handles a series that starts below zero (first level is the peak)", () => {
    const series: SeriesPoint[] = [
      ["2024-01-01", -0.05], // level 0.95 = peak
      ["2024-01-02", -0.148], // 0.852/0.95 − 1
    ];
    const out = drawdownFromCumulative(series);
    expect(out[0][1]).toBe(0);
    expect(out[1][1]).toBeCloseTo(0.852 / 0.95 - 1, 10);
  });
});
