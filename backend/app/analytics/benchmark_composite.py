"""Composite multi-block benchmark NAV synthesizer.

Ports quant_engine/benchmark_composite_service.compute_composite_nav into the
light analytics idiom. Each block contributes a daily benchmark-return series;
the composite NAV is the weighted-return compounding across blocks.

Pure sync, no I/O, no logging — the legacy structlog telemetry is dropped
(light analytics never log; callers decide on observability).

Algorithm:
    NAV_0 = inception_nav
    R_t   = Σ(w_block × r_block_t)   over blocks present at t (renormalized)
    NAV_t = NAV_{t-1} × (1 + R_t)

Scale contract: block returns are decimal fractions (0.05 = 5%); the NAV is in
currency units.
"""

from collections.abc import Mapping
from typing import cast

import pandas as pd

# Weights below this fraction of total weight on a given day are treated as
# insufficient coverage: the day is skipped rather than forward-fill amplified.
_ACTIVE_WEIGHT_FLOOR = 0.5
_WEIGHT_SUM_TOL = 1e-4
_RENORM_THRESHOLD = 0.999  # below this fraction of weight_sum, renormalize


def composite_benchmark_nav(
    block_weights: Mapping[str, float],
    block_returns: Mapping[str, pd.Series],
    inception_nav: float = 1000.0,
) -> pd.Series:
    """Composite benchmark NAV from block-weighted daily benchmark returns.

    Parameters
    ----------
    block_weights : Mapping[str, float]
        block_id -> target weight; must sum to 1.0 within 1e-4 (a composite
        benchmark is by definition a unit allocation).
    block_returns : Mapping[str, pd.Series]
        block_id -> date-indexed daily benchmark returns (decimal fractions).
    inception_nav : float
        Starting NAV value (default 1000.0, currency units).

    Returns
    -------
    pd.Series
        Composite NAV indexed by date ascending, starting at the latest common
        inception date across all weighted blocks.

    Raises:
        ValueError: if inputs are empty, weights do not sum to 1.0 (within
            1e-4), or a weighted block has no return data.
    """
    if not block_weights or not block_returns:
        raise ValueError("composite_benchmark_nav requires at least one block")

    weight_sum = sum(block_weights.values())
    if abs(weight_sum - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"block_weights must sum to 1.0 (within {_WEIGHT_SUM_TOL}); "
            f"got {weight_sum:.6f}. A composite benchmark is a unit allocation; "
            "caller must normalize or correct the input."
        )

    # Every weighted block must have return data; otherwise the composite is
    # undefined (a fixed-weight composite cannot exist before all constituents).
    block_min_dates: dict[str, pd.Timestamp] = {}
    for block_id in block_weights:
        series = block_returns.get(block_id)
        if series is None or series.dropna().empty:
            raise ValueError(
                f"composite block '{block_id}' has no return data; "
                "composite benchmark is undefined."
            )
        block_min_dates[block_id] = series.dropna().index.min()

    latest_inception = max(block_min_dates.values())

    # Wide frame of block returns, restricted to weighted blocks and dates
    # >= the latest common inception.
    frame = pd.DataFrame({bid: block_returns[bid] for bid in block_weights})
    frame = frame.loc[frame.index >= latest_inception].sort_index()

    navs: list[float] = []
    out_index: list[pd.Timestamp] = []
    current = inception_nav

    for date, row in frame.iterrows():
        composite_return = 0.0
        active_weight = 0.0
        for block_id, w in block_weights.items():
            r = row[block_id]
            if pd.notna(r):
                composite_return += w * float(r)
                active_weight += w

        if active_weight <= 0.0:
            continue

        # Renormalize partial-coverage days; skip days below the active floor.
        if active_weight < weight_sum * _RENORM_THRESHOLD:
            if active_weight < weight_sum * _ACTIVE_WEIGHT_FLOOR:
                continue
            composite_return = composite_return * (weight_sum / active_weight)

        current = current * (1.0 + composite_return)
        navs.append(current)
        out_index.append(cast(pd.Timestamp, date))

    return pd.Series(navs, index=pd.Index(out_index))
