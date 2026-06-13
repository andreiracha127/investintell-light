import { describe, expect, it, vi } from "vitest";

import type { FundsList } from "@/lib/api/client";
import { universePreviewToGridOptions } from "./universeGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

const ITEMS = [
  {
    instrument_id: "uuid-1",
    ticker: "AAA",
    name: "Alpha <Equity> Fund",
    aum_usd: 1_000_000,
    expense_ratio: 0.005,
    sharpe_1y: 1.1,
  },
  {
    instrument_id: "uuid-2",
    ticker: null,
    name: "Beta Fund",
    aum_usd: null,
    expense_ratio: null,
    sharpe_1y: null,
  },
] as unknown as FundsList["items"];

// Mock Cell `this`: value + column.id + row.getCell(id).value
type CellLike = {
  value: unknown;
  column?: { id: string };
  row: { getCell: (id: string) => { value: unknown } | undefined };
};
const mkCell = (
  value: unknown,
  rowValues: Record<string, unknown> = {},
  columnId?: string,
): CellLike => ({
  value,
  column: columnId ? { id: columnId } : undefined,
  row: { getCell: (id) => (id in rowValues ? { value: rowValues[id] } : undefined) },
});
const callFmt = (fn: unknown, cell: CellLike): string =>
  (fn as (this: CellLike) => string).call(cell);

describe("universePreviewToGridOptions", () => {
  it("applies the graphite theme and disables sorting", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(opts.columnDefaults?.sorting?.enabled).toBe(false);
  });

  it("first column is an `__include` checkbox renderer headed 'Use'", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    const cols = opts.columns!;
    const include = cols.find((c) => c.id === "__include");
    expect(cols[0].id).toBe("__include");
    expect(include?.header?.format).toBe("Use");
    expect(include?.cells?.renderer?.type).toBe("checkbox");
  });

  it("carries a hidden instrument_id column for the formatters", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    const hidden = opts.columns!.find((c) => c.id === "instrument_id");
    expect(hidden?.enabled).toBe(false);
  });

  it("data __include reflects the selected id-set per row", () => {
    const opts = universePreviewToGridOptions(
      ITEMS,
      new Set(["uuid-1"]),
      { onToggle: vi.fn() },
    );
    const data = opts.data as { columns: Record<string, unknown[]> };
    expect(data.columns.__include).toEqual([true, false]);
    expect(data.columns.instrument_id).toEqual(["uuid-1", "uuid-2"]);
    expect(data.columns.ticker).toEqual(["AAA", null]);
  });

  it("afterEdit calls onToggle(id, checked) reading instrument_id from the row", () => {
    const onToggle = vi.fn();
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle });
    const include = opts.columns!.find((c) => c.id === "__include")!;
    const afterEdit = include.cells?.events?.afterEdit as unknown as (
      this: CellLike,
    ) => void;
    afterEdit.call(mkCell(true, { instrument_id: "uuid-1" }, "__include"));
    expect(onToggle).toHaveBeenCalledWith("uuid-1", true);
    afterEdit.call(mkCell(false, { instrument_id: "uuid-2" }, "__include"));
    expect(onToggle).toHaveBeenCalledWith("uuid-2", false);
  });

  it("ticker formatter builds an escaped link to the fund profile", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    const fmt = opts.columns!.find((c) => c.id === "ticker")!.cells!.formatter;
    expect(callFmt(fmt, mkCell("AAA", { instrument_id: "uuid-1" }))).toBe(
      '<a class="ix-grid-link" href="/funds/uuid-1">AAA</a>',
    );
    // no instrument_id -> plain label
    expect(callFmt(fmt, mkCell("AAA", {}))).toBe("AAA");
  });

  it("name formatter escapes HTML", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    const fmt = opts.columns!.find((c) => c.id === "name")!.cells!.formatter;
    expect(callFmt(fmt, mkCell("Alpha <Equity> Fund", { instrument_id: "uuid-1" }))).toContain(
      "Alpha &lt;Equity&gt; Fund",
    );
  });

  it("numeric formatters render compact AUM, percent expense, number sharpe; dashes for null", () => {
    const opts = universePreviewToGridOptions(ITEMS, new Set(), { onToggle: vi.fn() });
    const get = (id: string) => opts.columns!.find((c) => c.id === id)!.cells!.formatter;
    expect(callFmt(get("aum_usd"), mkCell(1_000_000))).toBe("$1M");
    expect(callFmt(get("aum_usd"), mkCell(null))).toBe("—");
    expect(callFmt(get("expense_ratio"), mkCell(0.005))).toBe("0.50%");
    expect(callFmt(get("sharpe_1y"), mkCell(1.1))).toBe("1.10");
    expect(callFmt(get("sharpe_1y"), mkCell(null))).toBe("—");
  });
});
