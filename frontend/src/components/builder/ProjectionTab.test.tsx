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
  return { ...actual, postPortfolioMonteCarlo: vi.fn() };
});

import * as client from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type {
  OptimizeResponse,
  PortfolioMonteCarloRequest,
  PortfolioMonteCarloResponse,
  WeightOut,
} from "@/lib/api/client";

import { ProjectionTab } from "./ProjectionTab";

const mocked = vi.mocked(client);

const SPY_WEIGHT = {
  asset: { kind: "equity", ticker: "SPY" },
  weight: 0.6,
  ticker: "SPY",
  name: "SPDR S&P 500 ETF",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

const FUND_WEIGHT = {
  asset: { kind: "fund", id: "00000000-0000-0000-0000-000000000001" },
  weight: 0.4,
  ticker: null,
  name: "Tickerless fund",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

const ZERO_WEIGHT = {
  asset: { kind: "equity", ticker: "ZERO" },
  weight: 0,
  ticker: "ZERO",
  name: "Zero Weight",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

function makeResult(weights: WeightOut[] = [SPY_WEIGHT, FUND_WEIGHT]): OptimizeResponse {
  return {
    weights,
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

function makeMonteCarlo({
  degraded = false,
  historicalRank = 62,
  statistic = "return",
}: {
  degraded?: boolean;
  historicalRank?: number | null;
  statistic?: PortfolioMonteCarloResponse["params"]["statistic"];
} = {}): PortfolioMonteCarloResponse {
  return {
    params: {
      statistic,
      n_assets: 2,
      n_simulations: 10000,
      risk_free_rate: 0.04,
      seed: null,
    },
    percentiles: {
      "5th": -0.2,
      "50th": 1,
      "95th": 3.2,
    },
    mean: 0.1,
    median: 0.09,
    std: 0.2,
    historical_value: 0.08,
    historical_horizon_days: 252,
    historical_percentile_rank: historicalRank,
    confidence_bars: [
      {
        horizon: "1Y",
        horizon_days: 252,
        pct_5: -0.1,
        pct_10: -0.05,
        pct_25: 0,
        pct_50: 0.08,
        pct_75: 0.16,
        pct_90: 0.24,
        pct_95: 0.3,
        mean: 0.09,
      },
      {
        horizon: "10Y",
        horizon_days: 2520,
        pct_5: -0.2,
        pct_10: -0.1,
        pct_25: 0.2,
        pct_50: 1,
        pct_75: 1.8,
        pct_90: 2.6,
        pct_95: 3.2,
        mean: 1.1,
      },
    ],
    degraded,
    degraded_reason: degraded ? "insufficient common history" : null,
  };
}

function renderTab(result: OptimizeResponse = makeResult()) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <ProjectionTab result={result} colors={TEST_COLORS} />
    </QueryClientProvider>,
  );
}

function sentBody(callIndex = 0): PortfolioMonteCarloRequest {
  return mocked.postPortfolioMonteCarlo.mock.calls[callIndex][0];
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ProjectionTab", () => {
  it("renders loading, posts return positions, and renders the cone and summary", async () => {
    mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo());
    renderTab();

    expect(
      screen.getByLabelText("Running Monte Carlo projection"),
    ).toBeInTheDocument();

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(1),
    );
    expect(sentBody()).toEqual({
      positions: [
        { asset: { kind: "equity", ticker: "SPY" }, weight: 0.6 },
        {
          asset: { kind: "fund", id: "00000000-0000-0000-0000-000000000001" },
          weight: 0.4,
        },
      ],
      statistic: "return",
      n_simulations: 10000,
      risk_free_rate: 0.04,
    });

    expect(await screen.findByText("Median @ 10Y")).toBeInTheDocument();
    expect(screen.getByText("5th–95th @ 10Y")).toBeInTheDocument();
    expect(screen.getByText("Historical percentile rank")).toBeInTheDocument();
    expect(screen.getByText("Percentile 62")).toBeInTheDocument();
    expect(screen.getByTestId("highcharts-chart")).toBeInTheDocument();
  });

  it("switching statistic refetches with the new statistic", async () => {
    mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo());
    const user = userEvent.setup();
    renderTab();

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(1),
    );

    await user.click(screen.getByRole("button", { name: "Max drawdown" }));

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(2),
    );
    expect(sentBody(1).statistic).toBe("max_drawdown");
  });

  it("drops zero weights and renormalizes before posting positions", async () => {
    mocked.postPortfolioMonteCarlo.mockResolvedValue(makeMonteCarlo());
    renderTab(
      makeResult([
        { ...SPY_WEIGHT, weight: 0.3 },
        { ...FUND_WEIGHT, weight: 0.2 },
        ZERO_WEIGHT,
      ]),
    );

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(1),
    );
    expect(sentBody().positions).toEqual([
      { asset: { kind: "equity", ticker: "SPY" }, weight: 0.6 },
      {
        asset: { kind: "fund", id: "00000000-0000-0000-0000-000000000001" },
        weight: 0.4,
      },
    ]);
  });

  it("fails loud without calling the API when fewer than two active positions remain", async () => {
    renderTab(makeResult([SPY_WEIGHT, ZERO_WEIGHT]));

    expect(
      await screen.findByText(
        "At least two active positions above the weight floor are required.",
      ),
    ).toBeInTheDocument();
    expect(mocked.postPortfolioMonteCarlo).not.toHaveBeenCalled();
  });

  it("renders the degraded reason when present", async () => {
    mocked.postPortfolioMonteCarlo.mockResolvedValue(
      makeMonteCarlo({ degraded: true }),
    );
    renderTab();

    expect(
      await screen.findByText("insufficient common history"),
    ).toBeInTheDocument();
  });

  it("shows the verbatim 422 detail and retries the active statistic", async () => {
    const user = userEvent.setup();
    mocked.postPortfolioMonteCarlo
      .mockRejectedValueOnce(new client.ApiError(422, "portfolio has no overlap"))
      .mockResolvedValueOnce(makeMonteCarlo());
    renderTab();

    expect(await screen.findByText("portfolio has no overlap")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(2),
    );
    expect(sentBody(1).statistic).toBe("return");
    expect(await screen.findByText("Median @ 10Y")).toBeInTheDocument();
  });

  it("handles a Sharpe projection with null historical rank", async () => {
    mocked.postPortfolioMonteCarlo
      .mockResolvedValueOnce(makeMonteCarlo())
      .mockResolvedValueOnce(
        makeMonteCarlo({ statistic: "sharpe", historicalRank: null }),
      );
    const user = userEvent.setup();
    renderTab();

    await screen.findByText("Median @ 10Y");
    await user.click(screen.getByRole("button", { name: "Sharpe" }));

    await waitFor(() =>
      expect(mocked.postPortfolioMonteCarlo).toHaveBeenCalledTimes(2),
    );
    expect(sentBody(1).statistic).toBe("sharpe");
    expect(await screen.findByText("1.00")).toBeInTheDocument();
    expect(screen.getByText("-")).toBeInTheDocument();
  });
});
