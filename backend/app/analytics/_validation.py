"""Shared input-validation helpers for analytics scalar functions.

All public analytics functions that produce a single scalar (or a dataclass
wrapping scalars) must call :func:`reject_nan` before touching the data so
that NaN propagation is caught up-front rather than silently in the middle of
a computation.
"""

import math

import pandas as pd


def reject_nan(series: pd.Series, func_name: str) -> None:
    """Raise ``ValueError`` if *series* contains any NaN values.

    Args:
        series: The input pandas Series to validate.
        func_name: Name of the calling function, used in the error message.

    Raises:
        ValueError: if *series* contains one or more NaN values.
    """
    if series.isna().any():
        raise ValueError(
            f"{func_name} received NaN values in input; clean the series first"
        )


def reject_nan_float(value: float, func_name: str) -> None:
    """Raise ``ValueError`` if *value* is NaN.

    Used as a post-computation safety net where an up-front :func:`reject_nan`
    call is not sufficient (e.g. division by zero can still produce NaN).
    """
    if math.isnan(value):
        raise ValueError(f"{func_name} produced a NaN result")
