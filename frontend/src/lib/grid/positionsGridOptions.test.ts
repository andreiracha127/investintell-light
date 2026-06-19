import { describe, expect, it, vi } from "vitest";

import type { PortfolioOverview } from "@/lib/api/client";
import {
  countMatchingPositions,
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
      ticker: "AAA", name: "Alpha Inc", instrument_id: null, last_close: 10, change: 0.5, change_pct: 0.05,
      acq_price: 8, quantity: 100, basis: "executed", commission: 1.5, trade_date: "2026-01-02",
      pnl: 200, pnl_pct: 0.25, market_value: 1000,
    },
    {
      ticker: "BBB", name: null, instrument_id: "fund-123", last_close: 20, change: -1, change_pct: -0.05,
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
  it("includes clickable shares/cost/date columns and a Trade action column", () => {
    const cols = positionsGridColumns();
    const shares = cols.find((c) => c.id === "shares");
    const cost = cols.find((c) => c.id === "cost");
    const date = cols.find((c) => c.id === "trade_date");
    const action = cols.find((c) => c.id === "__trade");
    expect(shares?.cells?.events?.click).toBeTypeOf("function");
    expect(cost?.cells?.events?.click).toBeTypeOf("function");
    expect(date?.cells?.events?.click).toBeTypeOf("function");
    expect(action?.cells?.events?.click).toBeTypeOf("function");
  });

  it("keeps P&L and Market value headers plain", () => {
    const cols = positionsGridColumns();
    expect(cols.find((c) => c.id === "pnl")?.header?.format).toBe("P&L");
    expect(cols.find((c) => c.id === "mktvalue")?.header?.format).toBe(
      "Market value",
    );
  });

  it("orders visible columns to match the mockup and gives P&L %/Company their own columns", () => {
    const cols = positionsGridColumns();
    const visible = cols.filter((c) => c.enabled !== false).map((c) => c.id);
    expect(visible).toEqual([
      "ticker",
      "name",
      "trade_date",
      "last",
      "cost",
      "shares",
      "mktvalue",
      "pnl",
      "pnl_pct",
      "__trade",
    ]);
  });

  it("ticker formatter links to the stock; name moved to its own Company column", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    const out = callFmt(fmt, mkCell("AAA", { name: "Alpha Inc", instrument_id: null }));
    expect(out).toContain('href="/stocks/AAA"');
    expect(out).toContain("AAA");
    // Company name is no longer a ticker sub-line.
    expect(out).not.toContain("Alpha Inc");
    expect(out).not.toContain("FUND");
  });

  it("ticker formatter shows a FUND badge for fund/ETF holdings (instrument_id present)", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    const out = callFmt(fmt, mkCell("BBB", { name: null, instrument_id: "fund-123" }));
    expect(out).toContain("FUND");
  });

  it("Company column formatter renders the name, em-dash when null", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "name")!.cells!.formatter;
    expect(callFmt(fmt, mkCell("Alpha Inc"))).toContain("Alpha Inc");
    expect(callFmt(fmt, mkCell(null))).toBe("—");
  });

  it("Buy date formatter renders the position trade date", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "trade_date")!.cells!.formatter;
    expect(callFmt(fmt, mkCell("2026-01-02"))).toContain("02/01/26");
    expect(callFmt(fmt, mkCell(null))).toContain("Set date");
  });

  it("Buy date column opens the calendar editor callback", () => {
    const onEditTradeDate = vi.fn();
    const cols = positionsGridColumns({
      onEditShares: vi.fn(),
      onEditCost: vi.fn(),
      onEditTradeDate,
      onTrade: vi.fn(),
    });
    const click = cols.find((c) => c.id === "trade_date")!.cells!.events!
      .click as unknown as (this: CellLike) => void;

    click.call(mkCell("2026-01-02", { ticker: "AAA" }, "trade_date"));

    expect(onEditTradeDate).toHaveBeenCalledWith("AAA", "2026-01-02");
  });

  it("P&L % column formatter renders signed percent with tone, em-dash when null", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "pnl_pct")!.cells!.formatter;
    const gain = callFmt(fmt, mkCell(0.25));
    expect(gain).toContain("+25.00%");
    expect(gain).toContain("text-gain");
    expect(callFmt(fmt, mkCell(null))).toBe("—");
  });

  it("enables column sorting by default and opts the action column out", () => {
    const opts = positionsToGridOptions(OVERVIEW, {
      onEditShares: vi.fn(), onEditCost: vi.fn(), onEditTradeDate: vi.fn(), onTrade: vi.fn(),
    });
    expect(opts.columnDefaults?.sorting?.enabled).toBe(true);
    const action = (opts.columns ?? []).find((c) => c.id === "__trade");
    expect(action?.sorting?.enabled).toBe(false);
  });

  it("cost formatter shows price + commission without REF/EXEC badges", () => {
    const cols = positionsGridColumns();
    const fmt = cols.find((c) => c.id === "cost")!.cells!.formatter;
    const exec = callFmt(fmt, mkCell(8, { basis: "executed", commission: 1.5 }));
    expect(exec).not.toContain("EXEC");
    expect(exec).not.toContain("REF");
    expect(exec).toContain("incl. comm.");
    const ref = callFmt(fmt, mkCell(null, { basis: "reference", commission: null }));
    expect(ref).not.toContain("REF");
    expect(ref).toContain("—");
  });

  it("Avg cost and Qty columns open their field editor callbacks", () => {
    const onEditCost = vi.fn();
    const onEditShares = vi.fn();
    const cols = positionsGridColumns({
      onEditShares,
      onEditCost,
      onEditTradeDate: vi.fn(),
      onTrade: vi.fn(),
    });

    const costClick = cols.find((c) => c.id === "cost")!.cells!.events!
      .click as unknown as (this: CellLike) => void;
    const sharesClick = cols.find((c) => c.id === "shares")!.cells!.events!
      .click as unknown as (this: CellLike) => void;

    costClick.call(mkCell(8, { ticker: "AAA" }, "cost"));
    sharesClick.call(mkCell(100, { ticker: "AAA" }, "shares"));

    expect(onEditCost).toHaveBeenCalledWith("AAA", 8);
    expect(onEditShares).toHaveBeenCalledWith("AAA", 100);
  });
});

describe("positionsGridData", () => {
  it("pivots positions incl. hidden columns, null-safe", () => {
    const data = positionsGridData(OVERVIEW.positions);
    expect(data.columns!.ticker).toEqual(["AAA", "BBB"]);
    expect(data.columns!.shares).toEqual([100, 8.5]);
    expect(data.columns!.cost).toEqual([8, null]);
    expect(data.columns!.basis).toEqual(["executed", "reference"]);
    expect(data.columns!.trade_date).toEqual(["2026-01-02", null]);
    expect(data.columns!.name).toEqual(["Alpha Inc", null]);
    expect(data.columns!.instrument_id).toEqual([null, "fund-123"]);
    expect(data.columns!.change).toEqual([0.5, -1]);
  });

  it("filters rows by search across symbol and name", () => {
    const bySym = positionsGridData(OVERVIEW.positions, { search: "bbb" });
    expect(bySym.columns!.ticker).toEqual(["BBB"]);
    const byName = positionsGridData(OVERVIEW.positions, { search: "alpha" });
    expect(byName.columns!.ticker).toEqual(["AAA"]);
    const none = positionsGridData(OVERVIEW.positions, { search: "zzz" });
    expect(none.columns!.ticker).toEqual([]);
  });

  it("caps rows to the load-more limit", () => {
    const data = positionsGridData(OVERVIEW.positions, { limit: 1 });
    expect(data.columns!.ticker).toEqual(["AAA"]);
  });
});

describe("countMatchingPositions", () => {
  it("counts all without a search and the matching subset with one", () => {
    expect(countMatchingPositions(OVERVIEW.positions)).toBe(2);
    expect(countMatchingPositions(OVERVIEW.positions, "a")).toBe(1); // only AAA/"Alpha"
    expect(countMatchingPositions(OVERVIEW.positions, "bbb")).toBe(1);
  });
});

describe("positionsToGridOptions", () => {
  it("sets theme and keeps row-detail clicks off field-action columns", () => {
    const onEditShares = vi.fn();
    const onEditCost = vi.fn();
    const onTrade = vi.fn();
    const onOpenDetail = vi.fn();
    const opts = positionsToGridOptions(OVERVIEW, {
      onEditShares,
      onEditCost,
      onEditTradeDate: vi.fn(),
      onTrade,
      onOpenDetail,
    });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    const rowClick = opts.columnDefaults?.cells?.events?.click as unknown as (this: CellLike) => void;
    rowClick.call(mkCell("Alpha Inc", { ticker: "AAA" }, "name"));
    expect(onOpenDetail).toHaveBeenCalledWith("AAA");
    rowClick.call(mkCell(100, { ticker: "AAA" }, "shares"));
    expect(onOpenDetail).toHaveBeenCalledTimes(1);
  });
});
