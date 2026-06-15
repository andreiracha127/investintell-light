"""Unit tests for app/services/factor_attribution.py.

The IPCA fit is COMPUTED by the datalake worker (investintell-datalake-workers,
src/workers/factor_model.py) and materialized in factor_model_fits; the Light
only READS it and decomposes risk (no refit). These tests stub the data-lake
session — no live cloud, no live DB. The pure assemble_* math is tested
directly on synthetic numpy inputs.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pytest

from app.services import factor_attribution as fa

_FUND_A = uuid.UUID("00000000-0000-0000-0000-00000000000a")
_FUND_B = uuid.UUID("00000000-0000-0000-0000-00000000000b")

# Worker's fixed characteristic order (CHARS_COLS) = Gamma row order.
_CHARS = [
    "size_log_mkt_cap",
    "book_to_market",
    "mom_12_1",
    "quality_roa",
    "investment_growth",
    "profitability_gross",
]


# ---------------------------------------------------------------------------
# Pure assemble — single factor, hand-verifiable
# ---------------------------------------------------------------------------


def test_assemble_single_factor_euler_sums_to_systematic() -> None:
    # K=1, L=2 (use a 2-char fit for clarity). beta_i = Gamma^T z_i.
    # Gamma (L x K) = [[2.0], [0.0]]  → beta depends only on char 0.
    gamma = np.array([[2.0], [0.0]], dtype=float)
    # Two funds, rank-transformed chars z (N x L):
    #   fund A: char0 = 0.5 → beta_A = 2*0.5 = 1.0
    #   fund B: char0 = 0.25 → beta_B = 2*0.25 = 0.5
    chars = np.array([[0.5, 0.1], [0.25, -0.2]], dtype=float)
    # Factor returns (K x T): a single factor over T=5 days.
    factor_returns = np.array([[0.01, -0.02, 0.015, 0.0, -0.005]], dtype=float)
    weights = np.array([0.5, 0.5], dtype=float)

    result = fa.assemble_factor_attribution(
        weights=weights,
        gamma=gamma,
        chars=chars,
        factor_returns=factor_returns,
        factor_names=["ipca_factor_1"],
        # Per-fund specific (idiosyncratic) variances (annualized): supply
        # directly for the pure test (the orchestrator derives these).
        specific_variance=np.array([0.04, 0.09], dtype=float),
    )

    # Portfolio beta on the single factor = 0.5*1.0 + 0.5*0.5 = 0.75.
    assert result.portfolio_exposures["ipca_factor_1"] == pytest.approx(0.75, abs=1e-9)

    # Single-factor Euler: the one contribution equals systematic risk %.
    assert len(result.factor_contributions) == 1
    only = result.factor_contributions[0]
    assert only["factor_label"] == "ipca_factor_1"
    assert only["pct_contribution"] == pytest.approx(
        result.systematic_risk_pct, abs=1e-4
    )

    # systematic% + specific% == 100 (exact decomposition).
    assert result.systematic_risk_pct + result.specific_risk_pct == pytest.approx(
        100.0, abs=1e-4
    )
    # R² is the systematic share as a fraction in [0, 1].
    assert 0.0 <= result.r_squared <= 1.0
    assert result.r_squared == pytest.approx(
        result.systematic_risk_pct / 100.0, abs=1e-4
    )


def test_assemble_per_factor_marginals_sum_to_systematic_two_factors() -> None:
    # K=2 sanity: per-factor contributions sum to systematic_risk_pct.
    gamma = np.array([[1.0, 0.0], [0.0, 1.0]], dtype=float)  # L=2, K=2
    chars = np.array([[0.4, 0.3], [0.1, -0.2]], dtype=float)  # N=2
    rng = np.random.default_rng(7)
    factor_returns = rng.normal(0.0, 0.01, size=(2, 250))  # K x T
    weights = np.array([0.6, 0.4], dtype=float)
    result = fa.assemble_factor_attribution(
        weights=weights,
        gamma=gamma,
        chars=chars,
        factor_returns=factor_returns,
        factor_names=["ipca_factor_1", "ipca_factor_2"],
        specific_variance=np.array([0.02, 0.03], dtype=float),
    )
    total_factor_pct = sum(c["pct_contribution"] for c in result.factor_contributions)
    assert total_factor_pct == pytest.approx(result.systematic_risk_pct, abs=1e-3)


def test_assemble_rejects_dimension_mismatch() -> None:
    gamma = np.array([[1.0], [0.0]], dtype=float)  # L=2, K=1
    chars = np.array([[0.5, 0.1, 0.0]], dtype=float)  # L=3 — mismatch
    with pytest.raises(ValueError, match="characteristic columns"):
        fa.assemble_factor_attribution(
            weights=np.array([1.0]),
            gamma=gamma,
            chars=chars,
            factor_returns=np.array([[0.01, 0.02]]),
            factor_names=["ipca_factor_1"],
            specific_variance=np.array([0.04]),
        )


def test_assemble_rejects_weight_count_mismatch() -> None:
    with pytest.raises(ValueError, match="disagree on N"):
        fa.assemble_factor_attribution(
            weights=np.array([0.5, 0.5]),  # N=2
            gamma=np.array([[1.0]]),  # L=1, K=1
            chars=np.array([[0.5]]),  # N=1 — mismatch
            factor_returns=np.array([[0.01, 0.02]]),
            factor_names=["ipca_factor_1"],
            specific_variance=np.array([0.04]),
        )


def test_assemble_rejects_nan_inputs() -> None:
    with pytest.raises(ValueError, match="NaN or infinite"):
        fa.assemble_factor_attribution(
            weights=np.array([1.0]),
            gamma=np.array([[1.0]]),
            chars=np.array([[np.nan]]),
            factor_returns=np.array([[0.01, 0.02]]),
            factor_names=["ipca_factor_1"],
            specific_variance=np.array([0.04]),
        )


# ---------------------------------------------------------------------------
# Async orchestrator — fake data-lake session
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def first(self) -> Any | None:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return self._rows


class _Row:
    def __init__(self, **kw: Any) -> None:
        self.__dict__.update(kw)


class _FakeDatalake:
    """Routes the two SQL statements by the table name in their text."""

    def __init__(self, fit_row: Any | None, char_rows: dict[uuid.UUID, Any]) -> None:
        self._fit_row = fit_row
        self._char_rows = char_rows

    async def execute(
        self, stmt: Any, params: dict[str, Any] | None = None
    ) -> _FakeResult:
        sql = str(stmt)
        if "factor_model_fits" in sql:
            return _FakeResult([self._fit_row] if self._fit_row else [])
        if "equity_characteristics_monthly" in sql:
            # The cross-section query has no params; return the whole universe.
            return _FakeResult(list(self._char_rows.values()))
        return _FakeResult([])


def _fit_row() -> _Row:
    # K=1, L=6 Gamma where only size loads; factor returns over T=4.
    gamma = [[2.0], [0.0], [0.0], [0.0], [0.0], [0.0]]  # L x K
    return _Row(
        fit_date=dt.date(2026, 3, 31),
        k_factors=1,
        gamma_loadings=gamma,
        factor_returns={
            "dates": ["2026-01-31", "2026-02-28", "2026-03-31", "2026-04-30"],
            "values": [[0.01, -0.02, 0.015, -0.005]],
        },
        oos_r_squared=0.12,
        converged=True,
        n_iterations=37,
    )


def _char_row(instrument_id: uuid.UUID, size: float) -> _Row:
    return _Row(
        instrument_id=instrument_id,
        ticker="X",
        as_of=dt.date(2026, 3, 31),
        size_log_mkt_cap=size,
        book_to_market=0.1,
        mom_12_1=0.0,
        quality_roa=0.0,
        investment_growth=0.0,
        profitability_gross=0.0,
    )


@pytest.mark.anyio
async def test_run_orchestrator_reads_fit_and_chars_and_decomposes() -> None:
    datalake = _FakeDatalake(
        fit_row=_fit_row(),
        char_rows={
            _FUND_A: _char_row(_FUND_A, size=1.0),  # highest in the cross-section
            _FUND_B: _char_row(_FUND_B, size=-1.0),  # lowest
        },
    )
    result = await fa.run_factor_attribution(
        datalake,  # type: ignore[arg-type]
        weights={_FUND_A: 0.5, _FUND_B: 0.5},
    )
    assert result.fit_date == dt.date(2026, 3, 31)
    assert result.k_factors == 1
    assert result.factor_names == ["ipca_factor_1"]
    # Cross-section rank-transform: size 1.0 → rank 1.0 → 1.0-0.5=+0.5;
    # size -1.0 → rank 0.5 → 0.5-0.5=0.0.  beta = 2 * z_size:
    #   A: 2*0.5 = 1.0 ; B: 2*0.0 = 0.0 → portfolio beta = 0.5*1.0 = 0.5.
    assert result.portfolio_exposures["ipca_factor_1"] == pytest.approx(0.5, abs=1e-9)
    assert result.systematic_risk_pct + result.specific_risk_pct == pytest.approx(
        100.0, abs=1e-4
    )


@pytest.mark.anyio
async def test_run_orchestrator_no_fit_is_loud() -> None:
    datalake = _FakeDatalake(fit_row=None, char_rows={})
    with pytest.raises(ValueError, match="no IPCA fit"):
        await fa.run_factor_attribution(
            datalake,  # type: ignore[arg-type]
            weights={_FUND_A: 1.0},
        )


@pytest.mark.anyio
async def test_run_orchestrator_missing_characteristics_is_loud() -> None:
    datalake = _FakeDatalake(
        fit_row=_fit_row(),
        char_rows={_FUND_A: _char_row(_FUND_A, size=1.0)},  # B missing
    )
    with pytest.raises(ValueError, match="missing characteristics"):
        await fa.run_factor_attribution(
            datalake,  # type: ignore[arg-type]
            weights={_FUND_A: 0.5, _FUND_B: 0.5},
        )
