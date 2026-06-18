// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OptimizeResponse } from "@/lib/api/client";
import { ResultsPanel } from "./ResultsPanel";

vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="hc" />,
}));
vi.mock("@/components/ui/DataGrid", () => ({ DataGrid: () => <div /> }));
vi.mock("@/lib/charts/hc/allocation", () => ({
  buildHcAllocationOption: () => ({}),
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, fetchFundProfile: vi.fn(), postBuilderSave: vi.fn() };
});

const result: OptimizeResponse = {
  weights: [
    {
      asset: { kind: "equity", ticker: "AAPL" },
      ticker: "AAPL",
      name: null,
      weight: 1,
      asset_class: null,
      strategy_label: null,
    },
  ],
  expected: { vol_ann: 0.12, cvar_95_in_sample: 0.01, return_ann_bl: 0.08 },
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

function renderPanel() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ResultsPanel
        result={result}
        objective="max_return_cvar"
        constraints={{ cap: null, min_weight: null }}
        windowDays={null}
        cvarLimit={0.02}
        assetsByKey={new Map()}
        base={null}
        colors={null}
        grouped={false}
        cvarLimitPct="2"
      />
    </QueryClientProvider>,
  );
}

afterEach(cleanup);

describe("ResultsPanel effective CVaR ceiling", () => {
  it("renders a tile with requested -> effective ceiling and the regime state", () => {
    renderPanel();
    expect(screen.getByText(/CVaR ceiling/i)).toBeInTheDocument();
    expect(screen.getByText(/2\.00%.*1\.00%/)).toBeInTheDocument();
    expect(screen.getByText(/risk-off/i)).toBeInTheDocument();
  });
});
