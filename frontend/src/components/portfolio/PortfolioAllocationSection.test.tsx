// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { PortfolioAllocationSection } from "./PortfolioAllocationSection";
import type { PortfolioOverview } from "@/lib/api/client";

vi.mock("@/components/ui/DataGrid", () => ({
  DataGrid: ({ options }: { options: unknown }) => (
    <div data-testid="datagrid" data-rows={JSON.stringify(options).length} />
  ),
}));

afterEach(cleanup);

const overview = {
  id: 1,
  name: "P",
  positions: [
    {
      ticker: "VTI",
      name: "Vanguard",
      market_value: 60,
      asset_class: "equity",
      strategy_label: "Large-Cap Blend",
      instrument_id: "iid-1",
    },
  ],
  aggregates: { total_value: 100, total_market_value: 60, cash: 40 },
} as unknown as PortfolioOverview;

describe("PortfolioAllocationSection", () => {
  it("renders the allocation grid for a portfolio with holdings", () => {
    render(<PortfolioAllocationSection overview={overview} />);
    expect(screen.getByTestId("datagrid")).toBeInTheDocument();
    expect(screen.getByText(/Allocation/i)).toBeInTheDocument();
  });

  it("renders nothing when there are no holdings and no cash", () => {
    const empty = {
      ...overview,
      positions: [],
      aggregates: { total_value: 0, total_market_value: 0, cash: 0 },
    } as unknown as PortfolioOverview;
    const { container } = render(<PortfolioAllocationSection overview={empty} />);
    expect(container).toBeEmptyDOMElement();
  });
});
