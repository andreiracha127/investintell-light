// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { OptimizeRequest } from "@/lib/api/client";

const resultsPanelMock = vi.hoisted(() =>
  vi.fn((props: unknown) => {
    void props;
    return <div data-testid="results" />;
  }),
);

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
  ResultsPanel: (props: unknown) => resultsPanelMock(props),
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
  resultsPanelMock.mockClear();
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
      "Daily loss limit",
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

  it("keeps result tabs pinned to the submitted run parameters after edits", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.click(screen.getByRole("button", { name: /suggest weights/i }));

    await waitFor(() => expect(resultsPanelMock).toHaveBeenCalled());
    await user.clear(screen.getByLabelText("Max per holding"));
    await user.type(screen.getByLabelText("Max per holding"), "40");
    await user.selectOptions(screen.getByLabelText("Risk mandate"), "aggressive");

    const latestProps = resultsPanelMock.mock.calls.at(-1)?.[0];
    expect(latestProps).toBeDefined();
    const props = latestProps as {
      constraints: { cap: number | null; min_weight: number | null };
      cvarLimit: number | null;
      cvarLimitPct: string | null;
      objective: string;
      windowDays: number | null;
    };
    expect(props.objective).toBe("max_return_cvar");
    expect(props.constraints).toEqual({ cap: 0.25, min_weight: null });
    expect(props.windowDays).toBeNull();
    expect(props.cvarLimit).toBeCloseTo(0.02, 6);
    expect(props.cvarLimitPct).toBe("2");
  });

  it("keeps submitted null constraints pinned after edits", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.clear(screen.getByLabelText("Max per holding"));
    await user.click(screen.getByRole("button", { name: /suggest weights/i }));

    await waitFor(() => expect(resultsPanelMock).toHaveBeenCalled());
    await user.type(screen.getByLabelText("Max per holding"), "40");
    await user.type(screen.getByLabelText("Min per holding"), "5");
    await user.type(screen.getByLabelText("History window"), "252");

    const latestProps = resultsPanelMock.mock.calls.at(-1)?.[0];
    expect(latestProps).toBeDefined();
    const props = latestProps as {
      constraints: { cap: number | null; min_weight: number | null };
      windowDays: number | null;
    };
    expect(props.constraints).toEqual({ cap: null, min_weight: null });
    expect(props.windowDays).toBeNull();
  });

  it("blocks the run when the CVaR ceiling is cleared under max_return_cvar", async () => {
    const user = userEvent.setup();
    renderView();
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.clear(screen.getByLabelText("Daily loss limit"));
    const run = screen.getByRole("button", { name: /suggest weights/i });
    expect(run).toBeDisabled();
    expect(
      screen.getByText(/needs a daily loss limit/i),
    ).toBeInTheDocument();
  });
});

describe("BuilderView Regime-Aware objective option", () => {
  it("offers Regime-Aware in the objective dropdown and submits regime_aware", async () => {
    const user = userEvent.setup();
    renderView();
    const objective = screen.getByLabelText(
      "Optimization objective",
    ) as HTMLSelectElement;
    // The dropdown exposes a "Regime-Aware" option wired to the regime_aware value.
    const option = within(objective).getByRole("option", {
      name: "Regime-Aware",
    }) as HTMLOptionElement;
    expect(option.value).toBe("regime_aware");

    // Selecting it submits the regime_aware objective end-to-end.
    await user.click(screen.getByRole("button", { name: "seed-two" }));
    await user.selectOptions(objective, "regime_aware");
    await user.click(screen.getByRole("button", { name: /suggest weights/i }));
    await waitFor(() => expect(optimizeMock).toHaveBeenCalled());
    const body = optimizeMock.mock.calls.at(-1)?.[0];
    expect(body?.objective).toBe("regime_aware");
  });
});
