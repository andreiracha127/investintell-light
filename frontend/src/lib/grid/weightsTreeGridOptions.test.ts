import { describe, expect, it } from "vitest";

import { weightsTreeGridOptions, weightLabelFormatter } from "./weightsTreeGridOptions";
import type { WeightTreeRow } from "@/lib/builder/weightsTree";

const ROWS: WeightTreeRow[] = [
  { id: "ac:equity", parentId: null, label: "Equity", weight: 0.5, instrumentId: null, name: null },
  { id: "st:equity/Growth", parentId: "ac:equity", label: "Growth", weight: 0.5, instrumentId: null, name: null },
  { id: "leaf:a", parentId: "st:equity/Growth", label: "AAA", weight: 0.5, instrumentId: "uuid-a", name: "Alpha Fund" },
];

describe("weightsTreeGridOptions", () => {
  it("feeds every tree row as a column-oriented local data block with a label tree column", () => {
    const opts = weightsTreeGridOptions(ROWS);
    const data = opts.data as {
      columns: Record<string, unknown[]>;
      idColumn?: string;
      treeView?: { treeColumn?: string };
    };
    expect(data.columns.id).toHaveLength(3);
    expect(data.columns.parentId).toEqual(["", "ac:equity", "st:equity/Growth"]);
    // Tree input needs the row-id column declared, else the grid renders flat.
    expect(data.idColumn).toBe("id");
    expect(data.treeView?.treeColumn).toBe("label");
    const colIds = (opts.columns ?? []).map((c) => c.id);
    expect(colIds).toContain("label");
    expect(colIds).toContain("name");
    expect(colIds).toContain("weight");
  });
});

describe("weightLabelFormatter", () => {
  it("links a leaf label to the fund dossier and leaves parents plain", () => {
    const leaf = weightLabelFormatter.call({
      value: "AAA",
      row: { getCell: (k: string) => ({ value: k === "instrumentId" ? "uuid-a" : "" }) },
    } as never);
    expect(leaf).toContain('href="/funds/uuid-a"');
    const parent = weightLabelFormatter.call({
      value: "Equity",
      row: { getCell: () => ({ value: "" }) },
    } as never);
    expect(parent).not.toContain("href");
  });
});
