"""Static portfolio analytics: buy-and-hold replay + covariance risk decomposition.

BINDING SEMANTICS — two views, two questions:

1. REPLAY view (:func:`portfolio_nav`, :func:`nav_by_position`,
   :func:`weight_series`, :func:`portfolio_returns`): the Static Portfolio
   Analysis is a buy-and-hold historical replay. Positions are FIXED
   quantities held over the whole window — no rebalancing. When the user
   supplies WEIGHTS instead of quantities, they are converted to synthetic
   quantities at the FIRST date of the window against a notional initial NAV
   (default 10_000.0)::

       quantity_i = weight_i * initial_nav / price_i(first_date)

   Weights therefore drift with prices after day one — that is the honest
   replay (same as Tiingo's scenario semantics). This view answers
   "what would I have had?".

2. DECOMPOSITION view (:func:`risk_contributions`,
   :func:`diversification_ratio`): a covariance-based decomposition computed
   from the SUPPLIED weights (or, for quantity input, from the initial-date
   value weights) held CONSTANT — the standard MCR/CTR convention. This view
   answers "where does my risk come from at these weights?".

The two views intentionally answer different questions: replay weights drift
with prices while the decomposition is evaluated at the stated weights, so
their numbers are not expected to reconcile beyond the first date.

Conventions (project-wide):
- Pure pandas/numpy — no database access, no I/O, no FastAPI.
- All fractional quantities are decimal fractions (0.05 = 5%), never 0-100.
- ``prices`` inputs are date-indexed DataFrames of ADJUSTED closes, one column
  per ticker, already inner-join aligned by the caller. Any NaN, infinite
  value, or fewer than 2 rows raises ``ValueError`` (fail loud, never NaN or
  inf out).
- Long-only by design (F3 scope): every weight and quantity must be > 0.
- Sample statistics use ddof=1, matching the single-asset engine (F2).
"""

import math
from collections.abc import Mapping

import numpy as np
import pandas as pd

from app.analytics._validation import reject_nan, reject_nan_frame
from app.analytics.returns import simple_returns

_WEIGHT_SUM_TOL = 1e-6
_CTR_SUM_TOL = 1e-9
_MIN_CORR_ROWS = 10
# Variance below this is numerical dust, not signal: constant return columns
# yield sample variances around 1e-32 (squared float rounding of the mean),
# while any real return series — even at 1e-8 daily vol — sits at 1e-16 or
# above. Degenerate (zero-risk) portfolios are rejected at this floor.
_VARIANCE_FLOOR = 1e-24

DEFAULT_INITIAL_NAV = 10_000.0


def _validate_price_frame(prices: pd.DataFrame, func_name: str) -> None:
    """Common guard for date-by-ticker price/return frames: no NaN, >= 2 rows."""
    if prices.shape[1] < 1:
        raise ValueError(f"{func_name} requires at least 1 column, got 0")
    if len(prices) < 2:
        raise ValueError(f"{func_name} requires at least 2 rows, got {len(prices)}")
    reject_nan_frame(prices, func_name)


def _validate_keys(
    supplied: Mapping[str, float], columns: list[str], func_name: str, kind: str
) -> None:
    """Require *supplied* keys to exactly match the frame's *columns*."""
    supplied_keys = set(supplied)
    expected = set(columns)
    if supplied_keys != expected:
        missing = sorted(expected - supplied_keys)
        unknown = sorted(supplied_keys - expected)
        raise ValueError(
            f"{func_name} {kind} keys must exactly match the price columns; "
            f"missing={missing}, unknown={unknown}"
        )


def _validate_weights(
    weights: Mapping[str, float], columns: list[str], func_name: str
) -> np.ndarray:
    """Engine hard guard for weights: exact key match, each > 0, sum == 1 ± 1e-6.

    The API layer pre-validates with a looser tolerance and a friendlier
    message; this is the engine's last line of defense. Returns the weight
    vector ordered by *columns*.
    """
    _validate_keys(weights, columns, func_name, "weights")
    for ticker, weight in weights.items():
        if not weight > 0:  # also rejects NaN (NaN > 0 is False)
            raise ValueError(
                f"{func_name} requires long-only weights (> 0); got {ticker}={weight}"
            )
    total = float(sum(weights.values()))
    if abs(total - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"{func_name} weights must sum to 1 within {_WEIGHT_SUM_TOL}, got {total}"
        )
    return np.array([float(weights[c]) for c in columns], dtype=float)


def _validate_quantities(
    quantities: Mapping[str, float], columns: list[str], func_name: str
) -> pd.Series:
    """Quantities must cover exactly the price columns and each be > 0."""
    _validate_keys(quantities, columns, func_name, "quantities")
    for ticker, qty in quantities.items():
        if not qty > 0:  # also rejects NaN
            raise ValueError(
                f"{func_name} requires positive quantities (> 0); got {ticker}={qty}"
            )
    return pd.Series({c: float(quantities[c]) for c in columns}, dtype=float)


def weights_to_quantities(
    prices_first_row: pd.Series,
    weights: Mapping[str, float],
    initial_nav: float = DEFAULT_INITIAL_NAV,
) -> dict[str, float]:
    """Convert target weights into synthetic buy-and-hold quantities.

    Quantities are struck at the FIRST date of the window (see module
    docstring): ``quantity_i = weight_i * initial_nav / price_i(first_date)``.
    By construction the portfolio NAV at the first date equals
    ``initial_nav`` (up to the weight-sum tolerance).

    Raises:
        ValueError: if weight keys do not exactly match the price tickers,
            any weight is <= 0 or NaN, the weights do not sum to 1 within
            1e-6, ``initial_nav`` is not > 0, or any first-date price is
            NaN or <= 0.
    """
    reject_nan(prices_first_row, "weights_to_quantities")
    columns = [str(c) for c in prices_first_row.index]
    weight_vector = _validate_weights(weights, columns, "weights_to_quantities")
    if not initial_nav > 0:  # also rejects NaN
        raise ValueError(f"weights_to_quantities requires initial_nav > 0, got {initial_nav}")
    prices = prices_first_row.to_numpy(dtype=float)
    if not (prices > 0).all():
        raise ValueError(
            "weights_to_quantities requires strictly positive first-date prices"
        )
    quantities = weight_vector * initial_nav / prices
    return {ticker: float(qty) for ticker, qty in zip(columns, quantities, strict=True)}


def nav_by_position(prices: pd.DataFrame, quantities: Mapping[str, float]) -> pd.DataFrame:
    """Per-ticker value series of a buy-and-hold portfolio.

    ``value_i(t) = quantity_i * price_i(t)`` — the building block for the
    stacked-area composition chart (F5).

    Raises:
        ValueError: if the price frame has NaN or fewer than 2 rows, or the
            quantities do not exactly cover the price columns with values > 0.
    """
    _validate_price_frame(prices, "nav_by_position")
    columns = [str(c) for c in prices.columns]
    qty = _validate_quantities(quantities, columns, "nav_by_position")
    return prices.mul(qty, axis=1)


def portfolio_nav(prices: pd.DataFrame, quantities: Mapping[str, float]) -> pd.Series:
    """Date-indexed NAV of a buy-and-hold portfolio: ``NAV(t) = Σ qty_i * price_i(t)``.

    Raises:
        ValueError: same conditions as :func:`nav_by_position`.
    """
    nav = nav_by_position(prices, quantities).sum(axis=1)
    nav.name = "nav"
    return nav


def weight_series(prices: pd.DataFrame, quantities: Mapping[str, float]) -> pd.DataFrame:
    """Per-ticker weight evolution of a buy-and-hold portfolio.

    Each row sums to 1 (decimal fractions). This is where the weight drift of
    the replay view is visible: weights move with prices after day one.

    Raises:
        ValueError: same conditions as :func:`nav_by_position`.
    """
    values = nav_by_position(prices, quantities)
    return values.div(values.sum(axis=1), axis=0)


def portfolio_returns(prices: pd.DataFrame, quantities: Mapping[str, float]) -> pd.Series:
    """Simple period returns of the buy-and-hold portfolio NAV.

    Feeds the F2 single-asset statistics (volatility, VaR, drawdown, ...)
    unchanged — a 1-asset portfolio must reproduce the single-asset numbers
    (the F3 consistency gate).

    Raises:
        ValueError: same conditions as :func:`nav_by_position`.
    """
    return simple_returns(portfolio_nav(prices, quantities))


def asset_returns_frame(prices: pd.DataFrame) -> pd.DataFrame:
    """Per-ticker simple returns: ``prices.pct_change().dropna()``.

    Input frame for :func:`correlation_matrix`, :func:`risk_contributions`
    and :func:`diversification_ratio`.

    Raises:
        ValueError: if the price frame has NaN or fewer than 2 rows.
    """
    _validate_price_frame(prices, "asset_returns_frame")
    return prices.pct_change().dropna()


def correlation_matrix(returns: pd.DataFrame) -> pd.DataFrame:
    """Pairwise Pearson correlation matrix of a per-ticker returns frame.

    The diagonal is set to exactly 1.0 (float noise from the covariance path
    is clipped away). Symmetric by construction.

    Raises:
        ValueError: if the frame has NaN, fewer than 10 rows, or any column
            has zero variance (correlation undefined).
    """
    if len(returns) < _MIN_CORR_ROWS:
        raise ValueError(
            f"correlation_matrix requires at least {_MIN_CORR_ROWS} rows, got {len(returns)}"
        )
    reject_nan_frame(returns, "correlation_matrix")
    corr = returns.corr(method="pearson")
    if bool(corr.isna().any().any()):
        raise ValueError(
            "correlation_matrix is undefined: a column has zero variance"
        )
    matrix = corr.to_numpy(dtype=float, copy=True)
    np.fill_diagonal(matrix, 1.0)
    return pd.DataFrame(matrix, index=corr.index, columns=corr.columns)


def risk_contributions(
    returns: pd.DataFrame, weights: Mapping[str, float]
) -> dict[str, float]:
    """Covariance-based risk contributions at the stated weights (CTR convention).

    DECOMPOSITION view (see module docstring): with ``Σ = returns.cov()``
    (ddof=1) and portfolio variance ``σ²_p = wᵀΣw``, the contribution of
    asset *i* to total risk is ``CTR_i = w_i (Σw)_i / σ²_p``. Annualization
    is unnecessary — the ``periods_per_year`` factor cancels in the ratio.
    The contributions are fractions of TOTAL RISK and sum to 1.0.

    Raises:
        ValueError: if the returns frame has NaN or fewer than 2 rows, the
            weights fail the engine guard (exact keys, each > 0, sum == 1
            within 1e-6), or the portfolio variance is 0 (decomposition
            undefined).
    """
    _validate_price_frame(returns, "risk_contributions")
    columns = [str(c) for c in returns.columns]
    weight_vector = _validate_weights(weights, columns, "risk_contributions")
    cov = returns.cov(ddof=1).to_numpy(dtype=float)
    sigma_w = cov @ weight_vector
    portfolio_variance = float(weight_vector @ sigma_w)
    if portfolio_variance < _VARIANCE_FLOOR:
        raise ValueError(
            "risk_contributions is undefined: portfolio variance is 0"
        )
    contributions = weight_vector * sigma_w / portfolio_variance
    total = float(contributions.sum())
    # Internal invariant: CTRs are an exact algebraic decomposition of σ²_p.
    if abs(total - 1.0) >= _CTR_SUM_TOL:
        raise ValueError(
            f"risk_contributions: contributions sum to {total}, not 1 (numerical instability)"
        )
    return {
        ticker: float(ctr) for ticker, ctr in zip(columns, contributions, strict=True)
    }


def effective_number_of_bets(
    returns: pd.DataFrame, weights: Mapping[str, float]
) -> float:
    """Entropy Effective Number of Bets over the covariance risk contributions.

    Reuses :func:`risk_contributions` (the CTR decomposition that sums to 1) and
    applies the Meucci (2009) entropy diversification measure
    ``ENB = exp(-Sum RC_i ln RC_i)``. Tiny negative CTRs from floating-point
    noise are floored at 0 and the survivors renormalized before the entropy so
    ``ENB`` is bounded in ``[1, n_assets]``: ``n_assets`` when every asset
    contributes equal risk, near 1 when one asset dominates. Unitless.

    Raises:
        ValueError: if the returns frame has NaN or fewer than 2 rows, or the
            weights fail the engine guard (exact keys, each > 0, sum == 1
            within 1e-6) — propagated unchanged from :func:`risk_contributions`;
            also if all risk contributions floor to a non-positive total.
    """
    contributions = risk_contributions(returns, weights)
    rc = np.array(list(contributions.values()), dtype=float)
    rc_pos = np.where(rc > 0.0, rc, 0.0)
    total = float(rc_pos.sum())
    if total <= 0.0:
        raise ValueError(
            "effective_number_of_bets is undefined: non-positive risk contributions"
        )
    rc_norm = rc_pos / total
    # log(0) is guarded by the rc_norm>0 mask: zero-contribution terms add 0
    # (lim p->0 of p ln p = 0), so restrict the entropy sum to positives.
    mask = rc_norm > 0.0
    entropy = -float(np.sum(rc_norm[mask] * np.log(rc_norm[mask])))
    return float(np.exp(entropy))


def diversification_ratio(returns: pd.DataFrame, weights: Mapping[str, float]) -> float:
    """Diversification ratio at the stated weights: ``(Σ w_i σ_i) / σ_p``.

    DECOMPOSITION view (see module docstring). Conventionally stated with
    annualized volatilities, but the ``sqrt(periods_per_year)`` factor cancels
    between numerator and denominator, so raw sample stds (ddof=1) give the
    identical result. For a long-only portfolio the ratio is >= 1 (equality
    iff all assets are perfectly correlated).

    Raises:
        ValueError: if the returns frame has NaN or fewer than 2 rows, the
            weights fail the engine guard, or the portfolio volatility is 0
            (ratio undefined).
    """
    _validate_price_frame(returns, "diversification_ratio")
    columns = [str(c) for c in returns.columns]
    weight_vector = _validate_weights(weights, columns, "diversification_ratio")
    stds = returns.std(ddof=1).to_numpy(dtype=float)
    cov = returns.cov(ddof=1).to_numpy(dtype=float)
    portfolio_variance = float(weight_vector @ cov @ weight_vector)
    if portfolio_variance < _VARIANCE_FLOOR:
        raise ValueError(
            "diversification_ratio is undefined: portfolio volatility is 0"
        )
    return float(weight_vector @ stds) / math.sqrt(portfolio_variance)
