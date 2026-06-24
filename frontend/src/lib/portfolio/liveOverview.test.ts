import { describe, expect, it } from "vitest";

import type { PortfolioOverview } from "@/lib/api/client";
import {
  applyLiveTicksToOverview,
  liveEligibleTickers,
} from "./liveOverview";

function position(
  ticker: string,
  overrides: Partial<PortfolioOverview["positions"][number]> = {},
): PortfolioOverview["positions"][number] {
  return {
    ticker,
    name: `${ticker} Name`,
    asset_class: "equity",
    strategy_label: null,
    instrument_id: null,
    fund_type: null,
    price_source: "eod",
    live_price_eligible: true,
    quantity: 2,
    acq_price: 80,
    basis: "reference",
    commission: null,
    trade_date: null,
    last_close: 100,
    prev_close: 95,
    change: 5,
    change_pct: 5 / 95,
    market_value: 200,
    cost_basis: 160,
    pnl: 40,
    pnl_pct: 0.25,
    as_of: "2026-06-24",
    ...overrides,
  };
}

function overview(
  positions: PortfolioOverview["positions"],
  cash = 10,
): PortfolioOverview {
  const totalMarketValue = positions.reduce((sum, p) => sum + p.market_value, 0);
  const costValues = positions
    .map((p) => p.cost_basis)
    .filter((v): v is number => v !== null);
  const pnlValues = positions
    .map((p) => p.pnl)
    .filter((v): v is number => v !== null);
  const totalCostBasis = costValues.reduce((sum, v) => sum + v, 0);
  const totalPnl = pnlValues.reduce((sum, v) => sum + v, 0);
  return {
    id: 1,
    name: "Test",
    positions,
    aggregates: {
      total_market_value: totalMarketValue,
      total_cost_basis: totalCostBasis,
      total_pnl: totalPnl,
      total_pnl_pct: totalPnl / totalCostBasis,
      cash,
      total_value: totalMarketValue + cash,
      as_of: "2026-06-24",
    },
  };
}

describe("liveEligibleTickers", () => {
  it("returns only live-eligible tickers without duplicates", () => {
    const input = overview([
      position("AAPL"),
      position("AAPL"),
      position("VFIAX", {
        instrument_id: "00000000-0000-0000-0000-000000000001",
        fund_type: "mutual_fund",
        price_source: "nav",
        live_price_eligible: false,
      }),
      position("SPY", {
        instrument_id: "00000000-0000-0000-0000-000000000002",
        fund_type: "etf",
        live_price_eligible: true,
      }),
    ]);

    expect(liveEligibleTickers(input)).toEqual(["AAPL", "SPY"]);
  });
});

describe("applyLiveTicksToOverview", () => {
  it("reprices eligible stock positions and recomputes aggregates", () => {
    const input = overview([position("AAPL")], 10);
    const out = applyLiveTicksToOverview(input, { AAPL: { price: 110 } });

    expect(out.positions[0]).toMatchObject({
      last_close: 110,
      prev_close: 100,
      change: 10,
      change_pct: 0.1,
      market_value: 220,
      pnl: 60,
      pnl_pct: 60 / 160,
    });
    expect(out.aggregates).toMatchObject({
      total_market_value: 220,
      total_cost_basis: 160,
      total_pnl: 60,
      total_pnl_pct: 60 / 160,
      total_value: 230,
    });
  });

  it("keeps NAV-priced funds EOD even when a tick exists", () => {
    const fund = position("VFIAX", {
      instrument_id: "00000000-0000-0000-0000-000000000001",
      fund_type: "mutual_fund",
      price_source: "nav",
      live_price_eligible: false,
    });
    const input = overview([fund], 0);

    expect(applyLiveTicksToOverview(input, { VFIAX: { price: 999 } })).toBe(input);
  });

  it("allows ETF holdings to receive live ticks", () => {
    const etf = position("SPY", {
      instrument_id: "00000000-0000-0000-0000-000000000002",
      fund_type: "etf",
      live_price_eligible: true,
    });
    const out = applyLiveTicksToOverview(overview([etf]), { SPY: { price: 101 } });

    expect(out.positions[0].last_close).toBe(101);
    expect(out.positions[0].market_value).toBe(202);
  });
});
