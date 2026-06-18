import { describe, expect, it } from "vitest";

import type { WeightOut } from "@/lib/api/client";

import { ACTIVE_WEIGHT_FLOOR, buildActiveWeights } from "./activeWeights";

function equity(ticker: string, weight: number): WeightOut {
  return {
    asset: { kind: "equity", ticker },
    weight,
    ticker,
    name: ticker,
    asset_class: null,
    strategy_label: null,
  };
}

describe("buildActiveWeights", () => {
  it("drops solver-noise weights and renormalizes active positions", () => {
    const result = buildActiveWeights([
      equity("AAA", 0.3),
      equity("BBB", 0.2),
      equity("ZERO", ACTIVE_WEIGHT_FLOOR),
    ]);

    expect(result.dropped).toBe(1);
    expect(result.isValid).toBe(true);
    expect(result.positions).toEqual([
      expect.objectContaining({ weight: 0.6 }),
      expect.objectContaining({ weight: 0.4 }),
    ]);
  });

  it("marks the request invalid when fewer than two active weights remain", () => {
    const result = buildActiveWeights([
      equity("AAA", 1),
      equity("ZERO", 0),
    ]);

    expect(result.isValid).toBe(false);
    expect(result.positions).toHaveLength(1);
  });
});
