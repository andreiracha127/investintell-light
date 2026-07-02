// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="highcharts-chart" />,
}));
vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return { ...actual, postBacktestWalkForward: vi.fn() };
});

import * as client from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type {
  BuilderObjective,
  OptimizeResponse,
  WalkForwardRequest,
  WalkForwardResponse,
  WeightOut,
} from "@/lib/api/client";

import { BacktestTab } from "./BacktestTab";

const mocked = vi.mocked(client);

const SPY_WEIGHT = {
  asset: { kind: "equity", ticker: "SPY" },
  weight: 0.6,
  ticker: "SPY",
  name: "SPDR S&P 500 ETF",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

const QQQ_WEIGHT = {
  asset: { kind: "equity", ticker: "QQQ" },
  weight: 0.4,
  ticker: "QQQ",
  name: "Invesco QQQ",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

function makeResult(): OptimizeResponse {
  return {
    weights: [SPY_WEIGHT, QQQ_WEIGHT],
    expected: {
      vol_ann: 0.12,
      cvar_95_in_sample: 0.03,
      return_ann_bl: null,
    },
    diagnostics: {
      n_obs: 252,
      status: "optimal",
      mu_equilibrium: null,
      mu_posterior: null,
      view_consistency: null,
      selection: null,
      cvar_limit_effective: null,
      regime_state: null,
    },
  };
}

function makeWalkForward(): WalkForwardResponse {
  return {
    folds: [
      {
        fold: 1,
        train_size: 252,
        n_obs: 63,
        sharpe: 1.2,
        cvar_95: -0.02,
        max_drawdown: -0.05,
        turnover: 0.1,
        gross_return: 0.05,
        net_return: 0.04,
      },
      {
        fold: 2,
        train_size: 315,
        n_obs: 63,
        sharpe: 0.8,
        cvar_95: -0.03,
        max_drawdown: -0.06,
        turnover: 0.15,
        gross_return: 0.03,
        net_return: 0.02,
      },
    ],
    params: {
      objective: "min_cvar",
      n_obs: 504,
      n_splits_computed: 2,
      gap: 2,
      test_size: 63,
      min_train_size: 252,
      cost_bps: 10,
    },
    mean_sharpe: 1,
    std_sharpe: 0.2,
    positive_folds: 2,
    mean_turnover: 0.12,
    oos_curve: [
      ["2025-06-12", 1],
      ["2025-12-11", 1.03],
      ["2025-12-12", 1.035],
      ["2026-06-12", 1.06],
    ],
    fold_boundaries: ["2025-06-12", "2025-12-12"],
  };
}

function renderTab({
  objective,
  cvarLimit = null,
}: {
  objective: BuilderObjective;
  cvarLimit?: number | null;
}) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <BacktestTab
        result={makeResult()}
        objective={objective}
        constraints={{ cap: 0.25, min_weight: null }}
        windowDays={756}
        cvarLimit={cvarLimit}
        colors={TEST_COLORS}
      />
    </QueryClientProvider>,
  );
}

function sentBody(): WalkForwardRequest {
  return mocked.postBacktestWalkForward.mock.calls[0][0];
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("BacktestTab", () => {
  it("renders loading then posts the walk-forward body and renders KPIs, table, and charts", async () => {
    mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
    renderTab({ objective: "min_vol" });

    expect(
      screen.getByLabelText("Running walk-forward backtest"),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1),
    );
    expect(sentBody()).toEqual({
      assets: [
        { kind: "equity", ticker: "SPY" },
        { kind: "equity", ticker: "QQQ" },
      ],
      objective: "min_vol",
      constraints: { cap: 0.25, min_weight: null },
      window_days: 756,
      n_splits: 5,
      gap: 2,
      test_size: 63,
      min_train_size: 252,
      cost_bps: 10,
      risk_free_annual: 0,
    });

    expect(await screen.findByText("Average Sharpe")).toBeInTheDocument();
    expect(screen.getByText("Consistency")).toBeInTheDocument();
    expect(screen.getByText("2 / 2")).toBeInTheDocument();
    expect(screen.getByText("Average turnover")).toBeInTheDocument();
    // Each fold row names its REAL test window (fold_boundaries → oos end),
    // not an anonymous "Period N".
    // Fold 1 ends on the last OOS date before the fold-2 boundary
    // (Dec 11), not on the boundary itself (Dec 12, fold 2's first day).
    expect(
      screen.getAllByText("Jun 12, 2025 → Dec 11, 2025").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Dec 12, 2025 → Jun 12, 2026").length,
    ).toBeGreaterThan(0);
    expect(screen.getByText(/#1 · trained on 252d/)).toBeInTheDocument();
    expect(
      screen.getByText(/2 test periods · Jun 12, 2025 → Jun 12, 2026/),
    ).toBeInTheDocument();
    expect(screen.getAllByTestId("highcharts-chart")).toHaveLength(2);
  });

  it("downgrades bl_utility to min_cvar with a visible note", async () => {
    mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
    renderTab({ objective: "bl_utility" });

    await waitFor(() =>
      expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1),
    );
    expect(sentBody().objective).toBe("min_cvar");
    expect(screen.getByText(/objective adjusted to/i)).toBeInTheDocument();
  });

  it("sends max_return_cvar with cvar_limit when provided", async () => {
    mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
    renderTab({ objective: "max_return_cvar", cvarLimit: 0.025 });

    await waitFor(() =>
      expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1),
    );
    expect(sentBody().objective).toBe("max_return_cvar");
    expect(sentBody().cvar_limit).toBe(0.025);
    expect(screen.queryByText(/objective adjusted to/i)).not.toBeInTheDocument();
  });

  it("changes metric UI state without refiring the API", async () => {
    mocked.postBacktestWalkForward.mockResolvedValue(makeWalkForward());
    const user = userEvent.setup();
    renderTab({ objective: "min_vol" });

    const sharpe = await screen.findByRole("button", { name: "Sharpe" });
    expect(sharpe).toHaveAttribute("aria-pressed", "false");

    await user.click(sharpe);

    expect(sharpe).toHaveAttribute("aria-pressed", "true");
    expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(1);
  });

  it("shows the verbatim 422 detail and retries the same body", async () => {
    const user = userEvent.setup();
    mocked.postBacktestWalkForward
      .mockRejectedValueOnce(new client.ApiError(422, "cvar_limit: Field required"))
      .mockResolvedValueOnce(makeWalkForward());
    renderTab({ objective: "max_return_cvar", cvarLimit: null });

    expect(await screen.findByText("cvar_limit: Field required")).toBeInTheDocument();
    const firstBody = sentBody();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() =>
      expect(mocked.postBacktestWalkForward).toHaveBeenCalledTimes(2),
    );
    expect(mocked.postBacktestWalkForward.mock.calls[1][0]).toEqual(firstBody);
    expect(await screen.findByText("Average Sharpe")).toBeInTheDocument();
  });

  it("renders with empty OOS curve defaults when optional response fields are absent", async () => {
    const response = makeWalkForward();
    delete response.oos_curve;
    delete response.fold_boundaries;
    mocked.postBacktestWalkForward.mockResolvedValue(response);

    renderTab({ objective: "min_vol" });

    expect(await screen.findByText("Average Sharpe")).toBeInTheDocument();
    expect(screen.getAllByTestId("highcharts-chart")).toHaveLength(2);
  });
});
