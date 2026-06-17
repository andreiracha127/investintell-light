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

  it("prepends a top-level Cash node ordered by weight, no children", () => {
    // holdings 60, cash 40, total 100 -> equity 0.6 root precedes cash 0.4 root.
    const rows = buildAllocationTree([h({ marketValue: 60 })], 100, 40);
    const roots = rows.filter((r) => r.parentId === null);
    expect(roots.map((r) => r.label)).toEqual(["Equity", "Cash"]);
    const cash = rows.find((r) => r.id === "ac:__cash__");
    expect(cash?.weight).toBeCloseTo(0.4, 9);
    expect(cash?.instrumentId).toBeNull();
    // Cash has no children.
    expect(rows.some((r) => r.parentId === "ac:__cash__")).toBe(false);
  });

  it("funds keep instrumentId + their strategy; aggregates parent weights", () => {
    const rows = buildAllocationTree(
      [
        h({ ticker: "A", marketValue: 20, strategyLabel: "Growth", instrumentId: "a" }),
        h({ ticker: "B", marketValue: 30, strategyLabel: "Growth", instrumentId: "b" }),
      ],
      100,
      50,
    );
    const byId = new Map(rows.map((r) => [r.id, r]));
    expect(byId.get("ac:equity")?.weight).toBeCloseTo(0.5, 9);
    expect(byId.get("st:equity/Growth")?.weight).toBeCloseTo(0.5, 9);
    const leafA = rows.find((r) => r.label === "A");
    expect(leafA?.instrumentId).toBe("a");
    expect(leafA?.parentId).toBe("st:equity/Growth");
  });

  it("direct equities (no instrumentId) fall under 'Direct equity' with null leaf id", () => {
    const rows = buildAllocationTree(
      [h({ ticker: "AAPL", marketValue: 100, strategyLabel: null, instrumentId: null })],
      100,
      0,
    );
    const strat = rows.find((r) => r.id.startsWith("st:"));
    expect(strat?.label).toBe("Direct equity");
    const leaf = rows.find((r) => r.label === "AAPL");
    expect(leaf?.instrumentId).toBeNull();
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
