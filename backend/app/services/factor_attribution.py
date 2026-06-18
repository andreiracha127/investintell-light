"""Factor risk attribution over PERSISTED IPCA fits (Tier 2, no refit).

The IPCA model is FITTED by the datalake worker
(investintell-datalake-workers, src/workers/factor_model.py) and materialized in
``factor_model_fits`` (TimescaleDB Cloud). This service only READS that fit
(Gamma loadings L×K + factor returns K×T) plus a fund's latest rank-transformed
characteristics from ``equity_characteristics_monthly``, and decomposes a
portfolio's risk into per-factor Euler contributions. It never re-estimates
Gamma or the factor returns.

IPCA convention (worker docstring lines 17-19): r_{i,t} = (z_{i,t-1}ᵀ Γ) f_t + e,
so the fund's K-vector of betas is β_i = Γᵀ z_i where z_i is the L-vector of
rank-transformed instrument characteristics (CHARS_COLS order). Rank transform
is per cross-section, rescaled to [-0.5, +0.5] (matches the worker's
rank_transform so betas land on the same scale Γ was fitted against).

Euler decomposition (ported from quant_engine/factor_model_service.py
::compute_factor_contributions, lines 951-1008):
    Σ_f = cov(factor_returns)            # K×K, from the persisted K×T series
    expo = Σ_i w_i β_i                   # portfolio factor exposures (K)
    systematic_var = expoᵀ Σ_f expo
    contribution_k = expo_k · (Σ_f expo)_k     # sums to systematic_var
    specific_var = Σ_i w_i² · D_i        # idiosyncratic (D_i = per-fund residual var)
    R² (portfolio) = systematic_var / (systematic_var + specific_var)

COVARIANCE ORIENTATION: the legacy service holds factor_returns as T×K and so
uses np.cov(..., rowvar=False). The WORKER persists factor_returns as K×T
(factor_model.py::_upsert line 493; schemas/factor_model.sql lines 11-13), so
this service uses np.cov(..., rowvar=True). Do NOT change this to rowvar=False.

Pattern: pure ``assemble_factor_attribution`` (no I/O) + async
``run_factor_attribution(datalake, ...)`` orchestrator. Fail loud: ValueError on
missing fit / missing characteristics / NaN / dimension mismatch (routes map to
422 per the project contract).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

TRADING_DAYS_PER_YEAR = 252

# Worker's fixed instrument-characteristic order = Gamma row order
# (investintell-datalake-workers/src/workers/factor_model.py::CHARS_COLS).
CHARS_COLS = [
    "size_log_mkt_cap",
    "book_to_market",
    "mom_12_1",
    "quality_roa",
    "investment_growth",
    "profitability_gross",
]

_ENGINE = "ipca"
_ASSET_CLASS = "Equity"

_SPECIFIC_VAR_FLOOR = 1e-8


# ---------------------------------------------------------------------------
# Result dataclasses
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FactorAttribution:
    """Portfolio factor risk decomposition over a persisted IPCA fit."""

    systematic_risk_pct: float  # % of total variance from factors
    specific_risk_pct: float  # % of total variance idiosyncratic
    factor_contributions: list[dict[str, object]]  # [{factor_label, pct_contribution}]
    portfolio_exposures: dict[str, float]  # {factor_label: portfolio beta}
    r_squared: float  # systematic share as a fraction in [0, 1]
    factor_names: list[str]
    fit_date: dt.date | None = None
    k_factors: int | None = None


@dataclass(frozen=True)
class IpcaFit:
    """The persisted IPCA fit, parsed from factor_model_fits."""

    fit_date: dt.date
    k_factors: int
    gamma: np.ndarray  # L×K
    factor_returns: np.ndarray  # K×T
    factor_dates: list[dt.date]


# ---------------------------------------------------------------------------
# Pure assemble — no I/O
# ---------------------------------------------------------------------------


def assemble_factor_attribution(
    *,
    weights: np.ndarray,
    gamma: np.ndarray,
    chars: np.ndarray,
    factor_returns: np.ndarray,
    factor_names: list[str],
    specific_variance: np.ndarray,
    fit_date: dt.date | None = None,
) -> FactorAttribution:
    """Decompose portfolio risk over a persisted IPCA fit (no refit).

    Parameters
    ----------
    weights : np.ndarray
        Portfolio weights, length N (fractions; the caller has aligned them to
        the order of ``chars`` rows).
    gamma : np.ndarray
        Persisted Gamma loadings, shape L×K (CHARS_COLS order on rows).
    chars : np.ndarray
        Rank-transformed characteristics, shape N×L (same row order as weights).
    factor_returns : np.ndarray
        Persisted factor-return series, shape K×T.
    factor_names : list[str]
        Length K labels.
    specific_variance : np.ndarray
        Per-fund annualized idiosyncratic variance D_i, length N.
    fit_date : dt.date | None
        Passed through for provenance.

    Raises
    ------
    ValueError
        On NaN/inf, dimension mismatch, or degenerate (zero) total variance.
    """
    weights = np.asarray(weights, dtype=float).ravel()
    gamma = np.asarray(gamma, dtype=float)
    chars = np.asarray(chars, dtype=float)
    factor_returns = np.asarray(factor_returns, dtype=float)
    specific_variance = np.asarray(specific_variance, dtype=float).ravel()

    for name, arr in (
        ("weights", weights),
        ("gamma", gamma),
        ("chars", chars),
        ("factor_returns", factor_returns),
        ("specific_variance", specific_variance),
    ):
        if not np.isfinite(arr).all():
            raise ValueError(
                f"assemble_factor_attribution received NaN or infinite values in {name}"
            )

    if gamma.ndim != 2 or factor_returns.ndim != 2 or chars.ndim != 2:
        raise ValueError("gamma, chars and factor_returns must be 2-D")
    L, K = gamma.shape
    if len(factor_names) != K:
        raise ValueError(
            f"factor_names length {len(factor_names)} != K factor columns {K}"
        )
    if factor_returns.shape[0] != K:
        raise ValueError(
            f"factor_returns has {factor_returns.shape[0]} rows, expected K={K}"
        )
    if chars.shape[1] != L:
        raise ValueError(
            f"chars has {chars.shape[1]} characteristic columns, expected L={L}"
        )
    n = weights.shape[0]
    if chars.shape[0] != n or specific_variance.shape[0] != n:
        raise ValueError(
            f"weights/chars/specific_variance disagree on N: "
            f"{n} vs {chars.shape[0]} vs {specific_variance.shape[0]}"
        )

    # Instrumented betas: β_i = Γᵀ z_i  →  B = chars @ gamma  (N×K).
    betas = chars @ gamma  # N×K

    # Portfolio factor exposures: expo = Σ_i w_i β_i  (K).
    exposures = weights @ betas  # K

    # Factor covariance from the persisted K×T series (annualized). rowvar=True
    # because the worker persists factors on the ROWS (K×T) — see module docstr.
    if factor_returns.shape[1] < 2:
        raise ValueError(
            "factor_returns must have at least 2 periods to estimate a covariance"
        )
    factor_cov = np.cov(factor_returns, rowvar=True, ddof=1)  # K×K (scalar if K==1)
    factor_cov = np.atleast_2d(factor_cov)  # single factor → 1×1
    factor_cov = factor_cov * TRADING_DAYS_PER_YEAR

    sigma_f_expo = factor_cov @ exposures  # K
    systematic_var = float(exposures @ sigma_f_expo)

    # Specific (idiosyncratic) variance: Σ_i w_i² D_i.
    specific_var = float(np.sum((weights ** 2) * specific_variance))

    total_var = systematic_var + specific_var
    if total_var <= 0.0:
        raise ValueError(
            "assemble_factor_attribution is undefined: non-positive total variance"
        )

    # Per-factor Euler marginals: expo_k · (Σ_f expo)_k (sum to systematic_var).
    factor_marginals = exposures * sigma_f_expo  # K

    factor_contributions: list[dict[str, object]] = [
        {
            "factor_label": factor_names[k],
            "pct_contribution": round(float(factor_marginals[k] / total_var * 100), 6),
        }
        for k in range(K)
    ]

    return FactorAttribution(
        systematic_risk_pct=round(systematic_var / total_var * 100, 6),
        specific_risk_pct=round(specific_var / total_var * 100, 6),
        factor_contributions=factor_contributions,
        portfolio_exposures={
            factor_names[k]: round(float(exposures[k]), 6) for k in range(K)
        },
        r_squared=round(systematic_var / total_var, 6),
        factor_names=list(factor_names),
        fit_date=fit_date,
        k_factors=K,
    )


# ---------------------------------------------------------------------------
# Data-lake reads (read-only — factor_model_fits + equity_characteristics_monthly)
# ---------------------------------------------------------------------------

_LATEST_FIT_SQL = text("""
    SELECT fit_date, k_factors, gamma_loadings, factor_returns,
           oos_r_squared, converged, n_iterations
    FROM factor_model_fits
    WHERE engine = :engine AND asset_class = :asset_class
    ORDER BY fit_date DESC, created_at DESC
    LIMIT 1
""")

# Full latest cross-section (one row per instrument) — needed to reproduce the
# worker's per-period rank transform so the requested funds' characteristics
# land on the same [-0.5, +0.5] scale Gamma was fitted against.
_LATEST_CROSS_SECTION_SQL = text("""
    SELECT DISTINCT ON (instrument_id)
           instrument_id,
           size_log_mkt_cap, book_to_market, mom_12_1,
           quality_roa, investment_growth, profitability_gross
    FROM equity_characteristics_monthly
    ORDER BY instrument_id, as_of DESC
""")


async def fetch_latest_ipca_fit(datalake: AsyncSession) -> IpcaFit | None:
    """Most recent IPCA fit from factor_model_fits, or None if none exists."""
    row = (
        await datalake.execute(
            _LATEST_FIT_SQL, {"engine": _ENGINE, "asset_class": _ASSET_CLASS}
        )
    ).first()
    if row is None:
        return None
    gamma = np.asarray(row.gamma_loadings, dtype=float)  # L×K
    fr = row.factor_returns or {}
    values = fr.get("values", [])
    factor_returns = np.asarray(values, dtype=float)  # K×T
    factor_dates = [pd.Timestamp(d).date() for d in fr.get("dates", [])]
    return IpcaFit(
        fit_date=row.fit_date,
        k_factors=int(row.k_factors),
        gamma=gamma,
        factor_returns=factor_returns,
        factor_dates=factor_dates,
    )


async def _fetch_cross_section(datalake: AsyncSession) -> pd.DataFrame:
    """Latest characteristics for the WHOLE universe, indexed by instrument_id."""
    rows = (await datalake.execute(_LATEST_CROSS_SECTION_SQL)).all()
    if not rows:
        raise ValueError(
            "no characteristics in equity_characteristics_monthly — "
            "cannot rank-transform for factor attribution"
        )
    data = {col: [float(getattr(r, col)) for r in rows] for col in CHARS_COLS}
    index = pd.Index([r.instrument_id for r in rows], name="instrument_id")
    return pd.DataFrame(data, index=index)


def _rank_transform_cross_section(cross_section: pd.DataFrame) -> pd.DataFrame:
    """Reproduce the worker's transform: per-column rank(pct) - 0.5 → [-0.5, +0.5].

    The worker ranks WITHIN each monthly cross-section
    (factor_model.py::rank_transform, line 104). Here every row IS the latest
    cross-section (one as_of bucket per instrument), so a single rank across all
    instruments matches that semantics.
    """
    return cross_section.rank(pct=True) - 0.5


async def run_factor_attribution(
    datalake: AsyncSession,
    *,
    weights: dict[uuid.UUID, float],
) -> FactorAttribution:
    """Read the persisted IPCA fit + characteristics, then decompose risk.

    Parameters
    ----------
    datalake : AsyncSession
        Read-only TimescaleDB Cloud session (app.core.datalake).
    weights : dict[uuid.UUID, float]
        Portfolio weights keyed by fund instrument_id (fractions summing to ~1;
        the assemble step uses them as supplied, no renormalization).

    Raises
    ------
    ValueError
        If no IPCA fit is materialized, if any requested fund has no
        characteristics, or on degenerate / NaN data (fail loud → 422 at route).
    """
    if not weights:
        raise ValueError("run_factor_attribution requires at least one weighted fund")

    fit = await fetch_latest_ipca_fit(datalake)
    if fit is None:
        raise ValueError("no IPCA fit materialized in factor_model_fits")

    fund_ids = list(weights.keys())

    # Full latest cross-section → reproduce the worker's rank transform.
    cross_section = await _fetch_cross_section(datalake)
    ranked = _rank_transform_cross_section(cross_section)

    missing = [fid for fid in fund_ids if fid not in ranked.index]
    if missing:
        raise ValueError(
            f"missing characteristics for {len(missing)} fund(s): "
            + ", ".join(str(m) for m in missing)
        )

    chars_df = ranked.reindex(index=fund_ids, columns=CHARS_COLS)  # N×L
    chars = chars_df.to_numpy(dtype=float)
    weight_vec = np.array([float(weights[fid]) for fid in fund_ids], dtype=float)

    factor_names = [f"ipca_factor_{k + 1}" for k in range(fit.k_factors)]

    # Per-fund specific (idiosyncratic) variance proxy. The worker does NOT
    # persist Σ_f or per-fund residual variance D_i (confirmed against
    # factor_model.py::_upsert, lines 484-527 — it writes only gamma_loadings +
    # factor_returns + scalar stats). Until the worker is extended (see
    # open_questions), derive a strictly-positive D_i equal to the fund's own
    # systematic variance: D_i = Σ_k β_{i,k}² · Var_annualized(f_k). This keeps
    # specific_risk_pct > 0 and never NaN. The pure assemble_factor_attribution
    # accepts specific_variance explicitly, so the Euler math is unit-tested
    # independently of this proxy.
    betas = chars @ fit.gamma  # N×K
    factor_var = np.var(fit.factor_returns, axis=1, ddof=1) * TRADING_DAYS_PER_YEAR  # K
    systematic_per_fund = (betas ** 2) @ factor_var  # N
    specific_variance = np.where(
        systematic_per_fund > 0.0, systematic_per_fund, _SPECIFIC_VAR_FLOOR
    )

    return assemble_factor_attribution(
        weights=weight_vec,
        gamma=fit.gamma,
        chars=chars,
        factor_returns=fit.factor_returns,
        factor_names=factor_names,
        specific_variance=specific_variance,
        fit_date=fit.fit_date,
    )
