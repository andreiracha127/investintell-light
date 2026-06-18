"use client";

/**
 * Builder — plain-language copy maps (Claude Design upgrade, presentation only).
 *
 * The optimizer contract is unchanged: the API still speaks `BuilderObjective`
 * enums (`max_return_cvar`, `bl_utility`, …) and the result payload still keys
 * metrics by their technical names (`cvar_95_in_sample`, `vol_ann`, `n_obs`).
 * This module is the single seam between those codes and what the user reads,
 * so the catalog stays code-keyed and every screen stays human-readable.
 *
 * Design source: Builder.dc.html + revised/BuilderCopy.tsx.
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
    description:
      "Seeks the highest expected return while keeping the worst-case daily loss under the limit you set. A good default when you care about the downside.",
    tip: "Maximize expected return subject to a daily CVaR-95 ceiling. Uses a Black-Litterman equilibrium return when no views are given (the posterior when they are).",
    usesLossLimit: true,
  },
  min_cvar: {
    label: "Smallest worst-case loss",
    description:
      "Minimizes the average loss on the worst 5% of days, accepting whatever return that implies.",
    tip: "Rockafellar–Uryasev conditional value-at-risk (CVaR 95%) minimization.",
    usesLossLimit: false,
  },
  min_vol: {
    label: "Lowest day-to-day swing",
    description:
      "Minimizes how much the portfolio's value bounces around — the calmest ride, not necessarily the best return.",
    tip: "Minimum-variance under the Ledoit-Wolf shrinkage covariance estimate.",
    usesLossLimit: false,
  },
  erc: {
    label: "Risk shared equally",
    description:
      "Sizes holdings so each contributes the same share of total risk — a balanced, all-weather mix.",
    tip: "Equal risk contribution (risk parity).",
    usesLossLimit: false,
  },
  max_diversification: {
    label: "Most diversified",
    description: "Spreads bets to maximize diversification across holdings.",
    tip: "Maximizes the Choueifaty diversification ratio (weighted asset vols ÷ portfolio vol).",
    usesLossLimit: false,
  },
  equal_weight: {
    label: "Split evenly",
    description:
      "Equal slices across every holding, then trimmed to respect your caps. A simple baseline.",
    tip: "1/N across the universe, then capped and renormalized.",
    usesLossLimit: false,
  },
  bl_utility: {
    label: "Follow my views",
    description:
      "Starts from the market portfolio and tilts toward the views you set in the Advanced section.",
    tip: "Mean-variance utility on the Black-Litterman posterior — needs at least one view to tilt away from market weights.",
    usesLossLimit: false,
  },
};

/** Field labels + tooltips for the constraint inputs (plain language). */
export const FIELD_COPY = {
  objective: { label: "What should the optimizer aim for?" },
  mandate: {
    label: "Risk appetite",
    tip: "Pre-fills a suitable daily loss limit. Conservative caps losses tightly; Growth allows more swing for more return.",
  },
  lossLimit: {
    label: "Daily loss limit",
    affix: "%",
    tip: "Expected shortfall (CVaR 95%): a ceiling on the average loss on the worst 5% of days. Lower = more cautious.",
  },
  cap: {
    label: "Max per holding",
    affix: "%",
    tip: "No single stock or fund may exceed this share of the portfolio. Leave blank for no cap.",
  },
  minWeight: { label: "Min per holding", affix: "%", optional: true },
  window: {
    label: "History window",
    affix: "days",
    tip: "How far back to estimate returns and risk from. Blank uses all available history.",
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
    tip: "Annualized expected return blending the market equilibrium with any views (Black-Litterman).",
  },
  vol_ann: {
    label: "Volatility",
    detail: "per year",
    tip: "Annualized standard deviation — how much the portfolio's value swings.",
  },
  cvar_95: {
    label: "Worst-case loss",
    detail: "avg. of worst 5% of days",
    tip: "Expected shortfall (CVaR 95%): the average daily loss on the worst 5% of days.",
  },
  cvar_limit: {
    label: "Loss limit",
    detail: "requested → achieved",
    tip: "Your requested daily loss ceiling and the tighter level the optimizer actually reached.",
  },
  n_obs: { label: "Data points", detail: "trading days used" },
  status: { label: "Solver", detail: "solution found" },
  sharpe_ratio: {
    label: "Sharpe",
    tip: "Return per unit of total risk. Higher is better; above 1 is strong.",
  },
  sortino_ratio: {
    label: "Sortino",
    tip: "Like Sharpe, but only penalizes downside moves.",
  },
  max_drawdown: {
    label: "Max drawdown",
    tip: "Largest peak-to-trough drop over the period.",
  },
  diversification_ratio: {
    label: "Diversification",
    tip: "How much diversification reduces risk vs. holding the pieces alone. Higher is more diversified.",
  },
  information_ratio: {
    label: "Excess vs. market",
    tip: "Information ratio — risk-adjusted return above the benchmark.",
  },
  beta: {
    label: "Market sensitivity",
    tip: "Beta vs. the S&P 500. 1.0 moves with the market; below 1.0 is calmer.",
  },
};

/** "How it works" methodology side-panel copy. */
export const METHOD_ITEMS: { title: string; body: string }[] = [
  {
    title: "1 · You choose the goal",
    body: "Tell the optimizer what to aim for — most return within a loss limit, the calmest ride, balanced risk, and so on — plus how much daily loss you'll tolerate.",
  },
  {
    title: "2 · It estimates from history",
    body: "Returns, volatility and how holdings move together are estimated from daily prices and fund NAVs, using a Ledoit-Wolf covariance that's steadier than the raw sample.",
  },
  {
    title: "3 · It solves for weights",
    body: "A convex optimizer finds the weights that best meet your goal while respecting every guardrail (caps, minimums, loss limit). 'Optimal' means a valid solution was found.",
  },
  {
    title: "4 · You stress-test it",
    body: "Risk breaks down where the danger sits, Backtest re-runs the strategy on unseen history, and Projection simulates a range of future outcomes. None are guarantees.",
  },
];

export const METHOD_FOOTNOTE =
  "Engine: convex optimization (CVXPY) · Ledoit-Wolf covariance · Black-Litterman views. All figures are estimates from historical data.";
