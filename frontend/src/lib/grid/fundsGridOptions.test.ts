import { describe, expect, it, vi } from "vitest";

import type { FundsList } from "@/lib/api/client";
import {
  escapeHtml,
  fundsGridColumns,
  fundsGridData,
  fundsListToGridOptions,
} from "./fundsGridOptions";
import { GRAPHITE_THEME } from "./gridOptions";

const ITEMS = [
  {
    instrument_id: "uuid-1",
    ticker: "AAA",
    name: "Alpha <Equity> Fund",
    fund_type: "etf",
    strategy_label: "Large Cap",
    asset_class: "equity",
    aum_usd: 1_000_000,
    expense_ratio: 0.005,
    return_1y: 0.123,
    volatility_1y: 0.2,
    sharpe_1y: 1.1,
    peer_sharpe_pctl: 87,
    elite_flag: true,
  },
  {
    instrument_id: "uuid-2",
    ticker: null,
    name: "Beta Fund",
    fund_type: "mutual_fund",
    strategy_label: null,
    asset_class: null,
    aum_usd: null,
    expense_ratio: null,
    return_1y: -0.04,
    volatility_1y: null,
    sharpe_1y: null,
    peer_sharpe_pctl: null,
    elite_flag: false,
  },
] as unknown as FundsList["items"];

const LIST = { items: ITEMS, total: 2 } as unknown as FundsList;

// Mock Cell `this`: value + row.getCell(id).value
type CellLike = { value: unknown; row: { getCell: (id: string) => { value: unknown } | undefined } };
const fmtCall = (
  fn: unknown,
  value: unknown,
  rowValues: Record<string, unknown> = {},
): string =>
  (fn as (this: CellLike) => string).call({
    value,
    row: { getCell: (id: string) => (id in rowValues ? { value: rowValues[id] } : undefined) },
  });

describe("escapeHtml", () => {
  it("escapes &, <, >, and quotes", () => {
    expect(escapeHtml('a & b <c> "d"')).toBe("a &amp; b &lt;c&gt; &quot;d&quot;");
  });
});

describe("fundsGridColumns", () => {
  it("returns the 12 display columns plus a hidden instrument_id column", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    expect(cols).toHaveLength(13);
    const ids = cols.map((c) => c.id);
    expect(ids).toContain("instrument_id");
    const hidden = cols.find((c) => c.id === "instrument_id");
    expect(hidden?.enabled).toBe(false);
  });

  it("aligns numeric vs text and sets per-type orderSequence", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const ticker = cols.find((c) => c.id === "ticker");
    const aum = cols.find((c) => c.id === "aum_usd");
    expect(ticker?.className).toBe("ix-grid-cell-text");
    expect(aum?.className).toBe("ix-grid-cell-num");
    expect(ticker?.sorting?.orderSequence).toEqual(["asc", "desc", null]);
    expect(aum?.sorting?.orderSequence).toEqual(["desc", "asc", null]);
  });

  it("marks only the active sort column with its order", () => {
    const cols = fundsGridColumns({ sort: "aum_usd", dir: "desc" });
    expect(cols.find((c) => c.id === "aum_usd")?.sorting?.order).toBe("desc");
    expect(cols.find((c) => c.id === "ticker")?.sorting?.order).toBeUndefined();
  });

  it("ticker formatter builds an escaped link to the fund profile using instrument_id from the row", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const fmt = cols.find((c) => c.id === "ticker")!.cells!.formatter;
    expect(fmtCall(fmt, "AAA", { instrument_id: "uuid-1" })).toBe(
      '<a class="ix-grid-link" href="/funds/uuid-1">AAA</a>',
    );
    // no instrument_id -> plain label
    expect(fmtCall(fmt, "AAA", {})).toBe("AAA");
  });

  it("name formatter escapes HTML and wraps in a truncating link", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const fmt = cols.find((c) => c.id === "name")!.cells!.formatter;
    expect(fmtCall(fmt, "Alpha <Equity> Fund", { instrument_id: "uuid-1" })).toBe(
      '<a class="ix-grid-link-plain" href="/funds/uuid-1"><span class="ix-grid-trunc">Alpha &lt;Equity&gt; Fund</span></a>',
    );
  });

  it("type/asset/aum/return/sharpe/peer/elite formatters render expected output", () => {
    const cols = fundsGridColumns({ dir: "desc" });
    const get = (id: string) => cols.find((c) => c.id === id)!.cells!.formatter;
    expect(fmtCall(get("fund_type"), "etf")).toBe('<span class="ix-grid-tag">ETF</span>');
    expect(fmtCall(get("asset_class"), "equity")).toBe("Equity");
    expect(fmtCall(get("asset_class"), null)).toBe("—");
    expect(fmtCall(get("aum_usd"), 1_000_000)).toBe("$1M");
    expect(fmtCall(get("aum_usd"), null)).toBe("—");
    expect(fmtCall(get("return_1y"), 0.123)).toBe('<span class="text-gain">+12.30%</span>');
    expect(fmtCall(get("return_1y"), -0.04)).toBe('<span class="text-loss">-4.00%</span>');
    expect(fmtCall(get("sharpe_1y"), 1.1)).toBe("1.10");
    expect(fmtCall(get("peer_sharpe_pctl"), 87)).toBe("87");
    expect(fmtCall(get("elite_flag"), true)).toBe('<span class="ix-grid-elite" aria-label="Elite fund">✓</span>');
    expect(fmtCall(get("elite_flag"), false)).toBe('<span class="text-text-muted">—</span>');
  });
});

describe("fundsGridData", () => {
  it("pivots items into column arrays including instrument_id, null-safe", () => {
    const data = fundsGridData(ITEMS);
    expect(data.providerType).toBe("local");
    expect(data.columns!.ticker).toEqual(["AAA", null]);
    expect(data.columns!.instrument_id).toEqual(["uuid-1", "uuid-2"]);
    expect(data.columns!.elite_flag).toEqual([true, false]);
    expect(data.columns!.aum_usd).toEqual([1_000_000, null]);
  });
});

describe("fundsListToGridOptions", () => {
  it("applies theme + virtualization and wires afterSort with the loop guard", () => {
    const onSortChange = vi.fn();
    const opts = fundsListToGridOptions(LIST, { sort: "aum_usd", dir: "desc" }, { onSortChange });
    expect(opts.rendering?.theme).toBe(GRAPHITE_THEME);
    expect(opts.rendering?.rows?.virtualization).toBe(true);
    const afterSort = opts.columnDefaults?.events?.afterSort as unknown as (this: {
      id: string;
      options: { sorting?: { order?: "asc" | "desc" | null } };
    }) => void;
    // matches current state -> no-op
    afterSort.call({ id: "aum_usd", options: { sorting: { order: "desc" } } });
    expect(onSortChange).not.toHaveBeenCalled();
    // changed -> fires
    afterSort.call({ id: "sharpe_1y", options: { sorting: { order: "asc" } } });
    expect(onSortChange).toHaveBeenCalledWith("sharpe_1y", "asc");
  });
});
