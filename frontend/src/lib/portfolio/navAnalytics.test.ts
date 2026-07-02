import { describe, expect, it } from "vitest";

import type { PortfolioNavPoint } from "@/lib/api/client";
import {
  navDrawdownSeries,
  navPointsFrom,
  navWindowStats,
} from "@/lib/portfolio/navAnalytics";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";

function point(date: string, nav: number): PortfolioNavPoint {
  return { date, nav, market_value: nav, cash: 0, total_value: nav };
}

describe("navWindowStats", () => {
  it("returns nulls for fewer than two points", () => {
    expect(navWindowStats([point("2024-01-01", 100)])).toEqual({
      periodReturn: null,
      cagr: null,
      annualizedVolatility: null,
      maxDrawdown: null,
    });
  });

  it("computes the period return from first to last NAV", () => {
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-06-30", 112),
    ]);
    expect(stats.periodReturn).toBeCloseTo(0.12, 10);
  });

  it("annualizes the period return over calendar time (CAGR)", () => {
    // Exactly one 365-day year: CAGR equals the period return.
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-12-31", 110),
    ]);
    expect(stats.cagr).toBeCloseTo(Math.pow(1.1, 365 / 365) - 1, 6);
  });

  it("computes annualized volatility from daily returns (sample stdev ×√252)", () => {
    // Returns: +1%, −1% → mean 0, sample variance = 1e-4 → stdev 0.01.
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-01-02", 101),
      point("2024-01-03", 99.99),
    ]);
    const r1 = 101 / 100 - 1;
    const r2 = 99.99 / 101 - 1;
    const mean = (r1 + r2) / 2;
    const sampleVar = ((r1 - mean) ** 2 + (r2 - mean) ** 2) / 1;
    expect(stats.annualizedVolatility).toBeCloseTo(
      Math.sqrt(sampleVar) * Math.sqrt(252),
      10,
    );
  });

  it("finds the deepest drawdown with peak and trough dates", () => {
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-02-01", 120), // peak
      point("2024-03-01", 96), // −20% from peak
      point("2024-04-01", 130), // new high
      point("2024-05-01", 117), // −10% from new peak
    ]);
    expect(stats.maxDrawdown).not.toBeNull();
    expect(stats.maxDrawdown!.depth).toBeCloseTo(-0.2, 10);
    expect(stats.maxDrawdown!.peakDate).toBe("2024-02-01");
    expect(stats.maxDrawdown!.troughDate).toBe("2024-03-01");
  });

  it("reports null maxDrawdown for a monotonically rising NAV", () => {
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-02-01", 105),
      point("2024-03-01", 111),
    ]);
    expect(stats.maxDrawdown).toBeNull();
  });

  it("reports null maxDrawdown for a flat (cash-only) NAV — a plateau is not a decline", () => {
    const stats = navWindowStats([
      point("2024-01-01", 100),
      point("2024-02-01", 100),
      point("2024-03-01", 100),
    ]);
    expect(stats.maxDrawdown).toBeNull();
  });
});

describe("navDrawdownSeries", () => {
  it("is 0 at new highs and negative below the running peak", () => {
    const out = navDrawdownSeries([
      point("2024-01-01", 100),
      point("2024-01-02", 110),
      point("2024-01-03", 99),
    ]);
    expect(out[0]).toEqual(["2024-01-01", 0]);
    expect(out[1]).toEqual(["2024-01-02", 0]);
    expect(out[2][1]).toBeCloseTo(99 / 110 - 1, 10);
  });

  it("returns an empty series for empty input", () => {
    expect(navDrawdownSeries([])).toEqual([]);
  });
});

describe("navPointsFrom", () => {
  it("keeps only points on/after the start timestamp", () => {
    const points = [
      point("2024-01-01", 100),
      point("2024-02-01", 101),
      point("2024-03-01", 102),
    ];
    const out = navPointsFrom(points, dateToUtcMs("2024-02-01"));
    expect(out.map((p) => p.date)).toEqual(["2024-02-01", "2024-03-01"]);
  });
});
