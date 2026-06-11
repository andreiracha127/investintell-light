"""Return-distribution summaries.

Scale contract (project-wide): all fractional quantities (returns, bin
edges) are decimal fractions (0.05 = 5%), never 0-100.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics._validation import reject_nan

_MIN_RETURNS = 10
_MAX_BINS = 100


@dataclass(frozen=True)
class Histogram:
    """Histogram of a return series.

    ``bin_edges`` has ``len(counts) + 1`` entries, in decimal-fraction return
    units (0.05 = 5%). ``counts_normalized`` is each count divided by the
    maximum count (0-1), so the frontend can render bar heights without the
    backend dictating pixels.
    """

    bin_edges: list[float]
    counts: list[int]
    counts_normalized: list[float]


def return_histogram(returns: pd.Series, bins: int = 20) -> Histogram:
    """Histogram of a return series via ``numpy.histogram``.

    Returns are decimal fractions (0.05 = 5%), never 0-100. ``bins`` is
    bounded to [1, 100].

    Raises:
        ValueError: if ``bins`` is out of bounds, fewer than 10 returns are
            supplied, or the input contains NaN values.
    """
    if not 1 <= bins <= _MAX_BINS:
        raise ValueError(f"bins must be between 1 and {_MAX_BINS}, got {bins}")
    if len(returns) < _MIN_RETURNS:
        raise ValueError(
            f"return_histogram requires at least {_MIN_RETURNS} returns, got {len(returns)}"
        )
    reject_nan(returns, "return_histogram")
    values = returns.to_numpy(dtype=float)
    counts, edges = np.histogram(values, bins=bins)
    max_count = int(counts.max())
    if max_count == 0:  # unreachable with >= 10 finite returns, guard anyway
        raise ValueError("return_histogram produced no counts")
    return Histogram(
        bin_edges=[float(e) for e in edges],
        counts=[int(c) for c in counts],
        counts_normalized=[float(c) / max_count for c in counts],
    )
