import { describe, expect, it } from "vitest";

import { weightsTreeGridOptions, weightLabelFormatter } from "./weightsTreeGridOptions";
import type { WeightTreeRow } from "@/lib/builder/weightsTree";

const ROWS: WeightTreeRow[] = [
  { id: "ac:equity", parentId: null, label: "Equity", weight: 0.5, instrumentId: null, name: null, strategy: null, isGroup: true },
  { id: "leaf:a", parentId: "ac:equity", label: "AAA", weight: 0.5, instrumentId: "uuid-a", name: "Alpha Fund", strategy: "Growth", isGroup: false },
];

/** Minimal GridCell stub: getCell(key) reads from a row record. */
function cell(value: unknown, row: Record<string, unknown>) {
  return {
    value,
    row: { getCell: (k: string) => ({ value: row[k] }) },
  } as never;
}

describe("weightsTreeGridOptions", () => {
  it("feeds every tree row as a column-oriented local data block, collapsed by default", () => {
    const opts = weightsTreeGridOptions(ROWS);
    const data = opts.data as {
      columns: Record<string, unknown[]>;
      idColumn?: string;
      treeView?: { treeColumn?: string; expandedRowIds?: unknown };
    };
    expect(data.columns.id).toHaveLength(2);
    // Root rows MUST carry parentId null (not "") so the parent-id adapter treats
    // them as roots rather than references to a non-existent row.
    expect(data.columns.parentId).toEqual([null, "ac:equity"]);
    expect(data.idColumn).toBe("id");
    expect(data.treeView?.treeColumn).toBe("label");
    // Collapsed by default — not pre-expanded.
    expect(data.treeView?.expandedRowIds).toEqual([]);
    // Strategy + isGroup must be fed so the formatters can branch.
    expect(data.columns.strategy).toEqual(["", "Growth"]);
    expect(data.columns.isGroup).toEqual([true, false]);
    const colIds = (opts.columns ?? []).map((c) => c.id);
    expect(colIds).toContain("label");
    expect(colIds).toContain("strategy");
    expect(colIds).toContain("weight");
  });
});

describe("weightLabelFormatter", () => {
  it("renders a leaf as a dossier-linked ticker over its name", () => {
    const leaf = weightLabelFormatter.call(
      cell("AAA", { isGroup: false, instrumentId: "uuid-a", name: "Alpha Fund" }),
    );
    expect(leaf).toContain('href="/funds/uuid-a"');
    expect(leaf).toContain("AAA");
    expect(leaf).toContain("Alpha Fund");
  });

  it("renders a direct equity leaf as a plain ticker (no link)", () => {
    const leaf = weightLabelFormatter.call(
      cell("AAPL", { isGroup: false, instrumentId: "", name: "Apple Inc." }),
    );
    expect(leaf).not.toContain("href");
    expect(leaf).toContain("AAPL");
  });

  it("renders a group row as a bold asset-class label with no link", () => {
    const group = weightLabelFormatter.call(
      cell("Equity", { isGroup: true, instrumentId: "", name: "" }),
    );
    expect(group).not.toContain("href");
    expect(group).toContain("ix-grid-group");
    expect(group).toContain("Equity");
  });
});
