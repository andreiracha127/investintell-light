"""Expense-ratio unit normalisation (ported from legacy expense_ratio_validator).

The fund ``expense_ratio`` arrives in three incompatible shapes depending on
the upstream source:

* **Decimal fraction** (canonical) — e.g. ``0.015`` for 1.5%. XBRL N-CSR OEF
  taxonomy feeds produce this.
* **Whole percent** — e.g. ``1.5`` for 1.5%. Some N-CEN CSV exports / manual
  overrides live here.
* **Basis points** — e.g. ``150`` for 1.5%. Rare bulk adviser filings.

Any consumer that assumes one shape silently explodes on the others (a ``1.5``
percent read as a fraction is a 150% fee). ``to_decimal_fraction`` is the single
entry point: it inspects magnitude, converts to a decimal fraction, clamps into
a sane institutional range, and returns ``None`` when the input cannot be made
sense of. Callers prefer the fraction form and scale to percent/bps at the
presentation layer (project scale contract: fractions, never 0-100).

Pure function — no I/O. Warnings are emitted via stdlib ``logging`` with a
structured ``extra`` payload (the Light app does not use structlog).
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Institutional sanity bounds as a decimal fraction (0.15 = 15%). The highest
# documented institutional fund fee is ~10%; 15% is a conservative upper guard.
MAX_REASONABLE_EXPENSE_RATIO = 0.15  # 15%
MIN_REASONABLE_EXPENSE_RATIO = 0.0   # negative fees would be a bug


def to_decimal_fraction(value: Any) -> float | None:
    """Normalise an expense-ratio value to a decimal fraction.

    Scale detection (in order):

    * ``None`` / non-numeric / ``NaN`` / ``±inf`` -> ``None``.
    * ``abs(value) > 100``  -> basis points, divide by 10 000.
    * ``abs(value) > 0.15`` -> whole percent, divide by 100.
    * otherwise (``[0, 0.15]``) -> already a fraction, keep as-is.

    Inputs in ``(0.15, 1.0]`` are classified as whole percent (the dominant
    N-CEN defect: ``0.5`` meaning 0.5%); this band emits an
    ``expense_ratio_ambiguous_percent_or_fraction`` warning for observability.

    The result is clamped into ``[MIN_REASONABLE_EXPENSE_RATIO,
    MAX_REASONABLE_EXPENSE_RATIO]``; out-of-range inputs are clamped (not
    nullified) and emit a warning, so downstream calculations keep a
    defensible number.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None

    # ── Scale detection ──────────────────────────────────────────────
    abs_v = abs(v)
    if abs_v > 100.0:
        fraction = v / 10_000.0  # basis points → fraction
        source_scale = "bps"
    elif abs_v > MAX_REASONABLE_EXPENSE_RATIO:
        fraction = v / 100.0     # whole percent → fraction
        source_scale = "percent"
        if abs_v <= 1.0:
            logger.warning(
                "expense_ratio_ambiguous_percent_or_fraction",
                extra={
                    "raw": value,
                    "interpreted_as_percent": v,
                    "interpreted_as_fraction": fraction,
                    "note": (
                        "Input in (0.15, 1.0] band — assumed whole percent. "
                        "If source was an XBRL fraction this is a >15% outlier; "
                        "verify upstream source convention."
                    ),
                },
            )
    else:
        fraction = v             # already a fraction
        source_scale = "fraction"

    # ── Clamp to institutional range ─────────────────────────────────
    if fraction < MIN_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_below_zero",
            extra={
                "raw": value,
                "detected_scale": source_scale,
                "clamped_to": MIN_REASONABLE_EXPENSE_RATIO,
            },
        )
        return MIN_REASONABLE_EXPENSE_RATIO
    if fraction > MAX_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_above_max",
            extra={
                "raw": value,
                "detected_scale": source_scale,
                "clamped_to": MAX_REASONABLE_EXPENSE_RATIO,
            },
        )
        return MAX_REASONABLE_EXPENSE_RATIO

    return fraction
