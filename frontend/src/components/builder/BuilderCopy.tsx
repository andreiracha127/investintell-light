"use client";

/**
 * Builder presentation copy.
 *
 * The optimizer contract is unchanged: the API still speaks `BuilderObjective`
 * enums (`max_return_cvar`, `bl_utility`, …) and the result payload still keys
 * metrics by their technical names (`cvar_95_in_sample`, `vol_ann`, `n_obs`).
 * Keep this terse: the builder is aimed at users who already understand the
 * workflow and need labels, not a methodology guide.
 */

import type { BuilderObjective } from "@/lib/api/client";

export interface ObjectiveCopy {
  /** Human label shown in the goal dropdown. */
  label: string;
  /** One-line "what it does", shown under the field. */
  description: string;
  /** Technical gloss for the `i` / InfoDot tooltip. */
  tip: string;
  /** Whether the daily-loss-limit (CVaR ceiling) field applies. */
  usesLossLimit: boolean;
}

export const OBJECTIVE_COPY: Record<BuilderObjective, ObjectiveCopy> = {
  max_return_cvar: {
    label: "Most return within a loss limit",
    description: "Return objective with a daily CVaR cap.",
    tip: "Maximize expected return subject to CVaR 95%.",
    usesLossLimit: true,
  },
  min_cvar: {
    label: "Smallest worst-case loss",
    description: "Minimize CVaR 95%.",
    tip: "Minimizes average loss on the worst 5% of days.",
    usesLossLimit: false,
  },
  min_vol: {
    label: "Lowest day-to-day swing",
    description: "Minimum variance.",
    tip: "Uses the Ledoit-Wolf covariance estimate.",
    usesLossLimit: false,
  },
  erc: {
    label: "Risk shared equally",
    description: "Equal risk contribution.",
    tip: "Equal risk contribution (risk parity).",
    usesLossLimit: false,
  },
  max_diversification: {
    label: "Most diversified",
    description: "Maximize diversification ratio.",
    tip: "Weighted asset volatility divided by portfolio volatility.",
    usesLossLimit: false,
  },
  equal_weight: {
    label: "Split evenly",
    description: "Equal weight, then apply caps.",
    tip: "1/N across the universe.",
    usesLossLimit: false,
  },
  bl_utility: {
    label: "Follow my views",
    description: "Black-Litterman utility with views.",
    tip: "Mean-variance utility on the Black-Litterman posterior.",
    usesLossLimit: false,
  },
};

/** Field labels + tooltips for the constraint inputs (plain language). */
export const FIELD_COPY = {
  objective: { label: "Objective" },
  mandate: {
    label: "Mandate",
    tip: "Sets the default daily loss limit.",
  },
  lossLimit: {
    label: "Daily loss limit",
    affix: "%",
    tip: "CVaR 95% ceiling.",
  },
  cap: {
    label: "Max per holding",
    affix: "%",
    tip: "Leave blank for no cap.",
  },
  minWeight: { label: "Min per holding", affix: "%", optional: true },
  window: {
    label: "History window",
    affix: "days",
    tip: "Blank uses all available history.",
  },
} as const;

export interface MetricCopy {
  label: string;
  tip?: string;
  detail?: string;
}

/**
 * Result-metric copy, keyed by a stable code. Feeds the KPI tiles across
 * Allocation / Risk / Backtest / Projection — the values themselves come
 * straight from the unchanged payload.
 */
export const METRIC_COPY: Record<string, MetricCopy> = {
  return_ann_bl: {
    label: "Expected return",
    detail: "per year, estimated",
    tip: "Annualized estimate.",
  },
  vol_ann: {
    label: "Volatility",
    detail: "per year",
    tip: "Annualized standard deviation.",
  },
  cvar_95: {
    label: "Worst-case loss",
    detail: "avg. of worst 5% of days",
    tip: "CVaR 95%.",
  },
  cvar_limit: {
    label: "Loss limit",
    detail: "requested → achieved",
    tip: "Requested vs. achieved CVaR ceiling.",
  },
  n_obs: { label: "Data points", detail: "trading days used" },
  status: { label: "Solver", detail: "solution found" },
  sharpe_ratio: {
    label: "Sharpe",
    tip: "Return per unit of risk.",
  },
  sortino_ratio: {
    label: "Sortino",
    tip: "Downside-risk adjusted return.",
  },
  max_drawdown: {
    label: "Max drawdown",
    tip: "Largest peak-to-trough drop.",
  },
  diversification_ratio: {
    label: "Diversification",
    tip: "Higher is more diversified.",
  },
  information_ratio: {
    label: "Excess vs. market",
    tip: "Risk-adjusted excess return.",
  },
  beta: {
    label: "Market sensitivity",
    tip: "Beta vs. the S&P 500.",
  },
};
