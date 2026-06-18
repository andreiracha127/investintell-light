import { describe, expect, it } from "vitest";

import {
  buildAmountAdd,
  resolveSpot,
  weightedAvgCost,
  type ExistingHolding,
} from "@/lib/portfolio/addPosition";

const held: ExistingHolding = { quantity: 10, acqPrice: 90, lastClose: 105 };

describe("resolveSpot", () => {
  it("prefers an explicit positive price", () => {
    expect(resolveSpot(120, held)).toBe(120);
  });
  it("falls back to the holding's last close", () => {
    expect(resolveSpot(null, held)).toBe(105);
    expect(resolveSpot(0, held)).toBe(105); // non-positive explicit price ignored
  });
  it("is null with neither an explicit price nor a last close", () => {
    expect(resolveSpot(null, null)).toBeNull();
    expect(resolveSpot(null, { quantity: 1, acqPrice: 1, lastClose: null })).toBeNull();
  });
});

describe("weightedAvgCost", () => {
  it("blends old cost and new lot by quantity", () => {
    // (10·90 + 10·100) / 20 = 95
    expect(weightedAvgCost(held, 10, 100)).toBe(95);
  });
  it("returns null when the prior cost is unknown", () => {
    expect(weightedAvgCost({ quantity: 10, acqPrice: null, lastClose: 100 }, 5, 100)).toBeNull();
  });
});

describe("buildAmountAdd", () => {
  it("opens a new position when there is no holding", () => {
    expect(buildAmountAdd(1000, 100, null)).toEqual({
      quantity: 10,
      acqPrice: 100,
      addedQuantity: 10,
    });
  });

  it("accumulates onto an existing holding and blends the cost", () => {
    // adds 1000/100 = 10 shares onto 10 held → 20; cost (10·90+10·100)/20 = 95
    expect(buildAmountAdd(1000, 100, held)).toEqual({
      quantity: 20,
      acqPrice: 95,
      addedQuantity: 10,
    });
  });

  it("accumulates quantity but leaves cost null when prior cost is unknown", () => {
    const result = buildAmountAdd(500, 100, {
      quantity: 4,
      acqPrice: null,
      lastClose: 100,
    });
    expect(result.quantity).toBe(9); // 4 + 500/100
    expect(result.acqPrice).toBeNull();
    expect(result.addedQuantity).toBe(5);
  });
});
