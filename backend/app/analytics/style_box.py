"""9-box (size × value/growth) style classification — pure, fail-loud.

Tier 3 (T3B-1). Classifies a fund into one of nine style boxes from two
fund-level characteristics materialized by the datalake characteristics worker
in equity_characteristics_monthly:

  - size_log_mkt_cap : log of the summed equity-sleeve market value
                       (high => large-cap; low => small-cap)
  - book_to_market   : fund-aggregate B/M (high => value; low => growth)

Breakpoints are cross-sectional TERCILES of the as-of cohort (Morningstar-style,
data-driven — no absolute magic cut-points). Tilts are decimal fractions in
[0, 1] (NEVER 0-100). Pure: zero I/O, zero ``app.*`` imports. Fail-loud:
raises ValueError on an undersized cohort or non-finite inputs, never returns
NaN. The 9-box label vocabulary matches the legacy
quant_engine.style_analysis.StyleLabel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

StyleBoxLabel = Literal[
    "small_growth", "small_blend", "small_value",
    "mid_growth", "mid_blend", "mid_value",
    "large_growth", "large_blend", "large_value",
]

_SIZE_BANDS = ("small", "mid", "large")
_VG_BANDS = ("growth", "blend", "value")


@dataclass(frozen=True)
class StyleBoxBreakpoints:
    """Cross-sectional tercile breakpoints for one as-of cohort."""

    size_lo: float
    size_hi: float
    btm_lo: float
    btm_hi: float


@dataclass(frozen=True)
class StyleBox:
    """Result of a single-fund 9-box classification."""

    label: StyleBoxLabel
    size_band: str
    value_growth_band: str
    size_tilt: float       # 0..1 ; >0.5 leans large
    value_tilt: float      # 0..1 ; >0.5 leans value
    confidence: float      # 0..1 ; distance from the nearest breakpoint


def compute_breakpoints(cohort: list[tuple[float, float]]) -> StyleBoxBreakpoints:
    """Tercile (33rd/67th pct) breakpoints from a cohort of (size, btm) pairs.

    ``cohort`` is the cross-section of (size_log_mkt_cap, book_to_market) for
    every fund priced on the same as_of. Requires >= 3 funds so terciles are
    defined; raises ValueError on a non-finite value.
    """
    if len(cohort) < 3:
        raise ValueError("style-box breakpoints require at least 3 funds in the cohort")
    sizes = np.asarray([s for s, _ in cohort], dtype=float)
    btms = np.asarray([b for _, b in cohort], dtype=float)
    if not np.isfinite(sizes).all() or not np.isfinite(btms).all():
        raise ValueError("cohort contains non-finite size or book_to_market values")
    size_lo, size_hi = (float(x) for x in np.percentile(sizes, [33.3333, 66.6667]))
    btm_lo, btm_hi = (float(x) for x in np.percentile(btms, [33.3333, 66.6667]))
    return StyleBoxBreakpoints(
        size_lo=size_lo, size_hi=size_hi, btm_lo=btm_lo, btm_hi=btm_hi
    )


def _band(value: float, lo: float, hi: float, names: tuple[str, str, str]) -> str:
    if value <= lo:
        return names[0]
    if value >= hi:
        return names[2]
    return names[1]


def _axis_tilt(value: float, lo: float, hi: float) -> float:
    """Map a value onto [0, 1] using the lo/hi breakpoints as 1/3 and 2/3.

    Linear inside [lo, hi]; clamped to [0, 1] outside. Returns 1/3 at lo,
    2/3 at hi, 0.5 at the midpoint of the blend band.
    """
    if hi <= lo:
        return 0.5
    frac = (value - lo) / (hi - lo)  # 0 at lo, 1 at hi
    tilt = (1.0 + frac) / 3.0        # 1/3 at lo, 2/3 at hi
    return float(min(1.0, max(0.0, tilt)))


def classify_style_box(
    size_log_mkt_cap: float,
    book_to_market: float,
    breakpoints: StyleBoxBreakpoints,
) -> StyleBox:
    """Classify one fund into a 9-box style cell.

    Fail-loud: raises ValueError on non-finite inputs. Confidence is the
    smaller of the two axis distances from the nearest breakpoint, normalized
    by the axis span — a fund sitting exactly on a breakpoint scores 0.
    """
    if not math.isfinite(size_log_mkt_cap) or not math.isfinite(book_to_market):
        raise ValueError("non-finite size_log_mkt_cap or book_to_market")

    bp = breakpoints
    size_band = _band(size_log_mkt_cap, bp.size_lo, bp.size_hi, _SIZE_BANDS)
    vg_band = _band(book_to_market, bp.btm_lo, bp.btm_hi, _VG_BANDS)
    label = f"{size_band}_{vg_band}"

    size_tilt = _axis_tilt(size_log_mkt_cap, bp.size_lo, bp.size_hi)
    value_tilt = _axis_tilt(book_to_market, bp.btm_lo, bp.btm_hi)

    # Confidence: normalized distance to the nearest breakpoint on each axis,
    # taking the weaker axis (a fund is only as confident as its weakest axis).
    size_span = (bp.size_hi - bp.size_lo) or 1.0
    btm_span = (bp.btm_hi - bp.btm_lo) or 1.0
    size_conf = min(
        abs(size_log_mkt_cap - bp.size_lo), abs(size_log_mkt_cap - bp.size_hi)
    ) / size_span
    btm_conf = min(
        abs(book_to_market - bp.btm_lo), abs(book_to_market - bp.btm_hi)
    ) / btm_span
    confidence = float(min(1.0, min(size_conf, btm_conf)))

    return StyleBox(
        label=label,  # type: ignore[arg-type]
        size_band=size_band,
        value_growth_band=vg_band,
        size_tilt=round(size_tilt, 4),
        value_tilt=round(value_tilt, 4),
        confidence=round(confidence, 4),
    )
