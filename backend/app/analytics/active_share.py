"""Active Share over look-through weights vs a benchmark.

Active Share (Cremers & Petajisto 2009; eVestment p.73, ported from
quant_engine.active_share_service) measures how much a portfolio's holdings
differ from a benchmark's:

    active_share = 0.5 * sum(|w_portfolio,i - w_benchmark,i|)  over the union
                   of position identifiers.

Scale contract (project-wide): both weight maps are decimal fractions
(0.5 = 50%), and the RESULT is a decimal fraction in [0, 1] (1.0 = 100% active,
no overlap with the benchmark) — NOT the 0-100 scale of the legacy
quant_engine.active_share_service (which multiplies by 100). Both maps must
already be normalized to sum to 1 within tolerance; this function fails loud
rather than silently rescaling.
"""

import math
from collections.abc import Mapping

# Matches the legacy active_share_service._WEIGHT_SUM_TOL (= 0.05): look-through
# weights rarely sum to exactly 1, so a 5% tolerance is permitted before failing.
_WEIGHT_SUM_TOL = 0.05


def _check_weights(weights: Mapping[str, float], name: str) -> None:
    if not weights:
        raise ValueError(
            f"active_share requires at least one {name} position (got empty)"
        )
    for ticker, weight in weights.items():
        if not math.isfinite(weight):
            raise ValueError(
                f"active_share {name} weights must be finite; {ticker}={weight}"
            )
    total = float(sum(weights.values()))
    if abs(total - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"active_share {name} weights must sum to 1 within {_WEIGHT_SUM_TOL}, got {total}"
        )


def active_share(
    portfolio_weights: Mapping[str, float],
    benchmark_weights: Mapping[str, float],
) -> float:
    """Active Share of look-through weights against a benchmark.

    ``active_share = 0.5 * Sum|w_p,i - w_b,i|`` over the union of identifiers, in
    decimal fractions (0.0 = identical to benchmark, 1.0 = fully active). Both
    inputs are decimal-fraction weight maps that must each sum to 1 within 0.05.

    Raises:
        ValueError: if either map is empty, any weight is NaN/inf, or either
            map's weights do not sum to 1 within tolerance.
    """
    _check_weights(portfolio_weights, "portfolio")
    _check_weights(benchmark_weights, "benchmark")
    all_ids = set(portfolio_weights) | set(benchmark_weights)
    total_diff = 0.0
    for identifier in all_ids:
        w_p = float(portfolio_weights.get(identifier, 0.0))
        w_b = float(benchmark_weights.get(identifier, 0.0))
        total_diff += abs(w_p - w_b)
    result = total_diff / 2.0
    # Clamp residual float noise into [0, 1] (the math already guarantees it,
    # but a defensive clamp keeps the contract exact).
    return min(max(result, 0.0), 1.0)
