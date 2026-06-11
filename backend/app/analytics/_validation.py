"""Shared input-validation helpers for analytics scalar functions.

All public analytics functions that produce a single scalar (or a dataclass
wrapping scalars) must call :func:`reject_nan` before touching the data so
that NaN or infinite values are caught up-front rather than silently in the
middle of a computation.
"""

import datetime as dt
import math

import numpy as np
import pandas as pd


def to_date(value: object) -> dt.date:
    """Coerce an index label (Timestamp, datetime or date) to a ``date``."""
    if isinstance(value, pd.Timestamp):
        return value.date()
    if isinstance(value, dt.date):
        return value
    return pd.Timestamp(value).date()  # type: ignore[arg-type]


def reject_nan(series: pd.Series, func_name: str) -> None:
    """Raise ``ValueError`` if *series* contains any NaN or infinite values.

    Args:
        series: The input pandas Series to validate.
        func_name: Name of the calling function, used in the error message.

    Raises:
        ValueError: if *series* contains one or more NaN or infinite values.
    """
    numeric = pd.to_numeric(series, errors="coerce")
    if not bool(np.isfinite(numeric).all()):
        raise ValueError(
            f"{func_name} received NaN or infinite values in input; clean the series first"
        )


def reject_nan_frame(frame: pd.DataFrame, func_name: str) -> None:
    """Raise ``ValueError`` if *frame* contains any NaN or infinite values.

    DataFrame counterpart of :func:`reject_nan`, used by the portfolio engine
    where inputs are date-by-ticker matrices.
    """
    numeric = frame.select_dtypes(include="number")
    if not bool(np.isfinite(numeric.to_numpy()).all()):
        raise ValueError(
            f"{func_name} received NaN or infinite values in input; clean the data first"
        )


def reject_nan_float(value: float, func_name: str) -> None:
    """Raise ``ValueError`` if *value* is NaN.

    Used as a post-computation safety net where an up-front :func:`reject_nan`
    call is not sufficient (e.g. division by zero can still produce NaN).
    """
    if math.isnan(value):
        raise ValueError(f"{func_name} produced a NaN result")
