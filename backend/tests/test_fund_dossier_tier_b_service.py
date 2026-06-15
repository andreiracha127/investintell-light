"""Pure service tests for P5 fund dossier Tier B analytics."""

import uuid

import numpy as np
import pandas as pd
import pytest

from app.models.fund import Fund
from app.services.fund_dossier_tier_b import (
    _max_drawdown_series,
    _ols_market_sensitivities,
    _regime_label,
    active_share_from_weights,
    assemble_entity_analytics,
)

_FUND_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _fund() -> Fund:
    return Fund(
        instrument_id=_FUND_ID,
        series_id="S000000001",
        name="Sample Fund",
        fund_type="mutual_fund",
        strategy_label="Large Blend",
    )


def _nav(n_days: int = 320) -> pd.Series:
    dates = pd.bdate_range("2025-01-01", periods=n_days)
    rng = np.random.default_rng(7)
    values = 100.0 * np.cumprod(1.0 + rng.normal(0.00035, 0.008, n_days))
    return pd.Series(values, index=dates)


def test_entity_analytics_shape_and_tail_risk_fields() -> None:
    payload = assemble_entity_analytics(_nav(), fund=_fund(), window="1Y")

    assert payload.instrument_id == _FUND_ID
    assert payload.risk_statistics.n_observations > 100
    assert payload.drawdown.values
    assert payload.rolling_returns.series["1M"]
    assert payload.distribution.bin_edges
    assert payload.tail_risk.var_parametric_95 is not None
    assert payload.insider_data is None


def test_risk_timeseries_drawdown_percent_scaling_contract() -> None:
    nav = pd.Series(
        [100.0, 110.0, 99.0],
        index=pd.to_datetime(["2026-01-01", "2026-01-02", "2026-01-05"]),
    )
    drawdown_percent = _max_drawdown_series(nav) * 100.0

    assert drawdown_percent.iloc[-1] == pytest.approx(-10.0)


@pytest.mark.parametrize(
    ("raw", "expected_value", "expected_label"),
    [
        ("RISK_ON", 0.0, "Expansion"),
        ("neutral", 0.5, "Cautious"),
        ("CRISIS", 1.0, "Stress"),
    ],
)
def test_regime_relabel(raw: str, expected_value: float, expected_label: str) -> None:
    value, label = _regime_label(raw)
    assert value == expected_value
    assert label == expected_label


def test_active_share_formula_and_overlap() -> None:
    active_share, overlap, common = active_share_from_weights(
        {"A": 0.6, "B": 0.4},
        {"A": 0.2, "C": 0.8},
    )

    assert active_share == pytest.approx(0.8)
    assert overlap == pytest.approx(0.2)
    assert common == 1


def test_ols_market_sensitivities_include_t_stats() -> None:
    dates = pd.date_range("2025-01-31", periods=36, freq="ME")
    factor_1 = pd.Series(np.linspace(-0.02, 0.03, 36), index=dates)
    factor_2 = pd.Series(np.sin(np.linspace(0, 6, 36)) * 0.01, index=dates)
    fund_returns = 0.002 + 1.5 * factor_1 - 0.5 * factor_2
    factors = pd.DataFrame({"Factor 1": factor_1, "Factor 2": factor_2})

    payload = _ols_market_sensitivities(fund_returns, factors)

    assert [item.factor for item in payload] == ["Factor 1", "Factor 2"]
    assert payload[0].beta == pytest.approx(1.5)
    assert payload[0].t_stat is not None
