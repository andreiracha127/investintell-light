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
    const leaves = rows.filter((r) => !r.isGroup);
    expect(leaves.map((l) => l.label)).toEqual(["A"]);
  });

  it("builds 2 levels (asset class -> leaf) and aggregates the group weight", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.2, strategyLabel: "Growth" }),
      w({ instrumentId: "b", ticker: "B", weight: 0.3, strategyLabel: "Value" }),
      w({ instrumentId: "c", ticker: "C", weight: 0.5, assetClass: "fixed_income", strategyLabel: "Core" }),
    ]);
    const byId = new Map(rows.map((r) => [r.id, r]));
    // No strategy grouping level remains.
    expect(rows.some((r) => r.id.startsWith("st:"))).toBe(false);
    // Asset-class group rows carry the aggregated weight and are flagged isGroup.
    expect(byId.get("ac:equity")?.weight).toBeCloseTo(0.5, 9);
    expect(byId.get("ac:equity")?.isGroup).toBe(true);
    expect(byId.get("ac:fixed_income")?.weight).toBeCloseTo(0.5, 9);
    // Leaves parent directly onto the asset class and carry strategy + identity.
    const leafA = rows.find((r) => r.label === "A");
    expect(leafA?.parentId).toBe("ac:equity");
    expect(leafA?.isGroup).toBe(false);
    expect(leafA?.instrumentId).toBe("a");
    expect(leafA?.name).toBe("Fund A");
    expect(leafA?.strategy).toBe("Growth");
    // Group rows carry no identity, name or strategy.
    expect(byId.get("ac:equity")?.instrumentId).toBeNull();
    expect(byId.get("ac:equity")?.name).toBeNull();
    expect(byId.get("ac:equity")?.strategy).toBeNull();
  });

  it("direct equities (kind=equity) drop the dossier link but keep their strategy", () => {
    const rows = buildWeightsTree([
      w({ kind: "equity", instrumentId: null, ticker: "AAPL", weight: 0.5, strategyLabel: null }),
    ]);
    const leaf = rows.find((r) => r.label === "AAPL");
    expect(leaf?.instrumentId).toBeNull();
    expect(leaf?.strategy).toBeNull();
  });

  it("orders asset classes and leaves by descending weight", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.1, assetClass: "equity", strategyLabel: "G" }),
      w({ instrumentId: "c", ticker: "C", weight: 0.9, assetClass: "fixed_income", strategyLabel: "Core" }),
    ]);
    const acOrder = rows.filter((r) => r.isGroup).map((r) => r.id);
    expect(acOrder).toEqual(["ac:fixed_income", "ac:equity"]);
  });

  it("groups funds with no asset_class under 'Other'", () => {
    const rows = buildWeightsTree([
      w({ instrumentId: "a", ticker: "A", weight: 0.5, assetClass: null, strategyLabel: null }),
    ]);
    const ac = rows.find((r) => r.isGroup);
    expect(ac?.label).toBe("Other");
  });
});
