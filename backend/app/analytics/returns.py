"""Return computations on price and return series.

Scale contract (project-wide): all fractional quantities (returns,
cumulative returns, totals) are decimal fractions (0.05 = 5%), never 0-100.
"""

import pandas as pd


def simple_returns(prices: pd.Series) -> pd.Series:
    """Compute simple (arithmetic) period returns from a price series.

    ``prices`` must be a date-indexed series of ADJUSTED closes (adjusting for
    splits/dividends is the caller's responsibility). Returns are decimal
    fractions (0.05 = 5%), never 0-100.

    The first observation is consumed by differencing, so the result has
    ``len(prices) - 1`` rows and no NaNs.

    Raises:
        ValueError: if ``prices`` has fewer than 2 points.
    """
    if len(prices) < 2:
        raise ValueError(f"simple_returns requires at least 2 prices, got {len(prices)}")
    return prices.pct_change().dropna()


def cumulative_return_series(returns: pd.Series) -> pd.Series:
    """Compound a return series into a cumulative-return series.

    Computes ``(1 + r).cumprod() - 1``. Values are decimal fractions
    (0.05 = 5%), never 0-100. The series starts at the first return's date
    (i.e. after the first return has accrued).

    Raises:
        ValueError: if ``returns`` is empty.
    """
    if len(returns) < 1:
        raise ValueError("cumulative_return_series requires at least 1 return, got 0")
    return (1 + returns).cumprod() - 1


def total_return(returns: pd.Series) -> float:
    """Compound a return series into a single total return.

    Computes ``(1 + r).prod() - 1``. Result is a decimal fraction
    (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``returns`` is empty.
    """
    if len(returns) < 1:
        raise ValueError("total_return requires at least 1 return, got 0")
    return float((1 + returns).to_numpy(dtype=float).prod()) - 1.0


def align_returns(a: pd.Series, b: pd.Series) -> tuple[pd.Series, pd.Series]:
    """Align two return series on their common index.

    Inner-joins on the index and drops rows where either side is NaN.
    Used for asset-vs-benchmark statistics. Both series are decimal
    fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if fewer than 2 common non-NaN points remain.
    """
    joined = pd.concat([a, b], axis=1, join="inner", keys=["a", "b"]).dropna()
    if len(joined) < 2:
        raise ValueError(
            f"align_returns requires at least 2 overlapping points, got {len(joined)}"
        )
    return joined["a"], joined["b"]
