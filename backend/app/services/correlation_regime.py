"""Correlation-regime / contagion service.

Pure assembler over the SAME (T,N) daily-returns matrix the optimizer builds
(``app.optimizer.data.load_aligned_returns`` → ``frame.to_numpy``), plus an
async orchestrator that loads it. ALL covariance/eigenvalue math is delegated
to ``app.analytics.rmt`` (constant-correlation LW 2003, MP denoise, absorption)
— nothing is re-derived here.

Logic ported from legacy correlation_regime_service.compute_correlation_regime
(recent-vs-baseline split; per-pair contagion |Δ|>0.3 AND current>0.7;
average-corr regime shift; concentration + absorption status).

Service pattern: assemble_*(matrix)->schema (no I/O) + async run_*(session,...)
orchestrator. Fail-loud on NaN / shape mismatch (route maps → 422).
Scale contract: correlations/ratios are decimal fractions.
"""

from __future__ import annotations

import datetime as dt
from typing import Literal

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics import rmt
from app.optimizer import data as optimizer_data
from app.schemas.correlation_regime import (
    ConcentrationOut,
    CorrelationRegimeOut,
    PairCorrelationOut,
)

_WINDOW_DAYS = 60
_CONTAGION_THRESHOLD = 0.3
_CONTAGION_CURRENT_MIN = 0.7
_CONCENTRATION_MODERATE = 0.6
_CONCENTRATION_HIGH = 0.8
_DR_ALERT_THRESHOLD = 1.2
_MIN_OBSERVATIONS = 45
_ABSORPTION_WARNING = 0.80
_ABSORPTION_CRITICAL = 0.90


def _corr_from_cov(cov: np.ndarray) -> np.ndarray:
    d = np.sqrt(np.diag(cov))
    d[d == 0] = 1.0
    corr = cov / np.outer(d, d)
    np.fill_diagonal(corr, 1.0)
    return np.asarray(corr)


def _concentration(corr_denoised: np.ndarray, q: float) -> ConcentrationOut:
    eigenvalues = np.sort(np.maximum(np.linalg.eigvalsh(corr_denoised), 0.0))[::-1]
    total = float(eigenvalues.sum())
    n_signal, lambda_plus = rmt.mp_signal_eigenvalues(corr_denoised, q)
    if total < 1e-10:
        return ConcentrationOut(
            eigenvalues=[float(e) for e in eigenvalues],
            first_eigenvalue_ratio=1.0,
            concentration_status="high_concentration",
            absorption_ratio=1.0,
            absorption_status="critical",
            mp_threshold=round(lambda_plus, 6),
            n_signal_eigenvalues=n_signal,
        )
    first_ratio = float(eigenvalues[0] / total)
    status: Literal["diversified", "moderate_concentration", "high_concentration"]
    if first_ratio > _CONCENTRATION_HIGH:
        status = "high_concentration"
    elif first_ratio > _CONCENTRATION_MODERATE:
        status = "moderate_concentration"
    else:
        status = "diversified"
    ar = rmt.absorption_ratio(corr_denoised)
    ar_status: Literal["normal", "warning", "critical"]
    if ar > _ABSORPTION_CRITICAL:
        ar_status = "critical"
    elif ar > _ABSORPTION_WARNING:
        ar_status = "warning"
    else:
        ar_status = "normal"
    return ConcentrationOut(
        eigenvalues=[round(float(e), 6) for e in eigenvalues],
        first_eigenvalue_ratio=round(first_ratio, 6),
        concentration_status=status,
        absorption_ratio=round(ar, 6),
        absorption_status=ar_status,
        mp_threshold=round(lambda_plus, 6),
        n_signal_eigenvalues=n_signal,
    )


def _diversification_ratio(cov: np.ndarray, weights: np.ndarray) -> float:
    individual_vols = np.sqrt(np.diag(cov))
    portfolio_var = float(weights @ cov @ weights)
    if portfolio_var < 1e-20:
        return 1.0
    return round(float(np.dot(weights, individual_vols) / np.sqrt(portfolio_var)), 6)


def _empty_concentration() -> ConcentrationOut:
    return ConcentrationOut(
        eigenvalues=[],
        first_eigenvalue_ratio=0.0,
        concentration_status="diversified",
        absorption_ratio=0.0,
        absorption_status="normal",
        mp_threshold=0.0,
        n_signal_eigenvalues=0,
    )


def assemble_correlation_regime(
    returns_matrix: np.ndarray,
    labels: list[str],
    weights: np.ndarray | None = None,
    window_days: int = _WINDOW_DAYS,
    min_observations: int = _MIN_OBSERVATIONS,
) -> CorrelationRegimeOut:
    """Assemble the correlation-regime payload from a (T,N) returns matrix.

    Raises ValueError (→ 422) on NaN/inf or a labels/columns mismatch.
    """
    arr = np.asarray(returns_matrix, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns_matrix must be (T, N), got ndim={arr.ndim}")
    t, n = arr.shape
    if len(labels) != n:
        raise ValueError(f"labels ({len(labels)}) must match columns ({n})")
    if not np.isfinite(arr).all():
        raise ValueError("returns_matrix contains NaN/inf")

    if t < min_observations:
        return CorrelationRegimeOut(
            instrument_count=n,
            labels=labels,
            window_days=0,
            correlation_matrix=[],
            pair_correlations=[],
            concentration=_empty_concentration(),
            diversification_ratio=1.0,
            dr_alert=False,
            average_correlation=0.0,
            baseline_average_correlation=0.0,
            regime_shift_detected=False,
            sufficient_data=False,
        )

    if weights is None:
        weights = np.ones(n) / n

    window = min(window_days, t)
    recent = arr[-window:]
    baseline = arr[:-window] if window < t else arr

    cov_recent, _ = rmt.ledoit_wolf_constant_correlation(recent)
    corr_recent_raw = _corr_from_cov(cov_recent)
    q_recent = n / len(recent)
    corr_recent = (
        rmt.marchenko_pastur_denoise(corr_recent_raw, q_recent) if n > 1 else corr_recent_raw
    )

    if len(baseline) >= min_observations:
        cov_base, _ = rmt.ledoit_wolf_constant_correlation(baseline)
        corr_base_raw = _corr_from_cov(cov_base)
        q_base = n / len(baseline)
        corr_base = (
            rmt.marchenko_pastur_denoise(corr_base_raw, q_base) if n > 1 else corr_base_raw
        )
    else:
        corr_base_raw = corr_recent_raw
        corr_base = corr_recent

    pairs: list[PairCorrelationOut] = []
    for i in range(n):
        for j in range(i + 1, n):
            curr = float(corr_recent[i, j])
            base = float(corr_base[i, j])
            change = curr - base
            pairs.append(
                PairCorrelationOut(
                    label_a=labels[i],
                    label_b=labels[j],
                    current_correlation=round(curr, 6),
                    baseline_correlation=round(base, 6),
                    correlation_change=round(change, 6),
                    is_contagion=(
                        abs(change) > _CONTAGION_THRESHOLD and curr > _CONTAGION_CURRENT_MIN
                    ),
                )
            )

    concentration = _concentration(corr_recent, q_recent)
    dr = _diversification_ratio(cov_recent, weights)

    if n > 1:
        avg_corr = float(np.mean(corr_recent_raw[np.triu_indices(n, k=1)]))
        avg_corr_base = float(np.mean(corr_base_raw[np.triu_indices(n, k=1)]))
    else:
        avg_corr = avg_corr_base = 0.0
    regime_shift = abs(avg_corr - avg_corr_base) > _CONTAGION_THRESHOLD

    return CorrelationRegimeOut(
        instrument_count=n,
        labels=labels,
        window_days=window,
        correlation_matrix=[
            [round(float(v), 6) for v in row] for row in corr_recent_raw
        ],
        pair_correlations=pairs,
        concentration=concentration,
        diversification_ratio=dr,
        dr_alert=dr < _DR_ALERT_THRESHOLD,
        average_correlation=round(avg_corr, 6),
        baseline_average_correlation=round(avg_corr_base, 6),
        regime_shift_detected=regime_shift,
        sufficient_data=True,
    )


async def run_correlation_regime(
    session: AsyncSession,
    refs: list[optimizer_data.AssetRef],
    window_days: int | None = None,
    today: dt.date | None = None,
) -> CorrelationRegimeOut:
    """Load the aligned (T,N) returns matrix and assemble the regime payload.

    Reuses the optimizer's loader so the matrix is IDENTICAL to the one the
    builder optimizes over. ValueError from the loader bubbles to the route
    (mapped → 422).
    """
    frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
        session, refs, window_days=window_days, today=today
    )
    labels = [str(c) for c in frame.columns]
    return assemble_correlation_regime(frame.to_numpy(dtype=float), labels)
