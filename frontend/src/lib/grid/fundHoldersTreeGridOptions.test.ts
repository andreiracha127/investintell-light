import { describe, it, expect } from "vitest";

import type { StockFundHolders } from "@/lib/api/client";
import { fundHoldersTreeGridOptions } from "./fundHoldersTreeGridOptions";

function labelHtml(
  opts: ReturnType<typeof fundHoldersTreeGridOptions>,
  value: string,
  rowCells: Record<string, unknown>,
): string {
  const cols = opts.columns as Array<{ id?: string; cells?: { formatter?: (this: unknown) => string } }>;
  const col = cols.find((c) => c.id === "label")!;
  const fmt = col.cells!.formatter!;
  return fmt.call({ value, row: { getCell: (id: string) => ({ value: rowCells[id] }) } });
}

const data: StockFundHolders = {
  ticker: "NVDA",
  cusip: "67066G104",
  security_name: "NVIDIA Corp.",
  period: "2026-01-31",
  family_count: 1,
  fund_count: 2,
  total_market_value: 200,
  families: [
    {
      registrant_cik: "0001100663",
      family: "iSHARES TRUST",
      market_value: 200,
      fund_count: 2,
      funds: [
        { series_id: "S1", fund_name: "iShares Core S&P 500 ETF", instrument_id: "abc-123",
          quantity: 1, market_value: 100, pct_of_nav: 5, pct_nav_q1: 4, pct_nav_q2: 3, pct_nav_q3: 2 },
        { series_id: "S2", fund_name: "Uncatalogued Fund", instrument_id: null,
          quantity: 1, market_value: 100, pct_of_nav: 5, pct_nav_q1: 4, pct_nav_q2: 3, pct_nav_q3: 2 },
      ],
    },
  ],
  empty_state: null,
};

describe("fundHoldersTreeGridOptions label links", () => {
  it("links a catalogued fund to its dossier", () => {
    const opts = fundHoldersTreeGridOptions(data);
    const html = labelHtml(opts, "iShares Core S&P 500 ETF", { instrument_id: "abc-123", isGroup: false });
    expect(html).toContain('href="/funds/abc-123"');
    expect(html).toContain("ix-grid-link");
  });

  it("renders plain text for an uncatalogued fund", () => {
    const opts = fundHoldersTreeGridOptions(data);
    const html = labelHtml(opts, "Uncatalogued Fund", { instrument_id: null, isGroup: false });
    expect(html).not.toContain("href");
    expect(html).toContain("Uncatalogued Fund");
  });
});
