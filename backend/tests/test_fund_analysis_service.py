"""Unit tests for app.services.fund_analysis — synthetic NAV, no DB."""

import datetime as dt
import uuid

import numpy as np
import pandas as pd
import pytest

from app.services.fund_analysis import (
    FundIdentity,
    FundPayloadTooLargeError,
    InsufficientFundDataError,
    assemble_fund_analysis,
    build_nav_series,
)


def _nav(n_days: int = 420) -> pd.Series:
    dates = pd.bdate_range("2024-01-01", periods=n_days)
    rng = np.random.default_rng(42)
    values = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return pd.Series(values, index=dates)


def _identity() -> FundIdentity:
    return FundIdentity(
        instrument_id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
        ticker="VFINX",
        name="Vanguard 500 Index Fund",
    )


def _assemble(nav: pd.Series, **overrides):  # type: ignore[no-untyped-def]
    start = overrides.pop(
        "start", nav.index[-252].date() if len(nav) >= 252 else nav.index[0].date()
    )
    end = overrides.pop("end", nav.index[-1].date())
    kwargs = dict(
        fund=_identity(),
        range_key="1Y",
        window=21,
        start=start,
        end=end,
        max_points=5000,
    )
    kwargs.update(overrides)
    return assemble_fund_analysis(nav, **kwargs)


def test_assemble_fund_analysis_shape() -> None:
    payload = _assemble(_nav())
    assert payload.header.ticker == "VFINX"
    assert payload.growth_of_100[0][1] == pytest.approx(100.0)
    assert payload.monthly_returns
    assert payload.rolling_volatility
    assert payload.rolling_sharpe
    assert payload.drawdown[0][1] == pytest.approx(0.0)
    assert len(payload.histogram.counts) == 20
    assert payload.stats.var_95 >= 0
    assert payload.stats.cvar_95 >= payload.stats.var_95


def test_max_range_lines_are_weekly_bounded_but_keep_first_growth_point() -> None:
    nav = _nav()
    payload = _assemble(
        nav,
        range_key="MAX",
        start=nav.index[0].date(),
        end=nav.index[-1].date(),
    )
    assert payload.growth_of_100[0][1] == pytest.approx(100.0)
    dates = [date for date, _value in payload.rolling_volatility]
    assert dates
    assert all(date.weekday() == 4 for date in dates)


def test_too_few_nav_rows_raises_insufficient_data() -> None:
    with pytest.raises(InsufficientFundDataError, match="NAV rows"):
        _assemble(_nav(1), start=dt.date(2024, 1, 1), end=dt.date(2024, 1, 1))


def test_payload_cap_raises() -> None:
    nav = _nav()
    with pytest.raises(FundPayloadTooLargeError, match="exceeding"):
        _assemble(nav, max_points=10)


def test_build_nav_series_sorts_and_drops_non_positive_navs() -> None:
    series = build_nav_series(
        [
            (dt.date(2026, 1, 3), 103.0),
            (dt.date(2026, 1, 1), 101.0),
            (dt.date(2026, 1, 2), 0.0),
        ]
    )
    assert list(series.to_numpy()) == [101.0, 103.0]
