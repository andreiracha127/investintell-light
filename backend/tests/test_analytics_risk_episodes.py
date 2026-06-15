"""Tests for app.analytics.risk.drawdown_episodes (drawdown episode decomposition)."""

import datetime as dt

import pandas as pd
import pytest

from app.analytics import DrawdownEpisode, drawdown_episodes


def _dated(values: list[float], start: str = "2024-01-01") -> pd.Series:
    """Date-indexed business-day price series (matches the max_drawdown convention)."""
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def test_single_recovered_episode_basic_shape() -> None:
    # Up to 110 (peak), down to 88 (trough), back above 110 (recovery).
    prices = _dated([100, 110, 99, 88, 95, 112])
    episodes = drawdown_episodes(prices, top_n=5)
    assert len(episodes) == 1
    ep = episodes[0]
    assert isinstance(ep, DrawdownEpisode)
    # peak is the running-max date at drawdown ONSET (index 1 = 110), NOT recovery.
    assert ep.peak_date == dt.date(2024, 1, 2)
    # trough is the deepest point (index 3 = 88).
    assert ep.trough_date == dt.date(2024, 1, 4)
    # recovery is the first date the series climbs back to a new high (index 5 = 112).
    assert ep.recovery_date == dt.date(2024, 1, 8)
    # depth = 88/110 - 1 = -0.2 exactly, a NEGATIVE decimal fraction.
    assert ep.depth == pytest.approx(-0.2)
    # duration = peak -> recovery in CALENDAR days; recovery_days = trough -> recovery.
    assert ep.duration_days == (dt.date(2024, 1, 8) - dt.date(2024, 1, 2)).days
    assert ep.recovery_days == (dt.date(2024, 1, 8) - dt.date(2024, 1, 4)).days


def test_open_drawdown_has_no_recovery() -> None:
    # Falls and never recovers: an OPEN episode (recovery_date/_days are None).
    prices = _dated([100, 120, 90, 80, 85])
    episodes = drawdown_episodes(prices, top_n=5)
    assert len(episodes) == 1
    ep = episodes[0]
    assert ep.peak_date == dt.date(2024, 1, 2)   # 120
    assert ep.trough_date == dt.date(2024, 1, 4)  # 80
    assert ep.recovery_date is None
    assert ep.recovery_days is None
    assert ep.depth == pytest.approx(80 / 120 - 1)
    # duration of an open episode spans peak -> last available date.
    assert ep.duration_days == (dt.date(2024, 1, 5) - dt.date(2024, 1, 2)).days


def test_episodes_sorted_deepest_first_and_capped() -> None:
    # Two recovered drawdowns: a shallow -9% (110->100) then a deep -20% (130->104).
    prices = _dated([100, 110, 100, 111, 130, 104, 131])
    episodes = drawdown_episodes(prices, top_n=1)
    # top_n=1 keeps only the deepest (the -20% drop from 130 to 104).
    assert len(episodes) == 1
    assert episodes[0].depth == pytest.approx(104 / 130 - 1)
    assert episodes[0].peak_date == dt.date(2024, 1, 5)   # 130 (onset peak)
    assert episodes[0].trough_date == dt.date(2024, 1, 8)  # 104


def test_monotonic_series_has_no_episodes() -> None:
    prices = _dated([100, 101, 102, 103, 104])
    assert drawdown_episodes(prices) == []


def test_too_short_raises() -> None:
    with pytest.raises(ValueError, match="at least 2 prices"):
        drawdown_episodes(_dated([100.0]))


def test_nan_input_raises() -> None:
    prices = _dated([100.0, float("nan"), 90.0])
    with pytest.raises(ValueError, match="NaN or infinite"):
        drawdown_episodes(prices)


def test_top_n_must_be_positive() -> None:
    with pytest.raises(ValueError, match="top_n must be >= 1"):
        drawdown_episodes(_dated([100.0, 90.0, 95.0]), top_n=0)
