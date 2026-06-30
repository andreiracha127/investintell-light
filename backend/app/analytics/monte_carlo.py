"""Block-bootstrap Monte Carlo projections over a daily-return array.

Pure numpy — no I/O, no DB, no FastAPI. Uses block bootstrap (21 trading-day
blocks) to preserve autocorrelation; does NOT assume a normal distribution.
Ported from the legacy quant_engine.monte_carlo_service.

Scale contract (project-wide): drawdown and return statistics are decimal
fractions (0.05 = 5%), never 0-100; Sharpe is unitless. The only RNG is
``numpy.random.default_rng``.

Return scaling differs between the headline distribution and the per-horizon
fan: ``percentiles``/``mean``/``median``/``historical_value`` annualize to a
CAGR (horizons are comparable on a like-for-like rate basis), while
``confidence_bars`` reports the *cumulative* total return per horizon so the
projection fan widens with time the way a "range of outcomes" chart should —
annualized-rate estimates get *less* noisy over a longer horizon, which reads
as a misleadingly narrowing band. max_drawdown and sharpe are unaffected by
this distinction (drawdown is already a path extremum that widens with
horizon; Sharpe has no cumulative analogue, so it stays annualized everywhere
and its per-horizon band narrows by design — a longer track record makes the
risk-adjusted-return estimate more reliable, not less).

Fail-loud (LIGHT contract): the two hard input guards (too little history,
history too short for the requested horizon) raise ``ValueError`` — the route
maps these to HTTP 422. The ``degraded`` flag is reserved for the SOFT case of
a flat-NAV Sharpe collapse, which is a property of valid data rather than a
missing input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 1Y, 3Y, 5Y, 7Y, 10Y in trading days (the legacy default horizons).
DEFAULT_HORIZONS: list[int] = [252, 756, 1260, 1764, 2520]

_BLOCK_SIZE = 21
_MIN_HISTORY = 42
_ZERO_VARIANCE_MASS_THRESHOLD = 0.5
_PCTL_KEYS = ["1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
_PCTL_VALS = [1, 5, 10, 25, 50, 75, 90, 95, 99]


@dataclass(frozen=True)
class MonteCarloAnalytics:
    """Bootstrapped Monte Carlo simulation result for one statistic."""

    n_simulations: int
    statistic: str  # "max_drawdown" | "return" | "sharpe"
    percentiles: dict[str, float] = field(default_factory=dict)
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    historical_value: float = 0.0
    historical_horizon_days: int = 0
    historical_percentile_rank: float | None = None
    confidence_bars: tuple[dict[str, object], ...] = ()
    degraded: bool = False
    degraded_reason: str | None = None


def _block_bootstrap_paths(
    daily_returns: np.ndarray[Any, Any],
    n_simulations: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray[Any, Any]:
    """(n_simulations, horizon) array of simulated daily returns via block bootstrap."""
    n = len(daily_returns)
    n_blocks = (horizon + _BLOCK_SIZE - 1) // _BLOCK_SIZE
    starts = rng.integers(0, n - _BLOCK_SIZE + 1, size=(n_simulations, n_blocks))
    block_offsets = np.arange(_BLOCK_SIZE)
    idx = starts[:, :, None] + block_offsets[None, None, :]
    paths = daily_returns[idx].reshape(n_simulations, n_blocks * _BLOCK_SIZE)
    return np.asarray(paths[:, :horizon])


def _compute_statistic(
    simulated_returns: np.ndarray[Any, Any],
    statistic: str,
    risk_free_rate: float,
    *,
    annualize_return: bool = True,
) -> tuple[np.ndarray[Any, Any], int]:
    """Per-path statistic + zero-variance count (only meaningful for sharpe).

    ``annualize_return`` only affects ``statistic == "return"``: the headline
    distribution (mean/median/percentiles/historical rank) annualizes to a
    CAGR so horizons are comparable on a like-for-like basis. The per-horizon
    confidence fan instead wants the *cumulative* total return so the band
    widens with the horizon (compounding uncertainty grows with time, even
    though the annualized-rate estimate gets less noisy) — callers building
    that fan pass ``annualize_return=False``.
    """
    n_sims = simulated_returns.shape[0]
    zero_var_count = 0

    if statistic == "max_drawdown":
        nav = np.empty((n_sims, simulated_returns.shape[1] + 1))
        nav[:, 0] = 1.0
        nav[:, 1:] = np.cumprod(1 + simulated_returns, axis=1)
        running_max = np.maximum.accumulate(nav, axis=1)
        drawdown = (nav - running_max) / np.where(running_max > 0, running_max, 1.0)
        results = np.min(drawdown, axis=1)

    elif statistic == "return":
        h = simulated_returns.shape[1]
        total = np.prod(1 + simulated_returns, axis=1) - 1.0
        results = (1.0 + total) ** (252.0 / h) - 1.0 if annualize_return else total

    elif statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        excess = simulated_returns - rf_daily
        mean_excess = np.mean(excess, axis=1)
        std_excess = np.std(excess, axis=1, ddof=1)
        nonzero = std_excess > 1e-12
        results = np.where(
            nonzero,
            mean_excess / np.where(nonzero, std_excess, 1.0) * np.sqrt(252),
            0.0,
        )
        zero_var_count = int((~nonzero).sum())

    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    return results, zero_var_count


def _historical_statistic(
    daily_returns: np.ndarray[Any, Any],
    statistic: str,
    risk_free_rate: float,
) -> float:
    """The statistic computed on the ACTUAL historical series."""
    if statistic == "max_drawdown":
        nav = np.insert(np.cumprod(1 + daily_returns), 0, 1.0)
        running_max = np.maximum.accumulate(nav)
        drawdown = (nav - running_max) / np.where(running_max > 0, running_max, 1.0)
        return float(np.min(drawdown))

    if statistic == "return":
        total = float(np.prod(1 + daily_returns) - 1)
        h = len(daily_returns)
        return float((1.0 + total) ** (252.0 / h) - 1.0)

    if statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        excess = daily_returns - rf_daily
        mean_e = np.mean(excess)
        std_e = np.std(excess, ddof=1)
        if std_e > 1e-12:
            return float(mean_e / std_e * np.sqrt(252))
        return 0.0

    raise ValueError(f"Unknown statistic: {statistic}")


def block_bootstrap_monte_carlo(
    daily_returns: np.ndarray[Any, Any],
    n_simulations: int = 10_000,
    horizons: list[int] | None = None,
    statistic: str = "max_drawdown",
    risk_free_rate: float = 0.04,
    seed: int | None = None,
) -> MonteCarloAnalytics:
    """Bootstrapped Monte Carlo preserving skewness/kurtosis (21-day blocks).

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns (decimal fractions).
    n_simulations : int
        Number of bootstrap paths (default 10,000).
    horizons : list[int] | None
        Trading-day horizons for the confidence fan (default ``DEFAULT_HORIZONS``).
    statistic : str
        "max_drawdown" | "return" | "sharpe".
    risk_free_rate : float
        Annualized risk-free rate for the Sharpe statistic.
    seed : int | None
        Seed for ``numpy.random.default_rng`` (reproducibility).

    Raises
    ------
    ValueError
        If ``statistic`` is unknown, fewer than 42 returns are supplied, or the
        history is too short for the requested horizon (need
        ``T >= min(0.1 * max_horizon, 252)`` for a non-degenerate block bootstrap).
    """
    daily_returns = np.asarray(daily_returns, dtype=float)
    n = len(daily_returns)

    # Validate the statistic up-front so a bad name fails before the history guard.
    if statistic not in ("max_drawdown", "return", "sharpe"):
        raise ValueError(f"Unknown statistic: {statistic}")

    if n < _MIN_HISTORY:
        raise ValueError(
            f"insufficient_history: T={n} daily returns (min {_MIN_HISTORY})"
        )

    if horizons is None:
        horizons = DEFAULT_HORIZONS

    max_horizon = max(horizons)
    min_t_required = min(int(max_horizon * 0.1), 252)
    if n < min_t_required:
        raise ValueError(
            f"insufficient_history_for_horizon: T={n}, max_horizon={max_horizon}; "
            f"need T >= {min_t_required} (10% of horizon, capped at 252) "
            f"for a non-degenerate block bootstrap"
        )

    rng = np.random.default_rng(seed)

    primary_horizon = max(horizons)
    paths = _block_bootstrap_paths(daily_returns, n_simulations, primary_horizon, rng)
    sim_stats, primary_zero_var_count = _compute_statistic(
        paths, statistic, risk_free_rate
    )

    percentiles = {
        k: round(float(np.percentile(sim_stats, p)), 8)
        for k, p in zip(_PCTL_KEYS, _PCTL_VALS, strict=True)
    }

    hist_value = _historical_statistic(daily_returns, statistic, risk_free_rate)
    historical_percentile_rank: float | None = None
    if statistic in ("max_drawdown", "return"):
        matched_paths = _block_bootstrap_paths(daily_returns, n_simulations, n, rng)
        matched_stats, _ = _compute_statistic(matched_paths, statistic, risk_free_rate)
        historical_percentile_rank = round(
            float(np.mean(matched_stats < hist_value) * 100.0), 4
        )

    confidence_bars: list[dict[str, object]] = []
    for h in horizons:
        h_stats, _ = _compute_statistic(
            paths[:, :h], statistic, risk_free_rate, annualize_return=False
        )
        label = f"{h // 252}Y" if h >= 252 else f"{h}D"
        confidence_bars.append(
            {
                "horizon": label,
                "horizon_days": h,
                "pct_5": round(float(np.percentile(h_stats, 5)), 8),
                "pct_10": round(float(np.percentile(h_stats, 10)), 8),
                "pct_25": round(float(np.percentile(h_stats, 25)), 8),
                "pct_50": round(float(np.percentile(h_stats, 50)), 8),
                "pct_75": round(float(np.percentile(h_stats, 75)), 8),
                "pct_90": round(float(np.percentile(h_stats, 90)), 8),
                "pct_95": round(float(np.percentile(h_stats, 95)), 8),
                "mean": round(float(np.mean(h_stats)), 8),
            }
        )

    is_mass_zero_var = (
        statistic == "sharpe"
        and n_simulations > 0
        and primary_zero_var_count / n_simulations > _ZERO_VARIANCE_MASS_THRESHOLD
    )

    return MonteCarloAnalytics(
        n_simulations=n_simulations,
        statistic=statistic,
        percentiles=percentiles,
        mean=round(float(np.mean(sim_stats)), 8),
        median=round(float(np.median(sim_stats)), 8),
        std=round(float(np.std(sim_stats, ddof=1)), 8),
        historical_value=round(hist_value, 8),
        historical_horizon_days=n,
        historical_percentile_rank=historical_percentile_rank,
        confidence_bars=tuple(confidence_bars),
        degraded=is_mass_zero_var,
        degraded_reason=(
            f"zero_variance_collapse: {primary_zero_var_count}/{n_simulations} "
            f"paths produced zero-variance Sharpe (threshold "
            f"{_ZERO_VARIANCE_MASS_THRESHOLD:.0%}); input returns may be flat"
        )
        if is_mass_zero_var
        else None,
    )
