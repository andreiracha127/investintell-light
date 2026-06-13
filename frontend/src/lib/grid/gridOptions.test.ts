import { describe, expect, it, vi } from "vitest";

import type { ScreenResults } from "@/lib/api/client";
import {
  GRAPHITE_THEME,
  gridColumnsFromResults,
  gridDataFromResults,
  screenResultsToGridOptions,
} from "./gridOptions";

// Minimal ScreenResults stand-in (only fields the adapter reads).
const RESULTS = {
  columns: [
    { code: "ticker", name: "Ticker", data_type: "string" },
    { code: "sharpe_1y", name: "Sharpe 1Y", data_type: "number" },
  ],
  rows: [
    { ticker: "AAA", sharpe_1y: 1.23 },
    { ticker: "BBB", sharpe_1y: null },
  ],
  total: 2,
} as unknown as ScreenResults;

// `afterSort` reads only `this.id` and `this.options.sorting?.order`.
type ColumnLike = { id: string; options: { sorting?: { order?: "asc" | "desc" | null } } };
const fireAfterSort = (
  fn: ((this: never) => void) | undefined,
  ctx: ColumnLike,
) => (fn as unknown as (this: ColumnLike) => void).call(ctx);

describe("gridColumnsFromResults", () => {
  it("maps code→id, name→header, and aligns numeric vs text columns", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { dir: "asc" });
    expect(cols).toHaveLength(2);
    expect(cols[0]).toMatchObject({ id: "ticker", className: "ix-grid-cell-text" });
    expect(cols[1]).toMatchObject({ id: "sharpe_1y", className: "ix-grid-cell-num" });
  });

  it("marks only the active sort column with its order", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { sort: "sharpe_1y", dir: "desc" });
    expect(cols[1].sorting).toEqual({ order: "desc" });
    expect(cols[0].sorting).toBeUndefined();
  });

  it("formats numeric cells and renders an em-dash for null", () => {
    const cols = gridColumnsFromResults(RESULTS.columns, { dir: "asc" });
    const fmt = cols[1].cells?.formatter;
    expect((fmt as unknown as (this: { value: unknown }) => string).call({ value: null })).toBe("—");
    expect((fmt as unknown as (this: { value: unknown }) => string).call({ value: 1.23 })).toBe("1.23");
  });
});

describe("gridDataFromResults", () => {
  it("pivots rows into column-oriented arrays, null-safe", () => {
    const data = gridDataFromResults(RESULTS.columns, RESULTS.rows);
    expect(data).toEqual({
      providerType: "local",
      columns: { ticker: ["AAA", "BBB"], sharpe_1y: [1.23, null] },
    });
  });
});

describe("screenResultsToGridOptions", () => {
  it("applies the Graphite theme and enables virtualization", () => {
    const opts = screenResultsToGridOptions(RESULTS, { dir: "asc" }, { onSortChange: () => {} });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(opts.rendering?.rows?.virtualization).toBe(true);
  });

  it("afterSort calls onSortChange with the column id and the new order", () => {
    const onSortChange = vi.fn();
    const opts = screenResultsToGridOptions(RESULTS, { dir: "asc" }, { onSortChange });
    fireAfterSort(opts.columnDefaults?.events?.afterSort, {
      id: "sharpe_1y",
      options: { sorting: { order: "desc" } },
    });
    expect(onSortChange).toHaveBeenCalledWith("sharpe_1y", "desc");
  });

  it("afterSort is a no-op when the order already matches state (no refetch loop)", () => {
    const onSortChange = vi.fn();
    const opts = screenResultsToGridOptions(
      RESULTS,
      { sort: "sharpe_1y", dir: "desc" },
      { onSortChange },
    );
    fireAfterSort(opts.columnDefaults?.events?.afterSort, {
      id: "sharpe_1y",
      options: { sorting: { order: "desc" } },
    });
    expect(onSortChange).not.toHaveBeenCalled();
  });
});
