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
vi.mock("@/lib/charts/chartColors", () => ({
  chartColors: () => null,
}));

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
vi.mock("./ViewsCard", () => ({
  ViewsCard: () => <div />,
  toApiView: () => null,
}));
vi.mock("./ResultsPanel", () => ({
  ResultsPanel: () => <div data-testid="results" />,
}));
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

describe("BuilderView max_return_cvar controls", () => {
  it("defaults the objective to max_return_cvar", () => {
    renderView();
    const objective = screen.getByLabelText(
      "Optimization objective",
    ) as HTMLSelectElement;
    expect(objective.value).toBe("max_return_cvar");
  });

  it("renders a mandate select and a CVaR-ceiling field pre-filled from the preset", async () => {
    const user = userEvent.setup();
    renderView();
    const mandate = screen.getByLabelText("Risk mandate") as HTMLSelectElement;
    const ceiling = screen.getByLabelText(
      "Teto CVaR diário %",
    ) as HTMLInputElement;
    expect(mandate.value).toBe("moderate");
    expect(ceiling.value).toBe("2");

    await user.selectOptions(mandate, "conservative");
    expect(ceiling.value).toBe("1");
  });

  it("posts objective, mandate and cvar_limit = pct/100 on run", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.selectOptions(screen.getByLabelText("Risk mandate"), "aggressive");
    await user.click(screen.getByRole("button", { name: /suggest weights/i }));

    await waitFor(() => expect(optimizeMock).toHaveBeenCalledTimes(1));
    const body = optimizeMock.mock.calls[0]?.[0];
    expect(body).toBeDefined();
    expect(body?.objective).toBe("max_return_cvar");
    expect(body?.mandate).toBe("aggressive");
    expect(body?.cvar_limit).toBeCloseTo(0.03, 6);
  });

  it("blocks the run when the CVaR ceiling is cleared under max_return_cvar", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.clear(screen.getByLabelText("Teto CVaR diário %"));
    const run = screen.getByRole("button", { name: /suggest weights/i });
    expect(run).toBeDisabled();
    expect(
      screen.getByText(/Max retorno sob CVaR needs a daily CVaR ceiling/i),
    ).toBeInTheDocument();
  });
});
