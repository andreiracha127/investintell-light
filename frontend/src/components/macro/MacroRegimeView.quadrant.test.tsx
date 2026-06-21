// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

// Full-replacement mock of the API client: the component (and its retry/404
// logic) needs `ApiError` as a real class plus the fetchers it calls directly.
vi.mock("@/lib/api/client", () => {
  class ApiError extends Error {
    status: number;
    constructor(status: number, message: string) {
      super(message);
      this.status = status;
    }
  }
  return {
    ApiError,
    fetchMacroRegime: vi.fn().mockResolvedValue({
      detector: "vote2of3",
      state: "risk_on",
      vote_count: 1,
      votes: { credit: false, trend: true, nfci: false },
      as_of: "2026-06-18",
      days_in_state: 10,
      last_flip: null,
      signal: { ratio: 1, p20_5y: 0.9, distance_pct: 5, nfci: -0.2 },
      recent_flips: [],
      history: [],
      macro_quadrant: {
        as_of: "2026-06-18",
        quadrant: "EXPANSION",
        growth_state: "up",
        inflation_state: "up",
        growth_score: 0.07,
        inflation_score: 0.02,
        combined_regime: "INFLATION",
        bands: [
          { asset_class: "equity", min_weight: 0.3, max_weight: 0.54 },
          { asset_class: "fixed_income", min_weight: 0.16, max_weight: 0.34 },
          { asset_class: "alternatives", min_weight: 0.13, max_weight: 0.31 },
          { asset_class: "cash", min_weight: 0.05, max_weight: 0.17 },
        ],
        haven_tilt: null,
        gate: {
          as_of: "2026-06-18",
          state: "risk_on",
          trend_vote: true,
          credit_vote: false,
          drawdown_vote: false,
          vote_count: 1,
          dwell_days: 40,
        },
      },
    }),
    fetchPortfolioOverview: vi.fn(),
    fetchStockTimeseries: vi.fn().mockResolvedValue({ series: [] }),
    fetchFundTimeseries: vi.fn().mockResolvedValue({ series: [] }),
    stockTimeseriesToHistoryBars: vi.fn().mockReturnValue([]),
  };
});

vi.mock("@/lib/charts/chartColors", () => ({ chartColors: () => null }));

// Inert stubs for the child components that do their own data-fetching.
vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="hc" />,
}));
vi.mock("@/components/charts/SymbolSearchInput", () => ({
  SymbolSearchInput: () => <div data-testid="symbol-search" />,
}));
vi.mock("@/components/statistics/PortfolioSelect", () => ({
  PortfolioSelect: () => <div data-testid="portfolio-select" />,
}));
vi.mock("@/components/portfolio/usePortfolioNav", () => ({
  usePortfolioNav: () => ({
    recon: { nav: [] },
    isError: false,
    isLoading: false,
    refetch: vi.fn(),
  }),
}));

import { MacroRegimeView } from "./MacroRegimeView";

afterEach(cleanup);

it("shows current quadrant and combined regime", async () => {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <MacroRegimeView />
    </QueryClientProvider>,
  );
  // The COMBO section surfaces the worker-materialized quadrant (exact label, to
  // avoid matching the RRG tooltip that also mentions "Expansion").
  await waitFor(() =>
    expect(screen.getByText("Expansion", { selector: "span" })).toBeInTheDocument(),
  );
  // The combined regime label (RISK_ON/INFLATION/… → human label).
  expect(screen.getByText("Inflation bands")).toBeInTheDocument();
  // The raw combined_regime code is surfaced next to the label (appears in both
  // the section header and the regime badge).
  expect(screen.getAllByText(/· INFLATION/).length).toBeGreaterThan(0);
});

it("shows the live gate state, votes, and dwell time", async () => {
  const qc = new QueryClient();
  render(
    <QueryClientProvider client={qc}>
      <MacroRegimeView />
    </QueryClientProvider>,
  );
  // dwell_days + vote_count from the gate block (unique gate-context string).
  await waitFor(() =>
    expect(screen.getByText(/1\/3 votes · 40 days latched/)).toBeInTheDocument(),
  );
});
