"""Unit tests for app.services.portfolio_analysis (synthetic frames, no DB)."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import DEFAULT_INITIAL_NAV
from app.schemas.portfolio_analysis import PortfolioAnalysisResponse
from app.services.portfolio_analysis import assemble_portfolio_analysis
from app.services.stock_analysis import InsufficientDataError, PayloadTooLargeError

MAX_POINTS = 7000
END = "2025-12-31"


def _series(n_days: int, seed: int) -> pd.Series:
    """Deterministic geometric walk over *n_days* business days ending at END."""
    index = pd.bdate_range(end=END, periods=n_days)
    rng = np.random.default_rng(seed)
    values = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return pd.Series(values, index=index)


def _default_inputs(n_days: int = 250) -> tuple[dict[str, pd.Series], pd.Series]:
    series = {"AAA": _series(n_days, seed=1), "BBB": _series(n_days, seed=2)}
    benchmark = _series(n_days, seed=3)
    return series, benchmark


def _assemble(
    series_by_ticker: dict[str, pd.Series],
    benchmark: pd.Series,
    **overrides: object,
) -> PortfolioAnalysisResponse:
    kwargs: dict = {
        "mode": "weights",
        "weights": {"AAA": 0.6, "BBB": 0.4},
        "quantities": None,
        "benchmark": "SPY",
        "range_key": "1Y",
        "max_points": MAX_POINTS,
    }
    kwargs.update(overrides)
    return assemble_portfolio_analysis(series_by_ticker, benchmark, **kwargs)


# ---------------------------------------------------------------------------
# Mode consistency: weights mode == quantities mode at matching quantities
# ---------------------------------------------------------------------------


def test_weights_mode_equals_quantities_mode_for_matching_quantities() -> None:
    series, benchmark = _default_inputs()
    weights = {"AAA": 0.6, "BBB": 0.4}
    quantities = {
        ticker: weights[ticker] * DEFAULT_INITIAL_NAV / float(series[ticker].iloc[0])
        for ticker in weights
    }

    by_weights = _assemble(series, benchmark)
    by_quantities = _assemble(
        series, benchmark, mode="quantities", weights=None, quantities=quantities
    )

    assert by_weights.params.initial_nav == pytest.approx(
        by_quantities.params.initial_nav
    )
    for got, expected in zip(
        by_weights.allocation.positions, by_quantities.allocation.positions, strict=True
    ):
        assert got.ticker == expected.ticker
        assert got.weight == pytest.approx(expected.weight)
        assert got.initial_value == pytest.approx(expected.initial_value)
    for (d1, v1), (d2, v2) in zip(by_weights.nav, by_quantities.nav, strict=True):
        assert d1 == d2
        assert v1 == pytest.approx(v2)
    assert by_weights.stats.annualized_volatility == pytest.approx(
        by_quantities.stats.annualized_volatility
    )
    assert by_weights.stats.total_return == pytest.approx(
        by_quantities.stats.total_return
    )
    assert by_weights.stats.diversification_ratio == pytest.approx(
        by_quantities.stats.diversification_ratio
    )
    for got, expected in zip(
        by_weights.risk_contributions, by_quantities.risk_contributions, strict=True
    ):
        assert got.contribution == pytest.approx(expected.contribution)


# ---------------------------------------------------------------------------
# Window / inner-join logic
# ---------------------------------------------------------------------------


def test_inner_join_window_starts_at_latest_inception() -> None:
    # AAA has 300 days, BBB only 120 — the common window starts at BBB's
    # inception (the route resolves MAX the same way; the join enforces it).
    series = {"AAA": _series(300, seed=1), "BBB": _series(120, seed=2)}
    benchmark = _series(300, seed=3)
    response = _assemble(series, benchmark, range_key="MAX")
    assert response.params.start_date == series["BBB"].index[0].date()
    assert response.params.end_date == series["BBB"].index[-1].date()


def test_short_common_history_names_offending_ticker() -> None:
    series = {"AAA": _series(250, seed=1), "BBB": _series(5, seed=2)}
    benchmark = _series(250, seed=3)
    with pytest.raises(InsufficientDataError, match="BBB"):
        _assemble(series, benchmark)


def test_short_benchmark_overlap_names_benchmark() -> None:
    series, _ = _default_inputs()
    benchmark = _series(3, seed=3)
    with pytest.raises(InsufficientDataError, match="SPY"):
        _assemble(series, benchmark)


def test_payload_too_large_raises() -> None:
    series, benchmark = _default_inputs()
    with pytest.raises(PayloadTooLargeError, match="exceeding the maximum"):
        _assemble(series, benchmark, max_points=50)


def test_max_range_emits_weekly_points() -> None:
    series, benchmark = _default_inputs(250)
    daily = _assemble(series, benchmark, range_key="1Y")
    weekly = _assemble(series, benchmark, range_key="MAX")
    # ~250 trading days -> ~52 weekly points for nav and both comparison lines.
    assert len(weekly.nav) < len(daily.nav) / 3
    assert len(weekly.benchmark_comparison.portfolio) < len(
        daily.benchmark_comparison.portfolio
    )


# ---------------------------------------------------------------------------
# Payload invariants
# ---------------------------------------------------------------------------


def test_nav_starts_at_default_initial_nav_in_weights_mode() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    assert response.nav[0][1] == pytest.approx(DEFAULT_INITIAL_NAV)
    assert response.params.initial_nav == pytest.approx(DEFAULT_INITIAL_NAV)
    assert response.allocation.initial_nav == pytest.approx(DEFAULT_INITIAL_NAV)


def test_weights_within_api_tolerance_are_renormalized_and_echoed() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark, weights={"AAA": 0.6004, "BBB": 0.4})
    echoed = {p.ticker: p.weight for p in response.allocation.positions}
    assert sum(echoed.values()) == pytest.approx(1.0)
    assert echoed["AAA"] == pytest.approx(0.6004 / 1.0004)


def test_correlation_matrix_is_symmetric_with_unit_diagonal() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    matrix = response.correlation_matrix.matrix
    tickers = response.correlation_matrix.tickers
    assert tickers == ["AAA", "BBB"]
    assert len(matrix) == 2
    for i in range(2):
        assert matrix[i][i] == 1.0
        for j in range(2):
            assert matrix[i][j] == pytest.approx(matrix[j][i])


def test_risk_contributions_sum_to_one() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    total = sum(rc.contribution for rc in response.risk_contributions)
    assert total == pytest.approx(1.0)


def test_var_99_at_least_var_95_and_diversification_ratio_at_least_one() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    assert response.stats.var_99 >= response.stats.var_95
    assert response.stats.diversification_ratio >= 1.0


def test_benchmark_comparison_rebased_to_zero_on_same_first_date() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    portfolio_points = response.benchmark_comparison.portfolio
    benchmark_points = response.benchmark_comparison.benchmark
    assert portfolio_points[0][0] == benchmark_points[0][0]
    assert portfolio_points[0][1] == 0.0
    assert benchmark_points[0][1] == 0.0
    assert len(portfolio_points) == len(benchmark_points)


def test_histogram_has_twenty_bins() -> None:
    series, benchmark = _default_inputs()
    response = _assemble(series, benchmark)
    assert len(response.histogram.counts) == 20
    assert len(response.histogram.bin_edges) == 21


# --- Risk-adjusted ratios + ENB in PortfolioStats (T1A-5) --------------------

from app.analytics import effective_number_of_bets  # noqa: E402
from app.services._series import join_prices  # noqa: E402


def test_stats_carry_sharpe_sortino_ir_enb() -> None:
    series, benchmark = _default_inputs(250)
    resp = _assemble(series, benchmark)
    stats = resp.stats
    # Present and finite (not NaN).
    for value in (
        stats.sharpe_ratio,
        stats.sortino_ratio,
        stats.information_ratio,
        stats.effective_number_of_bets,
    ):
        assert value == value
    # ENB is bounded by the number of positions (2 here).
    assert 1.0 <= stats.effective_number_of_bets <= 2.0 + 1e-9


def test_stats_enb_matches_engine_over_effective_weights() -> None:
    series, benchmark = _default_inputs(250)
    resp = _assemble(series, benchmark)
    # Effective weights are echoed in the allocation; recompute ENB on the same
    # inner-joined price frame the assembler builds (via join_prices), then the
    # per-asset returns frame (pct_change().dropna(), as asset_returns_frame does).
    weights = {p.ticker: p.weight for p in resp.allocation.positions}
    prices = join_prices(series)
    returns_frame = prices.pct_change().dropna()
    expected = effective_number_of_bets(returns_frame, weights)
    assert resp.stats.effective_number_of_bets == pytest.approx(expected, rel=1e-9)
