# Quant Port -- Tier 2 -- Nucleo institucional (otimizador, risco, fatores, backtest) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elevar o `light` ao padrao institucional: Sharpe robusto, risk budgeting por ETL, o eixo de restricoes/retorno do otimizador (bounds de bloco -> turnover -> CVaR-como-restricao -> CVaR por regime), atribuicao de fatores sobre o IPCA ja persistido, absorption ratio, backtest walk-forward, diagnosticos BL e projecoes Monte Carlo.

**Architecture:** Ports puros em numpy isolados (robust Sharpe, risk budgeting, Monte Carlo, episodios de drawdown) combinados com extensoes convexas do `optimizer/engine.py` em cvxpy (mantendo o gate G5) e novos services/readers DB-first sobre tabelas existentes do data-lake.

**Tech Stack:** Python 3.12, numpy, pandas, cvxpy (+SCS), scikit-learn (TimeSeriesSplit), scipy.stats (adicionar como dep), FastAPI.

**Contexto:** deriva do review comparativo `quant_engine` (legado) x `investintell-light`. Visao geral, ordem de execucao e dependencias cruzadas estao em `2026-06-14-quant-port-overview.md`.

---

## Convencoes do projeto (validas para todas as tasks)

- **Repos:** o app vive em `investintell-light` (`backend/`, pytest); tasks marcadas **`[repo: investintell-datalake-workers]`** vivem no repo separado de workers (calculo offline persistido no data-lake). O legado `investintell-allocation/backend/quant_engine` e **somente leitura** (fonte do algoritmo).
- **Escala:** todas as quantidades fracionarias sao fracoes decimais (`0.05` = 5%), nunca 0-100. NAV/AUM em unidades monetarias.
- **Fail-loud:** analytics puros levantam `ValueError` em dados insuficientes/NaN, nunca retornam NaN. Rotas mapeiam para HTTP 422.
- **Padrao analytics:** funcoes puras em `app/analytics/*.py`, testadas em frames sinteticos.
- **Padrao service:** `assemble_*` puro (sem I/O) + `run_*` async (warm EOD -> le DB -> chama assemble); rota fina valida -> run -> mapeia 422.
- **Gate G5 (mu-free):** retornos esperados existem APENAS em `app/optimizer/black_litterman.py` (posterior BL). Nenhum objetivo consome media amostral. min-CVaR (Rockafellar-Uryasev) e o objetivo default.
- **DB-first:** quant pesado/recorrente e calculado no repo de workers e lido pelo app via `app.core.datalake`.
- **Comando de teste:** `cd backend && python -m pytest tests/test_<arquivo>.py::<test> -v` (Python 3.12, `asyncio_mode=auto`).
- **Dependencia extra:** tasks que usam `scipy.stats` devem adiciona-lo explicitamente em `backend/pyproject.toml` (`scipy>=1.13`) -- hoje so e instalado transitivamente via scikit-learn.

---

## Indice de tasks

- **T2A** (5 tasks) -- #7 Robust Cornish-Fisher Sharpe
- **T2B** (5 tasks) -- #8 Risk budgeting por ETL (MCETL/PCETL/STARR), #19 Risk budgeting (variancia): MCTR + retornos implicitos
- **T2C** (8 tasks) -- #10 Restricoes de bloco/setor + bounds por ativo, #11 Penalidade de turnover/custo L1, #9 CVaR-como-restricao max-retorno (+SCS, verificador realizado), #13 CVaR condicional a regime
- **T2D** (5 tasks) -- #12 Backtest walk-forward (OOS)
- **T2E** (2 tasks) -- #14 Atribuicao de risco por fatores (sobre IPCA), #15 Absorption ratio Kritzman-Li
- **T2F** (3 tasks) -- #16 Expor outputs orfaos do worker (EVT/GARCH) em FundRiskOut, #17 Mandato->delta ladder com clamp, #18 Alerta 3-sigma He-Litterman (views vs prior)
- **T2G** (5 tasks) -- #20 Decomposicao de episodios de drawdown, #21 Monte Carlo block-bootstrap

---

## Tier 2 — Robust Cornish–Fisher Sharpe module

Port the legacy robust Sharpe (`E:/investintell-allocation/backend/quant_engine/scoring_components/robust_sharpe.py`, 270 LOC) into the Light app as a **pure analytics module** `backend/app/analytics/robust_sharpe.py`. It computes a skewness/kurtosis-aware (Cornish–Fisher) Sharpe ratio with a 95% confidence interval, using:

- **CF σ-scaling** (Favre–Galeano / Gregoriou–Gueyie modified-VaR): scale σ by the ratio of the Cornish–Fisher-expanded quantile to the normal quantile.
- **Opdyke (2007) closed-form SE** for the period Sharpe estimator's asymptotic variance.
- **Quenouille leave-one-out jackknife SE fallback** (Efron–Tibshirani §11.5) triggered when `T < 60` or `|skew| > 1.5` (or requested explicitly).
- **Tiered sample-size degradation**: `T < 12` (best-effort traditional only), `T < 36` (no CF), `T < 60` (jackknife CI).

This module is the **exception to the analytics fail-loud convention by deliberate design**: the legacy contract returns a `RobustSharpeResult` with NaN fields + `degraded=True` + `degraded_reason` rather than raising, because it is meant to score many funds in a batch where one short series must not abort the run. We port that behavior **verbatim from the legacy source** (it is a dataclass result, not a bare scalar, so it does not conflict with the `reject_nan` scalar contract used by `risk.py`). All tasks below test on synthetic numpy arrays, matching the legacy module's array-based signature (NOT pandas Series — the existing `risk.py` Series functions are unrelated). Scale contract holds: `returns` and `rf_rate` are decimal fractions (0.05 = 5%).

**Verification note (already done while hardening this plan):** the entire legacy module was copied into `backend/` and every test assertion below was executed against it. All pass EXCEPT the original draft's `ci_unavailable` test, which was found to be factually wrong (see open_questions) and has been replaced with a deterministic direct unit test of the `_jackknife_se` helper. The code blocks below are transcribed verbatim from the verified legacy source so the implementation steps reproduce a known-green module.

Dependency order: **T2A-1** (module skeleton + dependency + full-sample closed-form path) → **T2A-2** (CF adjustment direction + non-monotonic clamp) → **T2A-3** (jackknife fallback + auto-trigger) → **T2A-4** (tiered degradation + zero-vol + empty) → **T2A-5** (package export). Each task is independently committable and leaves the test suite green.

Run all commands from the `backend/` directory. Pytest is invoked as `python -m pytest ...` (confirmed: `testpaths = ["tests"]`, `asyncio_mode = "auto"` in `pyproject.toml` lines 52–54).

---

### Task T2A-1: Module skeleton + closed-form (Opdyke) full-sample path

**Files:**
- Create: `backend/app/analytics/robust_sharpe.py`
- Modify: `backend/pyproject.toml` (`[project].dependencies` array, lines 5–22 — add `scipy`)
- Test: `backend/tests/test_analytics_robust_sharpe.py`

- [ ] **Step 1: Promote scipy to a direct dependency.** In `backend/pyproject.toml`, the `[project].dependencies` array (lines 5–22) currently has `"scikit-learn>=1.9.0",` (line 19) immediately before `"redis>=8.0.0",` (line 20). scipy 1.17.1 is already resolved transitively (verified in `uv.lock` line 1359), but this module imports `scipy.stats` directly, so make it explicit. Change:

```toml
    "scikit-learn>=1.9.0",
    "redis>=8.0.0",
```

  to:

```toml
    "scikit-learn>=1.9.0",
    "scipy>=1.13",
    "redis>=8.0.0",
```

  (Only the `"scipy>=1.13",` line is new; the surrounding lines show context. No mypy change is needed — scipy is already in the `ignore_missing_imports` override at line 49.)

- [ ] **Step 2: Write the failing test** for the full-sample closed-form branch. Create `backend/tests/test_analytics_robust_sharpe.py` with:

```python
"""Tests for app.analytics.robust_sharpe (Cornish-Fisher robust Sharpe)."""

import math

import numpy as np
import pytest
from scipy import stats

from app.analytics.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)


def _normal_returns(n: int, mu: float = 0.01, sigma: float = 0.04, seed: int = 42) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(mu, sigma, n)


# --- full-sample closed-form path --------------------------------------------


def test_closed_form_full_sample_basic() -> None:
    """T=120 near-normal series: closed_form CI, not degraded, sane fields.

    The Opdyke variance is positive for a near-normal sample, so the CI is
    finite and centered on the traditional (annualized) Sharpe ratio.
    """
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0)
    assert isinstance(res, RobustSharpeResult)
    assert res.n_observations == 120
    assert res.ci_method == "closed_form"
    assert res.degraded is False
    assert res.degraded_reason is None
    # Traditional Sharpe equals mean/std * sqrt(12) computed independently.
    expected_sr = float(np.mean(r) / np.std(r, ddof=1) * math.sqrt(12))
    assert res.sharpe_traditional == expected_sr
    # CI brackets the point estimate.
    assert res.ci_lower_95 < res.sharpe_traditional < res.ci_upper_95
    # Moments match scipy unbiased estimators.
    assert res.skewness == float(stats.skew(r, bias=False))
    assert res.excess_kurtosis == float(stats.kurtosis(r, bias=False, fisher=True))
    # All fields finite for a healthy sample.
    for v in (
        res.sharpe_traditional,
        res.sharpe_cornish_fisher,
        res.ci_lower_95,
        res.ci_upper_95,
    ):
        assert math.isfinite(v)


def test_rf_none_treated_as_zero() -> None:
    """rf_rate=None must equal rf_rate=0.0 (legacy spec 1.3)."""
    r = _normal_returns(120)
    a = robust_sharpe(r, rf_rate=None)
    b = robust_sharpe(r, rf_rate=0.0)
    assert a.sharpe_traditional == b.sharpe_traditional
    assert a.sharpe_cornish_fisher == b.sharpe_cornish_fisher


def test_rf_rate_shifts_sharpe_down() -> None:
    """A positive per-period risk-free rate lowers excess return, hence Sharpe."""
    r = _normal_returns(120, mu=0.02)
    base = robust_sharpe(r, rf_rate=0.0)
    charged = robust_sharpe(r, rf_rate=0.01)
    assert charged.sharpe_traditional < base.sharpe_traditional


def test_periods_per_year_scales_traditional_sharpe() -> None:
    """Annualized Sharpe scales by sqrt(periods_per_year)."""
    r = _normal_returns(120)
    monthly = robust_sharpe(r, rf_rate=0.0, periods_per_year=12)
    daily = robust_sharpe(r, rf_rate=0.0, periods_per_year=252)
    assert daily.sharpe_traditional == pytest.approx(
        monthly.sharpe_traditional / math.sqrt(12) * math.sqrt(252)
    )
```

  (Note: `daily.sharpe_traditional` and the recomputed expression are mathematically identical but differ in float rounding because the daily path computes `sr_period * sqrt(252)` directly while the test divides by `sqrt(12)` first; `pytest.approx` is therefore used rather than `==`. `pytest` is imported at the top so later tasks can reuse it.)

- [ ] **Step 3: Run it, expect FAIL** (module does not exist yet):

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v
```

  Expected: collection error / `ModuleNotFoundError: No module named 'app.analytics.robust_sharpe'` on the `from app.analytics.robust_sharpe import ...` line.

- [ ] **Step 4: Write the minimal implementation.** Create `backend/app/analytics/robust_sharpe.py` with the constants, dataclass, CF/Opdyke/jackknife helpers, and the full-sample closed-form path. (The jackknife trigger logic and the degradation branches are added in later tasks; this file is built up incrementally but every task leaves it import-clean and green.) Paste the complete file as it stands after this task:

```python
"""Robust Sharpe Ratio (Cornish-Fisher + Opdyke CI).

Skewness/kurtosis-aware Sharpe ratio with a 95% confidence interval, ported
verbatim from the legacy quant engine
(quant_engine/scoring_components/robust_sharpe.py).

Unlike the scalar functions in app.analytics.risk (which fail loud with
ValueError), this module returns a RobustSharpeResult with NaN fields and a
``degraded`` flag on insufficient/degenerate data. That is the legacy batch
contract: scoring many funds must not abort because one series is too short.

Scale contract (project-wide): returns and the risk-free rate are decimal
fractions (0.05 = 5%), never 0-100.

References:
- Favre, L. & Galeano, J.-A. (2002) "Mean-Modified Value-at-Risk Optimization
  with Hedge Funds", JAI.
- Gregoriou, G. & Gueyie, J.-P. (2003) "Risk-Adjusted Performance of Funds of
  Hedge Funds Using a Modified Sharpe Ratio", JWM.
- Opdyke, J. (2007) "Comparing Sharpe Ratios: So Where Are the p-Values?", JFIM.

Pure function — no DB, no async, no I/O. Deterministic given inputs.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
from numpy.typing import NDArray
from scipy import stats

__all__ = ["RobustSharpeResult", "robust_sharpe"]


# T<36 degrades; jackknife trigger below T<60 or |skew|>1.5.
_MIN_OBS_TRADITIONAL = 12
_MIN_OBS_CORNISH_FISHER = 36
_JACKKNIFE_T_THRESHOLD = 60
_JACKKNIFE_SKEW_THRESHOLD = 1.5
_CI_Z_95 = 1.959963984540054  # stats.norm.ppf(0.975)


@dataclass(frozen=True)
class RobustSharpeResult:
    """Robust Sharpe output with Cornish-Fisher adjustment + Opdyke/jackknife CI."""

    sharpe_traditional: float
    sharpe_cornish_fisher: float
    ci_lower_95: float
    ci_upper_95: float
    skewness: float
    excess_kurtosis: float
    n_observations: int
    ci_method: Literal["closed_form", "jackknife"]
    degraded: bool
    degraded_reason: str | None


def _nan_result(
    *,
    n: int,
    reason: str,
    sharpe_traditional: float = float("nan"),
    skewness: float = float("nan"),
    excess_kurtosis: float = float("nan"),
) -> RobustSharpeResult:
    return RobustSharpeResult(
        sharpe_traditional=sharpe_traditional,
        sharpe_cornish_fisher=float("nan"),
        ci_lower_95=float("nan"),
        ci_upper_95=float("nan"),
        skewness=skewness,
        excess_kurtosis=excess_kurtosis,
        n_observations=n,
        ci_method="closed_form",
        degraded=True,
        degraded_reason=reason,
    )


def _cornish_fisher_z(z: float, skew: float, excess_kurt: float) -> float:
    """Cornish-Fisher expansion of the standard-normal quantile ``z``.

    z_CF = z + (z^2 - 1)/6 * S + (z^3 - 3z)/24 * K - (2z^3 - 5z)/36 * S^2
    where S is skewness and K is excess kurtosis.
    """
    return (
        z
        + (z * z - 1.0) / 6.0 * skew
        + (z * z * z - 3.0 * z) / 24.0 * excess_kurt
        - (2.0 * z * z * z - 5.0 * z) / 36.0 * (skew * skew)
    )


def _opdyke_variance(sr_period: float, skew: float, excess_kurt: float, T: int) -> float:
    """Opdyke (2007) closed-form asymptotic variance of the *period* Sharpe.

    Uses period SR (not annualized). ``excess_kurt`` is already Fisher
    (full kurtosis - 3), so the (K-3)/4 * SR^2 term is excess_kurt/4 * SR^2.
    """
    return (
        1.0
        + 0.5 * sr_period * sr_period
        - skew * sr_period
        + (excess_kurt / 4.0) * sr_period * sr_period
    ) / T


def _jackknife_se(excess_returns: "NDArray[Any]", periods_per_year: int) -> float:
    """Leave-one-out (Quenouille) jackknife SE for the *annualized* Sharpe.

    SE = sqrt((T - 1) * var_pop), where var_pop is the population variance of
    the leave-one-out Sharpe replicates around their mean (Efron-Tibshirani
    11.5). Returns NaN if fewer than 3 finite replicates survive.
    """
    T = excess_returns.size
    sum_all = float(excess_returns.sum())
    sumsq_all = float(np.square(excess_returns).sum())
    sqrt_ann = float(np.sqrt(periods_per_year))
    loo = np.empty(T)
    for i in range(T):
        n = T - 1
        s = sum_all - float(excess_returns[i])
        ss = sumsq_all - float(excess_returns[i]) ** 2
        mean_i = s / n
        var_i = (ss - n * mean_i * mean_i) / (n - 1)  # sample variance, ddof=1
        if var_i <= 0.0:
            loo[i] = float("nan")
        else:
            loo[i] = mean_i / float(np.sqrt(var_i)) * sqrt_ann
    loo = loo[np.isfinite(loo)]
    if loo.size < 3:
        return float("nan")
    var_pop = float(np.var(loo, ddof=0))
    return float(np.sqrt((T - 1) * var_pop))


def robust_sharpe(
    returns: "NDArray[Any]",
    rf_rate: float | None,
    ci_method: str = "closed_form",
    alpha_cf: float = 0.05,
    periods_per_year: int = 12,
) -> RobustSharpeResult:
    """Compute the robust (Cornish-Fisher adjusted) Sharpe ratio with a 95% CI.

    Args:
        returns: Periodic (typically monthly) return series. NaNs/infs are
            stripped before computation.
        rf_rate: Per-period risk-free rate. ``None`` is treated as 0.
        ci_method: ``"closed_form"`` (default) or ``"jackknife"``. Closed form
            auto-falls-back to jackknife when ``T < 60`` or ``|skew| > 1.5``.
        alpha_cf: Tail probability for the Cornish-Fisher quantile. Default 0.05.
        periods_per_year: Annualization factor (12 monthly, 252 daily).

    Returns:
        ``RobustSharpeResult`` with traditional + robust values, degradation
        flags, and CI bounds. Degenerate inputs yield NaN fields with
        ``degraded=True`` rather than raising.
    """
    arr = np.asarray(returns, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    T = int(arr.size)
    rf = 0.0 if rf_rate is None else float(rf_rate)

    excess = arr - rf
    mean = float(np.mean(excess))
    std_returns = float(np.std(arr, ddof=1))
    sqrt_ann = float(np.sqrt(periods_per_year))

    sr_period = mean / std_returns  # per-period Sharpe (not annualized)
    sr_traditional = sr_period * sqrt_ann

    skew = float(stats.skew(arr, bias=False))
    excess_kurt = float(stats.kurtosis(arr, bias=False, fisher=True))

    # Cornish-Fisher adjusted Sharpe via modified-VaR scaling of sigma.
    z = float(stats.norm.ppf(alpha_cf))
    z_cf = _cornish_fisher_z(z, skew, excess_kurt)
    sigma_cf = (z_cf / z) * std_returns
    sr_cf = mean / sigma_cf * sqrt_ann

    # Closed-form (Opdyke) CI.
    var_period = _opdyke_variance(sr_period, skew, excess_kurt, T)
    se_ann = float(np.sqrt(var_period)) * sqrt_ann
    method: Literal["closed_form", "jackknife"] = "closed_form"

    ci_lower = sr_traditional - _CI_Z_95 * se_ann
    ci_upper = sr_traditional + _CI_Z_95 * se_ann

    return RobustSharpeResult(
        sharpe_traditional=sr_traditional,
        sharpe_cornish_fisher=sr_cf,
        ci_lower_95=ci_lower,
        ci_upper_95=ci_upper,
        skewness=skew,
        excess_kurtosis=excess_kurt,
        n_observations=T,
        ci_method=method,
        degraded=False,
        degraded_reason=None,
    )
```

  Note: `_nan_result` and `_jackknife_se` are defined now (unused by `robust_sharpe`'s body until T2A-3/T2A-4) so later tasks only modify `robust_sharpe`'s body, not the helpers. Ruff F811/F401 do not flag a defined-but-not-yet-called module-level function, so this is lint-clean. `_jackknife_se` is also unit-tested directly in T2A-3.

- [ ] **Step 5: Run tests, expect PASS:**

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v
```

  Expected: 4 passed (`test_closed_form_full_sample_basic`, `test_rf_none_treated_as_zero`, `test_rf_rate_shifts_sharpe_down`, `test_periods_per_year_scales_traditional_sharpe`).

- [ ] **Step 6: Commit:**

```
cd backend && git add app/analytics/robust_sharpe.py tests/test_analytics_robust_sharpe.py pyproject.toml && git commit -m "feat(analytics): robust Sharpe module — closed-form (Opdyke) full-sample path

Port the EDHEC robust (Cornish-Fisher) Sharpe from the legacy quant engine.
This commit lands the module skeleton, RobustSharpeResult dataclass, the
Cornish-Fisher quantile expansion, Opdyke closed-form variance, the
leave-one-out jackknife helper, plus the full-sample closed_form CI path.
scipy promoted to a direct dependency."
```

---

### Task T2A-2: Cornish–Fisher adjustment direction + non-monotonic clamp

**Files:**
- Modify: `backend/app/analytics/robust_sharpe.py` (the CF block inside `robust_sharpe`: the two lines `sigma_cf = (z_cf / z) * std_returns` / `sr_cf = mean / sigma_cf * sqrt_ann`, and the final `return RobustSharpeResult(...)` degradation args)
- Test: `backend/tests/test_analytics_robust_sharpe.py` (append)

- [ ] **Step 1: Write the failing tests** for the CF direction (negative skew penalizes, positive skew rewards) and the non-monotonic clamp (extreme skew/kurtosis pushes the CF left-tail quantile non-negative → clamp + `degraded=True`, `degraded_reason="cornish_fisher_non_monotonic"`). Append to `backend/tests/test_analytics_robust_sharpe.py`:

```python
# --- Cornish-Fisher adjustment direction -------------------------------------


def _left_tailed_returns() -> np.ndarray:
    """T=80 series with mild NEGATIVE skew (downside outliers)."""
    rng = np.random.default_rng(5)
    body = rng.standard_normal(78) * 0.02 + 0.008
    return np.concatenate([body, [-0.08, -0.10]])


def _right_tailed_returns() -> np.ndarray:
    """T=80 series with mild POSITIVE skew (upside outliers)."""
    rng = np.random.default_rng(5)
    body = rng.standard_normal(78) * 0.02 + 0.008
    return np.concatenate([body, [0.10, 0.12]])


def test_negative_skew_penalizes_cf_sharpe() -> None:
    """Left-tail risk inflates the CF sigma, so CF Sharpe < traditional Sharpe.

    skew(_left_tailed_returns()) ~ -1.31 (verified), z_cf ~ -1.88 (still
    negative, NOT clamped), so the comparison reflects the genuine CF math.
    """
    res = robust_sharpe(_left_tailed_returns(), rf_rate=0.0)
    assert res.skewness < 0
    assert res.sharpe_cornish_fisher < res.sharpe_traditional


def test_positive_skew_rewards_cf_sharpe() -> None:
    """Right-tail upside shrinks the CF sigma, so CF Sharpe > traditional.

    skew(_right_tailed_returns()) ~ +1.90 (verified) so |skew|>1.5 auto-routes
    the CI to jackknife, but z_cf ~ -0.90 stays negative (NOT clamped) so the
    CF point estimate is the genuine expansion; only the CI method differs.
    """
    res = robust_sharpe(_right_tailed_returns(), rf_rate=0.0)
    assert res.skewness > 0
    assert res.sharpe_cornish_fisher > res.sharpe_traditional


def test_symmetric_returns_cf_close_to_traditional() -> None:
    """Near-symmetric mesokurtic series: CF Sharpe ~ traditional Sharpe."""
    rng = np.random.default_rng(11)
    r = rng.normal(0.0, 0.03, 200)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.sharpe_cornish_fisher == pytest.approx(res.sharpe_traditional, rel=0.25)


# --- non-monotonic Cornish-Fisher clamp --------------------------------------


def test_cornish_fisher_non_monotonic_clamp() -> None:
    """Extreme positive skew/kurtosis makes z_CF >= 0 (the quantile expansion
    is non-monotonic). The module clamps sigma_CF to keep CF Sharpe finite and
    flags the result as degraded with reason 'cornish_fisher_non_monotonic'."""
    # 39 flat points + one huge positive outlier => skew ~ 6.33, excess kurt ~ 40
    # (verified). std is nonzero (the outlier), so the zero-vol guard does not
    # fire; T=40 >= 36 so CF is computed and z_cf ~ +1.71 >= 0 triggers the clamp.
    arr = np.array([0.01] * 39 + [2.0], dtype=float)
    res = robust_sharpe(arr, rf_rate=0.0)
    assert res.n_observations == 40
    assert res.degraded is True
    assert res.degraded_reason == "cornish_fisher_non_monotonic"
    # CF Sharpe stays finite despite the clamp.
    assert math.isfinite(res.sharpe_cornish_fisher)
    # Traditional Sharpe is still reported and finite.
    assert math.isfinite(res.sharpe_traditional)
```

- [ ] **Step 2: Run them, expect FAIL.** `test_cornish_fisher_non_monotonic_clamp` fails because the current code computes `sigma_cf = (z_cf / z) * std_returns` with a positive `z_cf` and negative `z`, producing a negative `sigma_cf` (→ negative CF Sharpe) and never sets `degraded`/`degraded_reason`:

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v -k "non_monotonic or skew or symmetric"
```

  Expected: `test_cornish_fisher_non_monotonic_clamp` FAILS on `assert res.degraded is True` (currently `False`). The three direction tests already pass (the CF math is correct for in-range skew, verified: z_cf stays negative for both the left and right tail fixtures); the clamp test is the gate.

- [ ] **Step 3: Implement the clamp.** In `backend/app/analytics/robust_sharpe.py`, replace the two CF lines:

```python
    sigma_cf = (z_cf / z) * std_returns
    sr_cf = mean / sigma_cf * sqrt_ann
```

  with the clamp-aware block (transcribed from the legacy source):

```python
    # z (left tail) is negative; z_cf must stay negative for sigma_cf > 0. If
    # extreme skew/kurtosis pushes it non-negative, the quantile expansion is
    # non-monotonic — clamp z_cf to a small negative multiple of z and flag.
    cf_non_monotonic = z_cf >= 0.0
    if cf_non_monotonic:
        z_cf_clamped = -0.01 * abs(z)
        sigma_cf = (z_cf_clamped / z) * std_returns
    else:
        sigma_cf = (z_cf / z) * std_returns
    sr_cf = mean / sigma_cf * sqrt_ann
```

  Then wire the degradation flag through the final `return RobustSharpeResult(...)`. Change its last three arguments:

```python
        ci_method=method,
        degraded=False,
        degraded_reason=None,
    )
```

  to:

```python
        ci_method=method,
        degraded=cf_non_monotonic,
        degraded_reason="cornish_fisher_non_monotonic" if cf_non_monotonic else None,
    )
```

  (The CI-availability degradation reason is layered on top of this in Task T2A-3.)

- [ ] **Step 4: Run tests, expect PASS:**

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v
```

  Expected: all prior tests plus the 4 new ones pass (`test_negative_skew_penalizes_cf_sharpe`, `test_positive_skew_rewards_cf_sharpe`, `test_symmetric_returns_cf_close_to_traditional`, `test_cornish_fisher_non_monotonic_clamp`).

- [ ] **Step 5: Commit:**

```
cd backend && git add app/analytics/robust_sharpe.py tests/test_analytics_robust_sharpe.py && git commit -m "feat(analytics): robust Sharpe — CF sigma scaling + non-monotonic clamp

Negative skew (left-tail risk) inflates the CF sigma and penalizes the CF
Sharpe; positive skew rewards it. Extreme skew/kurtosis that makes the CF
quantile non-monotonic (z_CF >= 0) is clamped and flagged degraded with
reason 'cornish_fisher_non_monotonic'."
```

---

### Task T2A-3: Quenouille jackknife SE auto-trigger + method selection

**Files:**
- Modify: `backend/app/analytics/robust_sharpe.py` (replace the closed-form-only CI block with method selection; restructure the trailing degradation wiring)
- Test: `backend/tests/test_analytics_robust_sharpe.py` (append)

> The `_jackknife_se` helper already exists (added in T2A-1). This task wires it into `robust_sharpe`'s CI-method selection and adds a deterministic direct unit test of the helper. **The original draft's `test_jackknife_degenerate_se_marks_ci_unavailable` test was REMOVED** — it asserted an outcome the verified port does not produce (`[0.01]*35 + [0.01000001]` yields 35 finite jackknife replicates and `degraded_reason == "cornish_fisher_non_monotonic"`, not `"ci_unavailable"`). The genuinely-reachable NaN-SE path is tested directly on the helper instead (see open_questions for why the end-to-end path is floating-point-fragile).

- [ ] **Step 1: Write the failing tests** for: (a) `ci_method="jackknife"` returns `ci_method == "jackknife"`; (b) auto-fallback when `T < 60`; (c) auto-fallback when `|skew| > 1.5`; (d) closed-form retained for `T >= 60` and `|skew| <= 1.5`; (e) the `_jackknife_se` helper returns NaN deterministically when fewer than 3 finite replicates survive. Append to `backend/tests/test_analytics_robust_sharpe.py`:

```python
# --- jackknife SE fallback ----------------------------------------------------


def test_explicit_jackknife_method() -> None:
    """Requesting jackknife yields a jackknife CI even for a large sample."""
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0, ci_method="jackknife")
    assert res.ci_method == "jackknife"
    assert math.isfinite(res.ci_lower_95)
    assert math.isfinite(res.ci_upper_95)
    assert res.ci_lower_95 < res.sharpe_traditional < res.ci_upper_95


def test_auto_jackknife_when_T_below_60() -> None:
    """T=48 (>= 36, so CF computed) auto-falls-back to jackknife for the CI."""
    r = _normal_returns(48, seed=3)
    res = robust_sharpe(r, rf_rate=0.0)  # default ci_method="closed_form"
    assert res.n_observations == 48
    assert res.ci_method == "jackknife"
    assert math.isfinite(res.sharpe_cornish_fisher)  # CF still available at T>=36
    assert math.isfinite(res.ci_lower_95)


def test_auto_jackknife_when_skew_extreme() -> None:
    """|skew| > 1.5 on a large sample forces jackknife even when T >= 60."""
    rng = np.random.default_rng(9)
    body = rng.standard_normal(98) * 0.02 + 0.01
    r = np.concatenate([body, [0.5, 0.6]])  # heavy right tail -> |skew| ~ 6.39
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.n_observations == 100
    assert abs(res.skewness) > 1.5
    assert res.ci_method == "jackknife"


def test_closed_form_retained_for_large_low_skew() -> None:
    """T=120, near-symmetric: stays closed_form (control for the triggers above)."""
    r = _normal_returns(120)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.ci_method == "closed_form"
    assert abs(res.skewness) <= 1.5
    assert res.n_observations >= 60


def test_jackknife_se_all_constant_returns_nan() -> None:
    """_jackknife_se returns NaN when fewer than 3 finite replicates survive.

    For an exactly-constant array every leave-one-out subset is constant, so
    every replicate variance is 0 -> every replicate is NaN -> < 3 finite ->
    SE is NaN. This is the deterministic unit of the degenerate-CI path
    (the end-to-end robust_sharpe path is floating-point-fragile; see the
    cluster open_questions). Note the helper has NO zero-vol guard — that guard
    lives in robust_sharpe, added in Task T2A-4 — so the helper is exercised
    directly here.
    """
    from app.analytics.robust_sharpe import _jackknife_se

    se = _jackknife_se(np.array([0.5] * 10, dtype=float), periods_per_year=12)
    assert math.isnan(se)
    # A healthy small sample yields a finite, positive SE.
    healthy = _normal_returns(48, seed=1)
    se_ok = _jackknife_se(healthy, periods_per_year=12)
    assert math.isfinite(se_ok)
    assert se_ok > 0.0
```

- [ ] **Step 2: Run them, expect FAIL.** The current module always returns `ci_method="closed_form"` and never selects jackknife, so the method-selection tests fail (the `_jackknife_se` helper test already passes because the helper was defined in T2A-1):

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v -k "jackknife or closed_form_retained"
```

  Expected: `test_explicit_jackknife_method`, `test_auto_jackknife_when_T_below_60`, `test_auto_jackknife_when_skew_extreme` FAIL (method is `closed_form`); `test_closed_form_retained_for_large_low_skew` and `test_jackknife_se_all_constant_returns_nan` PASS.

- [ ] **Step 3: Implement method selection.** In `robust_sharpe`, replace the closed-form-only CI block:

```python
    # Closed-form (Opdyke) CI.
    var_period = _opdyke_variance(sr_period, skew, excess_kurt, T)
    se_ann = float(np.sqrt(var_period)) * sqrt_ann
    method: Literal["closed_form", "jackknife"] = "closed_form"

    ci_lower = sr_traditional - _CI_Z_95 * se_ann
    ci_upper = sr_traditional + _CI_Z_95 * se_ann
```

  with method selection + fallback (transcribed from the legacy source):

```python
    # CI method selection / auto-fallback.
    requested = ci_method if ci_method in {"closed_form", "jackknife"} else "closed_form"
    use_jackknife = (
        requested == "jackknife"
        or T < _JACKKNIFE_T_THRESHOLD
        or abs(skew) > _JACKKNIFE_SKEW_THRESHOLD
    )
    method: Literal["closed_form", "jackknife"]
    if use_jackknife:
        se_ann = _jackknife_se(excess, periods_per_year)
        method = "jackknife"
    else:
        var_period = _opdyke_variance(sr_period, skew, excess_kurt, T)
        if var_period <= 0.0 or not np.isfinite(var_period):
            se_ann = float("nan")
        else:
            se_ann = float(np.sqrt(var_period)) * sqrt_ann
        method = "closed_form"

    if np.isfinite(se_ann):
        ci_lower = sr_traditional - _CI_Z_95 * se_ann
        ci_upper = sr_traditional + _CI_Z_95 * se_ann
    else:
        ci_lower = float("nan")
        ci_upper = float("nan")
```

  Then restructure the trailing degradation wiring so `ci_unavailable` layers on top of the CF clamp flag from Task T2A-2. Insert this block immediately BEFORE the final `return RobustSharpeResult(`:

```python
    degraded = cf_non_monotonic or not np.isfinite(se_ann)
    reason: str | None
    if cf_non_monotonic:
        reason = "cornish_fisher_non_monotonic"
    elif not np.isfinite(se_ann):
        reason = "ci_unavailable"
    else:
        reason = None
```

  and change the final `return`'s last three arguments from:

```python
        ci_method=method,
        degraded=cf_non_monotonic,
        degraded_reason="cornish_fisher_non_monotonic" if cf_non_monotonic else None,
    )
```

  to:

```python
        ci_method=method,
        degraded=degraded,
        degraded_reason=reason,
    )
```

- [ ] **Step 4: Run tests, expect PASS:**

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v
```

  Expected: all tests pass, including the 5 new jackknife tests. (`test_closed_form_full_sample_basic` and `test_periods_per_year_scales_traditional_sharpe` use `_normal_returns(120)` which is T>=60 and near-symmetric, so they remain `closed_form` — still green. `test_negative_skew_penalizes_cf_sharpe` / `test_positive_skew_rewards_cf_sharpe` now route to jackknife for their CI but their assertions only touch the CF point estimate, so they stay green.)

- [ ] **Step 5: Commit:**

```
cd backend && git add app/analytics/robust_sharpe.py tests/test_analytics_robust_sharpe.py && git commit -m "feat(analytics): robust Sharpe — Quenouille jackknife SE fallback

Wire the leave-one-out jackknife SE into CI-method selection with auto-fallback
(T<60 or |skew|>1.5, or explicit ci_method='jackknife'). A degenerate jackknife
(<3 finite replicates) or non-finite Opdyke variance yields NaN CI bounds
flagged degraded with reason 'ci_unavailable'."
```

---

### Task T2A-4: Tiered sample-size degradation, zero-volatility and empty inputs

**Files:**
- Modify: `backend/app/analytics/robust_sharpe.py` (add the early-exit tier guards inside `robust_sharpe`)
- Test: `backend/tests/test_analytics_robust_sharpe.py` (append)

- [ ] **Step 1: Write the failing tests** for the degradation tiers: `T == 0` (all-NaN/empty), `T < 12` (best-effort traditional, NaN CF), `12 <= T < 36` (traditional computed, no CF), and zero-volatility (constant returns → signed-infinity traditional Sharpe, no division-by-zero crash). Append to `backend/tests/test_analytics_robust_sharpe.py`:

```python
# --- tiered sample-size degradation ------------------------------------------


def test_empty_input_is_degraded_all_nan() -> None:
    """T=0 (empty or all-NaN) -> fully degraded, reason 'all_nan_or_empty'."""
    res = robust_sharpe(np.array([], dtype=float), rf_rate=0.0)
    assert res.n_observations == 0
    assert res.degraded is True
    assert res.degraded_reason == "all_nan_or_empty"
    assert math.isnan(res.sharpe_traditional)
    assert math.isnan(res.sharpe_cornish_fisher)


def test_all_nan_input_is_degraded() -> None:
    """A series of only NaNs strips to length 0."""
    res = robust_sharpe(np.array([float("nan")] * 20), rf_rate=0.0)
    assert res.n_observations == 0
    assert res.degraded_reason == "all_nan_or_empty"


def test_nans_are_stripped_then_counted() -> None:
    """Interior NaNs are dropped; n_observations counts only finite points."""
    rng = np.random.default_rng(2)
    clean = rng.normal(0.01, 0.04, 100)
    dirty = np.insert(clean, [10, 50, 90], np.nan)
    res = robust_sharpe(dirty, rf_rate=0.0)
    assert res.n_observations == 100


def test_below_12_best_effort_traditional_only() -> None:
    """T<12: traditional Sharpe is best-effort finite; CF/CI are NaN and the
    result is degraded with reason 'insufficient_observations'."""
    arr = np.array([0.01, 0.02, -0.01, 0.03, 0.0, 0.015, -0.005, 0.02], dtype=float)
    res = robust_sharpe(arr, rf_rate=0.0)
    assert res.n_observations == 8
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_observations"
    assert math.isfinite(res.sharpe_traditional)
    assert math.isnan(res.sharpe_cornish_fisher)
    assert math.isnan(res.ci_lower_95)


def test_between_12_and_36_no_cornish_fisher() -> None:
    """12 <= T < 36: traditional Sharpe and moments are computed, but CF is
    not (insufficient observations for a stable expansion)."""
    r = _normal_returns(24, seed=4)
    res = robust_sharpe(r, rf_rate=0.0)
    assert res.n_observations == 24
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_observations"
    assert math.isfinite(res.sharpe_traditional)
    assert math.isfinite(res.skewness)
    assert math.isfinite(res.excess_kurtosis)
    assert math.isnan(res.sharpe_cornish_fisher)


def test_zero_volatility_positive_mean_is_plus_inf() -> None:
    """Constant positive returns: zero vol -> +inf traditional Sharpe, degraded
    with reason 'zero_volatility', no division-by-zero crash."""
    res = robust_sharpe(np.array([0.02] * 40, dtype=float), rf_rate=0.0)
    assert res.n_observations == 40
    assert res.degraded is True
    assert res.degraded_reason == "zero_volatility"
    assert res.sharpe_traditional == float("inf")
    assert res.skewness == 0.0
    assert res.excess_kurtosis == 0.0


def test_zero_volatility_negative_mean_is_minus_inf() -> None:
    """Constant zero return with a positive rf -> negative excess -> -inf."""
    res = robust_sharpe(np.array([0.0] * 40, dtype=float), rf_rate=0.01)
    assert res.sharpe_traditional == float("-inf")
    assert res.degraded_reason == "zero_volatility"
```

  (Fixture note, verified against numpy: `np.std([0.02]*40, ddof=1)` and `np.std([0.0]*40, ddof=1)` are both EXACTLY `0.0`, so they deterministically trigger the zero-vol guard. Do NOT use `[0.01]*N` here — `np.std` of identical 0.01 values is a tiny nonzero residue at some N and would slip past the guard; see cluster open_questions.)

- [ ] **Step 2: Run them, expect FAIL.** The current `robust_sharpe` has no early guards: an empty array makes `np.mean([])` emit a warning and `mean/std_returns` divides by NaN/0, so these tests fail (NaN propagation or missing `degraded_reason`):

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v -k "empty or all_nan or stripped or best_effort or between_12 or zero_volatility"
```

  Expected: the new tier/zero-vol tests FAIL (no `degraded_reason` set, or division-by-zero produces NaN instead of signed infinity).

- [ ] **Step 3: Add the tier guards.** In `backend/app/analytics/robust_sharpe.py`, the input-prep lines are:

```python
    arr = np.asarray(returns, dtype=float).ravel()
    arr = arr[np.isfinite(arr)]
    T = int(arr.size)
    rf = 0.0 if rf_rate is None else float(rf_rate)
```

  Immediately AFTER those four lines and BEFORE `excess = arr - rf`, insert the T<12 guard (transcribed from the legacy source):

```python
    if T < _MIN_OBS_TRADITIONAL:
        if T == 0:
            return _nan_result(n=0, reason="all_nan_or_empty")
        # T<12 still emits a best-effort traditional Sharpe.
        excess_be = arr - rf
        mean_be = float(np.mean(excess_be))
        std_be = float(np.std(arr, ddof=1)) if T > 1 else 0.0
        sqrt_ann_be = float(np.sqrt(periods_per_year))
        sr_trad_be = (mean_be / std_be * sqrt_ann_be) if std_be > 0 else float("nan")
        return _nan_result(
            n=T,
            reason="insufficient_observations",
            sharpe_traditional=sr_trad_be,
        )
```

  Next, the existing lines compute `excess`, `mean`, `std_returns`, `sqrt_ann`. Immediately AFTER `sqrt_ann = float(np.sqrt(periods_per_year))` and BEFORE `sr_period = mean / std_returns`, insert the zero-volatility guard:

```python
    if std_returns == 0.0 or not np.isfinite(std_returns):
        signed = (
            float("inf")
            if mean > 0
            else (float("-inf") if mean < 0 else float("nan"))
        )
        return _nan_result(
            n=T,
            reason="zero_volatility",
            sharpe_traditional=signed,
            skewness=0.0,
            excess_kurtosis=0.0,
        )
```

  Finally, the moments are computed at:

```python
    skew = float(stats.skew(arr, bias=False))
    excess_kurt = float(stats.kurtosis(arr, bias=False, fisher=True))
```

  Immediately AFTER those two lines and BEFORE the Cornish-Fisher block (`z = float(stats.norm.ppf(alpha_cf))`), insert the `12 <= T < 36` (no-CF) guard:

```python
    if T < _MIN_OBS_CORNISH_FISHER:
        return _nan_result(
            n=T,
            reason="insufficient_observations",
            sharpe_traditional=sr_traditional,
            skewness=skew,
            excess_kurtosis=excess_kurt,
        )
```

  (`_nan_result` was defined in Task T2A-1 and is now exercised by all four early-exit branches.)

- [ ] **Step 4: Run tests, expect PASS:**

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py -v
```

  Expected: every test passes (full-sample, CF direction/clamp, jackknife/helper, and the 7 new degradation/zero-vol tests).

- [ ] **Step 5: Commit:**

```
cd backend && git add app/analytics/robust_sharpe.py tests/test_analytics_robust_sharpe.py && git commit -m "feat(analytics): robust Sharpe — tiered degradation + zero-vol guards

Add the EDHEC sample-size tiers: T=0 (all_nan_or_empty), T<12 (best-effort
traditional only), 12<=T<36 (no Cornish-Fisher), plus a zero-volatility
guard that returns signed infinity instead of dividing by zero. Degenerate
inputs are flagged degraded with an explicit reason rather than raising."
```

---

### Task T2A-5: Package export from app.analytics

**Files:**
- Modify: `backend/app/analytics/__init__.py` (add an import block after the `from app.analytics.risk import (...)` block that ends at line 40; add two names to `__all__`, lines 47–77)
- Test: `backend/tests/test_analytics_robust_sharpe.py` (append a package-level import test)

- [ ] **Step 1: Write the failing test** asserting the public symbols are re-exported from the package root (matching how every other test imports, e.g. `from app.analytics import historical_var`). Append to `backend/tests/test_analytics_robust_sharpe.py`:

```python
# --- package export -----------------------------------------------------------


def test_exported_from_app_analytics() -> None:
    """robust_sharpe and RobustSharpeResult are importable from app.analytics."""
    import app.analytics as analytics

    assert hasattr(analytics, "robust_sharpe")
    assert hasattr(analytics, "RobustSharpeResult")
    assert "robust_sharpe" in analytics.__all__
    assert "RobustSharpeResult" in analytics.__all__

    from app.analytics import RobustSharpeResult as RS
    from app.analytics import robust_sharpe as rs

    res = rs(_normal_returns(120), rf_rate=0.0)
    assert isinstance(res, RS)
```

- [ ] **Step 2: Run it, expect FAIL** (`app.analytics` does not yet re-export the symbols):

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py::test_exported_from_app_analytics -v
```

  Expected: FAIL on `assert hasattr(analytics, "robust_sharpe")` (AttributeError / False).

- [ ] **Step 3: Add the re-exports.** In `backend/app/analytics/__init__.py`, the `from app.analytics.risk import (...)` block ends at line 40 with `)`, and the `from app.analytics.rolling import (...)` block follows at lines 41–45. Insert the new import block immediately AFTER line 45 (`)` of the rolling import, just before the blank line that precedes `__all__`):

```python
from app.analytics.robust_sharpe import (
    RobustSharpeResult,
    robust_sharpe,
)
```

  Then add the two names to `__all__` (lines 47–77). The existing list places capitalized names first; `RobustSharpeResult` (capital R) goes among them — insert it after `"MIN_IN_RANGE_RETURNS",` (line 52):

```python
    "MIN_IN_RANGE_RETURNS",
    "RobustSharpeResult",
    "align_returns",
```

  and insert `"robust_sharpe",` among the lowercase names. The relevant existing run is `"return_histogram",` (line 68) → `"risk_contributions",` (line 69) → `"rolling_beta",` (line 70). Since "robust" sorts after "risk" but before "rolling", insert it between them:

```python
    "return_histogram",
    "risk_contributions",
    "robust_sharpe",
    "rolling_beta",
```

- [ ] **Step 4: Run the full analytics suite, expect PASS:**

```
cd backend && python -m pytest tests/test_analytics_robust_sharpe.py tests/test_analytics_risk.py -v
```

  Expected: all robust-Sharpe tests pass (including `test_exported_from_app_analytics`) and the existing 27 risk tests stay green (confirming the new import did not break the package).

- [ ] **Step 5: Lint + commit.** Verify the new module, test, and `__init__.py` are clean, then commit:

```
cd backend && python -m ruff check app/analytics/robust_sharpe.py tests/test_analytics_robust_sharpe.py app/analytics/__init__.py && git add app/analytics/__init__.py tests/test_analytics_robust_sharpe.py && git commit -m "feat(analytics): export robust_sharpe + RobustSharpeResult from app.analytics

Re-export the robust Cornish-Fisher Sharpe from the analytics package root so
callers import it the same way as the other risk statistics."
```

---

## Tier 2 — Risk budgeting: ETL-based (MCETL/PCETL/STARR) + variance MCTR & Sharpe-implied returns

This cluster delivers a new pure-numpy analytics module `backend/app/analytics/risk_budgeting.py` that operates on the same T×N daily scenario matrix the optimizer already assembles (`app.services.portfolio_builder` builds it at `backend/app/services/portfolio_builder.py:249` as `scenarios = frame.to_numpy(dtype=float)`, where `frame` comes from `app.optimizer.data.load_aligned_returns(...)` at `portfolio_builder.py:241`). It provides two Euler decompositions of portfolio risk into per-asset contributions plus their implied-return duals:

1. **Variance (MCTR/PCTR) + Sharpe-implied returns** — the standard Euler decomposition of portfolio volatility, reusing the exact identity already encoded in `app.analytics.portfolio.risk_contributions` (`backend/app/analytics/portfolio.py:244-280`: `σ_w = Σw`, `CTR_i = w_i (Σw)_i / σ²_p`, sums to 1). Implied returns require an EXPLICIT BL μ and risk-free rate (gate G5: never a sample mean).
2. **Tail / Expected-Shortfall (MCETL/PCETL) + STARR + ETL-implied returns** — the Euler decomposition of historical Expected Shortfall (ETL ≡ CVaR), computed as the per-asset average of asset returns over the scenarios that constitute the portfolio loss tail. By construction these sum EXACTLY to the total ES (Tasche 2002), which is the dispatch's "contributions sum to total ES" invariant. Portfolio STARR = annualized excess return / annualized ETL, with the sign and excess-return convention pinned by tests. ETL-space implied returns require an EXPLICIT BL μ and rf (gate G5).

Design decisions grounded in the read sources:
- **Sign conventions** match the existing light codebase, NOT the legacy one. `app.analytics.historical_cvar` (`backend/app/analytics/risk.py:88-114`) returns ETL as a POSITIVE decimal fraction (a 3% tail loss is `0.03`). This module keeps that: `portfolio_etl` is POSITIVE, `mcetl_i`/`pcetl_i` are the positive-ES Euler parts that sum to the positive `portfolio_etl`. (The legacy `risk_budgeting_service.py` returned a signed-negative ETL via a count-based tail; we deliberately diverge to stay consistent with the light analytics layer — see open_questions.)
- **Tail estimator** matches `historical_cvar` EXACTLY: `cutoff = np.quantile(port, 1 - confidence)` then `mask = port <= cutoff` (`risk.py:109-110`). This is what makes `etl_risk_budget(...).portfolio_etl` reconcile to 1e-12 with `app.analytics.historical_cvar` on the portfolio series. The legacy `_portfolio_etl` (`risk_budgeting_service.py:65-70`) instead used a count-based `np.sort(...)[:cutoff]` slice — intentionally not ported.
- **μ-free gate G5**: the implied-return functions take `portfolio_return_ann` (the EXPLICIT `wᵀμ_BL`) and `risk_free_rate` as REQUIRED arguments. The module never calls `.mean()` on a full scenario column. The ONLY `.mean(...)` calls are the ES tail kernel (`tail_assets.mean(axis=0)` and `port[mask].mean()`), which is the legitimate Euler-ES estimator, not an expected-return estimate. This mirrors the rule enforced in `app.optimizer.engine` / `black_litterman` (the only sanctioned mean is `historical_mean_ann`, for BL re-centering only — see `backend/tests/test_optimizer_engine.py:154-168`).
- **Fail-loud**: every function raises `ValueError` on insufficient rows, shape mismatch, NaN/inf, degenerate (zero-variance) portfolios, non-positive ETL, or an empty tail — never returns NaN. This matches `app.analytics.risk` and `app.analytics.portfolio`.
- **Scale**: inputs are daily decimal-fraction returns; vol-like outputs (`mctr`, `ctr`, `portfolio_volatility`) are daily, ETL-like outputs (`mcetl`, `cetl`, `portfolio_etl`) are daily, all per the scenario matrix. Annualization (×252 for return/ES-like, ×√252 for vol-like) is the caller's job — same convention the legacy docstring stated (`risk_budgeting_service.py:26-32`) and the optimizer follows (`TRADING_DAYS = 252` in `engine.py:23`). `risk_budgeting` exposes `TRADING_DAYS = 252` and applies it inside `portfolio_starr`, `sharpe_implied_returns`, and `etl_implied_returns` (where the implied-return identities require annualized marginals).

### Task T2B-1: Variance Euler decomposition on the scenario matrix (MCTR / PCTR)

**Files:**
- Create: `backend/app/analytics/risk_budgeting.py`
- Create (test): `backend/tests/test_analytics_risk_budgeting.py`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_risk_budgeting.py` with the variance-decomposition tests. These pin: (a) PCTR sums to 1.0; (b) the diagonal-Σ closed form (`CTR_i = w_i²σ_i² / σ²_p` for uncorrelated assets); (c) MCTR equals `(Σw)_i / σ_p`; (d) consistency with the existing `app.analytics.portfolio.risk_contributions` (PCTR_i must equal CTR_i); (e) fail-loud guards.

```python
"""Tier 2 risk-budgeting tests (T2B): variance MCTR/PCTR + Sharpe-implied
returns, and ETL MCETL/PCETL + STARR + ETL-implied returns.

All math is pure numpy on a T×N daily scenario matrix (the same matrix the
optimizer assembles in app.services.portfolio_builder). Vol-like / ETL-like
outputs are at the DAILY scale of the input; annualization is the caller's
job (TRADING_DAYS = 252).
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk_budgeting as rb
from app.analytics.portfolio import risk_contributions


def _scenarios(seed: int = 7, t: int = 600, n: int = 4) -> np.ndarray:
    """Seeded daily-return scenario matrix with mild cross-correlation."""
    rng = np.random.default_rng(seed)
    base = rng.normal(0.0, 0.01, size=(t, 1))
    idio = rng.normal(0.0, 0.008, size=(t, n))
    vols = np.array([0.5, 1.0, 1.5, 2.0])
    return base * vols + idio


def _diag_scenarios(vols: np.ndarray, t: int = 2000, seed: int = 3) -> np.ndarray:
    """Independent columns with the given per-asset daily vols (≈ diagonal Σ)."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0, 1.0, size=(t, vols.size)) * vols


# ── variance decomposition (MCTR / PCTR) ─────────────────────────────────────


def test_pctr_sums_to_one() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.variance_risk_budget(w, scen)
    assert abs(float(dec.pctr.sum()) - 1.0) < 1e-9


def test_mctr_equals_sigma_w_over_sigma_p() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    cov = np.cov(scen, rowvar=False, ddof=1)
    sigma_w = cov @ w
    sigma_p = float(np.sqrt(w @ cov @ w))
    dec = rb.variance_risk_budget(w, scen)
    np.testing.assert_allclose(dec.mctr, sigma_w / sigma_p, rtol=1e-10, atol=1e-12)
    assert abs(dec.portfolio_volatility - sigma_p) < 1e-12


def test_ctr_sums_to_sigma_p() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.variance_risk_budget(w, scen)
    assert abs(float(dec.ctr.sum()) - dec.portfolio_volatility) < 1e-12


def test_pctr_matches_existing_risk_contributions() -> None:
    """PCTR must reproduce app.analytics.portfolio.risk_contributions exactly."""
    scen = _scenarios()
    w = np.array([0.5, 0.2, 0.2, 0.1])
    cols = ["A", "B", "C", "D"]
    returns = pd.DataFrame(scen, columns=cols)
    ctr = risk_contributions(returns, dict(zip(cols, w, strict=True)))
    dec = rb.variance_risk_budget(w, scen)
    for i, col in enumerate(cols):
        assert abs(float(dec.pctr[i]) - ctr[col]) < 1e-9


def test_diagonal_sigma_closed_form() -> None:
    vols = np.array([0.01, 0.02, 0.04])
    scen = _diag_scenarios(vols)
    w = np.array([0.5, 0.3, 0.2])
    cov = np.cov(scen, rowvar=False, ddof=1)
    var_p = float(w @ cov @ w)
    expected_pctr = (w**2 * np.diag(cov)) / var_p
    dec = rb.variance_risk_budget(w, scen)
    np.testing.assert_allclose(dec.pctr, expected_pctr, rtol=1e-6, atol=1e-9)


def test_variance_budget_rejects_short_matrix() -> None:
    scen = np.zeros((1, 3))
    with pytest.raises(ValueError, match="at least 2 rows"):
        rb.variance_risk_budget(np.array([0.5, 0.3, 0.2]), scen)


def test_variance_budget_rejects_nan() -> None:
    scen = _scenarios()
    scen[0, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or infinite"):
        rb.variance_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen)


def test_variance_budget_rejects_weight_length_mismatch() -> None:
    scen = _scenarios()
    with pytest.raises(ValueError, match="weights length"):
        rb.variance_risk_budget(np.array([0.5, 0.5]), scen)


def test_variance_budget_rejects_zero_variance_portfolio() -> None:
    scen = np.zeros((50, 2))  # constant (all-zero) returns → zero variance
    with pytest.raises(ValueError, match="portfolio variance"):
        rb.variance_risk_budget(np.array([0.5, 0.5]), scen)
```

- [ ] **Step 2: Run it, expect FAIL.** The module does not exist yet, so the import fails at collection.
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -v`
  - Expected: collection error `ModuleNotFoundError: No module named 'app.analytics.risk_budgeting'` (every test errors during import).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/risk_budgeting.py` with the module header, shared validation, the `VarianceRiskBudget` dataclass, and `variance_risk_budget`. The sample covariance uses `ddof=1` to match `risk_contributions` (`portfolio.py:264`, `returns.cov(ddof=1)`) and `_VARIANCE_FLOOR` is reused at the same value as `portfolio.py:56` (`1e-24`).

```python
"""Tier 2 risk budgeting (pure numpy) on a T×N daily scenario matrix.

Two Euler decompositions of portfolio risk into per-asset contributions, with
their implied-return duals:

1. Variance / volatility:  MCTR_i = (Σw)_i / σ_p,  CTR_i = w_i·MCTR_i,
   PCTR_i = CTR_i / σ_p (CTR sums to σ_p; PCTR sums to 1; PCTR is identical to
   app.analytics.portfolio.risk_contributions).
   Sharpe-implied return_i = rf + Sharpe · MCTR_ann_i  (gate G5: rf + BL μ
   explicit; this module never estimates a return mean).

2. Tail / Expected Shortfall (ETL ≡ CVaR):  the Euler decomposition of the
   historical ES is the per-asset MEAN of asset returns over the scenarios that
   form the portfolio loss tail (Tasche 2002). MCETL_i / CETL_i sum EXACTLY to
   the (positive) portfolio ETL.  STARR = ann. excess return / ann. ETL.
   ETL-implied return_i = rf + STARR · MCETL_ann_i  (gate G5: rf + BL μ
   explicit).

SCALE: inputs are DAILY decimal-fraction returns (0.05 = 5%). Vol-/ES-like
outputs are at the daily scale of the input; annualize at the presentation
layer (×252 for return/ES-like, ×√252 for vol-like). PCTR/PCETL are
scale-invariant. (Same convention as risk_budgeting_service.py:26-32 and the
optimizer's TRADING_DAYS = 252 in engine.py:23.)

μ-FREE (gate G5): this module NEVER takes a sample mean of a scenario COLUMN.
The only .mean(...) calls are the ES tail kernel (tail_assets.mean(axis=0),
port[mask].mean()), which is the legitimate empirical-ES estimator, not an
expected-return estimate. Implied-return functions require an EXPLICIT
portfolio_return_ann (= wᵀμ_BL) and rf.

Fail-loud: every function raises ValueError on insufficient/degenerate/NaN
input — never returns NaN. (Matches app.analytics.risk / app.analytics.portfolio.)
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

TRADING_DAYS = 252

# Variance below this is numerical dust, not signal (matches
# app.analytics.portfolio._VARIANCE_FLOOR at portfolio.py:56). Degenerate
# zero-risk portfolios are rejected at this floor.
_VARIANCE_FLOOR = 1e-24
_MIN_SCENARIO_ROWS = 2
_MIN_TAIL_ROWS = 10  # matches app.analytics.risk._MIN_TAIL_POINTS (risk.py:20)


def _validate_scenarios(scenarios: np.ndarray, func_name: str, min_rows: int) -> np.ndarray:
    """Coerce to a finite float T×N matrix with at least *min_rows* rows."""
    scen = np.asarray(scenarios, dtype=float)
    if scen.ndim != 2:
        raise ValueError(f"{func_name} requires a T×N scenario matrix, got ndim={scen.ndim}")
    if scen.shape[0] < min_rows:
        raise ValueError(f"{func_name} requires at least {min_rows} rows, got {scen.shape[0]}")
    if scen.shape[1] < 1:
        raise ValueError(f"{func_name} requires at least 1 column, got {scen.shape[1]}")
    if not np.isfinite(scen).all():
        raise ValueError(f"{func_name} received NaN or infinite values in input; clean the data first")
    return scen


def _validate_weights(weights: np.ndarray, n: int, func_name: str) -> np.ndarray:
    w = np.asarray(weights, dtype=float).ravel()
    if w.shape[0] != n:
        raise ValueError(f"{func_name} weights length {w.shape[0]} != {n} scenario columns")
    if not np.isfinite(w).all():
        raise ValueError(f"{func_name} received NaN or infinite values in weights")
    return w


@dataclass(frozen=True)
class VarianceRiskBudget:
    """Per-asset variance/volatility decomposition (daily scale).

    ``portfolio_volatility``: daily σ_p = sqrt(wᵀΣw).
    ``mctr``: marginal contribution to volatility, (Σw)_i / σ_p.
    ``ctr``:  absolute contribution to volatility, w_i·mctr_i (sums to σ_p).
    ``pctr``: percentage contribution (sums to 1.0; scale-invariant).
    """

    portfolio_volatility: float
    mctr: np.ndarray
    ctr: np.ndarray
    pctr: np.ndarray


def variance_risk_budget(weights: np.ndarray, scenarios: np.ndarray) -> VarianceRiskBudget:
    """Euler decomposition of portfolio volatility on a T×N scenario matrix.

    Σ = sample covariance (ddof=1, matching portfolio.risk_contributions).
    σ²_p = wᵀΣw. MCTR_i = (Σw)_i / σ_p, CTR_i = w_i·MCTR_i (sums to σ_p),
    PCTR_i = CTR_i / σ_p (sums to 1).

    Raises ValueError on <2 rows, NaN/inf, a weights-length mismatch, or a
    portfolio variance at/below the numerical floor (decomposition undefined).
    """
    scen = _validate_scenarios(scenarios, "variance_risk_budget", _MIN_SCENARIO_ROWS)
    w = _validate_weights(weights, scen.shape[1], "variance_risk_budget")
    cov = np.atleast_2d(np.cov(scen, rowvar=False, ddof=1))
    sigma_w = cov @ w
    var_p = float(w @ sigma_w)
    if var_p < _VARIANCE_FLOOR:
        raise ValueError("variance_risk_budget is undefined: portfolio variance is 0")
    sigma_p = float(np.sqrt(var_p))
    mctr = sigma_w / sigma_p
    ctr = w * mctr
    pctr = ctr / sigma_p
    return VarianceRiskBudget(
        portfolio_volatility=sigma_p,
        mctr=np.asarray(mctr, dtype=float),
        ctr=np.asarray(ctr, dtype=float),
        pctr=np.asarray(pctr, dtype=float),
    )
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -v`
  - Expected: the 9 variance tests pass (`test_pctr_sums_to_one`, `test_mctr_equals_sigma_w_over_sigma_p`, `test_ctr_sums_to_sigma_p`, `test_pctr_matches_existing_risk_contributions`, `test_diagonal_sigma_closed_form`, and the 4 guard tests `test_variance_budget_rejects_short_matrix`, `test_variance_budget_rejects_nan`, `test_variance_budget_rejects_weight_length_mismatch`, `test_variance_budget_rejects_zero_variance_portfolio`).

- [ ] **Step 5: Commit.**
  - `cd backend && git add app/analytics/risk_budgeting.py tests/test_analytics_risk_budgeting.py`
  - Commit message: `feat(analytics): variance MCTR/PCTR Euler risk budget on scenario matrix (T2B-1)`

### Task T2B-2: ETL Euler decomposition (MCETL / PCETL) summing to total ES

**Files:**
- Modify: `backend/app/analytics/risk_budgeting.py` (append `_tail_mask`, `EtlRiskBudget`, `etl_risk_budget` after `variance_risk_budget`)
- Modify (test): `backend/tests/test_analytics_risk_budgeting.py` (append ETL-decomposition tests, plus the `historical_cvar` import)

- [ ] **Step 1: Write the failing test.** Append these tests. The core invariant: `MCETL_i` summed weighted by `w` equals `portfolio_etl`, AND `PCETL` sums to 1.0, AND `portfolio_etl` equals the existing `app.analytics.historical_cvar` on the portfolio series (same tail estimator, positive sign).

```python
# ── ETL decomposition (MCETL / PCETL) ────────────────────────────────────────

from app.analytics.risk import historical_cvar  # noqa: E402


def test_etl_contributions_sum_to_total_es() -> None:
    """w·MCETL sums EXACTLY to the (positive) portfolio ETL; PCETL sums to 1."""
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    np.testing.assert_allclose(
        float((w * dec.mcetl).sum()), dec.portfolio_etl, rtol=1e-10, atol=1e-12
    )
    assert abs(float(dec.pcetl.sum()) - 1.0) < 1e-9
    assert dec.portfolio_etl > 0.0  # positive sign convention (loss magnitude)


def test_cetl_sums_to_portfolio_etl() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    assert abs(float(dec.cetl.sum()) - dec.portfolio_etl) < 1e-12


def test_portfolio_etl_matches_historical_cvar() -> None:
    """portfolio_etl equals app.analytics.historical_cvar on the same series."""
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    port = pd.Series(scen @ w)
    assert abs(dec.portfolio_etl - historical_cvar(port, confidence=0.95)) < 1e-12


def test_pcetl_is_cetl_over_etl() -> None:
    scen = _scenarios()
    w = np.array([0.5, 0.2, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    np.testing.assert_allclose(
        dec.pcetl, (w * dec.mcetl) / dec.portfolio_etl, rtol=1e-10, atol=1e-12
    )


def test_etl_budget_requires_min_tail_rows() -> None:
    scen = _scenarios(t=9)
    with pytest.raises(ValueError, match="at least 10 rows"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=0.95)


def test_etl_budget_rejects_bad_confidence() -> None:
    scen = _scenarios()
    with pytest.raises(ValueError, match="confidence must be in"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=1.5)


def test_etl_budget_rejects_nan() -> None:
    scen = _scenarios()
    scen[5, 2] = np.inf
    with pytest.raises(ValueError, match="NaN or infinite"):
        rb.etl_risk_budget(np.array([0.25, 0.25, 0.25, 0.25]), scen, confidence=0.95)
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -k etl -v`
  - Expected: `AttributeError: module 'app.analytics.risk_budgeting' has no attribute 'etl_risk_budget'` for each new test (the variance tests still pass; `test_etl_budget_rejects_bad_confidence` also errors on the missing attribute before its `match` is checked).

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/risk_budgeting.py`. The tail set uses the SAME selection rule as `app.analytics.historical_cvar` (`risk.py:109-110`): `cutoff = np.quantile(port, 1 - confidence)`, `mask = port <= cutoff`. The per-asset MCETL is the mean of asset *i*'s returns over those tail scenarios, NEGATED so the result is a positive loss magnitude — by linearity `w·MCETL = -mean(port_tail) = portfolio_etl` exactly (the dispatch's "sum to total ES" invariant). PCETL = `(w·MCETL) / portfolio_etl`.

```python
def _tail_mask(port_returns: np.ndarray, confidence: float, func_name: str) -> np.ndarray:
    """Boolean mask of the loss-tail scenarios (port <= the (1-c) quantile).

    Identical selection to app.analytics.historical_cvar (risk.py:109-110) so
    the aggregate ETL reconciles exactly with the F3 estimator.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"{func_name}: confidence must be in (0, 1), got {confidence}")
    cutoff = float(np.quantile(port_returns, 1 - confidence))
    mask = port_returns <= cutoff
    if not mask.any():
        raise ValueError(f"{func_name} tail selection is empty")
    return mask


@dataclass(frozen=True)
class EtlRiskBudget:
    """Per-asset Expected-Shortfall (ETL/CVaR) decomposition (daily scale).

    ``portfolio_etl``: POSITIVE loss magnitude (matches historical_cvar).
    ``mcetl``: marginal contribution to ETL = −E[r_i | portfolio in tail]
        (positive when asset i loses in the portfolio tail).
    ``cetl``:  absolute contribution, w_i·mcetl_i (sums to portfolio_etl).
    ``pcetl``: percentage contribution (sums to 1.0; scale-invariant).
    """

    portfolio_etl: float
    mcetl: np.ndarray
    cetl: np.ndarray
    pcetl: np.ndarray


def etl_risk_budget(
    weights: np.ndarray, scenarios: np.ndarray, confidence: float = 0.95
) -> EtlRiskBudget:
    """Euler decomposition of historical Expected Shortfall on a T×N matrix.

    The portfolio loss tail is the set of scenarios whose portfolio return is at
    or below the (1−confidence) quantile (same rule as historical_cvar). The
    marginal ETL of asset i is the negated mean of its return over that tail, so
    by linearity Σ_i w_i·MCETL_i = −mean(portfolio tail) = portfolio_etl
    (positive). PCETL_i = w_i·MCETL_i / portfolio_etl (sums to 1).

    Raises ValueError on <10 rows, NaN/inf, a weights-length mismatch, a
    confidence outside (0, 1), an empty tail, or a non-positive portfolio ETL
    (the loss tail has non-negative mean return).
    """
    scen = _validate_scenarios(scenarios, "etl_risk_budget", _MIN_TAIL_ROWS)
    w = _validate_weights(weights, scen.shape[1], "etl_risk_budget")
    port = scen @ w
    mask = _tail_mask(port, confidence, "etl_risk_budget")
    tail_assets = scen[mask, :]            # (k, N) asset returns in the tail
    mcetl = -tail_assets.mean(axis=0)      # (N,) positive loss magnitudes
    portfolio_etl = float(-port[mask].mean())
    if portfolio_etl <= 0.0:
        raise ValueError(
            "etl_risk_budget is undefined: non-positive portfolio ETL "
            "(the loss tail has non-negative mean return)"
        )
    cetl = w * mcetl
    pcetl = cetl / portfolio_etl
    return EtlRiskBudget(
        portfolio_etl=portfolio_etl,
        mcetl=np.asarray(mcetl, dtype=float),
        cetl=np.asarray(cetl, dtype=float),
        pcetl=np.asarray(pcetl, dtype=float),
    )
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -v`
  - Expected: all variance tests (T2B-1) plus the 7 new ETL tests pass. Note `test_portfolio_etl_matches_historical_cvar` reconciles `etl_risk_budget` with `app.analytics.historical_cvar` to 1e-12.

- [ ] **Step 5: Commit.**
  - `cd backend && git add app/analytics/risk_budgeting.py tests/test_analytics_risk_budgeting.py`
  - Commit message: `feat(analytics): MCETL/PCETL Euler ES decomposition summing to total ETL (T2B-2)`

### Task T2B-3: Portfolio STARR (annualized excess return / annualized ETL)

**Files:**
- Modify: `backend/app/analytics/risk_budgeting.py` (append `portfolio_starr` after `etl_risk_budget`)
- Modify (test): `backend/tests/test_analytics_risk_budgeting.py` (append STARR tests)

- [ ] **Step 1: Write the failing test.** STARR (Stable Tail-Adjusted Return Ratio) = annualized excess return / annualized ETL. The excess return is the EXPLICIT annualized BL μ on the portfolio minus rf — NOT a sample mean (gate G5). Sign tests: positive when ann. portfolio return exceeds rf, negative when below.

```python
# ── STARR ────────────────────────────────────────────────────────────────────


def test_starr_positive_when_excess_positive() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    # Explicit annualized portfolio expected return well above rf.
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.10, risk_free_rate=0.04, confidence=0.95
    )
    assert starr > 0.0


def test_starr_negative_when_excess_negative() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.01, risk_free_rate=0.04, confidence=0.95
    )
    assert starr < 0.0


def test_starr_equals_excess_over_annualized_etl() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    dec = rb.etl_risk_budget(w, scen, confidence=0.95)
    etl_ann = dec.portfolio_etl * rb.TRADING_DAYS
    expected = (0.08 - 0.04) / etl_ann
    starr = rb.portfolio_starr(
        w, scen, portfolio_return_ann=0.08, risk_free_rate=0.04, confidence=0.95
    )
    assert abs(starr - expected) < 1e-10


def test_starr_rejects_nonpositive_etl_tail() -> None:
    # All-positive scenarios → loss tail has non-negative mean → ETL <= 0.
    scen = np.abs(_scenarios()) + 0.001
    w = np.array([0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ValueError, match="non-positive portfolio ETL"):
        rb.portfolio_starr(
            w, scen, portfolio_return_ann=0.08, risk_free_rate=0.04, confidence=0.95
        )


def test_starr_rejects_nonfinite_return() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ValueError, match="must be finite"):
        rb.portfolio_starr(
            w, scen, portfolio_return_ann=np.nan, risk_free_rate=0.04, confidence=0.95
        )
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -k starr -v`
  - Expected: `AttributeError: module 'app.analytics.risk_budgeting' has no attribute 'portfolio_starr'` for each STARR test.

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/risk_budgeting.py`. STARR reuses `etl_risk_budget` for the (positive) daily ETL, annualizes it ×252, and divides the EXPLICIT annualized excess return by it. The function takes `portfolio_return_ann` explicitly (the caller computes it as `mu_bl @ weights`) — the module itself never estimates a mean. The finite-input guards are checked BEFORE calling `etl_risk_budget` so a NaN return raises the clearer "must be finite" message.

```python
def portfolio_starr(
    weights: np.ndarray,
    scenarios: np.ndarray,
    portfolio_return_ann: float,
    risk_free_rate: float,
    confidence: float = 0.95,
) -> float:
    """Portfolio STARR = annualized excess return / annualized ETL.

    ``portfolio_return_ann`` is the EXPLICIT annualized portfolio expected
    return (gate G5: by contract the caller supplies wᵀμ_BL — never a sample
    mean). The annualized ETL is the daily etl_risk_budget ETL × TRADING_DAYS.
    STARR is positive iff the annualized return exceeds the risk-free rate.

    Raises ValueError on a NaN/inf return or rf, or any condition raised by
    etl_risk_budget (short/empty tail, non-positive ETL, NaN, shape mismatch).
    """
    if not np.isfinite(portfolio_return_ann):
        raise ValueError("portfolio_starr: portfolio_return_ann must be finite")
    if not np.isfinite(risk_free_rate):
        raise ValueError("portfolio_starr: risk_free_rate must be finite")
    dec = etl_risk_budget(weights, scenarios, confidence=confidence)
    etl_ann = dec.portfolio_etl * TRADING_DAYS
    return float((portfolio_return_ann - risk_free_rate) / etl_ann)
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -k starr -v`
  - Expected: the 5 STARR tests pass. (`test_starr_rejects_nonpositive_etl_tail` is raised by `etl_risk_budget`'s `non-positive portfolio ETL` guard, surfaced through `portfolio_starr`; `test_starr_rejects_nonfinite_return` is raised by `portfolio_starr`'s own finite guard.)

- [ ] **Step 5: Commit.**
  - `cd backend && git add app/analytics/risk_budgeting.py tests/test_analytics_risk_budgeting.py`
  - Commit message: `feat(analytics): portfolio STARR (excess return / annualized ETL) (T2B-3)`

### Task T2B-4: Implied returns — Sharpe-implied (variance) and ETL-implied (STARR), gate G5

**Files:**
- Modify: `backend/app/analytics/risk_budgeting.py` (append `sharpe_implied_returns` and `etl_implied_returns` after `portfolio_starr`)
- Modify (test): `backend/tests/test_analytics_risk_budgeting.py` (append implied-return tests)

- [ ] **Step 1: Write the failing test.** Implied returns decompose the portfolio's risk-adjusted performance back onto each asset. Sharpe-implied: `r_i = rf + Sharpe · MCTR_ann_i`, where `Sharpe = excess_ann / vol_ann`; the dot product `w · (implied − rf)` reconstructs the portfolio excess (since `w·MCTR_ann = σ_p_ann` and `Sharpe·σ_p_ann = excess`). ETL-implied: `r_i = rf + STARR · MCETL_ann_i`; analogously `w · (implied − rf)` reconstructs the portfolio excess (since `w·MCETL_ann = ETL_ann` and `STARR·ETL_ann = excess`). Both require explicit BL μ on the portfolio + rf (gate G5).

```python
# ── implied returns (gate G5: explicit excess return only) ───────────────────


def test_sharpe_implied_reconstructs_portfolio_excess() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    rf, mu_p_ann = 0.04, 0.09
    implied = rb.sharpe_implied_returns(
        w, scen, portfolio_return_ann=mu_p_ann, risk_free_rate=rf
    )
    # w·(implied − rf) == portfolio annualized excess return.
    assert abs(float((w * (implied - rf)).sum()) - (mu_p_ann - rf)) < 1e-9


def test_sharpe_implied_offset_by_rf() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    var_dec = rb.variance_risk_budget(w, scen)
    rf, mu_p_ann = 0.03, 0.08
    sharpe = (mu_p_ann - rf) / (var_dec.portfolio_volatility * np.sqrt(rb.TRADING_DAYS))
    expected = rf + sharpe * (var_dec.mctr * np.sqrt(rb.TRADING_DAYS))
    implied = rb.sharpe_implied_returns(
        w, scen, portfolio_return_ann=mu_p_ann, risk_free_rate=rf
    )
    np.testing.assert_allclose(implied, expected, rtol=1e-9, atol=1e-12)


def test_etl_implied_reconstructs_portfolio_excess() -> None:
    scen = _scenarios()
    w = np.array([0.4, 0.3, 0.2, 0.1])
    rf, mu_p_ann = 0.04, 0.09
    implied = rb.etl_implied_returns(
        w, scen, portfolio_return_ann=mu_p_ann, risk_free_rate=rf, confidence=0.95
    )
    assert abs(float((w * (implied - rf)).sum()) - (mu_p_ann - rf)) < 1e-9


def test_implied_returns_reject_nonfinite_excess_inputs() -> None:
    scen = _scenarios()
    w = np.array([0.25, 0.25, 0.25, 0.25])
    with pytest.raises(ValueError, match="must be finite"):
        rb.sharpe_implied_returns(
            w, scen, portfolio_return_ann=np.nan, risk_free_rate=0.04
        )
    with pytest.raises(ValueError, match="must be finite"):
        rb.etl_implied_returns(
            w, scen, portfolio_return_ann=0.08, risk_free_rate=np.inf
        )
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -k implied -v`
  - Expected: `AttributeError: module 'app.analytics.risk_budgeting' has no attribute 'sharpe_implied_returns'` (and `'etl_implied_returns'`) for the new tests.

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/risk_budgeting.py`. Both functions annualize the (daily) marginal contributions: vol-like MCTR ×√252, ETL-like MCETL ×252, so the implied returns are on an annualized basis matching `portfolio_return_ann` and `risk_free_rate`. The reconstruction identities hold because `w·MCTR_ann = σ_p_ann` and `w·MCETL_ann = ETL_ann`.

```python
def sharpe_implied_returns(
    weights: np.ndarray,
    scenarios: np.ndarray,
    portfolio_return_ann: float,
    risk_free_rate: float,
) -> np.ndarray:
    """Sharpe-implied (annualized) per-asset returns: rf + Sharpe·MCTR_ann.

    Sharpe = (portfolio_return_ann − rf) / σ_p_ann, MCTR_ann = MCTR·√252.
    By construction w·(implied − rf) = portfolio_return_ann − rf.

    Gate G5: ``portfolio_return_ann`` is the EXPLICIT wᵀμ_BL supplied by the
    caller — this function never estimates a mean from the scenarios.

    Raises ValueError on non-finite excess inputs, or any condition raised by
    variance_risk_budget (degenerate variance, NaN, shape mismatch).
    """
    if not np.isfinite(portfolio_return_ann):
        raise ValueError("sharpe_implied_returns: portfolio_return_ann must be finite")
    if not np.isfinite(risk_free_rate):
        raise ValueError("sharpe_implied_returns: risk_free_rate must be finite")
    dec = variance_risk_budget(weights, scenarios)
    vol_ann = dec.portfolio_volatility * np.sqrt(TRADING_DAYS)
    sharpe = (portfolio_return_ann - risk_free_rate) / vol_ann
    mctr_ann = dec.mctr * np.sqrt(TRADING_DAYS)
    return np.asarray(risk_free_rate + sharpe * mctr_ann, dtype=float)


def etl_implied_returns(
    weights: np.ndarray,
    scenarios: np.ndarray,
    portfolio_return_ann: float,
    risk_free_rate: float,
    confidence: float = 0.95,
) -> np.ndarray:
    """ETL-implied (annualized) per-asset returns: rf + STARR·MCETL_ann.

    STARR = (portfolio_return_ann − rf) / ETL_ann, MCETL_ann = MCETL·252.
    By construction w·(implied − rf) = portfolio_return_ann − rf.

    Gate G5: ``portfolio_return_ann`` is the EXPLICIT wᵀμ_BL supplied by the
    caller — this function never estimates a mean from the scenarios.

    Raises ValueError on non-finite excess inputs, or any condition raised by
    etl_risk_budget (short/empty tail, non-positive ETL, NaN, shape mismatch).
    """
    if not np.isfinite(portfolio_return_ann):
        raise ValueError("etl_implied_returns: portfolio_return_ann must be finite")
    if not np.isfinite(risk_free_rate):
        raise ValueError("etl_implied_returns: risk_free_rate must be finite")
    dec = etl_risk_budget(weights, scenarios, confidence=confidence)
    etl_ann = dec.portfolio_etl * TRADING_DAYS
    starr = (portfolio_return_ann - risk_free_rate) / etl_ann
    mcetl_ann = dec.mcetl * TRADING_DAYS
    return np.asarray(risk_free_rate + starr * mcetl_ann, dtype=float)
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -v`
  - Expected: the entire file passes — all variance, ETL, STARR, and implied-return tests.

- [ ] **Step 5: Commit.**
  - `cd backend && git add app/analytics/risk_budgeting.py tests/test_analytics_risk_budgeting.py`
  - Commit message: `feat(analytics): Sharpe- and ETL-implied per-asset returns (gate G5) (T2B-4)`

### Task T2B-5: Export the public surface + gate G5 structural guard

**Files:**
- Modify: `backend/app/analytics/__init__.py` (add an import block + 7 `__all__` entries; the existing import block is lines 8-45, the `__all__` list is lines 47-77)
- Modify (test): `backend/tests/test_analytics_risk_budgeting.py` (append the export test and the μ-free structural guard)

- [ ] **Step 1: Write the failing test.** Pin that the new symbols are importable from `app.analytics` (the package's public surface, the way `risk_contributions` etc. are exported), and add a structural gate-G5 guard: the `risk_budgeting` module source must NOT define a "historical mean" helper, must NOT take a mean of a full scenario column, and the ONLY `.mean(` calls allowed are the two ES tail kernels. (Mirrors the G5 structural check style in `test_optimizer_engine.py:154-168`, which reads module source via `pathlib` and asserts on `.mean(` occurrences.)

```python
# ── public surface + gate G5 structural guard ────────────────────────────────

import inspect  # noqa: E402
import pathlib  # noqa: E402


def test_public_symbols_exported_from_analytics() -> None:
    import app.analytics as analytics

    for name in (
        "variance_risk_budget",
        "etl_risk_budget",
        "portfolio_starr",
        "sharpe_implied_returns",
        "etl_implied_returns",
        "VarianceRiskBudget",
        "EtlRiskBudget",
    ):
        assert hasattr(analytics, name), f"{name} not exported from app.analytics"
        assert name in analytics.__all__, f"{name} missing from app.analytics.__all__"


def test_g5_no_sample_mean_of_scenarios_in_source() -> None:
    """Gate G5: risk_budgeting never estimates a mean OF A SCENARIO COLUMN.

    The ES tail mean (tail_assets.mean(axis=0) / port[mask].mean()) is the
    legitimate Euler ES kernel, not an expected-return estimate. The forbidden
    patterns are a 'historical mean' helper, or a full-column scenario mean
    feeding an implied/expected return. We assert the only two .mean( calls in
    the module are the two sanctioned ES-kernel calls.
    """
    source = pathlib.Path(inspect.getfile(rb)).read_text(encoding="utf-8")
    assert "historical_mean" not in source.lower()
    assert "scenarios.mean(" not in source
    assert "scen.mean(" not in source
    assert "np.average" not in source
    # The two sanctioned ES-kernel means, and nothing else.
    assert source.count(".mean(") == 2
    assert "tail_assets.mean(axis=0)" in source
    assert "port[mask].mean()" in source
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -k "exported or g5" -v`
  - Expected: `test_public_symbols_exported_from_analytics` FAILS with `AssertionError: variance_risk_budget not exported from app.analytics` (the `__init__.py` does not import them yet). `test_g5_no_sample_mean_of_scenarios_in_source` should already PASS (the module contains exactly the two sanctioned ES-kernel `.mean(` calls and no historical-mean helper) — that is the intended state.

- [ ] **Step 3: Write the minimal implementation.** Add the import block and `__all__` entries to `backend/app/analytics/__init__.py`.

  Add this import block immediately after the existing `from app.analytics.risk import (...)` block that ends at line 40, and before the `from app.analytics.rolling import (...)` block that starts at line 41:

```python
from app.analytics.risk_budgeting import (
    EtlRiskBudget,
    VarianceRiskBudget,
    etl_implied_returns,
    etl_risk_budget,
    portfolio_starr,
    sharpe_implied_returns,
    variance_risk_budget,
)
```

  Then add these 7 entries to the `__all__` list (lines 47-77). The list is alphabetically ordered with capitalized names first; insert `EtlRiskBudget` and `VarianceRiskBudget` among the capitalized entries (e.g. after `"DrawdownResult"`, before `"Histogram"`), and the lowercase function names among the lowercase entries (e.g. `etl_implied_returns`/`etl_risk_budget` after `"diversification_ratio"`; `portfolio_starr` after `"portfolio_returns"`; `sharpe_implied_returns` after `"risk_contributions"`/before `"rolling_beta"`; `variance_risk_budget` after `"total_return"`/before `"weight_series"`):

```python
    "EtlRiskBudget",
    "VarianceRiskBudget",
    "etl_implied_returns",
    "etl_risk_budget",
    "portfolio_starr",
    "sharpe_implied_returns",
    "variance_risk_budget",
```

  (Exact alphabetical placement is not load-bearing for the test, which only checks membership; keep the file ruff-clean — the repo enforces sorted `__all__` via ruff's RUF022 if configured, so prefer the alphabetical positions above.)

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_risk_budgeting.py -v`
  - Expected: the full file passes, including `test_public_symbols_exported_from_analytics` and `test_g5_no_sample_mean_of_scenarios_in_source`.
  - Then run the existing analytics suite to confirm no regression in the package exports:
  - Command: `cd backend && python -m pytest tests/test_analytics_portfolio.py tests/test_analytics_risk.py tests/test_analytics_risk_budgeting.py -q`
  - Expected: all pass.

- [ ] **Step 5: Commit.**
  - `cd backend && git add app/analytics/__init__.py tests/test_analytics_risk_budgeting.py`
  - Commit message: `feat(analytics): export risk_budgeting surface + G5 structural guard (T2B-5)`

---

## Tier 2 — Optimizer constraint/return axis: block & per-asset bounds -> turnover L1 -> CVaR-as-constraint max-return (+SCS fallback) -> regime-conditional CVaR

These tasks extend the pure cvxpy engine and the request contract along the *constraint and expected-return* axis. They are strictly dependency-ordered:

- **T2C-1 / T2C-2** add per-asset bound vectors and block/asset-class budget sums to the engine and `ConstraintsIn`. This is the **prerequisite primitive** for any later per-asset or regime cap.
- **T2C-3 / T2C-4** add an L1 turnover / transaction-cost penalty, threaded `OptimizeRequest -> run_optimize -> engine`, with `current_weights` coming from the rebalance path.
- **T2C-5 / T2C-6** add the CVaR-as-constraint **max-return** solve (`max μᵀw s.t. CVaR_α(w) ≤ limit`, μ from the BL posterior per gate G5) with a `CLARABEL -> SCS` solver ladder and a post-solve realized-CVaR verifier.
- **T2C-7 / T2C-8** add a regime-conditional CVaR-limit multiplier driven by the existing credit-regime series.

All fractional quantities are decimal fractions (`0.05 = 5%`). Every pure-analytics failure raises `OptimizerError` (a `ValueError` subclass, defined at `backend/app/optimizer/engine.py:31`); the service wraps it in `BuilderError` (`portfolio_builder.py:56`); the route maps to HTTP 422 (`api/routes/builder.py:48-51`). Tests live flat in `backend/tests/` (verified: no `tests/optimizer/` subdir exists). All pytest commands run from `backend/` (`pyproject.toml` sets `testpaths = ["tests"]`, `asyncio_mode = "auto"`).

### Verified facts the tasks rely on (re-read from source)
- `base_constraints(w, cap, min_weight)` returns `[w >= 0, cp.sum(w) == 1, (w <= cap), (w >= min_weight)]` (`engine.py:80-89`). `cp` is imported unquoted at `engine.py:20`; `np` at `engine.py:21`. **There is no `from dataclasses import dataclass` yet** — T2C-1 adds it.
- `_check_constraint_params(n, cap, min_weight)` validates scalar cap/min (`engine.py:58-77`).
- `_finalize(problem, w, label)` solves with the *default* solver (`problem.solve()`, no solver arg), demands `cp.OPTIMAL`, cleans noise <1e-10, rejects weights < `-_WEIGHT_ATOL` (=`1e-6`, `engine.py:28`), renormalizes (`engine.py:92-112`). The max-return path needs a *solver-ladder* variant, not `_finalize`.
- `solve_min_cvar(scenarios, alpha=0.95, cap=0.25, min_weight=None, ret_floor=None, mu=None)` (`engine.py:237-244`). Body: scenarios/`np.isfinite` checks (254-258), `t < 10` (260-261), `alpha` (262-263), `_check_constraint_params` (264), `ret_floor`-requires-`mu` pre-check (265-269), variable+CVaR expr (271-274), `cons = base_constraints(...)` (275), `ret_floor` floor block (276-280), `problem = cp.Problem(cp.Minimize(cvar), cons)` + `return _finalize(...)` (281-282).
- **GATE G5 STRUCTURAL TEST** `test_g5_structural_no_mean_estimation_in_engine_or_data` (`test_optimizer_engine.py:154-162`) asserts the literal substring `".mean("` is **NOT** present in `engine.py` (nor `np.average`). **Every new engine function in T2C-1/2/3/5 MUST avoid `.mean(`** — `_realized_cvar` uses `np.partition` (k-th worst loss), never a mean. The legacy port (`ru_cvar_lp.realized_cvar_from_weights`, `E:/investintell-allocation/backend/quant_engine/ru_cvar_lp.py:167-215`) is the source; its scenario-mean lines live only in the *constraint/objective builders*, which we do NOT port — only the realized verifier.
- BL μ source: `black_litterman.posterior(...) -> (mu_bl, sigma_bl)` (`black_litterman.py:174-210`); `equilibrium(...)` (`black_litterman.py:84-97`). These are the ONLY sanctioned expected-return vectors (gate G5).
- `ConstraintsIn` has scalar `cap` (default 0.25) and `min_weight` (`schemas/builder.py:60-64`). `Objective` literal at `schemas/builder.py:72-74`. `AssetClassFilter = Literal["equity","fixed_income","cash","alternatives"]` at `schemas/builder.py:79`. `model_validator`, `Field`, `Annotated`, `BaseModel` already imported (`schemas/builder.py:10-12`).
- `OptimizeRequest` (`schemas/builder.py:131-163`): fields `assets`, `universe`, `objective`, `constraints`, `window_days`, `views`, `bl` (last at line 146); validator `_check_asset_source` (148-163, `return self` at 163). `run_optimize(session, payload)` (`portfolio_builder.py:237`), `index_of` built at `portfolio_builder.py:248`, objective ladder at `portfolio_builder.py:279-305`, `_solve_mu_free` at `portfolio_builder.py:162-179`.
- Data loader `load_fund_aum` ends at `optimizer_data.py:165`; `Fund`, `FundNav` imported at `optimizer_data.py:24`; `select`, `func` at `optimizer_data.py:20`; `uuid` at `optimizer_data.py:14`. `Fund.asset_class: Mapped[str | None]` exists (`models/fund.py:80`).
- Rebalance evaluator: constants block `DEFAULT_OBJECTIVE` / `BUILDER_CAP` at `rebalance/evaluator.py:59-60`; `viable_cap(n_assets)` at `evaluator.py:173-175`; `current: dict[str, float]` at `evaluator.py:302`; `tickers` at 282, `fund_ids` (ticker->uuid) at 283; `assets = [...]` at 305-310; `request = OptimizeRequest(...)` at 311-315. `ConstraintsIn`, `EquityRefIn`, `FundRefIn`, `Objective`, `OptimizeRequest` imported at `evaluator.py:40-46`.
- Builder route: `optimize(payload, session)` at `api/routes/builder.py:36-51`, `SessionDep` at line 33, uses only `get_session` today. **`app.core.datalake.get_optional_datalake_session` exists (verified) and yields `AsyncSession | None` (None when `DATALAKE_DB_URL` unset)** — this is the correct dependency to inject (not `get_datalake_session`, which raises 503 when the DSN is unset).
- Regime reader: `app.services.macro_regime.fetch_credit_regime(datalake: AsyncSession) -> CreditRegimeSnapshot | None` (`macro_regime.py:71-108`); `CreditRegimeSnapshot.state: str` (`macro_regime.py:31`) and `.stress_score: float | None` (`macro_regime.py:40`).
- Test helpers (verified): `test_optimizer_engine.py` imports `engine` (line 16), `np`/`pytest` (13-14), defines `_assert_valid(weights, status, cap=None)` (21-26) and `_random_scenarios(t=500, n=5, seed=42)` (74-77). `test_builder_schema.py` imports `OptimizeRequest` (9), defines `_A`, `_B` (11-12), `_assets()` (15-16). `test_builder_route.py` imports `pytest`, `numpy as np`, `pandas as pd`, `uuid`, `datetime as dt`, `typing.Any`, `optimizer_data` (11-22), defines `_FUND_IDS` (24), `_client()` (27-30, overrides `get_session` with `lambda: None`), `_fund_ref(i)` (33-34), `_stub_returns(monkeypatch, n_obs=500)` (37-52), `_stub_aum(monkeypatch, aum=None)` (55-65).

---

### Task T2C-1: Engine — per-asset bound vectors + block budget sums (`bounds_constraints`)

Add a convex-compatible constraint builder accepting **per-asset** cap/min vectors and **block budget** sums (Σ wᵢ over a group of column indices ∈ `[lo, hi]`), with empty-block / floor infeasibility checks. Pure helper; existing solvers are untouched here. Returns cvxpy linear constraints so it composes with all five objectives. **No `.mean(` (gate G5 structural test).**

**Files:**
- Modify: `backend/app/optimizer/engine.py` — add `from dataclasses import dataclass` after line 21; add `BlockBudget` dataclass, `_check_bound_vectors`, `bounds_constraints` after `base_constraints` (i.e. after line 89, before `_finalize` at line 92); reuse `_WEIGHT_ATOL` (line 28) and `OptimizerError` (line 31).
- Test: `backend/tests/test_optimizer_engine.py` — append (imports `engine`, `np`, `pytest` already present at lines 13-16).

**Steps:**

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_engine.py`:
```python
# ── T2C-1: per-asset bound vectors + block budgets ──────────────────────────


def test_bounds_constraints_per_asset_vectors_bind() -> None:
    import cvxpy as cp

    # Asset 0 capped at 0.10, others free up to 1; min 0.05 on asset 2.
    n = 3
    w = cp.Variable(n)
    caps = np.array([0.10, 1.0, 1.0])
    mins = np.array([0.0, 0.0, 0.05])
    cons = engine.bounds_constraints(w, cap_vec=caps, min_vec=mins, blocks=None)
    sigma = np.diag([0.01, 0.04, 0.09])
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), cons)
    prob.solve()
    assert str(prob.status) == cp.OPTIMAL
    weights = np.asarray(w.value).ravel()
    assert abs(weights.sum() - 1.0) < 1e-6
    assert weights[0] <= 0.10 + 1e-6
    assert weights[2] >= 0.05 - 1e-6


def test_bounds_constraints_block_budget_caps_group_sum() -> None:
    import cvxpy as cp

    # Two blocks: {0,1} must sum to <= 0.30; {2,3} sum in [0.40, 1.0].
    n = 4
    w = cp.Variable(n)
    blocks = [
        engine.BlockBudget(indices=[0, 1], lo=0.0, hi=0.30),
        engine.BlockBudget(indices=[2, 3], lo=0.40, hi=1.0),
    ]
    cons = engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)
    sigma = np.diag([0.01, 0.01, 0.04, 0.04])
    prob = cp.Problem(cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))), cons)
    prob.solve()
    assert str(prob.status) == cp.OPTIMAL
    weights = np.asarray(w.value).ravel()
    assert weights[0] + weights[1] <= 0.30 + 1e-6
    assert weights[2] + weights[3] >= 0.40 - 1e-6


def test_bounds_constraints_block_floor_infeasible_against_caps_fails_loud() -> None:
    import cvxpy as cp

    # Block {0,1} floor 0.80, but each asset capped at 0.30 -> max group sum 0.60
    # < 0.80: structurally infeasible, must fail loud BEFORE solving.
    w = cp.Variable(4)
    caps = np.array([0.30, 0.30, 1.0, 1.0])
    blocks = [engine.BlockBudget(indices=[0, 1], lo=0.80, hi=1.0)]
    with pytest.raises(engine.OptimizerError, match="block floor"):
        engine.bounds_constraints(w, cap_vec=caps, min_vec=None, blocks=blocks)


def test_bounds_constraints_block_sum_of_floors_exceeds_one_fails_loud() -> None:
    import cvxpy as cp

    # Two disjoint blocks whose floors sum to > 1 can never satisfy sum(w)=1.
    w = cp.Variable(4)
    blocks = [
        engine.BlockBudget(indices=[0, 1], lo=0.60, hi=1.0),
        engine.BlockBudget(indices=[2, 3], lo=0.60, hi=1.0),
    ]
    with pytest.raises(engine.OptimizerError, match="block floors"):
        engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)


def test_bounds_constraints_empty_block_indices_fails_loud() -> None:
    import cvxpy as cp

    w = cp.Variable(3)
    blocks = [engine.BlockBudget(indices=[], lo=0.0, hi=0.5)]
    with pytest.raises(engine.OptimizerError, match="empty"):
        engine.bounds_constraints(w, cap_vec=None, min_vec=None, blocks=blocks)
```

- [ ] **Step 2: Run it, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "bounds_constraints" -v`
  Expected failure: `AttributeError: module 'app.optimizer.engine' has no attribute 'BlockBudget'` (and `bounds_constraints`).

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/optimizer/engine.py`, add the import line directly after `import numpy as np` (line 21):
```python
from dataclasses import dataclass
```
  Then insert AFTER `base_constraints` (after line 89, before `_finalize` at line 92):
```python
@dataclass(frozen=True)
class BlockBudget:
    """Group-budget constraint: Σ wᵢ over ``indices`` must lie in [lo, hi].

    ``indices`` are 0-based asset columns (e.g. all funds whose
    ``Fund.asset_class == 'equity'``). ``lo``/``hi`` are decimal fractions of
    the fully-invested portfolio (0.30 = 30%). Convex (linear) by construction,
    so it composes with every objective in this module.
    """

    indices: list[int]
    lo: float
    hi: float


def _check_bound_vectors(
    n: int, cap_vec: np.ndarray | None, min_vec: np.ndarray | None
) -> tuple[np.ndarray | None, np.ndarray | None]:
    """Validate per-asset cap/min vectors; return them as float ndarrays.

    Element-wise analogue of ``_check_constraint_params``: each cap ∈ (0, 1],
    each min ≥ 0, min ≤ cap, Σ caps ≥ 1 (else sum(w)=1 is unreachable),
    Σ mins ≤ 1. All failures are fail-loud ``OptimizerError``.
    """
    cap_arr = None
    min_arr = None
    if cap_vec is not None:
        cap_arr = np.asarray(cap_vec, dtype=float).ravel()
        if cap_arr.shape != (n,):
            raise OptimizerError(f"cap_vec has shape {cap_arr.shape}, expected ({n},)")
        if ((cap_arr <= 0) | (cap_arr > 1)).any():
            raise OptimizerError("each per-asset cap must be in (0, 1]")
        if float(cap_arr.sum()) < 1 - 1e-12:
            raise OptimizerError(
                f"infeasible constraints: per-asset caps sum to {float(cap_arr.sum())} < 1 — "
                "raise some caps or add assets"
            )
    if min_vec is not None:
        min_arr = np.asarray(min_vec, dtype=float).ravel()
        if min_arr.shape != (n,):
            raise OptimizerError(f"min_vec has shape {min_arr.shape}, expected ({n},)")
        if (min_arr < 0).any():
            raise OptimizerError("each per-asset min_weight must be >= 0")
        if float(min_arr.sum()) > 1 + 1e-12:
            raise OptimizerError(
                f"infeasible constraints: per-asset minimums sum to {float(min_arr.sum())} > 1"
            )
    if cap_arr is not None and min_arr is not None and (min_arr > cap_arr + 1e-12).any():
        raise OptimizerError("a per-asset min_weight exceeds its cap")
    return cap_arr, min_arr


def bounds_constraints(
    w: cp.Variable,
    cap_vec: np.ndarray | None,
    min_vec: np.ndarray | None,
    blocks: list[BlockBudget] | None,
) -> list[cp.Constraint]:
    """Long-only + sum=1 + per-asset bound vectors + block budgets.

    Always enforces ``w >= 0`` and ``cp.sum(w) == 1`` (the universal contract).
    Per-asset bounds (when given) replace the scalar cap/min. Block budgets add
    ``lo <= Σ_{i in block} wᵢ <= hi`` per group.

    Fail-loud pre-solve infeasibility checks (raised as ``OptimizerError`` so
    they never reach the solver as a silent ``infeasible`` status):
    - an empty block index list ("empty");
    - a block floor exceeds the max attainable group sum under the caps
      ("block floor" — singular);
    - the sum of block floors exceeds 1 ("block floors" — plural).
    """
    n = int(w.shape[0])
    cap_arr, min_arr = _check_bound_vectors(n, cap_vec, min_vec)
    cons: list[cp.Constraint] = [w >= 0, cp.sum(w) == 1]
    if cap_arr is not None:
        cons.append(w <= cap_arr)
    if min_arr is not None:
        cons.append(w >= min_arr)
    if blocks:
        for b in blocks:
            if not b.indices:
                raise OptimizerError("block budget has an empty index list")
            for idx in b.indices:
                if not 0 <= idx < n:
                    raise OptimizerError(f"block index {idx} out of range (n={n})")
            if not (0.0 <= b.lo <= b.hi <= 1.0):
                raise OptimizerError(
                    f"block budget bounds must satisfy 0 <= lo <= hi <= 1, got "
                    f"[{b.lo}, {b.hi}]"
                )
            if b.lo > 0:
                if cap_arr is not None:
                    max_attainable = float(min(cap_arr[b.indices].sum(), 1.0))
                else:
                    max_attainable = float(min(len(b.indices), 1.0))
                if b.lo > max_attainable + 1e-12:
                    raise OptimizerError(
                        f"infeasible constraints: block floor {b.lo} exceeds the maximum "
                        f"attainable sum {max_attainable} of its {len(b.indices)} assets under "
                        "their caps — lower the floor or raise the caps"
                    )
            group_sum = cp.sum(w[b.indices])
            cons.append(group_sum >= b.lo)
            cons.append(group_sum <= b.hi)
        if sum(b.lo for b in blocks) > 1 + 1e-12:
            raise OptimizerError(
                f"infeasible constraints: block floors sum to {sum(b.lo for b in blocks)} > 1 — "
                "sum(w)=1 cannot satisfy all minimums"
            )
    return cons
```
Note: the per-block `block floor` (singular) and `empty` checks are inside the per-block loop so they win for their respective test cases; the disjoint-floors `block floors` (plural) check follows the loop and triggers the plural message.

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "bounds_constraints" -v`
  Expected: 5 new tests pass. Regression (MUST include the G5 structural test): `cd backend && python -m pytest tests/test_optimizer_engine.py -v` — `test_g5_structural_no_mean_estimation_in_engine_or_data` must stay green (no `.mean(` was introduced).

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/optimizer/engine.py tests/test_optimizer_engine.py && git commit -m "feat(optimizer): per-asset bound vectors + block budget constraints with empty-block/floor infeasibility guards"`
  (the Co-Authored-By footer per repo convention is appended by the engineer)

---

### Task T2C-2: Wire per-asset bounds + block budgets through `ConstraintsIn` and `min_cvar`

Extend `ConstraintsIn` with optional `block_budgets`, add a `BoundsBundle` dataclass to the engine, thread it into `solve_min_cvar` via a new `bounds` kwarg that REPLACES the scalar `base_constraints` block when present, and resolve asset-class blocks to column indices in the service.

**Files:**
- Modify: `backend/app/schemas/builder.py` — add `BlockBudgetIn`, extend `ConstraintsIn` (currently lines 60-64).
- Modify: `backend/app/optimizer/engine.py` — add `BoundsBundle` after `BlockBudget`; add `bounds` kwarg to `solve_min_cvar` (lines 237-282).
- Modify: `backend/app/optimizer/data.py` — add `load_fund_asset_class` after `load_fund_aum` (after line 165).
- Modify: `backend/app/services/portfolio_builder.py` — import `BlockBudgetIn`; add `_resolve_block_budgets`; pass `bounds` from `run_optimize`.
- Test: `backend/tests/test_optimizer_engine.py` (append) and `backend/tests/test_builder_schema.py` (append).

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_optimizer_engine.py`:
```python
# ── T2C-2: solve_min_cvar honours the bounds bundle ─────────────────────────


def test_min_cvar_with_bounds_block_budget_binds() -> None:
    scenarios = _random_scenarios(t=500, n=4)
    blocks = [engine.BlockBudget(indices=[0, 1], lo=0.0, hi=0.20)]
    weights, status = engine.solve_min_cvar(
        scenarios,
        cap=None,
        bounds=engine.BoundsBundle(cap_vec=None, min_vec=None, blocks=blocks),
    )
    _assert_valid(weights, status)
    assert weights[0] + weights[1] <= 0.20 + 1e-6
```
Append to `backend/tests/test_builder_schema.py`:
```python
def test_constraints_accepts_block_budgets() -> None:
    from app.schemas.builder import ConstraintsIn

    c = ConstraintsIn(block_budgets=[{"asset_class": "equity", "lo": 0.0, "hi": 0.3}])
    assert c.block_budgets is not None
    assert c.block_budgets[0].asset_class == "equity"
    assert c.block_budgets[0].hi == 0.3


def test_constraints_block_budget_rejects_lo_above_hi() -> None:
    import pytest
    from pydantic import ValidationError

    from app.schemas.builder import ConstraintsIn

    with pytest.raises(ValidationError):
        ConstraintsIn(block_budgets=[{"asset_class": "equity", "lo": 0.5, "hi": 0.2}])
```

- [ ] **Step 2: Run them, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py::test_min_cvar_with_bounds_block_budget_binds tests/test_builder_schema.py::test_constraints_accepts_block_budgets tests/test_builder_schema.py::test_constraints_block_budget_rejects_lo_above_hi -v`
  Expected failure: `AttributeError: ... has no attribute 'BoundsBundle'` and pydantic rejects the unknown `block_budgets` field (`ValidationError`).

- [ ] **Step 3: Write the minimal implementation.**

  3a. In `backend/app/optimizer/engine.py`, add `BoundsBundle` immediately after `BlockBudget` (from T2C-1):
```python
@dataclass(frozen=True)
class BoundsBundle:
    """Optional advanced-constraint bundle for the CVaR solvers.

    When passed to a solver, it REPLACES the scalar (cap, min_weight) block
    with ``bounds_constraints`` — per-asset bound vectors plus block budgets.
    """

    cap_vec: np.ndarray | None = None
    min_vec: np.ndarray | None = None
    blocks: list[BlockBudget] | None = None
```
  Change `solve_min_cvar`'s signature (lines 237-244) to add `bounds: BoundsBundle | None = None,` after `min_weight` and BEFORE `ret_floor`:
```python
def solve_min_cvar(
    scenarios: np.ndarray,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    bounds: BoundsBundle | None = None,
    ret_floor: float | None = None,
    mu: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
```
  DELETE the standalone `_check_constraint_params(n, cap, min_weight)` at line 264. Replace the constraint-assembly line at line 275 (`cons = base_constraints(w, cap, min_weight)`) with:
```python
    if bounds is not None:
        cons = bounds_constraints(w, bounds.cap_vec, bounds.min_vec, bounds.blocks)
    else:
        _check_constraint_params(n, cap, min_weight)
        cons = base_constraints(w, cap, min_weight)
```
  Keep the `t < 10` / `alpha` / NaN checks (254-263) and the `ret_floor`-requires-`mu` pre-check (265-269) unchanged. (The pre-check stays valid: it only guards the `ret_floor`/`mu` pairing, independent of `bounds`.)

  3b. In `backend/app/schemas/builder.py`, add `BlockBudgetIn` and a `block_budgets` field to `ConstraintsIn`. `AssetClassFilter` is defined at line 79 — AFTER the current `ConstraintsIn` (lines 60-64). To keep `BlockBudgetIn` (which references `AssetClassFilter`) valid, place the new `BlockBudgetIn` + replacement `ConstraintsIn` AFTER `DEFAULT_UNIVERSE_ASSETS` (line 92) and DELETE the original `ConstraintsIn` at lines 60-64. Insert after line 92:
```python
class BlockBudgetIn(BaseModel):
    """Σ of weights in an asset-class block must lie in [lo, hi] (decimal
    fractions). ``asset_class`` matches ``Fund.asset_class``."""

    asset_class: AssetClassFilter
    lo: Annotated[float, Field(ge=0, le=1)] = 0.0
    hi: Annotated[float, Field(ge=0, le=1)] = 1.0

    @model_validator(mode="after")
    def _check_order(self) -> "BlockBudgetIn":
        if self.lo > self.hi:
            raise ValueError(f"block budget lo ({self.lo}) must be <= hi ({self.hi})")
        return self


class ConstraintsIn(BaseModel):
    """Long-only and sum(w)=1 are always enforced; these are the knobs.

    ``block_budgets`` (per-asset-class Σ-weight bounds) are honoured ONLY by the
    ``min_cvar`` objective in v1; they are resolved against ``Fund.asset_class``
    server-side and IGNORED by the other objectives. Empty/None = no blocks.
    """

    cap: Annotated[float, Field(gt=0, le=1)] | None = 0.25
    min_weight: Annotated[float, Field(ge=0, le=1)] | None = None
    block_budgets: list[BlockBudgetIn] | None = None
```
  Note: the original `ConstraintsIn` default value at `OptimizeRequest.constraints = ConstraintsIn()` (line 139) still works because `ConstraintsIn()` remains constructible; relocating the class definition above `OptimizeRequest`'s usage is preserved (it is still defined before line 131). Verify after the edit that `ConstraintsIn` is defined before `OptimizeRequest`.

  3c. In `backend/app/optimizer/data.py`, add after `load_fund_aum` (after line 165):
```python
async def load_fund_asset_class(
    session: AsyncSession, fund_ids: list[uuid.UUID]
) -> dict[uuid.UUID, str | None]:
    """asset_class (funds.asset_class) per instrument — None where unknown."""
    if not fund_ids:
        return {}
    result = await session.execute(
        select(Fund.instrument_id, Fund.asset_class).where(
            Fund.instrument_id.in_(fund_ids)
        )
    )
    found = {row[0]: row[1] for row in result.all()}
    return {fund_id: found.get(fund_id) for fund_id in fund_ids}
```

  3d. In `backend/app/services/portfolio_builder.py`, add `BlockBudgetIn` to the `from app.schemas.builder import (...)` block (after `AssetRefIn`, line 42). Add `_resolve_block_budgets` after `_solve_mu_free` (after line 179):
```python
async def _resolve_block_budgets(
    session: AsyncSession,
    assets: list[AssetRefIn],
    labels: list[str],
    block_budgets: list[BlockBudgetIn] | None,
) -> list[engine.BlockBudget] | None:
    """Map asset-class block budgets onto engine column-index groups.

    Equities have no asset_class in the builder catalog → any equity makes a
    block-budget request fail loud (mirrors the AUM rule in
    ``_market_weights_for``).
    """
    if not block_budgets:
        return None
    equity_labels = [_ref_key(ref) for ref in assets if isinstance(ref, EquityRefIn)]
    if equity_labels:
        raise BuilderError(
            "block budgets require an asset_class for every asset; equities have "
            f"none in the builder: {', '.join(equity_labels)}"
        )
    fund_ids = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    class_by_id = await optimizer_data.load_fund_asset_class(session, fund_ids)
    index_of = {label: i for i, label in enumerate(labels)}
    out: list[engine.BlockBudget] = []
    for budget in block_budgets:
        idxs = [
            index_of[_ref_key(ref)]
            for ref in assets
            if isinstance(ref, FundRefIn)
            and class_by_id.get(ref.id) == budget.asset_class
        ]
        if not idxs:
            raise BuilderError(
                f"block budget for asset_class '{budget.asset_class}' matches no "
                "asset in the resolved universe"
            )
        out.append(engine.BlockBudget(indices=idxs, lo=budget.lo, hi=budget.hi))
    return out
```
  In `run_optimize`, immediately BEFORE the `try:` at line 279, compute the blocks:
```python
    blocks = await _resolve_block_budgets(
        session, assets, labels, payload.constraints.block_budgets
    )
```
  Replace the no-views fallback branch `else: weights, status = _solve_mu_free(...)` (lines 300-303) with an objective split so `min_cvar` receives the bounds bundle:
```python
        else:
            if payload.objective == "min_cvar":
                bundle = (
                    engine.BoundsBundle(cap_vec=None, min_vec=None, blocks=blocks)
                    if blocks
                    else None
                )
                weights, status = engine.solve_min_cvar(
                    scenarios, cap=cap, min_weight=min_weight, bounds=bundle
                )
            else:
                weights, status = _solve_mu_free(
                    payload.objective, sigma, scenarios, cap, min_weight
                )
```
  (Block budgets on non-`min_cvar` objectives are accepted by the schema but ignored in v1 — documented in the `ConstraintsIn` docstring.)

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py::test_min_cvar_with_bounds_block_budget_binds tests/test_builder_schema.py -v`
  Expected: all pass. Regression: `cd backend && python -m pytest tests/test_optimizer_engine.py tests/test_builder_schema.py tests/test_optimizer_data.py -v` (G5 structural test still green — no `.mean(` added).

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/optimizer/engine.py app/schemas/builder.py app/optimizer/data.py app/services/portfolio_builder.py tests/test_optimizer_engine.py tests/test_builder_schema.py && git commit -m "feat(optimizer): thread per-asset-class block budgets through ConstraintsIn into min_cvar"`

---

### Task T2C-3: Engine — L1 turnover / transaction-cost penalty on `min_cvar`

Add an L1 turnover penalty `λ·‖w − w₀‖₁` to the `min_cvar` objective (`w₀` = current portfolio weights). Convex, keeps the problem an LP/SOCP. Pure-engine; threading comes in T2C-4. **No `.mean(`.**

**Files:**
- Modify: `backend/app/optimizer/engine.py` — `solve_min_cvar` (lines 237-282): add `current_weights` + `turnover_lambda`.
- Test: `backend/tests/test_optimizer_engine.py` (append).

**Steps:**

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_engine.py`:
```python
# ── T2C-3: L1 turnover penalty ──────────────────────────────────────────────


def test_min_cvar_turnover_penalty_pulls_toward_current() -> None:
    scenarios = _random_scenarios(t=600, n=4, seed=7)
    current = np.array([0.25, 0.25, 0.25, 0.25])
    w_free, _ = engine.solve_min_cvar(scenarios, cap=None)
    w_sticky, status = engine.solve_min_cvar(
        scenarios, cap=None, current_weights=current, turnover_lambda=5.0
    )
    _assert_valid(w_sticky, status)
    assert np.abs(w_sticky - current).sum() < np.abs(w_free - current).sum()


def test_min_cvar_turnover_zero_lambda_matches_unpenalized() -> None:
    scenarios = _random_scenarios(t=600, n=4, seed=7)
    current = np.array([0.10, 0.20, 0.30, 0.40])
    w0, _ = engine.solve_min_cvar(scenarios, cap=None)
    w1, _ = engine.solve_min_cvar(
        scenarios, cap=None, current_weights=current, turnover_lambda=0.0
    )
    np.testing.assert_allclose(w0, w1, atol=1e-4)


def test_min_cvar_turnover_requires_current_weights() -> None:
    scenarios = _random_scenarios(t=200, n=3)
    with pytest.raises(engine.OptimizerError, match="turnover_lambda requires"):
        engine.solve_min_cvar(scenarios, turnover_lambda=1.0)


def test_min_cvar_turnover_current_weights_shape_checked() -> None:
    scenarios = _random_scenarios(t=200, n=3)
    with pytest.raises(engine.OptimizerError, match="current_weights"):
        engine.solve_min_cvar(
            scenarios, current_weights=np.array([0.5, 0.5]), turnover_lambda=1.0
        )
```
Note: `_random_scenarios(t, n, seed)` builds a 5-asset diagonal covariance and slices `cov[:n,:n]` (verified `test_optimizer_engine.py:74-77`), so `n=3` and `n=4` are valid.

- [ ] **Step 2: Run it, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "turnover" -v`
  Expected failure: `TypeError: solve_min_cvar() got an unexpected keyword argument 'current_weights'`.

- [ ] **Step 3: Write the minimal implementation.** Extend `solve_min_cvar`'s signature, adding after the `bounds` kwarg (from T2C-2) and BEFORE `ret_floor`:
```python
    current_weights: np.ndarray | None = None,
    turnover_lambda: float = 0.0,
```
  Replace the final block — the `ret_floor` floor block (lines 276-280) and the `problem`/`return` lines (281-282) — with:
```python
    if ret_floor is not None and mu is not None:
        mu_arr = np.asarray(mu, dtype=float).ravel()
        if mu_arr.shape != (n,):
            raise OptimizerError(f"min_cvar: mu has shape {mu_arr.shape}, expected ({n},)")
        cons.append(mu_arr @ w >= ret_floor)

    objective_expr = cvar
    if turnover_lambda < 0:
        raise OptimizerError(f"min_cvar: turnover_lambda must be >= 0, got {turnover_lambda}")
    if turnover_lambda > 0:
        if current_weights is None:
            raise OptimizerError(
                "min_cvar: turnover_lambda requires current_weights (the existing "
                "portfolio allocation to penalize trading away from)"
            )
        w0 = np.asarray(current_weights, dtype=float).ravel()
        if w0.shape != (n,):
            raise OptimizerError(
                f"min_cvar: current_weights has shape {w0.shape}, expected ({n},)"
            )
        objective_expr = cvar + turnover_lambda * cp.norm1(w - w0)

    problem = cp.Problem(cp.Minimize(objective_expr), cons)
    return _finalize(problem, w, "min_cvar")
```
  Everything above (scenario validation, `_check_constraint_params`/`bounds` block, `cons` assembly, the CVaR `z`/`losses`/`cvar` expression) is kept intact.

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "turnover" -v`
  Expected: 4 pass. Regression: `cd backend && python -m pytest tests/test_optimizer_engine.py -v` (G5 structural test green).

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/optimizer/engine.py tests/test_optimizer_engine.py && git commit -m "feat(optimizer): L1 turnover/transaction-cost penalty on min_cvar (lambda * ||w - w0||_1)"`

---

### Task T2C-4: Thread turnover penalty through `OptimizeRequest -> run_optimize` (current_weights from the rebalance path)

Expose `turnover_lambda` and `current_weights` on `OptimizeRequest`, thread them through `run_optimize` to `solve_min_cvar`, and have the rebalance evaluator build the label-keyed current-weights map (the load-bearing bridge).

**Files:**
- Modify: `backend/app/schemas/builder.py` — `OptimizeRequest` (add `turnover_lambda`, `current_weights`; extend `_check_asset_source`).
- Modify: `backend/app/services/portfolio_builder.py` — `run_optimize` (build `current_vec`; pass to `solve_min_cvar` on both `min_cvar` branches).
- Modify: `backend/app/rebalance/evaluator.py` — build `label_current` from `current` (line 302) + `fund_ids` (line 283); add `DEFAULT_TURNOVER_LAMBDA`; pass through `OptimizeRequest` (lines 311-315).
- Test: `backend/tests/test_builder_schema.py` (append) and `backend/tests/test_builder_route.py` (append).

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_builder_schema.py`:
```python
def test_optimize_request_accepts_turnover_and_current_weights() -> None:
    req = OptimizeRequest(
        assets=_assets(),
        turnover_lambda=2.0,
        current_weights={f"fund:{_A}": 0.6, f"fund:{_B}": 0.4},
    )
    assert req.turnover_lambda == 2.0
    assert req.current_weights == {f"fund:{_A}": 0.6, f"fund:{_B}": 0.4}


def test_optimize_request_turnover_requires_current_weights() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="current_weights"):
        OptimizeRequest(assets=_assets(), turnover_lambda=2.0)
```
Append to `backend/tests/test_builder_route.py`:
```python
async def test_optimize_turnover_penalty_stays_near_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    base = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
        "constraints": {"cap": None},
    }
    current = {f"fund:{_FUND_IDS[i]}": 0.25 for i in range(4)}
    async with _client() as client:
        free = await client.post("/builder/optimize", json=base)
        sticky = await client.post(
            "/builder/optimize",
            json={**base, "turnover_lambda": 8.0, "current_weights": current},
        )
    assert free.status_code == 200, free.text
    assert sticky.status_code == 200, sticky.text
    free_w = {w["asset"]["id"]: w["weight"] for w in free.json()["weights"]}
    sticky_w = {w["asset"]["id"]: w["weight"] for w in sticky.json()["weights"]}
    free_l1 = sum(abs(free_w[str(_FUND_IDS[i])] - 0.25) for i in range(4))
    sticky_l1 = sum(abs(sticky_w[str(_FUND_IDS[i])] - 0.25) for i in range(4))
    assert sticky_l1 < free_l1
```
Note: the `current_weights` keys are the engine label scheme `fund:<uuid>` (verified in `optimizer_data.FundAssetRef.label`, `optimizer_data.py:39-40`), matching the labels `run_optimize` reads from the returns-frame columns.

- [ ] **Step 2: Run them, expect FAIL.** Command:
  `cd backend && python -m pytest "tests/test_builder_schema.py::test_optimize_request_accepts_turnover_and_current_weights" "tests/test_builder_schema.py::test_optimize_request_turnover_requires_current_weights" tests/test_builder_route.py::test_optimize_turnover_penalty_stays_near_current -v`
  Expected failure: pydantic rejects unknown `turnover_lambda` / `current_weights` (`ValidationError`) and the route returns 422/500.

- [ ] **Step 3: Write the minimal implementation.**

  3a. In `backend/app/schemas/builder.py`, add to `OptimizeRequest` after the `bl: BLParamsIn = BLParamsIn()` field (line 146):
```python
    # L1 turnover penalty λ·‖w − w₀‖₁ on the min_cvar objective. Requires
    # ``current_weights`` (asset-label -> decimal fraction, label scheme
    # 'fund:<uuid>' / 'equity:<TICKER>'). v1: honoured only by min_cvar.
    turnover_lambda: Annotated[float, Field(ge=0)] = 0.0
    current_weights: dict[str, float] | None = None
```
  and add to `_check_asset_source` (before `return self` at line 163):
```python
        if self.turnover_lambda > 0 and not self.current_weights:
            raise ValueError(
                "turnover_lambda requires current_weights (a label -> fraction map "
                "of the existing allocation)"
            )
```

  3b. In `backend/app/services/portfolio_builder.py`, in `run_optimize`, after `index_of = {label: i for i, label in enumerate(labels)}` (line 248) build the ordered current-weight vector:
```python
    current_vec: np.ndarray | None = None
    if payload.turnover_lambda > 0 and payload.current_weights:
        try:
            current_vec = np.array(
                [payload.current_weights[label] for label in labels], dtype=float
            )
        except KeyError as exc:
            raise BuilderError(
                f"current_weights is missing an entry for asset {exc.args[0]} — it must "
                "cover every asset in the request universe"
            ) from exc
```
  In the no-views `min_cvar` branch added in T2C-2, pass the turnover args:
```python
                weights, status = engine.solve_min_cvar(
                    scenarios,
                    cap=cap,
                    min_weight=min_weight,
                    bounds=bundle,
                    current_weights=current_vec,
                    turnover_lambda=payload.turnover_lambda,
                )
```
  In the views/BL `min_cvar` branch (lines 286-299, the `solve_min_cvar(recentered, ...)` call), add the same two kwargs for symmetry:
```python
            weights, status = engine.solve_min_cvar(
                recentered,
                cap=cap,
                min_weight=min_weight,
                ret_floor=ret_floor,
                mu=mu_posterior,
                current_weights=current_vec,
                turnover_lambda=payload.turnover_lambda,
            )
```

  3c. In `backend/app/rebalance/evaluator.py`, add a module constant after `BUILDER_CAP` (line 60):
```python
DEFAULT_TURNOVER_LAMBDA = 0.0  # advisory rebalance: report drift; do not bias toward holding
```
  After `assets = [...]` (lines 305-310), build the label-keyed current map (the bridge from the rebalance path's current weights; `fund_ids` is keyed by ticker, `current` by ticker):
```python
    label_current = {
        (f"fund:{fund_ids[t]}" if t in fund_ids else f"equity:{t}"): current[t]
        for t in tickers
    }
```
  and set `request` (lines 311-315) to thread the wiring while staying behaviourally identical today:
```python
    request = OptimizeRequest(
        assets=assets,
        objective=DEFAULT_OBJECTIVE,
        constraints=ConstraintsIn(cap=viable_cap(len(assets))),
        turnover_lambda=DEFAULT_TURNOVER_LAMBDA,
        current_weights=label_current if DEFAULT_TURNOVER_LAMBDA > 0 else None,
    )
```
  Note: the equity label is `equity:<TICKER>` (verified `optimizer_data.EquityAssetRef.label`, `optimizer_data.py:48-49`) — the original draft's `t.upper()` was wrong; tickers in `tickers` are already the stored case, and the engine label is `equity:<ticker>` exactly as the returns-frame column. With `DEFAULT_TURNOVER_LAMBDA = 0.0` the validator's `turnover_lambda > 0` guard never trips and `current_weights` stays `None`, so existing rebalance tests are unaffected; `label_current` is computed but only passed when a future policy raises the lambda.

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_builder_schema.py tests/test_builder_route.py tests/test_rebalance.py -v`
  Expected: new turnover tests pass; existing builder-route and rebalance tests stay green.

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/schemas/builder.py app/services/portfolio_builder.py app/rebalance/evaluator.py tests/test_builder_schema.py tests/test_builder_route.py && git commit -m "feat(builder): thread L1 turnover penalty + current_weights through run_optimize and the rebalance path"`

---

### Task T2C-5: Engine — CVaR-as-constraint max-return solve with CLARABEL->SCS ladder + realized-CVaR verifier

Add `solve_max_return_cvar_capped(scenarios, mu, cvar_limit, alpha, cap, min_weight, bounds, cvar_tol)` solving `max μᵀw s.t. CVaR_α(w) ≤ cvar_limit`, long-only, sum=1. μ is REQUIRED (gate G5: never estimated). Uses a `CLARABEL -> SCS` ladder (ported from legacy `optimizer_service.py`) and a post-solve realized-CVaR verifier ported from `ru_cvar_lp.realized_cvar_from_weights`. **No `.mean(` — the verifier uses `np.partition`.**

**Files:**
- Modify: `backend/app/optimizer/engine.py` — add `_realized_cvar`, `_SOLVER_LADDER`, `_solve_with_ladder`, `solve_max_return_cvar_capped` at end of file.
- Test: `backend/tests/test_optimizer_engine.py` (append).

**Steps:**

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_engine.py`:
```python
# ── T2C-5: CVaR-as-constraint max-return ────────────────────────────────────


def _mu_and_scenarios(n: int = 4, t: int = 600, seed: int = 3):
    rng = np.random.default_rng(seed)
    vols = np.array([0.010, 0.012, 0.020, 0.030])[:n]
    scen = rng.normal(0.0, 1.0, size=(t, n)) * vols
    mu = np.array([0.04, 0.06, 0.10, 0.14])[:n]
    return mu, scen


def test_max_return_cvar_capped_optimal_and_caps() -> None:
    mu, scen = _mu_and_scenarios()
    w, status = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.05, alpha=0.95, cap=0.5
    )
    _assert_valid(w, status, cap=0.5)


def test_max_return_cvar_capped_tighter_limit_lowers_return() -> None:
    mu, scen = _mu_and_scenarios()
    w_loose, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.08, alpha=0.95, cap=None
    )
    w_tight, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=0.02, alpha=0.95, cap=None
    )
    assert float(mu @ w_tight) <= float(mu @ w_loose) + 1e-6


def test_max_return_cvar_capped_realized_cvar_within_limit() -> None:
    mu, scen = _mu_and_scenarios()
    limit = 0.03
    w, _ = engine.solve_max_return_cvar_capped(
        scen, mu=mu, cvar_limit=limit, alpha=0.95, cap=None
    )
    realized = engine._realized_cvar(w, scen, alpha=0.95)
    assert realized <= limit + 1e-4


def test_max_return_cvar_capped_requires_mu() -> None:
    _, scen = _mu_and_scenarios()
    with pytest.raises(engine.OptimizerError, match="mu"):
        engine.solve_max_return_cvar_capped(scen, mu=None, cvar_limit=0.05)  # type: ignore[arg-type]


def test_max_return_cvar_capped_rejects_nonpositive_limit() -> None:
    mu, scen = _mu_and_scenarios()
    with pytest.raises(engine.OptimizerError, match="cvar_limit"):
        engine.solve_max_return_cvar_capped(scen, mu=mu, cvar_limit=0.0)
```

- [ ] **Step 2: Run it, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "max_return_cvar_capped" -v`
  Expected failure: `AttributeError: ... has no attribute 'solve_max_return_cvar_capped'` (and `_realized_cvar`).

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/optimizer/engine.py` (after `solve_min_cvar`, end of file). The realized verifier is a faithful port of `realized_cvar_from_weights` (`E:/investintell-allocation/backend/quant_engine/ru_cvar_lp.py:167-215`) — same `k = max(ceil(round((1-alpha)*T,8)),1)` k-th-worst-loss estimator; the ladder mirrors the `CLARABEL -> SCS` cascade in legacy `optimizer_service.py`:
```python
def _realized_cvar(
    weights: np.ndarray, scenarios: np.ndarray, alpha: float
) -> float:
    """Empirical CVaR_α (loss-space, positive = loss) of realized weights.

    Exact Rockafellar-Uryasev estimator (port of the legacy
    ``ru_cvar_lp.realized_cvar_from_weights``): the LP optimum at the k-th
    worst loss. Used as the post-solve verifier for the CVaR-constraint path,
    where the in-LP (z, slack) auxiliaries only UPPER-BOUND the CVaR and can
    over-estimate, so the cap is re-checked on the realized weights. Uses
    ``np.partition`` (no sample mean) — gate G5 structural guard safe.
    """
    weights = np.asarray(weights, dtype=float).ravel()
    scenarios = np.asarray(scenarios, dtype=float)
    t = scenarios.shape[0]
    if t == 0:
        raise OptimizerError("scenarios must have at least one row")
    if not 0 < alpha < 1:
        raise OptimizerError(f"alpha must be in (0, 1), got {alpha}")
    losses = -scenarios @ weights
    k = max(int(np.ceil(np.round((1.0 - alpha) * t, 8))), 1)
    var_threshold = float(np.partition(losses, -k)[-k])
    u = np.maximum(losses - var_threshold, 0.0)
    return float(var_threshold + u.sum() / ((1.0 - alpha) * t))


_SOLVER_LADDER = (cp.CLARABEL, cp.SCS)


def _solve_with_ladder(
    problem: cp.Problem, w: cp.Variable, label: str
) -> tuple[np.ndarray, str]:
    """Solve trying CLARABEL then SCS (legacy optimizer_service ladder).

    Accepts ``optimal`` and ``optimal_inaccurate`` (SCS often returns the
    latter on a feasible problem). Any other terminal status across BOTH
    solvers is a fail-loud ``OptimizerError``. Reimplements ``_finalize``'s
    noise cleanup / sum=1 verification because ``_finalize`` calls
    ``problem.solve()`` with no solver argument.
    """
    last_status = "no_solver_ran"
    for solver in _SOLVER_LADDER:
        try:
            problem.solve(solver=solver)
        except cp.error.SolverError:
            continue
        last_status = str(problem.status)
        if last_status in (cp.OPTIMAL, cp.OPTIMAL_INACCURATE) and w.value is not None:
            weights = np.asarray(w.value, dtype=float).ravel()
            weights[np.abs(weights) < 1e-10] = 0.0
            if (weights < -_WEIGHT_ATOL).any():
                continue
            weights = np.clip(weights, 0.0, None)
            total = float(weights.sum())
            if total <= 0 or abs(total - 1.0) > 1e-3:
                continue
            return weights / total, "optimal"
    raise OptimizerError(
        f"{label}: no solver in {list(_SOLVER_LADDER)} produced a usable "
        f"solution (last status '{last_status}')"
    )


def solve_max_return_cvar_capped(
    scenarios: np.ndarray,
    mu: np.ndarray,
    cvar_limit: float,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    bounds: BoundsBundle | None = None,
    cvar_tol: float = 1e-4,
) -> tuple[np.ndarray, str]:
    """Max-return s.t. CVaR_α(w) ≤ ``cvar_limit`` (Rockafellar-Uryasev cap).

        max  μᵀw      s.t.  z + 1/((1−α)·T)·Σ max(−rₜᵀw − z, 0) ≤ cvar_limit,
                            long-only, sum(w)=1, caps/min/blocks.

    Gate G5: ``mu`` (annualized expected returns) is REQUIRED and never
    estimated here — by contract it is the Black-Litterman posterior. The
    in-LP CVaR auxiliaries only upper-bound the realized CVaR, so the solved
    weights are re-verified with ``_realized_cvar``; a breach beyond
    ``cvar_tol`` fails loud. Solver ladder: CLARABEL then SCS.
    """
    scenarios = np.asarray(scenarios, dtype=float)
    if scenarios.ndim != 2:
        raise OptimizerError(f"scenarios must be T×n, got ndim={scenarios.ndim}")
    if not np.isfinite(scenarios).all():
        raise OptimizerError("scenarios contain NaN/inf")
    t, n = scenarios.shape
    if t < 10:
        raise OptimizerError(f"max_return_cvar requires at least 10 scenarios, got {t}")
    if not 0 < alpha < 1:
        raise OptimizerError(f"alpha must be in (0, 1), got {alpha}")
    if mu is None:
        raise OptimizerError(
            "max_return_cvar: mu is required (BL posterior) — historical means are "
            "never estimated here (gate G5)"
        )
    mu_arr = np.asarray(mu, dtype=float).ravel()
    if mu_arr.shape != (n,):
        raise OptimizerError(f"max_return_cvar: mu has shape {mu_arr.shape}, expected ({n},)")
    if cvar_limit <= 0:
        raise OptimizerError(f"max_return_cvar: cvar_limit must be > 0, got {cvar_limit}")

    w = cp.Variable(n)
    z = cp.Variable()
    losses = -scenarios @ w
    cvar_expr = z + cp.sum(cp.pos(losses - z)) / ((1 - alpha) * t)
    if bounds is not None:
        cons = bounds_constraints(w, bounds.cap_vec, bounds.min_vec, bounds.blocks)
    else:
        _check_constraint_params(n, cap, min_weight)
        cons = base_constraints(w, cap, min_weight)
    cons.append(cvar_expr <= cvar_limit)
    problem = cp.Problem(cp.Maximize(mu_arr @ w), cons)
    weights, status = _solve_with_ladder(problem, w, "max_return_cvar")
    realized = _realized_cvar(weights, scenarios, alpha)
    if realized > cvar_limit + cvar_tol:
        raise OptimizerError(
            f"max_return_cvar: solved weights realize CVaR {realized:.6f} > limit "
            f"{cvar_limit} (tol {cvar_tol}) — the solver returned an inaccurate point"
        )
    return weights, status
```

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_optimizer_engine.py -k "max_return_cvar_capped" -v`
  Expected: 5 pass. Regression: `cd backend && python -m pytest tests/test_optimizer_engine.py -v` — `test_g5_structural_no_mean_estimation_in_engine_or_data` MUST stay green (verify the new code has no `.mean(` substring).

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/optimizer/engine.py tests/test_optimizer_engine.py && git commit -m "feat(optimizer): CVaR-as-constraint max-return solve with CLARABEL->SCS ladder and realized-CVaR verifier"`

---

### Task T2C-6: Wire `max_return_cvar` objective through the request contract (BL μ source per G5)

Add `max_return_cvar` to the `Objective` literal and a `cvar_limit` field on `OptimizeRequest`, and route it in `run_optimize` to `solve_max_return_cvar_capped` with μ from the BL posterior. This objective REQUIRES views (μ must exist) — fail loud otherwise (gate G5: no sample mean). A temporary `_regime_cvar_limit` pass-through stub keeps this task self-contained; T2C-7/T2C-8 replace it.

**Files:**
- Modify: `backend/app/schemas/builder.py` — `Objective` literal (lines 72-74); `OptimizeRequest` add `cvar_limit`; extend `_check_asset_source`.
- Modify: `backend/app/services/portfolio_builder.py` — `run_optimize` new branch; add `_regime_cvar_limit` stub.
- Test: `backend/tests/test_builder_route.py` (append) and `backend/tests/test_builder_schema.py` (append).

**Steps:**

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_builder_schema.py`:
```python
def test_objective_accepts_max_return_cvar() -> None:
    req = OptimizeRequest(
        assets=_assets(), objective="max_return_cvar", cvar_limit=0.05,
        views=[{"type": "absolute", "asset": {"kind": "fund", "id": _A}, "q": 0.1}],
    )
    assert req.objective == "max_return_cvar"
    assert req.cvar_limit == 0.05


def test_max_return_cvar_requires_cvar_limit() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="cvar_limit"):
        OptimizeRequest(
            assets=_assets(), objective="max_return_cvar",
            views=[{"type": "absolute", "asset": {"kind": "fund", "id": _A}, "q": 0.1}],
        )
```
Append to `backend/tests/test_builder_route.py`:
```python
async def test_optimize_max_return_cvar_with_views_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.10,
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.15, "confidence": 0.6}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    assert body["diagnostics"]["mu_posterior"] is not None
    assert body["diagnostics"]["status"] == "optimal"


async def test_optimize_max_return_cvar_without_bl_inputs_is_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.10,
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 422, response.text
    assert "expected returns" in response.json()["detail"].lower()
```
Note: the 422 here is raised by the Pydantic validator (no `views`), so `detail` is FastAPI's request-validation envelope (a list), not a string. The validator message "max_return_cvar needs expected returns — supply Black-Litterman 'views' ..." contains "expected returns"; FastAPI 422 bodies put the message under `detail[0]["msg"]`. Adjust the assertion to scan the serialized body so it is robust to either shape:
```python
    assert "expected returns" in response.text.lower()
```
(Use `response.text.lower()` — both the Pydantic envelope and the `BuilderError`->`humanize_error` 422 path contain the phrase. Replace the `response.json()["detail"]` assertion accordingly.)

- [ ] **Step 2: Run them, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_builder_schema.py -k "max_return_cvar" "tests/test_builder_route.py::test_optimize_max_return_cvar_with_views_happy_path" "tests/test_builder_route.py::test_optimize_max_return_cvar_without_bl_inputs_is_422" -v`
  Expected failure: `max_return_cvar` is not a valid `Objective` / `cvar_limit` is an unknown field (`ValidationError`).

- [ ] **Step 3: Write the minimal implementation.**

  3a. In `backend/app/schemas/builder.py`, extend the `Objective` literal (lines 72-74):
```python
Objective = Literal[
    "equal_weight", "min_vol", "erc", "max_diversification", "min_cvar",
    "bl_utility", "max_return_cvar",
]
```
  Add `cvar_limit` to `OptimizeRequest` (after `current_weights` from T2C-4):
```python
    # Annual tail-loss cap for ``max_return_cvar`` (decimal fraction, e.g.
    # 0.10 = 10% CVaR_95). Required for that objective, ignored otherwise.
    cvar_limit: Annotated[float, Field(gt=0, le=1)] | None = None
```
  and in `_check_asset_source` (before `return self`):
```python
        if self.objective == "max_return_cvar":
            if self.cvar_limit is None:
                raise ValueError("max_return_cvar requires a cvar_limit (tail-loss cap)")
            if self.universe is not None:
                raise ValueError(
                    "max_return_cvar needs expected returns and so requires views on an "
                    "explicit 'assets' list — it cannot run over a 'universe'"
                )
            if not self.views:
                raise ValueError(
                    "max_return_cvar needs expected returns — supply Black-Litterman "
                    "'views' (gate G5: no sample mean is ever used as the objective)"
                )
```

  3b. In `backend/app/services/portfolio_builder.py`, add the temporary stub near the other module helpers (after `humanize_error`, before `_to_data_ref`):
```python
def _regime_cvar_limit(base_limit: float) -> float:
    """Base CVaR limit, unmodified. T2C-7/T2C-8 replace this with a regime-aware
    multiplier driven by the credit-regime stress series."""
    return base_limit
```
  Add a `max_return_cvar` branch in the objective ladder of `run_optimize`, AFTER the `bl_utility` branch (lines 280-285) and BEFORE the `elif payload.objective == "min_cvar" and mu_posterior is not None:` branch (line 286):
```python
        elif payload.objective == "max_return_cvar":
            assert payload.cvar_limit is not None  # schema validator guarantees it
            if mu_posterior is None:
                raise BuilderError(
                    "max_return_cvar needs expected returns — provide views so the "
                    "Black-Litterman posterior exists (gate G5)"
                )
            limit = _regime_cvar_limit(payload.cvar_limit)  # T2C-8 makes this regime-aware
            bundle = (
                engine.BoundsBundle(cap_vec=None, min_vec=None, blocks=blocks)
                if blocks
                else None
            )
            weights, status = engine.solve_max_return_cvar_capped(
                scenarios,
                mu=mu_posterior,
                cvar_limit=limit,
                cap=cap,
                min_weight=min_weight,
                bounds=bundle,
            )
```
  (`blocks` is the variable computed in T2C-2 before the `try:`. The `scenarios` passed are the RAW scenarios, not the BL-recentered ones — μ already carries the posterior tilt, so the tail cap is checked on the actual return distribution.)

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_builder_schema.py tests/test_builder_route.py -v`
  Expected: new `max_return_cvar` tests pass; existing builder tests stay green.

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/schemas/builder.py app/services/portfolio_builder.py tests/test_builder_schema.py tests/test_builder_route.py && git commit -m "feat(builder): max_return_cvar objective (CVaR-capped max-return) with BL-posterior mu per gate G5"`

---

### Task T2C-7: Regime-conditional CVaR-limit multiplier (pure helpers)

Add pure helpers `regime_cvar_multiplier(state, *, risk_off_factor)` and `apply_regime_cvar_limit(base_limit, state, *, risk_off_factor)` in the service (they consume the regime *state*, a service concern, not pure math — so NOT in `black_litterman.py`, which is μ-only). Unit-tested directly, no DB.

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` — replace the `_regime_cvar_limit` stub from T2C-6 with the two helpers + `DEFAULT_RISK_OFF_CVAR_FACTOR`; update the T2C-6 branch call site to `apply_regime_cvar_limit` (done fully in T2C-8 when the state read lands).
- Test: new module `backend/tests/test_builder_regime_cvar.py`.

**Steps:**

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_builder_regime_cvar.py`:
```python
"""T2C-7/T2C-8 — regime-conditional CVaR limit multiplier."""

import pytest

from app.services import portfolio_builder as pb


def test_multiplier_risk_off_tightens_limit() -> None:
    assert pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.5) == 0.5


def test_multiplier_risk_on_is_neutral() -> None:
    assert pb.regime_cvar_multiplier("risk_on", risk_off_factor=0.5) == 1.0


def test_multiplier_unknown_state_is_neutral() -> None:
    assert pb.regime_cvar_multiplier(None, risk_off_factor=0.5) == 1.0
    assert pb.regime_cvar_multiplier("something_else", risk_off_factor=0.5) == 1.0


def test_multiplier_rejects_nonpositive_factor() -> None:
    with pytest.raises(ValueError, match="risk_off_factor"):
        pb.regime_cvar_multiplier("risk_off", risk_off_factor=0.0)


def test_apply_regime_to_limit_tightens() -> None:
    assert pb.apply_regime_cvar_limit(0.10, "risk_off", risk_off_factor=0.5) == pytest.approx(0.05)
    assert pb.apply_regime_cvar_limit(0.10, "risk_on", risk_off_factor=0.5) == pytest.approx(0.10)
```

- [ ] **Step 2: Run it, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_builder_regime_cvar.py -v`
  Expected failure: `AttributeError: module 'app.services.portfolio_builder' has no attribute 'regime_cvar_multiplier'`.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/services/portfolio_builder.py`, REPLACE the `_regime_cvar_limit` stub from T2C-6 with:
```python
# Default tightening applied to the CVaR limit when the credit regime is
# risk_off (halve the tolerated tail loss). Surfaced as a constant so the
# route/tests can inspect it.
DEFAULT_RISK_OFF_CVAR_FACTOR = 0.5


def regime_cvar_multiplier(state: str | None, *, risk_off_factor: float) -> float:
    """Multiplier applied to the CVaR limit given the credit-regime state.

    ``risk_off`` -> ``risk_off_factor`` (must be in (0, 1] to TIGHTEN the cap);
    any other state (risk_on / None / unknown) -> 1.0 (no change). Pure."""
    if not 0 < risk_off_factor <= 1:
        raise ValueError(f"risk_off_factor must be in (0, 1], got {risk_off_factor}")
    return risk_off_factor if state == "risk_off" else 1.0


def apply_regime_cvar_limit(
    base_limit: float, state: str | None, *, risk_off_factor: float
) -> float:
    """Effective CVaR limit = base × regime multiplier."""
    return base_limit * regime_cvar_multiplier(state, risk_off_factor=risk_off_factor)
```
  IMPORTANT: the T2C-6 `max_return_cvar` branch still calls `_regime_cvar_limit(payload.cvar_limit)`. To avoid a transient red suite, in THIS task also update that call site to the neutral-state form:
```python
            limit = apply_regime_cvar_limit(
                payload.cvar_limit, None, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR
            )
```
  (Passing `state=None` keeps the limit unchanged — behaviourally identical to the T2C-6 stub. T2C-8 replaces `None` with the live regime read.) This keeps the full suite green between T2C-7 and T2C-8.

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_builder_regime_cvar.py tests/test_builder_route.py tests/test_builder_schema.py -v`
  Expected: all pass (the `max_return_cvar` route tests still green via the `state=None` neutral path).

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/services/portfolio_builder.py tests/test_builder_regime_cvar.py && git commit -m "feat(builder): pure regime_cvar_multiplier / apply_regime_cvar_limit helpers (risk_off tightens the tail cap)"`

---

### Task T2C-8: Drive the `max_return_cvar` limit by the live credit-regime series

Thread an optional data-lake session into `run_optimize`, read the current credit-regime state via `app.services.macro_regime.fetch_credit_regime`, and apply `apply_regime_cvar_limit` to the `max_return_cvar` limit. The route injects the OPTIONAL data-lake session; when it is `None` (DSN unset, e.g. in tests) the limit is unmodified (neutral).

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` — `run_optimize` signature (add `datalake`); `max_return_cvar` branch reads the regime; add `_OVERRIDE_REGIME_STATE` test seam; import `macro_regime`.
- Modify: `backend/app/api/routes/builder.py` — inject `get_optional_datalake_session` into `optimize`.
- Test: `backend/tests/test_builder_route.py` (append) + `backend/tests/test_builder_regime_cvar.py` (append a deterministic service-level assertion).

**Steps:**

- [ ] **Step 1: Write the failing test.** Append a DETERMINISTIC service-level test to `backend/tests/test_builder_regime_cvar.py` (no solver / no DB — asserts the regime override actually tightens the limit the engine sees):
```python
async def test_run_optimize_risk_off_halves_the_cvar_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With _OVERRIDE_REGIME_STATE='risk_off', the max_return_cvar branch must
    pass cvar_limit * 0.5 to the engine solver."""
    import numpy as np
    import pandas as pd

    from app.optimizer import data as optimizer_data
    from app.optimizer import engine
    from app.schemas.builder import OptimizeRequest

    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    labels = [f"fund:00000000-0000-0000-0000-00000000000{i}" for i in range(1, 5)]
    rng = np.random.default_rng(5)

    async def fake_load(session, assets, window_days=None, today=None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0003, 0.01, n_obs) for ref in assets}, index=index
        )

    async def fake_aum(session, fund_ids):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    captured: dict[str, float] = {}

    def fake_solver(scenarios, *, mu, cvar_limit, cap=None, min_weight=None,
                    bounds=None, alpha=0.95, cvar_tol=1e-4):
        captured["cvar_limit"] = cvar_limit
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)

    payload = OptimizeRequest(
        assets=[{"kind": "fund", "id": f"00000000-0000-0000-0000-00000000000{i}"} for i in range(1, 5)],
        objective="max_return_cvar",
        cvar_limit=0.20,
        views=[{"type": "absolute", "asset": {"kind": "fund", "id": "00000000-0000-0000-0000-000000000001"}, "q": 0.15, "confidence": 0.6}],
    )
    await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]
    assert captured["cvar_limit"] == pytest.approx(0.10)  # 0.20 * 0.5
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", None, raising=False)
```
Also append an integration smoke test to `backend/tests/test_builder_route.py` (asserts the risk_off path returns 200 and is internally consistent; per open_questions the realized cap rarely binds on the stub returns, so this only smoke-tests the wiring, not the binding):
```python
async def test_optimize_max_return_cvar_risk_off_smoke(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    _stub_aum(monkeypatch)
    from app.services import portfolio_builder

    monkeypatch.setattr(portfolio_builder, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "max_return_cvar",
        "cvar_limit": 0.20,
        "views": [
            {"type": "absolute", "asset": _fund_ref(0), "q": 0.15, "confidence": 0.6}
        ],
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    monkeypatch.setattr(portfolio_builder, "_OVERRIDE_REGIME_STATE", None, raising=False)
    assert response.status_code == 200, response.text
    assert abs(sum(w["weight"] for w in response.json()["weights"]) - 1.0) < 1e-6
```

- [ ] **Step 2: Run it, expect FAIL.** Command:
  `cd backend && python -m pytest "tests/test_builder_regime_cvar.py::test_run_optimize_risk_off_halves_the_cvar_limit" tests/test_builder_route.py::test_optimize_max_return_cvar_risk_off_smoke -v`
  Expected failure: `AttributeError: ... no attribute '_OVERRIDE_REGIME_STATE'` and/or `captured["cvar_limit"] == 0.20` (regime not consulted; still neutral).

- [ ] **Step 3: Write the minimal implementation.**

  3a. In `backend/app/services/portfolio_builder.py`, add the import `from app.services import macro_regime` to the imports (after the existing `from app.services import funds_catalog` at line 53). Add the test seam near the module helpers (before `run_optimize`):
```python
# Test seam: when set, overrides the regime state read (bypasses the data-lake).
_OVERRIDE_REGIME_STATE: str | None = None
```
  Change `run_optimize`'s signature (line 237) to accept an optional data-lake session:
```python
async def run_optimize(
    session: AsyncSession,
    payload: OptimizeRequest,
    datalake: AsyncSession | None = None,
) -> OptimizeResponse:
```
  In the `max_return_cvar` branch (T2C-6/T2C-7), replace the `limit = apply_regime_cvar_limit(payload.cvar_limit, None, ...)` line with a regime read:
```python
            state = _OVERRIDE_REGIME_STATE
            if state is None and datalake is not None:
                snap = await macro_regime.fetch_credit_regime(datalake)
                state = snap.state if snap is not None else None
            limit = apply_regime_cvar_limit(
                payload.cvar_limit, state, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR
            )
```
  (`apply_regime_cvar_limit` / `DEFAULT_RISK_OFF_CVAR_FACTOR` are from T2C-7. `fetch_credit_regime(datalake) -> CreditRegimeSnapshot | None` with `.state` — verified `macro_regime.py:71-108`, `:31`.)

  3b. In `backend/app/api/routes/builder.py`, inject the OPTIONAL data-lake session. Add the import after `from app.core.db import get_session` (line 21):
```python
from app.core.datalake import get_optional_datalake_session
```
  Add a typed dep alias after `SessionDep` (line 33):
```python
DatalakeDep = Annotated[AsyncSession | None, Depends(get_optional_datalake_session)]
```
  Change the `optimize` handler (lines 37-51) to thread the session:
```python
@router.post("/optimize", response_model=OptimizeResponse)
async def optimize(
    payload: OptimizeRequest, session: SessionDep, datalake: DatalakeDep
) -> OptimizeResponse:
    """Optimize weights over a mixed fund/equity universe.

    Default objective is ``min_cvar`` (Rockafellar–Uryasev, α=0.95) on raw
    historical scenarios. With Black-Litterman ``views``, scenarios are
    re-centered on the posterior μ_BL and floored at the equilibrium return;
    ``bl_utility`` selects the explicit max-utility objective instead;
    ``max_return_cvar`` maximizes BL-posterior return under a CVaR cap, which
    is tightened in a risk_off credit regime when the data-lake is configured.
    All fractional fields are decimal fractions (0.05 = 5%).
    """
    try:
        return await portfolio_builder.run_optimize(session, payload, datalake=datalake)
    except BuilderError as exc:
        raise HTTPException(
            status_code=422, detail=portfolio_builder.humanize_error(str(exc))
        ) from exc
```
  Verified: `app.core.datalake.get_optional_datalake_session` exists and yields `AsyncSession | None` (None when `DATALAKE_DB_URL` unset), so in tests (DSN unset) the dependency yields `None` and the limit stays neutral unless `_OVERRIDE_REGIME_STATE` is set — no test-double for the data-lake DB is required. (Do NOT use `get_datalake_session`: it raises HTTP 503 when the DSN is unset, which would break every optimize call in environments without a data-lake.)

- [ ] **Step 4: Run tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_builder_regime_cvar.py tests/test_builder_route.py -v`
  Expected: pass. Full regression: `cd backend && python -m pytest tests/test_builder_route.py tests/test_builder_schema.py tests/test_optimizer_engine.py tests/test_optimizer_black_litterman.py tests/test_optimizer_data.py tests/test_rebalance.py -v`.

- [ ] **Step 5: Commit.** Command:
  `cd backend && git add app/services/portfolio_builder.py app/api/routes/builder.py tests/test_builder_route.py tests/test_builder_regime_cvar.py && git commit -m "feat(builder): regime-conditional CVaR limit — risk_off tightens the max_return_cvar tail cap via the credit-regime series"`

---

## Tier 2 — First-class walk-forward / OOS backtest service (TimeSeriesSplit, per-fold Sharpe/CVaR/maxDD, positive_folds, cost-aware)

Productize the legacy `quant_engine/backtest_service.py` (`walk_forward_backtest` / `_compute_fold_metrics`) into the Light app, upgraded with **per-fold re-optimization** (train the fold -> solve the product objective -> hold those weights out-of-sample on the test fold) and the **cost/turnover accounting** lifted from `backend/_gate_vs_full_backtest.py` (one-way bps on the L1 weight change vs the previous fold's weights, charged on the first OOS day).

**Why per-fold re-optimization (not a fixed weight vector):** the rank-12 brief asks to "re-optimize per fold". The legacy `walk_forward_backtest` keeps a single supplied weight vector FIXED across folds; `_gate_vs_full_backtest.py.run_strategy` (lines 102-128) instead re-solves the objective on each rebalance window and holds it out-of-sample with turnover cost. This plan ports the stronger `_gate_vs_full_backtest.py` design (walk-forward re-optimization), which is the one the brief specifies. The legacy fixed-weight behaviour is NOT carried over.

Architecture follows the project's analytics/service/route split exactly:
- **Pure analytics** (`app/analytics/backtest.py`, new): `assemble_walk_forward_backtest(returns, solve_fn, ...)` over an aligned returns DataFrame — no I/O. Reuses `app.analytics.historical_cvar` and `app.analytics.max_drawdown` (gate G3 comparability) and `sklearn.model_selection.TimeSeriesSplit`. Fail-loud: raises `ValueError` on insufficient/NaN data.
- **Schema** (`app/schemas/backtest.py`, new): `WalkForwardRequest` / `WalkForwardResponse` (decimal-fraction scale contract).
- **Service** (`app/services/backtest.py`, new): async `run_walk_forward_backtest(session, payload)` orchestrator that resolves assets, calls `app.optimizer.data.load_aligned_returns`, builds a per-objective `solve_fn` (closure over `app.optimizer.engine`), and calls the pure assemble. `BacktestError(ValueError)` for domain failures.
- **Route** (`app/api/routes/backtest.py`, new): thin `POST /backtest/walk-forward`, maps `BacktestError`/`ValueError` -> 422; registered in `app/main.py`.

The fold loop and metrics are TDD'd directly on synthetic numpy/pandas frames; the service is tested with `load_aligned_returns` stubbed (same monkeypatch pattern as `tests/test_builder_route.py`); the route is tested in-process with the math LIVE and only the DB loader stubbed.

**Read-only reference (NOT modified by any task):**
- `app.optimizer.data.load_aligned_returns(session, assets, window_days=None, today=None) -> pd.DataFrame` (`backend/app/optimizer/data.py:115`), `FundAssetRef(id: uuid.UUID)` (`.label` -> `"fund:<id>"`, `:34`), `EquityAssetRef(ticker: str)` (`:43`), `AssetRef = FundAssetRef | EquityAssetRef` (`:52`), `MIN_COMMON_OBS = 400` (`:31`).
- `app.optimizer.engine`: `sigma_ledoit_wolf(returns: np.ndarray) -> np.ndarray` (`:35`); `solve_min_cvar(scenarios, alpha=0.95, cap=0.25, min_weight=None, ret_floor=None, mu=None) -> tuple[np.ndarray, str]` (`:237`); `solve_min_vol(sigma, cap=0.25, min_weight=None) -> tuple[np.ndarray, str]` (`:139`); `solve_erc(sigma, cap=0.25, min_weight=None)` (`:156`); `solve_max_diversification(sigma, cap=0.25, min_weight=None)` (`:196`); `solve_equal_weight(n_assets, cap=0.25, min_weight=None)` (`:124`); `OptimizerError(ValueError)` (`:31`); `DEFAULT_CAP=0.25` (`:25`); `DEFAULT_CVAR_ALPHA=0.95` (`:26`). NOTE: every solver returns a `(weights, status)` TUPLE — the closure must unpack it.
- `app.analytics.historical_cvar(returns: pd.Series, confidence=0.95) -> float` (POSITIVE fraction; needs >= 10 returns; `backend/app/analytics/risk.py:88`, re-exported `app/analytics/__init__.py:37`) and `max_drawdown(prices: pd.Series) -> DrawdownResult` with `DrawdownResult.depth` a NEGATIVE fraction (needs >= 2 prices; `risk.py:117`, re-exported `__init__.py:39`).
- Request asset-ref / constraints / objective vocabulary reuses `app.schemas.builder`: `AssetRefIn = Annotated[FundRefIn | EquityRefIn, Field(discriminator="kind")]` (`backend/app/schemas/builder.py:29`), `ConstraintsIn` (`cap: float|None = 0.25`, `min_weight: float|None = None`, `:60`), `Objective = Literal["equal_weight","min_vol","erc","max_diversification","min_cvar","bl_utility"]` (`:72`).
- Service asset-translation helper `_to_data_ref(ref: FundRefIn | EquityRefIn) -> optimizer_data.AssetRef` already exists in `app.services.portfolio_builder` (`backend/app/services/portfolio_builder.py:91`) — reused, not duplicated. The builder calls it exactly as `[_to_data_ref(ref) for ref in assets]` over a `list[AssetRefIn]` (`portfolio_builder.py:239`), so mypy accepts the same pattern here.
- FastAPI session dependency `get_session` (`app.core.db:38`); route registration block in `app/main.py` (imports lines 7-17, `include_router(...)` block lines 51-61).

---

### Task T2D-1: Pure walk-forward fold loop + OOS metrics (`assemble_walk_forward_backtest`)

**Files:**
- Create: `backend/app/analytics/backtest.py`
- Test: `backend/tests/test_backtest_analytics.py`

- [ ] **Step 1: Write the failing test.** Covers: (a) fold count from `TimeSeriesSplit`, (b) per-fold OOS Sharpe/CVaR/maxDD computed on the held-out test window (cost-free comparison to the live F3 engine), (c) `positive_folds` / aggregate consistency, (d) turnover cost reduces realized return, (e) fail-loud on NaN and on too-short history. The `solve_fn` is a trivial stub (equal weight) so the test isolates the loop, not the optimizer. (Fold geometry verified empirically: on 600 obs with `n_splits=5, gap=2, test_size=63`, all 5 train folds are >= 283 obs and the LAST test fold is exactly `frame.iloc[-63:]`.)

```python
"""Pure walk-forward backtest: fold loop + OOS per-fold metrics.

The optimizer is injected as ``solve_fn`` so these tests exercise ONLY the
TimeSeriesSplit fold loop, the out-of-sample holding logic, the cost/turnover
accounting, and the metric aggregation — on deterministic synthetic returns.
"""

import numpy as np
import pandas as pd
import pytest

from app.analytics.backtest import FoldMetrics, WalkForwardResult, assemble_walk_forward_backtest


def _equal_weight_solver(train: np.ndarray) -> np.ndarray:
    """A mu-free, deterministic solve_fn: 1/n regardless of the train window."""
    n = train.shape[1]
    return np.full(n, 1.0 / n)


def _synthetic_returns(n_obs: int = 600, n_assets: int = 3, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-02", periods=n_obs)
    data = {
        f"fund:{i}": rng.normal(0.0004, 0.009 + 0.001 * i, n_obs) for i in range(n_assets)
    }
    return pd.DataFrame(data, index=index)


def test_fold_count_and_shapes_match_timeseriessplit() -> None:
    frame = _synthetic_returns()
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
    )
    assert isinstance(result, WalkForwardResult)
    # 5 folds requested; all clear the 252 min_train_size on 600 obs.
    assert result.n_splits_computed == 5
    assert len(result.folds) == 5
    for fold in result.folds:
        assert isinstance(fold, FoldMetrics)
        assert fold.n_obs == 63  # fixed test_size
        assert fold.train_size >= 252


def test_oos_metrics_use_test_window_and_match_engine_estimators() -> None:
    # The LAST fold's test window is exactly the final 63 rows; reconstruct the
    # equal-weight OOS series by hand and confirm the stored CVaR/maxDD equal
    # the live F3 engine on that series. cost_bps=0.0 => net == gross, so the
    # equality holds regardless of turnover.
    from app.analytics import historical_cvar, max_drawdown

    frame = _synthetic_returns()
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=0.0,
    )
    last = result.folds[-1]
    test_block = frame.iloc[-63:]
    oos_daily = pd.Series(test_block.to_numpy() @ np.full(3, 1.0 / 3), index=test_block.index)
    expected_cvar = historical_cvar(oos_daily, confidence=0.95)
    nav = (1.0 + oos_daily).cumprod()
    expected_dd = max_drawdown(nav).depth  # negative fraction
    assert last.cvar_95 == pytest.approx(round(expected_cvar, 6), abs=1e-9)
    assert last.max_drawdown == pytest.approx(round(expected_dd, 6), abs=1e-9)


def test_positive_folds_and_aggregates() -> None:
    frame = _synthetic_returns(seed=1)
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
    )
    sharpes = [f.sharpe for f in result.folds]
    assert result.positive_folds == sum(1 for s in sharpes if s > 0)
    assert result.mean_sharpe == pytest.approx(round(float(np.mean(sharpes)), 6), abs=1e-9)
    assert result.std_sharpe == pytest.approx(round(float(np.std(sharpes, ddof=1)), 6), abs=1e-9)


def test_costs_reduce_realized_return_vs_zero_cost() -> None:
    frame = _synthetic_returns(seed=3)
    gross = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=0.0,
    )
    net = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=50.0,
    )
    # Equal-weight re-solve is constant => turnover is 0 only AFTER the first
    # fold; the first fold buys in from cash (turnover==1.0) so cost bites it.
    assert net.folds[0].turnover == pytest.approx(1.0, abs=1e-9)
    assert net.folds[0].net_return < gross.folds[0].net_return
    # No turnover on later folds (weights identical) => identical net return.
    assert net.folds[-1].turnover == pytest.approx(0.0, abs=1e-9)
    assert net.folds[-1].net_return == pytest.approx(gross.folds[-1].net_return, abs=1e-12)


def test_nan_in_returns_is_fail_loud() -> None:
    frame = _synthetic_returns()
    frame.iloc[10, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        assemble_walk_forward_backtest(frame, _equal_weight_solver)


def test_too_few_observations_is_fail_loud() -> None:
    frame = _synthetic_returns(n_obs=120)  # < min_train_size + n_splits*test_size
    with pytest.raises(ValueError, match="insufficient history"):
        assemble_walk_forward_backtest(
            frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63, min_train_size=252
        )
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_backtest_analytics.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.analytics.backtest'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/backtest.py`.

```python
"""Pure walk-forward / out-of-sample backtest (Tier 2).

Ports ``quant_engine/backtest_service.py`` into the Light analytics layer and
upgrades it to PER-FOLD RE-OPTIMIZATION with cost/turnover accounting (the
model in ``_gate_vs_full_backtest.py``): for each expanding ``TimeSeriesSplit``
fold we (1) solve the objective on the TRAIN window, (2) hold those weights
OUT-OF-SAMPLE over the TEST window, (3) charge a one-way transaction cost on
the L1 weight change vs the previous fold's weights (on the first OOS day), and
(4) score the realized test series with the SAME F3 estimators the rest of the
app uses (``historical_cvar``, ``max_drawdown``) for gate-G3 comparability.

Pure computation — no I/O, no DB, no FastAPI. Fail-loud: ``ValueError`` on
insufficient or NaN data (never NaN out). Scale contract: every fractional
quantity (returns, Sharpe inputs, CVaR, drawdown, turnover) is a decimal
fraction (0.05 = 5%), never 0-100.

Design defaults (from the legacy service docstring):
- ``gap=2``: daily-dealing liquid funds (T+1 NAV + 1 buffer day).
- ``test_size=63``: fixed 3-month OOS windows for comparable per-fold Sharpe.
- expanding window (TimeSeriesSplit default): covariance stability over rolling.
- report fold consistency (positive_folds), not p-values (Finucane 2004).
"""

import math
from collections.abc import Callable
from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.risk import historical_cvar, max_drawdown

TRADING_DAYS = 252

DEFAULT_N_SPLITS = 5
DEFAULT_GAP = 2
DEFAULT_TEST_SIZE = 63
DEFAULT_MIN_TRAIN_SIZE = 252
DEFAULT_CVAR_CONFIDENCE = 0.95
DEFAULT_COST_BPS = 10.0

# A solve function maps a TRAIN return matrix (T_train x n) to long-only,
# sum-to-1 weights (n,). Injected by the caller so the pure loop never imports
# the optimizer (keeps this module dependency-light and unit-testable).
SolveFn = Callable[[np.ndarray], np.ndarray]


@dataclass(frozen=True)
class FoldMetrics:
    """OOS metrics for one walk-forward fold.

    ``sharpe`` annualized; ``cvar_95`` POSITIVE fraction (F3 sign convention);
    ``max_drawdown`` NEGATIVE fraction; ``turnover`` is the L1 weight change vs
    the previous fold (0..2); ``gross_return``/``net_return`` are the fold's
    cumulative OOS returns before/after the one-way transaction cost.
    """

    fold: int
    train_size: int
    n_obs: int
    sharpe: float
    cvar_95: float
    max_drawdown: float
    turnover: float
    gross_return: float
    net_return: float


@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[FoldMetrics]
    n_splits_computed: int
    mean_sharpe: float
    std_sharpe: float
    positive_folds: int
    mean_turnover: float
    cost_bps: float


def _annualized_sharpe(returns: np.ndarray, risk_free_daily: float) -> float:
    """Annualized Sharpe of a daily OOS series (mean-excess / std x sqrt(252))."""
    std = float(np.std(returns, ddof=1))
    if std <= 0:
        raise ValueError("fold Sharpe undefined: zero-variance out-of-sample returns")
    mean = float(np.mean(returns))
    return (mean - risk_free_daily) / std * math.sqrt(TRADING_DAYS)


def assemble_walk_forward_backtest(
    returns: pd.DataFrame,
    solve_fn: SolveFn,
    *,
    n_splits: int = DEFAULT_N_SPLITS,
    gap: int = DEFAULT_GAP,
    test_size: int = DEFAULT_TEST_SIZE,
    min_train_size: int = DEFAULT_MIN_TRAIN_SIZE,
    cvar_confidence: float = DEFAULT_CVAR_CONFIDENCE,
    cost_bps: float = DEFAULT_COST_BPS,
    risk_free_annual: float = 0.0,
) -> WalkForwardResult:
    """Walk-forward OOS backtest with per-fold re-optimization.

    Args:
        returns: T x n aligned daily-return frame (rows = dates, cols = assets).
        solve_fn: maps a train return matrix to long-only sum-1 weights.
        n_splits / gap / test_size / min_train_size: TimeSeriesSplit knobs.
        cvar_confidence: tail level for the per-fold CVaR (default 0.95).
        cost_bps: one-way transaction cost in basis points charged on the L1
            weight change vs the previous fold, on the first OOS day.
        risk_free_annual: annual risk-free rate for the Sharpe excess (default
            0.0 — the project's mean/std convention).

    Returns:
        WalkForwardResult with per-fold metrics and the consistency aggregates.

    Raises:
        ValueError: NaN/non-finite returns, fewer than 2 assets, a window too
            short for even one qualifying fold, or a zero-variance fold.
    """
    from sklearn.model_selection import TimeSeriesSplit

    if returns.shape[1] < 2:
        raise ValueError("walk-forward backtest requires at least 2 assets")
    matrix = returns.to_numpy(dtype=float)
    if not np.isfinite(matrix).all():
        raise ValueError("returns contain NaN/inf — refusing to backtest")
    if not 0 < cvar_confidence < 1:
        raise ValueError(f"cvar_confidence must be in (0, 1), got {cvar_confidence}")
    if cost_bps < 0:
        raise ValueError(f"cost_bps must be >= 0, got {cost_bps}")
    if test_size < 2:
        raise ValueError(f"test_size must be >= 2, got {test_size}")

    t = matrix.shape[0]
    # TimeSeriesSplit needs n_splits*test_size of trailing rows plus room for a
    # min_train_size first-fold train window; this pre-check fires our own
    # message before sklearn raises its generic 'Too many splits' error.
    if t < min_train_size + n_splits * test_size:
        raise ValueError(
            f"insufficient history: {t} observations cannot support {n_splits} folds of "
            f"test_size={test_size} after a {min_train_size}-day minimum train window — "
            "lower n_splits/test_size or supply more history"
        )

    risk_free_daily = risk_free_annual / TRADING_DAYS
    one_way_cost = cost_bps / 1e4
    index = returns.index

    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size)
    folds: list[FoldMetrics] = []
    w_prev = np.zeros(matrix.shape[1])
    for fold_idx, (train_idx, test_idx) in enumerate(tscv.split(matrix)):
        if len(train_idx) < min_train_size:
            continue
        weights = np.asarray(solve_fn(matrix[train_idx]), dtype=float).ravel()
        turnover = float(np.abs(weights - w_prev).sum())

        test_block = matrix[test_idx]
        gross_daily = test_block @ weights
        # Charge the one-way cost on the first OOS day (research-script model:
        # _gate_vs_full_backtest.py:123 sr[0] -= turn * COST_BPS / 1e4).
        net_daily = gross_daily.copy()
        net_daily[0] -= turnover * one_way_cost

        oos_index = index[test_idx]
        net_series = pd.Series(net_daily, index=oos_index)
        nav = (1.0 + net_series).cumprod()

        sharpe = _annualized_sharpe(net_daily, risk_free_daily)
        cvar_95 = historical_cvar(net_series, confidence=cvar_confidence)
        max_dd = max_drawdown(nav).depth
        gross_return = float(np.prod(1.0 + gross_daily) - 1.0)
        net_return = float(np.prod(1.0 + net_daily) - 1.0)

        folds.append(
            FoldMetrics(
                fold=fold_idx,
                train_size=len(train_idx),
                n_obs=len(test_idx),
                sharpe=round(sharpe, 6),
                cvar_95=round(cvar_95, 6),
                max_drawdown=round(max_dd, 6),
                turnover=round(turnover, 6),
                gross_return=round(gross_return, 6),
                net_return=round(net_return, 6),
            )
        )
        w_prev = weights

    if not folds:
        raise ValueError(
            "no fold cleared the minimum train window — lower min_train_size or "
            "supply more history"
        )

    sharpes = [f.sharpe for f in folds]
    mean_sharpe = float(np.mean(sharpes))
    std_sharpe = float(np.std(sharpes, ddof=1)) if len(sharpes) > 1 else 0.0
    positive_folds = sum(1 for s in sharpes if s > 0)
    mean_turnover = float(np.mean([f.turnover for f in folds]))

    return WalkForwardResult(
        folds=folds,
        n_splits_computed=len(folds),
        mean_sharpe=round(mean_sharpe, 6),
        std_sharpe=round(std_sharpe, 6),
        positive_folds=positive_folds,
        mean_turnover=round(mean_turnover, 6),
        cost_bps=cost_bps,
    )
```

  Note on the metric tests: every stored fold field is `round(..., 6)`, so the engine-equality test (Step 1) compares against `round(expected_cvar, 6)` / `round(expected_dd, 6)`, and the aggregate test compares against `round(mean/std, 6)` — keeping the assertions exact.

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_backtest_analytics.py -v`
  Expected: all 6 tests pass.

- [ ] **Step 5: Commit.**
  Command: `cd backend && git add app/analytics/backtest.py tests/test_backtest_analytics.py`
  Message:
  ```
  feat(analytics): pure walk-forward OOS backtest (TimeSeriesSplit, per-fold Sharpe/CVaR/maxDD, cost-aware)

  Port quant_engine/backtest_service.py into app.analytics with per-fold
  re-optimization and the turnover/cost accounting from _gate_vs_full_backtest.py.
  Reuses app.analytics.historical_cvar / max_drawdown (gate G3). Fail-loud on
  NaN / insufficient history.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T2D-2: Backtest schemas (`WalkForwardRequest` / `WalkForwardResponse`)

**Files:**
- Create: `backend/app/schemas/backtest.py`
- Test: `backend/tests/test_backtest_schema.py`

- [ ] **Step 1: Write the failing test.** Validates the request shape (reuses builder `AssetRefIn`/`ConstraintsIn`/`Objective`, defaults, bounds) and that the response models round-trip.

```python
"""Schema contract for POST /backtest/walk-forward."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.backtest import (
    FoldMetricsOut,
    WalkForwardParams,
    WalkForwardRequest,
    WalkForwardResponse,
)


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}"))}


def test_request_defaults() -> None:
    req = WalkForwardRequest.model_validate(
        {"assets": [_fund(1), _fund(2)], "objective": "min_cvar"}
    )
    assert req.objective == "min_cvar"
    assert req.n_splits == 5
    assert req.gap == 2
    assert req.test_size == 63
    assert req.min_train_size == 252
    assert req.cost_bps == 10.0
    assert req.risk_free_annual == 0.0
    assert req.window_days is None
    assert req.constraints.cap == 0.25


def test_request_requires_two_assets() -> None:
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate({"assets": [_fund(1)], "objective": "min_cvar"})


def test_request_rejects_bad_bounds() -> None:
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "n_splits": 1}  # ge=2
        )
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "cost_bps": -1.0}  # ge=0
        )


def test_response_round_trips() -> None:
    fold = FoldMetricsOut(
        fold=0, train_size=283, n_obs=63, sharpe=1.1, cvar_95=0.02,
        max_drawdown=-0.08, turnover=1.0, gross_return=0.03, net_return=0.029,
    )
    resp = WalkForwardResponse(
        folds=[fold],
        params=WalkForwardParams(
            objective="min_cvar", n_obs=600, n_splits_computed=5, gap=2,
            test_size=63, min_train_size=252, cost_bps=10.0,
        ),
        mean_sharpe=1.1, std_sharpe=0.0, positive_folds=1, mean_turnover=1.0,
    )
    dumped = resp.model_dump()
    assert dumped["folds"][0]["max_drawdown"] == -0.08
    assert dumped["positive_folds"] == 1
    assert dumped["params"]["objective"] == "min_cvar"
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_backtest_schema.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.schemas.backtest'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/schemas/backtest.py`.

```python
"""Schemas for the walk-forward backtest endpoint (Tier 2).

Scale contract (project-wide): weights, returns, Sharpe, CVaR, drawdown and
turnover are decimal fractions (0.05 = 5%), never 0-100. ``cost_bps`` is the
one-way transaction cost in BASIS POINTS (10 = 0.10%). The asset references and
constraints reuse the builder vocabulary so a backtest takes the exact request
a user already built in POST /builder/optimize.
"""

from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.builder import AssetRefIn, ConstraintsIn, Objective

# -- Request -------------------------------------------------------------------


class WalkForwardRequest(BaseModel):
    """Walk-forward / OOS backtest over an explicit asset list.

    The objective is RE-OPTIMIZED on each expanding TimeSeriesSplit train fold
    and held out-of-sample over the following test fold. ``min_cvar`` (the
    product default) is mu-free; BL ``views`` are intentionally NOT accepted
    here (a backtest must not peek at user views formed with hindsight) —
    backtests run the mu-free objectives only.
    """

    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)]
    objective: Objective = "min_cvar"
    constraints: ConstraintsIn = ConstraintsIn()
    # None = FULL nav_timeseries history (the builder's convention). An explicit
    # int (30..3650 days) narrows the loaded window before folding.
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None
    n_splits: Annotated[int, Field(ge=2, le=20)] = 5
    gap: Annotated[int, Field(ge=0, le=63)] = 2
    test_size: Annotated[int, Field(ge=20, le=504)] = 63
    min_train_size: Annotated[int, Field(ge=60, le=5000)] = 252
    cost_bps: Annotated[float, Field(ge=0, le=1000)] = 10.0
    risk_free_annual: Annotated[float, Field(ge=0, le=1)] = 0.0


# -- Response ------------------------------------------------------------------


class FoldMetricsOut(BaseModel):
    fold: int
    train_size: int
    n_obs: int
    sharpe: float
    # POSITIVE fraction (F3 sign convention): cvar_95=0.02 -> 2% expected tail loss.
    cvar_95: float
    # NEGATIVE fraction: -0.08 -> 8% peak-to-trough OOS drawdown.
    max_drawdown: float
    # L1 weight change vs the previous fold (0..2).
    turnover: float
    gross_return: float
    net_return: float


class WalkForwardParams(BaseModel):
    objective: Objective
    n_obs: int
    n_splits_computed: int
    gap: int
    test_size: int
    min_train_size: int
    cost_bps: float


class WalkForwardResponse(BaseModel):
    folds: list[FoldMetricsOut]
    params: WalkForwardParams
    mean_sharpe: float
    std_sharpe: float
    # Consistency, not significance: how many of n folds had a positive Sharpe.
    positive_folds: int
    mean_turnover: float
```

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_backtest_schema.py -v`
  Expected: all 4 tests pass.

- [ ] **Step 5: Commit.**
  Command: `cd backend && git add app/schemas/backtest.py tests/test_backtest_schema.py`
  Message:
  ```
  feat(schemas): WalkForwardRequest/Response for the OOS backtest endpoint

  Reuses builder AssetRefIn/ConstraintsIn/Objective so a backtest accepts the
  same universe a user built. mu-free objectives only (no hindsight views).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T2D-3: Service orchestrator (`run_walk_forward_backtest`) + per-objective `solve_fn`

**Files:**
- Create: `backend/app/services/backtest.py`
- Test: `backend/tests/test_backtest_service.py`

- [ ] **Step 1: Write the failing test.** Stubs `app.optimizer.data.load_aligned_returns` (same pattern as `tests/test_builder_route.py`) and asserts the orchestrator: resolves refs, builds the right `solve_fn` per objective, returns a populated `WalkForwardResponse`, and maps loader/optimizer/analytics `ValueError`s to `BacktestError`.

```python
"""Service-level walk-forward backtest orchestration.

The DB loader is stubbed at its canonical module (app.optimizer.data); the
optimizer engine and the pure assemble stay LIVE so the happy path exercises
the real per-fold re-optimization end to end.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data
from app.schemas.backtest import WalkForwardRequest, WalkForwardResponse
from app.services import backtest as backtest_service
from app.services.backtest import BacktestError, _solve_fn_for

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 600) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int | None = None,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(5)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
             for i, ref in enumerate(assets)},
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


def test_solve_fn_min_cvar_is_long_only_sum_one() -> None:
    rng = np.random.default_rng(0)
    train = rng.normal(0.0005, 0.01, (300, 3))
    fn = _solve_fn_for("min_cvar", cap=0.5, min_weight=None)
    w = fn(train)
    assert abs(float(w.sum()) - 1.0) < 1e-6
    assert (w >= -1e-9).all() and (w <= 0.5 + 1e-6).all()


def test_solve_fn_min_vol_uses_covariance() -> None:
    rng = np.random.default_rng(1)
    train = rng.normal(0.0, 0.01, (300, 4))
    fn = _solve_fn_for("min_vol", cap=0.4, min_weight=None)
    w = fn(train)
    assert abs(float(w.sum()) - 1.0) < 1e-6


def test_solve_fn_bl_utility_is_rejected() -> None:
    with pytest.raises(BacktestError, match="bl_utility is not backtestable"):
        _solve_fn_for("bl_utility", cap=0.25, min_weight=None)


async def test_run_min_cvar_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "min_cvar"}
    )
    resp = await backtest_service.run_walk_forward_backtest(None, payload)
    assert isinstance(resp, WalkForwardResponse)
    assert resp.params.objective == "min_cvar"
    assert resp.params.n_obs == 600
    assert resp.params.n_splits_computed == 5
    assert len(resp.folds) == 5
    assert resp.params.cost_bps == 10.0
    assert 0 <= resp.positive_folds <= 5
    assert all(f.cvar_95 >= 0 for f in resp.folds)
    assert all(f.max_drawdown <= 0 for f in resp.folds)


async def test_run_maps_insufficient_common_history_to_backtest_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    )
    with pytest.raises(BacktestError, match="insufficient common history"):
        await backtest_service.run_walk_forward_backtest(None, payload)


async def test_run_maps_short_window_to_backtest_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # 300 obs cannot support 5 folds x 63 test after a 252 train minimum; the
    # loader stub bypasses MIN_COMMON_OBS so the analytics guard fires.
    _stub_returns(monkeypatch, n_obs=300)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1)], "objective": "min_cvar",
         "n_splits": 5, "test_size": 63, "min_train_size": 252}
    )
    with pytest.raises(BacktestError, match="insufficient history"):
        await backtest_service.run_walk_forward_backtest(None, payload)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_backtest_service.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.services.backtest'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/services/backtest.py`.

```python
"""Walk-forward backtest service (Tier 2): DB -> aligned returns -> per-fold
re-optimization -> OOS metrics -> response schema.

Pattern (project convention): the pure ``assemble_*`` lives in
``app.analytics.backtest``; this module is the async ``run_*`` orchestrator
(loads from the data-lake, builds the per-objective solve closure, calls the
pure assemble, maps to the schema). The route stays thin.

solve_fn contract: each objective's closure maps a TRAIN return matrix to
long-only sum-1 weights using ONLY ``app.optimizer.engine`` (mu-free). No BL /
views path: a backtest must not consume hindsight views.

Error contract: every domain failure (bad/short history, solver non-optimal,
zero-variance fold) raises ``BacktestError`` -> 422 with the message verbatim.
"""

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.backtest import SolveFn, assemble_walk_forward_backtest
from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.backtest import (
    FoldMetricsOut,
    WalkForwardParams,
    WalkForwardRequest,
    WalkForwardResponse,
)
from app.schemas.builder import Objective
from app.services.portfolio_builder import _to_data_ref


class BacktestError(ValueError):
    """Domain failure in the backtest — mapped verbatim to HTTP 422."""


def _solve_fn_for(
    objective: Objective, cap: float | None, min_weight: float | None
) -> SolveFn:
    """Build the per-fold solver closure for a mu-free objective.

    Wraps ``app.optimizer.engine`` so each call re-optimizes on the fold's TRAIN
    matrix. ``min_cvar`` solves on the raw scenarios (Rockafellar-Uryasev); the
    covariance objectives shrink Sigma with Ledoit-Wolf first. BL objectives
    (``bl_utility``) are rejected up-front — backtests are mu-free. Each engine
    solver returns a ``(weights, status)`` tuple, so the closure keeps weights.
    """
    if objective == "bl_utility":
        raise BacktestError(
            "bl_utility is not backtestable: Black-Litterman views are formed "
            "with hindsight; backtest a mu-free objective (min_cvar/min_vol/erc/"
            "max_diversification/equal_weight)"
        )

    def solve(train: np.ndarray) -> np.ndarray:
        if objective == "min_cvar":
            weights, _ = engine.solve_min_cvar(train, cap=cap, min_weight=min_weight)
        elif objective == "min_vol":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_min_vol(sigma, cap=cap, min_weight=min_weight)
        elif objective == "erc":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_erc(sigma, cap=cap, min_weight=min_weight)
        elif objective == "max_diversification":
            sigma = engine.sigma_ledoit_wolf(train)
            weights, _ = engine.solve_max_diversification(
                sigma, cap=cap, min_weight=min_weight
            )
        elif objective == "equal_weight":
            weights, _ = engine.solve_equal_weight(
                train.shape[1], cap=cap, min_weight=min_weight
            )
        else:  # pragma: no cover - Objective Literal + bl_utility guard above
            raise BacktestError(f"unknown objective: {objective}")
        return weights

    return solve


async def run_walk_forward_backtest(
    session: AsyncSession, payload: WalkForwardRequest
) -> WalkForwardResponse:
    refs = [_to_data_ref(ref) for ref in payload.assets]
    try:
        frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc

    solve_fn = _solve_fn_for(
        payload.objective, payload.constraints.cap, payload.constraints.min_weight
    )
    try:
        result = assemble_walk_forward_backtest(
            frame,
            solve_fn,
            n_splits=payload.n_splits,
            gap=payload.gap,
            test_size=payload.test_size,
            min_train_size=payload.min_train_size,
            cost_bps=payload.cost_bps,
            risk_free_annual=payload.risk_free_annual,
        )
    except engine.OptimizerError as exc:
        raise BacktestError(str(exc)) from exc
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc

    return WalkForwardResponse(
        folds=[
            FoldMetricsOut(
                fold=f.fold,
                train_size=f.train_size,
                n_obs=f.n_obs,
                sharpe=f.sharpe,
                cvar_95=f.cvar_95,
                max_drawdown=f.max_drawdown,
                turnover=f.turnover,
                gross_return=f.gross_return,
                net_return=f.net_return,
            )
            for f in result.folds
        ],
        params=WalkForwardParams(
            objective=payload.objective,
            n_obs=len(frame),
            n_splits_computed=result.n_splits_computed,
            gap=payload.gap,
            test_size=payload.test_size,
            min_train_size=payload.min_train_size,
            cost_bps=result.cost_bps,
        ),
        mean_sharpe=result.mean_sharpe,
        std_sharpe=result.std_sharpe,
        positive_folds=result.positive_folds,
        mean_turnover=result.mean_turnover,
    )
```

  NOTE: `engine.OptimizerError` is a subclass of `ValueError`, so the explicit `except engine.OptimizerError` is redundant for catching but documents intent; both arms raise `BacktestError`. Keep both for readability (matches the builder service style).

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_backtest_service.py -v`
  Expected: all 6 tests pass (two `_solve_fn_for` weight tests, the bl_utility rejection, the happy path, and the two error-mapping tests). The min_cvar happy path runs the real cvxpy solver 5 times (a few seconds).

- [ ] **Step 5: Commit.**
  Command: `cd backend && git add app/services/backtest.py tests/test_backtest_service.py`
  Message:
  ```
  feat(services): run_walk_forward_backtest orchestrator + per-objective solve_fn

  Loads aligned returns from the data-lake, builds a mu-free per-fold solver over
  app.optimizer.engine, calls the pure assemble, maps ValueError/OptimizerError
  to BacktestError. bl_utility rejected (no hindsight views in a backtest).

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T2D-4: Thin route `POST /backtest/walk-forward` + app registration

**Files:**
- Create: `backend/app/api/routes/backtest.py`
- Modify: `backend/app/main.py` (imports block lines 7-17 — add one import; `include_router` block lines 51-61 — add one `include_router`)
- Test: `backend/tests/test_backtest_route.py`

- [ ] **Step 1: Write the failing test.** Mirrors `tests/test_builder_route.py`: builds its own `AsyncClient` over `create_app()`, overrides `get_session`, stubs `load_aligned_returns`, and asserts the 200 happy path and the 422 mappings (insufficient history, bl_utility rejected). Pydantic bounds (n_splits=1) -> 422 automatically.

```python
"""Tests for POST /backtest/walk-forward (app/api/routes/backtest.py).

The DB loader is stubbed at app.optimizer.data; the optimizer + pure backtest
math stay LIVE so the happy path runs the real per-fold re-optimization.
"""

import datetime as dt
import uuid
from typing import Any

import numpy as np
import pandas as pd
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.optimizer import data as optimizer_data

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 6)]


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_returns(monkeypatch: pytest.MonkeyPatch, n_obs: int = 600) -> None:
    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int | None = None,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(9)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
             for i, ref in enumerate(assets)},
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_walk_forward_min_cvar_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["params"]["objective"] == "min_cvar"
    assert body["params"]["n_splits_computed"] == 5
    assert len(body["folds"]) == 5
    assert 0 <= body["positive_folds"] <= 5
    assert all(f["cvar_95"] >= 0 for f in body["folds"])
    assert all(f["max_drawdown"] <= 0 for f in body["folds"])
    assert body["folds"][0]["turnover"] == pytest.approx(1.0, abs=1e-6)  # buy-in from cash


async def test_walk_forward_min_vol_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(i) for i in range(4)], "objective": "min_vol",
               "constraints": {"cap": 0.4}}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["params"]["objective"] == "min_vol"


async def test_insufficient_common_history_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_short_window_maps_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch, n_obs=300)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "min_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "insufficient history" in response.json()["detail"]


async def test_bl_utility_rejected_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "bl_utility"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "bl_utility is not backtestable" in response.json()["detail"]


async def test_bad_n_splits_is_pydantic_422() -> None:
    payload = {"assets": [_fund(0), _fund(1)], "n_splits": 1}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422  # Field(ge=2)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_backtest_route.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.api.routes.backtest'` at import time (the test imports nothing from the route module directly, so the actual first failure is the happy-path `assert response.status_code == 200` failing with `404 Not Found` because the route is unregistered). Either way, Step 3 fixes it.

- [ ] **Step 3a: Write the route module.** Create `backend/app/api/routes/backtest.py`.

```python
"""Walk-forward backtest endpoint (Tier 2): POST /backtest/walk-forward.

Thin route over ``app.services.backtest``: validate (Pydantic) -> run the
service -> map domain/solver failures to 422 with the message verbatim.

Error mapping (fail loud):
- request shape / bounds (n_splits, cost_bps, asset count)  -> 422 (Pydantic)
- unknown asset / no history in window                      -> 422
- < MIN_COMMON_OBS common observations                      -> 422
- history too short for the requested folds                 -> 422
- bl_utility objective (no hindsight views in a backtest)   -> 422
- solver not 'optimal' / infeasible constraints             -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.schemas.backtest import WalkForwardRequest, WalkForwardResponse
from app.services import backtest as backtest_service
from app.services.backtest import BacktestError

router = APIRouter(prefix="/backtest", tags=["backtest"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


@router.post("/walk-forward", response_model=WalkForwardResponse)
async def walk_forward(
    payload: WalkForwardRequest, session: SessionDep
) -> WalkForwardResponse:
    """Walk-forward / out-of-sample backtest of a mu-free objective.

    Re-optimizes the objective on each expanding TimeSeriesSplit train fold and
    scores the held-out test fold (Sharpe, CVaR 95, max drawdown), folding in a
    one-way transaction cost on the L1 weight change vs the previous fold. The
    response reports per-fold metrics plus the ``positive_folds`` consistency
    count. All fractional fields are decimal fractions (0.05 = 5%).
    """
    try:
        return await backtest_service.run_walk_forward_backtest(session, payload)
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Step 3b: Register the router in `app/main.py`.** Add the import alphabetically alongside the other route imports (immediately before `from app.api.routes import builder as builder_router`, line 7):

```python
from app.api.routes import backtest as backtest_router
```

  and include it in `create_app()` (immediately before `application.include_router(builder_router.router)`, line 58):

```python
    application.include_router(backtest_router.router)
```

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_backtest_route.py -v`
  Expected: all 6 tests pass.

- [ ] **Step 5: Commit.**
  Command: `cd backend && git add app/api/routes/backtest.py app/main.py tests/test_backtest_route.py`
  Message:
  ```
  feat(api): POST /backtest/walk-forward thin route + registration

  Maps BacktestError -> 422 verbatim; registers the backtest router in
  create_app alongside builder.

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T2D-5: Full-suite green + lint/type gate

**Files:**
- Test/verify only (no new source).

- [ ] **Step 1: Run the new cluster's tests together.**
  Command: `cd backend && python -m pytest tests/test_backtest_analytics.py tests/test_backtest_schema.py tests/test_backtest_service.py tests/test_backtest_route.py -v`
  Expected: all pass (6 + 4 + 6 + 6 = 22 tests).

- [ ] **Step 2: Run the broader optimizer/builder suites to confirm no regression** (the service imports `_to_data_ref` from `portfolio_builder` and `main.py` gained one router).
  Command: `cd backend && python -m pytest tests/test_builder_route.py tests/test_builder_schema.py tests/test_optimizer_engine.py tests/test_optimizer_data.py tests/test_health.py -v`
  Expected: all pass (no behavior changed in those modules; only `main.py` gained one import and one `include_router`).

- [ ] **Step 3: Lint + type-check the new files** (project gate: ruff `select = ["E","F","I","UP","B"]`, line-length 100; mypy `disallow_untyped_defs = true`).
  Command: `cd backend && python -m ruff check app/analytics/backtest.py app/services/backtest.py app/schemas/backtest.py app/api/routes/backtest.py && python -m mypy app/analytics/backtest.py app/services/backtest.py app/schemas/backtest.py app/api/routes/backtest.py`
  Expected: ruff reports no issues; mypy reports no errors. The `[_to_data_ref(ref) for ref in payload.assets]` pattern already type-checks in `portfolio_builder.run_optimize` (line 239) so it passes here too. Keep the `# pragma: no cover` on the unreachable `else` arm of `_solve_fn_for` (matches the engine's style for Literal-guarded branches).

- [ ] **Step 4: Commit any lint/type fixups (only if Steps 1-3 surfaced something).**
  Command: `cd backend && git add -A` then commit:
  ```
  chore(backtest): satisfy ruff/mypy gate for the walk-forward service

  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```
  (If Steps 1-3 are already clean, skip this commit.)

---

## Tier 2 — Factor risk attribution (over existing IPCA fits) + Kritzman–Li absorption ratio

This cluster ports two distinct techniques from the legacy quant engine onto the Light app's DB-first architecture, **without re-fitting any model**.

- **Rank 15 (Task T2E-1):** a *pure* `absorption_ratio` function (Kritzman & Li 2010) — a single eigendecomposition of a universe **correlation** matrix, returning the fraction of variance absorbed by the top eigenvectors, the first-eigenvalue concentration ratio, and discrete status bands. Ported from `correlation_regime_service.py::_compute_concentration` (legacy), stripped of the shrinkage/denoising/regime machinery (those live elsewhere) so it can be unit-tested directly on synthetic correlation matrices. The Light already has a `correlation_matrix(returns)->pd.DataFrame` builder in `app/analytics/portfolio.py` (line 219) that a future caller can feed in; `absorption_ratio` accepts any square symmetric correlation matrix (numpy or `.to_numpy()` of that frame).
- **Rank 14 (Task T2E-2):** a factor-attribution *service* that READS the IPCA fits persisted in the data-lake table `factor_model_fits` (Gamma loadings `L×K` + factor returns `K×T`, materialized by `investintell-datalake-workers/src/workers/factor_model.py`), projects a fund's latest rank-transformed characteristics onto betas (`β = Γᵀ z`), and produces a per-factor Euler risk decomposition (systematic vs specific variance, portfolio R²). It builds **on top of** existing fits — it never refits. Ported from `factor_model_service.py::compute_factor_contributions` (legacy Euler decomposition, lines 951–1008) adapted to the IPCA `β = Γᵀ z` instrumented-beta convention.

Order: **T2E-1 first** (no data-lake dependency, pure, self-contained), **T2E-2 second** (depends on the data-lake reader pattern; consumes nothing from T2E-1 but reuses the project's eigendecomposition discipline).

> **Gate G5 (μ-free) compliance:** neither task consumes a sample mean of returns. T2E-1 is an eigendecomposition of a correlation matrix. T2E-2 uses only the *covariance* of the persisted factor-return series (second moment) and instrumented betas — no expected-return estimate enters. Expected returns remain confined to `app/optimizer/black_litterman.py`.

> **Async test convention (verified):** `pyproject.toml` sets `asyncio_mode = "auto"` (pytest-asyncio) and the repo also uses the `anyio` pytest plugin. Existing async service tests mark coroutines with `@pytest.mark.anyio` (see `tests/test_macro_regime_route.py`, which passes 3/3). T2E-2's async orchestrator tests follow that same `@pytest.mark.anyio` convention — no extra fixture or dependency is required.

---

### Task T2E-1: `absorption_ratio` pure analytics fn (Kritzman–Li, single eigendecomposition)

Port the absorption / first-eigenvalue-concentration logic from the legacy `_compute_concentration` into a standalone pure function in the analytics layer. Single `np.linalg.eigvalsh` on the (symmetric) correlation matrix; **no** shrinkage, **no** Marchenko–Pastur denoising (those are out of scope here), **no** I/O.

**Files:**
- Create: `backend/app/analytics/absorption.py`
- Modify: `backend/app/analytics/__init__.py` (add `from app.analytics.absorption import AbsorptionResult, absorption_ratio` to the import group; add `"AbsorptionResult"` and `"absorption_ratio"` to `__all__` in alphabetical position)
- Test: `backend/tests/test_analytics_absorption.py`

Legacy reference for the math (read, do not import): `E:/investintell-allocation/backend/quant_engine/correlation_regime_service.py` lines 254–312 (`_compute_concentration`): `eigvalsh` then eigenvalues sorted descending and floored at 0 (lines 258–260); `k = max(1, n // 5)` (Kritzman & Li 2010, line 293); `absorption_ratio = sum(eig[:k]) / sum(eig)` (line 294); first-eigenvalue band thresholds `concentration_high=0.80`, `concentration_moderate=0.60` with **strict** `>` comparisons (0.60 exactly ⇒ "diversified", lines 282–288); absorption bands `absorption_critical=0.90`, `absorption_warning=0.80` (strict `>`, lines 296–301). Verified numerically: identity(n=10) ⇒ absorption 0.2 / first 0.1; equicorrelated(n=10, ρ=0.9) ⇒ first 0.91 / absorption(k=2) 0.92; 2×2 ρ=0.20 ⇒ first 0.60 exactly; 2×2 ρ=0.21 ⇒ first 0.605; identity(n=20, top_k=1) ⇒ 0.05.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_absorption.py` with the COMPLETE code below.

```python
"""Unit tests for app/analytics/absorption.py (Kritzman–Li absorption ratio).

Pure function over a symmetric correlation matrix — no DB, no I/O. The matrix
is the kind app/analytics/portfolio.py::correlation_matrix produces. Mirrors the
legacy semantics in correlation_regime_service.py::_compute_concentration but
with no shrinkage / denoising machinery.
"""

import numpy as np
import pytest

from app.analytics.absorption import AbsorptionResult, absorption_ratio


def _identity_corr(n: int) -> np.ndarray:
    """Perfectly diversified: identity → every eigenvalue == 1."""
    return np.eye(n, dtype=float)


def _equicorrelated(n: int, rho: float) -> np.ndarray:
    """Constant off-diagonal correlation rho; eigenvalues are
    {1 + (n-1)rho} (once) and {1 - rho} (n-1 times)."""
    m = np.full((n, n), rho, dtype=float)
    np.fill_diagonal(m, 1.0)
    return m


def test_identity_matrix_is_maximally_diversified() -> None:
    # n=10, k = max(1, 10//5) = 2 top eigenvalues over total 10 → 0.2
    result = absorption_ratio(_identity_corr(10))
    assert isinstance(result, AbsorptionResult)
    assert result.n_assets == 10
    assert result.top_k == 2
    assert result.absorption_ratio == pytest.approx(0.2, abs=1e-9)
    assert result.first_eigenvalue_ratio == pytest.approx(0.1, abs=1e-9)
    assert result.absorption_status == "normal"
    assert result.concentration_status == "diversified"
    # eigenvalues are returned sorted descending, summing to the trace (== n)
    assert result.eigenvalues[0] >= result.eigenvalues[-1]
    assert sum(result.eigenvalues) == pytest.approx(10.0, abs=1e-9)


def test_equicorrelated_high_rho_is_concentrated_and_critical() -> None:
    # rho=0.9, n=10: lambda_1 = 1 + 9*0.9 = 9.1; total = 10.
    # first_eigenvalue_ratio = 0.91 (> 0.80 → high_concentration).
    # k=2: top-2 = 9.1 + (1-0.9) = 9.2 → absorption 0.92 (> 0.90 → critical).
    result = absorption_ratio(_equicorrelated(10, 0.9))
    assert result.first_eigenvalue_ratio == pytest.approx(0.91, abs=1e-9)
    assert result.concentration_status == "high_concentration"
    assert result.absorption_ratio == pytest.approx(0.92, abs=1e-9)
    assert result.absorption_status == "critical"


def test_moderate_band_is_strict_greater_than() -> None:
    # Construct a 2x2 corr with lambda_1/total exactly 0.60 → "diversified"
    # (strict >). 2x2 corr [[1, r],[r, 1]] has eigenvalues 1+r, 1-r; total 2.
    # first ratio = (1+r)/2 = 0.60 → r = 0.20.
    result = absorption_ratio(_equicorrelated(2, 0.20))
    assert result.first_eigenvalue_ratio == pytest.approx(0.60, abs=1e-9)
    assert result.concentration_status == "diversified"  # 0.60 NOT > 0.60
    # Nudge above the band: r=0.21 → first ratio 0.605 → moderate.
    result2 = absorption_ratio(_equicorrelated(2, 0.21))
    assert result2.first_eigenvalue_ratio == pytest.approx(0.605, abs=1e-9)
    assert result2.concentration_status == "moderate_concentration"


def test_custom_top_k_overrides_default() -> None:
    result = absorption_ratio(_identity_corr(20), top_k=1)
    assert result.top_k == 1
    assert result.absorption_ratio == pytest.approx(0.05, abs=1e-9)  # 1/20


def test_accepts_dataframe_to_numpy() -> None:
    # The optimizer's correlation_matrix returns a DataFrame; .to_numpy() of it
    # must work the same as a raw array.
    pd = pytest.importorskip("pandas")
    frame = pd.DataFrame(_identity_corr(10))
    result = absorption_ratio(frame.to_numpy(dtype=float))
    assert result.absorption_ratio == pytest.approx(0.2, abs=1e-9)


def test_rejects_non_square_matrix() -> None:
    with pytest.raises(ValueError, match="square"):
        absorption_ratio(np.ones((3, 4), dtype=float))


def test_rejects_nan_or_inf() -> None:
    bad = _identity_corr(3)
    bad[0, 1] = bad[1, 0] = np.nan
    with pytest.raises(ValueError, match="NaN or infinite"):
        absorption_ratio(bad)


def test_rejects_asymmetric_matrix() -> None:
    bad = np.array([[1.0, 0.5], [0.2, 1.0]], dtype=float)
    with pytest.raises(ValueError, match="symmetric"):
        absorption_ratio(bad)


def test_rejects_too_few_assets() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        absorption_ratio(np.array([[1.0]], dtype=float))


def test_rejects_degenerate_zero_trace() -> None:
    with pytest.raises(ValueError, match="non-positive total variance"):
        absorption_ratio(np.zeros((3, 3), dtype=float))


def test_top_k_out_of_range_is_loud() -> None:
    with pytest.raises(ValueError, match="top_k"):
        absorption_ratio(_identity_corr(5), top_k=6)
    with pytest.raises(ValueError, match="top_k"):
        absorption_ratio(_identity_corr(5), top_k=0)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_absorption.py -v`. Expected failure: `ModuleNotFoundError: No module named 'app.analytics.absorption'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/absorption.py` with the COMPLETE code below.

```python
"""Kritzman–Li (2010) absorption ratio — pure eigendecomposition diagnostic.

A single ``np.linalg.eigvalsh`` of a universe CORRELATION matrix (the kind
``app.analytics.portfolio.correlation_matrix`` produces): the fraction of total
variance absorbed by the top ``k`` eigenvectors plus the first-eigenvalue
concentration band. A high absorption ratio means a few eigenvectors explain
most of the cross-sectional variance — markets are tightly coupled (fragile /
risk-off prone).

Ported from ``correlation_regime_service.py::_compute_concentration`` (legacy
quant engine, lines 254-312), stripped of the Ledoit-Wolf shrinkage and
Marchenko-Pastur denoising that belong to the regime service; this function is
the bare concentration diagnostic so it can be unit-tested on synthetic
matrices.

Conventions (project-wide): pure numpy, no I/O, fail loud on bad input
(ValueError on non-square / asymmetric / NaN / degenerate). Ratios are decimal
fractions in [0, 1] (0.91 = 91%), never 0-100.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Kritzman & Li (2010) default: top k = N/5 eigenvectors (at least 1).
_DEFAULT_K_DIVISOR = 5

# First-eigenvalue concentration bands (strict >): mirror the legacy
# _compute_concentration thresholds.
_CONCENTRATION_HIGH = 0.80
_CONCENTRATION_MODERATE = 0.60

# Absorption-ratio status bands (strict >).
_ABSORPTION_CRITICAL = 0.90
_ABSORPTION_WARNING = 0.80

_SYMMETRY_ATOL = 1e-8


@dataclass(frozen=True, slots=True)
class AbsorptionResult:
    """Kritzman–Li absorption diagnostic over a correlation matrix."""

    n_assets: int
    top_k: int
    eigenvalues: tuple[float, ...]  # descending, floored at 0
    first_eigenvalue_ratio: float  # eig[0] / sum(eig), in [0, 1]
    absorption_ratio: float  # sum(eig[:k]) / sum(eig), in [0, 1]
    concentration_status: str  # "diversified" | "moderate_concentration" | "high_concentration"
    absorption_status: str  # "normal" | "warning" | "critical"


def absorption_ratio(
    corr_matrix: np.ndarray,
    *,
    top_k: int | None = None,
) -> AbsorptionResult:
    """Compute the Kritzman–Li absorption ratio of a correlation matrix.

    Parameters
    ----------
    corr_matrix : np.ndarray
        Square, symmetric (N×N) correlation matrix — typically the
        ``.to_numpy()`` of ``app.analytics.portfolio.correlation_matrix`` on the
        aligned returns frame. Must be finite.
    top_k : int | None
        Number of leading eigenvectors to sum for the absorption ratio.
        Defaults to ``max(1, N // 5)`` (Kritzman & Li 2010). When given it must
        satisfy ``1 <= top_k <= N``.

    Raises
    ------
    ValueError
        If the matrix is not square, not symmetric, contains NaN/inf, has fewer
        than 2 assets, has non-positive total variance (trace), or ``top_k`` is
        out of range. Never returns NaN (fail-loud contract).
    """
    matrix = np.asarray(corr_matrix, dtype=float)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError(
            f"absorption_ratio requires a square matrix, got shape {matrix.shape}"
        )
    n = matrix.shape[0]
    if n < 2:
        raise ValueError(f"absorption_ratio requires at least 2 assets, got {n}")
    if not np.isfinite(matrix).all():
        raise ValueError(
            "absorption_ratio received NaN or infinite values; clean the matrix first"
        )
    if not np.allclose(matrix, matrix.T, atol=_SYMMETRY_ATOL):
        raise ValueError("absorption_ratio requires a symmetric correlation matrix")

    k = max(1, n // _DEFAULT_K_DIVISOR) if top_k is None else top_k
    if not 1 <= k <= n:
        raise ValueError(
            f"absorption_ratio top_k must be in [1, {n}], got {top_k}"
        )

    # Single eigendecomposition of the symmetric matrix.
    eigenvalues = np.linalg.eigvalsh(matrix)
    eigenvalues = np.sort(eigenvalues)[::-1]  # descending
    eigenvalues = np.maximum(eigenvalues, 0.0)  # numerical floor (PSD)

    total = float(eigenvalues.sum())
    if total <= 0.0:
        raise ValueError(
            "absorption_ratio is undefined: non-positive total variance (trace)"
        )

    first_ratio = float(eigenvalues[0] / total)
    absorption = float(eigenvalues[:k].sum() / total)

    if first_ratio > _CONCENTRATION_HIGH:
        concentration_status = "high_concentration"
    elif first_ratio > _CONCENTRATION_MODERATE:
        concentration_status = "moderate_concentration"
    else:
        concentration_status = "diversified"

    if absorption > _ABSORPTION_CRITICAL:
        absorption_status = "critical"
    elif absorption > _ABSORPTION_WARNING:
        absorption_status = "warning"
    else:
        absorption_status = "normal"

    return AbsorptionResult(
        n_assets=n,
        top_k=k,
        eigenvalues=tuple(float(e) for e in eigenvalues),
        first_eigenvalue_ratio=first_ratio,
        absorption_ratio=absorption,
        concentration_status=concentration_status,
        absorption_status=absorption_status,
    )
```

  Then add the exports to `backend/app/analytics/__init__.py`. The current import group (lines 8–45) starts with `from app.analytics.distribution import Histogram, return_histogram`. Insert this line immediately **above** that `distribution` import (so the import group stays alphabetized by module name — `absorption` < `distribution`):

```python
from app.analytics.absorption import AbsorptionResult, absorption_ratio
```

  And add the two names to the `__all__` list (currently lines 47–77), keeping it alphabetically sorted. The list is mixed-case; the existing entries begin `"BestWorst", "DEFAULT_INITIAL_NAV", "DrawdownResult", "Histogram", "MIN_IN_RANGE_RETURNS", "align_returns", "annualized_volatility", ...`. Insert `"AbsorptionResult"` as the **first** entry (uppercase `A` sorts before `B`), and insert `"absorption_ratio"` **before** `"align_returns"` (the lowercase section: `absorption_ratio` < `align_returns` because `"abs" < "ali"`):

```python
    "AbsorptionResult",
```
```python
    "absorption_ratio",
```

  After editing, the head of `__all__` reads `"AbsorptionResult", "BestWorst", ...` and the lowercase run reads `... "MIN_IN_RANGE_RETURNS", "absorption_ratio", "align_returns", "annualized_volatility", ...`.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_absorption.py -v`. Expected: all 12 tests pass. Then confirm the package import still resolves: `cd backend && python -c "from app.analytics import AbsorptionResult, absorption_ratio; print('ok')"` → prints `ok`.

- [ ] **Step 5: Commit.** Commands:
  - `cd backend && git add app/analytics/absorption.py app/analytics/__init__.py tests/test_analytics_absorption.py`
  - `git commit -m "feat(analytics): Kritzman–Li absorption ratio pure fn (rank 15)"`

---

### Task T2E-2: factor-attribution service over persisted IPCA fits (no refit)

A DB-first service that READS the IPCA fit from `factor_model_fits` and a fund's latest characteristics from `equity_characteristics_monthly` (both in the TimescaleDB Cloud data-lake), projects characteristics → betas (`β = Γᵀ z`, the IPCA instrumented-beta convention from the worker docstring lines 17–19), and decomposes portfolio variance into per-factor Euler contributions + systematic-vs-specific split + portfolio R². **It does not refit anything** — it only consumes the persisted Gamma and factor-return series.

Pattern (project convention): a pure `assemble_factor_attribution(...)->FactorAttribution` (no I/O, unit-tested on synthetic inputs) + an async `run_factor_attribution(datalake, ...)` orchestrator that reads the data-lake and calls assemble. The reader functions follow the `app/services/lookthrough.py` `text()` + dataclass + `f()` None-coalescer pattern (see lines 105–192) and use `datalake.execute(SQL, params)` as in `fetch_many_lookthroughs` (lines 162–176).

**Files:**
- Create: `backend/app/services/factor_attribution.py`
- Test: `backend/tests/test_factor_attribution_service.py`

Source references (read, do not import):
- `E:/investintell-datalake-workers/src/workers/factor_model.py` — the fit producer. Confirms: model `r_{i,t} = (z_{i,t-1}ᵀ Γ) f_t + e` (lines 17–19); `gamma` is `L×K` (`CHARS_COLS` order = rows, lines 76–83; `_upsert` writes `gamma_loadings = fit["gamma"].tolist()  # L x K`, line 486); `factor_returns` persisted as `{"dates":[ISO...], "values": K×T}` (`_upsert` lines 491–494, `"values": fit["factor_returns"].tolist()  # K x T`); characteristics rank-transformed per period to `[-0.5, +0.5]` via `rank_transform` (lines 96–104, `groupby(level="month").transform(lambda g: g.rank(pct=True) - 0.5)`); `_upsert` writes ONLY gamma_loadings + factor_returns + scalar stats (no Σ_f, no per-fund D_i — lines 495–527).
- `E:/investintell-datalake-workers/schemas/factor_model.sql` — `factor_model_fits` columns (lines 22–35): `fit_id, engine, fit_date, universe_hash, k_factors, gamma_loadings (jsonb), factor_returns (jsonb), oos_r_squared, converged, n_iterations, created_at, asset_class`; lookup index on `(engine, asset_class, fit_date)` (lines 39–40); natural key `(engine, asset_class, universe_hash, fit_date)` (lines 44–45).
- `E:/investintell-datalake-workers/schemas/characteristics.sql` — `equity_characteristics_monthly(instrument_id, ticker, as_of, size_log_mkt_cap, book_to_market, mom_12_1, quality_roa, investment_growth, profitability_gross, source_filing_date, computed_at)`, PK `(instrument_id, as_of)` (lines 48–61), all six chars `NUMERIC(10,4)`.
- `E:/investintell-allocation/backend/quant_engine/factor_model_service.py` lines 951–1008 (`compute_factor_contributions`) — the Euler decomposition being ported: `factor_cov` quadratic form (line 972, `np.cov(factor_returns, rowvar=False)` because legacy holds `T×K`); `systematic_var = exposures @ factor_cov @ exposures` (line 977); per-factor marginal `factor_marginals = exposures * (factor_cov @ exposures)` (line 992); portfolio R² = `systematic_var / total_var` (line 1007). **NB:** the worker persists `K×T`, so T2E-2 uses `np.cov(..., rowvar=True)` — see the implementation note.
- `E:/investintell-light/backend/app/services/lookthrough.py` — the data-lake reader pattern (`text()`, `datalake: AsyncSession`, dataclass results, the `f()` None-coalescer at lines 127–128).

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_factor_attribution_service.py` with the COMPLETE code below. It tests (a) the pure assemble on synthetic Gamma/factor-returns/characteristics with a hand-verifiable single-factor case, and (b) the async orchestrator against a fake data-lake session that mimics the two reader queries. All numbers below were verified numerically against the implementation in Step 3.

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_factor_attribution_service.py -v`. Expected failure: `ModuleNotFoundError: No module named 'app.services.factor_attribution'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/services/factor_attribution.py` with the COMPLETE code below.

```python
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

    chars = ranked.loc[fund_ids, CHARS_COLS].to_numpy(dtype=float)  # N×L
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
```

  **Implementation notes (load-bearing, do not regress):**
  - `np.cov(factor_returns, rowvar=True)` is intentional: the worker persists `K×T` (factors on rows), unlike the legacy `T×K`/`rowvar=False`. Verified: `np.cov` of a 1×T input returns a 0-dim scalar, so `np.atleast_2d` reshapes it to `1×1` for the single-factor case.
  - The `specific_variance` proxy `D_i = systematic_per_fund_i` (floored at `1e-8`) is deliberately conservative and strictly positive; swap in worker-persisted `D_i` when available (open_questions). For a fund whose betas are all 0 after rank-transform (e.g. fund B in the orchestrator test, `z_size = 0.0`), `systematic_per_fund_i = 0` so the floor `1e-8` applies — keeping `total_var > 0`.
  - `_rank_transform_cross_section` calls `df.rank(pct=True) - 0.5`; for ties (equal values across the cross-section) pandas uses `method='average'`, which does not affect the size-driven beta in the tests because Gamma rows for the other characteristics are 0.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_factor_attribution_service.py -v`. Expected: all 8 tests pass (5 pure assemble + 3 orchestrator). Then run the whole new surface together: `cd backend && python -m pytest tests/test_analytics_absorption.py tests/test_factor_attribution_service.py -v` → all pass.

- [ ] **Step 5: Commit.** Commands:
  - `cd backend && git add app/services/factor_attribution.py tests/test_factor_attribution_service.py`
  - `git commit -m "feat(services): factor risk attribution over persisted IPCA fits (rank 14)"`

---

## Tier 2 — Surface orphaned worker outputs + mandate→δ ladder + He–Litterman 3σ view-consistency warning

This cluster has three independent tasks. Order them T2F-1 → T2F-2 → T2F-3 (no hard dependency, but this order goes schema → request-shape → diagnostics, the natural reviewing order). Every task is TDD: failing test first, minimal implementation, green, commit.

Context the implementer needs (all verified against source on 2026-06-14):

- The worker `E:/investintell-datalake-workers/src/workers/risk_metrics.py` already computes and upserts `volatility_garch`, `vol_model`, `cvar_999_evt`, `evt_xi_shape` into the `fund_risk_metrics` table: `_METRIC_COLUMNS` lists all four (lines 55-67), and they are assigned in `compute_metrics` (`evt_xi_shape` line 275, `cvar_999_evt` line 292, `volatility_garch` line 554, `vol_model` line 555). The worker schema `E:/investintell-datalake-workers/schemas/risk_metrics.sql` defines them as `volatility_garch numeric(10,6)` (line 44), `vol_model varchar` (line 45), `cvar_999_evt numeric(12,6)` (line 72), `evt_xi_shape numeric(12,6)` (line 73).
- The Light app reads the **materialized view** `fund_risk_latest_mv`, NOT the base table. The MV (`backend/db/ddl/2026-06-13_dynamic_catalog.sql`, `CREATE MATERIALIZED VIEW` SELECT lines 63-76) selects **33 columns** and does NOT include the four orphaned ones — so they are computed-but-unreachable. `cvar_99_evt` IS already plumbed (MV line 70, ORM `backend/app/models/fund.py:170`, schema `backend/app/schemas/funds.py:89`); the gap is its three siblings plus `volatility_garch` / `vol_model`.
- The app surfaces risk via `FundRiskOut.model_validate(profile.risk)` (`backend/app/api/routes/funds.py:291`), where `profile.risk` is a `FundRiskLatest` ORM instance and `FundRiskOut` uses `model_config = ConfigDict(from_attributes=True)` (`backend/app/schemas/funds.py:67`). `FundRiskOut` is built ONLY via `model_validate` (no positional construction anywhere — grep confirms a single definition site), so adding nullable columns to the ORM + the MV + the schema surfaces them end-to-end with zero risk to other call sites.

---

### Task T2F-1: Surface the orphaned EVT/GARCH worker columns through the MV, ORM and FundRiskOut

**Files:**
- Modify `backend/app/models/fund.py` — `class FundRiskLatest`, insert after `cvar_99_evt` (line 170, inside the metric block ending line 181).
- Modify `backend/app/schemas/funds.py` — `class FundRiskOut`, insert after line 89 (`cvar_99_evt: float | None`).
- Modify `backend/db/ddl/2026-06-13_dynamic_catalog.sql` — the `fund_risk_latest_mv` SELECT column list (lines 63-76) and the header comment that says `33 columns` (line 62).
- Create `backend/tests/test_funds_risk_schema.py` — schema serialization test.
- Modify `backend/tests/test_models.py` — add an MV-column assertion next to the existing `test_fund_risk_latest_pk_and_metric_lockstep` (lines 491-504; uses the module-level `_table` helper defined at line 17).

- [ ] **Step 1: Write the failing tests.** Create `backend/tests/test_funds_risk_schema.py` asserting `FundRiskOut` accepts and round-trips the four orphaned fields from an attribute object (mirrors the live `model_validate(profile.risk)` path), and append a metadata assertion to `test_models.py` that the MV-backed ORM declares the new columns as nullable Numeric/String.

```python
# backend/tests/test_funds_risk_schema.py
"""T2F-1: the orphaned EVT/GARCH worker outputs must be surfaced through
FundRiskOut. The worker computes volatility_garch / vol_model / cvar_999_evt /
evt_xi_shape into fund_risk_metrics, but the MV-backed FundRiskLatest ORM and
FundRiskOut schema never exposed them. They are validated from attributes,
exactly as the profile route does (FundRiskOut.model_validate(profile.risk))."""

import datetime as dt

from app.schemas.funds import FundRiskOut


class _RiskAttrs:
    """Minimal stand-in for a FundRiskLatest ORM row (from_attributes path)."""

    def __init__(self, **kwargs: object) -> None:
        # Every FundRiskOut field defaults to None; override the ones we test.
        for name in FundRiskOut.model_fields:
            setattr(self, name, None)
        self.calc_date = dt.date(2026, 6, 13)
        for k, v in kwargs.items():
            setattr(self, k, v)


def test_fund_risk_out_declares_orphaned_worker_fields() -> None:
    fields = set(FundRiskOut.model_fields)
    assert {"volatility_garch", "vol_model", "cvar_999_evt", "evt_xi_shape"} <= fields


def test_fund_risk_out_round_trips_orphaned_fields() -> None:
    attrs = _RiskAttrs(
        volatility_garch=0.1834,
        vol_model="GARCH(1,1)",
        cvar_999_evt=-0.0921,
        evt_xi_shape=0.213,
    )
    out = FundRiskOut.model_validate(attrs)
    assert out.volatility_garch == 0.1834
    assert out.vol_model == "GARCH(1,1)"
    assert out.cvar_999_evt == -0.0921
    assert out.evt_xi_shape == 0.213


def test_fund_risk_out_orphaned_fields_are_optional() -> None:
    """They are nullable in the source (per-metric gaps) — None must validate."""
    out = FundRiskOut.model_validate(_RiskAttrs())
    assert out.volatility_garch is None
    assert out.vol_model is None
    assert out.cvar_999_evt is None
    assert out.evt_xi_shape is None
```

Append to `backend/tests/test_models.py` (after `test_fund_risk_latest_pk_and_metric_lockstep`, i.e. after line 504):

```python
def test_fund_risk_latest_surfaces_orphaned_worker_columns() -> None:
    """T2F-1: volatility_garch / vol_model / cvar_999_evt / evt_xi_shape are
    computed by the worker into fund_risk_metrics; the MV-backed ORM must carry
    them (nullable) so FundRiskOut can surface them."""
    from sqlalchemy import Numeric, String

    table = _table("fund_risk_latest_mv")
    for col in ("volatility_garch", "cvar_999_evt", "evt_xi_shape"):
        assert col in table.c, col
        assert isinstance(table.c[col].type, Numeric), col
        assert table.c[col].nullable is True, col
    assert "vol_model" in table.c
    assert isinstance(table.c["vol_model"].type, String)
    assert table.c["vol_model"].nullable is True
```

- [ ] **Step 2: Run the tests, expect FAIL.**
```
cd backend && python -m pytest tests/test_funds_risk_schema.py tests/test_models.py::test_fund_risk_latest_surfaces_orphaned_worker_columns -v
```
Expected failure: `test_fund_risk_out_declares_orphaned_worker_fields` fails the subset assertion (the four names are not in `FundRiskOut.model_fields`); `test_fund_risk_out_round_trips_orphaned_fields` fails with `AttributeError` on `out.volatility_garch` (the validated model has no such attribute — `model_validate` ignores attrs that map to no declared field); `test_fund_risk_latest_surfaces_orphaned_worker_columns` fails on `assert 'volatility_garch' in table.c` (the MV-backed ORM has no such column).

- [ ] **Step 3: Add the columns to the ORM, the schema and the MV DDL (minimal change).**

In `backend/app/models/fund.py`, in `class FundRiskLatest`, insert the four columns immediately after `cvar_99_evt` (line 170). `Numeric` and `String` are already imported (lines 27-35). `vol_model` is the only String; the other three are Numeric (matching `numeric(10,6)` / `numeric(12,6)` in the worker schema):

```python
    cvar_99_evt: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    cvar_999_evt: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    evt_xi_shape: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    volatility_garch: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    vol_model: Mapped[str | None] = mapped_column(String, nullable=True)
```

In `backend/app/schemas/funds.py`, in `class FundRiskOut`, insert after line 89 (`cvar_99_evt: float | None`):

```python
    cvar_99_evt: float | None
    cvar_999_evt: float | None
    evt_xi_shape: float | None
    volatility_garch: float | None
    vol_model: str | None
```

In `backend/db/ddl/2026-06-13_dynamic_catalog.sql`, replace the header comment (line 62) and the `fund_risk_latest_mv` SELECT (lines 63-76) so the column list adds `volatility_garch`, `vol_model`, `cvar_999_evt`, `evt_xi_shape` and the header reflects the new count (33 → 37):

```sql
-- Latest risk metrics per fund (replaces the sync_funds.py fund_risk_latest
-- snapshot). organization_id IS NULL = the global (non-org) calc. The column
-- set EXACTLY mirrors the MV-backed model (37 columns).
CREATE MATERIALIZED VIEW IF NOT EXISTS fund_risk_latest_mv AS
SELECT DISTINCT ON (instrument_id)
       instrument_id, calc_date,
       return_1m, return_3m, return_1y, return_3y_ann, return_5y_ann,
       volatility_1y, volatility_garch, vol_model,
       max_drawdown_1y, max_drawdown_3y,
       sharpe_1y, sharpe_3y, sortino_1y, calmar_ratio_3y,
       alpha_1y, beta_1y, information_ratio_1y, tracking_error_1y,
       var_95_1m, cvar_95_1m, cvar_95_12m,
       cvar_99_evt, cvar_999_evt, evt_xi_shape,
       peer_sharpe_pctl, peer_sortino_pctl, peer_return_pctl, peer_drawdown_pctl,
       manager_score, downside_capture_1y, upside_capture_1y,
       equity_correlation_252d, peer_strategy_label, peer_count, elite_flag
FROM fund_risk_metrics
WHERE organization_id IS NULL
ORDER BY instrument_id, calc_date DESC;
```

(The column list now has exactly 37 names; all four added source columns already exist in `fund_risk_metrics` per `E:/investintell-datalake-workers/schemas/risk_metrics.sql` lines 44-45, 72-73, so NO base-table or worker change is needed. The `CREATE UNIQUE INDEX ... fund_risk_latest_mv_pk` at lines 78-79 is unchanged. The running MV on Tiger must be DROPped + re-created from this DDL plus its UNIQUE index because a MATERIALIZED VIEW cannot `ALTER ... ADD COLUMN`; record this in the commit body.)

- [ ] **Step 4: Run the tests, expect PASS.**
```
cd backend && python -m pytest tests/test_funds_risk_schema.py tests/test_models.py -v
```
Expected: all of `test_funds_risk_schema.py` pass; `test_models.py` (including the new `test_fund_risk_latest_surfaces_orphaned_worker_columns` and the existing `test_fund_risk_latest_pk_and_metric_lockstep`, which still holds because the new columns are nullable so the metric-lockstep loop at lines 503-504 stays green) pass.

- [ ] **Step 5: Commit.**
```
cd backend && git add app/models/fund.py app/schemas/funds.py db/ddl/2026-06-13_dynamic_catalog.sql tests/test_funds_risk_schema.py tests/test_models.py
git commit -m "feat(funds): surface orphaned EVT/GARCH worker columns in FundRiskOut

The worker already computes volatility_garch / vol_model / cvar_999_evt /
evt_xi_shape into fund_risk_metrics, but the fund_risk_latest_mv view, the
FundRiskLatest ORM and FundRiskOut never selected them, so they were
computed-but-unreachable. Add the four columns end-to-end (MV 33->37 cols,
ORM, schema). Production MV must be DROPped + re-created from the DDL (ADD
COLUMN is unsupported on a MV); the UNIQUE index fund_risk_latest_mv_pk must
be recreated and the worker's CONCURRENTLY refresh will repopulate them.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2F-2: Pure mandate→δ ladder (clamp [0.5, 10]) + optional `mandate` on OptimizeRequest feeding equilibrium() and solve_bl_utility()

Port the legacy ladder from `E:/investintell-allocation/backend/quant_engine/mandate_risk_aversion.py` (canonical map lines 35-44, `RA_MIN`/`RA_MAX` lines 47-48, normaliser line 51, `resolve_risk_aversion` lines 84-135) into a NEW pure module `app/optimizer/mandate.py` (the optimizer package is where δ / expected-returns logic lives — Gate G5). Then add an optional `mandate` field to `OptimizeRequest` and resolve the effective δ once, feeding it to `bl.equilibrium(...)` and `bl.solve_bl_utility(...)`.

The legacy depends on `structlog` and logs warnings/aliases; the Light optimizer is pure and log-free. The port therefore drops all logging and the `_MANDATE_ALIASES` rewrite (both `aggressive` and `growth` map directly to 1.5, so the numeric result is unchanged — see open_questions). The result is a pure function `resolve_delta(delta, mandate) -> float` that never returns NaN/Inf; an unknown mandate falls back to the default per the legacy contract (this is NOT a fail-loud case — the legacy explicitly falls back rather than raising).

**Files:**
- Create `backend/app/optimizer/mandate.py` — the ported pure ladder.
- Modify `backend/app/schemas/builder.py` — define the `Mandate` Literal after the `Objective` definition (lines 72-74), and add `mandate: Mandate | None = None` to `OptimizeRequest` after `bl: BLParamsIn = BLParamsIn()` (line 146).
- Modify `backend/app/services/portfolio_builder.py` — import `resolve_delta`; resolve δ once from `payload.bl.delta` + `payload.mandate` and pass it to `bl.equilibrium` (line 265) and `bl.solve_bl_utility` (line 284).
- Create `backend/tests/test_optimizer_mandate.py` — pure ladder + clamp tests.
- Modify `backend/tests/test_builder_schema.py` — `mandate` field tests (append; the file's `_assets()` helper at lines 15-17 and `OptimizeRequest` import at line 9 already exist).

- [ ] **Step 1: Write the failing tests.**

Create `backend/tests/test_optimizer_mandate.py`:

```python
# backend/tests/test_optimizer_mandate.py
"""T2F-2: mandate -> risk-aversion (delta) ladder, ported from the legacy
quant_engine.mandate_risk_aversion. Pure, no I/O, no logging. An explicit
delta override wins (clamped to [DELTA_MIN, DELTA_MAX]); a mandate label maps
through the ladder; unknown/absent -> DEFAULT_DELTA (== bl.DEFAULT_DELTA)."""

import math

import pytest

from app.optimizer import black_litterman as bl
from app.optimizer.mandate import (
    DELTA_MAX,
    DELTA_MIN,
    MANDATE_DELTA,
    resolve_delta,
)


def test_default_matches_bl_default_delta() -> None:
    # The fallback must be the same 2.5 the optimizer already uses.
    assert MANDATE_DELTA["moderate"] == bl.DEFAULT_DELTA


@pytest.mark.parametrize(
    ("mandate", "expected"),
    [
        ("conservative", 4.5),
        ("Conservative", 4.5),  # case-insensitive
        ("moderate", 2.5),
        ("balanced", 2.5),
        ("aggressive", 1.5),
        ("growth", 1.5),
        ("moderate-conservative", 3.5),  # dash normalised to underscore
        ("moderate aggressive", 2.0),    # whitespace normalised
    ],
)
def test_mandate_maps_to_ladder(mandate: str, expected: float) -> None:
    assert resolve_delta(None, mandate) == expected


def test_unknown_mandate_falls_back_to_default() -> None:
    assert resolve_delta(None, "wildly_unknown") == bl.DEFAULT_DELTA


def test_no_inputs_uses_default() -> None:
    assert resolve_delta(None, None) == bl.DEFAULT_DELTA


def test_explicit_delta_overrides_mandate() -> None:
    # Override beats the mandate ladder entirely.
    assert resolve_delta(3.0, "aggressive") == 3.0


def test_explicit_delta_is_clamped_into_range() -> None:
    assert resolve_delta(100.0, None) == DELTA_MAX
    assert resolve_delta(0.0001, None) == DELTA_MIN
    assert DELTA_MIN == 0.5
    assert DELTA_MAX == 10.0


def test_non_finite_override_discarded_then_mandate() -> None:
    # NaN/Inf override is dropped; mandate is used instead.
    assert resolve_delta(math.nan, "conservative") == 4.5
    assert resolve_delta(math.inf, None) == bl.DEFAULT_DELTA


def test_non_positive_override_discarded_then_default() -> None:
    assert resolve_delta(-1.0, None) == bl.DEFAULT_DELTA
```

Append to `backend/tests/test_builder_schema.py`:

```python
def test_optimize_request_mandate_defaults_to_none() -> None:
    req = OptimizeRequest(assets=_assets())
    assert req.mandate is None


def test_optimize_request_accepts_known_mandate() -> None:
    req = OptimizeRequest(assets=_assets(), mandate="aggressive")
    assert req.mandate == "aggressive"


def test_optimize_request_rejects_unknown_mandate() -> None:
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        OptimizeRequest(assets=_assets(), mandate="not_a_mandate")
```

- [ ] **Step 2: Run the tests, expect FAIL.**
```
cd backend && python -m pytest tests/test_optimizer_mandate.py tests/test_builder_schema.py -v
```
Expected failure: `ModuleNotFoundError: No module named 'app.optimizer.mandate'` collapses the whole `test_optimizer_mandate.py` module at import; the three new builder-schema tests fail because `OptimizeRequest` has no `mandate` field (`test_optimize_request_mandate_defaults_to_none` fails on the `req.mandate` attribute, and the validation/accept tests fail because the unknown keyword is ignored / no field exists).

- [ ] **Step 3: Create the pure ladder module and wire the schema + service.**

Create `backend/app/optimizer/mandate.py`:

```python
"""Mandate -> risk-aversion (delta) ladder for the Black-Litterman layer.

Ported from the legacy quant_engine.mandate_risk_aversion (Grinold-Kahn /
CFA L3 arithmetic ladder). Pure: no I/O, no logging. This is the only place
an investor mandate label is turned into the delta the optimizer consumes; it
keeps Conservative / Moderate / Aggressive clients off the same equilibrium.

    Conservative  -> 4.5   (variance heavily penalised)
    Moderate      -> 2.5   (== bl.DEFAULT_DELTA, the fallback)
    Aggressive    -> 1.5   (return-tilted)

Resolution: an explicit ``delta`` override wins and is clamped to
[DELTA_MIN, DELTA_MAX]; a non-finite/non-positive override is discarded and we
fall through to the mandate, then to DEFAULT_DELTA. A mandate label is
normalised (whitespace/dashes -> underscore, lowercased) and looked up; an
unknown label falls back to DEFAULT_DELTA. The legacy 'aggressive' -> 'growth'
deprecation alias is dropped (both rungs already map to 1.5, so the numeric
result is identical and the Light optimizer is log-free by contract).
"""

from __future__ import annotations

import math
import re

from app.optimizer.black_litterman import DEFAULT_DELTA

# Arithmetic ladder (lowercase, underscore-separated keys).
MANDATE_DELTA: dict[str, float] = {
    "conservative": 4.5,
    "defensive": 4.5,
    "moderate_conservative": 3.5,
    "moderate": 2.5,
    "balanced": 2.5,
    "moderate_aggressive": 2.0,
    "aggressive": 1.5,
    "growth": 1.5,
}

DELTA_MIN = 0.5    # Grinold-Kahn lower bound for institutional lambda
DELTA_MAX = 10.0   # upper bound — beyond this optimizer scaling fails

_KEY_NORMALISER = re.compile(r"[\s\-]+")


def normalise_mandate(mandate: str) -> str:
    """Collapse runs of whitespace/dashes into one underscore; lowercase."""
    return _KEY_NORMALISER.sub("_", mandate.strip().lower())


def resolve_delta(delta: float | None, mandate: str | None) -> float:
    """Resolve the effective delta from an override, a mandate, or the default.

    Priority: finite positive ``delta`` (clamped to [DELTA_MIN, DELTA_MAX]) >
    ``mandate`` ladder lookup > DEFAULT_DELTA. Never returns NaN/Inf.
    """
    if delta is not None and math.isfinite(delta) and delta > 0:
        return float(max(DELTA_MIN, min(DELTA_MAX, delta)))
    if mandate:
        key = normalise_mandate(mandate)
        if key in MANDATE_DELTA:
            return MANDATE_DELTA[key]
    return float(DEFAULT_DELTA)
```

In `backend/app/schemas/builder.py`, add the `Mandate` Literal immediately after the `Objective` definition (line 74) — `Literal` is already imported (line 10):

```python
Mandate = Literal[
    "conservative",
    "defensive",
    "moderate_conservative",
    "moderate",
    "balanced",
    "moderate_aggressive",
    "aggressive",
    "growth",
]
```

and add the field on `OptimizeRequest` immediately after `bl: BLParamsIn = BLParamsIn()` (line 146):

```python
    bl: BLParamsIn = BLParamsIn()
    # Optional investor mandate; resolves the BL risk-aversion (delta) ladder.
    # An explicit bl.delta override still wins (see app.optimizer.mandate).
    mandate: Mandate | None = None
```

In `backend/app/services/portfolio_builder.py`, add the resolver import right after the existing `from app.optimizer import black_litterman as bl` (line 37):

```python
from app.optimizer.mandate import resolve_delta
```

Then in `run_optimize`, resolve δ once and use it in both BL call sites. The current block (lines 255-265) reads:

```python
    cap = payload.constraints.cap
    min_weight = payload.constraints.min_weight
    has_views = bool(payload.views)
    needs_bl = has_views or payload.objective == "bl_utility"

    mu_equilibrium: np.ndarray | None = None
    mu_posterior: np.ndarray | None = None
    w_mkt: np.ndarray | None = None
    if needs_bl:
        w_mkt = await _market_weights_for(session, assets, labels)
        mu_equilibrium = bl.equilibrium(sigma, w_mkt, delta=payload.bl.delta)
```

Change it to resolve δ once and pass it to `equilibrium`:

```python
    cap = payload.constraints.cap
    min_weight = payload.constraints.min_weight
    has_views = bool(payload.views)
    needs_bl = has_views or payload.objective == "bl_utility"
    # Effective risk-aversion: explicit bl.delta override beats the mandate
    # ladder; both feed equilibrium (pi = delta*Sigma*w_mkt) and bl_utility.
    delta = resolve_delta(payload.bl.delta, payload.mandate)

    mu_equilibrium: np.ndarray | None = None
    mu_posterior: np.ndarray | None = None
    w_mkt: np.ndarray | None = None
    if needs_bl:
        w_mkt = await _market_weights_for(session, assets, labels)
        mu_equilibrium = bl.equilibrium(sigma, w_mkt, delta=delta)
```

And in the `bl_utility` branch (line 284), change `delta=payload.bl.delta` to `delta=delta`:

```python
            weights, status = bl.solve_bl_utility(
                mu_for_utility, sigma, delta=delta, cap=cap, min_weight=min_weight
            )
```

Precedence note (do not over-engineer this task): `BLParamsIn.delta` defaults to a present, finite, positive `2.5` (`backend/app/schemas/builder.py:68`), so the service always passes a concrete override and `resolve_delta` returns the (clamped) `bl.delta`. The pure `resolve_delta` contract (override-wins, clamp `[0.5, 10]`, mandate fallback) is fully unit-tested in `test_optimizer_mandate.py`, and all existing optimizer tests pass `delta=2.5` so nothing regresses. The unresolved product question — making a mandate take effect when the caller did NOT opt into a custom delta (which needs distinguishing "delta omitted" from "delta == 2.5", a schema change) — is recorded in open_questions and is explicitly OUT OF SCOPE here.

- [ ] **Step 4: Run the tests, expect PASS.**
```
cd backend && python -m pytest tests/test_optimizer_mandate.py tests/test_builder_schema.py -v
```
Expected: all mandate ladder/clamp tests pass; the three new builder-schema tests pass (`mandate` defaults to None, accepts `"aggressive"`, rejects `"not_a_mandate"` via the `Mandate` Literal → `ValidationError`). Then run the existing optimizer suite to confirm no regression:
```
cd backend && python -m pytest tests/test_optimizer_black_litterman.py -v
```
Expected: still green (the `equilibrium` / `solve_bl_utility` signatures are unchanged; the service passes the resolved δ, which equals 2.5 in every existing test path).

- [ ] **Step 5: Commit.**
```
cd backend && git add app/optimizer/mandate.py app/schemas/builder.py app/services/portfolio_builder.py tests/test_optimizer_mandate.py tests/test_builder_schema.py
git commit -m "feat(optimizer): mandate->delta ladder feeding BL equilibrium + utility

Port the Grinold-Kahn risk-aversion ladder from the legacy
quant_engine.mandate_risk_aversion into a pure app/optimizer/mandate.py
(Conservative 4.5 / Moderate 2.5 / Aggressive 1.5, clamp [0.5, 10]; drops the
legacy structlog logging and the aggressive->growth alias, both unchanged
numerically). Add an optional 'mandate' field on OptimizeRequest; the builder
resolves the effective delta once (explicit bl.delta override wins) and feeds
it to equilibrium() and solve_bl_utility() so mandates stop collapsing onto
the same equilibrium.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2F-3: He–Litterman 3σ view-consistency warning in DiagnosticsOut

Port the legacy He–Litterman (1999) consistency check from `E:/investintell-allocation/backend/quant_engine/black_litterman_service.py` (lines 459-484): a view `Q` more than 3σ from its prior-implied value `P·π` is the "views fighting the equilibrium" alarm. σ is the predictive dispersion: `view_cov = P·(τΣ)·Pᵀ + Ω`, `view_sigma = sqrt(diag(view_cov))`, flag where `|Q − P·π| > 3·view_sigma` (legacy lines 467-472).

The legacy logs via structlog (lines 474-482). The Light optimizer is pure and the app surfaces this through `DiagnosticsOut`, so the port is a **pure function** in `app/optimizer/black_litterman.py` returning a structured dict, and `run_optimize` attaches it to a new optional `DiagnosticsOut.view_consistency` field. ~15 LOC of math, reusing the P / Q / Ω / π the BL path already builds (`portfolio_builder.run_optimize` lines 266-275).

**Files:**
- Modify `backend/app/optimizer/black_litterman.py` — add the `_HE_LITTERMAN_SIGMA` constant and `view_consistency_he_litterman(...)` after `posterior` (which ends at line 210) and before `historical_mean_ann` (line 213).
- Modify `backend/app/schemas/builder.py` — add a `ViewConsistencyOut` model and a `view_consistency: ViewConsistencyOut | None = None` field on `DiagnosticsOut` (currently lines 188-193).
- Modify `backend/app/services/portfolio_builder.py` — add `ViewConsistencyOut` to the schema import block (lines 40-52); initialise a `view_consistency` local near `mu_posterior` (line 261); compute the check in the views branch (after the `bl.posterior(...)` call, line 275); pass it into the `DiagnosticsOut(...)` constructor (lines 329-338).
- Modify `backend/tests/test_optimizer_black_litterman.py` — append the pure-function tests (the `_fixture_sigma` helper at line 19 and `_W_MKT` at line 31 already exist).
- Modify `backend/tests/test_builder_schema.py` — append the `DiagnosticsOut.view_consistency` default test.

- [ ] **Step 1: Write the failing tests.** Append to `backend/tests/test_optimizer_black_litterman.py`:

```python
# ── He-Litterman 3-sigma view-consistency warning (T2F-3) ─────────────────────


def test_view_consistency_flags_view_fighting_prior() -> None:
    """A Q far above the prior-implied P*pi (>3 predictive sigma) is flagged."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    # Absolute view on asset 2, far above its equilibrium return, very confident
    # (small Omega) -> large z-score.
    p, q = bl.build_view_matrices(
        [bl.AbsoluteView(asset=2, q=float(pi[2]) + 1.0, confidence=0.99)], 3
    )
    omega = bl.omega_idzorek(p, sigma, [0.99])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is True
    assert result["n_flagged"] == 1
    assert result["max_z"] > 3.0
    assert result["threshold_sigma"] == 3.0


def test_view_consistency_passes_view_aligned_with_prior() -> None:
    """A Q equal to the prior-implied value is consistent (z=0)."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices(
        [bl.AbsoluteView(asset=0, q=float(pi[0]), confidence=0.5)], 3
    )
    omega = bl.omega_idzorek(p, sigma, [0.5])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is False
    assert result["n_flagged"] == 0
    assert result["max_z"] == pytest.approx(0.0, abs=1e-9)


def test_view_consistency_relative_view_uses_predictive_dispersion() -> None:
    """A modest relative view within ~3 sigma is NOT flagged."""
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p, q = bl.build_view_matrices(
        [bl.RelativeView(long=0, short=1, q=float(pi[0] - pi[1]) + 0.01, confidence=0.5)],
        3,
    )
    omega = bl.omega_idzorek(p, sigma, [0.5])
    result = bl.view_consistency_he_litterman(p, q, pi, omega, sigma, tau=bl.DEFAULT_TAU)
    assert result["inconsistent"] is False
    assert 0.0 <= result["max_z"] <= 3.0
```

Append to `backend/tests/test_builder_schema.py`:

```python
def test_diagnostics_out_view_consistency_defaults_to_none() -> None:
    from app.schemas.builder import DiagnosticsOut

    diag = DiagnosticsOut(n_obs=10, status="optimal")
    assert diag.view_consistency is None
```

- [ ] **Step 2: Run the tests, expect FAIL.**
```
cd backend && python -m pytest tests/test_optimizer_black_litterman.py -k view_consistency tests/test_builder_schema.py::test_diagnostics_out_view_consistency_defaults_to_none -v
```
Expected failure: `AttributeError: module 'app.optimizer.black_litterman' has no attribute 'view_consistency_he_litterman'` for the three optimizer tests; `test_diagnostics_out_view_consistency_defaults_to_none` fails on `diag.view_consistency` (the field does not exist on `DiagnosticsOut`).

- [ ] **Step 3: Add the pure check + the schema field + the service wiring.**

In `backend/app/optimizer/black_litterman.py`, add the constant and function after `posterior` (after line 210, before `historical_mean_ann` at line 213). `np` and `DEFAULT_TAU` are already in scope (lines 20, 32). It reuses the SAME predictive-dispersion math the legacy uses (`view_cov = P·τΣ·Pᵀ + Ω`):

```python
# He-Litterman (1999) consistency threshold: a view Q more than this many
# predictive sigmas from its prior-implied value P*pi is "fighting the prior".
_HE_LITTERMAN_SIGMA = 3.0


def view_consistency_he_litterman(
    p: np.ndarray,
    q: np.ndarray,
    pi: np.ndarray,
    omega: np.ndarray,
    sigma_ann: np.ndarray,
    tau: float = DEFAULT_TAU,
) -> dict[str, object]:
    """He-Litterman (1999) view-vs-prior consistency check.

    For each view, the prior-implied value is P*pi and the predictive
    dispersion of (Q - P*pi) is sqrt(diag(P*(tau*Sigma)*P' + Omega)). A view
    whose |Q - P*pi| exceeds ``_HE_LITTERMAN_SIGMA`` times that dispersion is
    the textbook "views fighting the equilibrium" red flag. Returns a
    structured summary (never raises on a degenerate sigma -> z=0 there).
    """
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float).ravel()
    pi = np.asarray(pi, dtype=float).ravel()
    omega = np.asarray(omega, dtype=float)
    sigma_ann = np.asarray(sigma_ann, dtype=float)
    prior_view = p @ pi                                   # (K,)
    view_cov = p @ (tau * sigma_ann) @ p.T + omega        # (K, K) predictive cov
    view_sigma = np.sqrt(np.maximum(np.diag(view_cov), 0.0))
    residual = np.abs(q - prior_view)
    z = residual / np.where(view_sigma > 0, view_sigma, 1.0)
    inconsistent = z > _HE_LITTERMAN_SIGMA
    return {
        "inconsistent": bool(inconsistent.any()),
        "n_flagged": int(inconsistent.sum()),
        "max_z": round(float(z.max()) if z.size else 0.0, 4),
        "threshold_sigma": _HE_LITTERMAN_SIGMA,
    }
```

In `backend/app/schemas/builder.py`, add a `ViewConsistencyOut` model and extend `DiagnosticsOut` (current lines 188-193):

```python
class ViewConsistencyOut(BaseModel):
    """He-Litterman 3-sigma alarm: are any views fighting the equilibrium?"""

    inconsistent: bool
    n_flagged: int
    max_z: float
    threshold_sigma: float


class DiagnosticsOut(BaseModel):
    n_obs: int
    status: str
    # Present only on the BL path (views and/or bl_utility), in asset order.
    mu_equilibrium: list[float] | None = None
    mu_posterior: list[float] | None = None
    # He-Litterman view-vs-prior consistency — present only when views are given.
    view_consistency: ViewConsistencyOut | None = None
```

In `backend/app/services/portfolio_builder.py`, add `ViewConsistencyOut` to the schema import block (between lines 40-52, e.g. after `ViewIn,`):

```python
    ViewConsistencyOut,
```

Initialise the local right after `mu_posterior: np.ndarray | None = None` (line 261):

```python
    mu_posterior: np.ndarray | None = None
    view_consistency: ViewConsistencyOut | None = None
```

In the views branch, after the `bl.posterior(...)` call succeeds (inside the existing `try`, after line 275 and before the `except ValueError` at line 276), compute the check from the SAME matrices:

```python
                mu_posterior, _sigma_bl = bl.posterior(
                    sigma, mu_equilibrium, p, q, omega, tau=payload.bl.tau
                )
                vc = bl.view_consistency_he_litterman(
                    p, q, mu_equilibrium, omega, sigma, tau=payload.bl.tau
                )
                view_consistency = ViewConsistencyOut(
                    inconsistent=bool(vc["inconsistent"]),
                    n_flagged=int(vc["n_flagged"]),
                    max_z=float(vc["max_z"]),
                    threshold_sigma=float(vc["threshold_sigma"]),
                )
```

Finally, pass it into the `DiagnosticsOut(...)` constructor (lines 329-338):

```python
        diagnostics=DiagnosticsOut(
            n_obs=len(frame),
            status=status,
            mu_equilibrium=(
                [float(x) for x in mu_equilibrium] if mu_equilibrium is not None else None
            ),
            mu_posterior=(
                [float(x) for x in mu_posterior] if mu_posterior is not None else None
            ),
            view_consistency=view_consistency,
        ),
```

- [ ] **Step 4: Run the tests, expect PASS.**
```
cd backend && python -m pytest tests/test_optimizer_black_litterman.py tests/test_builder_schema.py -v
```
Expected: the three `view_consistency` math tests pass (flag on a far/confident view with z≈22.3 > 3; z≈0 on an aligned view; z≈0.21 within 3σ on a modest relative view) and `test_diagnostics_out_view_consistency_defaults_to_none` passes; the existing BL gate tests (lines 48-174) stay green (the new function is additive and the service only sets the field on the views path). Then run the builder route suite to confirm no regression:
```
cd backend && python -m pytest tests/test_builder_route.py -v
```
Expected: green (`DiagnosticsOut.view_consistency` is optional and defaults to None on the no-views paths the existing tests exercise).

- [ ] **Step 5: Commit.**
```
cd backend && git add app/optimizer/black_litterman.py app/schemas/builder.py app/services/portfolio_builder.py tests/test_optimizer_black_litterman.py tests/test_builder_schema.py
git commit -m "feat(optimizer): He-Litterman 3-sigma view-consistency warning in diagnostics

Port the He-Litterman (1999) consistency check from the legacy
black_litterman_service: a view Q more than 3 predictive sigmas from its
prior-implied P*pi is the 'views fighting the equilibrium' red flag. Unlike
the legacy (structlog), the Light surfaces it as structured data —
DiagnosticsOut.view_consistency — computed from the P/Q/Omega/pi the BL path
already builds. Pure function view_consistency_he_litterman; ~15 LOC of math.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Tier 2 — Drawdown episode decomposition + block-bootstrap Monte Carlo projections

This cluster ports two techniques from the legacy `quant_engine` into the LIGHT app:

1. **Drawdown episode decomposition** (rank 20) — a pure function `drawdown_episodes(prices)` next to `max_drawdown` in `backend/app/analytics/risk.py`, returning the top-N worst drawdown episodes (peak/trough/recovery dates, durations, open-drawdown handling), ported from `E:/investintell-allocation/backend/quant_engine/drawdown_service.py` (`extract_drawdown_periods`, lines 53-107). It works on a date-indexed pandas price/NAV `Series` (the LIGHT convention used by `max_drawdown`, `backend/app/analytics/risk.py:117-142`), NOT on the legacy `(dates: list[date], dd_series: np.ndarray)` split signature.

2. **Block-bootstrap Monte Carlo projections** (rank 21) — a pure analytics module `backend/app/analytics/monte_carlo.py` (numpy, `default_rng` only) ported from `E:/investintell-allocation/backend/quant_engine/monte_carlo_service.py`, plus the standard LIGHT service triple: a Pydantic schema (`backend/app/schemas/monte_carlo.py`), a pure `assemble_monte_carlo(...)` + async `run_monte_carlo(...)` orchestrator (`backend/app/services/monte_carlo.py`), and a thin route `POST /monte-carlo/projection` (`backend/app/api/routes/monte_carlo.py`) registered in `backend/app/main.py`.

**Conventions honored** (verified against the real source):
- **Scale contract**: all fractional quantities (drawdown depth, returns, percentiles) are decimal fractions — the legacy already emits fractions; Sharpe is unitless.
- **Fail-loud**: pure analytics raise `ValueError` on insufficient/NaN data. The legacy MC returned a `degraded=True` object instead for its two hard guards (T<42 and T<min-horizon ratio); this plan REPLACES that with `ValueError` for the analytics layer's hard guards (the LIGHT pattern), keeping `degraded`/`degraded_reason` ONLY for the SOFT Sharpe zero-variance-mass case (a property of valid data, not a missing input). The legacy `structlog` warning is dropped (the `ValueError` message carries the diagnostic).
- **G5 (μ-free)**: no objective consumes a sample mean. The Monte Carlo "return" statistic is a *bootstrap projection of realized compounded return*, not an expected-return input to any optimizer — this cluster touches no optimizer code, so G5 is not engaged.
- **Service/route pattern** (verified against the CANONICAL `app/services/statistics.py` + `app/api/routes/statistics.py` + `tests/test_statistics_routes.py`): the SERVICE owns the DB reads. It imports `ensure_eod_or_http_error` from `app.api._shared` and the read helpers from `app.services._series` with leading-underscore aliases (`select_date_bounds as _select_date_bounds`, `select_adj_close_rows as _select_adj_close_rows`), exactly as `statistics.py:88-90` does. The async `run_*` orchestrator calls them; the route stays thin (validate -> run -> map `StockAnalysisError` to 422). Route tests monkeypatch the helpers on the SERVICE module and `ensure_eod_data` on `app.api._shared` (the proven boundary from `test_statistics_routes.py:89-90`).
- **RNG**: `numpy.random.default_rng(seed)` is the only RNG (the legacy already uses it).
- **Tests** live FLAT in `backend/tests/` (verified: `test_analytics_risk.py`, `test_portfolio_route.py`, `test_statistics_routes.py`), run from `backend/` with `python -m pytest`.

`DrawdownEpisode` is a NEW dataclass (the legacy name is `DrawdownPeriodResult`; LIGHT's `risk.py` already has a `DrawdownResult` for `max_drawdown`, so the episode type gets a distinct name). The MC dataclass is `MonteCarloAnalytics` (renamed from the legacy `MonteCarloResult`) to avoid colliding with the schema's `MonteCarloResponse`.

Order: **T2G-1** (drawdown episodes analytics) → **T2G-2** (Monte Carlo analytics) → **T2G-3** (schema) → **T2G-4** (service) → **T2G-5** (route + registration). T2G-3/4/5 depend on T2G-2; T2G-1 is independent.

---

### Task T2G-1: `drawdown_episodes(prices)` pure analytics function

Port the top-N drawdown-episode decomposition from the legacy `extract_drawdown_periods` (`E:/investintell-allocation/backend/quant_engine/drawdown_service.py:53-107`) into the LIGHT `risk.py`, adapted to operate on a single date-indexed pandas price `Series` (the same input as the existing `max_drawdown`, `backend/app/analytics/risk.py:117-142`). Episode `depth` is a NEGATIVE decimal fraction; `peak`/`trough`/`recovery` are dates; durations are calendar days; an open (unrecovered) episode has `recovery_date=None` and `recovery_days=None`. Episodes are ranked deepest-first and capped at `top_n`.

**IMPORTANT — peak resolution (do not regress this):** the running-max bar at recovery has `dd == 0`, which would overwrite a single shared "last peak" cursor. The legacy avoids this by capturing the peak index **at the onset of the drawdown** in a *separate* variable (`start_idx` at `drawdown_service.py:78`), distinct from the rolling `last_peak_idx`. This port keeps that separation as `peak_idx`. Using `last_peak_idx` directly in the recovery append would yield `peak_date == recovery_date` (a confirmed defect) — it MUST be a separate onset-captured index.

**Files:**
- Modify: `backend/app/analytics/risk.py` (add `DrawdownEpisode` dataclass immediately AFTER the existing `DrawdownResult` dataclass which ends at line 33; add `drawdown_episodes` function immediately AFTER `max_drawdown` which ends at line 142)
- Modify: `backend/app/analytics/__init__.py` (add `DrawdownEpisode`, `drawdown_episodes` to the `from app.analytics.risk import (...)` block at lines 30-40 and to `__all__` at lines 47-77)
- Test: `backend/tests/test_analytics_risk_episodes.py` (new)

- [ ] **Step 1: Write the failing test.**
Create `backend/tests/test_analytics_risk_episodes.py`:
```python
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
```

- [ ] **Step 2: Run it, expect FAIL.**
Command: `cd backend && python -m pytest tests/test_analytics_risk_episodes.py -v`
Expected failure: `ImportError: cannot import name 'DrawdownEpisode' from 'app.analytics'` (and `drawdown_episodes`) — the symbols do not exist yet.

- [ ] **Step 3: Write the minimal implementation.**
In `backend/app/analytics/risk.py`, add the `DrawdownEpisode` dataclass immediately AFTER the existing `DrawdownResult` dataclass (which ends at line 33):
```python
@dataclass(frozen=True)
class DrawdownEpisode:
    """One drawdown episode of a price/NAV series.

    ``depth`` is a NEGATIVE decimal fraction (e.g. -0.20 = a 20% peak-to-trough
    loss), never 0-100. ``peak_date`` is the running-max date at the ONSET of
    the drawdown; ``trough_date`` is the deepest point; ``recovery_date`` is the
    first date the series regains its prior peak (``None`` for an OPEN,
    unrecovered episode). Durations are CALENDAR days: ``duration_days`` spans
    peak -> recovery (peak -> last date for an open episode) and
    ``recovery_days`` spans trough -> recovery (``None`` while open).
    """

    depth: float
    peak_date: date
    trough_date: date
    recovery_date: date | None
    duration_days: int
    recovery_days: int | None
```
Then add the `drawdown_episodes` function immediately AFTER `max_drawdown` (which ends at line 142):
```python
def drawdown_episodes(prices: pd.Series, top_n: int = 5) -> list["DrawdownEpisode"]:
    """Top-``top_n`` worst drawdown episodes of a price/NAV series, deepest first.

    An episode runs from the most recent peak (drawdown == 0) preceding a loss,
    through the deepest trough, to the first date the series regains that peak.
    The final episode is OPEN (``recovery_date=None``) when the series never
    recovers by the last date. ``depth`` values are NEGATIVE decimal fractions
    (never 0-100); durations are calendar days. For a monotonically rising
    series the result is an empty list.

    Ported from the legacy ``extract_drawdown_periods``: the onset peak is
    captured in a SEPARATE index (``peak_idx``) at drawdown onset, distinct
    from the rolling ``last_peak_idx`` cursor, because the recovery bar itself
    has ``drawdown == 0`` and would otherwise overwrite the cursor.

    Raises:
        ValueError: if ``top_n`` < 1, fewer than 2 prices are supplied, or the
            input contains NaN/infinite values.
    """
    if top_n < 1:
        raise ValueError(f"top_n must be >= 1, got {top_n}")
    if len(prices) < 2:
        raise ValueError(
            f"drawdown_episodes requires at least 2 prices, got {len(prices)}"
        )
    reject_nan(prices, "drawdown_episodes")

    values = prices.to_numpy(dtype=float)
    running_max = np.maximum.accumulate(values)
    dd = values / running_max - 1.0  # <= 0; 0 at every new running high

    labels = list(prices.index)
    episodes: list[DrawdownEpisode] = []
    in_dd = False
    last_peak_idx = 0
    peak_idx = 0
    trough_idx = 0
    trough_val = 0.0

    for i, d in enumerate(dd):
        if d == 0:
            last_peak_idx = i

        if d < 0:
            if not in_dd:
                in_dd = True
                peak_idx = last_peak_idx  # onset peak — captured ONCE per episode
                trough_idx = i
                trough_val = d
            elif d < trough_val:
                trough_idx = i
                trough_val = d
        elif in_dd:
            # Recovery: d == 0 means a new running high was reached at index i.
            episodes.append(
                DrawdownEpisode(
                    depth=float(trough_val),
                    peak_date=to_date(labels[peak_idx]),
                    trough_date=to_date(labels[trough_idx]),
                    recovery_date=to_date(labels[i]),
                    duration_days=(
                        to_date(labels[i]) - to_date(labels[peak_idx])
                    ).days,
                    recovery_days=(
                        to_date(labels[i]) - to_date(labels[trough_idx])
                    ).days,
                )
            )
            in_dd = False

    if in_dd:
        episodes.append(
            DrawdownEpisode(
                depth=float(trough_val),
                peak_date=to_date(labels[peak_idx]),
                trough_date=to_date(labels[trough_idx]),
                recovery_date=None,
                duration_days=(
                    to_date(labels[-1]) - to_date(labels[peak_idx])
                ).days,
                recovery_days=None,
            )
        )

    episodes.sort(key=lambda e: e.depth)
    return episodes[:top_n]
```
(`np`, `pd`, `date`, `reject_nan`, `to_date` are already imported at the top of `risk.py` — `np`/`pd` at lines 14-15, `date` at line 12, `reject_nan`/`to_date` at line 17. Depth is left UNROUNDED — the legacy rounds to 6 dp, but the LIGHT `max_drawdown` returns the raw float and the open-drawdown test compares `80/120 - 1` under `pytest.approx`, so rounding is intentionally omitted here.)

Then in `backend/app/analytics/__init__.py`, extend the `from app.analytics.risk import (...)` block (lines 30-40) so it reads:
```python
from app.analytics.risk import (
    BestWorst,
    DrawdownEpisode,
    DrawdownResult,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    drawdown_episodes,
    historical_cvar,
    historical_var,
    max_drawdown,
)
```
and insert two entries into `__all__` (lines 47-77), keeping it sorted: add `"DrawdownEpisode",` immediately after `"DEFAULT_INITIAL_NAV",` (line 49), and `"drawdown_episodes",` immediately after `"diversification_ratio",` (line 60).

- [ ] **Step 4: Run tests, expect PASS.**
Command: `cd backend && python -m pytest tests/test_analytics_risk_episodes.py -v`
Expected: all 7 tests pass. Also run `cd backend && python -m pytest tests/test_analytics_risk.py -v` to confirm the existing risk tests still pass (no regression in `risk.py`).

- [ ] **Step 5: Commit.**
```
cd backend
git add app/analytics/risk.py app/analytics/__init__.py tests/test_analytics_risk_episodes.py
git commit -m "feat(analytics): drawdown_episodes top-N episode decomposition

Port extract_drawdown_periods from legacy drawdown_service to a pure
pandas Series fn next to max_drawdown; deepest-first, open-drawdown
handling, onset-captured peak index, fail-loud on NaN/short input.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2G-2: Block-bootstrap Monte Carlo analytics module

Port the block-bootstrap simulation engine from `E:/investintell-allocation/backend/quant_engine/monte_carlo_service.py` into a new pure analytics module `backend/app/analytics/monte_carlo.py`. Keep the legacy math verbatim (21-day blocks, `default_rng`, `cumprod` NAV paths, percentile distribution, per-horizon confidence fans, historical percentile rank for `max_drawdown`/`return`, Sharpe zero-variance handling). KEY ADAPTATIONS vs. the legacy: (a) the two hard guards (`T<42` and `T<min-horizon ratio`, legacy lines 191-228) now **raise `ValueError`** instead of returning a `degraded` object; `degraded`/`degraded_reason` is reserved for the SOFT Sharpe zero-variance-mass case (legacy lines 283-311). (b) The dataclass is `MonteCarloAnalytics` (legacy `MonteCarloResult`) to avoid colliding with the schema's `MonteCarloResponse` in later tasks. (c) `confidence_bars` is a `tuple` (not a list) so the frozen dataclass is hashable/comparable for the deterministic-equality test. (d) `structlog` is dropped — the `ValueError` message carries the diagnostic.

**Files:**
- Create: `backend/app/analytics/monte_carlo.py`
- Test: `backend/tests/test_analytics_monte_carlo.py` (new)

- [ ] **Step 1: Write the failing test.**
Create `backend/tests/test_analytics_monte_carlo.py`:
```python
"""Tests for app.analytics.monte_carlo (block-bootstrap Monte Carlo)."""

import numpy as np
import pytest

from app.analytics.monte_carlo import (
    DEFAULT_HORIZONS,
    MonteCarloAnalytics,
    block_bootstrap_monte_carlo,
)


def _returns(n: int = 500, seed: int = 11) -> np.ndarray:
    """Deterministic daily returns with positive drift and ~1% daily vol."""
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, n)


def test_max_drawdown_distribution_is_deterministic_under_seed() -> None:
    r = _returns()
    a = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=42)
    b = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=42)
    assert a == b  # frozen dataclass equality => bit-for-bit reproducible


def test_max_drawdown_result_shape_and_ordering() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=1)
    assert isinstance(res, MonteCarloAnalytics)
    assert res.statistic == "max_drawdown"
    assert res.n_simulations == 2000
    assert not res.degraded
    # Percentile keys present and monotone (max drawdown is negative; deeper at low pct).
    keys = ["1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
    assert list(res.percentiles.keys()) == keys
    vals = [res.percentiles[k] for k in keys]
    assert vals == sorted(vals)  # ascending: 1st (worst, most negative) -> 99th
    # All drawdowns are <= 0 decimal fractions.
    assert res.percentiles["99th"] <= 0.0
    # Confidence fan covers DEFAULT_HORIZONS, each with a 1Y..10Y label.
    assert [b["horizon_days"] for b in res.confidence_bars] == DEFAULT_HORIZONS
    assert res.confidence_bars[0]["horizon"] == "1Y"


def test_historical_percentile_rank_present_for_drawdown() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=2000, statistic="max_drawdown", seed=3)
    assert res.historical_percentile_rank is not None
    assert 0.0 <= res.historical_percentile_rank <= 100.0
    assert res.historical_horizon_days == len(r)


def test_return_statistic_annualizes() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="return", seed=5)
    assert res.statistic == "return"
    # Median annualized return is finite and within a sane band for the inputs.
    assert -1.0 < res.median < 5.0
    assert res.historical_percentile_rank is not None


def test_sharpe_statistic_no_rank() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(r, n_simulations=1500, statistic="sharpe", seed=7)
    assert res.statistic == "sharpe"
    # Per the legacy contract, the percentile rank is omitted for sharpe.
    assert res.historical_percentile_rank is None
    assert not res.degraded


def test_flat_returns_sharpe_degrades() -> None:
    flat = np.zeros(300)
    res = block_bootstrap_monte_carlo(flat, n_simulations=500, statistic="sharpe", seed=9)
    assert res.degraded is True
    assert res.degraded_reason is not None
    assert "zero_variance" in res.degraded_reason


def test_unknown_statistic_raises() -> None:
    with pytest.raises(ValueError, match="Unknown statistic"):
        block_bootstrap_monte_carlo(_returns(), statistic="median", seed=1)


def test_too_short_history_raises() -> None:
    with pytest.raises(ValueError, match="insufficient_history"):
        block_bootstrap_monte_carlo(_returns(n=40), statistic="max_drawdown", seed=1)


def test_horizon_ratio_guard_raises() -> None:
    # 60 days of history but asking for a 10Y (2520-day) horizon: need T >= 252.
    with pytest.raises(ValueError, match="insufficient_history_for_horizon"):
        block_bootstrap_monte_carlo(_returns(n=60), statistic="max_drawdown", seed=1)


def test_custom_horizons_respected() -> None:
    r = _returns()
    res = block_bootstrap_monte_carlo(
        r, n_simulations=1000, statistic="max_drawdown", horizons=[252, 504], seed=2
    )
    assert [b["horizon_days"] for b in res.confidence_bars] == [252, 504]
```

- [ ] **Step 2: Run it, expect FAIL.**
Command: `cd backend && python -m pytest tests/test_analytics_monte_carlo.py -v`
Expected failure: `ModuleNotFoundError: No module named 'app.analytics.monte_carlo'` — the module does not exist yet.

- [ ] **Step 3: Write the minimal implementation.**
Create `backend/app/analytics/monte_carlo.py`:
```python
"""Block-bootstrap Monte Carlo projections over a daily-return array.

Pure numpy — no I/O, no DB, no FastAPI. Uses block bootstrap (21 trading-day
blocks) to preserve autocorrelation; does NOT assume a normal distribution.
Ported from the legacy quant_engine.monte_carlo_service.

Scale contract (project-wide): drawdown and annualized-return statistics are
decimal fractions (0.05 = 5%), never 0-100; Sharpe is unitless. The only RNG is
``numpy.random.default_rng``.

Fail-loud (LIGHT contract): the two hard input guards (too little history,
history too short for the requested horizon) raise ``ValueError`` — the route
maps these to HTTP 422. The ``degraded`` flag is reserved for the SOFT case of
a flat-NAV Sharpe collapse, which is a property of valid data rather than a
missing input.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

#: 1Y, 3Y, 5Y, 7Y, 10Y in trading days (the legacy default horizons).
DEFAULT_HORIZONS: list[int] = [252, 756, 1260, 1764, 2520]

_BLOCK_SIZE = 21
_MIN_HISTORY = 42
_ZERO_VARIANCE_MASS_THRESHOLD = 0.5
_PCTL_KEYS = ["1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"]
_PCTL_VALS = [1, 5, 10, 25, 50, 75, 90, 95, 99]


@dataclass(frozen=True)
class MonteCarloAnalytics:
    """Bootstrapped Monte Carlo simulation result for one statistic."""

    n_simulations: int
    statistic: str  # "max_drawdown" | "return" | "sharpe"
    percentiles: dict[str, float] = field(default_factory=dict)
    mean: float = 0.0
    median: float = 0.0
    std: float = 0.0
    historical_value: float = 0.0
    historical_horizon_days: int = 0
    historical_percentile_rank: float | None = None
    confidence_bars: tuple[dict[str, object], ...] = ()
    degraded: bool = False
    degraded_reason: str | None = None


def _block_bootstrap_paths(
    daily_returns: np.ndarray[Any, Any],
    n_simulations: int,
    horizon: int,
    rng: np.random.Generator,
) -> np.ndarray[Any, Any]:
    """(n_simulations, horizon) array of simulated daily returns via block bootstrap."""
    n = len(daily_returns)
    n_blocks = (horizon + _BLOCK_SIZE - 1) // _BLOCK_SIZE
    starts = rng.integers(0, n - _BLOCK_SIZE + 1, size=(n_simulations, n_blocks))
    block_offsets = np.arange(_BLOCK_SIZE)
    idx = starts[:, :, None] + block_offsets[None, None, :]
    paths = daily_returns[idx].reshape(n_simulations, n_blocks * _BLOCK_SIZE)
    return paths[:, :horizon]


def _compute_statistic(
    simulated_returns: np.ndarray[Any, Any],
    statistic: str,
    risk_free_rate: float,
) -> tuple[np.ndarray[Any, Any], int]:
    """Per-path statistic + zero-variance count (only meaningful for sharpe)."""
    n_sims = simulated_returns.shape[0]
    zero_var_count = 0

    if statistic == "max_drawdown":
        nav = np.empty((n_sims, simulated_returns.shape[1] + 1))
        nav[:, 0] = 1.0
        nav[:, 1:] = np.cumprod(1 + simulated_returns, axis=1)
        running_max = np.maximum.accumulate(nav, axis=1)
        drawdown = (nav - running_max) / np.where(running_max > 0, running_max, 1.0)
        results = np.min(drawdown, axis=1)

    elif statistic == "return":
        h = simulated_returns.shape[1]
        total = np.prod(1 + simulated_returns, axis=1) - 1.0
        results = (1.0 + total) ** (252.0 / h) - 1.0

    elif statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        excess = simulated_returns - rf_daily
        mean_excess = np.mean(excess, axis=1)
        std_excess = np.std(excess, axis=1, ddof=1)
        nonzero = std_excess > 1e-12
        results = np.where(
            nonzero,
            mean_excess / np.where(nonzero, std_excess, 1.0) * np.sqrt(252),
            0.0,
        )
        zero_var_count = int((~nonzero).sum())

    else:
        raise ValueError(f"Unknown statistic: {statistic}")

    return results, zero_var_count


def _historical_statistic(
    daily_returns: np.ndarray[Any, Any],
    statistic: str,
    risk_free_rate: float,
) -> float:
    """The statistic computed on the ACTUAL historical series."""
    if statistic == "max_drawdown":
        nav = np.insert(np.cumprod(1 + daily_returns), 0, 1.0)
        running_max = np.maximum.accumulate(nav)
        drawdown = (nav - running_max) / np.where(running_max > 0, running_max, 1.0)
        return float(np.min(drawdown))

    if statistic == "return":
        total = float(np.prod(1 + daily_returns) - 1)
        h = len(daily_returns)
        return float((1.0 + total) ** (252.0 / h) - 1.0)

    if statistic == "sharpe":
        rf_daily = risk_free_rate / 252
        excess = daily_returns - rf_daily
        mean_e = np.mean(excess)
        std_e = np.std(excess, ddof=1)
        if std_e > 1e-12:
            return float(mean_e / std_e * np.sqrt(252))
        return 0.0

    raise ValueError(f"Unknown statistic: {statistic}")


def block_bootstrap_monte_carlo(
    daily_returns: np.ndarray[Any, Any],
    n_simulations: int = 10_000,
    horizons: list[int] | None = None,
    statistic: str = "max_drawdown",
    risk_free_rate: float = 0.04,
    seed: int | None = None,
) -> MonteCarloAnalytics:
    """Bootstrapped Monte Carlo preserving skewness/kurtosis (21-day blocks).

    Parameters
    ----------
    daily_returns : np.ndarray
        (T,) daily returns (decimal fractions).
    n_simulations : int
        Number of bootstrap paths (default 10,000).
    horizons : list[int] | None
        Trading-day horizons for the confidence fan (default ``DEFAULT_HORIZONS``).
    statistic : str
        "max_drawdown" | "return" | "sharpe".
    risk_free_rate : float
        Annualized risk-free rate for the Sharpe statistic.
    seed : int | None
        Seed for ``numpy.random.default_rng`` (reproducibility).

    Raises
    ------
    ValueError
        If ``statistic`` is unknown, fewer than 42 returns are supplied, or the
        history is too short for the requested horizon (need
        ``T >= min(0.1 * max_horizon, 252)`` for a non-degenerate block bootstrap).
    """
    daily_returns = np.asarray(daily_returns, dtype=float)
    n = len(daily_returns)

    # Validate the statistic up-front so a bad name fails before the history guard.
    if statistic not in ("max_drawdown", "return", "sharpe"):
        raise ValueError(f"Unknown statistic: {statistic}")

    if n < _MIN_HISTORY:
        raise ValueError(
            f"insufficient_history: T={n} daily returns (min {_MIN_HISTORY})"
        )

    if horizons is None:
        horizons = DEFAULT_HORIZONS

    max_horizon = max(horizons)
    min_t_required = min(int(max_horizon * 0.1), 252)
    if n < min_t_required:
        raise ValueError(
            f"insufficient_history_for_horizon: T={n}, max_horizon={max_horizon}; "
            f"need T >= {min_t_required} (10% of horizon, capped at 252) "
            f"for a non-degenerate block bootstrap"
        )

    rng = np.random.default_rng(seed)

    primary_horizon = max(horizons)
    paths = _block_bootstrap_paths(daily_returns, n_simulations, primary_horizon, rng)
    sim_stats, primary_zero_var_count = _compute_statistic(
        paths, statistic, risk_free_rate
    )

    percentiles = {
        k: round(float(np.percentile(sim_stats, p)), 8)
        for k, p in zip(_PCTL_KEYS, _PCTL_VALS, strict=True)
    }

    hist_value = _historical_statistic(daily_returns, statistic, risk_free_rate)
    historical_percentile_rank: float | None = None
    if statistic in ("max_drawdown", "return"):
        matched_paths = _block_bootstrap_paths(daily_returns, n_simulations, n, rng)
        matched_stats, _ = _compute_statistic(matched_paths, statistic, risk_free_rate)
        historical_percentile_rank = round(
            float(np.mean(matched_stats < hist_value) * 100.0), 4
        )

    confidence_bars: list[dict[str, object]] = []
    for h in horizons:
        h_stats, _ = _compute_statistic(paths[:, :h], statistic, risk_free_rate)
        label = f"{h // 252}Y" if h >= 252 else f"{h}D"
        confidence_bars.append(
            {
                "horizon": label,
                "horizon_days": h,
                "pct_5": round(float(np.percentile(h_stats, 5)), 8),
                "pct_10": round(float(np.percentile(h_stats, 10)), 8),
                "pct_25": round(float(np.percentile(h_stats, 25)), 8),
                "pct_50": round(float(np.percentile(h_stats, 50)), 8),
                "pct_75": round(float(np.percentile(h_stats, 75)), 8),
                "pct_90": round(float(np.percentile(h_stats, 90)), 8),
                "pct_95": round(float(np.percentile(h_stats, 95)), 8),
                "mean": round(float(np.mean(h_stats)), 8),
            }
        )

    is_mass_zero_var = (
        statistic == "sharpe"
        and n_simulations > 0
        and primary_zero_var_count / n_simulations > _ZERO_VARIANCE_MASS_THRESHOLD
    )

    return MonteCarloAnalytics(
        n_simulations=n_simulations,
        statistic=statistic,
        percentiles=percentiles,
        mean=round(float(np.mean(sim_stats)), 8),
        median=round(float(np.median(sim_stats)), 8),
        std=round(float(np.std(sim_stats, ddof=1)), 8),
        historical_value=round(hist_value, 8),
        historical_horizon_days=n,
        historical_percentile_rank=historical_percentile_rank,
        confidence_bars=tuple(confidence_bars),
        degraded=is_mass_zero_var,
        degraded_reason=(
            f"zero_variance_collapse: {primary_zero_var_count}/{n_simulations} "
            f"paths produced zero-variance Sharpe (threshold "
            f"{_ZERO_VARIANCE_MASS_THRESHOLD:.0%}); input returns may be flat"
        )
        if is_mass_zero_var
        else None,
    )
```

- [ ] **Step 4: Run tests, expect PASS.**
Command: `cd backend && python -m pytest tests/test_analytics_monte_carlo.py -v`
Expected: all 10 tests pass.

- [ ] **Step 5: Commit.**
```
cd backend
git add app/analytics/monte_carlo.py tests/test_analytics_monte_carlo.py
git commit -m "feat(analytics): block-bootstrap Monte Carlo projections

Port monte_carlo_service to a pure numpy module (default_rng only):
drawdown/return/sharpe distributions, multi-horizon confidence fans,
historical percentile rank. Hard guards raise ValueError; soft Sharpe
zero-variance collapse sets degraded.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2G-3: Monte Carlo request/response schema

Add the Pydantic request/response schema for `POST /monte-carlo/projection`, mirroring the structure of `backend/app/schemas/portfolio_analysis.py` (request validators, echoed params, nested response models). The request carries a single `ticker`, a `statistic`, a `range`, an `n_simulations` bound, an optional `horizons` override, an optional `risk_free_rate`, and an optional `seed`. The response echoes resolved params and carries the distribution + confidence fan.

**Files:**
- Create: `backend/app/schemas/monte_carlo.py`
- Test: `backend/tests/test_monte_carlo_service.py` (new — Step 1 here adds schema-level tests only; the service tests are appended in T2G-4)

- [ ] **Step 1: Write the failing test.**
Create `backend/tests/test_monte_carlo_service.py` (schema tests first; service tests added in T2G-4):
```python
"""Tests for the Monte Carlo schema and service."""

import pytest
from pydantic import ValidationError

from app.schemas.monte_carlo import (
    MAX_SIMULATIONS,
    MIN_SIMULATIONS,
    MonteCarloRequest,
)


def test_request_defaults() -> None:
    req = MonteCarloRequest(ticker="aapl")
    assert req.ticker == "AAPL"  # normalized to uppercase
    assert req.statistic == "max_drawdown"
    assert req.range == "MAX"
    assert req.n_simulations == 10_000
    assert req.horizons is None
    assert req.risk_free_rate == pytest.approx(0.04)
    assert req.seed is None


def test_request_rejects_low_simulations() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", n_simulations=MIN_SIMULATIONS - 1)


def test_request_rejects_high_simulations() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", n_simulations=MAX_SIMULATIONS + 1)


def test_request_rejects_unknown_statistic() -> None:
    with pytest.raises(ValidationError):
        MonteCarloRequest(ticker="AAPL", statistic="median")


def test_request_rejects_nonpositive_horizon() -> None:
    with pytest.raises(ValidationError, match="horizons must all be >= 1"):
        MonteCarloRequest(ticker="AAPL", horizons=[252, 0])


def test_request_rejects_empty_horizons() -> None:
    with pytest.raises(ValidationError, match="horizons must be non-empty"):
        MonteCarloRequest(ticker="AAPL", horizons=[])
```

- [ ] **Step 2: Run it, expect FAIL.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_service.py -v`
Expected failure: `ModuleNotFoundError: No module named 'app.schemas.monte_carlo'`.

- [ ] **Step 3: Write the minimal implementation.**
Create `backend/app/schemas/monte_carlo.py`:
```python
"""Request/response schemas for POST /monte-carlo/projection.

Scale contract (project-wide): drawdown and annualized-return percentiles are
decimal fractions (0.05 = 5%), never 0-100; Sharpe is unitless. Request
validation is fail-loud (422 via Pydantic); the service maps analytics
ValueErrors to 422 as well.
"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas._tickers import normalize_ticker as _normalize_ticker
from app.schemas.analysis import RangeKey

MIN_SIMULATIONS = 1_000
MAX_SIMULATIONS = 50_000

Statistic = Literal["max_drawdown", "return", "sharpe"]


class MonteCarloRequest(BaseModel):
    """Block-bootstrap Monte Carlo projection request for one instrument."""

    ticker: str = Field(description="Instrument ticker (normalized to uppercase).")
    statistic: Statistic = Field(
        default="max_drawdown",
        description="Which statistic to project: max_drawdown | return | sharpe.",
    )
    range: RangeKey = Field(
        default="MAX",
        description="History window used to estimate the return distribution; "
        "MAX = full available history.",
    )
    n_simulations: int = Field(
        default=10_000,
        ge=MIN_SIMULATIONS,
        le=MAX_SIMULATIONS,
        description=f"Number of bootstrap paths ({MIN_SIMULATIONS}-{MAX_SIMULATIONS}).",
    )
    horizons: list[int] | None = Field(
        default=None,
        description="Trading-day horizons for the confidence fan; default 1Y/3Y/5Y/7Y/10Y.",
    )
    risk_free_rate: float = Field(
        default=0.04,
        description="Annualized risk-free rate for the Sharpe statistic (decimal fraction).",
    )
    seed: int | None = Field(
        default=None, description="Optional RNG seed for a reproducible projection."
    )

    @field_validator("ticker")
    @classmethod
    def _check_ticker(cls, value: str) -> str:
        return _normalize_ticker(value, "ticker")

    @field_validator("horizons")
    @classmethod
    def _check_horizons(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        if len(value) == 0:
            raise ValueError("horizons must be non-empty when supplied")
        if any(h < 1 for h in value):
            raise ValueError("horizons must all be >= 1 trading day")
        return value


class MonteCarloParams(BaseModel):
    """Echo of the resolved request parameters."""

    ticker: str
    statistic: Statistic
    range: RangeKey
    n_simulations: int
    risk_free_rate: float
    seed: int | None = Field(description="Seed used, or null when unseeded.")


class ConfidenceBar(BaseModel):
    """One horizon's percentile fan of the projected statistic.

    For max_drawdown/return the percentile fields are decimal fractions
    (0.05 = 5%); for sharpe they are unitless.
    """

    horizon: str = Field(description="Human label, e.g. '1Y', '10Y' (or 'ND' for sub-year).")
    horizon_days: int = Field(description="Horizon length in trading days.")
    pct_5: float
    pct_10: float
    pct_25: float
    pct_50: float
    pct_75: float
    pct_90: float
    pct_95: float
    mean: float


class MonteCarloResponse(BaseModel):
    """Render-ready Monte Carlo projection payload.

    The backend computes ALL finance; the frontend only draws. Percentiles for
    max_drawdown/return are decimal fractions (0.05 = 5%); sharpe is unitless.
    """

    params: MonteCarloParams
    percentiles: dict[str, float] = Field(
        description="Distribution of the statistic at the longest horizon, keyed by "
        "percentile ('1st'..'99th')."
    )
    mean: float
    median: float
    std: float
    historical_value: float = Field(
        description="The statistic computed on the ACTUAL historical series."
    )
    historical_horizon_days: int = Field(
        description="Length of the historical series in trading days."
    )
    historical_percentile_rank: float | None = Field(
        description="Percentile rank (0-100) of the historical value within a "
        "horizon-matched bootstrap; null for the sharpe statistic."
    )
    confidence_bars: list[ConfidenceBar] = Field(
        description="Per-horizon percentile fans (the projection chart)."
    )
    degraded: bool = Field(
        description="True only when a flat-NAV Sharpe collapse made the result uninformative."
    )
    degraded_reason: str | None = Field(
        description="Diagnostic when degraded is True, else null."
    )
```
(`RangeKey` = `Literal["1M","6M","1Y","5Y","MAX"]` is imported from `app.schemas.analysis:20`; `_normalize_ticker` uppercases + validates against `^[A-Z0-9.\-]{1,10}$` per `app/schemas/_tickers.py:13`.)

- [ ] **Step 4: Run tests, expect PASS.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_service.py -v`
Expected: all 6 schema tests pass.

- [ ] **Step 5: Commit.**
```
cd backend
git add app/schemas/monte_carlo.py tests/test_monte_carlo_service.py
git commit -m "feat(schema): Monte Carlo projection request/response models

MonteCarloRequest (ticker/statistic/range/n_simulations/horizons/
risk_free_rate/seed) with fail-loud validators; MonteCarloResponse with
percentile distribution + confidence fan.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2G-4: Monte Carlo service (pure `assemble_*` + async `run_*`)

Add the service layer following the CANONICAL LIGHT pattern from `backend/app/services/statistics.py` (pure `assemble_monte_carlo(returns_array, ...) -> MonteCarloResponse` with no I/O, plus an async `run_monte_carlo(session, client, ...)` orchestrator that warms EOD, reads the DB, builds the return array, and calls assemble). The assemble step maps the analytics `ValueError` hard guards to `InsufficientDataError` (so the route emits 422). The orchestrator imports the read helpers with leading-underscore aliases EXACTLY like `statistics.py:88-90` (`from app.services._series import select_date_bounds as _select_date_bounds` and `select_adj_close_rows as _select_adj_close_rows`) so the route tests can monkeypatch them on this service module (the boundary proven by `tests/test_statistics_routes.py:90`).

**Files:**
- Create: `backend/app/services/monte_carlo.py`
- Test: `backend/tests/test_monte_carlo_service.py` (append service tests to the file created in T2G-3)

- [ ] **Step 1: Write the failing test (append to the existing file).**
Append to `backend/tests/test_monte_carlo_service.py`:
```python
import numpy as np

from app.services.monte_carlo import assemble_monte_carlo
from app.services.stock_analysis import InsufficientDataError


def _mc_returns(n: int = 500, seed: int = 13) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.normal(0.0004, 0.01, n)


def test_assemble_returns_response_shape() -> None:
    resp = assemble_monte_carlo(
        _mc_returns(),
        ticker="AAPL",
        statistic="max_drawdown",
        range_key="MAX",
        n_simulations=2000,
        horizons=None,
        risk_free_rate=0.04,
        seed=42,
    )
    assert resp.params.ticker == "AAPL"
    assert resp.params.statistic == "max_drawdown"
    assert resp.params.n_simulations == 2000
    assert resp.params.seed == 42
    assert set(resp.percentiles.keys()) == {
        "1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"
    }
    assert resp.historical_percentile_rank is not None
    assert resp.confidence_bars[0].horizon == "1Y"
    assert resp.confidence_bars[0].horizon_days == 252
    assert resp.degraded is False


def test_assemble_is_deterministic_under_seed() -> None:
    r = _mc_returns()
    kwargs = dict(
        ticker="AAPL", statistic="return", range_key="MAX",
        n_simulations=1500, horizons=None, risk_free_rate=0.04, seed=99,
    )
    a = assemble_monte_carlo(r, **kwargs)
    b = assemble_monte_carlo(r, **kwargs)
    assert a.percentiles == b.percentiles
    assert a.median == b.median


def test_assemble_short_history_maps_to_insufficient_data() -> None:
    with pytest.raises(InsufficientDataError, match="insufficient_history"):
        assemble_monte_carlo(
            _mc_returns(n=40),
            ticker="AAPL",
            statistic="max_drawdown",
            range_key="MAX",
            n_simulations=1000,
            horizons=None,
            risk_free_rate=0.04,
            seed=1,
        )


def test_assemble_horizon_guard_maps_to_insufficient_data() -> None:
    with pytest.raises(InsufficientDataError, match="insufficient_history_for_horizon"):
        assemble_monte_carlo(
            _mc_returns(n=60),
            ticker="AAPL",
            statistic="max_drawdown",
            range_key="MAX",
            n_simulations=1000,
            horizons=None,
            risk_free_rate=0.04,
            seed=1,
        )
```
(`pytest` is already imported at the top of the file from T2G-3 Step 1. The local helper is named `_mc_returns` to avoid shadowing.)

- [ ] **Step 2: Run it, expect FAIL.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_service.py -v`
Expected failure: `ModuleNotFoundError: No module named 'app.services.monte_carlo'` for the appended imports.

- [ ] **Step 3: Write the minimal implementation.**
Create `backend/app/services/monte_carlo.py`:
```python
"""Assembly + orchestration for POST /monte-carlo/projection.

assemble_monte_carlo is a pure adapter (numpy return array -> response schema,
no I/O). run_monte_carlo is the async orchestrator: warm EOD, read the DB,
build the daily-return array, call assemble. Mirrors the assemble_* / run_*
split and the underscore-aliased read-helper imports used by
app.services.statistics.

Scale contract: drawdown/return percentiles are decimal fractions; sharpe is
unitless. The analytics layer's hard ValueError guards are re-raised as
InsufficientDataError so the route maps them to HTTP 422.
"""

from __future__ import annotations

import datetime as dt

import numpy as np
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.monte_carlo import block_bootstrap_monte_carlo
from app.analytics.returns import simple_returns
from app.api._shared import ensure_eod_or_http_error
from app.ingestion.service import HISTORY_FLOOR
from app.schemas.analysis import RangeKey
from app.schemas.monte_carlo import (
    ConfidenceBar,
    MonteCarloParams,
    MonteCarloResponse,
    Statistic,
)
from app.services._series import (
    RANGE_DAYS,
)
from app.services._series import (
    select_adj_close_rows as _select_adj_close_rows,
)
from app.services._series import (
    select_date_bounds as _select_date_bounds,
)
from app.services.stock_analysis import (
    InsufficientDataError,
    build_adj_close_series,
)
from app.tiingo.client import TiingoClient

_MIN_RETURNS = 42


def assemble_monte_carlo(
    daily_returns: np.ndarray,
    *,
    ticker: str,
    statistic: Statistic,
    range_key: RangeKey,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> MonteCarloResponse:
    """Build the projection payload from a daily-return array (pure, no I/O).

    Raises:
        InsufficientDataError: if the analytics layer rejects the input
            (too little history, or history too short for the horizon).
    """
    try:
        result = block_bootstrap_monte_carlo(
            daily_returns,
            n_simulations=n_simulations,
            horizons=horizons,
            statistic=statistic,
            risk_free_rate=risk_free_rate,
            seed=seed,
        )
    except ValueError as exc:
        # "Unknown statistic" cannot occur (the schema constrains the literal);
        # the remaining ValueErrors are the history/horizon guards.
        raise InsufficientDataError(str(exc)) from exc

    return MonteCarloResponse(
        params=MonteCarloParams(
            ticker=ticker,
            statistic=statistic,
            range=range_key,
            n_simulations=n_simulations,
            risk_free_rate=risk_free_rate,
            seed=seed,
        ),
        percentiles=result.percentiles,
        mean=result.mean,
        median=result.median,
        std=result.std,
        historical_value=result.historical_value,
        historical_horizon_days=result.historical_horizon_days,
        historical_percentile_rank=result.historical_percentile_rank,
        confidence_bars=[ConfidenceBar(**bar) for bar in result.confidence_bars],
        degraded=result.degraded,
        degraded_reason=result.degraded_reason,
    )


async def run_monte_carlo(
    session: AsyncSession,
    client: TiingoClient,
    *,
    ticker: str,
    statistic: Statistic,
    range_key: RangeKey,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> MonteCarloResponse:
    """Warm EOD, read adjusted closes, build the return array, then assemble.

    Raises:
        InsufficientDataError: no price rows, fewer than 2 closes, or the
            analytics layer rejects the return array.
    """
    today = dt.date.today()
    ensure_start = (
        HISTORY_FLOOR
        if range_key == "MAX"
        else today - dt.timedelta(days=RANGE_DAYS[range_key])
    )
    await ensure_eod_or_http_error(session, client, [ticker], ensure_start, today)

    first, last = await _select_date_bounds(session, ticker)
    if first is None or last is None:
        raise InsufficientDataError(f"No price data available for {ticker}.")
    end = last
    start = (
        first if range_key == "MAX" else end - dt.timedelta(days=RANGE_DAYS[range_key])
    )

    rows = await _select_adj_close_rows(session, ticker, start, end)
    closes = build_adj_close_series(rows)
    if len(closes) < 2:
        raise InsufficientDataError(
            f"Only {len(closes)} price rows for {ticker} — not enough to compute returns."
        )

    returns = simple_returns(closes).to_numpy(dtype=float)
    if len(returns) < _MIN_RETURNS:
        raise InsufficientDataError(
            f"Only {len(returns)} daily returns for {ticker} — at least {_MIN_RETURNS} "
            "are required for a block-bootstrap projection. Use a wider range."
        )

    return assemble_monte_carlo(
        returns,
        ticker=ticker,
        statistic=statistic,
        range_key=range_key,
        n_simulations=n_simulations,
        horizons=horizons,
        risk_free_rate=risk_free_rate,
        seed=seed,
    )
```
(`ensure_eod_or_http_error` raises HTTP errors itself for warming failures, exactly as the portfolio route at `backend/app/api/routes/portfolio.py:80` and the statistics service at `backend/app/services/statistics.py:221`. `HISTORY_FLOOR` = `date(1990,1,1)` is at `app/ingestion/service.py:47`; `RANGE_DAYS` = `{"1M":30,"6M":182,"1Y":365,"5Y":1826}` (no `"MAX"` key, hence the conditional) is at `app/services/_series.py:28`; `select_date_bounds`/`select_adj_close_rows` are at `app/services/_series.py:31,44`; `build_adj_close_series` at `app/services/stock_analysis.py:119`; `simple_returns` at `app/analytics/returns.py:12`; `InsufficientDataError(StockAnalysisError)` at `app/services/stock_analysis.py:89`.)

- [ ] **Step 4: Run tests, expect PASS.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_service.py -v`
Expected: all 6 schema tests AND the 4 service tests pass (10 total).

- [ ] **Step 5: Commit.**
```
cd backend
git add app/services/monte_carlo.py tests/test_monte_carlo_service.py
git commit -m "feat(service): Monte Carlo assemble + async run orchestrator

Pure assemble_monte_carlo(returns_array)->MonteCarloResponse mapping
analytics ValueError guards to InsufficientDataError; async run_monte_carlo
warms EOD, reads adj closes, builds returns, calls assemble. Read helpers
underscore-aliased (statistics.py pattern) for the route-test boundary.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T2G-5: `POST /monte-carlo/projection` route + registration

Add the thin route (validate -> run -> map `InsufficientDataError`/`StockAnalysisError` to 404/422), mirroring `backend/app/api/routes/statistics.py` (which imports `from app.services import statistics as statistics_service`, `from app.services.stock_analysis import StockAnalysisError`, and overrides `get_session`/`get_tiingo_client`). Register it in `backend/app/main.py`. The route does NO DB reads itself — the service owns them — so the route module needs no read-helper imports. Route tests monkeypatch the helpers on the SERVICE module (`mc_service._select_date_bounds`, `mc_service._select_adj_close_rows`) and `ensure_eod_data` on `app.api._shared`, exactly the boundary used by `tests/test_statistics_routes.py:89-90`.

**Files:**
- Create: `backend/app/api/routes/monte_carlo.py`
- Modify: `backend/app/main.py` (add `from app.api.routes import monte_carlo as monte_carlo_router` to the alphabetical import block at lines 7-17, placed after the `macro` import on line 10 and before the `portfolio` import on line 11; add `application.include_router(monte_carlo_router.router)` to the registration block, immediately after `application.include_router(macro_router.router)` on line 59)
- Test: `backend/tests/test_monte_carlo_route.py` (new)

- [ ] **Step 1: Write the failing test.**
Create `backend/tests/test_monte_carlo_route.py`:
```python
"""Tests for POST /monte-carlo/projection.

The ingestion service and DB read helpers are stubbed at the SERVICE-module
boundary (the canonical pattern from test_statistics_routes.py); the Tiingo
client and DB session dependencies are overridden. No live network, no live DB.
"""

import datetime as dt
from collections.abc import AsyncGenerator
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.api import _shared as api_shared
from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.ingestion.service import EnsureReport
from app.main import create_app
from app.services import monte_carlo as mc_service

N_DAYS = 800
AdjCloseRow = tuple[dt.date, float]


def _synthetic_rows(seed: int, n_days: int = N_DAYS) -> list[AdjCloseRow]:
    dates = pd.bdate_range(end=dt.date.today(), periods=n_days)
    rng = np.random.default_rng(seed)
    closes = 100.0 * np.cumprod(1 + rng.normal(0.0004, 0.01, n_days))
    return [(ts.date(), float(c)) for ts, c in zip(dates, closes, strict=True)]


ROWS_BY_TICKER: dict[str, list[AdjCloseRow]] = {"AAPL": _synthetic_rows(seed=1)}


def _app_with_overrides() -> FastAPI:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_tiingo_client] = lambda: object()
    return app


def _install_stubs(
    monkeypatch: pytest.MonkeyPatch,
    rows_by_ticker: dict[str, list[AdjCloseRow]] | None = None,
) -> None:
    rows_map = ROWS_BY_TICKER if rows_by_ticker is None else rows_by_ticker

    async def fake_ensure(*args: Any, **kwargs: Any) -> EnsureReport:
        return EnsureReport()

    async def fake_bounds(
        session: Any, ticker: str
    ) -> tuple[dt.date | None, dt.date | None]:
        rows = rows_map.get(ticker, [])
        if not rows:
            return None, None
        return rows[0][0], rows[-1][0]

    async def fake_adj_close(
        session: Any, ticker: str, start: dt.date, end: dt.date
    ) -> list[AdjCloseRow]:
        return [r for r in rows_map.get(ticker, []) if start <= r[0] <= end]

    # ensure_eod_or_http_error calls ensure_eod_data from app.api._shared's
    # namespace; the read helpers are looked up as SERVICE-module globals
    # (underscore aliases to app.services._series).
    monkeypatch.setattr(api_shared, "ensure_eod_data", fake_ensure)
    monkeypatch.setattr(mc_service, "_select_date_bounds", fake_bounds)
    monkeypatch.setattr(mc_service, "_select_adj_close_rows", fake_adj_close)


@pytest.fixture
async def stub_client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncGenerator[AsyncClient, None]:
    _install_stubs(monkeypatch)
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def test_projection_happy_path_shape(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/monte-carlo/projection",
        json={
            "ticker": "aapl",
            "statistic": "max_drawdown",
            "n_simulations": 2000,
            "seed": 7,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "params", "percentiles", "mean", "median", "std",
        "historical_value", "historical_horizon_days",
        "historical_percentile_rank", "confidence_bars",
        "degraded", "degraded_reason",
    }
    assert body["params"]["ticker"] == "AAPL"
    assert body["params"]["statistic"] == "max_drawdown"
    assert body["params"]["seed"] == 7
    assert set(body["percentiles"].keys()) == {
        "1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"
    }
    assert body["confidence_bars"][0]["horizon"] == "1Y"
    assert body["degraded"] is False


async def test_projection_is_deterministic_under_seed(stub_client: AsyncClient) -> None:
    payload = {"ticker": "AAPL", "statistic": "return", "n_simulations": 1500, "seed": 5}
    a = (await stub_client.post("/monte-carlo/projection", json=payload)).json()
    b = (await stub_client.post("/monte-carlo/projection", json=payload)).json()
    assert a["percentiles"] == b["percentiles"]
    assert a["median"] == b["median"]


async def test_unknown_ticker_404(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_stubs(monkeypatch, rows_by_ticker={})
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post("/monte-carlo/projection", json={"ticker": "ZZZZ"})
    assert response.status_code == 404


async def test_insufficient_history_422(monkeypatch: pytest.MonkeyPatch) -> None:
    # Only 30 business days: below the 42-return analytics floor -> 422.
    _install_stubs(
        monkeypatch, rows_by_ticker={"AAPL": _synthetic_rows(seed=1, n_days=30)}
    )
    transport = ASGITransport(app=_app_with_overrides())
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        response = await ac.post(
            "/monte-carlo/projection", json={"ticker": "AAPL", "range": "MAX"}
        )
    assert response.status_code == 422


async def test_bad_n_simulations_422(stub_client: AsyncClient) -> None:
    response = await stub_client.post(
        "/monte-carlo/projection", json={"ticker": "AAPL", "n_simulations": 1}
    )
    assert response.status_code == 422  # Pydantic bound violation
```

- [ ] **Step 2: Run it, expect FAIL.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_route.py -v`
Expected failure: `ModuleNotFoundError: No module named 'app.api.routes.monte_carlo'` (the route module and its registration do not exist yet).

- [ ] **Step 3: Write the minimal implementation.**
Create `backend/app/api/routes/monte_carlo.py`:
```python
"""Monte Carlo endpoint: POST /monte-carlo/projection (single instrument).

DB-first contract (same as the stock/portfolio/statistics routes): never talks
to Tiingo directly — the service warms EOD via the shared error-mapping helper,
then serves from eod_prices. The route stays thin: validate -> run -> map
InsufficientDataError/StockAnalysisError to 404/422.

Error mapping (fail loud):
- request validation (ticker/statistic/n_simulations/horizons)  -> 422 (Pydantic)
- unknown ticker / no price rows                                 -> 404
- Tiingo rate limited / auth / server error                     -> 503/502 (warm helper)
- insufficient history for the projection                       -> 422
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.tiingo_provider import get_tiingo_client
from app.schemas.monte_carlo import MonteCarloRequest, MonteCarloResponse
from app.services.monte_carlo import run_monte_carlo
from app.services.stock_analysis import InsufficientDataError, StockAnalysisError
from app.tiingo.client import TiingoClient

router = APIRouter(prefix="/monte-carlo", tags=["monte-carlo"])


@router.post("/projection", response_model=MonteCarloResponse)
async def project_monte_carlo(
    payload: MonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
    client: Annotated[TiingoClient, Depends(get_tiingo_client)],
) -> MonteCarloResponse:
    """Block-bootstrap Monte Carlo projection for one instrument — single call.

    Returns the percentile distribution of the chosen statistic at the longest
    horizon, a per-horizon confidence fan, and the historical value with its
    bootstrap percentile rank. All drawdown/return fields are decimal fractions
    (0.05 = 5%); sharpe is unitless.
    """
    try:
        return await run_monte_carlo(
            session,
            client,
            ticker=payload.ticker,
            statistic=payload.statistic,
            range_key=payload.range,
            n_simulations=payload.n_simulations,
            horizons=payload.horizons,
            risk_free_rate=payload.risk_free_rate,
            seed=payload.seed,
        )
    except InsufficientDataError as exc:
        message = str(exc)
        if message.startswith("No price data available"):
            raise HTTPException(status_code=404, detail=message) from exc
        raise HTTPException(status_code=422, detail=message) from exc
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```
(`InsufficientDataError` is a subclass of `StockAnalysisError` — `app/services/stock_analysis.py:85,89` — so the `InsufficientDataError` `except` clause MUST come first; the 404 branch keys off the "No price data available" message raised by `run_monte_carlo` when `_select_date_bounds` returns `(None, None)`.)

Then register the router in `backend/app/main.py`. Add the import (alphabetical) between `macro` (line 10) and `portfolio` (line 11):
```python
from app.api.routes import monte_carlo as monte_carlo_router
```
and add the `include_router` call immediately after `application.include_router(macro_router.router)` (line 59):
```python
    application.include_router(monte_carlo_router.router)
```

- [ ] **Step 4: Run tests, expect PASS.**
Command: `cd backend && python -m pytest tests/test_monte_carlo_route.py -v`
Expected: all 5 route tests pass. Then run the whole new suite to confirm no cross-file regression:
`cd backend && python -m pytest tests/test_analytics_risk_episodes.py tests/test_analytics_monte_carlo.py tests/test_monte_carlo_service.py tests/test_monte_carlo_route.py -v`
Expected: all green (7 + 10 + 10 + 5 = 32 tests). Also confirm app import is intact: `cd backend && python -c "from app.main import create_app; create_app()"`.

- [ ] **Step 5: Commit.**
```
cd backend
git add app/api/routes/monte_carlo.py app/main.py tests/test_monte_carlo_route.py
git commit -m "feat(route): POST /monte-carlo/projection + registration

Thin route validate->run->map; InsufficientDataError->404/422,
StockAnalysisError->422. Register monte_carlo_router in main.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Perguntas em aberto / decisoes necessarias (Tier 2)

_Resolver antes (ou no inicio) da execucao das tasks afetadas._

### T2A
- Annualization default: the legacy module defaults periods_per_year=12 (monthly fund returns, the EDHEC use-case). The Light risk.py functions (annualized_volatility et al.) default to 252 (daily). The port keeps the legacy default of 12 because the robust Sharpe is designed for monthly fund series and the tiered T<12/36/60 thresholds are calibrated for monthly data. Callers passing daily series MUST pass periods_per_year=252 explicitly. Confirm no Light caller silently relies on a 252 default (there are no callers yet — this is an analytics-only cluster).
- No risk-free-rate source exists in app/analytics today (the existing risk.py functions take no rf). robust_sharpe takes rf_rate per-period and treats None as 0.0 per the legacy spec. Wiring it to a service/route (warm EOD -> read DB -> assemble) is OUT OF SCOPE for this Tier-2 analytics-only cluster and is left to a downstream service task. Gate G5 (no sample-mean expected returns in objectives) is unaffected: this is a scoring statistic, not an optimizer objective input.
- End-to-end reachability of degraded_reason=='ci_unavailable' through robust_sharpe() is floating-point-fragile and NOT deterministically testable on synthetic data. VERIFIED empirically against the legacy module: (a) an exactly-constant series whose float std is exactly 0.0 (e.g. [0.02]*40, [0.0]*40, or [0.01]*72) hits the zero_volatility guard BEFORE the jackknife/Opdyke branch, so it returns 'zero_volatility', not 'ci_unavailable'; (b) [0.01]*60 happens to give np.std(ddof=1)==1.75e-18 (tiny but nonzero, because 60 copies of the IEEE-754 value of 0.01 do not cancel to exactly 0) so it slips past the zero-vol guard and DOES reach 'ci_unavailable' via a degenerate jackknife — but the same construction at T=72 or T=120 rounds to exactly 0.0 and yields 'zero_volatility' instead. Because the outcome depends on T-specific float accumulation (and skew/kurtosis come back NaN via catastrophic cancellation), the original draft test test_jackknife_degenerate_se_marks_ci_unavailable ([0.01]*35+[0.01000001], T=36) is WRONG: it actually yields 35 finite jackknife replicates, a finite (huge ~2e7) CI, and degraded_reason=='cornish_fisher_non_monotonic' — NOT 'ci_unavailable'. The hardened plan therefore (1) deletes that brittle test and (2) tests the _jackknife_se helper's NaN return directly (deterministic: _jackknife_se([0.5]*10) -> nan because every leave-one-out subset is exactly constant). The end-to-end ci_unavailable wiring (degraded + reason) is still implemented and exercised indirectly via the helper + the closed-form non-finite-SE branch; an explicit robust end-to-end ci_unavailable fixture is left as an open question for whoever adds a service-level integration test (it would need a deliberately constructed near-constant series at a specific T, which is too implementation-coupled for a unit test).
- scipy is currently only a transitive dependency. Task T2A-1 Step 1 adds it explicitly in pyproject.toml. If repo policy is to NOT pin transitive deps explicitly, drop Step 1 (the import works regardless) — but explicit is safer since this module imports scipy.stats directly. This is a judgement call for the maintainer; the plan assumes explicit-is-better.

### T2B
- The light analytics layer does not yet have a service/route that calls risk_budgeting (the legacy compute_risk_budget shipped as a pure-sync service in quant_engine/risk_budgeting_service.py with a RiskBudgetResult shell). This cluster delivers ONLY the pure-numpy analytics layer plus its __init__ exports, matching the dispatch ("Pure numpy ... on the scenario matrix"). Wiring it into a builder diagnostics route / Pydantic schema is out of scope here and should be a separate Tier-2 service task if the product wants to surface MCETL/PCETL/STARR through the API. The natural feed is backend/app/services/portfolio_builder.py:249 (scenarios = frame.to_numpy(dtype=float)) plus the BL posterior mu for the implied-return duals.
- Legacy compute_risk_budget (E:/investintell-allocation/backend/quant_engine/risk_budgeting_service.py:149-157) computes MCETL by FINITE DIFFERENCE on perturbed weights (epsilon=1e-4), which does NOT exactly satisfy Euler's identity (sum of w_i*MCETL_i = portfolio ETL only to O(epsilon)). This cluster instead uses the EXACT Euler/empirical-ES kernel-average decomposition (the per-asset mean over the scenarios that fall in the portfolio tail), which DOES sum to total ES by construction and is the correct basis for the "contributions sum to total ES" TDD invariant the dispatch requires. The finite-difference legacy approach is intentionally not ported. Confirm the product is fine with the exact-Euler definition (it is the standard one; e.g. Tasche 2002).
- SIGN/TAIL-ESTIMATOR DIVERGENCE FROM LEGACY (intentional, confirm with product): (a) legacy _portfolio_etl returns a SIGNED-NEGATIVE ETL via a COUNT-based tail (np.sort(returns)[:int(len*(1-c))], min 1), whereas this cluster returns a POSITIVE ETL via the SAME quantile-based tail mask as app.analytics.historical_cvar (risk.py:109-110: cutoff = quantile(port, 1-c); tail = port <= cutoff). We deliberately match the light analytics layer (positive loss magnitude, quantile tail) so portfolio_etl reconciles to 1e-12 with app.analytics.historical_cvar. The two tail estimators give slightly different ETL numbers than the legacy count-based one near the boundary; this is by design (consistency with the F3 estimator beats bit-for-bit legacy parity).

### T2C
- Asset-class block-budget request DSL (T2C-2): the engine operates on bare numpy and never sees Fund.asset_class, so block budgets are implemented as index-group budgets (BlockBudget(indices, lo, hi)). The service resolves asset_class strings -> column indices via the new optimizer_data.load_fund_asset_class. Fund.asset_class (backend/app/models/fund.py:80, Mapped[str | None], values equity|fixed_income|cash|alternatives, 100% coverage per the model comment) exists, so resolution is real. The PRODUCT decision still owed: whether to expose block bounds keyed by the asset_class taxonomy in the public request (this plan exposes block_budgets: list[BlockBudgetIn] with asset_class keys, honoured only by the min_cvar objective in v1) needs owner sign-off on which taxonomy to surface; block budgets on non-min_cvar objectives are accepted by the schema but ignored in v1 (documented in the ConstraintsIn docstring).
- Regime-conditional CVaR (T2C-7/T2C-8) drives the multiplier off the DISCRETE state (CreditRegimeSnapshot.state == 'risk_off' tightens the limit by DEFAULT_RISK_OFF_CVAR_FACTOR=0.5) because that is the materialized, tested series the rebalance path already consumes. CreditRegimeSnapshot also carries a continuous stress_score (float | None); switching to a stress_score-scaled multiplier is a localized change to regime_cvar_multiplier but needs a product decision on the scaling curve.
- T2C-8 integration-test sensitivity: _stub_returns in test_builder_route.py produces daily returns with ~0.008-0.014 vol, so daily CVaR_95 of any allocation is roughly 0.02-0.03 — far below a 0.20 or even 0.10 cvar_limit. A pure 'realized CVaR <= effective limit' assertion would pass trivially without the cap ever binding. The hardened T2C-8 test therefore (a) asserts the service-level apply_regime_cvar_limit math directly (deterministic, no solver), and (b) keeps the integration test but asserts on the OVERRIDE-driven effective limit via a monkeypatched solve_max_return_cvar_capped capture, rather than relying on the realized number to drop. If the product wants a binding-cap end-to-end assertion, the stub must inject a fat-tailed scenario matrix — flagged for the owner.
- expected.cvar_95_in_sample in OptimizeResponse is computed by app.analytics.historical_cvar on RAW scenarios (portfolio_builder.py:309-311), which is a slightly different empirical estimator than engine._realized_cvar (the RU k-th-worst-loss verifier). They agree in magnitude but are not identical; tests must not assert exact equality between the response field and the engine verifier.

### T2D
- Risk-free rate for Sharpe: the LEGACY quant_engine/backtest_service.py uses 0.04/252 (annualized 4%) as the _compute_fold_metrics default; backend/_gate_vs_full_backtest.py (metrics()) uses an excess-free Sharpe (daily.mean()/daily.std()*sqrt(252)). This plan exposes risk_free_annual as a request field DEFAULTING TO 0.0 — matching the research script and the app's existing mean/std Sharpe usage (screener/statistics). Confirm whether 4% RF is desired as the product default instead of 0.0 (the analytics function already supports any value via risk_free_annual).
- Cost model default: backend/_gate_vs_full_backtest.py charges turnover*COST_BPS/1e4 on the FIRST day of each test segment (one-way bps on the L1 weight change vs the previous rebalance; line 117 + 123). This plan ports that exact accounting with a 10 bps one-way default (the script's COST_BPS env fallback, line 32). Confirm 10 bps one-way is acceptable for the product; it is fully request-overridable via cost_bps (0..1000 bps).
- max_drawdown NAV convention: the LEGACY _compute_fold_metrics prepends a 1.0 anchor to the NAV path before drawdown (navs = concatenate([[1.0], cumprod(1+r)]), line 46), so a loss on the FIRST OOS day still registers a drawdown from the 1.0 peak. This plan computes nav=(1+net_series).cumprod() WITHOUT the leading 1.0 (so the first OOS bar IS the initial peak), to keep nav.index aligned with the OOS dates for max_drawdown's date attribution. The test reconstructs the metric identically, so the plan is internally consistent — but the resulting max_drawdown can differ slightly from the legacy convention on folds whose worst day is day 1. Confirm whether the legacy leading-1.0 anchor is required for parity; if so, Task T2D-1 Step 3 must prepend the anchor (and the test's expected_dd reconstruction must match).

### T2E
- Rank-transform leakage for live attribution: the worker rank-transforms characteristics PER PERIOD across the whole universe (factor_model.py::rank_transform line 96-104, groupby(level='month').transform(lambda g: g.rank(pct=True) - 0.5), range [-0.5,+0.5]) before fitting Gamma. To project a fund's CURRENT characteristics onto betas consistently, the reader must rank-transform that fund's latest equity_characteristics_monthly row against the SAME cross-section. Task T2E-2 reads the full latest cross-section from equity_characteristics_monthly (_LATEST_CROSS_SECTION_SQL) and re-applies the worker's rank_transform (_rank_transform_cross_section: df.rank(pct=True) - 0.5) so betas land on the Gamma scale. CONFIRM with the data owner that equity_characteristics_monthly is materialized in the cloud data-lake. The worker has a legacy-DB fallback (factor_model.py lines 85-90, _LEGACY_DSN host=localhost port=5434) that does NOT exist in production; the cloud path requires the recalculated table (factor_model.py docstring lines 52-56 confirm the cloud table is 'em reconstrução por outro agente'). If the cloud table is empty, T2E-2's _fetch_cross_section raises ValueError (fail-loud) and the route maps to 422.
- factor_model_fits stores gamma_loadings (L×K) and factor_returns ({dates, values K×T}) but NO factor covariance and NO per-fund residual variance — confirmed against factor_model.py::_upsert (lines 484-527, INSERT writes only gamma_loadings + factor_returns + scalar fit stats; no Σ_f, no D_i). Task T2E-1 (the factor-attribution service) therefore computes the factor covariance from the persisted factor_returns series (np.cov over the K×T matrix, rowvar=True) and derives a strictly-positive per-fund specific variance proxy D_i = the fund's own systematic variance (betaᵢ² · diag-annualized factor variance), floored at 1e-8, so specific_risk_pct > 0 and the decomposition never returns NaN. CONFIRM this proxy is acceptable vs persisting true Σ_f / D_i in the worker; if the product wants worker-persisted Σ_f / D_i, that is a separate WORKERS-repo task (out of scope for T2E). The pure assemble_factor_attribution takes specific_variance as an explicit argument, so the Euler math is tested independently of the proxy.
- np.cov convention differs from legacy: legacy quant_engine/factor_model_service.py::compute_factor_contributions (lines 972) uses np.cov(factor_returns, rowvar=False) because its in-memory factor_returns is T×K (time on rows). The WORKER persists factor_returns as K×T (factor_model.py::_upsert line 493, values = fit['factor_returns'].tolist() # K x T; confirmed by schemas/factor_model.sql comment lines 11-13 'values[k] = série temporal (T)'). T2E-2 therefore MUST use np.cov(factor_returns, rowvar=True) — do NOT 'correct' this to match the legacy rowvar=False. This is called out explicitly in the implementation note so the executing engineer does not regress it.
- There is no existing FastAPI route for factor attribution or absorption in the light app (no app/routes for either; absorption_ratio in analytics is currently unused — app/optimizer/data.py does NOT call analytics.portfolio.correlation_matrix, contrary to an earlier draft claim). T2E delivers the analytics pure fn (rank 15) and the service reader + assemble (rank 14), both route-ready (pure assemble_* + async run_*). Wiring an actual route (e.g. GET /portfolios/{id}/factor-attribution and an absorption field on a risk endpoint) is intentionally left to a separate route task.

### T2F
- T2F-1 production MV re-creation is operational, not code: after merge an operator must DROP MATERIALIZED VIEW fund_risk_latest_mv; re-run the CREATE from backend/db/ddl/2026-06-13_dynamic_catalog.sql; recreate the UNIQUE index fund_risk_latest_mv_pk; then the worker's CONCURRENTLY refresh repopulates the four columns on the next cron. Noted in the T2F-1 commit body; cannot be exercised by a unit test (offline metadata only).
- T2F-2 precedence: BLParamsIn.delta defaults to a present, finite, positive 2.5, so when a caller omits bl.delta the service still passes 2.5 and resolve_delta returns 2.5 (override wins) regardless of mandate. As implemented, a non-moderate mandate changes delta only when the caller has NOT set bl.delta away from 2.5 AND the mandate maps to a non-2.5 rung — but because 2.5 is also the explicit default the two are indistinguishable at the boundary. Making mandate take effect for a user who did not opt into a custom delta requires distinguishing 'delta omitted' from 'delta == 2.5' (e.g. defaulting BLParamsIn.delta to None and only clamping when supplied). That schema change is OUT OF SCOPE here; the pure resolve_delta contract (override-wins, clamp [0.5,10]) is fully unit-tested, and the wiring passes payload.bl.delta verbatim. Flag to product before promoting mandate to a user-facing knob.
- T2F-2 does NOT persist mandate on the saved portfolio (SaveRequest). Product has not specified whether mandate should be stored; this cluster wires mandate->delta only into the live optimize path (equilibrium + solve_bl_utility). Persistence is left for a future task.
- T2F-2 intentionally drops the legacy _MANDATE_ALIASES rewrite ('aggressive' -> 'growth', PR-BE-7, sunset 2026-10-30) from mandate_risk_aversion.py. The port maps BOTH 'aggressive' and 'growth' directly to 1.5, so the numeric result is identical and no test changes; if the legacy deprecation-logging behaviour is ever required in the Light it must be re-added explicitly (but the Light optimizer is pure/log-free by contract, so this is unlikely).

### T2G
- Risk-free rate source for the Sharpe statistic: the legacy default is 0.04 (annualized). The light repo has no central rf constant in app/core/config.py. Task T2G-3 hardcodes the 0.04 default in MonteCarloRequest with an optional override field; if the product wants a single source of truth, a settings field (e.g. Settings.default_risk_free_rate) should be added separately and the schema default sourced from it.
- Percentile-rank semantics: the legacy historical_percentile_rank is computed ONLY for max_drawdown and return (not sharpe). This plan preserves that behavior (rank is null for sharpe). Confirm product wants the rank omitted (null) for the sharpe statistic rather than computed.
- Single-ticker scope: the Monte Carlo route operates on a SINGLE ticker (a fund/instrument NAV) using the same DB-warm + read helpers as app/services/statistics.py (ensure_eod_or_http_error, _select_date_bounds, _select_adj_close_rows, build_adj_close_series, simple_returns). The cluster brief said 'over a daily-return array' (single series), which this satisfies. If the product later wants Monte Carlo over an ad-hoc multi-position portfolio NAV, run_monte_carlo must assemble portfolio_returns first (separate task).

