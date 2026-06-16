"""Tests for app.analytics.expense_ratio.to_decimal_fraction (T3D-3)."""

import logging

import pytest

from app.analytics.expense_ratio import (
    MAX_REASONABLE_EXPENSE_RATIO,
    MIN_REASONABLE_EXPENSE_RATIO,
    to_decimal_fraction,
)

# --- scale detection ---------------------------------------------------------


def test_basis_points_divided_by_10000() -> None:
    # 150 bps -> 0.015 (1.5%)
    assert to_decimal_fraction(150.0) == pytest.approx(0.015)


def test_whole_percent_divided_by_100() -> None:
    # 1.5 percent -> 0.015
    assert to_decimal_fraction(1.5) == pytest.approx(0.015)


def test_decimal_fraction_kept_as_is() -> None:
    # 0.015 already a fraction
    assert to_decimal_fraction(0.015) == pytest.approx(0.015)


def test_small_fraction_below_band_kept() -> None:
    # 0.0069 (0.69%) is a canonical XBRL fraction, must survive untouched
    assert to_decimal_fraction(0.0069) == pytest.approx(0.0069)


def test_ambiguous_band_treated_as_percent_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # (0.15, 1.0] -> whole percent per the ported Q57 convention; warns.
    with caplog.at_level(logging.WARNING, logger="app.analytics.expense_ratio"):
        result = to_decimal_fraction(0.5)
    assert result == pytest.approx(0.005)  # 0.5% -> 0.005 fraction
    assert "expense_ratio_ambiguous_percent_or_fraction" in caplog.text


# --- clamping ----------------------------------------------------------------


def test_above_max_is_clamped_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # 9999 bps -> 0.9999 fraction -> clamped to 0.15
    with caplog.at_level(logging.WARNING, logger="app.analytics.expense_ratio"):
        result = to_decimal_fraction(9999.0)
    assert result == pytest.approx(MAX_REASONABLE_EXPENSE_RATIO)
    assert "expense_ratio_clamped_above_max" in caplog.text


def test_negative_is_clamped_to_zero_with_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.WARNING, logger="app.analytics.expense_ratio"):
        result = to_decimal_fraction(-0.01)
    assert result == pytest.approx(MIN_REASONABLE_EXPENSE_RATIO)
    assert "expense_ratio_clamped_below_zero" in caplog.text


# --- non-numeric / sentinel inputs ------------------------------------------


def test_none_returns_none() -> None:
    assert to_decimal_fraction(None) is None


def test_non_numeric_string_returns_none() -> None:
    assert to_decimal_fraction("n/a") is None


def test_numeric_string_is_parsed() -> None:
    assert to_decimal_fraction("1.5") == pytest.approx(0.015)


def test_nan_returns_none() -> None:
    assert to_decimal_fraction(float("nan")) is None


def test_inf_returns_none() -> None:
    assert to_decimal_fraction(float("inf")) is None
    assert to_decimal_fraction(float("-inf")) is None
