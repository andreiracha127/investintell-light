"""Unit tests for the pure 9-box style classification (Tier 3, T3B-1).

Pure-function tests on synthetic cohorts — no DB, no I/O. The classifier takes
one fund's (size_log_mkt_cap, book_to_market) plus the cross-sectional cohort
breakpoints and returns a 9-box label, axis tilts, and a confidence score.
"""

import math

import pytest

from app.analytics.style_box import (
    StyleBox,
    StyleBoxBreakpoints,
    classify_style_box,
    compute_breakpoints,
)


def _cohort() -> list[tuple[float, float]]:
    # 9 funds spanning a clean 3x3 grid: size in {small,mid,large},
    # book_to_market in {growth(low),blend(mid),value(high)}.
    sizes = [10.0, 13.0, 16.0]          # log mkt cap terciles
    btms = [0.20, 0.50, 0.90]           # book_to_market terciles
    return [(s, b) for s in sizes for b in btms]


def test_compute_breakpoints_terciles():
    bp = compute_breakpoints(_cohort())
    assert isinstance(bp, StyleBoxBreakpoints)
    # 33rd/67th percentiles -> the low/high bands sit strictly inside the range.
    assert bp.size_lo < bp.size_hi
    assert bp.btm_lo < bp.btm_hi
    # The middle point of each axis falls inside the blend band.
    assert bp.size_lo <= 13.0 <= bp.size_hi
    assert bp.btm_lo <= 0.50 <= bp.btm_hi


def test_classify_corners():
    bp = compute_breakpoints(_cohort())
    # small + low B/M -> small_growth ; large + high B/M -> large_value
    sg = classify_style_box(10.0, 0.20, bp)
    lv = classify_style_box(16.0, 0.90, bp)
    assert sg.label == "small_growth"
    assert lv.label == "large_value"
    # mid + mid -> mid_blend (the center cell)
    mb = classify_style_box(13.0, 0.50, bp)
    assert mb.label == "mid_blend"


def test_tilts_are_unit_fractions():
    bp = compute_breakpoints(_cohort())
    box = classify_style_box(16.0, 0.90, bp)
    # value_tilt and size_tilt are decimal fractions in [0, 1] (never 0-100).
    assert 0.0 <= box.size_tilt <= 1.0
    assert 0.0 <= box.value_tilt <= 1.0
    # high B/M => value-leaning => value_tilt > 0.5
    assert box.value_tilt > 0.5
    # large size => size_tilt > 0.5
    assert box.size_tilt > 0.5
    assert isinstance(box, StyleBox)


def test_confidence_drops_near_breakpoints():
    bp = compute_breakpoints(_cohort())
    # A fund sitting exactly on both breakpoints is maximally ambiguous.
    on_edge = classify_style_box(bp.size_lo, bp.btm_lo, bp)
    deep_corner = classify_style_box(16.0, 0.90, bp)
    assert on_edge.confidence < deep_corner.confidence
    assert 0.0 <= on_edge.confidence <= 1.0
    assert 0.0 <= deep_corner.confidence <= 1.0


def test_compute_breakpoints_rejects_empty():
    with pytest.raises(ValueError, match="at least 3 funds"):
        compute_breakpoints([])


def test_compute_breakpoints_rejects_too_small_cohort():
    with pytest.raises(ValueError, match="at least 3 funds"):
        compute_breakpoints([(10.0, 0.2), (12.0, 0.5)])


def test_compute_breakpoints_rejects_non_finite_cohort():
    with pytest.raises(ValueError, match="non-finite"):
        compute_breakpoints([(10.0, 0.2), (13.0, float("nan")), (16.0, 0.9)])


def test_classify_rejects_nan():
    bp = compute_breakpoints(_cohort())
    with pytest.raises(ValueError, match="non-finite"):
        classify_style_box(float("nan"), 0.5, bp)
    with pytest.raises(ValueError, match="non-finite"):
        classify_style_box(13.0, math.inf, bp)
