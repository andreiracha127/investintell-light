"""F3 portfolio engine tests.

The CONSISTENCY GATE section is the F3 phase gate: a 1-asset portfolio must
reproduce the F2 single-asset statistics exactly (within float noise). If
those tests fail, the portfolio replay disagrees with the single-asset engine
and F3 must not ship.
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    annualized_volatility,
    asset_returns_frame,
    correlation_matrix,
    diversification_ratio,
    historical_var,
    max_drawdown,
    nav_by_position,
    portfolio_nav,
    portfolio_returns,
    risk_contributions,
    simple_returns,
    total_return,
    weight_series,
    weights_to_quantities,
)


def _price_frame(data: dict[str, list[float]]) -> pd.DataFrame:
    n = len(next(iter(data.values())))
    index = pd.date_range("2024-01-01", periods=n, freq="B")
    return pd.DataFrame(data, index=index)


def _seeded_prices(tickers: list[str], periods: int = 120, seed: int = 42) -> pd.DataFrame:
    """Realistic positive price paths from seeded lognormal-ish returns."""
    rng = np.random.default_rng(seed)
    data = {}
    for i, ticker in enumerate(tickers):
        rets = rng.normal(0.0005 + 0.0001 * i, 0.01 + 0.002 * i, periods - 1)
        data[ticker] = 100.0 * (1 + i) * np.concatenate([[1.0], np.cumprod(1 + rets)])
    return _price_frame({k: list(v) for k, v in data.items()})


def _orthogonal_returns(vol_a: float, vol_b: float, blocks: int = 5) -> pd.DataFrame:
    """Two return columns with EXACTLY zero mean and zero sample covariance.

    Per 4-row block: A = [+a, -a, +a, -a], B = [+b, +b, -b, -b].
    Both columns have mean 0, so the sample covariance is
    sum(A_t * B_t) / (n-1) = (ab - ab - ab + ab) / (n-1) = 0 per block.
    """
    a = [vol_a, -vol_a, vol_a, -vol_a] * blocks
    b = [vol_b, vol_b, -vol_b, -vol_b] * blocks
    index = pd.date_range("2024-01-01", periods=len(a), freq="B")
    return pd.DataFrame({"A": a, "B": b}, index=index)


# ---------------------------------------------------------------------------
# CONSISTENCY GATE (F3 phase gate): 1-asset portfolio == F2 single-asset engine
# ---------------------------------------------------------------------------
# These tests pin F3==F2 consistency, the dispatch's phase gate. A portfolio
# holding a single ticker at weight 1.0 is the SAME investment as the single
# asset, so every F2 statistic computed on the portfolio NAV must match the
# one computed on the raw price series.


class TestSingleAssetConsistencyGate:
    @pytest.fixture()
    def prices(self) -> pd.DataFrame:
        return _seeded_prices(["AAA"])

    @pytest.fixture()
    def quantities(self, prices: pd.DataFrame) -> dict[str, float]:
        return weights_to_quantities(prices.iloc[0], {"AAA": 1.0})

    def test_portfolio_returns_match_simple_returns(
        self, prices: pd.DataFrame, quantities: dict[str, float]
    ) -> None:
        port = portfolio_returns(prices, quantities)
        single = simple_returns(prices["AAA"])
        assert (port.index == single.index).all()
        assert np.max(np.abs(port.to_numpy() - single.to_numpy())) < 1e-12

    def test_volatility_matches(
        self, prices: pd.DataFrame, quantities: dict[str, float]
    ) -> None:
        port_vol = annualized_volatility(portfolio_returns(prices, quantities))
        single_vol = annualized_volatility(simple_returns(prices["AAA"]))
        assert abs(port_vol - single_vol) < 1e-12

    def test_var_matches(self, prices: pd.DataFrame, quantities: dict[str, float]) -> None:
        port_var = historical_var(portfolio_returns(prices, quantities))
        single_var = historical_var(simple_returns(prices["AAA"]))
        assert abs(port_var - single_var) < 1e-12

    def test_total_return_matches(
        self, prices: pd.DataFrame, quantities: dict[str, float]
    ) -> None:
        port_total = total_return(portfolio_returns(prices, quantities))
        single_total = total_return(simple_returns(prices["AAA"]))
        assert abs(port_total - single_total) < 1e-12

    def test_max_drawdown_depth_matches(
        self, prices: pd.DataFrame, quantities: dict[str, float]
    ) -> None:
        port_dd = max_drawdown(portfolio_nav(prices, quantities))
        single_dd = max_drawdown(prices["AAA"])
        assert abs(port_dd.depth - single_dd.depth) < 1e-12
        assert port_dd.peak_date == single_dd.peak_date
        assert port_dd.trough_date == single_dd.trough_date


# ---------------------------------------------------------------------------
# Manual validation (F2 pattern): hand-computed NAV and returns
# ---------------------------------------------------------------------------


def test_manual_validation_two_asset_nav_and_returns() -> None:
    # Prices: A = [10, 11, 12], B = [20, 19, 21]; quantities: A=2, B=1.
    #
    # NAV(t) = 2 * A(t) + 1 * B(t):
    #   day 1: 2*10 + 20 = 40
    #   day 2: 2*11 + 19 = 41
    #   day 3: 2*12 + 21 = 45
    #
    # Returns of the NAV:
    #   r1 = 41/40 - 1 = 1/40        = 0.025
    #   r2 = 45/41 - 1 = 4/41        = 0.0975609756...
    prices = _price_frame({"A": [10.0, 11.0, 12.0], "B": [20.0, 19.0, 21.0]})
    quantities = {"A": 2.0, "B": 1.0}

    nav = portfolio_nav(prices, quantities)
    assert nav.tolist() == [40.0, 41.0, 45.0]  # exact: small integers in float

    rets = portfolio_returns(prices, quantities)
    assert len(rets) == 2
    assert rets.iloc[0] == 41.0 / 40.0 - 1.0  # = 0.025
    assert rets.iloc[1] == 45.0 / 41.0 - 1.0  # = 4/41 = 0.0975609756...
    assert abs(rets.iloc[0] - 0.025) < 1e-15
    assert abs(rets.iloc[1] - 0.0975609756) < 1e-9

    positions = nav_by_position(prices, quantities)
    assert positions["A"].tolist() == [20.0, 22.0, 24.0]
    assert positions["B"].tolist() == [20.0, 19.0, 21.0]


# ---------------------------------------------------------------------------
# Intent tests
# ---------------------------------------------------------------------------


def test_equal_weight_identical_assets_behave_like_single_asset() -> None:
    # Two identical price series: diversification is impossible, so the
    # portfolio IS the single asset and risk splits 50/50.
    single = _seeded_prices(["AAA"])["AAA"]
    prices = pd.DataFrame({"A": single, "B": single})
    weights = {"A": 0.5, "B": 0.5}

    quantities = weights_to_quantities(prices.iloc[0], weights)
    port_vol = annualized_volatility(portfolio_returns(prices, quantities))
    single_vol = annualized_volatility(simple_returns(single))
    assert abs(port_vol - single_vol) < 1e-12

    ctr = risk_contributions(asset_returns_frame(prices), weights)
    assert abs(ctr["A"] - 0.5) < 1e-12
    assert abs(ctr["B"] - 0.5) < 1e-12


def test_diversification_ratio_sqrt2_for_uncorrelated_equal_vol() -> None:
    # Equal vol, exactly zero sample correlation, equal weights:
    #   sigma_p^2 = 0.25*s^2 + 0.25*s^2 = s^2/2  ->  sigma_p = s/sqrt(2)
    #   DR = (0.5s + 0.5s) / (s/sqrt(2)) = sqrt(2)
    # The construction makes covariance EXACTLY zero, so the tolerance is
    # float-level rather than statistical.
    returns = _orthogonal_returns(vol_a=0.01, vol_b=0.01)
    dr = diversification_ratio(returns, {"A": 0.5, "B": 0.5})
    assert abs(dr - np.sqrt(2.0)) < 1e-12


def test_diversification_ratio_at_least_one_for_long_only() -> None:
    # Property: for long-only weights, DR >= 1 (Cauchy-Schwarz on the
    # covariance quadratic form). Checked across seeded random portfolios.
    rng = np.random.default_rng(7)
    for seed in range(10):
        prices = _seeded_prices(["A", "B", "C"], periods=80, seed=seed)
        raw = rng.uniform(0.05, 1.0, 3)
        w = raw / raw.sum()
        weights = {"A": float(w[0]), "B": float(w[1]), "C": float(w[2])}
        dr = diversification_ratio(asset_returns_frame(prices), weights)
        assert dr >= 1.0 - 1e-12


def test_weight_series_rows_sum_to_one_and_first_day_matches_supplied() -> None:
    prices = _seeded_prices(["A", "B", "C"])
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    quantities = weights_to_quantities(prices.iloc[0], weights)

    ws = weight_series(prices, quantities)
    row_sums = ws.sum(axis=1).to_numpy()
    assert np.max(np.abs(row_sums - 1.0)) < 1e-12  # every day

    first = ws.iloc[0]
    for ticker, weight in weights.items():
        assert abs(float(first[ticker]) - weight) < 1e-9  # day 1 == supplied

    # Weights DRIFT after day one (buy-and-hold replay, no rebalancing): with
    # different per-asset paths the last-day weights differ from the supplied.
    last = ws.iloc[-1]
    assert any(abs(float(last[t]) - w) > 1e-6 for t, w in weights.items())


def test_nav_at_first_date_equals_initial_nav() -> None:
    prices = _seeded_prices(["A", "B"])
    quantities = weights_to_quantities(prices.iloc[0], {"A": 0.6, "B": 0.4})
    nav = portfolio_nav(prices, quantities)
    assert abs(float(nav.iloc[0]) - 10_000.0) < 1e-9

    custom = weights_to_quantities(prices.iloc[0], {"A": 0.6, "B": 0.4}, initial_nav=250.0)
    nav_custom = portfolio_nav(prices, custom)
    assert abs(float(nav_custom.iloc[0]) - 250.0) < 1e-9


def test_risk_contributions_sum_to_one() -> None:
    prices = _seeded_prices(["A", "B", "C"])
    weights = {"A": 0.5, "B": 0.3, "C": 0.2}
    ctr = risk_contributions(asset_returns_frame(prices), weights)
    assert abs(sum(ctr.values()) - 1.0) < 1e-9
    assert set(ctr) == {"A", "B", "C"}


def test_risk_contributions_dominant_vol_asset_dominates() -> None:
    # 2 assets, vol ratio 3:1, exactly zero correlation, equal weights:
    #   CTR_A = w^2 * (3s)^2 / (w^2 * (3s)^2 + w^2 * s^2) = 9/10 = 0.9 > 0.8
    returns = _orthogonal_returns(vol_a=0.03, vol_b=0.01)
    ctr = risk_contributions(returns, {"A": 0.5, "B": 0.5})
    assert ctr["A"] > 0.8
    assert abs(ctr["A"] - 0.9) < 1e-12
    assert abs(ctr["B"] - 0.1) < 1e-12


def test_correlation_matrix_diagonal_symmetry_and_bounds() -> None:
    prices = _seeded_prices(["A", "B", "C"])
    corr = correlation_matrix(asset_returns_frame(prices))
    assert list(corr.index) == ["A", "B", "C"]
    assert list(corr.columns) == ["A", "B", "C"]
    diag = np.diag(corr.to_numpy())
    assert (diag == 1.0).all()  # exactly 1.0 by contract
    mat = corr.to_numpy()
    assert np.max(np.abs(mat - mat.T)) == 0.0  # symmetric
    assert (mat >= -1.0).all() and (mat <= 1.0).all()


def test_correlation_matrix_zero_correlation_construction() -> None:
    returns = _orthogonal_returns(vol_a=0.01, vol_b=0.02)
    corr = correlation_matrix(returns)
    assert abs(float(corr.loc["A", "B"])) < 1e-12


# ---------------------------------------------------------------------------
# ValueError paths (fail-loud contract)
# ---------------------------------------------------------------------------


class TestValueErrorPaths:
    def test_nan_in_prices(self) -> None:
        prices = _price_frame({"A": [10.0, np.nan, 12.0], "B": [20.0, 19.0, 21.0]})
        with pytest.raises(ValueError, match="NaN"):
            portfolio_nav(prices, {"A": 1.0, "B": 1.0})
        with pytest.raises(ValueError, match="NaN"):
            asset_returns_frame(prices)

    def test_nan_in_first_row_for_weights_to_quantities(self) -> None:
        row = pd.Series({"A": np.nan, "B": 20.0})
        with pytest.raises(ValueError, match="NaN"):
            weights_to_quantities(row, {"A": 0.5, "B": 0.5})

    def test_weights_not_summing_to_one(self) -> None:
        row = pd.Series({"A": 10.0, "B": 20.0})
        with pytest.raises(ValueError, match="sum to 1"):
            weights_to_quantities(row, {"A": 0.6, "B": 0.5})
        returns = _orthogonal_returns(0.01, 0.01)
        with pytest.raises(ValueError, match="sum to 1"):
            risk_contributions(returns, {"A": 0.6, "B": 0.5})
        with pytest.raises(ValueError, match="sum to 1"):
            diversification_ratio(returns, {"A": 0.6, "B": 0.5})

    def test_weight_sum_tolerance_boundary(self) -> None:
        row = pd.Series({"A": 10.0, "B": 20.0})
        # within 1e-6 -> accepted
        qty = weights_to_quantities(row, {"A": 0.5, "B": 0.5 + 5e-7})
        assert qty["A"] > 0

    def test_negative_or_zero_weight(self) -> None:
        row = pd.Series({"A": 10.0, "B": 20.0})
        with pytest.raises(ValueError, match="long-only"):
            weights_to_quantities(row, {"A": 1.2, "B": -0.2})
        with pytest.raises(ValueError, match="long-only"):
            weights_to_quantities(row, {"A": 1.0, "B": 0.0})

    def test_unknown_ticker_key(self) -> None:
        row = pd.Series({"A": 10.0, "B": 20.0})
        with pytest.raises(ValueError, match="unknown"):
            weights_to_quantities(row, {"A": 0.5, "ZZZ": 0.5})
        prices = _price_frame({"A": [10.0, 11.0], "B": [20.0, 21.0]})
        with pytest.raises(ValueError, match="missing"):
            portfolio_nav(prices, {"A": 1.0})
        with pytest.raises(ValueError, match="unknown"):
            portfolio_nav(prices, {"A": 1.0, "B": 1.0, "ZZZ": 1.0})

    def test_non_positive_quantity(self) -> None:
        prices = _price_frame({"A": [10.0, 11.0], "B": [20.0, 21.0]})
        with pytest.raises(ValueError, match="positive quantities"):
            portfolio_nav(prices, {"A": 1.0, "B": -1.0})
        with pytest.raises(ValueError, match="positive quantities"):
            portfolio_nav(prices, {"A": 1.0, "B": 0.0})

    def test_fewer_than_two_rows(self) -> None:
        prices = _price_frame({"A": [10.0], "B": [20.0]})
        with pytest.raises(ValueError, match="at least 2 rows"):
            portfolio_nav(prices, {"A": 1.0, "B": 1.0})
        with pytest.raises(ValueError, match="at least 2 rows"):
            asset_returns_frame(prices)

    def test_correlation_matrix_requires_ten_rows(self) -> None:
        returns = _orthogonal_returns(0.01, 0.01, blocks=2)[:9]
        with pytest.raises(ValueError, match="at least 10 rows"):
            correlation_matrix(returns)

    def test_zero_portfolio_variance(self) -> None:
        # Constant returns -> zero covariance matrix -> sigma_p == 0.
        index = pd.date_range("2024-01-01", periods=12, freq="B")
        returns = pd.DataFrame({"A": [0.01] * 12, "B": [0.02] * 12}, index=index)
        with pytest.raises(ValueError, match="variance is 0"):
            risk_contributions(returns, {"A": 0.5, "B": 0.5})
        with pytest.raises(ValueError, match="volatility is 0"):
            diversification_ratio(returns, {"A": 0.5, "B": 0.5})

    def test_correlation_matrix_zero_variance_column(self) -> None:
        index = pd.date_range("2024-01-01", periods=12, freq="B")
        rng = np.random.default_rng(0)
        returns = pd.DataFrame(
            {"A": [0.01] * 12, "B": rng.normal(0, 0.01, 12)}, index=index
        )
        with pytest.raises(ValueError, match="zero variance"):
            correlation_matrix(returns)

    def test_non_positive_initial_nav_or_price(self) -> None:
        row = pd.Series({"A": 10.0, "B": 20.0})
        with pytest.raises(ValueError, match="initial_nav"):
            weights_to_quantities(row, {"A": 0.5, "B": 0.5}, initial_nav=0.0)
        bad_row = pd.Series({"A": 0.0, "B": 20.0})
        with pytest.raises(ValueError, match="positive first-date prices"):
            weights_to_quantities(bad_row, {"A": 0.5, "B": 0.5})
