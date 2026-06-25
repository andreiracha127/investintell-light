"""Return-convention conversion for PERFORMANCE consumers (Bug 1 + Bug 2 guard).

`nav_timeseries.return_1d` is a LOG return for ~99.8% of rows (return_type='log')
and arithmetic for a small proxy-ETF minority (return_type='arithmetic'). The
backtest / projection / Monte-Carlo curves compound returns as SIMPLE
(prod(1+r)); feeding them log returns is wrong (catastrophically so on a glitch).

This helper converts to SIMPLE honoring the per-element convention, and zeroes
residual log glitches above GLITCH_LOG_THRESHOLD as a safety net for any print
the source cleanup has not yet reprocessed. The COVARIANCE/risk path keeps log
and does NOT use this helper.

Pure; no I/O. Scale contract: inputs and outputs are decimal fractions.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

#: |log return| above this is treated as a residual glitch and zeroed (matches
#: backend/scripts/local_fund_backtest.py --logfix).
GLITCH_LOG_THRESHOLD: float = 0.40


def to_simple_returns(
    values: pd.Series | np.ndarray,
    return_types: Sequence[str] | np.ndarray | None = None,
    *,
    glitch_threshold: float = GLITCH_LOG_THRESHOLD,
) -> pd.Series | np.ndarray:
    """Convert returns to SIMPLE honoring per-element convention, with a glitch guard.

    For ``"log"`` entries: zero where ``|value| > glitch_threshold`` (Bug 2 net),
    then ``expm1`` (log->simple). For ``"arithmetic"`` entries: identity (already
    simple). ``return_types=None`` treats every element as ``"log"`` (the fund
    default). NaN propagates positionally. A ``pd.Series`` keeps its index.
    """
    index: pd.Index | None = None
    if isinstance(values, pd.Series):
        index = values.index
    arr = np.asarray(values, dtype=float)

    if return_types is None:
        log_mask = np.ones(arr.shape, dtype=bool)
    else:
        types = np.asarray(return_types, dtype=object)
        if types.shape != arr.shape:
            raise ValueError(
                f"return_types shape {types.shape} != values shape {arr.shape}"
            )
        log_mask = types == "log"

    out = arr.copy()
    glitch = log_mask & (np.abs(arr) > glitch_threshold)
    out[glitch] = 0.0
    out[log_mask] = np.expm1(out[log_mask])
    # arithmetic entries are left as-is (already simple).

    if index is not None:
        return pd.Series(out, index=index)
    return out
