import type { PortfolioOverview } from "@/lib/api/client";

export interface LiveOverviewTick {
  price: number;
}

type Position = PortfolioOverview["positions"][number];
type Aggregates = PortfolioOverview["aggregates"];

function recomputePosition(position: Position, livePrice: number): Position {
  const prevClose = position.last_close;
  const change = livePrice - prevClose;
  const changePct = prevClose > 0 ? change / prevClose : null;
  const marketValue = position.quantity * livePrice;
  const costBasis = position.cost_basis;
  const pnl = costBasis !== null ? marketValue - costBasis : null;
  const pnlPct = pnl !== null && costBasis !== null && costBasis > 0
    ? pnl / costBasis
    : null;

  return {
    ...position,
    last_close: livePrice,
    prev_close: prevClose,
    change,
    change_pct: changePct,
    market_value: marketValue,
    pnl,
    pnl_pct: pnlPct,
  };
}

function recomputeAggregates(
  positions: Position[],
  base: Aggregates,
): Aggregates {
  const totalMarketValue = positions.reduce(
    (sum, position) => sum + position.market_value,
    0,
  );
  const costValues = positions
    .map((position) => position.cost_basis)
    .filter((value): value is number => value !== null);
  const pnlValues = positions
    .map((position) => position.pnl)
    .filter((value): value is number => value !== null);
  const totalCostBasis = costValues.length
    ? costValues.reduce((sum, value) => sum + value, 0)
    : null;
  const totalPnl = pnlValues.length
    ? pnlValues.reduce((sum, value) => sum + value, 0)
    : null;
  const totalPnlPct =
    totalPnl !== null && totalCostBasis !== null && totalCostBasis > 0
      ? totalPnl / totalCostBasis
      : null;

  return {
    ...base,
    total_market_value: totalMarketValue,
    total_cost_basis: totalCostBasis,
    total_pnl: totalPnl,
    total_pnl_pct: totalPnlPct,
    total_value: totalMarketValue + base.cash,
  };
}

export function liveEligibleTickers(overview: PortfolioOverview): string[] {
  return Array.from(
    new Set(
      overview.positions
        .filter((position) => position.live_price_eligible)
        .map((position) => position.ticker),
    ),
  );
}

export function applyLiveTicksToOverview(
  overview: PortfolioOverview,
  ticks: Record<string, LiveOverviewTick>,
): PortfolioOverview {
  let changed = false;
  const positions = overview.positions.map((position) => {
    if (!position.live_price_eligible) return position;
    const tick = ticks[position.ticker];
    if (!tick || !Number.isFinite(tick.price) || tick.price <= 0) {
      return position;
    }
    changed = true;
    return recomputePosition(position, tick.price);
  });

  if (!changed) return overview;
  return {
    ...overview,
    positions,
    aggregates: recomputeAggregates(positions, overview.aggregates),
  };
}
