import { describe, expect, it, vi } from "vitest";

import type { PortfolioOverview } from "@/lib/api/client";
import {
  formatShares,
  positionsGridColumns,
  positionsGridData,
  positionsToGridOptions,
} from "./positionsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

const OVERVIEW = {
  name: "Main",
  positions: [
    {
      ticker: "AAA", name: "Alpha Inc", last_close: 10, change: 0.5, change_pct: 0.05,
      acq_price: 8, quantity: 100, basis: "executed", commission: 1.5, trade_date: "2026-01-02",
      pnl: 200, pnl_pct: 0.25, market_value: 1000,
    },
    {
      ticker: "BBB", name: null, last_close: 20, change: -1, change_pct: -0.05,
      acq_price: null, quantity: 8.5, basis: "reference", commission: null, trade_date: null,
      pnl: null, pnl_pct: null, market_value: 170,
    },
  ],
  aggregates: { total_value: 1170, total_pnl: 200, total_pnl_pct: 0.2, total_market_value: 1170, cash: 0, as_of: "2026-06-12" },
} as unknown as PortfolioOverview;

type CellLike = {
  value: unknown;
  column?: { id: string };
  row: { getCell: (id: string) => { value: unknown } | undefined };
};
const mkCell = (value: unknown, rowValues: Record<string, unknown> = {}, columnId?: string): CellLike => ({
  value,
  column: columnId ? { id: columnId } : undefined,
  row: { getCell: (id) => (id in rowValues ? { value: rowValues[id] } : undefined) },
});
const callFmt = (fn: unknown, cell: CellLike) => (fn as (this: CellLike) => string).call(cell);

describe("formatShares", () => {
  it("shows integers without decimals and fractions with two", () => {
    expect(formatShares(8)).toBe("8");
    expect(formatShares(8.5)).toBe("8.50");
  });
});

describe("positionsGridColumns", () => {
  it("includes editable shares & cost columns and a clickable action column", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const shares = cols.find((c) => c.id === "shares");
    const cost = cols.find((c) => c.id === "cost");
    const action = cols.find((c) => c.id === "__remove");
    expect(shares?.cells?.editMode?.enabled).toBe(true);
    expect(cost?.cells?.editMode?.enabled).toBe(true);
    expect(action?.cells?.events?.click).toBeTypeOf("function");
  });

  it("bakes aggregates into the P&L and Mkt Value headers", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    expect(cols.find((c) => c.id === "pnl")?.header?.format).toContain("+$200");
    expect(cols.find((c) => c.id === "mktvalue")?.header?.format).toContain("$1,170");
  });

  it("ticker formatter links to the stock and shows the name sub-line", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    const out = callFmt(fmt, mkCell("AAA", { name: "Alpha Inc" }));
    expect(out).toContain('href="/stocks/AAA"');
    expect(out).toContain("AAA");
    expect(out).toContain("Alpha Inc");
  });

  it("cost formatter shows EXEC badge + price + commission; REF when not executed", () => {
    const cols = positionsGridColumns(OVERVIEW.aggregates);
    const fmt = cols.find((c) => c.id === "cost")!.cells!.formatter;
    const exec = callFmt(fmt, mkCell(8, { basis: "executed", commission: 1.5 }));
    expect(exec).toContain("EXEC");
    expect(exec).toContain("ix-grid-basis-exec");
    const ref = callFmt(fmt, mkCell(null, { basis: "reference", commission: null }));
    expect(ref).toContain("REF");
    expect(ref).toContain("—");
  });
});

describe("positionsGridData", () => {
  it("pivots positions incl. hidden columns, null-safe", () => {
    const data = positionsGridData(OVERVIEW.positions);
    expect(data.columns!.ticker).toEqual(["AAA", "BBB"]);
    expect(data.columns!.shares).toEqual([100, 8.5]);
    expect(data.columns!.cost).toEqual([8, null]);
    expect(data.columns!.basis).toEqual(["executed", "reference"]);
    expect(data.columns!.name).toEqual(["Alpha Inc", null]);
  });
});

describe("positionsToGridOptions", () => {
  it("sets theme and dispatches afterEdit to the right callback", () => {
    const onEditShares = vi.fn();
    const onEditCost = vi.fn();
    const onRemove = vi.fn();
    const opts = positionsToGridOptions(OVERVIEW, { onEditShares, onEditCost, onRemove });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    const afterEdit = opts.columnDefaults?.cells?.events?.afterEdit as unknown as (this: CellLike) => void;
    afterEdit.call(mkCell(120, { ticker: "AAA" }, "shares"));
    expect(onEditShares).toHaveBeenCalledWith("AAA", 120);
    afterEdit.call(mkCell(9, { ticker: "AAA" }, "cost"));
    expect(onEditCost).toHaveBeenCalledWith("AAA", 9);
  });
});
