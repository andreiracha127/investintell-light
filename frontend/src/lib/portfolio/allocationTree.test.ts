import { describe, expect, it } from "vitest";

import { buildAllocationTree, type AllocationInput } from "./allocationTree";

function h(over: Partial<AllocationInput> = {}): AllocationInput {
  return {
    ticker: "VTI",
    name: "Vanguard Total Market",
    marketValue: 100,
    assetClass: "equity",
    strategyLabel: "Large-Cap Blend",
    instrumentId: "iid-1",
    ...over,
  };
}

describe("buildAllocationTree", () => {
  it("returns [] when totalValue is 0", () => {
    expect(buildAllocationTree([h()], 0, 0)).toEqual([]);
  });

  it("adds a top-level Cash leaf ordered by weight, with no children", () => {
    // holdings 60, cash 40, total 100 -> equity 0.6 root precedes cash 0.4 root.
    const rows = buildAllocationTree([h({ marketValue: 60 })], 100, 40);
    const roots = rows.filter((r) => r.parentId === null);
    expect(roots.map((r) => r.label)).toEqual(["Equity", "Cash"]);
    const cash = rows.find((r) => r.id === "ac:__cash__");
    expect(cash?.weight).toBeCloseTo(0.4, 9);
    expect(cash?.instrumentId).toBeNull();
    // Cash is a leaf (no expander), not a group, and has no children.
    expect(cash?.isGroup).toBe(false);
    expect(rows.some((r) => r.parentId === "ac:__cash__")).toBe(false);
  });

  it("builds 2 levels (asset class -> holding); leaves keep instrumentId + strategy", () => {
    const rows = buildAllocationTree(
      [
        h({ ticker: "A", marketValue: 20, strategyLabel: "Growth", instrumentId: "a" }),
        h({ ticker: "B", marketValue: 30, strategyLabel: "Value", instrumentId: "b" }),
      ],
      100,
      50,
    );
    const byId = new Map(rows.map((r) => [r.id, r]));
    expect(rows.some((r) => r.id.startsWith("st:"))).toBe(false);
    expect(byId.get("ac:equity")?.weight).toBeCloseTo(0.5, 9);
    expect(byId.get("ac:equity")?.isGroup).toBe(true);
    const leafA = rows.find((r) => r.label === "A");
    expect(leafA?.instrumentId).toBe("a");
    expect(leafA?.parentId).toBe("ac:equity");
    expect(leafA?.strategy).toBe("Growth");
  });

  it("direct equities (no instrumentId) keep a null leaf id and blank strategy", () => {
    const rows = buildAllocationTree(
      [h({ ticker: "AAPL", marketValue: 100, strategyLabel: null, instrumentId: null })],
      100,
      0,
    );
    const leaf = rows.find((r) => r.label === "AAPL");
    expect(leaf?.instrumentId).toBeNull();
    expect(leaf?.parentId).toBe("ac:equity");
    expect(leaf?.strategy).toBeNull();
  });

  it("drops sub-floor weights", () => {
    const rows = buildAllocationTree(
      [
        h({ ticker: "A", marketValue: 100, instrumentId: "a" }),
        h({ ticker: "Z", marketValue: 0, instrumentId: "z" }),
      ],
      100,
      0,
    );
    expect(rows.some((r) => r.label === "Z")).toBe(false);
  });
});
