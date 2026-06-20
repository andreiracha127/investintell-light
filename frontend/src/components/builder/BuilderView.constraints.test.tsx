// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OptimizeRequest } from "@/lib/api/client";

const optimizeMock = vi.fn(async (body: OptimizeRequest) => {
  void body;
  return {
    weights: [],
    expected: { vol_ann: 0.1, cvar_95_in_sample: 0.02, return_ann_bl: null },
    diagnostics: {
      n_obs: 500,
      status: "optimal",
      mu_equilibrium: null,
      mu_posterior: null,
      view_consistency: null,
      selection: null,
      cvar_limit_effective: 0.01,
      regime_state: "risk_off",
    },
  };
});

vi.mock("@/lib/api/client", () => ({
  postBuilderOptimize: (body: OptimizeRequest) => optimizeMock(body),
  fetchPortfolioOverview: vi.fn(),
}));
vi.mock("@/lib/charts/chartColors", () => ({ chartColors: () => null }));
vi.mock("./UniverseCard", () => ({
  UniverseCard: ({ onAdd }: { onAdd: (a: unknown[]) => void }) => (
    <button
      type="button"
      onClick={() =>
        onAdd([
          { kind: "equity", ticker: "AAPL" },
          { kind: "equity", ticker: "MSFT" },
        ])
      }
    >
      seed-two
    </button>
  ),
}));
vi.mock("./FundUniverseCard", () => ({ FundUniverseCard: () => <div /> }));
vi.mock("./ViewsCard", () => ({ ViewsCard: () => <div />, toApiView: () => null }));
vi.mock("./ResultsPanel", () => ({ ResultsPanel: () => <div data-testid="results" /> }));
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(),
}));

import { BuilderView } from "./BuilderView";

function renderView() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <BuilderView />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  optimizeMock.mockClear();
});

describe("BuilderView constraints payload", () => {
  it("sends overlap_cap and block_budgets in constraints when set", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));

    await user.type(screen.getByLabelText("Overlap cap"), "20");
    await user.type(screen.getByLabelText("Equity min"), "10");
    await user.type(screen.getByLabelText("Equity max"), "60");

    await user.click(screen.getByRole("button", { name: /suggest weights/i }));

    await waitFor(() => expect(optimizeMock).toHaveBeenCalledTimes(1));
    const body = optimizeMock.mock.calls[0]?.[0];
    expect(body).toBeDefined();
    expect(body?.constraints.overlap_cap).toBeCloseTo(0.2, 6);
    expect(body?.constraints.block_budgets).toEqual([
      { asset_class: "equity", lo: 0.1, hi: 0.6 },
    ]);
  });

  it("omits overlap_cap and block_budgets when the fields are blank", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.click(screen.getByRole("button", { name: /suggest weights/i }));

    await waitFor(() => expect(optimizeMock).toHaveBeenCalledTimes(1));
    const body = optimizeMock.mock.calls[0]?.[0];
    expect(body?.constraints.overlap_cap ?? null).toBeNull();
    expect(body?.constraints.block_budgets ?? null).toBeNull();
  });
});
