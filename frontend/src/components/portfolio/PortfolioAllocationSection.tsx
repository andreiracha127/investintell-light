"use client";

import { DataGrid } from "@/components/ui/DataGrid";
import { Card } from "@/components/ui/panels";
import type { PortfolioOverview } from "@/lib/api/client";
import {
  buildAllocationTree,
  type AllocationInput,
} from "@/lib/portfolio/allocationTree";
import { weightsTreeGridOptions } from "@/lib/grid/weightsTreeGridOptions";

/**
 * Read-only allocation breakdown. The editable holdings grid remains separate.
 */
export function PortfolioAllocationSection({
  overview,
}: {
  overview: PortfolioOverview;
}) {
  const { positions, aggregates } = overview;
  const totalValue = aggregates.total_value;
  const cashValue = aggregates.cash;
  if (totalValue <= 0) return null;

  const rows = buildAllocationTree(
    positions.map<AllocationInput>((p) => ({
      ticker: p.ticker ?? null,
      name: p.name ?? null,
      marketValue: p.market_value,
      assetClass: p.asset_class ?? null,
      strategyLabel: p.strategy_label ?? null,
      instrumentId: p.instrument_id ?? null,
    })),
    totalValue,
    cashValue,
  );
  if (rows.length === 0) return null;

  return (
    <Card title="Allocation" subtitle="asset class / holding">
      <DataGrid
        options={weightsTreeGridOptions(rows)}
        className="h-[420px] w-full"
        emptyMessage="No holdings to allocate."
      />
    </Card>
  );
}
