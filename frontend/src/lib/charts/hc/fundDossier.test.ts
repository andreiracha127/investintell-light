import { describe, expect, it } from "vitest";

import type {
  FundEntityAnalytics,
  FundFactors,
  FundInstitutionalReveal,
  FundPeers,
  FundRiskTimeseries,
  FundStyleDrift,
  FundsScatter,
} from "@/lib/api/client";
import type { ChartColors } from "@/lib/charts/chartColors";
import { dateToUtcMs } from "@/lib/charts/hc/dateAxis";
import {
  buildHcFactorSensitivityOption,
  buildHcFundsScatterOption,
  buildHcInsiderSentimentOption,
  buildHcInstitutionalHolderOption,
  buildHcInstitutionalOverlapOption,
  buildHcPeerBubbleOption,
  buildHcRiskSynchronizedOptions,
  buildHcRiskTimeseriesOption,
  buildHcStyleBiasOption,
  buildHcStyleDriftOption,
  buildHcTailRiskOption,
} from "@/lib/charts/hc/fundDossier";

const colors: ChartColors = {
  gain: "#198038",
  loss: "#da1e28",
  accent: "#8a1538",
  accentMuted: "#b36b7d",
  accentWash: "#f7e7ec",
  textOnAccent: "#fff",
  text: "#111",
  textSecondary: "#555",
  textMuted: "#777",
  grid: "#ddd",
  surface: "#fff",
  bar: "#333",
  barMute: "#999",
  blue: "#0f62fe",
  amber: "#9b6a00",
  categories: ["#111", "#222", "#333", "#444"],
};

function styleDrift(): FundStyleDrift {
  return {
    instrument_id: "fund-id",
    series_id: "S1",
    periods: [
      {
        report_date: "2026-03-31",
        quarter: "2026Q1",
        sectors: [
          { sector: "Technology", weight: 0.4 },
          { sector: "Health Care", weight: 0.2 },
        ],
      },
      {
        report_date: "2026-06-30",
        quarter: "2026Q2",
        sectors: [
          { sector: "Technology", weight: 0.3 },
          { sector: "Financials", weight: 0.25 },
        ],
      },
    ],
    empty_state: null,
  };
}

function factors(): FundFactors {
  return {
    instrument_id: "fund-id",
    market_sensitivities: [
      { factor: "Factor 1", beta: 0.8, t_stat: 2.1, significance: "**" },
      { factor: "Factor 2", beta: -0.2, t_stat: -0.8, significance: null },
    ],
    style_bias: [
      { factor: "momentum", value: 1.2, z_score: 1.4, as_of: "2026-03-31" },
      { factor: "quality", value: 0.7, z_score: -0.5, as_of: "2026-03-31" },
    ],
    source_metadata: [],
  };
}

function riskTimeseries(): FundRiskTimeseries {
  return {
    instrument_id: "fund-id",
    drawdown: [
      ["2026-01-01", 0],
      ["2026-01-02", -5],
    ],
    conditional_volatility: [
      ["2026-01-01", 10],
      ["2026-01-02", 12],
    ],
    benchmark_drawdown: [
      ["2026-01-01", 0],
      ["2026-01-02", -3],
    ],
    benchmark_label: "Benchmark Fund",
    benchmark_empty_state: null,
    volatility_model: "ewma",
    regime_bands: [
      { time: "2026-01-01", value: 0, regime: "Expansion" },
      { time: "2026-01-02", value: 1, regime: "Stress" },
    ],
    empty_state: null,
  };
}

function analytics(): FundEntityAnalytics {
  return {
    instrument_id: "fund-id",
    name: "Fund",
    as_of_date: "2026-06-30",
    window: "1Y",
    risk_statistics: { n_observations: 252 },
    drawdown: {
      dates: [],
      values: [],
      max_drawdown: null,
      current_drawdown: null,
      worst_periods: [],
    },
    capture: { up_periods: 0, down_periods: 0 },
    rolling_returns: { series: { "1M": [], "3M": [], "6M": [], "1Y": [] } },
    distribution: {
      bin_edges: [],
      bin_counts: [],
      skewness: null,
      kurtosis: null,
      var_95: null,
      cvar_95: null,
    },
    return_statistics: {},
    tail_risk: {
      var_parametric_90: 0.01,
      var_parametric_95: 0.02,
      var_parametric_99: 0.03,
      var_modified_95: 0.025,
      var_modified_99: 0.04,
      etl_95: 0.035,
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

function institutionalReveal(): FundInstitutionalReveal {
  return {
    instrument_id: "fund-id",
    series_id: "S1",
    fund_name: "Fund",
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
        name: "APPLE INC",
        fund_pct_of_nav: 7.1,
        institutional_value_usd: 123000,
        institution_count: 1,
        top_managers: ["Berkshire Hathaway"],
      },
    ],
    holder_network: {
      nodes: [
        { id: "fund:fund-id", label: "Fund", type: "fund", value: null },
        { id: "institution:1067983", label: "Berkshire Hathaway", type: "institution", value: 123000 },
      ],
      edges: [],
    },
    empty_state: null,
  };
}

function scatter(): FundsScatter {
  return {
    count: 2,
    instrument_ids: ["fund-id", "peer-id"],
    names: ["Fund", "Peer"],
    tickers: ["FND", null],
    expected_returns: [0.12, 0.08],
    volatilities: [0.18, 0.1],
    tail_risks: [-0.04, -0.03],
    strategies: ["Large blend", "Large blend"],
    classification_note: "Test universe",
  };
}

function peers(): FundPeers {
  return {
    instrument_id: "fund-id",
    cohort_label: "Large blend",
    count: 2,
    classification_note: "Test cohort",
    items: [
      {
        instrument_id: "fund-id",
        ticker: "FND",
        name: "Fund",
        strategy_label: "Large blend",
        expense_ratio: 0.001,
        return_1y: 0.12,
        volatility_1y: 0.18,
        sharpe_1y: 1.1,
        max_drawdown_1y: -0.08,
        cvar_95_12m: -0.04,
        is_target: true,
      },
      {
        instrument_id: "peer-id",
        ticker: "PER",
        name: "Peer",
        strategy_label: "Large blend",
        expense_ratio: 0.002,
        return_1y: -0.04,
        volatility_1y: 0.1,
        sharpe_1y: 0.6,
        max_drawdown_1y: -0.06,
        cvar_95_12m: -0.03,
        is_target: false,
      },
    ],
  };
}

describe("fund dossier Highcharts builders", () => {
  it("builds a stacked style drift area with one series per sector", () => {
    const option = buildHcStyleDriftOption(styleDrift(), colors);

    expect(option.series).toHaveLength(3);
    expect(option.series?.[0]).toMatchObject({
      type: "area",
      name: "Technology",
      data: [
        [dateToUtcMs("2026-03-31"), 0.4],
        [dateToUtcMs("2026-06-30"), 0.3],
      ],
    });
    expect((option.xAxis as { type?: string }).type).toBe("datetime");
  });

  it("builds factor sensitivity and style bias bars with signed colors", () => {
    const sensitivity = buildHcFactorSensitivityOption(factors(), colors);
    const bias = buildHcStyleBiasOption(factors(), colors);

    expect(sensitivity.series?.[0]).toMatchObject({ type: "bar", name: "Beta" });
    expect(bias.series?.[0]).toMatchObject({ type: "bar", name: "Z-score" });
  });

  it("keeps risk timeseries in percent-point units", () => {
    const option = buildHcRiskTimeseriesOption(riskTimeseries(), colors);

    expect(option.series?.[0]).toMatchObject({
      name: "Drawdown",
      data: [
        [dateToUtcMs("2026-01-01"), 0],
        [dateToUtcMs("2026-01-02"), -5],
      ],
    });
    expect(option.series?.[1]).toMatchObject({
      name: "Conditional volatility",
      data: [
        [dateToUtcMs("2026-01-01"), 10],
        [dateToUtcMs("2026-01-02"), 12],
      ],
    });
    expect((option.xAxis as { type?: string }).type).toBe("datetime");
  });

  it("builds synchronized risk panes for volatility, fund drawdown, and benchmark drawdown", () => {
    const panes = buildHcRiskSynchronizedOptions(riskTimeseries(), colors);

    expect(panes).toHaveLength(3);
    expect(panes.map((pane) => pane.id)).toEqual([
      "conditional-volatility",
      "fund-drawdown",
      "benchmark-drawdown",
    ]);
    expect(panes[0].option.series?.[0]).toMatchObject({
      name: "Conditional volatility",
      data: [
        [dateToUtcMs("2026-01-01"), 10],
        [dateToUtcMs("2026-01-02"), 12],
      ],
    });
    expect(panes[2].subtitle).toBe("Benchmark Fund");
    expect(panes[2].option.series?.[0]).toMatchObject({
      name: "Benchmark Fund",
      data: [
        [dateToUtcMs("2026-01-01"), 0],
        [dateToUtcMs("2026-01-02"), -3],
      ],
    });
  });

  it("builds tail risk bars from decimal-fraction backend metrics", () => {
    const option = buildHcTailRiskOption(analytics(), colors);

    expect(option.series?.[0]).toMatchObject({
      type: "bar",
      data: [1, 2, 3, 2.5, 4, 3.5000000000000004],
    });
  });

  it("builds insider sentiment buy/sell/net series", () => {
    const option = buildHcInsiderSentimentOption(analytics(), colors);

    expect(option.series?.[0]).toMatchObject({
      type: "column",
      name: "Buy value",
      data: [125],
    });
    expect(option.series?.[2]).toMatchObject({ type: "line", name: "Net", data: [45] });
  });

  it("builds institutional holder and overlap charts", () => {
    const reveal = institutionalReveal();
    const holders = buildHcInstitutionalHolderOption(reveal, colors);
    const overlap = buildHcInstitutionalOverlapOption(reveal, colors);

    expect(holders.series?.[0]).toMatchObject({
      type: "bar",
      name: "13F value",
    });
    expect(overlap.series?.[0]).toMatchObject({
      type: "column",
      name: "Institutional value",
    });
  });

  it("builds peer scatter points from funds scatter payload arrays", () => {
    const option = buildHcFundsScatterOption(scatter(), colors);

    expect(option.series?.[0]).toMatchObject({
      type: "scatter",
      data: [
        { id: "fund-id", x: 0.18, y: 0.12 },
        { id: "peer-id", x: 0.1, y: 0.08 },
      ],
    });
  });

  it("builds peer bubbles from the same twenty-row peer cohort payload", () => {
    const option = buildHcPeerBubbleOption(peers(), colors);

    expect(option.series?.[0]).toMatchObject({
      type: "bubble",
      data: [
        { id: "fund-id", x: 0.18, y: 1.1, z: 12 },
        { id: "peer-id", x: 0.1, y: 0.6, z: 4 },
      ],
    });
  });
});
