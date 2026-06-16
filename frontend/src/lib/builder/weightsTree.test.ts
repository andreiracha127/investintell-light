import { describe, expect, it } from "vitest";

import { buildWeightsTree, type WeightInput } from "./weightsTree";

function w(over: Partial<WeightInput> = {}): WeightInput {
  return {
    kind: "fund",
    instrumentId: "id-1",
    ticker: "AAA",
    name: "Fund A",
    weight: 0.1,
    assetClass: "equity",
    strategyLabel: "Growth",
    ...over,
  };
}

describe("buildWeightsTree", () => {
  it("drops zero-weight positions", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.6 }),
      w({ instrumentId: "b", ticker: "B", weight: 0 }),
    ]);
    const leaves = rows.filter((r) => r.instrumentId !== null);
    expect(leaves.map((l) => l.label)).toEqual(["A"]);
  });

  it("builds 3 levels and aggregates parent weights", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.2, strategyLabel: "Growth" }),
      w({ instrumentId: "b", ticker: "B", weight: 0.3, strategyLabel: "Growth" }),
      w({ instrumentId: "c", ticker: "C", weight: 0.5, assetClass: "fixed_income", strategyLabel: "Core" }),
    ]);
    const byId = new Map(rows.map((r) => [r.id, r]));
    // Asset-class parents carry the aggregated weight.
    expect(byId.get("ac:equity")?.weight).toBeCloseTo(0.5, 9);
    expect(byId.get("ac:fixed_income")?.weight).toBeCloseTo(0.5, 9);
    // Strategy parent aggregates its funds.
    expect(byId.get("st:equity/Growth")?.weight).toBeCloseTo(0.5, 9);
    // Leaf chain: fund -> strategy -> asset class.
    const leafA = rows.find((r) => r.label === "A");
    expect(leafA?.parentId).toBe("st:equity/Growth");
    expect(byId.get("st:equity/Growth")?.parentId).toBe("ac:equity");
    expect(byId.get("ac:equity")?.parentId).toBeNull();
    // Parents carry no instrumentId; leaves do.
    expect(byId.get("ac:equity")?.instrumentId).toBeNull();
    expect(leafA?.instrumentId).toBe("a");
  });

  it("orders asset classes and funds by descending weight", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.1, assetClass: "equity", strategyLabel: "G" }),
      w({ instrumentId: "c", ticker: "C", weight: 0.9, assetClass: "fixed_income", strategyLabel: "Core" }),
    ]);
    // Fixed income (0.9) precedes equity (0.1) in the flat pre-order array.
    const acOrder = rows.filter((r) => r.id.startsWith("ac:")).map((r) => r.id);
    expect(acOrder).toEqual(["ac:fixed_income", "ac:equity"]);
  });

  it("groups funds with no asset_class under 'Other'", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.5, assetClass: null, strategyLabel: null }),
    ]);
    const ac = rows.find((r) => r.id.startsWith("ac:"));
    expect(ac?.label).toBe("Other");
  });
});
