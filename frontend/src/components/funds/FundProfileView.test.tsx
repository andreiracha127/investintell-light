// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

vi.mock("@/components/charts/InteractiveChart", () => ({
  InteractiveChart: ({ range }: { range: string }) => (
    <div data-testid="interactive-chart">{range}</div>
  ),
}));

vi.mock("@/components/charts/HighchartsChart", () => ({
  HighchartsChart: () => <div data-testid="highcharts-chart" />,
}));

vi.mock("@/components/funds/FundLookthroughSection", () => ({
  FundLookthroughSection: () => <div data-testid="lookthrough-section" />,
}));

vi.mock("@/lib/charts/chartColors", () => ({
  chartColors: () => ({
    gain: "#198038",
    loss: "#da1e28",
    accent: "#8a1538",
    accentMuted: "#b36b7d",
    accentWash: "#f7e7ec",
    textOnAccent: "#ffffff",
    text: "#161616",
    textSecondary: "#525252",
    textMuted: "#6f6f6f",
    grid: "#e0e0e0",
    surface: "#ffffff",
    bar: "#393939",
    barMute: "#8d8d8d",
    categories: [
      "#6929c4",
      "#1192e8",
      "#005d5d",
      "#9f1853",
      "#fa4d56",
      "#570408",
      "#198038",
      "#002d9c",
    ],
  }),
}));

vi.mock("@/lib/api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api/client")>();
  return {
    ...actual,
    fetchFundActiveShare: vi.fn(),
    fetchFundAnalysis: vi.fn(),
    fetchFundEntityAnalytics: vi.fn(),
    fetchFundFactors: vi.fn(),
    fetchFundHoldingsTop: vi.fn(),
    fetchFundInstitutionalReveal: vi.fn(),
    fetchFundPeers: vi.fn(),
    fetchFundProfile: vi.fn(),
    fetchFundRiskTimeseries: vi.fn(),
    fetchFundStyleDrift: vi.fn(),
    fetchFundTimeseries: vi.fn(),
    fetchHoldingReverseLookup: vi.fn(),
    fetchFundsScatter: vi.fn(),
  };
});

import * as client from "@/lib/api/client";
import { FundProfileView } from "@/components/funds/FundProfileView";

const mocked = vi.mocked(client);

const FUND_ID = "8a2cac81-68df-40dd-b925-0e6350d6a0de";

function makeProfile(): client.FundProfile {
  return {
    instrument_id: FUND_ID,
    series_id: "VFINX-series",
    ticker: "VFINX",
    isin: null,
    cusip: null,
    lei: null,
    name: "Vanguard 500 Index Fund",
    fund_type: "mutual_fund",
    strategy_label: "Large blend",
    asset_class: "equity",
    is_index: true,
    expense_ratio: 0.0001,
    aum_usd: 1_500_000_000_000,
    primary_benchmark: "SPY",
    inception_date: "1976-08-31",
    domicile: "US",
    currency: "USD",
    synced_at: "2026-06-12T00:00:00Z",
    source_calc_date: "2026-06-12",
    source_nav_max_date: "2026-06-12",
    risk: null,
    nav: [],
    holdings: {
      report_date: null,
      items: [],
      pct_of_nav_total: null,
    },
    classes: [],
    classification_note: "Classification note",
  };
}

function makeAnalysis(): client.FundAnalysis {
  return {
    params: {
      range: "1Y",
      window: 252,
      start_date: "2025-06-12",
      end_date: "2026-06-12",
    },
    header: {
      instrument_id: FUND_ID,
      ticker: "VFINX",
      name: "Vanguard 500 Index Fund",
      last_nav: 125,
      prev_nav: 124,
      change: 1,
      change_pct: 0.008,
      as_of: "2026-06-12",
    },
    growth_of_100: [
      ["2025-06-12", 100],
      ["2026-06-12", 125],
    ],
    monthly_returns: [["2026-05-31", 0.01]],
    rolling_volatility: [["2026-06-12", 0.12]],
    rolling_sharpe: [["2026-06-12", 1.1]],
    drawdown: [["2026-06-12", -0.04]],
    histogram: {
      bin_edges: [-0.02, 0, 0.02],
      counts: [3, 5],
      counts_normalized: [0.6, 1],
    },
    stats: {
      annualized_volatility: 0.12,
      var_95: -0.02,
      cvar_95: -0.03,
      total_return: 0.25,
      max_drawdown: {
        depth: -0.08,
        peak_date: "2026-01-01",
        trough_date: "2026-03-01",
      },
      best_day: { date: "2026-01-05", value: 0.02 },
      worst_day: { date: "2026-02-05", value: -0.03 },
    },
  };
}

function makeHoldingsTop(): client.FundHoldingsTop {
  return {
    instrument_id: FUND_ID,
    series_id: "VFINX-series",
    report_date: "2026-03-31",
    top_holdings: [
      {
        rank: 1,
        issuer_name: "Apple Inc.",
        cusip: "037833100",
        isin: null,
        asset_class: "equity",
        sector: "CORP",
        gics_sector: "Information Technology",
        sector_label: "Information Technology",
        market_value: 100,
        pct_of_nav: 7.1,
      },
    ],
    sector_breakdown: [
      {
        key: "tech",
        label: "Information Technology",
        direct_pct: 7.1,
        indirect_pct: 0,
        total_pct: 7.1,
        source: "holdings",
      },
    ],
    pct_of_nav_total: 97.5,
  };
}

function makePeers(): client.FundPeers {
  return {
    instrument_id: FUND_ID,
    cohort_label: "Large blend",
    count: 1,
    classification_note: "Peer classification note",
    items: [
      {
        instrument_id: FUND_ID,
        ticker: "VFINX",
        name: "Vanguard 500 Index Fund",
        strategy_label: "Large blend",
        expense_ratio: 0.0001,
        return_1y: 0.12,
        volatility_1y: 0.11,
        sharpe_1y: 1.1,
        max_drawdown_1y: -0.08,
        cvar_95_12m: -0.03,
        is_target: true,
      },
    ],
  };
}

function makeScatter(): client.FundsScatter {
  return {
    count: 1,
    instrument_ids: [FUND_ID],
    names: ["Vanguard 500 Index Fund"],
    tickers: ["VFINX"],
    expected_returns: [0.12],
    volatilities: [0.11],
    tail_risks: [-0.03],
    strategies: ["Large blend"],
    classification_note: "Scatter classification note",
  };
}

function makeFactors(): client.FundFactors {
  return {
    instrument_id: FUND_ID,
    market_sensitivities: [
      { factor: "Market", beta: 1, t_stat: 3, significance: "***" },
    ],
    style_bias: [
      { factor: "quality", value: 0.7, z_score: 1.2, as_of: "2026-03-31" },
    ],
    source_metadata: [{ source: "factor_model_fits", as_of: "2026-03-31" }],
  };
}

function makeStyleDrift(): client.FundStyleDrift {
  return {
    instrument_id: FUND_ID,
    series_id: "VFINX-series",
    periods: [
      {
        report_date: "2026-03-31",
        quarter: "2026Q1",
        sectors: [{ sector: "Technology", weight: 0.4 }],
      },
    ],
    empty_state: null,
  };
}

function makeRiskTimeseries(): client.FundRiskTimeseries {
  return {
    instrument_id: FUND_ID,
    drawdown: [["2026-06-12", -4]],
    conditional_volatility: [["2026-06-12", 12]],
    volatility_model: "ewma",
    regime_bands: [{ time: "2026-06-12", value: 0, regime: "Expansion" }],
    empty_state: null,
  };
}

function makeEntityAnalytics(): client.FundEntityAnalytics {
  return {
    instrument_id: FUND_ID,
    name: "Vanguard 500 Index Fund",
    as_of_date: "2026-06-12",
    window: "1Y",
    risk_statistics: {
      annualized_return: 0.12,
      annualized_volatility: 0.11,
      sharpe_ratio: 1.1,
      sortino_ratio: 1.3,
      calmar_ratio: 0.8,
      max_drawdown: -0.08,
      alpha: 0.01,
      beta: 1,
      tracking_error: 0.02,
      information_ratio: 0.5,
      n_observations: 252,
    },
    drawdown: {
      dates: ["2026-06-12"],
      values: [-0.04],
      max_drawdown: -0.08,
      current_drawdown: -0.02,
      worst_periods: [
        {
          start_date: "2026-01-01",
          trough_date: "2026-03-01",
          end_date: "2026-05-01",
          depth: -0.08,
          duration_days: 60,
          recovery_days: 61,
        },
      ],
    },
    capture: {
      up_capture: null,
      down_capture: null,
      up_periods: 0,
      down_periods: 0,
      benchmark_id: null,
      benchmark_label: null,
      empty_state: { reason: "benchmark_id is required", source: "request" },
    },
    rolling_returns: { series: { "1M": [["2026-06-12", 0.01]] } },
    distribution: {
      bin_edges: [-0.02, 0, 0.02],
      bin_counts: [3, 5],
      skewness: 0.1,
      kurtosis: 3.1,
      var_95: -0.02,
      cvar_95: -0.03,
    },
    return_statistics: {
      arithmetic_mean_monthly: 0.01,
      geometric_mean_monthly: 0.01,
      avg_monthly_gain: 0.02,
      avg_monthly_loss: -0.01,
      gain_loss_ratio: 2,
      downside_deviation: 0.03,
      semi_deviation: 0.02,
      omega_ratio: 1.2,
      up_percentage_ratio: 0.6,
      down_percentage_ratio: 0.4,
    },
    tail_risk: {
      var_parametric_90: -0.01,
      var_parametric_95: -0.02,
      var_parametric_99: -0.03,
      var_modified_95: -0.025,
      var_modified_99: -0.04,
      etl_95: -0.035,
      starr: 0.8,
      rachev: 1.2,
      jarque_bera: 2,
      jarque_bera_pvalue: 0.3,
    },
    insider_data: {
      issuer_ciks: ["320193"],
      matched_cusips: ["037833100"],
      quarters: [
        {
          quarter: "2026-01-01",
          buy_value: 125,
          sell_value: 80,
          net_value: 45,
          buy_count: 1,
          sell_count: 1,
        },
      ],
      total_buy_value: 125,
      total_sell_value: 80,
      net_value: 45,
      sentiment_score: 0.21,
      source: "sec_insider_sentiment",
      as_of: "2026-01-01",
      empty_state: null,
    },
  };
}

function makeActiveShare(): client.FundActiveShare {
  return {
    instrument_id: FUND_ID,
    benchmark_name: "Vanguard Total Stock Market ETF",
    benchmark_series_id: "S000000999",
    active_share: 0.12,
    overlap: 0.88,
    n_portfolio_positions: 1,
    n_benchmark_positions: 500,
    n_common_positions: 1,
    as_of_date: "2026-03-31",
    empty_state: null,
  };
}

function makeInstitutionalReveal(): client.FundInstitutionalReveal {
  return {
    instrument_id: FUND_ID,
    series_id: "VFINX-series",
    fund_name: "Vanguard 500 Index Fund",
    holdings_report_date: "2026-03-31",
    period: "2026-03-31",
    top_holders: [
      {
        cik: "1067983",
        manager_name: "Berkshire Hathaway",
        value_usd: 123000,
        shares: 4500,
        holding_count: 1,
        period: "2026-03-31",
        report_date: "2026-03-31",
      },
    ],
    overlap: [
      {
        cusip: "037833100",
        name: "Apple Inc.",
        fund_pct_of_nav: 7.1,
        institutional_value_usd: 123000,
        institution_count: 1,
        top_managers: ["Berkshire Hathaway"],
      },
    ],
    holder_network: {
      nodes: [
        { id: `fund:${FUND_ID}`, label: "VFINX", type: "fund", value: null },
        { id: "security:037833100", label: "Apple Inc.", type: "security", value: 123000 },
      ],
      edges: [
        {
          source: `fund:${FUND_ID}`,
          target: "security:037833100",
          weight: 7.1,
          label: "fund holding",
        },
      ],
    },
    empty_state: null,
  };
}

function makeReverseLookup(): client.HoldingReverseLookup {
  return {
    cusip: "037833100",
    security_name: "Apple Inc.",
    period: "2026-03-31",
    institutions: [
      {
        cik: "1067983",
        manager_name: "Berkshire Hathaway",
        value_usd: 123000,
        shares: 4500,
        period: "2026-03-31",
        report_date: "2026-03-31",
      },
    ],
    fund_exposures: [],
    empty_state: null,
  };
}

function mockDossierResponses() {
  mocked.fetchFundProfile.mockResolvedValue(makeProfile());
  mocked.fetchFundTimeseries.mockImplementation(async (instrumentId, range) => ({
    id: instrumentId,
    interval: range === "MAX" ? "monthly" : "daily",
    series: [
      [Date.UTC(2025, 5, 12), 100],
      [Date.UTC(2026, 5, 12), 125],
    ],
  }));
  mocked.fetchFundAnalysis.mockResolvedValue(makeAnalysis());
  mocked.fetchFundHoldingsTop.mockResolvedValue(makeHoldingsTop());
  mocked.fetchFundPeers.mockResolvedValue(makePeers());
  mocked.fetchFundsScatter.mockResolvedValue(makeScatter());
  mocked.fetchFundFactors.mockResolvedValue(makeFactors());
  mocked.fetchFundStyleDrift.mockResolvedValue(makeStyleDrift());
  mocked.fetchFundRiskTimeseries.mockResolvedValue(makeRiskTimeseries());
  mocked.fetchFundEntityAnalytics.mockResolvedValue(makeEntityAnalytics());
  mocked.fetchFundActiveShare.mockResolvedValue(makeActiveShare());
  mocked.fetchFundInstitutionalReveal.mockResolvedValue(makeInstitutionalReveal());
  mocked.fetchHoldingReverseLookup.mockResolvedValue(makeReverseLookup());
}

function renderFundProfile() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <FundProfileView instrumentId={FUND_ID} />
    </QueryClientProvider>,
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FundProfileView", () => {
  it("loads first-paint queries immediately and defers tab/modal queries until opened", async () => {
    mockDossierResponses();
    const user = userEvent.setup();

    renderFundProfile();

    await waitFor(() =>
      expect(mocked.fetchFundTimeseries).toHaveBeenCalledWith(
        FUND_ID,
        "1Y",
        expect.any(AbortSignal),
      ),
    );

    expect(mocked.fetchFundProfile).toHaveBeenCalledWith(
      FUND_ID,
      expect.any(AbortSignal),
    );
    expect(mocked.fetchFundAnalysis).toHaveBeenCalledWith(
      FUND_ID,
      { range: "1Y", window: 252 },
      expect.any(AbortSignal),
    );
    expect(mocked.fetchFundRiskTimeseries).toHaveBeenCalledWith(
      FUND_ID,
      {},
      expect.any(AbortSignal),
    );

    expect(mocked.fetchFundHoldingsTop).not.toHaveBeenCalled();
    expect(mocked.fetchFundPeers).not.toHaveBeenCalled();
    expect(mocked.fetchFundsScatter).not.toHaveBeenCalled();
    expect(mocked.fetchFundFactors).not.toHaveBeenCalled();
    expect(mocked.fetchFundStyleDrift).not.toHaveBeenCalled();
    expect(mocked.fetchFundEntityAnalytics).not.toHaveBeenCalled();
    expect(mocked.fetchFundActiveShare).not.toHaveBeenCalled();
    expect(mocked.fetchFundInstitutionalReveal).not.toHaveBeenCalled();
    expect(mocked.fetchHoldingReverseLookup).not.toHaveBeenCalled();

    expect(await screen.findByText("Vanguard 500 Index Fund")).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Performance" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Holdings" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Style" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Factors" })).toBeInTheDocument();
    expect(screen.getByRole("tab", { name: "Peers" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Relationships" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Deep Analysis" })).toBeInTheDocument();
    expect(screen.getByTestId("interactive-chart")).toHaveTextContent("1Y");

    await user.click(screen.getByRole("tab", { name: "Holdings" }));
    await waitFor(() =>
      expect(mocked.fetchFundHoldingsTop).toHaveBeenCalledWith(
        FUND_ID,
        { limit: 25 },
        expect.any(AbortSignal),
      ),
    );
    expect(mocked.fetchFundActiveShare).toHaveBeenCalledWith(
      FUND_ID,
      expect.any(AbortSignal),
    );
    // A5: active-share never carries benchmark_id (product change, primary benchmark only).
    for (const call of mocked.fetchFundActiveShare.mock.calls) {
      for (const arg of call) {
        expect(arg).not.toMatchObject({ benchmark_id: expect.anything() });
      }
    }
    expect(screen.getAllByText("Information Technology").length).toBeGreaterThan(0);
    expect(screen.queryByText("CORP")).not.toBeInTheDocument();

    await user.click(screen.getByRole("tab", { name: "Style" }));
    await waitFor(() =>
      expect(mocked.fetchFundStyleDrift).toHaveBeenCalledWith(
        FUND_ID,
        { quarters: 40 },
        expect.any(AbortSignal),
      ),
    );

    await user.click(screen.getByRole("tab", { name: "Factors" }));
    await waitFor(() =>
      expect(mocked.fetchFundFactors).toHaveBeenCalledWith(
        FUND_ID,
        expect.any(AbortSignal),
      ),
    );

    await user.click(screen.getByRole("tab", { name: "Peers" }));
    await waitFor(() =>
      expect(mocked.fetchFundPeers).toHaveBeenCalledWith(
        FUND_ID,
        { limit: 10 },
        expect.any(AbortSignal),
      ),
    );
    expect(mocked.fetchFundsScatter).toHaveBeenCalledWith(
      { limit: 250 },
      expect.any(AbortSignal),
    );

    await user.click(screen.getByRole("button", { name: "Deep Analysis" }));
    await waitFor(() =>
      expect(mocked.fetchFundEntityAnalytics).toHaveBeenCalledWith(
        FUND_ID,
        expect.objectContaining({ window: "1Y" }),
        expect.any(AbortSignal),
      ),
    );
    expect(await screen.findByText("Buy value")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Close deep analysis" }));
    await user.click(screen.getByRole("button", { name: "Relationships" }));
    await waitFor(() =>
      expect(mocked.fetchFundInstitutionalReveal).toHaveBeenCalledWith(
        FUND_ID,
        expect.any(AbortSignal),
      ),
    );
    await waitFor(() =>
      expect(mocked.fetchHoldingReverseLookup).toHaveBeenCalledWith(
        "037833100",
        expect.any(AbortSignal),
      ),
    );
  });

  it("auto-resolves the profile benchmark proxy ticker for Deep Analysis", async () => {
    mockDossierResponses();
    const user = userEvent.setup();
    const benchmarkUuid = "11111111-2222-4333-8444-555555555555";
    mocked.fetchFundProfile.mockResolvedValueOnce({
      ...makeProfile(),
      primary_benchmark: "S&P 500",
      benchmark: {
        name: "S&P 500",
        proxy_ticker: "SPY",
        proxy_instrument_id: benchmarkUuid,
        proxy_fit_quality_score: 0.95,
        proxy_asset_class: "equity_us_large",
        resolution_method: "class_name_exact",
        resolution_conflict: false,
        proxy_candidates: ["SPY"],
        canonical_name_matches: ["S&P 500"],
      },
    });

    renderFundProfile();

    expect(await screen.findByText("Vanguard 500 Index Fund")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Deep Analysis" }));

    await waitFor(() =>
      expect(mocked.fetchFundEntityAnalytics).toHaveBeenCalledWith(
        FUND_ID,
        { window: "1Y", benchmark_id: benchmarkUuid },
        expect.any(AbortSignal),
      ),
    );
  });
});
