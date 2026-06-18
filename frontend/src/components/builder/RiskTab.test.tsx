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
  return { ...actual, postPortfolioAnalysis: vi.fn() };
});

import * as client from "@/lib/api/client";
import { TEST_COLORS } from "@/lib/charts/hc/__fixtures__/colors";
import type {
  OptimizeResponse,
  PortfolioAnalysis,
  WeightOut,
} from "@/lib/api/client";

import type { UniverseAsset } from "./assets";
import { RiskTab } from "./RiskTab";

const mocked = vi.mocked(client);

const SPY_WEIGHT = {
  asset: { kind: "equity", ticker: "SPY" },
  weight: 0.6,
  ticker: "SPY",
  name: "SPDR S&P 500 ETF",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

const QQQ_WEIGHT_FROM_ASSET = {
  asset: { kind: "equity", ticker: "QQQ" },
  weight: 0.4,
  ticker: null,
  name: "Invesco QQQ",
  asset_class: null,
  strategy_label: null,
} satisfies WeightOut;

const FUND_NO_TICKER = {
  asset: { kind: "fund", id: "uuid-1" },
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

function makeResult(weights: WeightOut[]): OptimizeResponse {
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

function makeAnalysis(): PortfolioAnalysis {
  return {
    params: {
      mode: "weights",
      range: "1Y",
      benchmark: "SPY",
      start_date: "2025-06-12",
      end_date: "2026-06-12",
      initial_nav: 10000,
    },
    allocation: {
      initial_nav: 10000,
      positions: [
        { ticker: "SPY", weight: 0.6, initial_value: 6000 },
        { ticker: "QQQ", weight: 0.4, initial_value: 4000 },
      ],
    },
    nav: [
      ["2025-06-12", 10000],
      ["2026-06-12", 12500],
    ],
    stats: {
      annualized_volatility: 0.12,
      var_95: 0.02,
      var_99: 0.03,
      cvar_95: 0.03,
      total_return: 0.25,
      beta: 1,
      correlation: 0.95,
      diversification_ratio: 1.2,
      sharpe_ratio: 1.1,
      sortino_ratio: 1.3,
      information_ratio: 0.4,
      effective_number_of_bets: 1.8,
      max_drawdown: {
        depth: -0.08,
        peak_date: "2026-01-01",
        trough_date: "2026-03-01",
      },
      best_day: { date: "2026-01-05", value: 0.02 },
      worst_day: { date: "2026-02-05", value: -0.03 },
    },
    risk_contributions: [
      { ticker: "SPY", contribution: 0.6 },
      { ticker: "QQQ", contribution: 0.4 },
    ],
    correlation_matrix: {
      tickers: ["SPY", "QQQ"],
      matrix: [
        [1, 0.9],
        [0.9, 1],
      ],
    },
    benchmark_comparison: {
      portfolio: [
        ["2025-06-12", 0],
        ["2026-06-12", 0.25],
      ],
      benchmark: [
        ["2025-06-12", 0],
        ["2026-06-12", 0.2],
      ],
    },
    histogram: {
      bin_edges: [-0.04, 0, 0.04],
      counts: [3, 7],
      counts_normalized: [0.43, 1],
    },
  };
}

function renderTab(
  result: OptimizeResponse,
  assetsByKey: Map<string, UniverseAsset> = new Map(),
) {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });

  return render(
    <QueryClientProvider client={queryClient}>
      <RiskTab result={result} assetsByKey={assetsByKey} colors={TEST_COLORS} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("RiskTab", () => {
  it("renders loading then calls /portfolio/analysis with weights and renders KPI tiles plus charts", async () => {
    mocked.postPortfolioAnalysis.mockResolvedValue(makeAnalysis());
    renderTab(makeResult([SPY_WEIGHT, QQQ_WEIGHT_FROM_ASSET]));

    expect(screen.getByLabelText("Analyzing portfolio risk")).toBeInTheDocument();
    await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1));
    expect(mocked.postPortfolioAnalysis).toHaveBeenCalledWith({
      positions: [
        { ticker: "SPY", weight: 0.6 },
        { ticker: "QQQ", weight: 0.4 },
      ],
      mode: "weights",
      benchmark: "SPY",
      range: "1Y",
    });

    expect(await screen.findByText("Sharpe")).toBeInTheDocument();
    expect(screen.getByText("Beta (SPY)")).toBeInTheDocument();
    expect(screen.getAllByTestId("highcharts-chart")).toHaveLength(3);
  });

  it("shows the verbatim 422 detail and retries the same request", async () => {
    const user = userEvent.setup();
    mocked.postPortfolioAnalysis
      .mockRejectedValueOnce(new client.ApiError(422, "ticker SPY has no priced history"))
      .mockResolvedValueOnce(makeAnalysis());

    renderTab(makeResult([SPY_WEIGHT, QQQ_WEIGHT_FROM_ASSET]));

    expect(
      await screen.findByText("ticker SPY has no priced history"),
    ).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Retry" }));

    await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(2));
    expect(mocked.postPortfolioAnalysis).toHaveBeenNthCalledWith(2, {
      positions: [
        { ticker: "SPY", weight: 0.6 },
        { ticker: "QQQ", weight: 0.4 },
      ],
      mode: "weights",
      benchmark: "SPY",
      range: "1Y",
    });
  });

  it("fails loud without calling the API when a weight has no resolvable ticker", async () => {
    renderTab(makeResult([SPY_WEIGHT, FUND_NO_TICKER]));

    expect(
      await screen.findByText("Could not resolve a ticker for 1 position."),
    ).toBeInTheDocument();
    expect(mocked.postPortfolioAnalysis).not.toHaveBeenCalled();
  });

  it("uses assetsByKey to resolve a manually selected fund ticker", async () => {
    mocked.postPortfolioAnalysis.mockResolvedValue(makeAnalysis());
    renderTab(
      makeResult([SPY_WEIGHT, FUND_NO_TICKER]),
      new Map([
        [
          "fund:uuid-1",
          { kind: "fund", id: "uuid-1", ticker: "FNDX", name: "Fund X" },
        ],
      ]),
    );

    await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1));
    expect(mocked.postPortfolioAnalysis).toHaveBeenCalledWith({
      positions: [
        { ticker: "SPY", weight: 0.6 },
        { ticker: "FNDX", weight: 0.4 },
      ],
      mode: "weights",
      benchmark: "SPY",
      range: "1Y",
    });
  });

  it("drops zero weights and renormalizes before calling /portfolio/analysis", async () => {
    mocked.postPortfolioAnalysis.mockResolvedValue(makeAnalysis());
    renderTab(
      makeResult([
        { ...SPY_WEIGHT, weight: 0.3 },
        { ...QQQ_WEIGHT_FROM_ASSET, weight: 0.2 },
        ZERO_WEIGHT,
      ]),
    );

    await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1));
    expect(mocked.postPortfolioAnalysis).toHaveBeenCalledWith({
      positions: [
        { ticker: "SPY", weight: 0.6 },
        { ticker: "QQQ", weight: 0.4 },
      ],
      mode: "weights",
      benchmark: "SPY",
      range: "1Y",
    });
  });

  it("fails loud without calling the API when fewer than two active positions remain", async () => {
    renderTab(makeResult([SPY_WEIGHT, ZERO_WEIGHT]));

    expect(
      await screen.findByText(
        "At least two active positions above the weight floor are required.",
      ),
    ).toBeInTheDocument();
    expect(mocked.postPortfolioAnalysis).not.toHaveBeenCalled();
  });

  it("fires the analysis exactly once across rerenders", async () => {
    mocked.postPortfolioAnalysis.mockResolvedValue(makeAnalysis());
    const result = makeResult([SPY_WEIGHT, QQQ_WEIGHT_FROM_ASSET]);
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
    });
    const view = render(
      <QueryClientProvider client={queryClient}>
        <RiskTab result={result} assetsByKey={new Map()} colors={TEST_COLORS} />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1));
    view.rerender(
      <QueryClientProvider client={queryClient}>
        <RiskTab result={result} assetsByKey={new Map()} colors={TEST_COLORS} />
      </QueryClientProvider>,
    );

    await new Promise((resolve) => setTimeout(resolve, 0));
    expect(mocked.postPortfolioAnalysis).toHaveBeenCalledTimes(1);
  });
});
