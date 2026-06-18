// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OptimizeResponse } from "@/lib/api/client";

vi.mock("./AllocationTab", () => ({
  AllocationTab: () => <div data-testid="allocation-tab" />,
}));
vi.mock("./RiskTab", () => ({
  RiskTab: () => <div data-testid="risk-tab" />,
}));
vi.mock("./BacktestTab", () => ({
  BacktestTab: () => <div data-testid="backtest-tab" />,
}));
vi.mock("./ProjectionTab", () => ({
  ProjectionTab: () => <div data-testid="projection-tab" />,
}));

import { ResultsPanel } from "./ResultsPanel";

const RESULT: OptimizeResponse = {
  weights: [],
  expected: { vol_ann: 0, cvar_95_in_sample: 0, return_ann_bl: null },
  diagnostics: {
    n_obs: 0,
    status: "empty",
    mu_equilibrium: null,
    mu_posterior: null,
    view_consistency: null,
    selection: null,
    cvar_limit_effective: null,
    regime_state: null,
  },
};

function renderPanel(result: OptimizeResponse = RESULT) {
  return render(
    <ResultsPanel
      result={result}
      objective="min_cvar"
      constraints={{ cap: 0.25, min_weight: null }}
      windowDays={null}
      cvarLimit={null}
      assetsByKey={new Map()}
      base={null}
      colors={null}
      grouped={false}
      cvarLimitPct={null}
    />,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ResultsPanel tab shell", () => {
  it("shows Allocation by default and exposes all four tabs", () => {
    renderPanel();

    expect(screen.getByTestId("allocation-tab")).toBeInTheDocument();
    for (const name of ["Allocation", "Risk", "Backtest", "Projection"]) {
      expect(screen.getByRole("tab", { name })).toBeInTheDocument();
    }
    expect(screen.getByRole("tab", { name: "Allocation" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  it("switches to Risk and keeps visited tabs mounted without remounting them", async () => {
    const user = userEvent.setup();
    renderPanel();
    const allocation = screen.getByRole("tab", { name: "Allocation" });
    const risk = screen.getByRole("tab", { name: "Risk" });

    expect(allocation).toHaveAttribute("aria-selected", "true");
    expect(risk).toHaveAttribute("aria-selected", "false");

    await user.click(risk);

    const riskNode = screen.getByTestId("risk-tab");
    expect(screen.getByTestId("allocation-tab")).not.toBeVisible();
    expect(riskNode).toBeVisible();
    expect(allocation).toHaveAttribute("aria-selected", "false");
    expect(risk).toHaveAttribute("aria-selected", "true");

    await user.click(allocation);
    expect(riskNode).not.toBeVisible();
    await user.click(risk);

    expect(screen.getByTestId("risk-tab")).toBe(riskNode);
    expect(screen.getByTestId("risk-tab")).toBeInTheDocument();
    expect(allocation).toHaveAttribute("aria-selected", "false");
    expect(risk).toHaveAttribute("aria-selected", "true");
  });

  it("resets visited data tabs when a new optimization result arrives", async () => {
    const user = userEvent.setup();
    const view = renderPanel();

    await user.click(screen.getByRole("tab", { name: "Risk" }));
    expect(screen.getByTestId("risk-tab")).toBeInTheDocument();

    view.rerender(
      <ResultsPanel
        result={{
          ...RESULT,
          weights: [
            {
              asset: { kind: "equity", ticker: "SPY" },
              weight: 1,
              ticker: "SPY",
              name: "SPY",
              asset_class: null,
              strategy_label: null,
            },
          ],
        }}
        objective="min_cvar"
        constraints={{ cap: 0.25, min_weight: null }}
        windowDays={null}
        cvarLimit={null}
        assetsByKey={new Map()}
        base={null}
        colors={null}
        grouped={false}
        cvarLimitPct={null}
      />,
    );

    expect(screen.getByTestId("allocation-tab")).toBeVisible();
    expect(screen.queryByTestId("risk-tab")).not.toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Allocation" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });
});
