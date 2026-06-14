# Quant Port -- Tier 3 -- Fact-sheet, sistemico e avancado (conforme demanda) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Cobrir o backlog: pacote de fact-sheet (rolling-returns, benchmark composto, ratios eVestment), classificacao style-box, K-selection do IPCA, manager_score, enriquecimento de peers, painel tail-VaR, servico de correlation-regime/contagio + pacote RMT, hardening do solver e os itens avancados de BL/CVaR; mais dois spikes grandes (TAA por regime e track de fatores fundamental) que exigem novo substrato de dados.

**Architecture:** Mistura de funcoes puras de fact-sheet, readers sobre tabelas ja materializadas, extensoes SOCP do otimizador e -- para os dois itens LARGE -- tasks de spike/decisao que enumeram pre-requisitos de dados e decisoes de produto em vez de codigo fabricado.

**Tech Stack:** Python 3.12, numpy, pandas, cvxpy (+SCS, SOCP), scipy.stats (adicionar como dep), FastAPI, SQLAlchemy async.

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

- **T3A** (5 tasks) -- #22 Rolling annualized returns, #23 Benchmark composto multi-bloco, #32 Ratios eVestment (Sterling/Omega/Treynor/Jensen), #42 Up/down proficiency + R2
- **T3B** (3 tasks) -- #24 Style-box 9-box, #25 IPCA K-selection (worker), #38 Gamma drift monitor (worker)
- **T3C** (3 tasks) -- #26 manager_score equity-only, #27 Enriquecimento do peer ranking
- **T3D** (3 tasks) -- #28 Drift 2-tier + downside/semi-deviation, #29 Normalizacao de expense ratio
- **T3E** (2 tasks) -- #30 Tail-VaR panel (CF mVaR/ETR/Rachev/JB), #31 CVaR parametrico + EVT POT-GPD live
- **T3F** (8 tasks) -- #33 LW constant-correlation + Marchenko-Pastur denoise, #34 Correlation-regime/contagio, #35 Robusto/vol-target SOCP, #36 SCS fallback + verificacao pos-solve (standalone), #44 Marchenko-Pastur + absorption (RMT pack)
- **T3G** (7 tasks) -- #37 CVaR limit ajustado a regime, #39 CVaR annualization + verificador realizado, #40 PSD eigenvalue repair, #41 Governanca de breach CVaR, #43 BL Woodbury/full-Omega, #45 TAA regime bands (LARGE - spike), #46 Track de fatores fundamental (LARGE - spike)

---

## Tier 3 — Fact-sheet pack: rolling annualized returns, composite multi-block benchmark, eVestment ratios (Sterling/Omega/Treynor/Jensen), up/down proficiency + R²

This cluster ports four legacy fact-sheet algorithms into the LIGHT analytics layer, re-expressed in the light idiom (pandas `Series`, decimal-fraction scale contract, fail-loud `ValueError`, `reject_nan` guards). Every function is a PURE analytics primitive in `backend/app/analytics/*.py`, unit-tested directly on synthetic pandas frames — no I/O, no DB, no FastAPI. Gate G5 is respected: NO function consumes a sample mean as an expected-return input; the geometric-mean / proficiency / regression metrics are descriptive fact-sheet statistics, not optimizer μ inputs.

Scope note (see `open_questions`): the brief mentioned a data-lake `benchmark_nav` source and a fact-sheet HTTP endpoint. Re-verified during this hardening pass: neither the source table nor an `AllocationBlock` model exists in the light repo (`grep -ri benchmark_nav backend/` → 0 hits; `grep -ri AllocationBlock backend/` → 0 hits). The composite-benchmark synthesizer is therefore delivered as a pure function that consumes already-resolved per-block return Series; the DB orchestrator + route are deferred pending a product/data decision and are recorded in `open_questions`, not stubbed here (stubbing would violate the no-placeholder contract).

Legacy sources read during this pass (line numbers verified):
- `quant_engine/rolling_service.py::compute_rolling_returns` (lines 42-88) → T3A-1.
- `quant_engine/return_statistics_service.py::_to_monthly_returns` (lines 136-151) → T3A-2.
- `quant_engine/benchmark_composite_service.py::compute_composite_nav` (lines 35-172) → T3A-3.
- `quant_engine/return_statistics_service.py::_compute_sterling_ratio` (182-226), `_compute_omega_ratio` (229-243), `_annualize_monthly` (154-156), and the absolute/risk-adjusted/relative block of `compute_return_statistics` (246-357) → T3A-4 and T3A-5.

Light targets confirmed present: `app/analytics/rolling.py` (ends line 88 with `rolling_correlation`; has `_validate_window` at lines 21-27, `rolling_volatility`/`rolling_beta`/`rolling_correlation`), `app/analytics/returns.py` (ends line 78 with `align_returns`; `reject_nan` imported at line 9), `app/analytics/risk.py` (`beta` lines 170-190, `correlation` lines 193-213, `max_drawdown` lines 117-142 returning a `DrawdownResult` dataclass with `.depth`), `app/analytics/__init__.py` (imports lines 8-45, `__all__` lines 47-77).

Dependency order: **T3A-1** (rolling returns, standalone) → **T3A-2** (daily→monthly aggregator primitive) → **T3A-3** (composite benchmark, standalone) → **T3A-4** (eVestment absolute + risk-adjusted ratios, depends on T3A-2) → **T3A-5** (proficiency + R², depends on T3A-2 and the existing `correlation`).

---

### Task T3A-1: Rolling annualized total-return series (1M/3M/6M/1Y)

Ports `quant_engine/rolling_service.py::compute_rolling_returns` (legacy lines 42-88) into `app/analytics/rolling.py`, re-expressed as a `pd.Series` returner that matches the existing `rolling_volatility`/`rolling_beta` idiom (leading-NaN `min_periods=window`, decimal fractions, `_validate_window` guard at lines 21-27). The legacy annualization is `cum ** (252 / window) - 1` per window (legacy line 78); we keep that formula but make `periods_per_year` a parameter.

**Files:**
- Modify: `backend/app/analytics/rolling.py` (add `rolling_annualized_return`; the file currently ends at line 88 with `rolling_correlation`)
- Modify: `backend/app/analytics/__init__.py` (rolling import block lines 41-45; `__all__` lines 47-77)
- Test: `backend/tests/test_analytics_rolling.py` (append; file currently ends at line 98; pre-existing helpers `WINDOW = 10` and `_random_returns(n=60, seed=11)` at lines 16-24)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_rolling.py`:
```python
def test_rolling_annualized_return_leading_nans_and_value() -> None:
    """First window-1 values are NaN; the value at index window-1 equals the
    annualized compounding of the first window slice: (prod(1+r))**(252/w)-1."""
    returns = _random_returns()
    result = rolling_annualized_return(returns, window=WINDOW)
    assert len(result) == len(returns)
    assert result.index.equals(returns.index)
    assert result.iloc[: WINDOW - 1].isna().all()
    first = returns.iloc[:WINDOW]
    expected = float((1.0 + first).prod()) ** (252 / WINDOW) - 1.0
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)
    assert not result.iloc[WINDOW - 1 :].isna().any()


def test_rolling_annualized_return_periods_per_year_param() -> None:
    """A non-default periods_per_year changes the annualization exponent."""
    returns = _random_returns()
    result = rolling_annualized_return(returns, window=WINDOW, periods_per_year=12)
    first = returns.iloc[:WINDOW]
    expected = float((1.0 + first).prod()) ** (12 / WINDOW) - 1.0
    assert result.iloc[WINDOW - 1] == pytest.approx(expected, abs=1e-12)


def test_rolling_annualized_return_window_too_small_raises() -> None:
    returns = _random_returns()
    with pytest.raises(ValueError, match="window >= 2"):
        rolling_annualized_return(returns, window=1)


def test_rolling_annualized_return_input_shorter_than_window_raises() -> None:
    returns = _random_returns(5)
    with pytest.raises(ValueError, match="at least window"):
        rolling_annualized_return(returns, window=WINDOW)
```
  Also extend the import at the top of the file (currently lines 7-14) to include `rolling_annualized_return`:
```python
from app.analytics import (
    annualized_volatility,
    beta,
    correlation,
    rolling_annualized_return,
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_rolling.py::test_rolling_annualized_return_leading_nans_and_value -v`. Expected failure: `ImportError: cannot import name 'rolling_annualized_return' from 'app.analytics'` (function not yet defined/exported).

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/rolling.py` (after `rolling_correlation`, which ends at line 88; `np` is already imported at line 15, `pd` at line 16, `_validate_window` at lines 21-27):
```python
def rolling_annualized_return(
    returns: pd.Series, window: int = 63, periods_per_year: int = 252
) -> pd.Series:
    """Rolling annualized total return (decimal fraction, 0.05 = 5%).

    For each trailing window of ``window`` daily returns, compounds them
    (``prod(1 + r)``) and annualizes by raising to ``periods_per_year / window``
    minus 1 — the legacy fact-sheet convention
    (``quant_engine/rolling_service.py`` line 78). Uses ``min_periods=window``
    so the first ``window - 1`` values are NaN by construction; an upstream
    filter is expected to drop the leading NaNs before serving. Inputs and
    result are decimal fractions (0.05 = 5%), never 0-100.

    Standard institutional windows (caller-chosen): 21 (1M), 63 (3M),
    126 (6M), 252 (1Y).

    Raises:
        ValueError: if ``window < 2`` or ``len(returns) < window``.
    """
    _validate_window(window, len(returns), "rolling_annualized_return")
    growth = (1.0 + returns).rolling(window, min_periods=window).apply(
        np.prod, raw=True
    )
    return growth ** (periods_per_year / window) - 1.0
```
  Then update `backend/app/analytics/__init__.py` — replace the `from app.analytics.rolling import (...)` block (lines 41-45) with:
```python
from app.analytics.rolling import (
    rolling_annualized_return,
    rolling_beta,
    rolling_correlation,
    rolling_volatility,
)
```
  and insert `"rolling_annualized_return",` into `__all__` immediately before the existing `"rolling_beta",` entry (currently line 70), preserving alphabetical order.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_rolling.py -v`. Expected: 11 tests pass (the 4 new ones plus the 7 pre-existing). Also run `cd backend && python -c "import app.analytics as a; print(a.rolling_annualized_return)"` to confirm the export resolves.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/rolling.py app/analytics/__init__.py tests/test_analytics_rolling.py` then:
```
git commit -m "feat(analytics): rolling annualized total-return series (1M/3M/6M/1Y)

Port rolling_service.compute_rolling_returns into rolling.py as a pandas
Series returner (min_periods=window, decimal-fraction contract), matching
the rolling_volatility/beta idiom. Fact-sheet pack rank 22.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T3A-2: daily→monthly geometric aggregator primitive

Ports `quant_engine/return_statistics_service.py::_to_monthly_returns` (legacy lines 136-151) into `app/analytics/returns.py` as a public primitive. It groups daily returns into fixed 21-trading-day END-ANCHORED blocks (dropping the oldest `len % 21` days so the most recent/as-of observations are preserved) and geometrically compounds each block. This primitive is the shared input for every monthly-frequency eVestment ratio in T3A-4 and T3A-5. (Aggregation approximation flagged in `open_questions`.) Note: the legacy returns a bare numpy array; the light version returns a date-indexed `pd.Series` (indexed by each block's LAST date) so it can be aligned with other monthly series via `align_returns`.

**Files:**
- Modify: `backend/app/analytics/returns.py` (add `to_monthly_returns` + `TRADING_DAYS_PER_MONTH`; file currently ends at line 78 with `align_returns`; `reject_nan` imported at line 9, `pd` at line 7)
- Modify: `backend/app/analytics/__init__.py` (returns import block lines 21-26; `__all__` lines 47-77)
- Test: `backend/tests/test_analytics_returns.py` (append; file currently ends at line 94; pre-existing helper `_dated(values, start="2024-01-01")` at lines 15-16)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_returns.py`:
```python
def test_to_monthly_returns_compounds_21_day_blocks() -> None:
    """Each 21-day block is geometrically compounded; exactly len//21 months."""
    rng = np.random.default_rng(7)
    daily = _dated(list(rng.normal(0.0004, 0.01, 63)))  # exactly 3 months
    monthly = to_monthly_returns(daily)
    assert len(monthly) == 3
    arr = daily.to_numpy(dtype=float)
    for k in range(3):
        block = arr[k * 21 : (k + 1) * 21]
        assert monthly.iloc[k] == pytest.approx(float((1.0 + block).prod() - 1.0), abs=1e-12)


def test_to_monthly_returns_end_anchored_drops_oldest_remainder() -> None:
    """len % 21 != 0 drops the OLDEST days; the last month is the final 21 days."""
    rng = np.random.default_rng(8)
    daily = _dated(list(rng.normal(0.0004, 0.01, 50)))  # 50 -> 2 months, drops 8 oldest
    monthly = to_monthly_returns(daily)
    assert len(monthly) == 2
    arr = daily.to_numpy(dtype=float)
    last_block = arr[-21:]
    assert monthly.iloc[-1] == pytest.approx(float((1.0 + last_block).prod() - 1.0), abs=1e-12)
    # Last month is indexed by the last date of the series (as-of date).
    assert monthly.index[-1] == daily.index[-1]


def test_to_monthly_returns_too_few_days_raises() -> None:
    with pytest.raises(ValueError, match="at least 21"):
        to_monthly_returns(_dated([0.01] * 20))


def test_to_monthly_returns_nan_raises() -> None:
    daily = _dated([0.01] * 21 + [float("nan")] * 21)
    with pytest.raises(ValueError, match="NaN"):
        to_monthly_returns(daily)
```
  Add `to_monthly_returns` to the import block at the top of the file (currently lines 7-12):
```python
from app.analytics import (
    align_returns,
    cumulative_return_series,
    simple_returns,
    to_monthly_returns,
    total_return,
)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_returns.py::test_to_monthly_returns_compounds_21_day_blocks -v`. Expected failure: `ImportError: cannot import name 'to_monthly_returns' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/returns.py` (after `align_returns`, line 78; `reject_nan` is already imported at line 9, `pd` at line 7, and add `import numpy as np` at the top of the file alongside the `pandas` import — there is currently no numpy import in returns.py):
```python
import numpy as np  # add near the top, beside `import pandas as pd`

TRADING_DAYS_PER_MONTH = 21


def to_monthly_returns(daily_returns: pd.Series) -> pd.Series:
    """Aggregate daily returns into monthly geometric returns.

    Groups by fixed 21-trading-day blocks anchored to the END of the series so
    the most recent (as-of-date) observations are always preserved; the oldest
    ``len % 21`` returns are dropped when the length is not a multiple of 21.
    Each block is geometrically compounded: ``prod(1 + r) - 1``. This mirrors
    the legacy fact-sheet aggregator (``return_statistics_service`` lines
    136-151); calendar months are approximated as 21 trading days. Inputs and
    result are decimal fractions (0.05 = 5%), never 0-100.

    The returned series is indexed by the LAST date of each block (the
    as-of date for that month), so it can be aligned with other monthly series
    via :func:`align_returns`.

    Raises:
        ValueError: if fewer than 21 returns are supplied or the input
            contains NaN/infinite values.
    """
    if len(daily_returns) < TRADING_DAYS_PER_MONTH:
        raise ValueError(
            f"to_monthly_returns requires at least {TRADING_DAYS_PER_MONTH} "
            f"returns, got {len(daily_returns)}"
        )
    reject_nan(daily_returns, "to_monthly_returns")
    n_months = len(daily_returns) // TRADING_DAYS_PER_MONTH
    trimmed = daily_returns.iloc[-n_months * TRADING_DAYS_PER_MONTH :]
    values = trimmed.to_numpy(dtype=float).reshape(n_months, TRADING_DAYS_PER_MONTH)
    monthly = np.prod(1.0 + values, axis=1) - 1.0
    block_end_dates = trimmed.index[TRADING_DAYS_PER_MONTH - 1 :: TRADING_DAYS_PER_MONTH]
    return pd.Series(monthly, index=block_end_dates)
```
  Update `backend/app/analytics/__init__.py` — add `to_monthly_returns` to the `from app.analytics.returns import (...)` block (currently lines 21-26, alphabetically before `total_return`) and insert `"to_monthly_returns",` into `__all__` immediately before the existing `"total_return",` entry (currently line 74).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_returns.py -v`. Expected: 15 tests pass (4 new + 11 pre-existing).

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/returns.py app/analytics/__init__.py tests/test_analytics_returns.py` then:
```
git commit -m "feat(analytics): daily->monthly geometric aggregator primitive

Port return_statistics_service._to_monthly_returns into returns.py as a
public pandas primitive (21-day end-anchored blocks, geometric compounding,
date-indexed by block-end date). Shared input for the eVestment monthly
ratios. Fact-sheet pack.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T3A-3: Composite multi-block benchmark NAV synthesizer

Ports `quant_engine/benchmark_composite_service.py::compute_composite_nav` (legacy lines 35-172) into a new `app/analytics/benchmark_composite.py`. Re-expressed in the light idiom: inputs are per-block `pd.Series` of daily returns (decimal fractions), output is a single composite NAV `pd.Series` in currency units. Keeps the legacy guards verbatim in semantics: weight-sum must be ~1.0 within 1e-4 (fail loud `ValueError`, legacy lines 69-74), latest-common-inception start (legacy lines 76-105), per-day renormalization with a 50% active-weight floor (legacy lines 127-162; days below the floor are skipped). Pure function, no I/O, no logging dependency (legacy `structlog` calls at lines 85, 99, 146, 155 are dropped — light analytics never log). Verified during this hardening pass against all six tests below (all pass against this implementation).

**Files:**
- Create: `backend/app/analytics/benchmark_composite.py`
- Modify: `backend/app/analytics/__init__.py` (add import after the `distribution` import at line 8; add to `__all__`)
- Test: `backend/tests/test_analytics_benchmark_composite.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_benchmark_composite.py`:
```python
"""Tests for app.analytics.benchmark_composite."""

import pandas as pd
import pytest

from app.analytics import composite_benchmark_nav


def _series(values: list[float], start: str = "2024-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def test_composite_two_equal_blocks_compounds_weighted_returns() -> None:
    """50/50 composite return each day is the weighted mean of block returns;
    NAV compounds from inception_nav."""
    a = _series([0.01, 0.02, -0.01])
    b = _series([0.03, 0.00, 0.01])
    nav = composite_benchmark_nav({"A": 0.5, "B": 0.5}, {"A": a, "B": b}, inception_nav=1000.0)
    assert list(nav.index) == list(a.index)
    expected_returns = [0.5 * 0.01 + 0.5 * 0.03, 0.5 * 0.02 + 0.5 * 0.00, 0.5 * -0.01 + 0.5 * 0.01]
    cur = 1000.0
    for i, r in enumerate(expected_returns):
        cur *= 1.0 + r
        assert nav.iloc[i] == pytest.approx(cur, abs=1e-9)


def test_composite_weights_must_sum_to_one() -> None:
    a = _series([0.01, 0.02])
    b = _series([0.03, 0.00])
    with pytest.raises(ValueError, match="sum to 1.0"):
        composite_benchmark_nav({"A": 0.5, "B": 0.4}, {"A": a, "B": b})


def test_composite_latest_common_inception() -> None:
    """The composite starts at the latest inception across blocks (block B
    starts 2 business days later -> composite has 3 points, not 5)."""
    a = _series([0.01, 0.02, 0.03, 0.01, 0.02], start="2024-01-01")
    b = _series([0.00, 0.01, 0.02], start="2024-01-03")  # 2 B-days later
    nav = composite_benchmark_nav({"A": 0.5, "B": 0.5}, {"A": a, "B": b})
    assert len(nav) == 3
    assert nav.index[0] == b.index[0]


def test_composite_day_below_active_floor_is_skipped() -> None:
    """A day where only a 0.3-weight block is present (< 50% floor) is dropped
    (no forward-fill amplification). Block B (0.7 weight) is missing the middle
    date, so the middle day carries only A's 0.3 weight and is skipped."""
    idx = pd.date_range("2024-01-01", periods=3, freq="B")
    a = pd.Series([0.01, 0.02, 0.03], index=idx)
    b = pd.Series([0.05, 0.06], index=idx[[0, 2]])  # missing the middle date
    nav = composite_benchmark_nav({"A": 0.3, "B": 0.7}, {"A": a, "B": b})
    assert len(nav) == 2
    assert idx[1] not in nav.index


def test_composite_renormalizes_above_floor() -> None:
    """A day with >=50% active weight renormalizes the partial composite up to
    full weight."""
    idx = pd.date_range("2024-01-01", periods=2, freq="B")
    a = pd.Series([0.01, 0.02], index=idx)
    b = pd.Series([0.05], index=idx[[0]])  # missing the 2nd date
    nav = composite_benchmark_nav({"A": 0.7, "B": 0.3}, {"A": a, "B": b}, inception_nav=1000.0)
    # Day 1: full -> 0.7*0.01 + 0.3*0.05 = 0.022
    # Day 2: only A (0.7 >= 0.5 floor) -> renormalize 0.7*0.02 * (1.0/0.7) = 0.02
    assert nav.iloc[0] == pytest.approx(1000.0 * 1.022, abs=1e-9)
    assert nav.iloc[1] == pytest.approx(1000.0 * 1.022 * 1.02, abs=1e-9)


def test_composite_empty_inputs_raise() -> None:
    with pytest.raises(ValueError, match="at least one block"):
        composite_benchmark_nav({}, {})
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_benchmark_composite.py::test_composite_two_equal_blocks_compounds_weighted_returns -v`. Expected failure: `ImportError: cannot import name 'composite_benchmark_nav' from 'app.analytics'` (module/function not yet created).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/benchmark_composite.py`:
```python
"""Composite multi-block benchmark NAV synthesizer.

Ports quant_engine/benchmark_composite_service.compute_composite_nav into the
light analytics idiom. Each block contributes a daily benchmark-return series;
the composite NAV is the weighted-return compounding across blocks.

Pure sync, no I/O, no logging — the legacy structlog telemetry is dropped
(light analytics never log; callers decide on observability).

Algorithm:
    NAV_0 = inception_nav
    R_t   = Σ(w_block × r_block_t)   over blocks present at t (renormalized)
    NAV_t = NAV_{t-1} × (1 + R_t)

Scale contract: block returns are decimal fractions (0.05 = 5%); the NAV is in
currency units.
"""

from collections.abc import Mapping

import pandas as pd

# Weights below this fraction of total weight on a given day are treated as
# insufficient coverage: the day is skipped rather than forward-fill amplified.
_ACTIVE_WEIGHT_FLOOR = 0.5
_WEIGHT_SUM_TOL = 1e-4
_RENORM_THRESHOLD = 0.999  # below this fraction of weight_sum, renormalize


def composite_benchmark_nav(
    block_weights: Mapping[str, float],
    block_returns: Mapping[str, pd.Series],
    inception_nav: float = 1000.0,
) -> pd.Series:
    """Composite benchmark NAV from block-weighted daily benchmark returns.

    Parameters
    ----------
    block_weights : Mapping[str, float]
        block_id -> target weight; must sum to 1.0 within 1e-4 (a composite
        benchmark is by definition a unit allocation).
    block_returns : Mapping[str, pd.Series]
        block_id -> date-indexed daily benchmark returns (decimal fractions).
    inception_nav : float
        Starting NAV value (default 1000.0, currency units).

    Returns
    -------
    pd.Series
        Composite NAV indexed by date ascending, starting at the latest common
        inception date across all weighted blocks.

    Raises:
        ValueError: if inputs are empty, weights do not sum to 1.0 (within
            1e-4), or a weighted block has no return data.
    """
    if not block_weights or not block_returns:
        raise ValueError("composite_benchmark_nav requires at least one block")

    weight_sum = sum(block_weights.values())
    if abs(weight_sum - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"block_weights must sum to 1.0 (within {_WEIGHT_SUM_TOL}); "
            f"got {weight_sum:.6f}. A composite benchmark is a unit allocation; "
            "caller must normalize or correct the input."
        )

    # Every weighted block must have return data; otherwise the composite is
    # undefined (a fixed-weight composite cannot exist before all constituents).
    block_min_dates: dict[str, pd.Timestamp] = {}
    for block_id in block_weights:
        series = block_returns.get(block_id)
        if series is None or series.dropna().empty:
            raise ValueError(
                f"composite block '{block_id}' has no return data; "
                "composite benchmark is undefined."
            )
        block_min_dates[block_id] = series.dropna().index.min()

    latest_inception = max(block_min_dates.values())

    # Wide frame of block returns, restricted to weighted blocks and dates
    # >= the latest common inception.
    frame = pd.DataFrame({bid: block_returns[bid] for bid in block_weights})
    frame = frame.loc[frame.index >= latest_inception].sort_index()

    navs: list[float] = []
    out_index: list[pd.Timestamp] = []
    current = inception_nav

    for date, row in frame.iterrows():
        composite_return = 0.0
        active_weight = 0.0
        for block_id, w in block_weights.items():
            r = row[block_id]
            if pd.notna(r):
                composite_return += w * float(r)
                active_weight += w

        if active_weight <= 0.0:
            continue

        # Renormalize partial-coverage days; skip days below the active floor.
        if active_weight < weight_sum * _RENORM_THRESHOLD:
            if active_weight < weight_sum * _ACTIVE_WEIGHT_FLOOR:
                continue
            composite_return = composite_return * (weight_sum / active_weight)

        current = current * (1.0 + composite_return)
        navs.append(current)
        out_index.append(date)

    return pd.Series(navs, index=pd.Index(out_index))
```
  Update `backend/app/analytics/__init__.py` — add the import immediately after the `distribution` import (currently line 8 `from app.analytics.distribution import Histogram, return_histogram`), before the `portfolio` import block:
```python
from app.analytics.benchmark_composite import composite_benchmark_nav
```
  and insert `"composite_benchmark_nav",` into `__all__` immediately after the existing `"best_worst_day",` entry (currently line 56), preserving alphabetical order.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_benchmark_composite.py -v`. Expected: all 6 tests pass.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/benchmark_composite.py app/analytics/__init__.py tests/test_analytics_benchmark_composite.py` then:
```
git commit -m "feat(analytics): composite multi-block benchmark NAV synthesizer

Port benchmark_composite_service.compute_composite_nav into analytics as a
pure pandas function: weight-sum=1.0 guard, latest-common-inception start,
per-day renormalization with 50% active-weight floor. Fact-sheet pack rank 23.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T3A-4: eVestment absolute + risk-adjusted ratios (geometric mean, Sterling, Omega, Treynor, Jensen)

Ports the absolute-return / risk-adjusted half of `quant_engine/return_statistics_service.py::compute_return_statistics` (geometric mean at legacy line 279, Treynor/Jensen at legacy lines 320-328) plus its private helpers (`_compute_sterling_ratio` lines 182-226, `_compute_omega_ratio` lines 229-243, `_annualize_monthly` lines 154-156) into a new `app/analytics/return_statistics.py`. Each ratio is its own fail-loud pure function so they can be unit-tested in isolation; a `ReturnStatistics` dataclass assembles them. Monthly metrics consume `to_monthly_returns` (T3A-2). Sterling reuses the existing `max_drawdown` (`app/analytics/risk.py` lines 117-142, returns a `DrawdownResult` whose `.depth` is the negative drawdown) on yearly NAV chunks — verified numerically identical to the legacy `compute_drawdown_series`/`np.min` during this hardening pass. Treynor/Jensen consume a benchmark and reuse `beta` (`app/analytics/risk.py` lines 170-190). This task covers the absolute + risk-adjusted block; proficiency + R² are T3A-5.

**Files:**
- Create: `backend/app/analytics/return_statistics.py`
- Modify: `backend/app/analytics/__init__.py` (export the new functions + `ReturnStatistics`)
- Test: `backend/tests/test_analytics_return_statistics.py` (new)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_return_statistics.py`:
```python
"""Tests for app.analytics.return_statistics (eVestment ratios)."""

import numpy as np
import pandas as pd
import pytest

from app.analytics import (
    geometric_mean_monthly,
    jensen_alpha,
    omega_ratio,
    sterling_ratio,
    treynor_ratio,
)


def _daily(n: int, seed: int, mu: float = 0.0005, sigma: float = 0.01) -> pd.Series:
    rng = np.random.default_rng(seed)
    return pd.Series(
        rng.normal(mu, sigma, n),
        index=pd.date_range("2020-01-01", periods=n, freq="B"),
    )


def test_geometric_mean_monthly_matches_formula() -> None:
    daily = _daily(252, seed=1)
    from app.analytics import to_monthly_returns

    monthly = to_monthly_returns(daily)
    expected = float(np.prod(1.0 + monthly.to_numpy()) ** (1.0 / len(monthly)) - 1.0)
    assert geometric_mean_monthly(daily) == pytest.approx(expected, abs=1e-12)


def test_omega_ratio_gains_over_losses() -> None:
    """Omega = sum(max(r-MAR,0)) / sum(|min(r-MAR,0)|) on monthly returns."""
    daily = _daily(252, seed=2)
    from app.analytics import to_monthly_returns

    monthly = to_monthly_returns(daily).to_numpy()
    gains = float(np.sum(np.maximum(monthly, 0.0)))
    losses = float(np.sum(np.abs(np.minimum(monthly, 0.0))))
    assert omega_ratio(daily, mar=0.0) == pytest.approx(gains / losses, abs=1e-9)


def test_omega_ratio_all_gains_raises() -> None:
    daily = pd.Series([0.01] * 42, index=pd.date_range("2020-01-01", periods=42, freq="B"))
    with pytest.raises(ValueError, match="no downside"):
        omega_ratio(daily)


def test_sterling_ratio_kestner_denominator() -> None:
    """Sterling = ann_return / |avg_yearly_max_dd - 0.10|; denominator uses the
    additive 10% cushion (Kestner)."""
    daily = _daily(504, seed=3)  # 2 years
    val = sterling_ratio(daily)
    # Reconstruct expected: geometric annualized return over full sample.
    arr = daily.to_numpy(dtype=float)
    ann = float(np.prod(1.0 + arr) ** (252 / len(arr)) - 1.0)
    # Yearly max DDs on the two 252-day NAV chunks (end-anchored).
    n_years = len(arr) // 252
    trimmed = arr[-n_years * 252 :]
    dds = []
    for k in range(n_years):
        chunk = trimmed[k * 252 : (k + 1) * 252]
        navs = np.concatenate([[1.0], np.cumprod(1.0 + chunk)])
        run_max = np.maximum.accumulate(navs)
        dds.append(float(np.min(navs / run_max - 1.0)))
    denom = abs(float(np.mean(dds)) - 0.10)
    assert val == pytest.approx(ann / denom, abs=1e-9)


def test_sterling_ratio_requires_one_year() -> None:
    daily = _daily(200, seed=4)
    with pytest.raises(ValueError, match="at least 252"):
        sterling_ratio(daily)


def test_treynor_and_jensen_against_regression() -> None:
    """Treynor = (ann_return - rf) / beta_monthly; Jensen = annualized monthly
    alpha. Cross-checked against a direct monthly covariance/var beta."""
    daily = _daily(504, seed=5)
    bench = _daily(504, seed=6)
    from app.analytics import to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    rv = r.to_numpy()[:n]
    bv = bm.to_numpy()[:n]
    beta_m = float(np.cov(rv, bv, ddof=1)[0, 1] / np.var(bv, ddof=1))
    geom = float(np.prod(1.0 + rv) ** (1.0 / n) - 1.0)
    ann_return = (1.0 + geom) ** 12 - 1.0
    rf = 0.04
    assert treynor_ratio(daily, bench, risk_free_rate=rf) == pytest.approx(
        (ann_return - rf) / beta_m, abs=1e-6
    )
    rf_monthly = rf / 12.0
    monthly_alpha = float(np.mean(rv) - rf_monthly - beta_m * (np.mean(bv) - rf_monthly))
    assert jensen_alpha(daily, bench, risk_free_rate=rf) == pytest.approx(
        monthly_alpha * 12.0, abs=1e-8
    )


def test_treynor_requires_min_months() -> None:
    daily = _daily(210, seed=7)   # 10 months (210 // 21)
    bench = _daily(210, seed=8)
    with pytest.raises(ValueError, match="at least 12"):
        treynor_ratio(daily, bench)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_return_statistics.py::test_geometric_mean_monthly_matches_formula -v`. Expected failure: `ImportError: cannot import name 'geometric_mean_monthly' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/return_statistics.py`. Note `_beta_monthly` returns the aligned monthly arrays AND beta because Treynor/Jensen both need them; the count guard (`< 12`) is checked before `beta()` so the `>= 12 common months` failure is raised with the expected message:
```python
"""eVestment risk/return ratios for the fact-sheet pack.

Ports the absolute-return and risk-adjusted half of
quant_engine/return_statistics_service.compute_return_statistics into the light
analytics idiom: each ratio is a fail-loud pure function over a daily-return
pd.Series (decimal fractions), aggregated to monthly via to_monthly_returns.

Conventions (pinned to legacy parity):
- monthly returns: fixed 21-day end-anchored blocks (see to_monthly_returns);
- geometric annualization: (1 + monthly_geo_mean)**12 - 1 (legacy _annualize_monthly);
- Sterling denominator: |avg_yearly_max_dd - 0.10| (Kestner additive cushion);
- Omega: sum(max(r-MAR,0)) / sum(|min(r-MAR,0)|) on monthly returns;
- Treynor: (ann_geo_return - rf) / beta_monthly;
- Jensen: 12 * (mean(r) - rf/12 - beta*(mean(bm) - rf/12)).

Scale contract: returns are decimal fractions (0.05 = 5%). rf is an ANNUAL rate.
Gate G5: none of these consume a sample mean as an optimizer expected-return
input; they are descriptive fact-sheet statistics.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.analytics.returns import align_returns, to_monthly_returns
from app.analytics.risk import beta, max_drawdown

_MIN_DAYS_ONE_YEAR = 252
_MIN_MONTHS_REGRESSION = 12
DEFAULT_RISK_FREE_RATE = 0.04
_MONTHS_PER_YEAR = 12


def geometric_mean_monthly(daily_returns: pd.Series) -> float:
    """Geometric mean of the monthly return series (decimal fraction).

    ``prod(1 + monthly)**(1/n) - 1`` over the 21-day end-anchored months.

    Raises:
        ValueError: if fewer than 21 daily returns (no full month) or the
            input contains NaN values.
    """
    monthly = to_monthly_returns(daily_returns)
    return float(np.prod(1.0 + monthly.to_numpy(dtype=float)) ** (1.0 / len(monthly)) - 1.0)


def omega_ratio(daily_returns: pd.Series, mar: float = 0.0) -> float:
    """Omega ratio at a monthly minimum-acceptable-return threshold.

    ``sum(max(r - MAR, 0)) / sum(|min(r - MAR, 0)|)`` over monthly returns.

    Raises:
        ValueError: if fewer than 21 daily returns, NaN input, or there is no
            downside below MAR (denominator zero — Omega undefined).
    """
    monthly = to_monthly_returns(daily_returns).to_numpy(dtype=float)
    gains = float(np.sum(np.maximum(monthly - mar, 0.0)))
    losses = float(np.sum(np.abs(np.minimum(monthly - mar, 0.0))))
    if losses < 1e-12:
        raise ValueError("omega_ratio is undefined: no downside below MAR")
    return gains / losses


def sterling_ratio(daily_returns: pd.Series) -> float:
    """Sterling ratio = ann_geo_return / |avg_yearly_max_dd - 0.10|.

    Splits the daily series into 252-day yearly chunks anchored to the END,
    averages each chunk's max drawdown (via :func:`max_drawdown` on the chunk
    NAV), and applies the Kestner additive 10% cushion to the denominator.
    ``avg_max_dd`` is negative, so the subtraction increases the denominator.

    Raises:
        ValueError: if fewer than 252 daily returns, NaN/infinite input, or the
            denominator collapses to <= 0.
    """
    if len(daily_returns) < _MIN_DAYS_ONE_YEAR:
        raise ValueError(
            f"sterling_ratio requires at least {_MIN_DAYS_ONE_YEAR} daily "
            f"returns, got {len(daily_returns)}"
        )
    arr = daily_returns.to_numpy(dtype=float)
    if not np.isfinite(arr).all():
        raise ValueError("sterling_ratio received NaN or infinite values in input")

    n = len(arr)
    ann_return = float(np.prod(1.0 + arr) ** (_MIN_DAYS_ONE_YEAR / n) - 1.0)

    n_years = n // _MIN_DAYS_ONE_YEAR
    trimmed = arr[-n_years * _MIN_DAYS_ONE_YEAR :]
    yearly_max_dds: list[float] = []
    for k in range(n_years):
        chunk = trimmed[k * _MIN_DAYS_ONE_YEAR : (k + 1) * _MIN_DAYS_ONE_YEAR]
        navs = pd.Series(np.concatenate([[1.0], np.cumprod(1.0 + chunk)]))
        yearly_max_dds.append(max_drawdown(navs).depth)

    avg_max_dd = float(np.mean(yearly_max_dds))
    denominator = abs(avg_max_dd - 0.10)
    if denominator <= 0:
        raise ValueError("sterling_ratio denominator collapsed to zero")
    return ann_return / denominator


def _beta_monthly(
    daily_returns: pd.Series, benchmark_returns: pd.Series
) -> tuple[np.ndarray, np.ndarray, float]:
    """Aligned monthly return arrays and their beta. Internal helper.

    Raises:
        ValueError: if fewer than 12 common months (regression undefined).
    """
    r = to_monthly_returns(daily_returns)
    bm = to_monthly_returns(benchmark_returns)
    ar, abm = align_returns(r, bm)
    if len(ar) < _MIN_MONTHS_REGRESSION:
        raise ValueError(
            f"requires at least {_MIN_MONTHS_REGRESSION} common months, got {len(ar)}"
        )
    return ar.to_numpy(dtype=float), abm.to_numpy(dtype=float), beta(ar, abm)


def treynor_ratio(
    daily_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Treynor ratio = (ann_geo_return - rf) / beta (monthly beta).

    Raises:
        ValueError: if fewer than 12 common months, NaN input, zero benchmark
            variance, or beta is ~0 (Treynor undefined).
    """
    rv, _bm, beta_m = _beta_monthly(daily_returns, benchmark_returns)
    if abs(beta_m) < 1e-10:
        raise ValueError("treynor_ratio is undefined: beta is ~0")
    geom = float(np.prod(1.0 + rv) ** (1.0 / len(rv)) - 1.0)
    ann_return = (1.0 + geom) ** _MONTHS_PER_YEAR - 1.0
    return (ann_return - risk_free_rate) / beta_m


def jensen_alpha(
    daily_returns: pd.Series,
    benchmark_returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
) -> float:
    """Jensen's alpha, annualized from the monthly CAPM residual.

    ``12 * (mean(r) - rf/12 - beta * (mean(bm) - rf/12))``.

    Raises:
        ValueError: if fewer than 12 common months, NaN input, or zero
            benchmark variance (beta undefined).
    """
    rv, bm, beta_m = _beta_monthly(daily_returns, benchmark_returns)
    rf_monthly = risk_free_rate / _MONTHS_PER_YEAR
    monthly_alpha = float(
        np.mean(rv) - rf_monthly - beta_m * (np.mean(bm) - rf_monthly)
    )
    return monthly_alpha * _MONTHS_PER_YEAR


@dataclass(frozen=True)
class ReturnStatistics:
    """eVestment absolute + risk-adjusted ratios (decimal fractions).

    All fields are decimal fractions or pure ratios; rf is an annual rate.
    Proficiency ratios and R-squared are added in T3A-5.
    """

    geometric_mean_monthly: float
    sterling_ratio: float
    omega_ratio: float
    treynor_ratio: float
    jensen_alpha: float
```
  Update `backend/app/analytics/__init__.py` — add a new import block immediately after the `rolling` import block (which currently ends at line 45):
```python
from app.analytics.return_statistics import (
    ReturnStatistics,
    geometric_mean_monthly,
    jensen_alpha,
    omega_ratio,
    sterling_ratio,
    treynor_ratio,
)
```
  and add to `__all__`: `"ReturnStatistics"` (after `"MIN_IN_RANGE_RETURNS"` at line 52, before the lowercase block), plus `"geometric_mean_monthly"`, `"jensen_alpha"`, `"omega_ratio"`, `"sterling_ratio"`, `"treynor_ratio"` interleaved alphabetically into the lowercase entries.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_return_statistics.py -v`. Expected: all 7 tests pass. Also confirm no import regressions: `cd backend && python -m pytest tests/test_analytics_rolling.py tests/test_analytics_returns.py -q` (expected 26 passed: 11 rolling + 15 returns).

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/return_statistics.py app/analytics/__init__.py tests/test_analytics_return_statistics.py` then:
```
git commit -m "feat(analytics): eVestment ratios (geo-mean, Sterling, Omega, Treynor, Jensen)

Port return_statistics_service absolute+risk-adjusted ratios into a new
return_statistics.py module: fail-loud pure functions over monthly returns,
reusing to_monthly_returns/beta/max_drawdown. Fact-sheet pack rank 32.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T3A-5: up/down proficiency hit-rate + R²

Ports the proficiency-ratio and R² block of `quant_engine/return_statistics_service.py::compute_return_statistics` (legacy lines 330-338 for proficiency, lines 316-318 for R²) into `app/analytics/return_statistics.py`. Up-proficiency = fraction of months (where the benchmark was UP) in which the fund beat the benchmark; down-proficiency = the same over benchmark-DOWN months. R² is the square of the existing Pearson `correlation` of the aligned monthly series (legacy used `linregress.rvalue**2`, which equals `correlation**2`). Both consume the monthly aggregator (T3A-2) and the benchmark.

IMPORTANT FIX (found during this hardening pass): proficiency must NOT route through `_beta_monthly`, because `beta()` raises "benchmark variance is 0" before the up/down-months guard can fire (a constant benchmark would surface the wrong error). A beta-free `_aligned_monthly` helper is introduced for proficiency; R² uses `correlation` directly (which has its own zero-variance guard). The legacy code likewise computes proficiency independently of beta within the same block.

**Files:**
- Modify: `backend/app/analytics/return_statistics.py` (add `_aligned_monthly`, `up_proficiency_ratio`, `down_proficiency_ratio`, `r_squared`; extend the risk import to add `correlation`)
- Modify: `backend/app/analytics/__init__.py` (export the three new functions)
- Test: `backend/tests/test_analytics_return_statistics.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_return_statistics.py`:
```python
def test_proficiency_ratios_hit_rate() -> None:
    """Up = fraction of benchmark-UP months the fund beat the benchmark;
    Down = same over benchmark-DOWN months. Both are decimal fractions in [0,1]."""
    daily = _daily(504, seed=11)
    bench = _daily(504, seed=12)
    from app.analytics import to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    rv = r.to_numpy()[:n]
    bv = bm.to_numpy()[:n]
    up_mask = bv >= 0
    down_mask = bv < 0
    exp_up = float(np.sum(rv[up_mask] > bv[up_mask]) / np.sum(up_mask))
    exp_down = float(np.sum(rv[down_mask] > bv[down_mask]) / np.sum(down_mask))
    assert up_proficiency_ratio(daily, bench) == pytest.approx(exp_up, abs=1e-9)
    assert down_proficiency_ratio(daily, bench) == pytest.approx(exp_down, abs=1e-9)
    assert 0.0 <= up_proficiency_ratio(daily, bench) <= 1.0
    assert 0.0 <= down_proficiency_ratio(daily, bench) <= 1.0


def test_r_squared_is_correlation_squared() -> None:
    daily = _daily(504, seed=13)
    bench = _daily(504, seed=14)
    from app.analytics import correlation, to_monthly_returns

    r = to_monthly_returns(daily)
    bm = to_monthly_returns(bench)
    n = min(len(r), len(bm))
    corr = correlation(r.iloc[:n], bm.iloc[:n])
    assert r_squared(daily, bench) == pytest.approx(corr**2, abs=1e-9)
    assert 0.0 <= r_squared(daily, bench) <= 1.0


def test_proficiency_requires_min_months() -> None:
    daily = _daily(210, seed=15)   # 10 months
    bench = _daily(210, seed=16)
    with pytest.raises(ValueError, match="at least 12"):
        up_proficiency_ratio(daily, bench)


def test_up_proficiency_no_up_months_raises() -> None:
    """A benchmark that is never up over the aligned months -> undefined up-ratio.
    The benchmark VARIES day to day (nonzero monthly variance) but every month
    compounds negative, so the up-months guard fires, not a variance guard."""
    idx = pd.date_range("2020-01-01", periods=12 * 21, freq="B")
    daily = pd.Series(np.full(12 * 21, 0.001), index=idx)
    rng = np.random.default_rng(99)
    bench_vals = -np.abs(rng.normal(0.002, 0.001, 12 * 21)) - 0.0005  # every day < 0
    bench = pd.Series(bench_vals, index=idx)
    with pytest.raises(ValueError, match="no benchmark-up months"):
        up_proficiency_ratio(daily, bench)
```
  Extend the top-of-file import to include the three new names:
```python
from app.analytics import (
    down_proficiency_ratio,
    geometric_mean_monthly,
    jensen_alpha,
    omega_ratio,
    r_squared,
    sterling_ratio,
    treynor_ratio,
    up_proficiency_ratio,
)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_return_statistics.py::test_proficiency_ratios_hit_rate -v`. Expected failure: `ImportError: cannot import name 'up_proficiency_ratio' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/analytics/return_statistics.py`, extend the risk import at the top to add `correlation`:
```python
from app.analytics.risk import beta, correlation, max_drawdown
```
  Then add a beta-free aligned-monthly helper and the three functions (after `jensen_alpha`, before the `ReturnStatistics` dataclass):
```python
def _aligned_monthly(
    daily_returns: pd.Series, benchmark_returns: pd.Series
) -> tuple[np.ndarray, np.ndarray]:
    """Aligned monthly return arrays (no beta). Internal helper for proficiency.

    Raises:
        ValueError: if fewer than 12 common months.
    """
    r = to_monthly_returns(daily_returns)
    bm = to_monthly_returns(benchmark_returns)
    ar, abm = align_returns(r, bm)
    if len(ar) < _MIN_MONTHS_REGRESSION:
        raise ValueError(
            f"requires at least {_MIN_MONTHS_REGRESSION} common months, got {len(ar)}"
        )
    return ar.to_numpy(dtype=float), abm.to_numpy(dtype=float)


def up_proficiency_ratio(
    daily_returns: pd.Series, benchmark_returns: pd.Series
) -> float:
    """Fraction of benchmark-UP months in which the fund beat the benchmark.

    Decimal fraction in [0, 1] (0.6 = beat the benchmark in 60% of up months).

    Raises:
        ValueError: if fewer than 12 common months, NaN input, or there are no
            benchmark-up months (ratio undefined).
    """
    rv, bm = _aligned_monthly(daily_returns, benchmark_returns)
    up_mask = bm >= 0.0
    n_up = int(np.sum(up_mask))
    if n_up == 0:
        raise ValueError("up_proficiency_ratio is undefined: no benchmark-up months")
    return float(np.sum(rv[up_mask] > bm[up_mask]) / n_up)


def down_proficiency_ratio(
    daily_returns: pd.Series, benchmark_returns: pd.Series
) -> float:
    """Fraction of benchmark-DOWN months in which the fund beat the benchmark.

    Decimal fraction in [0, 1].

    Raises:
        ValueError: if fewer than 12 common months, NaN input, or there are no
            benchmark-down months (ratio undefined).
    """
    rv, bm = _aligned_monthly(daily_returns, benchmark_returns)
    down_mask = bm < 0.0
    n_down = int(np.sum(down_mask))
    if n_down == 0:
        raise ValueError(
            "down_proficiency_ratio is undefined: no benchmark-down months"
        )
    return float(np.sum(rv[down_mask] > bm[down_mask]) / n_down)


def r_squared(daily_returns: pd.Series, benchmark_returns: pd.Series) -> float:
    """R-squared of the monthly fund-vs-benchmark regression.

    Equals the square of the Pearson correlation of the aligned monthly series
    (R² = ρ² for a single-factor OLS), in [0, 1].

    Raises:
        ValueError: if fewer than 12 common months, NaN input, or either
            monthly series has zero variance (correlation undefined).
    """
    r = to_monthly_returns(daily_returns)
    bm = to_monthly_returns(benchmark_returns)
    ar, abm = align_returns(r, bm)
    if len(ar) < _MIN_MONTHS_REGRESSION:
        raise ValueError(
            f"r_squared requires at least {_MIN_MONTHS_REGRESSION} common "
            f"months, got {len(ar)}"
        )
    rho = correlation(ar, abm)
    return rho * rho
```
  Note: `correlation` (from `app/analytics/risk.py` lines 193-213) enforces its own `_MIN_TAIL_POINTS = 10` count guard and zero-variance guard; since we require >= 12 months first, the count guard is already satisfied and the zero-variance path still fails loud. Add `down_proficiency_ratio`, `r_squared`, `up_proficiency_ratio` to the `return_statistics` import block in `__init__.py` (from T3A-4) and interleave `"down_proficiency_ratio"`, `"r_squared"`, `"up_proficiency_ratio"` alphabetically into `__all__`.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_return_statistics.py -v`. Expected: all 11 tests pass (4 new + 7 from T3A-4). Run the full analytics suite to confirm no regressions: `cd backend && python -m pytest tests/test_analytics_rolling.py tests/test_analytics_returns.py tests/test_analytics_return_statistics.py tests/test_analytics_benchmark_composite.py tests/test_analytics_risk.py -q`.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/return_statistics.py app/analytics/__init__.py tests/test_analytics_return_statistics.py` then:
```
git commit -m "feat(analytics): up/down proficiency hit-rate + R-squared

Add proficiency ratios (fraction of bench-up/down months the fund won) and
R-squared (= correlation^2 of aligned monthly series) to return_statistics.py.
Beta-free aligned-monthly helper so the no-up-months guard fires correctly.
Fail loud when a regime has no months. Fact-sheet pack rank 42.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

## Tier 3 — Style-box 9-box classification + IPCA K-selection + Gamma drift monitor [style-box in app; K-selection & gamma drift repo: investintell-datalake-workers]

This cluster ports three independent techniques from the legacy `quant_engine` into the production split:

- **T3B-1** (LIGHT app, rank 24): a 9-box style classification (size × value/growth) as a pure analytics function plus a thin async reader over `equity_characteristics_monthly`. Mirrors the reader-service pattern of `backend/app/services/lookthrough.py` (pure dataclass + pure fn + async `text()` fetch over a materialized data-lake table); fail-loud `ValueError` on insufficient/non-finite data per the project Fail-loud contract.
- **T3B-2** (`[repo: investintell-datalake-workers]`, rank 25): IPCA K-selection — a walk-forward CV across a K grid with a ≥3-fold reliability gate, best-K pick, and a degraded fallback, wrapping the worker's existing `fit_ipca` / `oos_r_squared` in `src/workers/factor_model.py`. Ports the selection technique from legacy `factor_model_ipca_service.fit_universe`.
- **T3B-3** (`[repo: investintell-datalake-workers]`, rank 38): a Gamma drift monitor — orthogonal-Procrustes alignment of successive `Gamma` matrices + relative Frobenius drift with an alert threshold, ported 1:1 from legacy `quant_engine/ipca/drift_monitor.compute_gamma_drift`, plus a reader that pulls the two latest `factor_model_fits.gamma_loadings` and persists the drift.

Tasks are ordered by dependency (T3B-3 conceptually consumes K-selected fits from T3B-2, but the two have NO code dependency — both reuse the same `factor_model_fits` table; T3B-1 is fully independent and listed first as the simplest). Gate G5 (μ-free optimizer) is untouched: none of these techniques produce or consume an expected-return vector.

Verification notes (sources re-read before writing):
- LIGHT async-test config: `backend/pyproject.toml` line 53 sets `asyncio_mode = "auto"`, so the `@pytest.mark.asyncio` decorators in T3B-1's reader test are OPTIONAL (kept for explicitness; they are harmless under auto-mode).
- WORKER `src/workers/factor_model.py` is **527 lines**; the last function `_upsert` spans lines **484–527**. `fit_ipca` is lines **191–252**, `oos_r_squared` lines **255–307**, `run` lines **410–481**, `CHARS_COLS` lines **76–83** (L = 6), `ASSET_CLASS = "Equity"` line **73**. `from typing import Any` (line 65) and `import pandas as pd` (line 68) are already imported — `select_k` reuses both with no new import.
- WORKER `factor_model_fits` schema (`schemas/factor_model.sql`): `fit_id uuid` PK (line 23/35), `gamma_loadings jsonb` (line 28), natural key `(engine, asset_class, universe_hash, fit_date)` (line 44–45). No drift column exists yet.
- LEGACY `drift_monitor.compute_gamma_drift` (`E:/investintell-allocation/backend/quant_engine/ipca/drift_monitor.py`, full 86-line file read): `_DRIFT_THRESHOLD = 0.25`, `_MIN_GAMMA_NORM = 1e-12`; SVD-based orthogonal Procrustes `R = U @ Vt`, `gamma_new_aligned = gamma_new @ R.T`; raises on non-2D / shape-mismatch / empty / non-finite / near-zero baseline; returns `1.0` for a near-zero new gamma.

---

### Task T3B-1: 9-box style classification — pure analytics fn + async reader (LIGHT app)

**Files:**
- Create: `backend/app/analytics/style_box.py`
- Create: `backend/app/services/style_box.py`
- Test: `backend/tests/test_analytics_style_box.py` (pure fn; naming matches the existing `test_analytics_*.py` convention)
- Test: `backend/tests/test_style_box_service.py` (async reader, fake session; naming matches `test_*_service.py` convention)

Context from sources read:
- `equity_characteristics_monthly` (DDL in `E:/investintell-datalake-workers/schemas/characteristics.sql` lines 48–61) has `instrument_id UUID`, `ticker TEXT`, `as_of DATE`, `size_log_mkt_cap NUMERIC(10,4)`, `book_to_market NUMERIC(10,4)` (plus `mom_12_1`, `quality_roa`, `investment_growth`, `profitability_gross`, not used here). PK is `(instrument_id, as_of)` (line 60). `size_log_mkt_cap` is the log of the summed equity-sleeve market value; `book_to_market` is the fund-aggregate B/M (high = value, low = growth).
- The light app reads the data-lake via `app.core.datalake.get_datalake_session` (an `AsyncSession`, file confirmed at `backend/app/core/datalake.py`), exactly like `backend/app/services/lookthrough.py`, which executes `sqlalchemy.text()` queries with a dict of bind params: `await datalake.execute(_SQL, {"key": value})` (lookthrough.py lines 163, 169–175).
- Project convention: pure analytics in `app/analytics/*.py` raise `ValueError` on insufficient/NaN data (never NaN); fractions are decimal fractions (0..1, never 0–100).
- The legacy `style_analysis.classify_fund_style` returns a `StyleVector` with a `growth_tilt` derived from N-PORT SECTOR exposure (different data source) — NOT reused here; only the 9-box label vocabulary (`small_growth`…`large_value`, style_analysis.py lines 12–17) is carried over for consistency.

- [ ] **Step 1: Write the failing pure-analytics test.**
  Create `backend/tests/test_analytics_style_box.py`:

```python
"""Unit tests for the pure 9-box style classification (Tier 3, T3B-1).

Pure-function tests on synthetic cohorts — no DB, no I/O. The classifier takes
one fund's (size_log_mkt_cap, book_to_market) plus the cross-sectional cohort
breakpoints and returns a 9-box label, axis tilts, and a confidence score.
"""

import math

import pytest

from app.analytics.style_box import (
    StyleBox,
    StyleBoxBreakpoints,
    classify_style_box,
    compute_breakpoints,
)


def _cohort() -> list[tuple[float, float]]:
    # 9 funds spanning a clean 3x3 grid: size in {small,mid,large},
    # book_to_market in {growth(low),blend(mid),value(high)}.
    sizes = [10.0, 13.0, 16.0]          # log mkt cap terciles
    btms = [0.20, 0.50, 0.90]           # book_to_market terciles
    return [(s, b) for s in sizes for b in btms]


def test_compute_breakpoints_terciles():
    bp = compute_breakpoints(_cohort())
    assert isinstance(bp, StyleBoxBreakpoints)
    # 33rd/67th percentiles -> the low/high bands sit strictly inside the range.
    assert bp.size_lo < bp.size_hi
    assert bp.btm_lo < bp.btm_hi
    # The middle point of each axis falls inside the blend band.
    assert bp.size_lo <= 13.0 <= bp.size_hi
    assert bp.btm_lo <= 0.50 <= bp.btm_hi


def test_classify_corners():
    bp = compute_breakpoints(_cohort())
    # small + low B/M -> small_growth ; large + high B/M -> large_value
    sg = classify_style_box(10.0, 0.20, bp)
    lv = classify_style_box(16.0, 0.90, bp)
    assert sg.label == "small_growth"
    assert lv.label == "large_value"
    # mid + mid -> mid_blend (the center cell)
    mb = classify_style_box(13.0, 0.50, bp)
    assert mb.label == "mid_blend"


def test_tilts_are_unit_fractions():
    bp = compute_breakpoints(_cohort())
    box = classify_style_box(16.0, 0.90, bp)
    # value_tilt and size_tilt are decimal fractions in [0, 1] (never 0-100).
    assert 0.0 <= box.size_tilt <= 1.0
    assert 0.0 <= box.value_tilt <= 1.0
    # high B/M => value-leaning => value_tilt > 0.5
    assert box.value_tilt > 0.5
    # large size => size_tilt > 0.5
    assert box.size_tilt > 0.5
    assert isinstance(box, StyleBox)


def test_confidence_drops_near_breakpoints():
    bp = compute_breakpoints(_cohort())
    # A fund sitting exactly on both breakpoints is maximally ambiguous.
    on_edge = classify_style_box(bp.size_lo, bp.btm_lo, bp)
    deep_corner = classify_style_box(16.0, 0.90, bp)
    assert on_edge.confidence < deep_corner.confidence
    assert 0.0 <= on_edge.confidence <= 1.0
    assert 0.0 <= deep_corner.confidence <= 1.0


def test_compute_breakpoints_rejects_empty():
    with pytest.raises(ValueError, match="at least 3 funds"):
        compute_breakpoints([])


def test_compute_breakpoints_rejects_too_small_cohort():
    with pytest.raises(ValueError, match="at least 3 funds"):
        compute_breakpoints([(10.0, 0.2), (12.0, 0.5)])


def test_compute_breakpoints_rejects_non_finite_cohort():
    with pytest.raises(ValueError, match="non-finite"):
        compute_breakpoints([(10.0, 0.2), (13.0, float("nan")), (16.0, 0.9)])


def test_classify_rejects_nan():
    bp = compute_breakpoints(_cohort())
    with pytest.raises(ValueError, match="non-finite"):
        classify_style_box(float("nan"), 0.5, bp)
    with pytest.raises(ValueError, match="non-finite"):
        classify_style_box(13.0, math.inf, bp)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_analytics_style_box.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.analytics.style_box'` (the module does not exist yet — confirmed absent: `backend/app/analytics/` currently holds only `_validation.py`, `distribution.py`, `portfolio.py`, `returns.py`, `risk.py`, `rolling.py`).

- [ ] **Step 3: Write the minimal implementation.**
  Create `backend/app/analytics/style_box.py`:

```python
"""9-box (size × value/growth) style classification — pure, fail-loud.

Tier 3 (T3B-1). Classifies a fund into one of nine style boxes from two
fund-level characteristics materialized by the datalake characteristics worker
in equity_characteristics_monthly:

  - size_log_mkt_cap : log of the summed equity-sleeve market value
                       (high => large-cap; low => small-cap)
  - book_to_market   : fund-aggregate B/M (high => value; low => growth)

Breakpoints are cross-sectional TERCILES of the as-of cohort (Morningstar-style,
data-driven — no absolute magic cut-points). Tilts are decimal fractions in
[0, 1] (NEVER 0-100). Pure: zero I/O, zero ``app.*`` imports. Fail-loud:
raises ValueError on an undersized cohort or non-finite inputs, never returns
NaN. The 9-box label vocabulary matches the legacy
quant_engine.style_analysis.StyleLabel.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

import numpy as np

StyleBoxLabel = Literal[
    "small_growth", "small_blend", "small_value",
    "mid_growth", "mid_blend", "mid_value",
    "large_growth", "large_blend", "large_value",
]

_SIZE_BANDS = ("small", "mid", "large")
_VG_BANDS = ("growth", "blend", "value")


@dataclass(frozen=True)
class StyleBoxBreakpoints:
    """Cross-sectional tercile breakpoints for one as-of cohort."""

    size_lo: float
    size_hi: float
    btm_lo: float
    btm_hi: float


@dataclass(frozen=True)
class StyleBox:
    """Result of a single-fund 9-box classification."""

    label: StyleBoxLabel
    size_band: str
    value_growth_band: str
    size_tilt: float       # 0..1 ; >0.5 leans large
    value_tilt: float      # 0..1 ; >0.5 leans value
    confidence: float      # 0..1 ; distance from the nearest breakpoint


def compute_breakpoints(cohort: list[tuple[float, float]]) -> StyleBoxBreakpoints:
    """Tercile (33rd/67th pct) breakpoints from a cohort of (size, btm) pairs.

    ``cohort`` is the cross-section of (size_log_mkt_cap, book_to_market) for
    every fund priced on the same as_of. Requires >= 3 funds so terciles are
    defined; raises ValueError on a non-finite value.
    """
    if len(cohort) < 3:
        raise ValueError("style-box breakpoints require at least 3 funds in the cohort")
    sizes = np.asarray([s for s, _ in cohort], dtype=float)
    btms = np.asarray([b for _, b in cohort], dtype=float)
    if not np.isfinite(sizes).all() or not np.isfinite(btms).all():
        raise ValueError("cohort contains non-finite size or book_to_market values")
    size_lo, size_hi = (float(x) for x in np.percentile(sizes, [33.3333, 66.6667]))
    btm_lo, btm_hi = (float(x) for x in np.percentile(btms, [33.3333, 66.6667]))
    return StyleBoxBreakpoints(
        size_lo=size_lo, size_hi=size_hi, btm_lo=btm_lo, btm_hi=btm_hi
    )


def _band(value: float, lo: float, hi: float, names: tuple[str, str, str]) -> str:
    if value <= lo:
        return names[0]
    if value >= hi:
        return names[2]
    return names[1]


def _axis_tilt(value: float, lo: float, hi: float) -> float:
    """Map a value onto [0, 1] using the lo/hi breakpoints as 1/3 and 2/3.

    Linear inside [lo, hi]; clamped to [0, 1] outside. Returns 1/3 at lo,
    2/3 at hi, 0.5 at the midpoint of the blend band.
    """
    if hi <= lo:
        return 0.5
    frac = (value - lo) / (hi - lo)  # 0 at lo, 1 at hi
    tilt = (1.0 + frac) / 3.0        # 1/3 at lo, 2/3 at hi
    return float(min(1.0, max(0.0, tilt)))


def classify_style_box(
    size_log_mkt_cap: float,
    book_to_market: float,
    breakpoints: StyleBoxBreakpoints,
) -> StyleBox:
    """Classify one fund into a 9-box style cell.

    Fail-loud: raises ValueError on non-finite inputs. Confidence is the
    smaller of the two axis distances from the nearest breakpoint, normalized
    by the axis span — a fund sitting exactly on a breakpoint scores 0.
    """
    if not math.isfinite(size_log_mkt_cap) or not math.isfinite(book_to_market):
        raise ValueError("non-finite size_log_mkt_cap or book_to_market")

    bp = breakpoints
    size_band = _band(size_log_mkt_cap, bp.size_lo, bp.size_hi, _SIZE_BANDS)
    vg_band = _band(book_to_market, bp.btm_lo, bp.btm_hi, _VG_BANDS)
    label = f"{size_band}_{vg_band}"

    size_tilt = _axis_tilt(size_log_mkt_cap, bp.size_lo, bp.size_hi)
    value_tilt = _axis_tilt(book_to_market, bp.btm_lo, bp.btm_hi)

    # Confidence: normalized distance to the nearest breakpoint on each axis,
    # taking the weaker axis (a fund is only as confident as its weakest axis).
    size_span = (bp.size_hi - bp.size_lo) or 1.0
    btm_span = (bp.btm_hi - bp.btm_lo) or 1.0
    size_conf = min(
        abs(size_log_mkt_cap - bp.size_lo), abs(size_log_mkt_cap - bp.size_hi)
    ) / size_span
    btm_conf = min(
        abs(book_to_market - bp.btm_lo), abs(book_to_market - bp.btm_hi)
    ) / btm_span
    confidence = float(min(1.0, min(size_conf, btm_conf)))

    return StyleBox(
        label=label,  # type: ignore[arg-type]
        size_band=size_band,
        value_growth_band=vg_band,
        size_tilt=round(size_tilt, 4),
        value_tilt=round(value_tilt, 4),
        confidence=round(confidence, 4),
    )
```

- [ ] **Step 4: Run the pure tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_analytics_style_box.py -v`
  Expected: all 8 tests pass.

- [ ] **Step 5: Write the failing async-reader test.**
  Create `backend/tests/test_style_box_service.py`:

```python
"""Tests for the style-box reader/orchestrator (Tier 3, T3B-1).

The cohort comes from equity_characteristics_monthly (materialized by the
datalake characteristics worker); this service only READS it via an
AsyncSession and applies the pure classifier. The DB is stubbed with a fake
async session that returns canned rows — no live cloud. The light test suite
runs under pytest asyncio_mode="auto" (pyproject.toml line 53), so the
@pytest.mark.asyncio markers below are optional but kept for clarity.
"""

import datetime as dt
import uuid

import pytest

from app.services.style_box import classify_fund_style_box, load_cohort


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _FakeSession:
    """Minimal AsyncSession stub: records the last params, returns rows.

    Mirrors how app.services.lookthrough calls the session:
    ``await datalake.execute(text_sql, {"as_of": ...})`` — params arrive as the
    second positional argument.
    """

    def __init__(self, rows):
        self._rows = rows
        self.last_params = None

    async def execute(self, _stmt, params=None):
        self.last_params = params
        return _FakeResult(self._rows)


def _row(iid, size, btm, as_of=dt.date(2026, 3, 31)):
    # Mirrors the SELECT column order in load_cohort:
    # (instrument_id, as_of, size_log_mkt_cap, book_to_market).
    return (iid, as_of, size, btm)


@pytest.mark.asyncio
async def test_load_cohort_maps_rows():
    rows = [
        _row(uuid.uuid4(), 10.0, 0.2),
        _row(uuid.uuid4(), 13.0, 0.5),
        _row(uuid.uuid4(), 16.0, 0.9),
    ]
    session = _FakeSession(rows)
    cohort = await load_cohort(session, dt.date(2026, 3, 31))
    assert len(cohort) == 3
    assert (10.0, 0.2) in cohort
    assert session.last_params["as_of"] == dt.date(2026, 3, 31)


@pytest.mark.asyncio
async def test_classify_fund_style_box_happy_path():
    target = uuid.uuid4()
    rows = [
        (target, dt.date(2026, 3, 31), 16.0, 0.9),
        (uuid.uuid4(), dt.date(2026, 3, 31), 10.0, 0.2),
        (uuid.uuid4(), dt.date(2026, 3, 31), 13.0, 0.5),
    ]
    session = _FakeSession(rows)
    box = await classify_fund_style_box(session, target, dt.date(2026, 3, 31))
    assert box.label == "large_value"


@pytest.mark.asyncio
async def test_classify_fund_style_box_missing_fund_raises():
    rows = [
        (uuid.uuid4(), dt.date(2026, 3, 31), 10.0, 0.2),
        (uuid.uuid4(), dt.date(2026, 3, 31), 13.0, 0.5),
        (uuid.uuid4(), dt.date(2026, 3, 31), 16.0, 0.9),
    ]
    session = _FakeSession(rows)
    with pytest.raises(ValueError, match="not in the style-box cohort"):
        await classify_fund_style_box(session, uuid.uuid4(), dt.date(2026, 3, 31))


@pytest.mark.asyncio
async def test_classify_fund_style_box_undersized_cohort_raises():
    target = uuid.uuid4()
    rows = [(target, dt.date(2026, 3, 31), 16.0, 0.9)]
    session = _FakeSession(rows)
    with pytest.raises(ValueError, match="at least 3 funds"):
        await classify_fund_style_box(session, target, dt.date(2026, 3, 31))
```

- [ ] **Step 6: Run the reader test, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_style_box_service.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.services.style_box'`.

- [ ] **Step 7: Write the reader/orchestrator implementation.**
  Create `backend/app/services/style_box.py`:

```python
"""Style-box reader/orchestrator (Tier 3, T3B-1) — DB-first, read-only.

The size/value characteristics are materialized by the datalake
``characteristics`` worker in ``equity_characteristics_monthly`` (TimescaleDB
Cloud). This service only READS that table via an AsyncSession and applies the
pure classifier in ``app.analytics.style_box`` — no characteristic math here.

Pattern mirrors ``app.services.lookthrough``: ``text()`` SQL against the
materialized data-lake table + a thin pure-fn call. Fail-loud: ValueError
(mapped to 422 by the route) when the cohort is too small or the target fund is
absent.
"""

from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.style_box import (
    StyleBox,
    classify_style_box,
    compute_breakpoints,
)

# Latest as_of for each instrument on/before the requested date, then the
# size/value chars for that snapshot. equity_characteristics_monthly is keyed
# (instrument_id, as_of); we take the most recent row per fund <= as_of.
_COHORT_SQL = text("""
    SELECT DISTINCT ON (instrument_id)
           instrument_id, as_of, size_log_mkt_cap, book_to_market
    FROM equity_characteristics_monthly
    WHERE as_of <= :as_of
      AND size_log_mkt_cap IS NOT NULL
      AND book_to_market IS NOT NULL
    ORDER BY instrument_id, as_of DESC
""")


async def load_cohort(
    datalake: AsyncSession, as_of: dt.date
) -> list[tuple[float, float]]:
    """Cross-sectional (size_log_mkt_cap, book_to_market) cohort as-of a date."""
    result = await datalake.execute(_COHORT_SQL, {"as_of": as_of})
    return [(float(size), float(btm)) for _iid, _as_of, size, btm in result.all()]


async def _load_cohort_with_ids(
    datalake: AsyncSession, as_of: dt.date
) -> list[tuple[uuid.UUID, float, float]]:
    result = await datalake.execute(_COHORT_SQL, {"as_of": as_of})
    return [
        (iid, float(size), float(btm))
        for iid, _as_of, size, btm in result.all()
    ]


async def classify_fund_style_box(
    datalake: AsyncSession, instrument_id: uuid.UUID, as_of: dt.date
) -> StyleBox:
    """Classify one fund against the as-of cross-sectional cohort.

    Raises ValueError when the cohort has < 3 funds or the target fund has no
    materialized characteristics on/before ``as_of``.
    """
    cohort = await _load_cohort_with_ids(datalake, as_of)
    breakpoints = compute_breakpoints([(s, b) for _iid, s, b in cohort])
    for iid, size, btm in cohort:
        if iid == instrument_id:
            return classify_style_box(size, btm, breakpoints)
    raise ValueError(
        f"fund {instrument_id} not in the style-box cohort as-of {as_of}"
    )
```

- [ ] **Step 8: Run both T3B-1 test files, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_analytics_style_box.py tests/test_style_box_service.py -v`
  Expected: all 12 tests pass. (`load_cohort` is exercised by `test_load_cohort_maps_rows`; the undersized-cohort `ValueError("style-box breakpoints require at least 3 funds in the cohort")` raised by `compute_breakpoints` is matched by the `at least 3 funds` regex in `test_classify_fund_style_box_undersized_cohort_raises`.)

- [ ] **Step 9: Commit.**
  Commands:
  - `cd backend && git add app/analytics/style_box.py app/services/style_box.py tests/test_analytics_style_box.py tests/test_style_box_service.py`
  - `git commit -m "feat(style-box): 9-box size×value classification reader over equity_characteristics_monthly (T3B-1)"`

---

### Task T3B-2: IPCA K-selection — walk-forward CV with ≥3-fold reliability gate `[repo: investintell-datalake-workers]`

**Files:**
- Modify: `src/workers/factor_model.py` (add `MIN_FOLDS_FOR_K_SELECTION` constant + `_count_oos_folds(...)` + `select_k(...)`; reuse the existing `fit_ipca` at lines 191–252 and `oos_r_squared` at lines 255–307; `from typing import Any` (line 65) and `import pandas as pd` (line 68) already imported; the existing `run` at lines 410–481 is NOT changed in this task)
- Test: `tests/test_factor_model_k_selection.py`

Context from sources read:
- The worker already exposes `fit_ipca(chars, returns, K, *, max_iter=200, tol=1e-6) -> dict` (returns `gamma`, `factor_returns`, `dates`, `K`, `r_squared`, `converged`, `n_iterations`, `T` — lines 191–252) and `oos_r_squared(chars, returns, K, *, min_train=24, test_window=12, max_iter=100) -> float | None` (lines 255–307; its expanding-window loop starts at `i = min_train` and advances `while i + test_window <= n`).
- The legacy `factor_model_ipca_service.fit_universe` (`E:/investintell-allocation/backend/quant_engine/factor_model_ipca_service.py` lines 50–255) is the technique to port: it grids K over `range(1, max_k+1)` (line 112), runs walk-forward CV (60m train / 12m test, lines 116–120), requires `MIN_FOLDS_FOR_K_SELECTION = 3` valid folds before a K's mean OOS R² is "reliable" (defined line 20; gate lines 200–226), picks `best_k = max(candidates, key=...)` (line 208), and falls back to the smallest K with any valid fold (degraded, lines 211–220) when no K clears the gate. When ALL K's have zero valid folds it raises `ValueError("IPCA walk-forward CV could not validate any K in [1, {max_k}]...")` (lines 194–198).
- Here we do NOT re-implement the CV loop or call the `ipca` package (the worker has a numpy-pure ALS already): we reuse the worker's existing `oos_r_squared` (mean OOS R² over expanding-window folds) to score each K, and add `_count_oos_folds` so the ≥3-fold gate can be applied (the worker's `oos_r_squared` returns the MEAN, not per-fold scores, hence the separate fold count).
- The worker's `test_factor_model.py` (lines 35–60) already has a `_make_synthetic` panel generator; the K-selection test below defines its own copy (same DGP) to stay self-contained, importing `from src.workers import factor_model as fm` (matching test_factor_model.py line 24).

- [ ] **Step 1: Write the failing test.**
  Create `tests/test_factor_model_k_selection.py`:

```python
"""Tests for IPCA K-selection (Tier 3, T3B-2).

select_k grids K over [1, min(max_k, L)], scores each with walk-forward OOS R²,
and applies a >=3-fold reliability gate. Uses a self-contained synthetic-panel
generator (same DGP as test_factor_model) so the recovered best K matches the
true K of the data-generating process.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from src.workers import factor_model as fm


def _make_synthetic(*, L=4, K=2, T=120, N=60, noise=0.01, seed=7):
    """r_{i,t} = (z_{i,t} Gamma) f_t + noise. Returns (chars, returns, Gamma)."""
    rng = np.random.default_rng(seed)
    G_true, _ = np.linalg.qr(rng.standard_normal((L, K)))
    F = rng.standard_normal((K, T)) * 0.05
    months = pd.date_range("2010-01-31", periods=T, freq="ME")
    frames = []
    for t in range(T):
        Z = rng.standard_normal((N, L))
        beta = Z @ G_true
        r = beta @ F[:, t] + rng.standard_normal(N) * noise
        df = pd.DataFrame(Z, columns=fm.CHARS_COLS[:L])
        df["instrument_id"] = [f"id_{i:03d}" for i in range(N)]
        df["month"] = months[t]
        df["monthly_return"] = r
        frames.append(df)
    panel = pd.concat(frames, ignore_index=True)
    panel = panel.set_index(["instrument_id", "month"]).sort_index()
    return panel[fm.CHARS_COLS[:L]], panel["monthly_return"], G_true


def test_count_oos_folds_matches_window_math():
    # Expanding window: first fold at i=min_train, slide by test_window while
    # i + test_window <= n.
    chars, _returns, _ = _make_synthetic(T=120)
    n = chars.index.get_level_values("month").nunique()
    folds = fm._count_oos_folds(n, min_train=36, test_window=12)
    expected = len(range(36, n - 12 + 1, 12))
    assert folds == expected
    assert folds >= 3


def test_select_k_recovers_true_k():
    chars, returns, _ = _make_synthetic(K=2, T=120, noise=0.005)
    sel = fm.select_k(chars, returns, max_k=4, min_train=36, test_window=12)
    assert sel["best_k"] == 2
    assert sel["degraded"] is False
    assert sel["insufficient_folds"] is False
    assert sel["n_folds"] >= fm.MIN_FOLDS_FOR_K_SELECTION
    # best OOS R2 is the max over the grid and plausible for a strong signal.
    assert sel["best_oos_r_squared"] > 0.4
    # every K in the grid (1..L=4) has a recorded mean OOS score.
    assert set(sel["k_scores"].keys()) == {1, 2, 3, 4}


def test_select_k_degraded_when_too_few_folds():
    # T short enough that the expanding window yields < 3 folds -> degraded
    # fallback to the smallest K with any valid fold.
    # _count_oos_folds(50, 36, 12) = len(range(36, 39, 12)) = 1 < 3.
    chars, returns, _ = _make_synthetic(K=2, T=50, noise=0.01)
    sel = fm.select_k(chars, returns, max_k=3, min_train=36, test_window=12)
    assert sel["n_folds"] == 1
    assert sel["insufficient_folds"] is True
    assert sel["degraded"] is True
    assert sel["best_k"] == 1  # smallest K fallback
    assert sel["degraded_reason"] == "ipca_k_selection_insufficient_folds"


def test_select_k_raises_when_no_valid_fold():
    # n < min_train + test_window -> oos_r_squared returns None for every K.
    chars, returns, _ = _make_synthetic(K=2, T=20)
    with pytest.raises(ValueError, match="could not validate any K"):
        fm.select_k(chars, returns, max_k=3, min_train=36, test_window=12)


def test_select_k_clamps_grid_to_n_chars():
    # max_k above the number of instrument characteristics (L) is clamped to L.
    chars, returns, _ = _make_synthetic(L=3, K=2, T=120, noise=0.005)
    sel = fm.select_k(chars, returns, max_k=6, min_train=36, test_window=12)
    assert max(sel["k_scores"].keys()) == 3  # clamped to L=3
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd E:/investintell-datalake-workers && python -m pytest tests/test_factor_model_k_selection.py -v`
  Expected failure: `AttributeError: module 'src.workers.factor_model' has no attribute '_count_oos_folds'` (and `select_k`, `MIN_FOLDS_FOR_K_SELECTION` are absent).

- [ ] **Step 3: Write the minimal implementation.**
  In `src/workers/factor_model.py`, add the constant immediately AFTER the `CHARS_COLS` block (which ends at line 83) and BEFORE the `_LEGACY_DSN` block (lines 85–90):

```python
# PR-Q36 F04 (ported to worker, T3B-2): require >= 3 valid CV folds before a K's
# mean OOS R^2 is treated as reliable. Mirrors
# quant_engine.factor_model_ipca_service.MIN_FOLDS_FOR_K_SELECTION.
MIN_FOLDS_FOR_K_SELECTION = 3
```

  Then append these two functions to the END of `src/workers/factor_model.py` (after `_upsert`, the last function, which ends at line 527):

```python
# --------------------------------------------------------------------------- #
# K-selection (T3B-2): grid K, score each by walk-forward OOS R^2, apply the
# >=3-fold reliability gate. Ports quant_engine.factor_model_ipca_service.
# fit_universe's selection logic; reuses this module's fit_ipca / oos_r_squared.
# --------------------------------------------------------------------------- #
def _count_oos_folds(n_dates: int, *, min_train: int, test_window: int) -> int:
    """Number of expanding-window folds oos_r_squared would evaluate.

    Mirrors the loop in oos_r_squared: i starts at min_train and advances by
    test_window while i + test_window <= n_dates.
    """
    if n_dates < min_train + test_window:
        return 0
    return len(range(min_train, n_dates - test_window + 1, test_window))


def select_k(
    chars: pd.DataFrame,
    returns: pd.Series,
    *,
    max_k: int = 6,
    min_train: int = 24,
    test_window: int = 12,
    max_iter: int = 100,
) -> dict[str, Any]:
    """Select the IPCA factor count K by walk-forward OOS R^2.

    Grids K over [1, min(max_k, L)] where L = chars.shape[1], scoring each K with
    this module's expanding-window ``oos_r_squared``. Applies a
    >= MIN_FOLDS_FOR_K_SELECTION reliability gate:
      - if the panel yields >= 3 folds, pick best_k = argmax mean OOS R^2;
      - else fall back to the SMALLEST K with a (non-None) score and flag the
        result degraded (insufficient_folds);
      - if NO K produces a score (panel too short), raise ValueError.

    Returns a dict: best_k, best_oos_r_squared, n_folds, k_scores (K -> mean OOS
    R^2), degraded, insufficient_folds, degraded_reason.
    """
    L = chars.shape[1]
    grid_top = min(max_k, L)
    if grid_top < 1:
        raise ValueError(f"select_k: no characteristics to fit (L={L})")

    n_dates = chars.index.get_level_values("month").nunique()
    n_folds = _count_oos_folds(n_dates, min_train=min_train, test_window=test_window)

    k_scores: dict[int, float] = {}
    for k in range(1, grid_top + 1):
        score = oos_r_squared(
            chars, returns, k,
            min_train=min_train, test_window=test_window, max_iter=max_iter,
        )
        if score is not None:
            k_scores[k] = float(score)

    if not k_scores:
        raise ValueError(
            f"IPCA walk-forward CV could not validate any K in [1, {grid_top}]: "
            "no fold produced an OOS score (panel too short or numerically unstable)"
        )

    if n_folds >= MIN_FOLDS_FOR_K_SELECTION:
        best_k = max(k_scores, key=lambda kk: k_scores[kk])
        insufficient_folds = False
        degraded_reason: str | None = None
    else:
        best_k = min(k_scores)  # smallest K with any valid score
        insufficient_folds = True
        degraded_reason = "ipca_k_selection_insufficient_folds"

    best_oos = k_scores[best_k]
    degraded = insufficient_folds or best_oos <= 0.0
    if degraded_reason is None and best_oos <= 0.0:
        degraded_reason = "oos_r2_negative_useless_fit"

    return {
        "best_k": int(best_k),
        "best_oos_r_squared": float(best_oos),
        "n_folds": int(n_folds),
        "k_scores": k_scores,
        "degraded": bool(degraded),
        "insufficient_folds": bool(insufficient_folds),
        "degraded_reason": degraded_reason,
    }
```

- [ ] **Step 4: Run the tests, expect PASS.**
  Command: `cd E:/investintell-datalake-workers && python -m pytest tests/test_factor_model_k_selection.py -v`
  Expected: all 5 tests pass. (`test_select_k_recovers_true_k` relies on the strong-signal DGP making K=2 the OOS-max with 7 folds — `_count_oos_folds(120, 36, 12) = len(range(36, 109, 12)) = 7`; `test_select_k_degraded_when_too_few_folds` uses T=50 so `_count_oos_folds(50, 36, 12) = len(range(36, 39, 12)) = 1 < 3`; `test_select_k_raises_when_no_valid_fold` uses T=20 < 36+12 so every `oos_r_squared` returns None and `k_scores` is empty.)

- [ ] **Step 5: Commit.**
  Commands:
  - `cd E:/investintell-datalake-workers && git add src/workers/factor_model.py tests/test_factor_model_k_selection.py`
  - `git commit -m "feat(factor-model): IPCA K-selection with >=3-fold reliability gate + degraded fallback (T3B-2)"`

---

### Task T3B-3: Gamma drift monitor — Procrustes-aligned Frobenius drift + reader/alert `[repo: investintell-datalake-workers]`

**Files:**
- Create: `src/workers/gamma_drift.py` (pure `compute_gamma_drift` + reader `monitor_gamma_drift` + persistence `_persist_drift` + `run`)
- Modify: `schemas/factor_model.sql` (idempotent ALTER adding `gamma_drift_vs_prior NUMERIC` + `drift_alert BOOLEAN`; append after the existing unique index block at line 45)
- Test: `tests/test_gamma_drift.py`

Context from sources read:
- Legacy `compute_gamma_drift` lives in `E:/investintell-allocation/backend/quant_engine/ipca/drift_monitor.py` (full 86-line file read): orthogonal Procrustes via `U, _, Vt = np.linalg.svd(gamma_old.T @ gamma_new); R = U @ Vt; gamma_new_aligned = gamma_new @ R.T` (lines 71–73); drift = `||aligned - old||_F / ||old||_F` (lines 75–76); threshold `_DRIFT_THRESHOLD = 0.25` (line 10); `_MIN_GAMMA_NORM = 1e-12` (line 11). It raises `ValueError` on non-2D (line 32), shape mismatch (line 38), empty (line 43), or non-finite inputs (line 46), and on a near-zero baseline norm (lines 51–57); returns `1.0` for a near-zero new gamma (lines 59–66). The port renames `_DRIFT_THRESHOLD` to a public `DRIFT_THRESHOLD` so the monitor and tests can read it, and drops `structlog` (not a worker dependency) in favor of returning the alert flag.
- Persistence target is `factor_model_fits` (`schemas/factor_model.sql`): `gamma_loadings jsonb` (line 28) holds the L×K loading matrix (header lines 10–13), `fit_id uuid` PK (lines 23, 35), natural key `(engine, asset_class, universe_hash, fit_date)` (lines 44–45). The two most recent fits per `(engine, asset_class, universe_hash)` are compared, ordered by `fit_date`.
- DB access uses `from src.db import connect, advisory_lock, LOCK_FACTOR_MODEL` (worker `src/db.py`: `connect` lines 24–26, `advisory_lock` lines 29–44, `LOCK_FACTOR_MODEL = 900_203` line 51). The factor_model worker already owns `LOCK_FACTOR_MODEL`; the drift monitor reuses it (it touches the same table after the fit, so serializing against the fit worker is correct).
- `numpy` is pinned (`requirements.txt` line 2, numpy>=1.26); `numpy.typing` ships with numpy and is used by the legacy module, so `import numpy.typing as npt` is valid in the worker.

- [ ] **Step 1: Write the failing test.**
  Create `tests/test_gamma_drift.py`:

```python
"""Tests for the IPCA gamma drift monitor (Tier 3, T3B-3).

compute_gamma_drift is pure (Procrustes-aligned relative Frobenius drift); it
is rotation/sign invariant per Kelly-Pruitt-Su identification. The reader
monitor_gamma_drift pulls the two latest gamma_loadings from factor_model_fits
and is tested against a fake psycopg connection (no live DB).
"""

from __future__ import annotations

import numpy as np
import pytest

from src.workers.gamma_drift import (
    DRIFT_THRESHOLD,
    compute_gamma_drift,
    monitor_gamma_drift,
)


def test_identical_gamma_zero_drift():
    g = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, -0.5]])
    assert compute_gamma_drift(g, g) == pytest.approx(0.0, abs=1e-12)


def test_sign_flip_is_zero_drift():
    # A pure sign flip is a valid IPCA equivalence -> drift 0 after Procrustes.
    g = np.array([[1.0, 0.2], [0.3, 1.0], [-0.4, 0.5]])
    assert compute_gamma_drift(g, -g) == pytest.approx(0.0, abs=1e-9)


def test_orthogonal_rotation_is_zero_drift():
    rng = np.random.default_rng(3)
    g, _ = np.linalg.qr(rng.standard_normal((5, 2)))
    theta = 0.7
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    assert compute_gamma_drift(g, g @ rot) == pytest.approx(0.0, abs=1e-9)


def test_real_drift_is_positive():
    g_old = np.array([[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]])
    g_new = np.array([[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]])  # genuine new loading
    drift = compute_gamma_drift(g_old, g_new)
    assert drift > 0.0


def test_shape_mismatch_raises():
    with pytest.raises(ValueError, match="Shape mismatch"):
        compute_gamma_drift(np.ones((3, 2)), np.ones((3, 3)))


def test_non_finite_raises():
    g = np.array([[1.0, np.nan], [0.0, 1.0]])
    with pytest.raises(ValueError, match="finite"):
        compute_gamma_drift(g, np.ones((2, 2)))


def test_non_2d_raises():
    with pytest.raises(ValueError, match="2D"):
        compute_gamma_drift(np.ones(4), np.ones(4))


# --- reader against a fake psycopg connection -------------------------------
class _FakeCur:
    def __init__(self, rows):
        self._rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql, params=None):
        self.executed.append((sql, params))

    def fetchall(self):
        return self._rows


class _FakeConn:
    def __init__(self, rows):
        self._rows = rows

    def cursor(self):
        return _FakeCur(self._rows)


def test_monitor_returns_none_with_one_fit():
    conn = _FakeConn([([[1.0, 0.0], [0.0, 1.0]],)])  # only one gamma row
    out = monitor_gamma_drift(conn, universe_hash="abc", engine="ipca",
                              asset_class="Equity")
    assert out is None


def test_monitor_flags_alert_on_large_drift():
    g_old = [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    g_new = [[1.0, 0.0], [0.0, 1.0], [3.0, 3.0]]  # big genuine drift
    # rows ordered newest first (matches the ORDER BY fit_date DESC LIMIT 2).
    conn = _FakeConn([(g_new,), (g_old,)])
    out = monitor_gamma_drift(conn, universe_hash="abc", engine="ipca",
                              asset_class="Equity")
    assert out is not None
    assert out["drift"] > DRIFT_THRESHOLD
    assert out["alert"] is True


def test_monitor_no_alert_on_small_drift():
    g_old = [[1.0, 0.0], [0.0, 1.0], [0.0, 0.0]]
    g_new = [[1.0, 0.0], [0.0, 1.0], [0.01, 0.0]]  # tiny drift
    conn = _FakeConn([(g_new,), (g_old,)])
    out = monitor_gamma_drift(conn, universe_hash="abc", engine="ipca",
                              asset_class="Equity")
    assert out is not None
    assert out["drift"] < DRIFT_THRESHOLD
    assert out["alert"] is False
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd E:/investintell-datalake-workers && python -m pytest tests/test_gamma_drift.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'src.workers.gamma_drift'`.

- [ ] **Step 3: Write the implementation.**
  Create `src/workers/gamma_drift.py`:

```python
"""gamma_drift — IPCA Gamma drift monitor (Tier 3, T3B-3).

Ported from quant_engine/ipca/drift_monitor.compute_gamma_drift. IPCA factor
loadings (Gamma) are identified only up to an orthogonal rotation / sign flip
(Kelly-Pruitt-Su 2019), so successive re-estimations may differ by a rotation
that carries NO economic drift. We align Gamma_new to Gamma_old by orthogonal
Procrustes (Schonemann 1966) before measuring the relative Frobenius-norm
change, and raise an alert when the aligned drift exceeds DRIFT_THRESHOLD.

The monitor reads the two latest gamma_loadings for a universe from
factor_model_fits (materialized by the factor_model worker) and persists the
drift back onto the newest fit row. DB-first: no fit math here. Unlike the
legacy module this returns the alert flag instead of logging via structlog
(structlog is not a worker dependency).
"""

from __future__ import annotations

from typing import Any

import numpy as np
import numpy.typing as npt

from src.db import LOCK_FACTOR_MODEL, advisory_lock, connect

DRIFT_THRESHOLD = 0.25
_MIN_GAMMA_NORM = 1e-12

ENGINE = "ipca"
ASSET_CLASS = "Equity"


def compute_gamma_drift(
    gamma_old: npt.NDArray[np.float64],
    gamma_new: npt.NDArray[np.float64],
) -> float:
    """Procrustes-aligned relative Frobenius drift between two Gamma matrices.

    Rotation/sign invariant: a pure rotation or sign flip yields 0.0. Raises
    ValueError on non-2D, shape mismatch, empty, or non-finite inputs, and on a
    near-zero baseline norm. Returns 1.0 when the new Gamma is near-zero.
    """
    gamma_old = np.asarray(gamma_old, dtype=np.float64)
    gamma_new = np.asarray(gamma_new, dtype=np.float64)

    if gamma_old.ndim != 2 or gamma_new.ndim != 2:
        raise ValueError(
            f"Gamma matrices must be 2D: gamma_old {gamma_old.shape}, "
            f"gamma_new {gamma_new.shape}"
        )
    if gamma_old.shape != gamma_new.shape:
        raise ValueError(
            f"Shape mismatch: gamma_old {gamma_old.shape} != gamma_new {gamma_new.shape}"
        )
    if gamma_old.size == 0:
        raise ValueError("Gamma matrices must be non-empty")
    if not np.isfinite(gamma_old).all() or not np.isfinite(gamma_new).all():
        raise ValueError("Gamma matrices must contain only finite values")

    norm_old = float(np.linalg.norm(gamma_old, ord="fro"))
    norm_new = float(np.linalg.norm(gamma_new, ord="fro"))
    if norm_old < _MIN_GAMMA_NORM:
        if norm_new < _MIN_GAMMA_NORM:
            return 0.0
        raise ValueError(
            "Cannot compute relative gamma drift from a near-zero baseline "
            f"(norm_old={norm_old:.3e}, norm_new={norm_new:.3e})"
        )
    if norm_new < _MIN_GAMMA_NORM:
        return 1.0

    # Orthogonal Procrustes: R = U V^T from SVD(gamma_old^T @ gamma_new),
    # minimizing ||gamma_new @ R^T - gamma_old||_F.
    U, _, Vt = np.linalg.svd(gamma_old.T @ gamma_new)
    R = U @ Vt
    gamma_new_aligned = gamma_new @ R.T

    diff = gamma_new_aligned - gamma_old
    return float(np.linalg.norm(diff, ord="fro") / norm_old)


def _fetch_latest_two_gammas(
    conn: Any, *, universe_hash: str, engine: str, asset_class: str
) -> list[np.ndarray]:
    """Latest two gamma_loadings (newest first) for one universe/engine/class."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT gamma_loadings
            FROM factor_model_fits
            WHERE engine = %s AND asset_class = %s AND universe_hash = %s
            ORDER BY fit_date DESC
            LIMIT 2
            """,
            (engine, asset_class, universe_hash),
        )
        rows = cur.fetchall()
    return [np.asarray(r[0], dtype=np.float64) for r in rows]


def monitor_gamma_drift(
    conn: Any,
    *,
    universe_hash: str,
    engine: str = ENGINE,
    asset_class: str = ASSET_CLASS,
) -> dict[str, Any] | None:
    """Compare the two latest Gamma fits for a universe; return drift + alert.

    Returns None when fewer than two fits exist (drift undefined). Otherwise
    returns {"drift": float, "alert": bool, "threshold": float}. Shape changes
    between fits (different K or L) surface as a ValueError from
    compute_gamma_drift — a fail-loud signal that the fit dimension moved.
    """
    gammas = _fetch_latest_two_gammas(
        conn, universe_hash=universe_hash, engine=engine, asset_class=asset_class
    )
    if len(gammas) < 2:
        return None
    gamma_new, gamma_old = gammas[0], gammas[1]
    drift = compute_gamma_drift(gamma_old, gamma_new)
    return {
        "drift": drift,
        "alert": drift > DRIFT_THRESHOLD,
        "threshold": DRIFT_THRESHOLD,
    }


def _persist_drift(
    conn: Any, *, universe_hash: str, engine: str, asset_class: str,
    drift: float, alert: bool,
) -> None:
    """Write the drift + alert onto the newest fit row for the universe."""
    with conn.cursor() as cur:
        cur.execute(
            """
            UPDATE factor_model_fits
            SET gamma_drift_vs_prior = %s, drift_alert = %s
            WHERE fit_id = (
                SELECT fit_id FROM factor_model_fits
                WHERE engine = %s AND asset_class = %s AND universe_hash = %s
                ORDER BY fit_date DESC LIMIT 1
            )
            """,
            (drift, alert, engine, asset_class, universe_hash),
        )


def run(
    dsn: str,
    *,
    universe_hash: str | None = None,
    engine: str = ENGINE,
    asset_class: str = ASSET_CLASS,
) -> dict[str, Any]:
    """Compute + persist Gamma drift for one (or every) universe.

    When universe_hash is None, monitors every universe that has >= 2 fits.
    Reuses LOCK_FACTOR_MODEL so it serializes against the factor_model fit
    worker on the shared table.
    """
    with connect(dsn) as conn:
        with advisory_lock(conn, LOCK_FACTOR_MODEL) as got:
            if not got:
                return {"status": "skipped", "reason": "lock_held", "monitored": 0}

            if universe_hash is not None:
                hashes = [universe_hash]
            else:
                with conn.cursor() as cur:
                    cur.execute(
                        """
                        SELECT universe_hash
                        FROM factor_model_fits
                        WHERE engine = %s AND asset_class = %s
                        GROUP BY universe_hash
                        HAVING count(*) >= 2
                        """,
                        (engine, asset_class),
                    )
                    hashes = [r[0] for r in cur.fetchall()]

            monitored = 0
            alerts = 0
            for uh in hashes:
                result = monitor_gamma_drift(
                    conn, universe_hash=uh, engine=engine, asset_class=asset_class
                )
                if result is None:
                    continue
                _persist_drift(
                    conn, universe_hash=uh, engine=engine, asset_class=asset_class,
                    drift=result["drift"], alert=result["alert"],
                )
                monitored += 1
                alerts += int(result["alert"])
            conn.commit()
            return {"status": "succeeded", "monitored": monitored, "alerts": alerts}
```

- [ ] **Step 4: Run the tests, expect PASS.**
  Command: `cd E:/investintell-datalake-workers && python -m pytest tests/test_gamma_drift.py -v`
  Expected: all 10 tests pass. (`monitor_gamma_drift` consumes `fetchall()` rows shaped `(gamma_loadings,)`; the fakes return nested lists which `np.asarray(..., dtype=np.float64)` converts to L×K arrays; the reader fakes never reach `_persist_drift`/`run`, so no live DB is touched.)

- [ ] **Step 5: Add the idempotent schema migration.**
  Append to `schemas/factor_model.sql` (after the existing `uq_factor_model_fits_natural` unique index block ending at line 45):

```sql
-- ---------------------------------------------------------------------------
-- T3B-3: Gamma drift columns. Procrustes-aligned relative Frobenius drift of
-- this fit's Gamma vs. the previous fit for the same (engine, asset_class,
-- universe_hash). NULL until the gamma_drift monitor runs (>= 2 fits needed).
-- Idempotent ADD COLUMN IF NOT EXISTS — safe to re-run.
-- ---------------------------------------------------------------------------
ALTER TABLE factor_model_fits
    ADD COLUMN IF NOT EXISTS gamma_drift_vs_prior NUMERIC,
    ADD COLUMN IF NOT EXISTS drift_alert          BOOLEAN;
```

- [ ] **Step 6: Apply the DDL to the cloud (manual ops step).**
  Command (run by someone holding the cloud DSN in `DATABASE_URL`):
  `cd E:/investintell-datalake-workers && psql "$DATABASE_URL" -f schemas/factor_model.sql`
  Expected: `ALTER TABLE` (idempotent; re-runnable — the surrounding `CREATE TABLE IF NOT EXISTS` / `CREATE INDEX IF NOT EXISTS` are no-ops on an existing table). This is the only step that touches live infra — the unit tests above never hit a live DB. (Open question flags whether drift belongs on the fit row vs. a separate `factor_model_drift` table; resolve before applying.)

- [ ] **Step 7: Commit.**
  Commands:
  - `cd E:/investintell-datalake-workers && git add src/workers/gamma_drift.py tests/test_gamma_drift.py schemas/factor_model.sql`
  - `git commit -m "feat(factor-model): Procrustes-aligned Gamma drift monitor + factor_model_fits drift columns (T3B-3)"`

---

## Tier 3 — Equity composite manager_score + enriched peer ranking

**Context for the executing engineer (read once).** All three tasks live in the **workers repo** `E:/investintell-datalake-workers/` (a SEPARATE git repo), not the light app. The light app NEVER recomputes quant (DB-first contract): it READS `fund_risk_latest_mv` which copies `manager_score`, `elite_flag`, `peer_*` verbatim from the worker's `fund_risk_metrics` table (confirmed: `E:/investintell-light/backend/db/ddl/2026-06-13_dynamic_catalog.sql` lines 71-73 SELECT them; `E:/investintell-light/backend/app/models/fund.py` `FundRiskLatest` lines 138-178 map them). Those columns are currently **dead** (always NULL — see `schemas/risk_metrics.sql` lines 139-151 and the comment in `risk_metrics.py` lines 740-741: "manager_score/elite_flag NÃO são computados aqui"). This cluster makes the worker POPULATE `manager_score` (equity funds only) and ENRICH the peer-ranking post-step with a quartile + a p25/median/p75 band + a cohort-size guard + a mid-rank tie convention.

The math is ported from the legacy allocation engine (READ-ONLY): the normalize/peaked helpers from `E:/investintell-allocation/backend/quant_engine/scoring_service.py` (`_normalize_with_provenance` lines 274-287, `_peaked_score` lines 266-271, the equity component bounds in `_compute_equity_score` lines 720-742, the robust-Sharpe resolution in `_resolve_sharpe_input` lines 307-334), and the peer band/quartile/tie conventions from `E:/investintell-allocation/backend/quant_engine/peer_group_service.py` (`_percentile_rank` lines 61-82 mid-rank ties, `_quartile_from_percentile` lines 85-93, `MIN_PEER_COHORT_SIZE = 10` line 57, p25/median/p75 lines 164-183).

**Weight derivation (verified against the real legacy source — do NOT invent components).** The legacy equity composite `_DEFAULT_SCORING_WEIGHTS` (`scoring_service.py` lines 94-101) has SIX components: `return_consistency` 0.20, `risk_adjusted_return` 0.25, `drawdown_control` 0.20, `information_ratio` 0.15, `flows_momentum` 0.10, `fee_efficiency` 0.10. `fund_risk_metrics` carries no expense ratio (no `fee_efficiency`) and no flows signal (no `flows_momentum`), so BOTH are dropped and the remaining FOUR risk weights (0.20/0.25/0.20/0.15, summing 0.80) are renormalized `/0.80` → `0.25 / 0.3125 / 0.25 / 0.1875` (sum exactly 1.0). There is NO 5th "robust_sharpe" component (grep of `scoring_service.py` for `robust_sharpe` hits only the `use_robust_sharpe` config flag, never a scored component); the robust-Sharpe behaviour is folded INTO `risk_adjusted_return`, which reads `sharpe_cf` first and falls back to `sharpe_1y`, exactly as legacy `_resolve_sharpe_input` does with the flag ON.

All worker tests run from the repo root: `cd E:/investintell-datalake-workers && python -m pytest <path> -v`. The pure tests (T3C-1, plus the helper tests in T3C-2/T3C-3) need NO database — they call module-level functions on synthetic dicts/lists/fake cursors. Imports use `from src.workers import manager_score as ms` / `from src.workers import risk_metrics as rm` (see existing `tests/test_risk_metrics.py` line 36 and the `_FakeConn`/`_FakeCursor` seams at lines 315-344).

Tasks are ordered by dependency: T3C-1 builds the pure scoring helpers + composite; T3C-2 adds the DB post-step that writes `manager_score`; T3C-3 enriches the peer SQL with quartile/band/cohort/tie columns.

---

### Task T3C-1: Pure equity composite `manager_score` scoring helpers

Port the normalize/peaked helpers and assemble an **equity-only** composite over the four risk inputs already present in a `fund_risk_metrics` row that have legacy weights (`return_1y`, the robust Sharpe = `sharpe_cf`→`sharpe_1y`, `max_drawdown_1y`, `information_ratio_1y`), with a peer-median opacity penalty for missing inputs. No I/O — this is a pure module unit-tested on synthetic dicts.

**Files:**
- Create: `E:/investintell-datalake-workers/src/workers/manager_score.py`
- Test: `E:/investintell-datalake-workers/tests/test_manager_score.py`
- Read-only reference: `E:/investintell-allocation/backend/quant_engine/scoring_service.py` (`_normalize_with_provenance` lines 274-287, `_peaked_score` lines 266-271, `_resolve_sharpe_input` lines 307-334, `_DEFAULT_SCORING_WEIGHTS` lines 94-101, `_compute_equity_score` bounds lines 720-742)

- [ ] **Step 1: Write the failing test.** Create `E:/investintell-datalake-workers/tests/test_manager_score.py` with the complete code below.

```python
"""Unit tests for the equity composite manager_score (pure, no DB)."""

from __future__ import annotations

import math

import pytest

from src.workers import manager_score as ms


# ── normalize ────────────────────────────────────────────────────────────────
def test_normalize_midpoint_value_scores_50():
    score, synth = ms.normalize_with_provenance(0.10, -0.20, 0.40)
    assert synth is False
    assert score == pytest.approx(50.0)


def test_normalize_clamps_above_max_to_100():
    score, synth = ms.normalize_with_provenance(0.80, -0.20, 0.40)
    assert synth is False
    assert score == 100.0


def test_normalize_clamps_below_min_to_0():
    score, synth = ms.normalize_with_provenance(-0.50, -0.20, 0.40)
    assert synth is False
    assert score == 0.0


def test_normalize_degenerate_range_returns_50():
    score, synth = ms.normalize_with_provenance(5.0, 1.0, 1.0)
    assert synth is False
    assert score == 50.0


def test_normalize_missing_with_peer_median_applies_minus_5_penalty():
    score, synth = ms.normalize_with_provenance(None, -1.0, 3.0, peer_median=60.0)
    assert synth is True
    assert score == pytest.approx(55.0)


def test_normalize_missing_peer_median_penalty_floored_at_zero():
    score, synth = ms.normalize_with_provenance(None, -1.0, 3.0, peer_median=3.0)
    assert synth is True
    assert score == 0.0


def test_normalize_missing_no_peer_median_falls_back_to_45():
    score, synth = ms.normalize_with_provenance(None, -1.0, 3.0, peer_median=None)
    assert synth is True
    assert score == 45.0


def test_normalize_nonfinite_treated_as_missing():
    score, synth = ms.normalize_with_provenance(float("nan"), -1.0, 3.0, peer_median=None)
    assert synth is True
    assert score == 45.0


# ── peaked (ported helper, retained for parity with legacy scoring_service) ────
def test_peaked_at_target_is_100():
    assert ms.peaked_score(1.0, target=1.0, half_range=1.0) == 100.0


def test_peaked_at_half_range_is_0():
    assert ms.peaked_score(2.0, target=1.0, half_range=1.0) == 0.0


def test_peaked_missing_returns_45():
    assert ms.peaked_score(None, target=1.0, half_range=1.0) == 45.0


# ── weights ──────────────────────────────────────────────────────────────────
def test_weights_sum_to_one():
    assert math.isclose(sum(ms.EQUITY_MANAGER_SCORE_WEIGHTS.values()), 1.0, abs_tol=1e-9)


def test_weights_are_legacy_renormalized():
    # Legacy risk weights 0.20/0.25/0.20/0.15 (sum 0.80) renormalized /0.80.
    assert ms.EQUITY_MANAGER_SCORE_WEIGHTS["return_consistency"] == pytest.approx(0.25)
    assert ms.EQUITY_MANAGER_SCORE_WEIGHTS["risk_adjusted_return"] == pytest.approx(0.3125)
    assert ms.EQUITY_MANAGER_SCORE_WEIGHTS["drawdown_control"] == pytest.approx(0.25)
    assert ms.EQUITY_MANAGER_SCORE_WEIGHTS["information_ratio"] == pytest.approx(0.1875)


def test_weights_have_no_fee_or_flows_or_robust_sharpe():
    # fee_efficiency / flows_momentum are unavailable in fund_risk_metrics;
    # there is no 'robust_sharpe' component in the legacy engine.
    assert "fee_efficiency" not in ms.EQUITY_MANAGER_SCORE_WEIGHTS
    assert "flows_momentum" not in ms.EQUITY_MANAGER_SCORE_WEIGHTS
    assert "robust_sharpe" not in ms.EQUITY_MANAGER_SCORE_WEIGHTS


# ── composite ────────────────────────────────────────────────────────────────
def test_composite_all_present_is_weighted_mean_in_range():
    metrics = {
        "return_1y": 0.10,
        "sharpe_1y": 1.0,
        "sharpe_cf": 1.0,
        "max_drawdown_1y": -0.25,
        "information_ratio_1y": 0.5,
    }
    result = ms.compute_equity_manager_score(metrics)
    assert result.degraded is False
    assert result.degraded_components == []
    # Every sub-score lands in [0, 100]; the composite is their weighted mean.
    expected = sum(
        result.components[name] * w
        for name, w in ms.EQUITY_MANAGER_SCORE_WEIGHTS.items()
    )
    assert result.score == pytest.approx(round(expected, 2))
    assert 0.0 <= result.score <= 100.0
    assert set(result.components) == set(ms.EQUITY_MANAGER_SCORE_WEIGHTS)


def test_composite_prefers_sharpe_cf_over_sharpe_1y_for_risk_adjusted():
    # risk_adjusted_return reads sharpe_cf when present; sharpe_1y differs but
    # must NOT change the risk_adjusted_return sub-score.
    base = {
        "return_1y": 0.10, "sharpe_1y": 0.0, "sharpe_cf": 2.0,
        "max_drawdown_1y": -0.25, "information_ratio_1y": 0.5,
    }
    r = ms.compute_equity_manager_score(base)
    # sharpe_cf=2.0 normalized on [-1, 3] -> 75.0
    assert r.components["risk_adjusted_return"] == pytest.approx(75.0)


def test_composite_falls_back_to_sharpe_1y_when_cf_missing():
    base = {
        "return_1y": 0.10, "sharpe_1y": 2.0, "sharpe_cf": None,
        "max_drawdown_1y": -0.25, "information_ratio_1y": 0.5,
    }
    r = ms.compute_equity_manager_score(base)
    # sharpe_1y=2.0 normalized on [-1, 3] -> 75.0
    assert r.components["risk_adjusted_return"] == pytest.approx(75.0)
    assert r.degraded is False  # sharpe_1y present -> not synthesized


def test_composite_both_sharpes_missing_synthesizes_risk_adjusted():
    base = {
        "return_1y": 0.10, "sharpe_1y": None, "sharpe_cf": None,
        "max_drawdown_1y": -0.25, "information_ratio_1y": 0.5,
    }
    r = ms.compute_equity_manager_score(base)
    assert r.degraded is True
    assert "risk_adjusted_return" in r.degraded_components
    # No peer_median given -> 45.0 neutral-below-midpoint fallback.
    assert r.components["risk_adjusted_return"] == pytest.approx(45.0)


def test_composite_missing_input_flags_degraded_with_opacity_penalty():
    metrics = {
        "return_1y": None, "sharpe_1y": 1.0, "sharpe_cf": 1.0,
        "max_drawdown_1y": -0.25, "information_ratio_1y": 0.5,
    }
    peer_medians = {"return_consistency": 70.0}
    r = ms.compute_equity_manager_score(metrics, peer_medians=peer_medians)
    assert r.degraded is True
    assert "return_consistency" in r.degraded_components
    # peer_median 70 - 5 opacity penalty
    assert r.components["return_consistency"] == pytest.approx(65.0)


def test_composite_score_is_rounded_to_two_decimals():
    metrics = {
        "return_1y": 0.123456, "sharpe_1y": 0.777, "sharpe_cf": 0.777,
        "max_drawdown_1y": -0.111, "information_ratio_1y": 0.333,
    }
    r = ms.compute_equity_manager_score(metrics)
    assert r.score == round(r.score, 2)
```

- [ ] **Step 2: Run it, expect FAIL.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_manager_score.py -v`. Expected failure: `ModuleNotFoundError: No module named 'src.workers.manager_score'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation.** Create `E:/investintell-datalake-workers/src/workers/manager_score.py` with the complete code below. `normalize_with_provenance` / `peaked_score` are direct ports of `scoring_service._normalize_with_provenance` (lines 274-287) / `_peaked_score` (lines 266-271). The four component bounds match `_compute_equity_score` (`return_1y ∈ [-0.20, 0.40]` line 721, robust Sharpe `∈ [-1.0, 3.0]` line 727, `max_drawdown_1y ∈ [-0.50, 0.0]` line 733, `information_ratio_1y ∈ [-1.0, 2.0]` line 739). `_resolve_sharpe` mirrors `_resolve_sharpe_input` (lines 307-334, robust path). `fee_efficiency` and `flows_momentum` are dropped (no expense ratio / no flows signal in this table) and the four legacy risk weights are renormalized to sum to 1.0.

```python
"""Equity composite manager_score — pure scoring math (no I/O).

Ported from the legacy allocation engine's scoring_service.py
(``_normalize_with_provenance`` lines 274-287, ``_peaked_score`` lines 266-271,
``_resolve_sharpe_input`` lines 307-334, ``_compute_equity_score`` bounds lines
720-742) and trimmed to the four legacy-weighted risk components that are
derivable from a fund_risk_metrics row:

    return_consistency   <- return_1y                       [-0.20, 0.40]
    risk_adjusted_return <- sharpe_cf (robust) else sharpe_1y [-1.0, 3.0]
    drawdown_control     <- max_drawdown_1y                 [-0.50, 0.0]
    information_ratio    <- information_ratio_1y            [-1.0, 2.0]

The legacy composite (``_DEFAULT_SCORING_WEIGHTS`` lines 94-101) also weights
``flows_momentum`` (0.10) and ``fee_efficiency`` (0.10); fund_risk_metrics
carries NEITHER a flows signal NOR an expense ratio, so both are dropped and
the remaining four risk weights (0.20/0.25/0.20/0.15, sum 0.80) are
renormalized /0.80 to sum to 1.0. There is no separate "robust_sharpe"
component — the robust Sharpe (Cornish-Fisher ``sharpe_cf``, falling back to
``sharpe_1y``) IS the input to ``risk_adjusted_return``, exactly as legacy
``_resolve_sharpe_input`` resolves it with use_robust_sharpe=True.

Missing inputs get a peer-median opacity penalty (peer_median - 5, floored at
0) so opaque/short-history funds rank below transparent peers with mediocre
metrics, exactly as the legacy engine does.

This module is EQUITY-ONLY: callers must gate on asset_class == 'equity'
before invoking. FI/cash/alternatives have their own (un-ported) models.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# Legacy risk weights (scoring_service._DEFAULT_SCORING_WEIGHTS lines 94-101)
# minus flows_momentum (0.10) and fee_efficiency (0.10), renormalized /0.80.
#   return_consistency   0.20 / 0.80 = 0.25
#   risk_adjusted_return 0.25 / 0.80 = 0.3125
#   drawdown_control     0.20 / 0.80 = 0.25
#   information_ratio    0.15 / 0.80 = 0.1875   (sum = 1.0)
EQUITY_MANAGER_SCORE_WEIGHTS: dict[str, float] = {
    "return_consistency": 0.25,
    "risk_adjusted_return": 0.3125,
    "drawdown_control": 0.25,
    "information_ratio": 0.1875,
}


@dataclass(frozen=True, slots=True)
class ManagerScoreResult:
    """Composite 0-100 manager_score with provenance."""

    score: float
    components: dict[str, float] = field(default_factory=dict)
    degraded: bool = False
    degraded_components: list[str] = field(default_factory=list)


def normalize_with_provenance(
    value: float | None,
    min_val: float,
    max_val: float,
    peer_median: float | None = None,
) -> tuple[float, bool]:
    """Normalize value to 0-100; returns (score, was_synthesized).

    Direct port of scoring_service._normalize_with_provenance. Missing/non-finite
    -> (peer_median - 5, True) when a peer_median is given (opacity penalty,
    floored at 0), else (45.0, True). A degenerate range (max == min) returns
    (50.0, False).
    """
    if value is None or not math.isfinite(value):
        if peer_median is not None:
            return max(0.0, min(100.0, peer_median - 5.0)), True
        return 45.0, True
    if max_val == min_val:
        return 50.0, False
    return max(0.0, min(100.0, (value - min_val) / (max_val - min_val) * 100.0)), False


def peaked_score(value: float | None, target: float, half_range: float) -> float:
    """100 at value==target, decays linearly to 0 at |value-target| >= half_range.

    Direct port of scoring_service._peaked_score. Missing/non-finite -> 45.0
    (neutral-below-midpoint, legacy convention). Retained for parity with the
    legacy helper set; not used by the four-component equity composite below.
    """
    if value is None or not math.isfinite(value):
        return 45.0
    distance = abs(value - target)
    return max(0.0, 100.0 * (1.0 - distance / half_range))


def _resolve_sharpe(metrics: dict[str, float | None]) -> float | None:
    """Robust Sharpe: sharpe_cf preferred, fall back to sharpe_1y when absent.

    Mirrors scoring_service._resolve_sharpe_input (lines 307-334) with the
    use_robust_sharpe path active.
    """
    cf = metrics.get("sharpe_cf")
    if cf is not None and math.isfinite(float(cf)):
        return float(cf)
    s1 = metrics.get("sharpe_1y")
    return float(s1) if s1 is not None and math.isfinite(float(s1)) else None


def compute_equity_manager_score(
    metrics: dict[str, float | None],
    peer_medians: dict[str, float] | None = None,
) -> ManagerScoreResult:
    """Composite equity manager_score from a fund_risk_metrics-shaped dict.

    ``metrics`` keys consumed: return_1y, sharpe_1y, sharpe_cf,
    max_drawdown_1y, information_ratio_1y. ``peer_medians`` maps component
    name -> peer-median sub-score (0-100) used for the opacity penalty on
    missing inputs.
    """
    pm = peer_medians or {}
    components: dict[str, float] = {}
    synthesized: list[str] = []

    def _num(key: str) -> float | None:
        v = metrics.get(key)
        return float(v) if v is not None and math.isfinite(float(v)) else None

    # return_consistency: trailing 1y return, [-0.20, 0.40].
    val, synth = normalize_with_provenance(
        _num("return_1y"), -0.20, 0.40, pm.get("return_consistency")
    )
    components["return_consistency"] = round(val, 2)
    if synth:
        synthesized.append("return_consistency")

    # risk_adjusted_return: robust Sharpe (cf preferred, sharpe_1y fallback),
    # [-1.0, 3.0]. Synthesized only when BOTH sharpe inputs are missing.
    sharpe = _resolve_sharpe(metrics)
    val, synth = normalize_with_provenance(
        sharpe, -1.0, 3.0, pm.get("risk_adjusted_return")
    )
    components["risk_adjusted_return"] = round(val, 2)
    if synth:
        synthesized.append("risk_adjusted_return")

    # drawdown_control: max_drawdown_1y (negative fraction), [-0.50, 0.0].
    val, synth = normalize_with_provenance(
        _num("max_drawdown_1y"), -0.50, 0.0, pm.get("drawdown_control")
    )
    components["drawdown_control"] = round(val, 2)
    if synth:
        synthesized.append("drawdown_control")

    # information_ratio: [-1.0, 2.0].
    val, synth = normalize_with_provenance(
        _num("information_ratio_1y"), -1.0, 2.0, pm.get("information_ratio")
    )
    components["information_ratio"] = round(val, 2)
    if synth:
        synthesized.append("information_ratio")

    score = sum(components[k] * w for k, w in EQUITY_MANAGER_SCORE_WEIGHTS.items())
    # Match legacy: only flag degraded for components with positive weight.
    weighted_synth = [
        name for name in synthesized
        if EQUITY_MANAGER_SCORE_WEIGHTS.get(name, 0.0) > 0.0
    ]
    return ManagerScoreResult(
        score=round(score, 2),
        components=components,
        degraded=len(weighted_synth) > 0,
        degraded_components=weighted_synth,
    )
```

- [ ] **Step 4: Run tests, expect PASS.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_manager_score.py -v`. Expected: all 20 tests pass.

- [ ] **Step 5: Commit.** `cd E:/investintell-datalake-workers && git add src/workers/manager_score.py tests/test_manager_score.py && git commit -m "feat(manager-score): pure equity composite scoring helpers (T3C-1)"`. Commit body should note: ports scoring_service normalize/peaked/resolve_sharpe helpers; equity-only; flows_momentum + fee_efficiency dropped (absent in fund_risk_metrics); four legacy risk weights renormalized to 1.0.

---

### Task T3C-2: Populate the dead `manager_score` column (worker post-step)

Wire `compute_equity_manager_score` into a DB post-step that reads the equity rows of `fund_risk_metrics` for one `calc_date`, computes per-cohort peer-median sub-scores (the opacity-penalty baseline), and UPDATEs `manager_score`. Equity gating is by `asset_class = 'equity'` from `instruments_universe` (the same join shape the existing label/peer post-step uses against the cloud replica). Add the call into `run()` next to `_update_peer_percentiles` in BOTH the serial and parallel paths.

**Files:**
- Modify: `E:/investintell-datalake-workers/src/workers/risk_metrics.py` (add `from src.workers import manager_score as _ms` after the `from src.db import ...` import at line 38; add `_MANAGER_SCORE_EQUITY_SQL`, `_MANAGER_SCORE_COMPONENT_INPUT`, `_equity_peer_medians`, `_update_manager_scores` immediately before `_update_peer_percentiles` at line 801; call `_update_manager_scores(conn, cdate)` in the serial path after line 886 and parallel path after line 919; add `"manager_score_rows": mscores,` to both result dicts after `"peer_rows": peers,` at lines 891 and 925)
- Modify: `E:/investintell-datalake-workers/schemas/risk_metrics.sql` (update the comment at lines 139-141 to mark manager_score LIVE; the column already exists at line 149 — no DDL change for it; this file is also touched in T3C-3)
- Test: `E:/investintell-datalake-workers/tests/test_risk_metrics.py` (append fake-conn unit tests after the existing `test_run_refreshes_mv_after_lock_released`, end of file at line 422; AND patch the existing `test_run_refreshes_mv_after_lock_released` to stub the new post-step)

- [ ] **Step 1: Write the failing test.** Append the code below to `E:/investintell-datalake-workers/tests/test_risk_metrics.py` (after `test_run_refreshes_mv_after_lock_released`, current end of file line 422). It exercises `_update_manager_scores` against a fake cursor returning two synthetic equity rows, asserts the UPDATE batch carries the expected composites, and asserts `run()` invokes the post-step. `_dt` is already imported at line 29.

```python
# ──────────────────────────────────────────────────────────────────────────────
# T3C-2: manager_score post-step (equity composite). No DB — fake the cursor.
# ──────────────────────────────────────────────────────────────────────────────
class _ManagerScoreCursor:
    """Fake cursor: SELECT returns canned equity rows; UPDATE batch is captured."""

    def __init__(self, select_rows, sink):
        self._select_rows = select_rows
        self._sink = sink

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False

    def execute(self, sql, params=None):
        self._sink["last_sql"] = " ".join(str(sql).split())

    def fetchall(self):
        return self._select_rows

    def executemany(self, sql, rows):
        self._sink["update_sql"] = " ".join(str(sql).split())
        self._sink["update_rows"] = list(rows)


class _ManagerScoreConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def test_update_manager_scores_writes_equity_composites():
    """Two equity rows -> two (manager_score, instrument_id, calc_date) updates,
    each a 0-100 composite from manager_score.compute_equity_manager_score."""
    from src.workers import manager_score as ms

    # row columns: instrument_id, return_1y, sharpe_1y, sharpe_cf,
    #              max_drawdown_1y, information_ratio_1y
    rows = [
        ("11111111-1111-1111-1111-111111111111", 0.10, 1.0, 1.0, -0.25, 0.5),
        ("22222222-2222-2222-2222-222222222222", -0.05, 0.0, None, -0.40, -0.2),
    ]
    sink: dict = {}
    cur = _ManagerScoreCursor(rows, sink)
    conn = _ManagerScoreConn(cur)

    # Reproduce the post-step's peer-median baseline so expected == actual.
    peer_medians = rm._equity_peer_medians(rows)
    updated = rm._update_manager_scores(conn, _dt.date(2026, 6, 11))

    assert updated == 2
    by_id = {r[1]: r[0] for r in sink["update_rows"]}
    exp0 = ms.compute_equity_manager_score(
        {"return_1y": 0.10, "sharpe_1y": 1.0, "sharpe_cf": 1.0,
         "max_drawdown_1y": -0.25, "information_ratio_1y": 0.5},
        peer_medians=peer_medians,
    ).score
    exp1 = ms.compute_equity_manager_score(
        {"return_1y": -0.05, "sharpe_1y": 0.0, "sharpe_cf": None,
         "max_drawdown_1y": -0.40, "information_ratio_1y": -0.2},
        peer_medians=peer_medians,
    ).score
    assert by_id["11111111-1111-1111-1111-111111111111"] == exp0
    assert by_id["22222222-2222-2222-2222-222222222222"] == exp1
    # Every written score is a valid 0-100 manager_score at the calc_date.
    for score, _iid, cdate in sink["update_rows"]:
        assert 0.0 <= score <= 100.0
        assert cdate == _dt.date(2026, 6, 11)
    assert "UPDATE fund_risk_metrics" in sink["update_sql"]
    assert "manager_score" in sink["update_sql"]


def test_update_manager_scores_empty_cohort_returns_zero():
    sink: dict = {}
    cur = _ManagerScoreCursor([], sink)
    conn = _ManagerScoreConn(cur)
    updated = rm._update_manager_scores(conn, _dt.date(2026, 6, 11))
    assert updated == 0
    assert "update_rows" not in sink  # nothing to write


def test_equity_peer_medians_skips_missing_inputs():
    """Median sub-score per component is taken over funds that HAVE the metric."""
    rows = [
        ("a", 0.10, 1.0, 1.0, -0.25, 0.5),
        ("b", None, 2.0, 2.0, -0.10, None),  # missing return_1y and IR
    ]
    medians = rm._equity_peer_medians(rows)
    # return_consistency only has fund 'a' -> its single sub-score is the median.
    assert "return_consistency" in medians
    # information_ratio only has fund 'a' -> present.
    assert "information_ratio" in medians
    # All medians are valid 0-100 sub-scores.
    for v in medians.values():
        assert 0.0 <= v <= 100.0


def test_run_calls_manager_score_post_step(monkeypatch):
    """Successful run() invokes _update_manager_scores once with the calc_date."""
    import contextlib

    events: list[str] = []

    def _fake_connect(dsn=None, *, autocommit=False):
        return _FakeConn({"events": events})

    monkeypatch.setattr(rm, "connect", _fake_connect)

    @contextlib.contextmanager
    def _granted_lock(_conn, _lock_id):
        yield True

    monkeypatch.setattr(rm, "advisory_lock", _granted_lock)
    monkeypatch.setattr(rm, "_resolve_calc_date", lambda _c, _cd: _dt.date(2026, 6, 11))
    monkeypatch.setattr(rm, "_risk_free_rate", lambda _c, _cd: 0.04)
    monkeypatch.setattr(rm, "_fetch_fund_ids", lambda _c, _cd, _lim: [])
    monkeypatch.setattr(rm, "_fetch_benchmark_returns", lambda _c, _cd: {})
    monkeypatch.setattr(rm, "_fetch_fund_benchmarks", lambda _c: {})
    monkeypatch.setattr(rm, "_update_peer_percentiles", lambda _c, _cd: 0)
    monkeypatch.setattr(rm, "_refresh_fund_risk_latest_mv", lambda _dsn: None)

    captured: dict = {}
    monkeypatch.setattr(
        rm, "_update_manager_scores",
        lambda _c, cdate: captured.__setitem__("calc_date", cdate) or 7,
    )

    stats = rm.run("postgres://x")
    assert captured["calc_date"] == _dt.date(2026, 6, 11)
    assert stats["manager_score_rows"] == 7
```

- [ ] **Step 2: Run it, expect FAIL.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -k "manager_score or equity_peer_medians" -v`. Expected failure: `AttributeError: module 'src.workers.risk_metrics' has no attribute '_equity_peer_medians'` (the post-step does not exist yet).

- [ ] **Step 3: Write the minimal implementation.**

  (a) In `E:/investintell-datalake-workers/src/workers/risk_metrics.py`, add the import immediately after the existing `from src.db import LOCK_RISK_METRICS, advisory_lock, connect` at line 38:

```python
from src.workers import manager_score as _ms
```

  (b) Add the SQL + helpers + post-step function immediately before `_update_peer_percentiles` (before line 801). The SELECT joins equity instruments and reads the five inputs; the UPDATE writes the composite. Peer medians are computed in Python from the cohort so the opacity penalty has a baseline (mirrors the legacy `peer_medians` semantics). `Any` and `np` are already imported at lines 34 and 36.

```python
# Equity-only manager_score post-step (T3C). Reads the five inputs already
# persisted in fund_risk_metrics for the calc_date, restricted to equity funds
# (instruments_universe.asset_class = 'equity'), computes the composite via
# src.workers.manager_score, and writes the numeric(5,2) manager_score column.
# FI/cash/alternatives are left NULL (their scoring models are not ported).
_MANAGER_SCORE_EQUITY_SQL = """
SELECT m.instrument_id, m.return_1y, m.sharpe_1y, m.sharpe_cf,
       m.max_drawdown_1y, m.information_ratio_1y
FROM fund_risk_metrics m
JOIN instruments_universe iu ON iu.instrument_id = m.instrument_id
WHERE m.calc_date = %(calc_date)s
  AND m.organization_id IS NULL
  AND iu.asset_class = 'equity'
"""

# Sub-score component -> (metric key, lo, hi) for the peer-median baseline.
# Mirrors the four weighted equity components in manager_score; the robust
# Sharpe baseline reads sharpe_1y (sharpe_cf may be sparse).
_MANAGER_SCORE_COMPONENT_INPUT = {
    "return_consistency": ("return_1y", -0.20, 0.40),
    "risk_adjusted_return": ("sharpe_1y", -1.0, 3.0),
    "drawdown_control": ("max_drawdown_1y", -0.50, 0.0),
    "information_ratio": ("information_ratio_1y", -1.0, 2.0),
}


def _equity_peer_medians(rows: list[tuple[Any, ...]]) -> dict[str, float]:
    """Median sub-score per component across the equity cohort (opacity baseline).

    Each present input is normalized to its 0-100 sub-score (no penalty), then
    the per-component median is taken. Missing inputs are skipped (the median
    is over funds that HAVE the metric), so an opaque fund is penalized against
    the median of its transparent peers — the legacy peer_medians contract.

    ``rows`` columns: (instrument_id, return_1y, sharpe_1y, sharpe_cf,
    max_drawdown_1y, information_ratio_1y).
    """
    cols = {
        "return_1y": 1, "sharpe_1y": 2, "max_drawdown_1y": 4,
        "information_ratio_1y": 5,
    }
    medians: dict[str, float] = {}
    for component, (metric, lo, hi) in _MANAGER_SCORE_COMPONENT_INPUT.items():
        idx = cols[metric]
        subs: list[float] = []
        for r in rows:
            v = r[idx]
            if v is None:
                continue
            fv = float(v)
            if not np.isfinite(fv):
                continue
            sub, _synth = _ms.normalize_with_provenance(fv, lo, hi)
            subs.append(sub)
        if subs:
            medians[component] = float(np.median(subs))
    return medians


def _update_manager_scores(conn, calc_date: _dt.date) -> int:
    """Compute & UPDATE manager_score for every equity fund at calc_date.

    Does NOT commit — the caller owns the transaction (run() commits; tests
    fake the cursor). Returns the number of rows written.
    """
    with conn.cursor() as cur:
        cur.execute(_MANAGER_SCORE_EQUITY_SQL, {"calc_date": calc_date})
        rows = cur.fetchall()
    if not rows:
        return 0
    peer_medians = _equity_peer_medians(rows)
    updates: list[tuple[float, Any, _dt.date]] = []
    for iid, ret_1y, sharpe_1y, sharpe_cf, mdd_1y, ir_1y in rows:
        result = _ms.compute_equity_manager_score(
            {
                "return_1y": float(ret_1y) if ret_1y is not None else None,
                "sharpe_1y": float(sharpe_1y) if sharpe_1y is not None else None,
                "sharpe_cf": float(sharpe_cf) if sharpe_cf is not None else None,
                "max_drawdown_1y": float(mdd_1y) if mdd_1y is not None else None,
                "information_ratio_1y": float(ir_1y) if ir_1y is not None else None,
            },
            peer_medians=peer_medians,
        )
        updates.append((result.score, iid, calc_date))
    with conn.cursor() as cur:
        cur.executemany(
            """UPDATE fund_risk_metrics
               SET manager_score = %s
               WHERE instrument_id = %s AND calc_date = %s
                 AND organization_id IS NULL""",
            updates,
        )
    return len(updates)
```

  (c) Wire it into `run()`. In the **serial path**, replace the two lines (currently 886-887):

```python
                peers = _update_peer_percentiles(conn, cdate)
                conn.commit()
```

  with:

```python
                peers = _update_peer_percentiles(conn, cdate)
                mscores = _update_manager_scores(conn, cdate)
                conn.commit()
```

  and add `"manager_score_rows": mscores,` to the serial `result` dict immediately after the `"peer_rows": peers,` line (currently line 891).

  In the **parallel path**, replace (currently 919-920):

```python
                peers = _update_peer_percentiles(conn, cdate)
                conn.commit()
```

  with:

```python
                peers = _update_peer_percentiles(conn, cdate)
                mscores = _update_manager_scores(conn, cdate)
                conn.commit()
```

  and add `"manager_score_rows": mscores,` to the parallel `result` dict immediately after its `"peer_rows": peers,` line (currently line 925).

  (d) Guard the PRE-EXISTING run() test against the new post-step. In `E:/investintell-datalake-workers/tests/test_risk_metrics.py`, inside `test_run_refreshes_mv_after_lock_released` (lines 386-421), add the following monkeypatch line immediately after the existing `monkeypatch.setattr(rm, "_update_peer_percentiles", lambda _c, _cd: 0)` (line 412). Without it, run() takes the serial path (`_fetch_fund_ids` returns `[]`) and calls the REAL `_update_manager_scores` against the `_FakeConn`, whose `_FakeCursor` has no `fetchall`, breaking the test:

```python
    monkeypatch.setattr(rm, "_update_manager_scores", lambda _c, _cd: 0)
```

  (e) In `E:/investintell-datalake-workers/schemas/risk_metrics.sql`, update the comment at lines 139-141 so the LIVE status is recorded — change:

```sql
--   * manager_score / elite_flag / equity_correlation_252d: reservadas — o
--     modelo de scoring do projeto allocation ainda não foi portado; ficam
--     NULL até existir worker próprio (UI mostra "—").
```

  to:

```sql
--   * manager_score (numeric(5,2)): LIVE (T3C) — composite equity score written
--     by _update_manager_scores() post-step (equity funds only); NULL for
--     non-equity funds.
--   * equity_correlation_252d: LIVE (computed by relative_metrics_for).
--   * elite_flag: reservada — sem threshold definido; fica NULL.
```

- [ ] **Step 4: Run tests, expect PASS.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -k "manager_score or equity_peer_medians" -v`. Expected: the four new tests pass. Then run the whole module to confirm no regression: `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -v`. The DB-requiring tests (`test_run_end_to_end_and_idempotent`, `test_recalc_vs_legacy`, `test_advisory_lock_is_distinct`, `test_peer_percentiles_set_based`) self-skip when the DB-mãe is unreachable (per the file docstring); every monkeypatched/fake-conn test — including the now-guarded `test_run_refreshes_mv_after_lock_released` — must pass.

- [ ] **Step 5: Commit.** `cd E:/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py schemas/risk_metrics.sql && git commit -m "feat(manager-score): populate equity manager_score in risk_metrics run (T3C-2)"`.

---

### Task T3C-3: Enrich peer ranking SQL — quartile + p25/median/p75 band + cohort guard + mid-rank ties

Enrich the worker's peer post-step so each ranked fund also carries a quartile (1=best..4=worst), a p25/median/p75 band of `sharpe_1y` per cohort, an explicit cohort-size guard (cohorts below `MIN_PEER_COHORT_SIZE=10` degrade to the median percentile 50 / second quartile), and the mid-rank tie convention (`percent_rank()` over-ranks ties — replace with the institutional `(below + 0.5*equal)/N` rule so an all-tied cohort sits at 50, not 100). Add the new columns to the schema and extend `_PEER_PERCENTILES_SQL`.

**Files:**
- Modify: `E:/investintell-datalake-workers/src/workers/risk_metrics.py` (add `MIN_PEER_COHORT_SIZE`, `_peer_quartile_from_percentile`, `_peer_midrank_percentile` immediately before `_PEER_PERCENTILES_SQL` at line 742; rewrite `_PEER_PERCENTILES_SQL` lines 742-798 to switch each percentile CTE from `percent_rank()` to the mid-rank formula, add a quartile expression, add a `bands` CTE over `sharpe_1y`, and a cohort-size guard; update `_update_peer_percentiles` lines 801-809 to pass the `min_cohort` bind)
- Modify: `E:/investintell-datalake-workers/schemas/risk_metrics.sql` (add `peer_overall_quartile`, `peer_band_low`, `peer_band_mid`, `peer_band_high` columns after line 151)
- Read-only reference: `E:/investintell-allocation/backend/quant_engine/peer_group_service.py` (`_percentile_rank` lines 61-82, `_quartile_from_percentile` lines 85-93, `MIN_PEER_COHORT_SIZE` line 57, p25/median/p75 lines 164-183)
- Test: `E:/investintell-datalake-workers/tests/test_risk_metrics.py` (append pure-helper + SQL-shape tests after the T3C-2 block)

- [ ] **Step 1: Write the failing test.** Append the code below to `E:/investintell-datalake-workers/tests/test_risk_metrics.py` (after the T3C-2 block). The pure-helper tests assert the ported quartile + mid-rank conventions on a Python re-expression of the SQL math (no DB); the constant-string test asserts the enriched SQL references the new columns/conventions.

```python
# ──────────────────────────────────────────────────────────────────────────────
# T3C-3: enriched peer ranking — quartile + band + cohort guard + mid-rank ties.
# Pure-helper tests (no DB) for the ported conventions, plus an SQL-shape guard.
# ──────────────────────────────────────────────────────────────────────────────
def test_peer_quartile_from_percentile_boundaries():
    assert rm._peer_quartile_from_percentile(100.0) == 1
    assert rm._peer_quartile_from_percentile(75.0) == 1
    assert rm._peer_quartile_from_percentile(74.99) == 2
    assert rm._peer_quartile_from_percentile(50.0) == 2
    assert rm._peer_quartile_from_percentile(49.99) == 3
    assert rm._peer_quartile_from_percentile(25.0) == 3
    assert rm._peer_quartile_from_percentile(24.99) == 4
    assert rm._peer_quartile_from_percentile(0.0) == 4


def test_midrank_percentile_all_tied_is_50_not_100():
    # All-tied cohort: every member sits at the median (50.0), the institutional
    # convention — percent_rank() would put them all at 0.
    peers = [1.0, 1.0, 1.0, 1.0]
    assert rm._peer_midrank_percentile(1.0, peers, higher_is_better=True) == 50.0


def test_midrank_percentile_best_value_high():
    peers = [0.1, 0.2, 0.3, 0.4, 0.5]
    # value strictly above all peers -> (5 below + 0)/5 = 100.
    assert rm._peer_midrank_percentile(0.9, peers, higher_is_better=True) == 100.0


def test_midrank_percentile_drawdown_less_negative_ranks_higher():
    # Drawdown uses higher_is_better=True (less-negative = larger numeric =
    # better), matching the existing SQL (ORDER BY max_drawdown_1y ASC ->
    # higher value = higher pctl).
    peers = [-0.40, -0.30, -0.20, -0.10]
    p_best = rm._peer_midrank_percentile(-0.05, peers, higher_is_better=True)
    p_worst = rm._peer_midrank_percentile(-0.50, peers, higher_is_better=True)
    assert p_best > p_worst


def test_midrank_percentile_empty_cohort_returns_50():
    assert rm._peer_midrank_percentile(1.0, [], higher_is_better=True) == 50.0


def test_enriched_peer_sql_has_quartile_band_and_cohort_guard():
    sql = rm._PEER_PERCENTILES_SQL.lower()
    # New target columns are written.
    assert "peer_overall_quartile" in sql
    assert "peer_band_low" in sql
    assert "peer_band_mid" in sql
    assert "peer_band_high" in sql
    # Cohort guard uses the institutional minimum (passed as a bind).
    assert "min_cohort" in sql
    # Mid-rank tie convention: count_below + 0.5 * count_equal.
    assert "0.5" in sql
    # Band uses percentile_cont over sharpe_1y (p25/median/p75).
    assert "percentile_cont" in sql
    # percent_rank() is no longer the ranking mechanism.
    assert "percent_rank" not in sql


def test_min_peer_cohort_size_matches_legacy():
    # Ported from peer_group_service.MIN_PEER_COHORT_SIZE = 10.
    assert rm.MIN_PEER_COHORT_SIZE == 10
```

- [ ] **Step 2: Run it, expect FAIL.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -k "peer_quartile or midrank or enriched_peer or min_peer_cohort" -v`. Expected failure: `AttributeError: module 'src.workers.risk_metrics' has no attribute '_peer_quartile_from_percentile'` (and the SQL-shape test fails because the new columns are not in `_PEER_PERCENTILES_SQL` yet, and `percent_rank` is still present).

- [ ] **Step 3: Write the minimal implementation.** In `E:/investintell-datalake-workers/src/workers/risk_metrics.py`:

  (a) Add the institutional cohort constant and the two pure helpers immediately before `_PEER_PERCENTILES_SQL` (before line 742, after the existing comment block at lines 734-741):

```python
# Institutional peer-cohort minimum (ported from the allocation engine's
# peer_group_service.MIN_PEER_COHORT_SIZE = 10, line 57). Cohorts below this
# degrade to the median percentile (50) / second quartile — a fund cannot be
# ranked credibly against fewer than 10 peers.
MIN_PEER_COHORT_SIZE = 10


def _peer_quartile_from_percentile(percentile: float) -> int:
    """Map a 0-100 percentile to a quartile (1=best .. 4=worst).

    Direct port of peer_group_service._quartile_from_percentile (lines 85-93).
    """
    if percentile >= 75:
        return 1
    if percentile >= 50:
        return 2
    if percentile >= 25:
        return 3
    return 4


def _peer_midrank_percentile(
    value: float, peers: list[float], higher_is_better: bool
) -> float:
    """Mid-rank percentile (0-100), Morningstar/eVestment tie convention.

    Each tied value contributes 0.5 to the rank so an all-tied cohort ranks at
    the median (50.0), not 100.0. Ported from peer_group_service._percentile_rank
    (lines 61-82). This is the Python mirror of the SQL the post-step runs, kept
    in lock-step so the conventions are unit-tested without a database.
    """
    n = len(peers)
    if n == 0:
        return 50.0
    if higher_is_better:
        below = sum(1 for p in peers if p < value)
    else:
        below = sum(1 for p in peers if p > value)
    equal = sum(1 for p in peers if p == value)
    return round((below + 0.5 * equal) / n * 100.0, 2)
```

  (b) Replace `_PEER_PERCENTILES_SQL` (lines 742-798) with the enriched version below. Each percentile CTE now uses the mid-rank formula (count of strictly-better + 0.5 × count-of-ties, over the matched-on-non-null cohort size) instead of `percent_rank()`; a `bands` CTE computes p25/median/p75 of `sharpe_1y` per label; the `guarded` CTE applies the cohort-size guard (percentile 50 when `peer_count < %(min_cohort)s`); the UPDATE writes the new columns and derives the quartile from the guarded Sharpe percentile. The original UPDATE's `lt` alias for `latest` is preserved. The `%(min_cohort)s` bind is passed by `_update_peer_percentiles` in step (c).

```python
_PEER_PERCENTILES_SQL = """
WITH labels AS (
    SELECT DISTINCT ON (source_pk)
           source_pk::uuid AS instrument_id,
           proposed_strategy_label AS label
    FROM strategy_reclassification_stage
    WHERE source_table = 'instruments_universe'
      AND proposed_strategy_label IS NOT NULL
    ORDER BY source_pk, classified_at DESC
),
latest AS (
    SELECT m.instrument_id, m.sharpe_1y, m.sortino_1y, m.return_1y,
           m.max_drawdown_1y, l.label
    FROM fund_risk_metrics m
    JOIN labels l ON l.instrument_id = m.instrument_id
    WHERE m.calc_date = %(calc_date)s AND m.organization_id IS NULL
),
counts AS (
    SELECT label, count(*) AS peer_count FROM latest GROUP BY label
),
bands AS (
    SELECT label,
           percentile_cont(0.25) WITHIN GROUP (ORDER BY sharpe_1y) AS band_low,
           percentile_cont(0.50) WITHIN GROUP (ORDER BY sharpe_1y) AS band_mid,
           percentile_cont(0.75) WITHIN GROUP (ORDER BY sharpe_1y) AS band_high
    FROM latest WHERE sharpe_1y IS NOT NULL GROUP BY label
),
sharpe AS (
    SELECT a.instrument_id, round((
        (count(*) FILTER (WHERE b.sharpe_1y < a.sharpe_1y)
         + 0.5 * count(*) FILTER (WHERE b.sharpe_1y = a.sharpe_1y))
        / count(*)::numeric) * 100, 2) AS p
    FROM latest a JOIN latest b ON b.label = a.label AND b.sharpe_1y IS NOT NULL
    WHERE a.sharpe_1y IS NOT NULL
    GROUP BY a.instrument_id, a.sharpe_1y
),
sortino AS (
    SELECT a.instrument_id, round((
        (count(*) FILTER (WHERE b.sortino_1y < a.sortino_1y)
         + 0.5 * count(*) FILTER (WHERE b.sortino_1y = a.sortino_1y))
        / count(*)::numeric) * 100, 2) AS p
    FROM latest a JOIN latest b ON b.label = a.label AND b.sortino_1y IS NOT NULL
    WHERE a.sortino_1y IS NOT NULL
    GROUP BY a.instrument_id, a.sortino_1y
),
ret AS (
    SELECT a.instrument_id, round((
        (count(*) FILTER (WHERE b.return_1y < a.return_1y)
         + 0.5 * count(*) FILTER (WHERE b.return_1y = a.return_1y))
        / count(*)::numeric) * 100, 2) AS p
    FROM latest a JOIN latest b ON b.label = a.label AND b.return_1y IS NOT NULL
    WHERE a.return_1y IS NOT NULL
    GROUP BY a.instrument_id, a.return_1y
),
dd AS (
    SELECT a.instrument_id, round((
        (count(*) FILTER (WHERE b.max_drawdown_1y < a.max_drawdown_1y)
         + 0.5 * count(*) FILTER (WHERE b.max_drawdown_1y = a.max_drawdown_1y))
        / count(*)::numeric) * 100, 2) AS p
    FROM latest a JOIN latest b
      ON b.label = a.label AND b.max_drawdown_1y IS NOT NULL
    WHERE a.max_drawdown_1y IS NOT NULL
    GROUP BY a.instrument_id, a.max_drawdown_1y
),
guarded AS (
    SELECT lt.instrument_id, lt.label, c.peer_count,
           CASE WHEN c.peer_count < %(min_cohort)s THEN 50.0 ELSE s.p  END AS sharpe_p,
           CASE WHEN c.peer_count < %(min_cohort)s THEN 50.0 ELSE so.p END AS sortino_p,
           CASE WHEN c.peer_count < %(min_cohort)s THEN 50.0 ELSE r.p  END AS return_p,
           CASE WHEN c.peer_count < %(min_cohort)s THEN 50.0 ELSE d.p  END AS dd_p,
           bd.band_low, bd.band_mid, bd.band_high
    FROM latest lt
    JOIN counts c ON c.label = lt.label
    LEFT JOIN bands bd ON bd.label = lt.label
    LEFT JOIN sharpe s ON s.instrument_id = lt.instrument_id
    LEFT JOIN sortino so ON so.instrument_id = lt.instrument_id
    LEFT JOIN ret r ON r.instrument_id = lt.instrument_id
    LEFT JOIN dd d ON d.instrument_id = lt.instrument_id
)
UPDATE fund_risk_metrics m
SET peer_strategy_label   = g.label,
    peer_sharpe_pctl      = g.sharpe_p,
    peer_sortino_pctl     = g.sortino_p,
    peer_return_pctl      = g.return_p,
    peer_drawdown_pctl    = g.dd_p,
    peer_count            = g.peer_count,
    peer_overall_quartile = CASE
        WHEN g.sharpe_p >= 75 THEN 1
        WHEN g.sharpe_p >= 50 THEN 2
        WHEN g.sharpe_p >= 25 THEN 3
        ELSE 4 END,
    peer_band_low         = g.band_low,
    peer_band_mid         = g.band_mid,
    peer_band_high        = g.band_high
FROM guarded g
WHERE m.instrument_id = g.instrument_id
  AND m.calc_date = %(calc_date)s
  AND m.organization_id IS NULL
"""
```

  (c) Update `_update_peer_percentiles` (lines 801-809) to pass the `min_cohort` bind:

```python
def _update_peer_percentiles(conn, calc_date: _dt.date) -> int:
    """Set-based peer-percentile refresh for one calc_date; returns rows updated.

    Does NOT commit — the caller owns the transaction (run() commits; tests
    roll back). Now writes quartile + p25/median/p75 band of sharpe_1y and
    applies the MIN_PEER_COHORT_SIZE guard (percentile 50 / quartile 2 for
    cohorts smaller than 10).
    """
    with conn.cursor() as cur:
        cur.execute(
            _PEER_PERCENTILES_SQL,
            {"calc_date": calc_date, "min_cohort": MIN_PEER_COHORT_SIZE},
        )
        return cur.rowcount
```

  (d) Add the new columns to `E:/investintell-datalake-workers/schemas/risk_metrics.sql` after line 151 (`equity_correlation_252d`):

```sql
-- Enriched peer ranking (T3C): quartile + p25/median/p75 band of sharpe_1y
-- within the peer_strategy_label cohort. peer_overall_quartile derives from
-- peer_sharpe_pctl (1=best..4=worst); band columns are absolute sharpe_1y
-- quantiles for the cohort. Cohorts below 10 funds degrade to pctl 50 / Q2.
-- NOTE: not yet surfaced to the Light app — fund_risk_latest_mv + the
-- FundRiskLatest model need a follow-up migration to SELECT/map these.
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS peer_overall_quartile smallint;
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS peer_band_low numeric(10,6);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS peer_band_mid numeric(10,6);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS peer_band_high numeric(10,6);
```

- [ ] **Step 4: Run tests, expect PASS.** Run `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -k "peer_quartile or midrank or enriched_peer or min_peer_cohort" -v`. Expected: the seven new tests pass. Then run the full module: `cd E:/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -v`. The DB-backed `test_peer_percentiles_set_based` (lines 198-255) self-skips when the DB-mãe is unreachable; when a DB IS available it must still pass — the enriched SQL is a strict superset: it still writes `peer_sharpe_pctl`, `peer_drawdown_pctl`, `peer_count`; the best-Sharpe-in-group still ranks 100 (no top tie in Large Blend); the monotonic-by-Sharpe-desc and least-negative-drawdown assertions hold under mid-rank ranking; and `Large Blend` has >=10 funds so the cohort guard does not fire.

- [ ] **Step 5: Commit.** `cd E:/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py schemas/risk_metrics.sql && git commit -m "feat(peer-ranking): quartile + band + cohort guard + mid-rank ties (T3C-3)"`.

---

## Tier 3 — Two-tier drift bands + downside/semi-deviation + expense-ratio unit normalization

This cluster ports three independent techniques from the legacy `quant_engine` into the Light app. Each task is self-contained TDD. The three tasks are fully independent of one another (no shared new symbols), so they may be executed in any order or in parallel. Run all commands from `E:/investintell-light/backend` unless stated otherwise. The pytest config is `asyncio_mode = "auto"` (`pyproject.toml`), tests live flat under `backend/tests/`, and the project scale contract is decimal fractions (0.05 = 5%).

Gate G5 (μ-free) is respected: none of these tasks introduce an expected-return estimate. T3D-1 only classifies drift magnitudes; T3D-2 adds downside/semi-deviation dispersion measures (no mean-return objective); T3D-3 normalizes a fee unit. None touch the optimizer objective.

Source provenance (all re-read against the real files for this hardening pass):
- Two-tier classifier: `E:/investintell-allocation/backend/quant_engine/drift_service.py`, `compute_block_drifts` lines 137-184 (`urgent` when `|abs_drift| >= urgent_trigger`, else `maintenance` when `>= maintenance_trigger`, else `ok`).
- Downside/semi deviation: `E:/investintell-allocation/backend/quant_engine/return_statistics_service.py`, `_compute_downside_deviation` lines 159-167 and `_compute_semi_deviation` lines 170-179.
- Expense-ratio normalizer: `E:/investintell-allocation/backend/quant_engine/expense_ratio_validator.py`, `to_decimal_fraction` lines 44-137.

---

### Task T3D-1: Two-tier drift classification (ok / maintenance / urgent) in the rebalance evaluator

Ports the legacy three-state status into the Light single-boolean `PositionDrift`. The existing `breach` boolean is preserved (it becomes `breach == status in {"maintenance","urgent"}`) so nothing downstream breaks; a new `status` field and a derived `urgent` band are added. The urgent band defaults to `2 x band_abs` clamped to `<= 1.0` (see open question 3).

**Files:**
- Modify: `backend/app/rebalance/evaluator.py` — band-default constants at lines 56-60; dataclass `PositionDrift` lines 67-75; pure-core section starts at line 96 with `calendar_due` at line 101; `compute_drifts` lines 125-151; `evaluate_portfolio` call to `compute_drifts` at line 338.
- Modify: `backend/app/schemas/rebalance.py` — `PositionDriftOut` lines 34-40 (`Literal` already imported at line 8).
- Modify: `backend/app/api/routes/rebalance.py` — `PositionDriftOut(...)` construction lines 148-155.
- Test: `backend/tests/test_rebalance.py` — extend; the module already imports `from app.rebalance import evaluator as ev` (line 28) and `pytest` (line 21); existing drift tests at lines 87-111; existing preview test asserting `breach` at line 232.

- [ ] **Step 1: Write the failing tests.** Append these to `backend/tests/test_rebalance.py`:

```python
# ---------------------------------------------------------------------------
# T3D-1 — two-tier drift classification (ok / maintenance / urgent)
# ---------------------------------------------------------------------------


def test_drift_status_default_urgent_is_twice_band_abs() -> None:
    assert ev.default_urgent_band(0.05) == pytest.approx(0.10)
    assert ev.default_urgent_band(0.25) == pytest.approx(0.50)
    # never exceeds a full 100% drift
    assert ev.default_urgent_band(0.60) == pytest.approx(1.0)


def test_compute_drifts_classifies_three_tiers() -> None:
    current = {"OK": 0.41, "MAINT": 0.47, "URG": 0.62}
    target = {"OK": 0.40, "MAINT": 0.40, "URG": 0.40}
    drifts = ev.compute_drifts(
        current, target, band_abs=0.05, band_rel=0.25, band_urgent=0.10
    )
    by = {d.ticker: d for d in drifts}
    # |0.01| < 0.05 -> ok, not a breach
    assert by["OK"].status == "ok"
    assert by["OK"].breach is False
    # 0.05 <= |0.07| < 0.10 -> maintenance, still a breach
    assert by["MAINT"].status == "maintenance"
    assert by["MAINT"].breach is True
    # |0.22| >= 0.10 -> urgent, a breach
    assert by["URG"].status == "urgent"
    assert by["URG"].breach is True


def test_compute_drifts_status_boundaries_are_inclusive() -> None:
    # exactly at the maintenance band -> maintenance; exactly at urgent -> urgent
    drifts = ev.compute_drifts(
        {"M": 0.45, "U": 0.50}, {"M": 0.40, "U": 0.40},
        band_abs=0.05, band_rel=10.0, band_urgent=0.10,
    )
    by = {d.ticker: d for d in drifts}
    assert by["M"].status == "maintenance"  # |0.05| == band_abs (inclusive)
    assert by["U"].status == "urgent"       # |0.10| == band_urgent (inclusive)


def test_compute_drifts_relative_only_breach_is_maintenance() -> None:
    # small abs drift but big relative drift -> breach, classified maintenance
    drifts = ev.compute_drifts(
        {"X": 0.08, "Y": 0.92}, {"X": 0.05, "Y": 0.95},
        band_abs=0.05, band_rel=0.25, band_urgent=0.10,
    )
    x = next(d for d in drifts if d.ticker == "X")
    assert abs(x.drift_abs) < 0.05          # below the absolute maintenance band
    assert x.drift_rel == pytest.approx(0.60)
    assert x.breach is True
    assert x.status == "maintenance"


def test_compute_drifts_defaults_urgent_when_band_urgent_omitted() -> None:
    # band_urgent omitted -> defaults to 2 x band_abs (= 0.10 here)
    drifts = ev.compute_drifts(
        {"A": 0.62}, {"A": 0.40}, band_abs=0.05, band_rel=0.25
    )
    assert drifts[0].status == "urgent"
```

  Note on `test_compute_drifts_relative_only_breach_is_maintenance`: the inputs match the EXISTING `test_compute_drifts_rel_only_breach` (lines 102-111). That existing test only asserts `breach is True`; this new one additionally pins `status == "maintenance"`. Keeping both is intentional — the existing test keeps passing unchanged, the new one pins the new field.

- [ ] **Step 2: Run the tests, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_rebalance.py -k "drift_status or three_tiers or status_boundaries or relative_only_breach or defaults_urgent" -v`
  Expected failure: `AttributeError: module 'app.rebalance.evaluator' has no attribute 'default_urgent_band'`, then (after that is added) `TypeError: compute_drifts() got an unexpected keyword argument 'band_urgent'` and `AttributeError: 'PositionDrift' object has no attribute 'status'`.

- [ ] **Step 3: Implement the minimal change in `backend/app/rebalance/evaluator.py`.**

  3a. Add a constant after `DEFAULT_BAND_REL = 0.25` (line 58). Replace the line:
```python
DEFAULT_BAND_REL = 0.25   # 25% do peso-alvo
```
  with:
```python
DEFAULT_BAND_REL = 0.25   # 25% do peso-alvo
# Banda "urgent" = 2× a banda de manutenção (T3D-1), travada em 100% de drift.
# Espelha drift_service.urgent_trigger (0.10) quando band_abs é o default 0.05.
DEFAULT_URGENT_MULTIPLE = 2.0
```

  3b. Add the helper and a type alias just before `def calendar_due(` (line 101). Insert immediately after the section header comment block that ends at line 98 (`# Pure decision core`):
```python
DriftStatus = str  # "ok" | "maintenance" | "urgent"


def default_urgent_band(band_abs: float) -> float:
    """Banda urgent default = 2× banda de manutenção, travada em 1.0 (100%)."""
    return min(band_abs * DEFAULT_URGENT_MULTIPLE, 1.0)
```

  3c. Add the `status` field to `PositionDrift`. Replace the dataclass body (lines 67-75):
```python
@dataclass(frozen=True)
class PositionDrift:
    ticker: str
    current_weight: float
    target_weight: float
    drift_abs: float            # current − target (fração decimal, sinal)
    drift_rel: float | None     # |drift_abs| / target; None quando target = 0
    breach: bool
    status: DriftStatus         # "ok" | "maintenance" | "urgent"
```

  3d. Replace `compute_drifts` (lines 125-151) so it computes the three-tier status. `breach` stays True iff status is not `"ok"` (preserves the abs-OR-rel breach semantics — a relative-only breach is classified `maintenance`):
```python
def compute_drifts(
    current: dict[str, float],
    target: dict[str, float],
    band_abs: float,
    band_rel: float,
    band_urgent: float | None = None,
) -> list[PositionDrift]:
    """Drift por posição com classificação em três faixas (T3D-1).

    status:
      "urgent"      — |drift_abs| >= band_urgent (faixa crítica)
      "maintenance" — breach de banda (abs >= band_abs OU rel > band_rel)
                      mas abaixo da banda urgent
      "ok"          — nenhuma banda violada
    breach == status in {"maintenance", "urgent"} (compat. retroativa).
    band_urgent default = default_urgent_band(band_abs) = 2× band_abs.
    """
    urgent = band_urgent if band_urgent is not None else default_urgent_band(band_abs)
    drifts: list[PositionDrift] = []
    for ticker in sorted(set(current) | set(target)):
        cur = current.get(ticker, 0.0)
        tgt = target.get(ticker, 0.0)
        drift_abs = cur - tgt
        drift_rel = abs(drift_abs) / tgt if tgt > 0 else None
        abs_breach = abs(drift_abs) >= band_abs
        rel_breach = drift_rel is not None and drift_rel > band_rel
        if abs(drift_abs) >= urgent:
            status: DriftStatus = "urgent"
        elif abs_breach or rel_breach:
            status = "maintenance"
        else:
            status = "ok"
        drifts.append(
            PositionDrift(
                ticker=ticker,
                current_weight=cur,
                target_weight=tgt,
                drift_abs=drift_abs,
                drift_rel=drift_rel,
                breach=status != "ok",
                status=status,
            )
        )
    return drifts
```
  Boundary-change note (verified against the existing tests): the previous single-boolean breach used STRICT `>` for the absolute band (`abs(drift_abs) > band_abs`, line 138). The legacy `drift_service` three-tier classifier uses INCLUSIVE `>=` (lines 168-171). T3D-1 adopts the legacy inclusive convention (`abs_breach = abs(drift_abs) >= band_abs`). This does NOT regress the existing tests: `test_compute_drifts_flags_abs_and_rel_breaches` (line 87) has VTI drift 0.06 and AGG drift 0.08, both strictly `> 0.05` so still breaches; `test_compute_drifts_rel_only_breach` (line 102) breaches on the relative band, unaffected by the abs comparator. The existing preview test (`test_preview_no_policy_uses_defaults_and_reports_drift`, asserts `drifts["FUNDX"]["breach"] is True` at line 232) has a 10pp drift which is `>= band_abs` and equals the default urgent band, so it stays a breach (now classified `urgent`).

  3e. In `evaluate_portfolio`, pass the urgent band through. Replace line 338:
```python
    drifts = compute_drifts(current, target, band_abs, band_rel)
```
  with:
```python
    drifts = compute_drifts(
        current, target, band_abs, band_rel, default_urgent_band(band_abs)
    )
```

- [ ] **Step 4: Surface `status` through the API schema and route.**

  4a. In `backend/app/schemas/rebalance.py`, add `status` to `PositionDriftOut`. Replace lines 34-40:
```python
class PositionDriftOut(BaseModel):
    ticker: str
    current_weight: float
    target_weight: float
    drift_abs: float
    drift_rel: float | None
    breach: bool
    status: Literal["ok", "maintenance", "urgent"]
```
  (`Literal` is already imported at line 8: `from typing import Literal`.)

  4b. In `backend/app/api/routes/rebalance.py`, pass `status=d.status`. Replace the `PositionDriftOut(...)` block (lines 148-155):
```python
            PositionDriftOut(
                ticker=d.ticker,
                current_weight=d.current_weight,
                target_weight=d.target_weight,
                drift_abs=d.drift_abs,
                drift_rel=d.drift_rel,
                breach=d.breach,
                status=d.status,
            )
```

- [ ] **Step 5: Run the new tests plus the full rebalance suite, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_rebalance.py -v`
  Expected: all T3D-1 tests pass AND the pre-existing tests (`test_compute_drifts_flags_abs_and_rel_breaches`, `test_compute_drifts_rel_only_breach`, `test_preview_no_policy_uses_defaults_and_reports_drift`, etc.) still pass. The preview test passes because the evaluator now always supplies `status` and the route forwards it.

- [ ] **Step 6: Commit.** Commands:
  `cd backend && git add app/rebalance/evaluator.py app/schemas/rebalance.py app/api/routes/rebalance.py tests/test_rebalance.py`
  `git commit -m "feat(rebalance): two-tier drift bands (ok/maintenance/urgent) on PositionDrift"`

---

### Task T3D-2: `downside_deviation` and `semi_deviation` pure functions in analytics/risk

Ports `return_statistics_service._compute_downside_deviation` (lines 159-167: `sqrt(mean(min(R-MAR,0)^2))`, N denominator) and `_compute_semi_deviation` (lines 170-179: same with `mean(R)` as the threshold) into `app/analytics/risk.py`, adapted to the Light fail-loud pandas convention (raise `ValueError` on `< 2` points or NaN, never return `None`/NaN — the legacy returns `None` on `< 2`). MAR is a per-period decimal fraction.

**Files:**
- Modify: `backend/app/analytics/risk.py` — add two functions immediately after `annualized_volatility` (ends at line 61) and before `historical_var` (line 64); reuse `reject_nan` (imported at line 17), `np` (line 14), `pd` (line 15).
- Modify: `backend/app/analytics/__init__.py` — the `from app.analytics.risk import (...)` block at lines 30-40 (currently: `BestWorst, DrawdownResult, annualized_volatility, best_worst_day, beta, correlation, historical_cvar, historical_var, max_drawdown`); and `__all__` at lines 47-77 (`diversification_ratio` at line 61, `risk_contributions` at line 69).
- Test: `backend/tests/test_analytics_risk.py` — extend; `math` imported at line 3; `_dated` helper at lines 20-21; import block at lines 9-17.

- [ ] **Step 1: Write the failing tests.** First, update the import block in `backend/tests/test_analytics_risk.py` (replace lines 9-17):
```python
from app.analytics import (
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    downside_deviation,
    historical_cvar,
    historical_var,
    max_drawdown,
    semi_deviation,
)
```
  Then append these tests:
```python
# --- downside / semi deviation (T3D-2) ---------------------------------------


def test_downside_deviation_only_counts_shortfalls() -> None:
    # returns: two below MAR=0, one above. shortfalls: -0.02, 0, -0.04
    # sqrt(mean([0.02^2, 0, 0.04^2])) = sqrt((0.0004 + 0 + 0.0016) / 3)
    r = _dated([-0.02, 0.05, -0.04])
    expected = math.sqrt((0.02**2 + 0.0**2 + 0.04**2) / 3)
    assert downside_deviation(r) == pytest.approx(expected)


def test_downside_deviation_zero_when_all_returns_at_or_above_mar() -> None:
    r = _dated([0.01, 0.02, 0.0, 0.03])
    assert downside_deviation(r, mar=0.0) == pytest.approx(0.0)


def test_downside_deviation_respects_nonzero_mar() -> None:
    # MAR = 0.01: shortfalls vs 0.01 -> (0.00, -0.02, -0.03)
    r = _dated([0.01, -0.01, -0.02])
    expected = math.sqrt((0.0**2 + 0.02**2 + 0.03**2) / 3)
    assert downside_deviation(r, mar=0.01) == pytest.approx(expected)


def test_downside_deviation_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        downside_deviation(_dated([0.01]))


def test_downside_deviation_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        downside_deviation(_dated([0.01, float("nan"), -0.02]))


def test_semi_deviation_uses_mean_as_threshold() -> None:
    # mean of [0.02, -0.01, 0.05, -0.03] = 0.0075
    # shortfalls below mean: (0.02-0.0075)>0 ->0, (-0.01-0.0075)=-0.0175,
    #   (0.05-0.0075)>0 ->0, (-0.03-0.0075)=-0.0375
    r = _dated([0.02, -0.01, 0.05, -0.03])
    mean_r = (0.02 - 0.01 + 0.05 - 0.03) / 4
    shortfalls = [min(x - mean_r, 0.0) for x in [0.02, -0.01, 0.05, -0.03]]
    expected = math.sqrt(sum(s**2 for s in shortfalls) / 4)
    assert semi_deviation(r) == pytest.approx(expected)


def test_semi_deviation_zero_for_constant_series() -> None:
    # constant series: every point equals the mean -> no shortfall
    assert semi_deviation(_dated([0.01, 0.01, 0.01, 0.01])) == pytest.approx(0.0)


def test_semi_deviation_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        semi_deviation(_dated([0.01]))


def test_semi_deviation_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        semi_deviation(_dated([0.01, float("nan")]))
```

- [ ] **Step 2: Run the tests, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_analytics_risk.py -k "downside or semi" -v`
  Expected failure: `ImportError: cannot import name 'downside_deviation' from 'app.analytics'`.

- [ ] **Step 3: Implement the two functions in `backend/app/analytics/risk.py`.** Insert immediately after `annualized_volatility` (after line 61) and before `def historical_var(` (line 64):
```python
def downside_deviation(returns: pd.Series, mar: float = 0.0) -> float:
    """Downside deviation below a Minimum Acceptable Return (MAR).

    ``sqrt(mean(min(R - MAR, 0)^2))`` over the full sample (N denominator,
    not N-1) — only shortfalls below ``mar`` contribute; upside is treated as
    zero. ``mar`` and inputs/result are per-period decimal fractions
    (0.05 = 5%), never 0-100. Mirrors the eVestment MAR-based downside
    deviation (legacy return_statistics_service._compute_downside_deviation).

    Raises:
        ValueError: if fewer than 2 returns are supplied or the input contains
            NaN values.
    """
    if len(returns) < 2:
        raise ValueError(
            f"downside_deviation requires at least 2 returns, got {len(returns)}"
        )
    reject_nan(returns, "downside_deviation")
    shortfall = np.minimum(returns.to_numpy(dtype=float) - mar, 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))


def semi_deviation(returns: pd.Series) -> float:
    """Semi-deviation: downside deviation using the sample mean as threshold.

    ``sqrt(mean(min(R - mean(R), 0)^2))`` over the full sample (N denominator).
    Only returns below the series mean contribute. Inputs/result are per-period
    decimal fractions (0.05 = 5%), never 0-100. Mirrors the eVestment
    semi-deviation (legacy return_statistics_service._compute_semi_deviation).

    Raises:
        ValueError: if fewer than 2 returns are supplied or the input contains
            NaN values.
    """
    if len(returns) < 2:
        raise ValueError(
            f"semi_deviation requires at least 2 returns, got {len(returns)}"
        )
    reject_nan(returns, "semi_deviation")
    values = returns.to_numpy(dtype=float)
    shortfall = np.minimum(values - values.mean(), 0.0)
    return float(np.sqrt(np.mean(shortfall**2)))
```

- [ ] **Step 4: Export both from `backend/app/analytics/__init__.py`.**

  4a. Replace the risk-import block (lines 30-40) to add `downside_deviation` and `semi_deviation` (keeping alphabetical order):
```python
from app.analytics.risk import (
    BestWorst,
    DrawdownResult,
    annualized_volatility,
    best_worst_day,
    beta,
    correlation,
    downside_deviation,
    historical_cvar,
    historical_var,
    max_drawdown,
    semi_deviation,
)
```
  4b. Add `"downside_deviation",` and `"semi_deviation",` to `__all__` (lines 47-77), keeping it sorted. Insert `"downside_deviation",` after `"diversification_ratio",` (line 61). Replace:
```python
    "diversification_ratio",
    "historical_cvar",
```
  with:
```python
    "diversification_ratio",
    "downside_deviation",
    "historical_cvar",
```
  Insert `"semi_deviation",` after `"rolling_volatility",` (line 72) and before `"simple_returns",` (line 73). Replace:
```python
    "rolling_volatility",
    "simple_returns",
```
  with:
```python
    "rolling_volatility",
    "semi_deviation",
    "simple_returns",
```

- [ ] **Step 5: Run the tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_analytics_risk.py -v`
  Expected: all T3D-2 tests pass and the pre-existing risk tests still pass.

- [ ] **Step 6: Commit.** Commands:
  `cd backend && git add app/analytics/risk.py app/analytics/__init__.py tests/test_analytics_risk.py`
  `git commit -m "feat(analytics): downside_deviation + semi_deviation pure fns (fail-loud)"`

---

### Task T3D-3: Expense-ratio unit normalization (scale-detect + clamp + structured warning)

Ports `expense_ratio_validator.to_decimal_fraction` (bps/percent/fraction scale-detect, `[0, 0.15]` clamp, structured warning logs) into a new pure module `app/analytics/expense_ratio.py`, then applies it at the fund read seam in `app/api/routes/funds.py` line 280 (the live `app/sync/funds.py` ingest was decommissioned and `app/sync/mother_db.py` carries no expense_ratio — see open question 1). The normalizer keeps the legacy semantics exactly: `abs(v) > 100` -> bps (`/10000`); `abs(v) > 0.15` -> percent (`/100`); else fraction; then clamp to `[0.0, 0.15]` with a warning; non-numeric/NaN/inf/None -> `None`. The legacy module uses `structlog`; the Light app uses stdlib `logging`, so the port uses `logging.getLogger(__name__)` (warnings emitted via `extra=` dicts).

**Files:**
- Create: `backend/app/analytics/expense_ratio.py`
- Create: `backend/tests/test_analytics_expense_ratio.py`
- Modify: `backend/app/api/routes/funds.py` — the fund-profile serialization at line 280 (`expense_ratio=float(fund.expense_ratio) if fund.expense_ratio is not None else None,`); add an import grouped with the existing `from app.services import ... as catalog` block near lines 57-71.
- Create: `backend/tests/test_funds_expense_normalization.py`

- [ ] **Step 1: Write the failing unit tests for the pure normalizer.** Create `backend/tests/test_analytics_expense_ratio.py`:
```python
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
```

- [ ] **Step 2: Run the unit tests, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_analytics_expense_ratio.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.analytics.expense_ratio'`.

- [ ] **Step 3: Implement the pure normalizer.** Create `backend/app/analytics/expense_ratio.py`:
```python
"""Expense-ratio unit normalisation (ported from legacy expense_ratio_validator).

The fund ``expense_ratio`` arrives in three incompatible shapes depending on
the upstream source:

* **Decimal fraction** (canonical) — e.g. ``0.015`` for 1.5%. XBRL N-CSR OEF
  taxonomy feeds produce this.
* **Whole percent** — e.g. ``1.5`` for 1.5%. Some N-CEN CSV exports / manual
  overrides live here.
* **Basis points** — e.g. ``150`` for 1.5%. Rare bulk adviser filings.

Any consumer that assumes one shape silently explodes on the others (a ``1.5``
percent read as a fraction is a 150% fee). ``to_decimal_fraction`` is the single
entry point: it inspects magnitude, converts to a decimal fraction, clamps into
a sane institutional range, and returns ``None`` when the input cannot be made
sense of. Callers prefer the fraction form and scale to percent/bps at the
presentation layer (project scale contract: fractions, never 0-100).

Pure function — no I/O. Warnings are emitted via stdlib ``logging`` with a
structured ``extra`` payload (the Light app does not use structlog).
"""

from __future__ import annotations

import logging
import math
from typing import Any

logger = logging.getLogger(__name__)

# Institutional sanity bounds as a decimal fraction (0.15 = 15%). The highest
# documented institutional fund fee is ~10%; 15% is a conservative upper guard.
MAX_REASONABLE_EXPENSE_RATIO = 0.15  # 15%
MIN_REASONABLE_EXPENSE_RATIO = 0.0   # negative fees would be a bug


def to_decimal_fraction(value: Any) -> float | None:
    """Normalise an expense-ratio value to a decimal fraction.

    Scale detection (in order):

    * ``None`` / non-numeric / ``NaN`` / ``±inf`` -> ``None``.
    * ``abs(value) > 100``  -> basis points, divide by 10 000.
    * ``abs(value) > 0.15`` -> whole percent, divide by 100.
    * otherwise (``[0, 0.15]``) -> already a fraction, keep as-is.

    Inputs in ``(0.15, 1.0]`` are classified as whole percent (the dominant
    N-CEN defect: ``0.5`` meaning 0.5%); this band emits an
    ``expense_ratio_ambiguous_percent_or_fraction`` warning for observability.

    The result is clamped into ``[MIN_REASONABLE_EXPENSE_RATIO,
    MAX_REASONABLE_EXPENSE_RATIO]``; out-of-range inputs are clamped (not
    nullified) and emit a warning, so downstream calculations keep a
    defensible number.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(v):
        return None

    # ── Scale detection ──────────────────────────────────────────────
    abs_v = abs(v)
    if abs_v > 100.0:
        fraction = v / 10_000.0  # basis points → fraction
        source_scale = "bps"
    elif abs_v > MAX_REASONABLE_EXPENSE_RATIO:
        fraction = v / 100.0     # whole percent → fraction
        source_scale = "percent"
        if abs_v <= 1.0:
            logger.warning(
                "expense_ratio_ambiguous_percent_or_fraction",
                extra={
                    "raw": value,
                    "interpreted_as_percent": v,
                    "interpreted_as_fraction": fraction,
                    "note": (
                        "Input in (0.15, 1.0] band — assumed whole percent. "
                        "If source was an XBRL fraction this is a >15% outlier; "
                        "verify upstream source convention."
                    ),
                },
            )
    else:
        fraction = v             # already a fraction
        source_scale = "fraction"

    # ── Clamp to institutional range ─────────────────────────────────
    if fraction < MIN_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_below_zero",
            extra={
                "raw": value,
                "detected_scale": source_scale,
                "clamped_to": MIN_REASONABLE_EXPENSE_RATIO,
            },
        )
        return MIN_REASONABLE_EXPENSE_RATIO
    if fraction > MAX_REASONABLE_EXPENSE_RATIO:
        logger.warning(
            "expense_ratio_clamped_above_max",
            extra={
                "raw": value,
                "detected_scale": source_scale,
                "clamped_to": MAX_REASONABLE_EXPENSE_RATIO,
            },
        )
        return MAX_REASONABLE_EXPENSE_RATIO

    return fraction
```

- [ ] **Step 4: Run the unit tests, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_analytics_expense_ratio.py -v`
  Expected: all 12 tests pass.

- [ ] **Step 5: Write the failing integration test for the read seam.** Create `backend/tests/test_funds_expense_normalization.py`. This pins that the fund-profile route emits a normalized fraction (a stored whole-percent `1.5` is served as `0.015`), by stubbing the catalog service the route calls. The route under test is `get_fund_profile` (`@router.get("/funds/{instrument_id}")`, line 255), which calls `await catalog.fetch_fund_profile(session, instrument_id)` (line 262). Verified: the catalog object is imported as `from app.services import funds_catalog as catalog` (line 57); `funds_route.catalog` is that same module, so `monkeypatch.setattr(funds_route.catalog, "fetch_fund_profile", ...)` patches the symbol the route uses. The route depends only on `get_session` (`SessionDep`, funds.py line 82); the funds router has no router-level `get_current_user` dependency. The `get_current_user` / `get_optional_datalake_session` overrides below are harmless belt-and-suspenders (FastAPI ignores overrides of unused dependencies) and mirror the existing `_client()` helper in `tests/test_rebalance.py` (lines 152-159) and `tests/test_funds_routes.py`.
```python
"""T3D-3 — expense_ratio is normalized to a decimal fraction at the read seam."""

import uuid
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.routes import funds as funds_route
from app.core.auth import CurrentUser, get_current_user
from app.core.datalake import get_optional_datalake_session
from app.core.db import get_session
from app.main import create_app

_IID = uuid.UUID("00000000-0000-0000-0000-0000000000ff")


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    app.dependency_overrides[get_optional_datalake_session] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        sub="u-1", org_id=None, claims={}
    )
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(expense_ratio: float | None) -> SimpleNamespace:
    return SimpleNamespace(
        instrument_id=_IID,
        series_id="S000",
        ticker="ABC",
        isin=None,
        cusip=None,
        lei=None,
        name="Fund ABC",
        fund_type="etf",
        strategy_label="Unclassified",
        asset_class="equity",
        is_index=False,
        expense_ratio=expense_ratio,
        aum_usd=None,
        primary_benchmark=None,
        inception_date=None,
        domicile=None,
        currency="USD",
    )


def _profile(fund: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(
        fund=fund,
        risk=None,
        nav=[],
        holdings=[],
        holdings_report_date=None,
        holdings_pct_of_nav_total=None,
        classes=[],
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("stored", "served"),
    [
        (1.5, 0.015),      # whole percent -> fraction
        (150.0, 0.015),    # basis points -> fraction
        (0.0069, 0.0069),  # canonical fraction unchanged
    ],
)
async def test_profile_expense_ratio_is_normalized(
    monkeypatch: pytest.MonkeyPatch, stored: float, served: float
) -> None:
    async def fake_fetch(session, instrument_id):
        return _profile(_fund(stored))

    monkeypatch.setattr(funds_route.catalog, "fetch_fund_profile", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_IID}")
    assert resp.status_code == 200
    assert resp.json()["expense_ratio"] == pytest.approx(served)


@pytest.mark.anyio
async def test_profile_expense_ratio_none_stays_none(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(session, instrument_id):
        return _profile(_fund(None))

    monkeypatch.setattr(funds_route.catalog, "fetch_fund_profile", fake_fetch)
    async with _client() as client:
        resp = await client.get(f"/funds/{_IID}")
    assert resp.status_code == 200
    assert resp.json()["expense_ratio"] is None
```
  Note: `get_fund_profile` reads `profile.fund`, `profile.risk`, `profile.nav`, `profile.holdings`, `profile.holdings_report_date`, `profile.holdings_pct_of_nav_total`, `profile.classes`, plus `getattr(fund, "synced_at"/"source_calc_date"/"source_nav_max_date", None)` (lines 288-290) — all covered by the SimpleNamespaces above (`getattr` defaults handle the three staleness fields). `FundRiskOut.model_validate(profile.risk) if profile.risk else None` (line 291) yields `None` for `risk=None`; `holdings=[]` is iterated empty; `classes=[]` is iterated empty.

- [ ] **Step 6: Run the integration test, expect FAIL.** Command:
  `cd backend && python -m pytest tests/test_funds_expense_normalization.py -v`
  Expected failure: for `stored=1.5` the served `expense_ratio` is the raw `1.5` (the route still does `float(fund.expense_ratio)` at line 280), so `assert 1.5 == approx(0.015)` fails. (The `0.0069` and `None` cases would already pass, but the `1.5` and `150.0` cases fail.)

- [ ] **Step 7: Apply normalization at the read seam in `backend/app/api/routes/funds.py`.**

  7a. Add the import grouped with the existing service imports (the block at lines 57-60 starts with `from app.services import funds_catalog as catalog`). Insert after line 57:
```python
from app.analytics.expense_ratio import to_decimal_fraction
```
  7b. Replace the expense_ratio line in `get_fund_profile` (line 280):
```python
        expense_ratio=float(fund.expense_ratio) if fund.expense_ratio is not None else None,
```
  with:
```python
        expense_ratio=to_decimal_fraction(fund.expense_ratio),
```
  (`to_decimal_fraction` already returns `None` for `None` input, so the `if ... is not None else None` guard is no longer needed.)

- [ ] **Step 8: Run both T3D-3 test files plus the existing funds-route test, expect PASS.** Command:
  `cd backend && python -m pytest tests/test_analytics_expense_ratio.py tests/test_funds_expense_normalization.py tests/test_funds_routes.py -v`
  Expected: all pass. `tests/test_funds_routes.py::test_fund_profile_payload` (which stubs a fund with `expense_ratio=0.0003` and does NOT assert on the served `expense_ratio` value) is unaffected because `to_decimal_fraction(0.0003)` returns `0.0003` unchanged (0.0003 ≤ 0.15 → fraction kept).

- [ ] **Step 9: Commit.** Commands:
  `cd backend && git add app/analytics/expense_ratio.py app/api/routes/funds.py tests/test_analytics_expense_ratio.py tests/test_funds_expense_normalization.py`
  `git commit -m "feat(funds): normalize expense_ratio to decimal fraction at read seam (scale-detect + clamp)"`

---

### Cluster verification (after all three tasks)

Run the full touched test set to confirm no regressions across the cluster:
`cd backend && python -m pytest tests/test_rebalance.py tests/test_analytics_risk.py tests/test_analytics_expense_ratio.py tests/test_funds_expense_normalization.py tests/test_funds_routes.py -v`
Expected: green. If `ruff`/`mypy` gates run in CI, also run:
`cd backend && python -m ruff check app tests && python -m mypy app`

---

## Tier 3 — Tail-VaR panel (Cornish–Fisher mVaR/ETR/Rachev/Jarque–Bera) + parametric & EVT POT-GPD CVaR in the live service

**Context grounded in source (re-read line-by-line before writing this plan):**
- LEGACY `E:/investintell-allocation/backend/quant_engine/tail_var_service.py` — `_parametric_var` (lines 83-92, returns `mean + z*std`, NEGATIVE), `_cornish_fisher_var` (lines 95-112), `compute_tail_risk` (lines 115-248): CF expansion, the **monotonicity clamp** (lines 158-168, `if abs(var_m99) < abs(var_m95): var_m99 = min(var_m99, var_m95)` in negative space), Jarque-Bera (lines 170-173, `jb_stat = n*(skew**2/6 + ek**2/24)`, `chi2.sf(jb, df=2)`), ETR right-tail (lines 205-208), Rachev (lines 218-232), tiered `n<30` (line 130, returns empty) / `30..<100` / `>=100` (`TAIL_MIN_OBS_FOR_HISTORICAL = 100`, line 50; gate at line 176) gates. Legacy uses scipy-default `bias=True` population moments (`sp_stats.skew`/`sp_stats.kurtosis`), `ddof=1` std, the std-before-moments order guard (lines 142-144), and **NEGATIVE return-space** losses.
- LEGACY `E:/investintell-allocation/backend/quant_engine/cvar_service.py` — `compute_cvar` (lines 142-265): parametric Gaussian branch (lines 222-242: `mu = mean`, `sigma = std(ddof=1)`, `z = norm.ppf(1-conf)`, `phi_z = norm.pdf(z)`, `var = mu + z*sigma`, `cvar = mu - sigma*phi_z/(1-conf)`, NEGATIVE) and `evt_pot` branch (lines 171-220) delegating to `extreme_var_evt`; the degraded/fail-closed carrier `CVaRResult` (lines 125-139) carries `degraded: bool` (line 138) + `degraded_reason: str | None` (line 139), NaN never 0.0 (lines 185-186). Confidence guard `0.0 < confidence < 1.0` (lines 152-155).
- LEGACY `E:/investintell-allocation/backend/quant_engine/evt/pot_gpd.py` — `extreme_var_evt` (lines 78-245): loss space `losses = -returns; losses[losses>0]` (lines 104-107), POT at the 90th pct, retry at the 85th (lines 112-122), `n_u >= 20` else retry / `>= 15` else fallback, GPD MLE via `genpareto.fit` (delegated through `_fit_gpd_mle`, lines 248+), McNeil-Frey closed form (lines 188-199 with `prob_ratio = (n_u/N_total)/(1-q)`, `var_q = u + (beta/xi)*(prob_ratio**xi - 1)`), `xi >= 1.0` infinite-mean guard (lines 164-167), and the `var_q = max(var_q, u)` clamp (line 205).
- WORKER `E:/investintell-datalake-workers/src/workers/risk_metrics.py` — `evt_tail` (lines 243-293), PROVEN OFFLINE (module docstring line 21): the compact MLE-only POT-GPD recipe — `len(arr) < 100` guard (line 250), `losses = -arr; losses[losses>0]` with `len(losses) < 30` guard (lines 252-255), POT 90th→85th with `len(exceed) >= 20` (lines 261-267), `genpareto.fit(exceed, floc=0.0)` (line 270), `beta <= 0 or not isfinite(xi)` guard (line 273), and the `_var_cvar` McNeil-Frey closed form (lines 277-286) with `ratio = (n/n_u)*(1-p)`, `var = u + (beta/xi)*(ratio**(-xi) - 1)` (`abs(xi) > 1e-8` else `u - beta*log(ratio)`), `cvar = var/(1-xi) + (beta - xi*u)/(1-xi)` when `xi < 1.0` else `cvar = var`. This plan ports THIS compact recipe (no lmoments3). NOTE: the worker form `ratio**(-xi)` and the legacy form `prob_ratio**xi` are algebraically identical (`ratio = ((n_u/N)/(1-q))**-1`); the worker form is used because it is the proven one.
- LIGHT target `backend/app/analytics/risk.py` — existing `historical_var` (lines 64-85) / `historical_cvar` (lines 88-114) return **POSITIVE loss magnitudes** and are **fail-loud** (`ValueError`). `_MIN_TAIL_POINTS = 10` (line 20). Module already imports `math` (line 10), `from dataclasses import dataclass` (line 11), `numpy as np` (line 14), `pandas as pd` (line 15), and `from app.analytics._validation import reject_nan, to_date` (line 17). **The file ends at line 213** (`correlation` returns on line 213) — append new code after it.
- LIGHT `backend/app/analytics/_validation.py` — `reject_nan(series, func_name)` (lines 25-39) raises `ValueError` containing the substring `"NaN or infinite values"` on any non-finite input.
- LIGHT `backend/app/analytics/__init__.py` — imports block: `app.analytics.risk` import is lines 30-40, `app.analytics.rolling` import is lines 41-45 (closes `)` on line 45). `__all__` is lines 47-77 (list, order is NOT load-bearing — entries are alphabetized by convention only).

**Design decisions (binding for all tasks):**
1. **Sign convention = POSITIVE loss magnitudes** for every new function (consistent with the existing `risk.py` rail), NOT the legacy negative convention. Each parametric VaR is `-(mean + z*std)`; CVaR is `-mu + sigma*phi(z)/(1-conf)`; EVT VaR/CVaR are returned as positive losses (the worker negates at the end, line 291-292; here we keep them positive). `mVaR99 >= mVaR95` means "99 is a worse loss". Docstrings state the conversion from legacy explicitly.
2. **Moments**: `scipy.stats.skew(values)` and `scipy.stats.kurtosis(values)` with scipy defaults (`bias=True`, population moments, excess kurtosis) — matches legacy `cf_population_moments_v1`. Std is `ddof=1` everywhere.
3. **Fail-loud vs carrier**: the CF tail **panel** and the **parametric Gaussian** VaR/CVaR are pure & **fail-loud** (`ValueError` on insufficient / zero-variance / NaN). The **EVT POT-GPD** path is the one place a fit can legitimately be non-estimable, so it returns an explicit **degraded carrier** dataclass (`EvtTailResult` with `degraded: bool` + `degraded_reason: str | None`, values NaN when degraded — fail-CLOSED, never a silent 0.0). This mirrors the legacy `CVaRResult` carrier (cvar_service.py lines 125-139, 185-186) and is documented as the deliberate exception to the fail-loud rule. A NaN/inf *input* is a caller bug and still raises `ValueError` up front (via `reject_nan`).
4. **Tiered n gates** (from legacy `compute_tail_risk`): `n < 30` → raise `ValueError` (panel undefined; legacy returns empty, Light fails loud); `30 <= n < 100` → parametric VaR + modified VaR + Jarque-Bera, historical-tail fields (`etl_95`, `etr_95`, `rachev_ratio`) are `None`; `n >= 100` → full panel.

---

### Task T3E-1: Tail-VaR panel pure module (CF mVaR with monotonicity clamp, ETR, Rachev, Jarque-Bera, tiered gates)

**Files:**
- Create: `backend/app/analytics/tail.py`
- Test: `backend/tests/test_analytics_tail.py`
- Modify: `backend/app/analytics/__init__.py` (add an import block after the `app.analytics.rolling` import that closes on line 45; add two entries to the `__all__` list, lines 47-77)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_tail.py` with the COMPLETE code below. It exercises: positive-loss sign convention, the CF monotonicity clamp on right-skewed leptokurtic samples (numerically verified: expo-seed11 sample has raw mVaR95=0.01139 but raw mVaR99=0.00788, so the clamp fires; spikes-seed5 sample has raw mVaR95=0.00118 but raw mVaR99=-0.03556, clamp fires), the tiered gates, Jarque-Bera on normal vs fat-tailed data (verified: normal-500-seed3 JB p=0.6991 > 0.05; Student-t df=3 JB p≈0 with excess-kurt≈9.34), ETR/Rachev positivity for the full panel (verified: ETR=0.042, Rachev=0.919), and fail-loud on `n<30`/NaN/zero-variance.

```python
"""Tests for app.analytics.tail — Cornish-Fisher tail-VaR panel."""

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student_t

from app.analytics.tail import TailPanel, tail_panel


def _dated(values: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def _normal_returns(n: int = 250, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(rng.normal(0.0003, 0.012, n)))


def _fat_tailed_returns(n: int = 600, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(student_t.rvs(3, size=n, random_state=rng) * 0.01))


# --- shape / sign convention --------------------------------------------------


def test_tail_panel_returns_positive_loss_var() -> None:
    """Parametric VaR is a POSITIVE loss magnitude under our convention."""
    panel = tail_panel(_normal_returns())
    assert panel.var_parametric_95 > 0
    assert panel.var_parametric_99 > 0
    assert panel.var_parametric_99 >= panel.var_parametric_95


def test_tail_panel_modified_var_positive_and_monotonic_on_normal_data() -> None:
    panel = tail_panel(_normal_returns())
    assert panel.var_modified_95 > 0
    assert panel.var_modified_99 >= panel.var_modified_95


# --- the Cornish-Fisher monotonicity clamp ------------------------------------


def test_cornish_fisher_clamp_fires_on_right_skewed_sample() -> None:
    """A strongly right-skewed sample makes the RAW CF expansion non-monotonic
    in confidence: the raw 99% positive-loss falls BELOW the raw 95% loss, which
    would report the deeper tail as less severe. The clamp must force
    mVaR99 >= mVaR95 (the more-severe positive loss wins).

    Verified numerically on this exact sample (exponential minus its mean,
    seed 11, n=300): empirical skew=1.54, excess-kurt=2.02, raw mVaR95=0.01139,
    raw mVaR99=0.00788 -> clamp fires -> post mVaR99 = mVaR95 = 0.01139.
    """
    rng = np.random.default_rng(11)
    base = rng.exponential(0.01, 300) - 0.01  # right-skewed (skew > 0)
    panel = tail_panel(_dated(list(base)))
    assert panel.var_modified_99 >= panel.var_modified_95


def test_cornish_fisher_clamp_fires_on_leptokurtic_spike_cluster() -> None:
    """A cluster of large positive outliers drives skew/kurtosis high enough
    that the raw CF 99% quantile crosses to the wrong side. The post-clamp
    invariant must hold.

    Verified numerically on this exact sample (seed 5, n=300): empirical
    skew=3.27, excess-kurt=10.13, raw mVaR95=0.00118, raw mVaR99=-0.03556 ->
    clamp fires -> post mVaR99 = mVaR95.
    """
    rng = np.random.default_rng(5)
    spikes = np.concatenate([
        rng.normal(0.0, 0.005, 280),
        rng.uniform(0.05, 0.09, 20),  # a cluster of large positive outliers
    ])
    panel = tail_panel(_dated(list(spikes)))
    assert panel.var_modified_99 >= panel.var_modified_95


# --- Jarque-Bera --------------------------------------------------------------


def test_jarque_bera_accepts_normal_data() -> None:
    panel = tail_panel(_normal_returns(500, seed=3))
    assert panel.jarque_bera_pvalue > 0.05
    assert panel.is_normal is True


def test_jarque_bera_rejects_fat_tailed_data() -> None:
    panel = tail_panel(_fat_tailed_returns())
    assert panel.jarque_bera_pvalue < 0.05
    assert panel.is_normal is False
    assert panel.jarque_bera_stat > 0


# --- ETR / Rachev (right tail, full panel only) -------------------------------


def test_etr_and_rachev_present_for_full_panel() -> None:
    panel = tail_panel(_fat_tailed_returns())
    # ETR is a positive expected-gain magnitude (mean of the right tail).
    assert panel.etr_95 is not None
    assert panel.etr_95 > 0
    # ETL is a positive expected-loss magnitude.
    assert panel.etl_95 is not None
    assert panel.etl_95 > 0
    # Rachev = ETR / ETL is a positive ratio when both tails are well-defined.
    assert panel.rachev_ratio is not None
    assert panel.rachev_ratio > 0


# --- tiered n gates -----------------------------------------------------------


def test_short_sample_raises() -> None:
    with pytest.raises(ValueError, match="at least 30"):
        tail_panel(_normal_returns(29))


def test_medium_sample_has_parametric_and_jb_but_no_historical_tail() -> None:
    """30 <= n < 100: parametric VaR + Jarque-Bera, but ETL/ETR/Rachev are None."""
    panel = tail_panel(_normal_returns(60, seed=2))
    assert panel.var_parametric_95 > 0
    assert panel.var_modified_95 > 0
    assert panel.jarque_bera_stat > 0
    assert panel.etl_95 is None
    assert panel.etr_95 is None
    assert panel.rachev_ratio is None


def test_nan_input_raises() -> None:
    bad = _normal_returns(120)
    bad.iloc[10] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        tail_panel(bad)


def test_zero_variance_raises() -> None:
    with pytest.raises(ValueError, match="variance"):
        tail_panel(_dated([0.01] * 120))


def test_tail_panel_is_frozen_dataclass() -> None:
    panel = tail_panel(_normal_returns())
    assert isinstance(panel, TailPanel)
    with pytest.raises((AttributeError, TypeError)):
        panel.var_parametric_95 = 0.0  # type: ignore[misc]
```

- [ ] **Step 2: Run it, expect FAIL.** `tail.py` does not exist yet, so the import fails at collection.
  Command: `cd backend && python -m pytest tests/test_analytics_tail.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.analytics.tail'` (collection error, 0 tests run).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/tail.py` with the COMPLETE code below. This ports `compute_tail_risk` from legacy `tail_var_service.py` (lines 115-248) but in the **positive-loss** Light convention, with the clamp expressed as `max(...)` in positive-loss space (the legacy `min(...)` in negative space).

```python
"""Cornish-Fisher tail-VaR panel — eVestment Section VII (ported, Light convention).

Pure functions over a pandas return Series. Computes parametric (Normal) VaR,
Cornish-Fisher modified VaR (with the monotonicity clamp), Expected Tail
Loss/Return, the Rachev ratio, and the Jarque-Bera normality test.

Ported from quant_engine/tail_var_service.py (method ``cf_population_moments_v1``,
compute_tail_risk lines 115-248) but in the Light app's **positive-loss**
convention: every VaR/CVaR/ETL is a POSITIVE decimal-fraction loss magnitude
(0.05 = a 5% loss), NOT the legacy NEGATIVE return-space value. ETR is a
POSITIVE expected-gain magnitude. The legacy clamp ``min(var_m99, var_m95)`` in
negative space becomes ``max(var_m99, var_m95)`` here.

Scale contract (project-wide): all fractional quantities are decimal fractions
(0.05 = 5%), never 0-100.

Fail-loud: raises ``ValueError`` on insufficient (n < 30) or degenerate
(NaN / zero-variance) input — never returns NaN. Historical-tail fields
(``etl_95``, ``etr_95``, ``rachev_ratio``) are ``None`` (not an error) when
30 <= n < 100, because < ~5 tail observations make the historical tail
statistically meaningless; they are populated only at the n >= 100 floor.

Moments: scipy defaults (``bias=True`` population moments, excess kurtosis),
matching the legacy ``cf_population_moments_v1`` convention. Std uses ddof=1.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd
from scipy import stats as sp_stats

from app.analytics._validation import reject_nan

# Sample minimums (tiered gates, ported from tail_var_service.py lines 130, 50, 176).
TAIL_MIN_OBS = 30  # below this the panel is undefined (ValueError)
TAIL_MIN_OBS_FOR_HISTORICAL = 100  # institutional floor — guarantees >=5 tail obs at 95%

CF_METHOD_VERSION = "cf_population_moments_v1"


@dataclass(frozen=True)
class TailPanel:
    """eVestment Section VII tail-risk panel, POSITIVE-loss convention.

    All VaR/ETL fields are positive loss magnitudes; ``etr_95`` is a positive
    expected-gain magnitude. ``etl_95``/``etr_95``/``rachev_ratio`` are ``None``
    when 30 <= n < 100 (historical tail withheld below the institutional floor).
    """

    method_version: str

    # Parametric VaR (Normal distribution), positive loss magnitudes.
    var_parametric_90: float
    var_parametric_95: float
    var_parametric_99: float

    # Modified VaR (Cornish-Fisher), positive loss magnitudes, monotone in conf.
    var_modified_95: float
    var_modified_99: float

    # Jarque-Bera normality test.
    jarque_bera_stat: float
    jarque_bera_pvalue: float
    is_normal: bool  # p > 0.05

    # Historical tail metrics (n >= 100 only; else None).
    etl_95: float | None = None  # Expected Tail Loss (CVaR), positive magnitude
    etr_95: float | None = None  # Expected Tail Return (right tail), positive
    rachev_ratio: float | None = None  # ETR / ETL (both positive)


def _parametric_var_loss(mean: float, std: float, confidence: float) -> float:
    """Parametric Normal VaR as a POSITIVE loss magnitude.

    Legacy ``_parametric_var`` (tail_var_service.py lines 83-92) returns
    ``mean + z*std`` (negative). Here we negate to a positive loss:
    ``-(mean + z*std)`` where ``z = norm.ppf(1 - confidence) < 0``.
    """
    z = float(sp_stats.norm.ppf(1 - confidence))
    return -(mean + z * std)


def _cornish_fisher_var_loss(
    mean: float, std: float, skew: float, excess_kurt: float, confidence: float
) -> float:
    """Cornish-Fisher modified VaR as a POSITIVE loss magnitude.

    z_cf = z + (z^2-1)/6 * S + (z^3-3z)/24 * K - (2z^3-5z)/36 * S^2,
    then loss = -(mean + z_cf * std). Ported from
    tail_var_service._cornish_fisher_var (lines 95-112), negated to positive-loss.
    """
    z = float(sp_stats.norm.ppf(1 - confidence))
    z_cf = (
        z
        + (z**2 - 1) / 6 * skew
        + (z**3 - 3 * z) / 24 * excess_kurt
        - (2 * z**3 - 5 * z) / 36 * skew**2
    )
    return -(mean + z_cf * std)


def tail_panel(returns: pd.Series) -> TailPanel:
    """Compute the eVestment Section VII tail-risk panel from a return series.

    Args:
        returns: daily simple returns, decimal fractions (0.05 = 5%).

    Raises:
        ValueError: fewer than 30 finite returns, NaN/inf in the input, or a
            (near-)zero-variance series (tail measures undefined).
    """
    reject_nan(returns, "tail_panel")
    values = returns.to_numpy(dtype=float)
    n = int(values.size)
    if n < TAIL_MIN_OBS:
        raise ValueError(
            f"tail_panel requires at least {TAIL_MIN_OBS} returns, got {n}"
        )

    mean = float(np.mean(values))
    std = float(np.std(values, ddof=1))
    # Check std before computing higher moments to avoid scipy precision warnings
    # on a degenerate series (ported from BUG-T3-SCIPY-ORDER, tail_var_service
    # lines 142-144).
    if std < 1e-12:
        raise ValueError("tail_panel is undefined: returns have (near-)zero variance")

    skew = float(sp_stats.skew(values))
    excess_kurt = float(sp_stats.kurtosis(values))  # excess kurtosis (scipy default)

    # Parametric (Normal) VaR — positive loss magnitudes.
    var_p90 = _parametric_var_loss(mean, std, 0.90)
    var_p95 = _parametric_var_loss(mean, std, 0.95)
    var_p99 = _parametric_var_loss(mean, std, 0.99)

    # Modified (Cornish-Fisher) VaR — positive loss magnitudes.
    var_m95 = _cornish_fisher_var_loss(mean, std, skew, excess_kurt, 0.95)
    var_m99 = _cornish_fisher_var_loss(mean, std, skew, excess_kurt, 0.99)

    # Monotonicity clamp (ported from BUG-T2c-CF-MONOTONIC, tail_var_service
    # lines 158-168). The legacy ``min(var_m99, var_m95)`` selected the more
    # negative (worse) loss; in POSITIVE-loss space the worse loss is the LARGER
    # value, so we take ``max``. The 99% loss must be at least the 95% loss.
    if var_m99 < var_m95:
        var_m99 = max(var_m99, var_m95)

    # Jarque-Bera normality test (population moments are correct for JB).
    jb_stat = float(n * (skew**2 / 6 + excess_kurt**2 / 24))
    jb_pvalue = float(sp_stats.chi2.sf(jb_stat, df=2))  # survival function (BUG-T2a-JBSF)
    is_normal = jb_pvalue > 0.05

    etl_95: float | None = None
    etr_95: float | None = None
    rachev: float | None = None

    if n >= TAIL_MIN_OBS_FOR_HISTORICAL:
        sorted_returns = np.sort(values)
        # ceil tail count, matching cvar_service convention (BUG-T2a-CEIL,
        # tail_var_service line 188).
        cutoff = max(1, math.ceil(round(n * 0.05, 10)))
        # ETL: positive loss magnitude (negate the mean of the worst tail).
        etl_95 = -float(np.mean(sorted_returns[:cutoff]))
        # ETR: positive gain magnitude (mean of the symmetric right tail,
        # tail_var_service lines 207-208).
        etr_95 = float(np.mean(sorted_returns[n - cutoff:]))
        # Rachev = ETR / ETL (both positive). Undefined when ETL is non-positive
        # (a window with no losses) -> leave None (BUG-T3-RACHEV-DEGRADED).
        if etl_95 > 1e-12 and etr_95 > 1e-12:
            rachev = etr_95 / etl_95

    return TailPanel(
        method_version=CF_METHOD_VERSION,
        var_parametric_90=var_p90,
        var_parametric_95=var_p95,
        var_parametric_99=var_p99,
        var_modified_95=var_m95,
        var_modified_99=var_m99,
        jarque_bera_stat=jb_stat,
        jarque_bera_pvalue=jb_pvalue,
        is_normal=is_normal,
        etl_95=etl_95,
        etr_95=etr_95,
        rachev_ratio=rachev,
    )
```

- [ ] **Step 4: Extend the analytics package exports.** In `backend/app/analytics/__init__.py`, add a new import block immediately after the `app.analytics.rolling` import that closes its `)` on line 45, and add the two new symbols to the `__all__` list (lines 47-77).
  Insert this import block right after line 45:
```python
from app.analytics.tail import (
    TailPanel,
    tail_panel,
)
```
  Then add `"TailPanel",` and `"tail_panel",` as two new elements anywhere inside the `__all__` brackets (list order is not load-bearing; to keep the alphabetical convention, place `"TailPanel",` after `"MIN_IN_RANGE_RETURNS",` on line 52 and `"tail_panel",` after `"simple_returns",` on line 73).

- [ ] **Step 5: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_analytics_tail.py -v`
  Expected: all 13 tests pass. (Verified numerically up-front against the Light venv — scipy 1.17.1 / numpy 2.2.6 / pandas 3.0.1: normal-250-seed7 parametric VaR95=0.01945, VaR99=0.02685 (both > 0, 99 >= 95); Student-t df=3 JB p≈0 with excess-kurt≈9.34; normal-500-seed3 JB p=0.6991; the clamp fires on both right-skewed samples and the post-clamp invariant holds; full-panel ETL=0.04581, ETR=0.04208, Rachev=0.919.)
  Also run the existing analytics suite for no regressions: `cd backend && python -m pytest tests/test_analytics_risk.py tests/test_analytics_tail.py -q`

- [ ] **Step 6: Commit.**
  Command (from repo root): `git add backend/app/analytics/tail.py backend/app/analytics/__init__.py backend/tests/test_analytics_tail.py`
  Message: `feat(analytics): Cornish-Fisher tail-VaR panel (mVaR clamp, ETR, Rachev, Jarque-Bera, tiered gates)`

---

### Task T3E-2: Parametric Gaussian CVaR/VaR + on-demand EVT POT-GPD CVaR/VaR with an explicit fail-closed degraded carrier

**Files:**
- Modify: `backend/app/analytics/risk.py` (append after `correlation`; the file currently ends at line 213. Reuse the existing module imports — `math` line 10, `from dataclasses import dataclass` line 11, `numpy as np` line 14, `pandas as pd` line 15, `from app.analytics._validation import reject_nan` line 17, and `_MIN_TAIL_POINTS = 10` line 20)
- Modify: `backend/app/analytics/__init__.py` (the `from app.analytics.risk import (...)` block lines 30-40, and `__all__` lines 47-77)
- Test: `backend/tests/test_analytics_risk_evt.py`

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_risk_evt.py` with the COMPLETE code below. It exercises: parametric Gaussian VaR/CVaR (positive loss, CVaR>=VaR, monotone in confidence), the EVT carrier on fat-tailed data (verified: EVT VaR99=0.0687, CVaR99=0.0808, xi=-0.188, n_u=30; parametric CVaR99=0.0480; so EVT CVaR > parametric CVaR), the fail-CLOSED degraded paths (insufficient losses / short sample → `degraded=True`, NaN values, reason set), and the fail-loud guards on the parametric path.

```python
"""Tests for parametric & EVT POT-GPD tail risk in app.analytics.risk."""

import math

import numpy as np
import pandas as pd
import pytest
from scipy.stats import t as student_t

from app.analytics.risk import (
    EvtTailResult,
    evt_tail_var_cvar,
    parametric_cvar,
    parametric_var,
)


def _dated(values: list[float], start: str = "2020-01-01") -> pd.Series:
    return pd.Series(values, index=pd.date_range(start, periods=len(values), freq="B"))


def _normal_returns(n: int = 250, seed: int = 7) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(rng.normal(0.0003, 0.012, n)))


def _fat_tailed_returns(n: int = 600, seed: int = 42) -> pd.Series:
    rng = np.random.default_rng(seed)
    return _dated(list(student_t.rvs(3, size=n, random_state=rng) * 0.01))


# --- parametric Gaussian VaR / CVaR -------------------------------------------


def test_parametric_var_positive_and_monotonic() -> None:
    r = _normal_returns()
    assert parametric_var(r, 0.95) > 0
    assert parametric_var(r, 0.99) >= parametric_var(r, 0.95)


def test_parametric_cvar_at_least_var() -> None:
    r = _normal_returns()
    assert parametric_cvar(r, 0.95) >= parametric_var(r, 0.95)


def test_parametric_cvar_monotonic() -> None:
    r = _normal_returns(500, seed=17)
    assert parametric_cvar(r, 0.99) >= parametric_cvar(r, 0.95)


def test_parametric_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        parametric_var(_normal_returns(), confidence=95.0)


def test_parametric_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        parametric_var(_dated([0.01] * 9))


def test_parametric_zero_variance_raises() -> None:
    with pytest.raises(ValueError, match="variance"):
        parametric_cvar(_dated([0.01] * 30))


def test_parametric_nan_raises() -> None:
    bad = _normal_returns(50)
    bad.iloc[3] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        parametric_var(bad)


# --- EVT POT-GPD carrier ------------------------------------------------------


def test_evt_tail_on_fat_tailed_data_is_well_defined() -> None:
    res = evt_tail_var_cvar(_fat_tailed_returns(), confidence=0.99)
    assert isinstance(res, EvtTailResult)
    assert res.degraded is False
    assert res.degraded_reason is None
    assert res.var > 0
    assert res.cvar >= res.var
    assert res.evt_n_exceedances >= 20
    assert res.evt_threshold > 0
    assert math.isfinite(res.evt_xi)


def test_evt_cvar_exceeds_parametric_on_fat_tails() -> None:
    """On genuinely fat-tailed (Student-t df=3) data, the EVT CVaR at 99% is
    materially larger than the Gaussian parametric CVaR — the whole point of
    using EVT for the deep tail. (Verified: EVT CVaR99 ~0.0808 vs parametric
    CVaR99 ~0.0480.)
    """
    r = _fat_tailed_returns()
    evt = evt_tail_var_cvar(r, confidence=0.99)
    assert evt.degraded is False
    assert evt.cvar > parametric_cvar(r, 0.99)


def test_evt_degrades_fail_closed_on_insufficient_losses() -> None:
    """An all-positive series has zero losses, so a GPD tail cannot be fit: the
    carrier must report degraded with NaN values and a reason — NEVER a silent
    0.0 (fail-closed). (Verified: 200 |gains| -> 0 losses -> insufficient_losses.)
    """
    rng = np.random.default_rng(1)
    almost_all_gains = _dated(list(np.abs(rng.normal(0.01, 0.002, 200))))
    res = evt_tail_var_cvar(almost_all_gains, confidence=0.99)
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_losses"
    assert math.isnan(res.var)
    assert math.isnan(res.cvar)


def test_evt_degrades_fail_closed_on_short_sample() -> None:
    res = evt_tail_var_cvar(_normal_returns(50), confidence=0.99)
    assert res.degraded is True
    assert res.degraded_reason == "insufficient_obs"
    assert math.isnan(res.var)
    assert math.isnan(res.cvar)


def test_evt_nan_input_raises() -> None:
    """NaN is a caller bug, not a degradable tail condition — fail loud."""
    bad = _fat_tailed_returns()
    bad.iloc[5] = float("nan")
    with pytest.raises(ValueError, match="NaN"):
        evt_tail_var_cvar(bad, confidence=0.99)


def test_evt_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        evt_tail_var_cvar(_fat_tailed_returns(), confidence=1.5)


def test_evt_result_is_frozen() -> None:
    res = evt_tail_var_cvar(_fat_tailed_returns(), confidence=0.99)
    with pytest.raises((AttributeError, TypeError)):
        res.degraded = True  # type: ignore[misc]
```

- [ ] **Step 2: Run it, expect FAIL.** The new symbols don't exist yet.
  Command: `cd backend && python -m pytest tests/test_analytics_risk_evt.py -v`
  Expected failure: `ImportError: cannot import name 'EvtTailResult' from 'app.analytics.risk'` (collection error, 0 tests run).

- [ ] **Step 3: Write the minimal implementation.** Append the COMPLETE code below to the end of `backend/app/analytics/risk.py` (after `correlation`, which returns on line 213). The parametric functions are fail-loud and reuse the existing `_MIN_TAIL_POINTS = 10` (line 20) and `reject_nan` (imported line 17) and `dataclass` (imported line 11). The EVT path ports the PROVEN worker recipe (`risk_metrics.evt_tail`, lines 243-293) — MLE-only POT-GPD, POT 90th→85th, `n_u >= 20`, McNeil-Frey closed form, `xi < 1.0` ES guard — but as a per-confidence on-demand call returning the explicit fail-closed carrier (mirroring legacy `CVaRResult`, cvar_service.py lines 125-139). The `max(var_loss, u)` clamp is from legacy `pot_gpd.py` line 205.

```python
# ---------------------------------------------------------------------------
# Parametric Gaussian VaR / CVaR (fail-loud) and EVT POT-GPD (degraded carrier)
# ---------------------------------------------------------------------------

# EVT thresholds (ported from worker risk_metrics.evt_tail lines 250/254/264 and
# legacy pot_gpd): >=100 finite returns, >=30 strictly-positive losses, >=20
# exceedances over the POT threshold (90th pct, retried at 85th).
_EVT_MIN_OBS = 100
_EVT_MIN_LOSSES = 30
_EVT_MIN_EXCEEDANCES = 20


def parametric_var(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric (Normal) Value-at-Risk as a POSITIVE decimal-fraction loss.

    ``VaR = -(mu + z*sigma)`` with ``z = norm.ppf(1 - confidence) < 0`` and
    ``sigma`` the sample std (ddof=1). Ported from cvar_service.compute_cvar's
    parametric branch (lines 222-242), negated to the Light positive-loss
    convention.

    Raises:
        ValueError: confidence not in (0, 1), fewer than 10 returns, NaN/inf in
            the input, or a (near-)zero-variance series (VaR undefined).
    """
    from scipy.stats import norm

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"parametric_var requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "parametric_var")
    values = returns.to_numpy(dtype=float)
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    if sigma < 1e-12:
        raise ValueError("parametric_var is undefined: returns have zero variance")
    z = float(norm.ppf(1 - confidence))
    return -(mu + z * sigma)


def parametric_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Parametric (Normal) Conditional VaR as a POSITIVE decimal-fraction loss.

    ``CVaR = -mu + sigma * phi(z) / (1 - confidence)`` with ``z = norm.ppf(1 -
    confidence)`` and ``phi`` the standard-normal pdf. Ported from
    cvar_service.compute_cvar's parametric branch (lines 222-242, ``cvar = mu -
    sigma*phi_z/(1-conf)``), negated to positive-loss.

    Raises:
        ValueError: confidence not in (0, 1), fewer than 10 returns, NaN/inf in
            the input, or a (near-)zero-variance series (CVaR undefined).
    """
    from scipy.stats import norm

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"parametric_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "parametric_cvar")
    values = returns.to_numpy(dtype=float)
    mu = float(np.mean(values))
    sigma = float(np.std(values, ddof=1))
    if sigma < 1e-12:
        raise ValueError("parametric_cvar is undefined: returns have zero variance")
    z = float(norm.ppf(1 - confidence))
    phi_z = float(norm.pdf(z))
    return -mu + sigma * phi_z / (1 - confidence)


@dataclass(frozen=True)
class EvtTailResult:
    """EVT POT-GPD tail estimate with an explicit fail-CLOSED degraded carrier.

    Light analytics are normally fail-loud, but an EVT fit can legitimately be
    non-estimable (too few losses/exceedances, GPD MLE non-convergence, an
    infinite-mean tail). For those *data* conditions this carrier reports
    ``degraded=True`` with ``var``/``cvar`` = NaN and a ``degraded_reason`` —
    NEVER a silent 0.0 (a 0.0 would masquerade as "0% tail risk"). This mirrors
    the legacy cvar_service.CVaRResult carrier (lines 125-139, 185-186). A
    NaN/inf *input* is a caller bug and still raises ``ValueError`` up front.

    ``var``/``cvar`` are POSITIVE decimal-fraction loss magnitudes when not
    degraded; CVaR >= VaR by construction (xi < 1).
    """

    var: float
    cvar: float
    confidence: float
    degraded: bool
    degraded_reason: str | None
    evt_xi: float  # GPD shape (NaN when degraded)
    evt_beta: float  # GPD scale (NaN when degraded)
    evt_threshold: float  # POT threshold u in loss space (NaN when degraded)
    evt_n_exceedances: int  # exceedances over u (0 when degraded)


def _degraded_evt(confidence: float, reason: str) -> EvtTailResult:
    return EvtTailResult(
        var=float("nan"),
        cvar=float("nan"),
        confidence=confidence,
        degraded=True,
        degraded_reason=reason,
        evt_xi=float("nan"),
        evt_beta=float("nan"),
        evt_threshold=float("nan"),
        evt_n_exceedances=0,
    )


def evt_tail_var_cvar(returns: pd.Series, confidence: float = 0.99) -> EvtTailResult:
    """On-demand EVT POT-GPD VaR/CVaR for the deep loss tail (fail-closed carrier).

    Ports the offline-proven recipe from the workers repo
    (``src/workers/risk_metrics.py::evt_tail``, lines 243-293): work in loss
    space (``losses = -returns``, keep the strictly-positive losses), pick a
    peaks-over-threshold cut at the 90th loss percentile (retry at the 85th if
    too few exceedances), fit a GPD to the exceedances via
    ``scipy.stats.genpareto.fit(exceed, floc=0)``, then apply the McNeil-Frey
    closed-form tail quantile and expected-shortfall:

        ratio = (n / n_u) * (1 - confidence)
        VaR   = u + (beta/xi) * (ratio**(-xi) - 1)            (xi != 0)
              = u - beta * log(ratio)                          (xi ~ 0)
        CVaR  = VaR/(1 - xi) + (beta - xi*u)/(1 - xi)          (xi < 1)

    Returns POSITIVE loss magnitudes (the worker negates at the end for its
    return-space table; here we keep them positive). The ``max(var_loss, u)``
    clamp is from legacy pot_gpd.py line 205 (POT VaR is bounded below by the
    threshold); harmless for the deep tail. Degrades fail-closed (NaN + reason)
    on: fewer than 100 finite returns, fewer than 30 positive losses, fewer than
    20 exceedances at either threshold, GPD MLE failure / non-positive scale, or
    an infinite-mean tail (xi >= 1, ES undefined).

    Raises:
        ValueError: confidence not in (0, 1), or NaN/inf in the input.
    """
    from scipy.stats import genpareto

    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    reject_nan(returns, "evt_tail_var_cvar")
    values = returns.to_numpy(dtype=float)
    if values.size < _EVT_MIN_OBS:
        return _degraded_evt(confidence, "insufficient_obs")

    losses = -values
    losses = losses[losses > 0]
    if losses.size < _EVT_MIN_LOSSES:
        return _degraded_evt(confidence, "insufficient_losses")

    # POT threshold at the 90th loss percentile; drop to 85th if too few exceed.
    exceed = np.array([])
    u = float("nan")
    for q in (0.90, 0.85):
        u = float(np.quantile(losses, q))
        exceed = losses[losses > u] - u
        if exceed.size >= _EVT_MIN_EXCEEDANCES:
            break
    else:
        return _degraded_evt(confidence, "insufficient_exceedances")

    n = int(losses.size)
    n_u = int(exceed.size)
    try:
        xi, _loc, beta = genpareto.fit(exceed, floc=0.0)
    except Exception:
        return _degraded_evt(confidence, "gpd_fit_failed")
    xi = float(xi)
    beta = float(beta)
    if beta <= 0 or not np.isfinite(xi):
        return _degraded_evt(confidence, "gpd_fit_invalid")
    if xi >= 1.0:
        # Infinite-mean tail — expected shortfall undefined.
        return _degraded_evt(confidence, "infinite_mean_tail")

    # McNeil-Frey closed form (worker recipe lines 277-286).
    ratio = (n / n_u) * (1.0 - confidence)
    if abs(xi) > 1e-8:
        var_loss = u + (beta / xi) * (ratio ** (-xi) - 1.0)
    else:
        var_loss = u - beta * math.log(ratio)
    var_loss = max(var_loss, u)  # POT VaR bounded below by threshold (pot_gpd L205)
    cvar_loss = var_loss / (1.0 - xi) + (beta - xi * u) / (1.0 - xi)

    if not (np.isfinite(var_loss) and np.isfinite(cvar_loss)):
        return _degraded_evt(confidence, "non_finite_estimate")

    return EvtTailResult(
        var=float(var_loss),
        cvar=float(cvar_loss),
        confidence=confidence,
        degraded=False,
        degraded_reason=None,
        evt_xi=xi,
        evt_beta=beta,
        evt_threshold=u,
        evt_n_exceedances=n_u,
    )
```

- [ ] **Step 4: Extend the analytics package exports.** In `backend/app/analytics/__init__.py`, add the three new symbols to the existing `from app.analytics.risk import (` block (lines 30-40) and to `__all__` (lines 47-77).
  In the `from app.analytics.risk import (` block, add these four import lines (alphabetical with the existing entries — `EvtTailResult` after `DrawdownResult`, the three functions after `correlation`):
```python
    EvtTailResult,
    evt_tail_var_cvar,
    parametric_cvar,
    parametric_var,
```
  And add four entries to `__all__`: `"EvtTailResult",`, `"evt_tail_var_cvar",`, `"parametric_cvar",`, `"parametric_var",` (list order is not load-bearing; any position inside the brackets is fine).

- [ ] **Step 5: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_analytics_risk_evt.py -v`
  Expected: all 14 tests pass. (Verified numerically up-front against the Light venv — scipy 1.17.1: on Student-t df=3 data, EVT VaR99=0.0687 / CVaR99=0.0808 with xi=-0.188, n_u=30, u=0.0272; parametric CVaR99=0.0480; so `evt.cvar > parametric_cvar` holds. The all-|gains| series yields 0 losses -> `insufficient_losses`; the 50-point series -> `insufficient_obs`.)
  Then run the full analytics + risk suites for no regressions:
  `cd backend && python -m pytest tests/test_analytics_risk.py tests/test_analytics_tail.py tests/test_analytics_risk_evt.py -q`

- [ ] **Step 6: Commit.**
  Command (from repo root): `git add backend/app/analytics/risk.py backend/app/analytics/__init__.py backend/tests/test_analytics_risk_evt.py`
  Message: `feat(analytics): parametric Gaussian + EVT POT-GPD tail VaR/CVaR with fail-closed degraded carrier`

---

## Tier 3 — Correlation-regime/contagion service + RMT pack (constant-correlation LW 2003 + Marchenko–Pastur denoise + absorption) + robust/vol-target SOCP + SCS hardening

This cluster ports the legacy `correlation_regime_service.py` math into the Light app as (a) a shared, unit-tested RMT analytics module, (b) a DB-reading correlation-regime/contagion service + thin route over the same `(T,N)` matrix the optimizer builds, and (c) two μ-aware SOCP solvers (robust/ellipsoidal mean-uncertainty and volatility-target) plus an SCS fallback ladder and post-solve constraint re-verification + telemetry for the engine's μ-free solvers.

**Source provenance (RE-READ and verified against the real files):**
- Legacy correlation math: `E:/investintell-allocation/backend/quant_engine/correlation_regime_service.py` — `_ledoit_wolf_constant_correlation` lines 92–193 (1/T sample-cov convention, constant-correlation target F, closed-form δ); `_marchenko_pastur_denoise` lines 215–251 (clamps eigenvalues ≥ 0 before reconstruction); `_compute_concentration` lines 254–312 (absorption k=max(1,N//5), Kritzman & Li 2010; MP signal count vs λ₊); contagion / 60d-vs-baseline rolling in `compute_correlation_regime` lines 328–501 (per-pair `|Δ|>0.3 AND current>0.7` line 450–453; symmetric avg-corr regime shift line 483; raw correlation kept for display per WMJ-015 lines 397–401, 472–488). NOTE: legacy uses a 504d baseline window split (`_DEFAULT_BASELINE_WINDOW_DAYS = 504`, line 20); the light port keeps the simpler recent-vs-everything-before split (`baseline = arr[:-window]`) which the legacy also degrades to when history is short.
- Legacy SOCP: `E:/investintell-allocation/backend/quant_engine/optimizer_service.py` — κ from `chi2.ppf`: `kappa_95 = float(np.sqrt(sp_chi2.ppf(0.95, df=max(n, 1))))` at lines 1116 and 1472, scaled by `uncertainty_level` (lines 1117–1119, 1473–1475); ellipsoidal penalty `mu @ w2 - kappa * norm(L_chol.T @ w2, 2)` line 1497; vol-target SOC `norm(chol.T @ w, 2) <= vol_target_annual` line 1135; floor-vol infeasibility report lines 1315–1326; CLARABEL→SCS fallback ladder lines 786–798.
- Light targets (verified line numbers): `backend/app/optimizer/engine.py` — `OptimizerError` L31, `sigma_ledoit_wolf` L35, `_WEIGHT_ATOL` L28, `_check_constraint_params` L58, `base_constraints` L80, `_finalize` L92–112, `_validate_sigma` L115, `solve_min_vol` return at L153, `solve_min_cvar` return at L282. `backend/app/optimizer/black_litterman.py` — `solve_bl_utility` L251–276 (the existing μ-consuming solver; imports `cp`, `np`, `OptimizerError`, `_check_constraint_params`, `_finalize`, `_validate_sigma`, `base_constraints` at L22–29). `backend/app/main.py` — router import block L7–17, registration block L51–61, macro import at L10, macro registration at L59.

**Gate G5 (verified live, `backend/tests/test_optimizer_engine.py` lines 154–168):** `engine.py` and `data.py` must contain ZERO `.mean(` and zero `np.average`; `black_litterman.py` must contain EXACTLY ONE `.mean(` (the `historical_mean_ann` re-centering estimator at `black_litterman.py` L223). Confirmed by grep: engine.py=0, data.py=0, black_litterman.py=1. Every code addition in T3F-2/T3F-3/T3F-4 was checked to introduce NO new `.mean(`/`np.average` (they use `.min()`, `.max()`, `.sum()`, `np.maximum`, `np.linalg.cholesky`, `cp.norm`, `np.sqrt`). T3F-2 Step 4 and T3F-3/T3F-4 Step 4 re-run the G5 gate to prove this.

**Baseline (verified):** `python -m pytest tests/test_optimizer_engine.py tests/test_optimizer_black_litterman.py -q` → 26 passed. All RMT primitives, both SOCP solvers, and the regime assembler were numerically smoke-tested against the exact assertions below before writing.

**Dependency order:** T3F-1 (RMT module) → T3F-2 (engine telemetry/SCS hardening, independent) → T3F-3 (robust SOCP) → T3F-4 (vol-target SOCP) → T3F-6 (schema) → T3F-5 (service, imports T3F-1 + T3F-6) → T3F-7 (route, imports T3F-5/T3F-6 + main.py) → T3F-8 (regression gate). NOTE the schema (T3F-6) must land before the service (T3F-5) can pass Step 4 — execute T3F-6 first; they are numbered for clarity but T3F-6 → T3F-5 is the run order.

---

### Task T3F-1: Shared RMT analytics module (constant-correlation LW 2003 + Marchenko–Pastur denoise + absorption + MP signal count)

**Files:**
- Create: `backend/app/analytics/rmt.py`
- Test: `backend/tests/test_analytics_rmt.py`

This module is the SINGLE owner of the RMT primitives. It is consumed by the correlation-regime service (T3F-5) and is the canonical home for the absorption-ratio primitive (T2E must import `absorption_ratio` from here, not re-derive it — see open_questions). All functions are pure (numpy in, numpy/float out), fail-loud on degenerate input, and follow the project scale contract (correlations/ratios are decimal fractions). `from app.analytics import rmt` works as a submodule import — no edit to `backend/app/analytics/__init__.py` is required (verified: the package `__init__` does not gate submodule imports).

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_rmt.py`:

```python
"""Unit tests for the shared RMT analytics module (app.analytics.rmt).

Ported/condensed from legacy correlation_regime_service: constant-correlation
Ledoit-Wolf 2003 shrinkage, Marchenko-Pastur denoise, absorption ratio, and
the MP signal-eigenvalue count. Pure numpy — no I/O, no DB.
"""

import numpy as np
import pytest

from app.analytics import rmt


def _factor_returns(t: int, n: int, load: float = 0.6, seed: int = 0) -> np.ndarray:
    """(T,N) returns with a single common factor — strong cross-correlation."""
    rng = np.random.default_rng(seed)
    common = rng.standard_normal((t, 1))
    idio = rng.standard_normal((t, n))
    return load * common + (1.0 - load) * idio


# ── constant-correlation Ledoit-Wolf 2003 ────────────────────────────────────


def test_lw_constant_correlation_returns_psd_and_intensity_in_unit_interval() -> None:
    x = _factor_returns(60, 4)
    cov, delta = rmt.ledoit_wolf_constant_correlation(x)
    assert cov.shape == (4, 4)
    np.testing.assert_allclose(cov, cov.T, atol=1e-12)
    assert 0.0 <= delta <= 1.0
    assert np.linalg.eigvalsh(cov).min() > -1e-10


def test_lw_constant_correlation_preserves_offdiagonal_sign() -> None:
    """Unlike sklearn's scaled-identity target, the constant-correlation
    target keeps cross-asset covariance (off-diagonals stay non-trivial)."""
    x = _factor_returns(60, 4, load=0.8)
    cov, delta = rmt.ledoit_wolf_constant_correlation(x)
    off = cov[np.triu_indices(4, k=1)]
    assert (off > 0).all()
    assert delta > 0.0  # short window + structure ⇒ non-zero shrinkage


def test_lw_constant_correlation_rejects_too_few_rows() -> None:
    with pytest.raises(ValueError, match="at least 2"):
        rmt.ledoit_wolf_constant_correlation(np.zeros((1, 3)))


def test_lw_constant_correlation_rejects_nan() -> None:
    x = _factor_returns(60, 3)
    x[5, 1] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        rmt.ledoit_wolf_constant_correlation(x)


# ── Marchenko-Pastur denoise ─────────────────────────────────────────────────


def test_mp_denoise_returns_correlation_matrix_unit_diagonal() -> None:
    x = _factor_returns(120, 6)
    corr = np.corrcoef(x, rowvar=False)
    q = 6 / 120
    denoised = rmt.marchenko_pastur_denoise(corr, q)
    np.testing.assert_allclose(np.diag(denoised), np.ones(6), atol=1e-9)
    np.testing.assert_allclose(denoised, denoised.T, atol=1e-12)
    assert np.linalg.eigvalsh(denoised).min() > -1e-10


def test_mp_denoise_collapses_noise_eigenvalues() -> None:
    """Eigenvalues below the MP upper bound are flattened to one value, so the
    denoised spectrum has fewer DISTINCT small eigenvalues than the raw one."""
    x = _factor_returns(80, 8)
    corr = np.corrcoef(x, rowvar=False)
    q = 8 / 80
    raw_eigs = np.sort(np.linalg.eigvalsh(corr))
    den_eigs = np.sort(np.linalg.eigvalsh(rmt.marchenko_pastur_denoise(corr, q)))
    lambda_plus = (1 + np.sqrt(q)) ** 2
    raw_noise = raw_eigs[raw_eigs < lambda_plus]
    den_noise = den_eigs[den_eigs < lambda_plus]
    assert raw_noise.size >= 2
    assert raw_noise.std() > den_noise.std()


def test_mp_denoise_rejects_bad_q() -> None:
    corr = np.eye(3)
    with pytest.raises(ValueError, match="q must be > 0"):
        rmt.marchenko_pastur_denoise(corr, 0.0)


# ── absorption ratio ─────────────────────────────────────────────────────────


def test_absorption_ratio_high_for_single_factor_market() -> None:
    x = _factor_returns(200, 10, load=0.9)
    corr = np.corrcoef(x, rowvar=False)
    ar = rmt.absorption_ratio(corr)
    assert 0.0 < ar <= 1.0
    assert ar > 0.5  # one dominant factor ⇒ top eigenvalues absorb most variance


def test_absorption_ratio_low_for_independent_assets() -> None:
    rng = np.random.default_rng(1)
    x = rng.standard_normal((300, 10))  # ~independent
    ar = rmt.absorption_ratio(np.corrcoef(x, rowvar=False))
    assert ar < 0.5


def test_absorption_ratio_respects_explicit_k() -> None:
    corr = np.eye(5)
    # Identity: each eigenvalue = 1, total = 5; top-1 absorbs exactly 0.2.
    assert rmt.absorption_ratio(corr, k=1) == pytest.approx(0.2, abs=1e-9)
    assert rmt.absorption_ratio(corr, k=2) == pytest.approx(0.4, abs=1e-9)


def test_absorption_ratio_rejects_empty() -> None:
    with pytest.raises(ValueError, match="non-empty square"):
        rmt.absorption_ratio(np.zeros((0, 0)))


# ── MP signal-eigenvalue count ───────────────────────────────────────────────


def test_mp_signal_count_counts_eigenvalues_above_bound() -> None:
    x = _factor_returns(150, 6, load=0.85)
    corr = np.corrcoef(x, rowvar=False)
    q = 6 / 150
    n_signal, lambda_plus = rmt.mp_signal_eigenvalues(corr, q)
    assert lambda_plus == pytest.approx((1 + np.sqrt(q)) ** 2, abs=1e-9)
    assert 1 <= n_signal < 6  # at least the factor, not all six


def test_mp_signal_count_rejects_bad_q() -> None:
    with pytest.raises(ValueError, match="q must be > 0"):
        rmt.mp_signal_eigenvalues(np.eye(3), -0.1)
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_analytics_rmt.py -v`
  - Expected failure: `ModuleNotFoundError: No module named 'app.analytics.rmt'` (the module does not exist yet).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/rmt.py`:

```python
"""Random-Matrix-Theory (RMT) primitives — pure numpy, no I/O.

The SINGLE home for the covariance/correlation cleaning math shared across the
optimizer and the correlation-regime service:

* ``ledoit_wolf_constant_correlation`` — Ledoit & Wolf (2003) shrinkage toward
  a CONSTANT-CORRELATION target F (F_ij = r̄·√(S_ii·S_jj)). Unlike
  ``sklearn.covariance.LedoitWolf`` (scaled-identity target), this preserves
  cross-asset dependence — essential for short stress windows.
* ``marchenko_pastur_denoise`` — flatten eigenvalues below the MP upper bound
  λ₊ = (1+√q)² to their average, then renormalize to a unit-diagonal
  correlation matrix.
* ``absorption_ratio`` — Kritzman & Li (2010): fraction of total variance
  absorbed by the top-k eigenvalues (k = N/5, ≥1, unless overridden). This is
  the canonical absorption primitive; the Tier-2 absorption work (T2E) must
  import THIS function rather than re-deriving it.
* ``mp_signal_eigenvalues`` — count eigenvalues above λ₊ (the "signal" count)
  and return (count, λ₊).

Scale contract: correlations and ratios are decimal fractions (0.20 = 20%).
Fail-loud: degenerate/NaN input raises ``ValueError`` (routes map → 422).
"""

from __future__ import annotations

import numpy as np
from numpy.typing import NDArray


def ledoit_wolf_constant_correlation(
    returns: NDArray[np.floating],
) -> tuple[NDArray[np.float64], float]:
    """Constant-correlation Ledoit-Wolf 2003 shrinkage.

    Parameters
    ----------
    returns : (T, N) array of returns (de-meaning handled internally).

    Returns
    -------
    (shrunk_covariance, shrinkage_intensity_delta) — δ ∈ [0, 1].

    Ported from legacy correlation_regime_service._ledoit_wolf_constant_correlation
    (1/T sample-covariance convention per the LW paper).
    """
    arr = np.asarray(returns, dtype=float)
    if arr.ndim != 2:
        raise ValueError(f"returns must be a (T, N) matrix, got ndim={arr.ndim}")
    if not np.isfinite(arr).all():
        raise ValueError("returns contain NaN/inf — refusing to estimate covariance")
    t, n = arr.shape
    if t < 2 or n < 2:
        raise ValueError(f"need at least 2 rows and 2 columns, got shape {arr.shape}")

    x = arr - arr.mean(axis=0, keepdims=True)
    s = (x.T @ x) / t  # 1/T convention (LW paper)

    var = np.diag(s).copy()
    std = np.sqrt(np.maximum(var, 1e-20))
    std_outer = np.outer(std, std)

    r = s / std_outer
    np.fill_diagonal(r, 1.0)
    mask = ~np.eye(n, dtype=bool)
    r_bar = float(r[mask].mean())

    f = r_bar * std_outer
    np.fill_diagonal(f, var)

    x2 = x ** 2
    pi_mat = (x2.T @ x2) / t - s ** 2
    pi_hat = float(pi_mat.sum())

    rho_diag = float(np.sum(np.diag(pi_mat)))
    x3 = x ** 3
    term1 = (x3.T @ x) / t - var[:, None] * s
    term2 = (x.T @ x3) / t - s * var[None, :]
    std_ratio_ji = std[None, :] / std[:, None]
    std_ratio_ij = std[:, None] / std[None, :]
    rho_off_mat = (r_bar / 2.0) * (std_ratio_ji * term1 + std_ratio_ij * term2)
    np.fill_diagonal(rho_off_mat, 0.0)
    rho_hat = rho_diag + float(rho_off_mat.sum())

    gamma_hat = float(np.sum((f - s) ** 2))
    if gamma_hat < 1e-12:
        delta = 0.0
    else:
        kappa = (pi_hat - rho_hat) / gamma_hat
        delta = float(np.clip(kappa / t, 0.0, 1.0))

    shrunk = delta * f + (1.0 - delta) * s
    return np.asarray((shrunk + shrunk.T) / 2.0, dtype=float), delta


def marchenko_pastur_denoise(
    corr_matrix: NDArray[np.floating], q: float
) -> NDArray[np.float64]:
    """Flatten sub-MP eigenvalues to their mean; return a unit-diagonal corr.

    ``q = N / T``. Ported from legacy _marchenko_pastur_denoise (clamps
    eigenvalues ≥ 0 before reconstruction to guarantee PSD output).
    """
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    if q <= 0:
        raise ValueError(f"q must be > 0 (= N/T), got {q}")

    eigenvalues, eigenvectors = np.linalg.eigh(c)
    idx = np.argsort(eigenvalues)[::-1]
    eigenvalues = eigenvalues[idx]
    eigenvectors = eigenvectors[:, idx]

    lambda_plus = (1 + np.sqrt(q)) ** 2
    noise_mask = eigenvalues < lambda_plus
    if noise_mask.any():
        eigenvalues[noise_mask] = float(np.mean(eigenvalues[noise_mask]))
    eigenvalues = np.maximum(eigenvalues, 0.0)

    denoised = eigenvectors @ np.diag(eigenvalues) @ eigenvectors.T
    d = np.sqrt(np.diag(denoised))
    d[d == 0] = 1.0
    denoised = denoised / np.outer(d, d)
    np.fill_diagonal(denoised, 1.0)
    return np.asarray((denoised + denoised.T) / 2.0, dtype=float)


def absorption_ratio(
    corr_matrix: NDArray[np.floating], k: int | None = None
) -> float:
    """Kritzman & Li (2010) absorption ratio: top-k eigenvalues / total.

    Default k = max(1, N // 5). Operates on a correlation (or covariance)
    matrix. This is the canonical absorption primitive (T2E imports it).
    """
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    n = c.shape[0]
    if k is None:
        k = max(1, n // 5)
    if not 1 <= k <= n:
        raise ValueError(f"k must be in [1, {n}], got {k}")

    eigenvalues = np.sort(np.maximum(np.linalg.eigvalsh(c), 0.0))[::-1]
    total = float(eigenvalues.sum())
    if total < 1e-12:
        return 1.0
    return float(eigenvalues[:k].sum() / total)


def mp_signal_eigenvalues(
    corr_matrix: NDArray[np.floating], q: float
) -> tuple[int, float]:
    """Count eigenvalues above the MP bound λ₊ = (1+√q)²; return (count, λ₊)."""
    c = np.asarray(corr_matrix, dtype=float)
    if c.ndim != 2 or c.shape[0] != c.shape[1] or c.shape[0] == 0:
        raise ValueError(f"corr_matrix must be a non-empty square matrix, got {c.shape}")
    if not np.isfinite(c).all():
        raise ValueError("corr_matrix contains NaN/inf")
    if q <= 0:
        raise ValueError(f"q must be > 0 (= N/T), got {q}")
    lambda_plus = (1 + np.sqrt(q)) ** 2
    eigenvalues = np.maximum(np.linalg.eigvalsh(c), 0.0)
    return int(np.sum(eigenvalues > lambda_plus)), float(lambda_plus)
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_analytics_rmt.py -v`
  - Expected: all 13 tests pass. (Verified numerically: δ=1.0 for the load=0.8 case; off-diagonals positive; min eig 0.037>−1e-10; raw_noise.size=7≥2 and raw.std>den.std; ar_single=0.99>0.5, ar_indep=0.249<0.5; identity k=1→0.2, k=2→0.4; n_signal=1 with λ₊≈1.44.)

- [ ] **Step 5: Commit.**
  - `git add backend/app/analytics/rmt.py backend/tests/test_analytics_rmt.py`
  - Message:
    ```
    feat(analytics): shared RMT module — constant-correlation LW 2003 + MP denoise + absorption

    Single home for the RMT primitives ported from the legacy
    correlation_regime_service: ledoit_wolf_constant_correlation,
    marchenko_pastur_denoise, absorption_ratio (canonical; T2E imports it),
    mp_signal_eigenvalues. Pure numpy, fail-loud, decimal-fraction scale.

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-2: Engine SCS fallback ladder + post-solve constraint re-verification + solve telemetry

**Files:**
- Modify: `backend/app/optimizer/engine.py` — add `from dataclasses import dataclass`, `_SOLVER_LADDER`, `SolveTelemetry` after `_WEIGHT_ATOL = 1e-6` (line 28); add `_verify_constraints` just before `_finalize` (line 92); replace the body of `_finalize` (lines 92–112); change the `solve_min_vol` return at line 153 and the `solve_min_cvar` return at line 282.
- Test: `backend/tests/test_optimizer_engine.py` (append after line 169; the file currently ends at line 168 with the G5 structural test).

`_finalize` currently calls `problem.solve()` once with the default solver and raises on any non-optimal status (engine.py lines 92–112). This task hardens it: try CLARABEL (the cvxpy conic default — confirmed installed), then fall back to SCS (confirmed installed) on failure/non-optimal, and after a successful solve RE-VERIFY the realized constraints (long-only within `_WEIGHT_ATOL`, sum=1 within 1e-4, cap and min_weight if supplied) before returning. A `SolveTelemetry` dataclass records the winning solver, fallback usage, and the realized max-weight/sum. The public 2-tuple return `(weights, status)` is unchanged so all existing callers keep working.

NOTE (scope): only `_finalize` callers gain the ladder — `solve_min_vol`/`solve_min_cvar` (engine.py) and `solve_bl_utility`/`solve_bl_robust`/`solve_bl_vol_target` (black_litterman.py). `solve_erc` (engine.py lines 182–193) and `solve_max_diversification` (lines 220–234) keep their OWN inline `problem.solve()` and are not touched here.

GATE G5: none of the added code estimates a mean — verified no `.mean(`/`np.average` token is introduced into engine.py, so the structural gate `test_g5_structural_no_mean_estimation_in_engine_or_data` (lines 154–162) stays green.

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_engine.py`:

```python
# ── T3F-2: SCS fallback + post-solve re-verification + telemetry ──────────────

from app.optimizer.engine import SolveTelemetry, _finalize, _verify_constraints


def test_finalize_telemetry_records_solver_and_realized_constraints() -> None:
    import cvxpy as cp

    sigma = np.diag([0.04, 0.09, 0.16])
    w = cp.Variable(3)
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))),
        engine.base_constraints(w, cap=0.5, min_weight=None),
    )
    weights, status, telemetry = _finalize(
        problem, w, "tele", cap=0.5, min_weight=None, with_telemetry=True
    )
    assert status == "optimal"
    assert isinstance(telemetry, SolveTelemetry)
    assert telemetry.solver in {"CLARABEL", "SCS"}
    assert telemetry.used_fallback in {True, False}
    assert telemetry.realized_max_weight <= 0.5 + 1e-6
    assert abs(telemetry.realized_sum - 1.0) < 1e-6


def test_finalize_default_signature_still_returns_two_tuple() -> None:
    """Back-compat: without with_telemetry, _finalize returns (weights, status)."""
    import cvxpy as cp

    sigma = np.diag([0.04, 0.09])
    w = cp.Variable(2)
    problem = cp.Problem(
        cp.Minimize(cp.quad_form(w, cp.psd_wrap(sigma))),
        engine.base_constraints(w, cap=None, min_weight=None),
    )
    result = _finalize(problem, w, "compat", cap=None, min_weight=None)
    assert isinstance(result, tuple) and len(result) == 2
    weights, status = result
    _assert_valid(weights, status)


def test_verify_constraints_rejects_cap_violation() -> None:
    weights = np.array([0.6, 0.4])
    ok, reason = _verify_constraints(weights, cap=0.5, min_weight=None)
    assert ok is False
    assert "cap" in reason


def test_verify_constraints_rejects_sum_violation() -> None:
    weights = np.array([0.5, 0.4])  # sums to 0.9
    ok, reason = _verify_constraints(weights, cap=None, min_weight=None)
    assert ok is False
    assert "sum" in reason


def test_verify_constraints_rejects_min_weight_violation() -> None:
    weights = np.array([0.95, 0.05])
    ok, reason = _verify_constraints(weights, cap=None, min_weight=0.1)
    assert ok is False
    assert "min_weight" in reason


def test_verify_constraints_accepts_valid() -> None:
    weights = np.array([0.5, 0.5])
    ok, reason = _verify_constraints(weights, cap=0.6, min_weight=0.1)
    assert ok is True
    assert reason == ""


def test_solve_min_vol_still_passes_post_verification() -> None:
    """The public solver path now runs post-solve re-verification internally;
    a normal solve must still succeed and respect the cap."""
    sigma = np.diag([0.05**2, 0.2**2, 0.2**2, 0.2**2, 0.2**2])
    weights, status = engine.solve_min_vol(sigma, cap=0.25)
    _assert_valid(weights, status, cap=0.25)
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_engine.py -k "T3F or finalize or verify_constraints" -v`
  - Expected failure: `ImportError: cannot import name 'SolveTelemetry' from 'app.optimizer.engine'` (and `_verify_constraints` missing; `_finalize` lacks `cap`/`min_weight`/`with_telemetry`).

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/optimizer/engine.py`:

  (a) After `_WEIGHT_ATOL = 1e-6` (line 28), add the dataclass import + ladder + telemetry record:

```python
from dataclasses import dataclass

# CLARABEL is cvxpy's conic default for these QPs/SOCPs; SCS is the robust
# fallback (handles ill-conditioned cones the default may reject). Both are
# confirmed in cp.installed_solvers() (1.8.1).
_SOLVER_LADDER = ("CLARABEL", "SCS")


@dataclass(frozen=True)
class SolveTelemetry:
    """Observability for a single engine solve."""

    solver: str
    status: str
    used_fallback: bool
    realized_sum: float
    realized_max_weight: float
    n_assets: int
```

  (b) Add `_verify_constraints` immediately before `_finalize` (i.e. before the current line 92):

```python
def _verify_constraints(
    weights: np.ndarray, cap: float | None, min_weight: float | None
) -> tuple[bool, str]:
    """Post-solve re-verification of the realized weight vector.

    Returns (ok, reason). ``ok`` is False with a human reason on the first
    violation (long-only, sum=1, cap, min_weight); empty reason when valid.
    """
    w = np.asarray(weights, dtype=float).ravel()
    if (w < -_WEIGHT_ATOL).any():
        return False, f"negative weight {float(w.min())}"
    total = float(w.sum())
    if abs(total - 1.0) > 1e-4:
        return False, f"weights sum to {total}, expected 1"
    if cap is not None and (w > cap + 1e-6).any():
        return False, f"cap {cap} violated (max weight {float(w.max())})"
    if min_weight is not None and (w < min_weight - 1e-6).any():
        return False, f"min_weight {min_weight} violated (min weight {float(w.min())})"
    return True, ""
```

  (c) Replace the WHOLE current `_finalize` body (engine.py lines 92–112) with:

```python
def _finalize(
    problem: cp.Problem,
    w: cp.Variable,
    label: str,
    cap: float | None = None,
    min_weight: float | None = None,
    with_telemetry: bool = False,
) -> tuple[np.ndarray, str] | tuple[np.ndarray, str, SolveTelemetry]:
    """Solve with an SCS fallback ladder, demand ``optimal``, clean numerical
    noise, then RE-VERIFY the realized constraints before returning.

    Returns ``(weights, status)`` by default; with ``with_telemetry=True``
    returns ``(weights, status, SolveTelemetry)``.
    """
    used_fallback = False
    last_status = "unknown"
    solver_name = _SOLVER_LADDER[0]
    for i, solver in enumerate(_SOLVER_LADDER):
        try:
            problem.solve(solver=solver)
        except cp.error.SolverError:  # pragma: no cover - solver-dependent
            last_status = "solver_error"
            used_fallback = i > 0
            continue
        last_status = str(problem.status)
        solver_name = solver
        used_fallback = i > 0
        if last_status == cp.OPTIMAL and w.value is not None:
            break
    if last_status != cp.OPTIMAL:
        raise OptimizerError(f"{label}: solver status '{last_status}' (expected 'optimal')")
    if w.value is None:  # pragma: no cover - defensive
        raise OptimizerError(f"{label}: solver returned no solution")

    weights = np.asarray(w.value, dtype=float).ravel()
    weights[np.abs(weights) < 1e-10] = 0.0
    if (weights < -_WEIGHT_ATOL).any():
        raise OptimizerError(f"{label}: negative weight in solution: {weights.min()}")
    weights = np.clip(weights, 0.0, None)
    total = float(weights.sum())
    if abs(total - 1.0) > 1e-4:
        raise OptimizerError(f"{label}: weights sum to {total}, expected 1")
    weights = weights / total

    ok, reason = _verify_constraints(weights, cap, min_weight)
    if not ok:
        raise OptimizerError(f"{label}: post-solve constraint check failed: {reason}")

    if with_telemetry:
        telemetry = SolveTelemetry(
            solver=solver_name,
            status=last_status,
            used_fallback=used_fallback,
            realized_sum=float(weights.sum()),
            realized_max_weight=float(weights.max()),
            n_assets=int(weights.size),
        )
        return weights, last_status, telemetry
    return weights, last_status
```

  (d) Activate cap re-verification on the two `_finalize` callers in engine.py:
  - line 153: change `return _finalize(problem, w, "min_vol")` → `return _finalize(problem, w, "min_vol", cap=cap, min_weight=min_weight)`
  - line 282: change `return _finalize(problem, w, "min_cvar")` → `return _finalize(problem, w, "min_cvar", cap=cap, min_weight=min_weight)`

  (Do NOT change `solve_bl_utility` in black_litterman.py here — T3F-3/T3F-4 add the new callers; the existing `_finalize(problem, w, "bl_utility")` 3-arg call keeps working because the new params default to None.)

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_engine.py -v`
  - Expected: the 7 new T3F-2 tests pass AND all pre-existing G2/G4/G5 tests still pass — in particular `test_g5_structural_no_mean_estimation_in_engine_or_data` (engine.py still has zero `.mean(`) and the back-compat 2-tuple path keeps `solve_min_vol`/`solve_min_cvar` returning `(weights, status)`.

- [ ] **Step 5: Commit.**
  - `git add backend/app/optimizer/engine.py backend/tests/test_optimizer_engine.py`
  - Message:
    ```
    feat(optimizer): SCS fallback ladder + post-solve constraint re-verification + solve telemetry

    _finalize now tries CLARABEL then SCS, re-verifies the realized weight
    vector (long-only/sum=1/cap/min_weight) before returning, and can emit a
    SolveTelemetry record. Back-compat 2-tuple return preserved for existing
    callers; min_vol/min_cvar opt into cap re-verification. No mean estimated
    (gate G5 intact).

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-3: Robust / ellipsoidal mean-uncertainty SOCP (κ·‖Lᵀw‖₂, κ from chi2.ppf)

**Files:**
- Modify: `backend/app/optimizer/black_litterman.py` — append `_kappa_from_chi2` and `solve_bl_robust` after `solve_bl_utility` (current EOF is line 277). Reuses the already-imported `cp`, `np`, `OptimizerError`, `_check_constraint_params`, `_validate_sigma`, `base_constraints`, `_finalize` (import block lines 22–29).
- Test: `backend/tests/test_optimizer_black_litterman.py` (append; file currently ends after the existing BL gate tests).

Gate G5: this solver CONSUMES a μ vector, so by contract it lives in `black_litterman.py` alongside `solve_bl_utility` — μ comes only from the BL posterior (or π). It maximizes `μᵀw − κ·‖Lᵀw‖₂` (long-only, sum=1, optional cap/min) where `L = cholesky(Σ)` and `κ = √(chi2.ppf(confidence, df=n))` scaled by an optional `uncertainty_level`. Infeasibility (bad constraints, non-optimal solve) raises `OptimizerError` (→ 422). Ported from legacy `optimizer_service.py` lines 1471–1497. G5 structural: this adds NO `.mean(`, so `black_litterman.py` keeps EXACTLY one `.mean(` (verified) and the gate stays green.

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_black_litterman.py`:

```python
# ── T3F-3: robust / ellipsoidal mean-uncertainty SOCP ────────────────────────

import pytest as _pytest
from scipy.stats import chi2 as _chi2

from app.optimizer import black_litterman as _bl
from app.optimizer.engine import OptimizerError as _OptErr


def test_kappa_from_chi2_matches_sqrt_ppf() -> None:
    kappa = _bl._kappa_from_chi2(0.95, n=4, uncertainty_level=None)
    assert kappa == _pytest.approx(float(np.sqrt(_chi2.ppf(0.95, 4))), rel=1e-9)


def test_kappa_scales_with_uncertainty_level() -> None:
    base = _bl._kappa_from_chi2(0.95, n=3, uncertainty_level=None)
    half = _bl._kappa_from_chi2(0.95, n=3, uncertainty_level=0.5)
    assert half == _pytest.approx(0.5 * base, rel=1e-9)


def test_solve_bl_robust_returns_valid_weights() -> None:
    mu = np.array([0.10, 0.08, 0.06])
    sigma = np.diag([0.04, 0.06, 0.09])
    weights, status = _bl.solve_bl_robust(mu, sigma, cap=None)
    assert status == "optimal"
    assert abs(float(weights.sum()) - 1.0) < 1e-6
    assert (weights >= -1e-6).all()


def test_solve_bl_robust_more_uncertainty_shrinks_toward_min_vol() -> None:
    """Higher κ penalizes risky concentration; with strong uncertainty the
    robust portfolio is LESS concentrated than the near-zero-κ (pure-μ) tilt."""
    mu = np.array([0.20, 0.05, 0.05])
    sigma = np.diag([0.09, 0.04, 0.04])
    low, _ = _bl.solve_bl_robust(mu, sigma, cap=None, uncertainty_level=0.01)
    high, _ = _bl.solve_bl_robust(mu, sigma, cap=None, uncertainty_level=3.0)
    assert high[0] < low[0]


def test_solve_bl_robust_respects_cap() -> None:
    mu = np.array([0.20, 0.05, 0.05, 0.05])
    sigma = np.diag([0.04, 0.04, 0.04, 0.04])
    weights, status = _bl.solve_bl_robust(mu, sigma, cap=0.4)
    assert status == "optimal"
    assert (weights <= 0.4 + 1e-6).all()


def test_solve_bl_robust_rejects_mu_shape_mismatch() -> None:
    mu = np.array([0.1, 0.1])  # 2 assets
    sigma = np.diag([0.04, 0.04, 0.04])  # 3x3
    with _pytest.raises(_OptErr, match="mu has shape"):
        _bl.solve_bl_robust(mu, sigma, cap=None)


def test_solve_bl_robust_infeasible_cap_reports_loud() -> None:
    mu = np.array([0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="infeasible"):
        _bl.solve_bl_robust(mu, sigma, cap=0.25)  # 0.25*2 < 1


def test_solve_bl_robust_rejects_bad_confidence() -> None:
    mu = np.array([0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="confidence"):
        _bl.solve_bl_robust(mu, sigma, cap=None, confidence=1.5)
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_black_litterman.py -k "robust or kappa" -v`
  - Expected failure: `AttributeError: module 'app.optimizer.black_litterman' has no attribute '_kappa_from_chi2'` (and `solve_bl_robust`).

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/optimizer/black_litterman.py` (after `solve_bl_utility`, current line 277):

```python
def _kappa_from_chi2(
    confidence: float, n: int, uncertainty_level: float | None
) -> float:
    """Ellipsoid radius κ = √(chi2.ppf(confidence, df=n)), optionally scaled.

    The (1-confidence) ellipsoidal confidence region of a μ estimate has
    half-width √(χ²_{n}(confidence)) in the Σ-metric (legacy
    optimizer_service lines 1471-1472). ``uncertainty_level`` (>0) linearly
    rescales the radius; None ⇒ 1.0.
    """
    from scipy.stats import chi2

    if not 0 < confidence < 1:
        raise OptimizerError(f"bl_robust: confidence must be in (0, 1), got {confidence}")
    if n < 1:
        raise OptimizerError("bl_robust: n must be >= 1")
    kappa = float(np.sqrt(chi2.ppf(confidence, df=n)))
    if uncertainty_level is not None:
        if uncertainty_level <= 0:
            raise OptimizerError(
                f"bl_robust: uncertainty_level must be > 0, got {uncertainty_level}"
            )
        kappa *= float(uncertainty_level)
    return kappa


def solve_bl_robust(
    mu_ann: np.ndarray,
    sigma_ann: np.ndarray,
    cap: float | None = None,
    min_weight: float | None = None,
    confidence: float = 0.95,
    uncertainty_level: float | None = None,
) -> tuple[np.ndarray, str]:
    """Robust max-return under ellipsoidal μ-uncertainty (SOCP).

        max  μᵀw − κ·‖Lᵀw‖₂      s.t. long-only, sum(w)=1, optional cap/min

    where L = cholesky(Σ) and κ = √(chi2.ppf(confidence, df=n)) scaled by
    ``uncertainty_level``. Gate G5: μ is the BL posterior (or π) — never a
    sample mean. Ported from legacy optimizer_service Phase-2 robust RU.

    Infeasibility / non-optimal solve raise ``OptimizerError`` (→ 422).
    """
    sigma_ann = _validate_sigma(sigma_ann, "bl_robust")
    mu_arr = np.asarray(mu_ann, dtype=float).ravel()
    n = sigma_ann.shape[0]
    if mu_arr.shape != (n,):
        raise OptimizerError(f"bl_robust: mu has shape {mu_arr.shape}, expected ({n},)")
    _check_constraint_params(n, cap, min_weight)

    try:
        chol = np.linalg.cholesky(sigma_ann)
    except np.linalg.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(sigma_ann)
        floored = np.maximum(eigvals, 1e-12)
        chol = eigvecs @ np.diag(np.sqrt(floored))

    kappa = _kappa_from_chi2(confidence, n, uncertainty_level)
    w = cp.Variable(n)
    objective = cp.Maximize(mu_arr @ w - kappa * cp.norm(chol.T @ w, 2))
    problem = cp.Problem(objective, base_constraints(w, cap, min_weight))
    return _finalize(problem, w, "bl_robust", cap=cap, min_weight=min_weight)
```

  Note on the infeasible-cap test: `_check_constraint_params(n, cap, ...)` (engine.py line 64) raises `OptimizerError("infeasible constraints: cap ... × ... < 1 ...")` BEFORE the solve, so `match="infeasible"` is satisfied pre-solve.

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_black_litterman.py -v`
  - Expected: the 8 new robust/kappa tests pass; all pre-existing BL tests still pass. (Verified numerically: κ matches √chi2.ppf and scales linearly; low[0]=1.0 vs high[0]=0.20 so high<low; cap=0.4 respected.) The G5 structural count of `.mean(` in `black_litterman.py` stays 1 (this task adds none) — covered by the engine G5 test re-run in T3F-8.

- [ ] **Step 5: Commit.**
  - `git add backend/app/optimizer/black_litterman.py backend/tests/test_optimizer_black_litterman.py`
  - Message:
    ```
    feat(optimizer): robust ellipsoidal mean-uncertainty SOCP (solve_bl_robust)

    max μᵀw − κ·‖Lᵀw‖₂ with κ = √(chi2.ppf(conf, df=n)) scaled by an optional
    uncertainty_level; L = cholesky(Σ) with an eigenvalue-floor repair. Lives
    in black_litterman.py (gate G5: μ-consuming). Fail-loud on shape/cap.

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-4: Volatility-target SOCP (‖cholᵀw‖₂ ≤ vol_target) with infeasibility reporting

**Files:**
- Modify: `backend/app/optimizer/black_litterman.py` (append `solve_bl_vol_target` after `solve_bl_robust`)
- Test: `backend/tests/test_optimizer_black_litterman.py` (append)

Maximize BL expected return subject to an annualized volatility cap expressed as the second-order cone `‖cholᵀw‖₂ ≤ vol_target` (legacy `optimizer_service.py` line 1135). μ-consuming ⇒ lives with BL. When the cap is so tight that even the minimum-variance portfolio exceeds it, the SOCP is infeasible — reported loud with the achievable floor volatility (mirrors the legacy floor-vol check at lines 1315–1326). Adds NO `.mean(` (gate G5 count stays 1).

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_optimizer_black_litterman.py`:

```python
# ── T3F-4: volatility-target SOCP ────────────────────────────────────────────


def test_solve_bl_vol_target_caps_realized_volatility() -> None:
    mu = np.array([0.12, 0.08, 0.05])
    sigma = np.diag([0.09, 0.04, 0.01])  # vols 0.30, 0.20, 0.10
    target = 0.15
    weights, status = _bl.solve_bl_vol_target(mu, sigma, vol_target=target, cap=None)
    assert status == "optimal"
    realized = float(np.sqrt(weights @ sigma @ weights))
    assert realized <= target + 1e-4
    assert abs(float(weights.sum()) - 1.0) < 1e-6


def test_solve_bl_vol_target_tilts_toward_high_mu_when_slack() -> None:
    """With a generous vol cap, the optimizer loads the highest-μ asset more
    than equal weight."""
    mu = np.array([0.20, 0.05, 0.05])
    sigma = np.diag([0.04, 0.04, 0.04])
    weights, _ = _bl.solve_bl_vol_target(mu, sigma, vol_target=0.19, cap=None)
    assert weights[0] > 1.0 / 3.0


def test_solve_bl_vol_target_infeasible_when_target_below_floor_vol() -> None:
    mu = np.array([0.10, 0.10])
    sigma = np.diag([0.04, 0.04])  # every long-only portfolio has vol 0.2
    with _pytest.raises(_OptErr, match="infeasible|vol_target"):
        _bl.solve_bl_vol_target(mu, sigma, vol_target=0.05, cap=None)


def test_solve_bl_vol_target_rejects_nonpositive_target() -> None:
    mu = np.array([0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="vol_target must be > 0"):
        _bl.solve_bl_vol_target(mu, sigma, vol_target=0.0, cap=None)


def test_solve_bl_vol_target_rejects_mu_shape_mismatch() -> None:
    mu = np.array([0.1, 0.1, 0.1])
    sigma = np.diag([0.04, 0.04])
    with _pytest.raises(_OptErr, match="mu has shape"):
        _bl.solve_bl_vol_target(mu, sigma, vol_target=0.3, cap=None)


def test_solve_bl_vol_target_respects_cap() -> None:
    mu = np.array([0.30, 0.05, 0.05, 0.05])
    sigma = np.diag([0.04, 0.04, 0.04, 0.04])
    weights, status = _bl.solve_bl_vol_target(mu, sigma, vol_target=0.19, cap=0.4)
    assert status == "optimal"
    assert (weights <= 0.4 + 1e-6).all()
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_black_litterman.py -k "vol_target" -v`
  - Expected failure: `AttributeError: module 'app.optimizer.black_litterman' has no attribute 'solve_bl_vol_target'`.

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/optimizer/black_litterman.py` (after `solve_bl_robust`):

```python
def solve_bl_vol_target(
    mu_ann: np.ndarray,
    sigma_ann: np.ndarray,
    vol_target: float,
    cap: float | None = None,
    min_weight: float | None = None,
) -> tuple[np.ndarray, str]:
    """Max BL return subject to an annualized volatility cap (SOCP).

        max μᵀw   s.t.  ‖Lᵀw‖₂ ≤ vol_target, long-only, sum(w)=1, cap/min

    where L = cholesky(Σ). μ-consuming ⇒ lives with BL (gate G5). When the
    target is below the achievable floor volatility (min-variance portfolio),
    the cone is infeasible and the failure is reported loud with that floor.
    Ported from legacy optimizer_service vol_target phase (line 1135).
    """
    sigma_ann = _validate_sigma(sigma_ann, "bl_vol_target")
    mu_arr = np.asarray(mu_ann, dtype=float).ravel()
    n = sigma_ann.shape[0]
    if mu_arr.shape != (n,):
        raise OptimizerError(f"bl_vol_target: mu has shape {mu_arr.shape}, expected ({n},)")
    if vol_target <= 0:
        raise OptimizerError(f"bl_vol_target: vol_target must be > 0, got {vol_target}")
    _check_constraint_params(n, cap, min_weight)

    try:
        chol = np.linalg.cholesky(sigma_ann)
    except np.linalg.LinAlgError:
        eigvals, eigvecs = np.linalg.eigh(sigma_ann)
        floored = np.maximum(eigvals, 1e-12)
        chol = eigvecs @ np.diag(np.sqrt(floored))

    w = cp.Variable(n)
    cons = base_constraints(w, cap, min_weight)
    cons.append(cp.norm(chol.T @ w, 2) <= vol_target)
    problem = cp.Problem(cp.Maximize(mu_arr @ w), cons)
    try:
        return _finalize(problem, w, "bl_vol_target", cap=cap, min_weight=min_weight)
    except OptimizerError as exc:
        # Surface the achievable floor when the cap is the binding cause.
        floor_w = cp.Variable(n)
        floor_prob = cp.Problem(
            cp.Minimize(cp.quad_form(floor_w, cp.psd_wrap(sigma_ann))),
            base_constraints(floor_w, cap, min_weight),
        )
        try:
            floor_prob.solve()
        except cp.error.SolverError:  # pragma: no cover - solver-dependent
            raise exc
        if floor_w.value is not None and str(floor_prob.status) == cp.OPTIMAL:
            floor_vol = float(np.sqrt(floor_w.value @ sigma_ann @ floor_w.value))
            if floor_vol > vol_target + 1e-6:
                raise OptimizerError(
                    f"bl_vol_target infeasible: target vol {vol_target} is below the "
                    f"achievable floor {floor_vol:.6f} under these constraints — "
                    "raise the target or relax the cap"
                ) from exc
        raise exc
```

  Note: when the cone is infeasible, `_finalize` raises `OptimizerError("bl_vol_target: solver status 'infeasible' ...")` (the CLARABEL→SCS ladder both return `infeasible`, verified). The except-branch then solves the min-variance floor and re-raises with the floor vol — the test's `match="infeasible|vol_target"` matches EITHER message.

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_black_litterman.py -v`
  - Expected: the 6 new vol-target tests pass; all earlier BL + robust tests still pass. (Verified numerically: realized vol 0.15 at cap 0.15; tilt w[0]=0.95>1/3; infeasible status="infeasible" when target 0.05 < floor 0.2.)

- [ ] **Step 5: Commit.**
  - `git add backend/app/optimizer/black_litterman.py backend/tests/test_optimizer_black_litterman.py`
  - Message:
    ```
    feat(optimizer): volatility-target SOCP (solve_bl_vol_target) with floor-vol infeasibility report

    max μᵀw s.t. ‖cholᵀw‖₂ ≤ vol_target; on infeasibility, solves the
    min-variance floor and reports the achievable floor volatility in the
    error. μ-consuming ⇒ lives with BL (gate G5). Fail-loud on target/shape.

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-6: Correlation-regime response + request schemas (execute BEFORE T3F-5)

**Files:**
- Create: `backend/app/schemas/correlation_regime.py`
- Test: `backend/tests/test_correlation_regime_route.py` (SCHEMA section; the ROUTE section is appended in T3F-7)

Pydantic schemas for the service output (`CorrelationRegimeOut`, `ConcentrationOut`, `PairCorrelationOut`) and the request (`CorrelationRegimeRequest`, mirroring the builder's explicit-`assets`-OR-`universe` shape so the route reuses the same selection semantics). Reuses the VERIFIED builder types `AssetRefIn` (discriminated `FundRefIn|EquityRefIn`, builder.py line 29) and `UniverseSpecIn` (builder.py line 95). All fractional fields are decimal fractions.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_correlation_regime_route.py` with the SCHEMA section:

```python
"""Tests for the correlation-regime schema (T3F-6) and route (T3F-7).

Schema section pins field shapes/validators; route section (T3F-7) stubs the
service and asserts the wire payload + 422 mapping.
"""

import pytest

from app.schemas.correlation_regime import (
    ConcentrationOut,
    CorrelationRegimeOut,
    CorrelationRegimeRequest,
    PairCorrelationOut,
)


# ── T3F-6: schema validation ─────────────────────────────────────────────────


def _concentration() -> ConcentrationOut:
    return ConcentrationOut(
        eigenvalues=[3.1, 0.5, 0.4],
        first_eigenvalue_ratio=0.7,
        concentration_status="moderate_concentration",
        absorption_ratio=0.82,
        absorption_status="warning",
        mp_threshold=1.58,
        n_signal_eigenvalues=1,
    )


def test_correlation_regime_out_roundtrip() -> None:
    out = CorrelationRegimeOut(
        instrument_count=2,
        labels=["fund:a", "fund:b"],
        window_days=60,
        correlation_matrix=[[1.0, 0.4], [0.4, 1.0]],
        pair_correlations=[
            PairCorrelationOut(
                label_a="fund:a",
                label_b="fund:b",
                current_correlation=0.4,
                baseline_correlation=0.2,
                correlation_change=0.2,
                is_contagion=False,
            )
        ],
        concentration=_concentration(),
        diversification_ratio=1.3,
        dr_alert=False,
        average_correlation=0.4,
        baseline_average_correlation=0.2,
        regime_shift_detected=False,
        sufficient_data=True,
    )
    dumped = out.model_dump()
    assert dumped["instrument_count"] == 2
    assert dumped["pair_correlations"][0]["is_contagion"] is False
    assert dumped["concentration"]["absorption_status"] == "warning"


def test_request_requires_exactly_one_source() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CorrelationRegimeRequest()  # neither assets nor universe


def test_request_rejects_both_sources() -> None:
    with pytest.raises(ValueError, match="exactly one"):
        CorrelationRegimeRequest(
            assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}],
            universe={"max_assets": 5},
        )


def test_request_accepts_explicit_assets() -> None:
    req = CorrelationRegimeRequest(
        assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}]
    )
    assert req.assets is not None and len(req.assets) == 2
    assert req.universe is None


def test_request_window_days_bounds() -> None:
    with pytest.raises(ValueError):
        CorrelationRegimeRequest(
            assets=[{"kind": "equity", "ticker": "SPY"}, {"kind": "equity", "ticker": "QQQ"}],
            window_days=10,  # below the 30 floor
        )
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_route.py -k "schema or request or roundtrip" -v`
  - Expected failure: `ModuleNotFoundError: No module named 'app.schemas.correlation_regime'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/schemas/correlation_regime.py`:

```python
"""Schemas for POST /correlation-regime (T3F).

Scale contract: correlations, ratios and the diversification ratio are decimal
fractions / pure numbers (never 0-100). The request mirrors the builder's
explicit-``assets``-OR-``universe`` shape (app.schemas.builder) so the route
reuses the same fund/equity selection semantics.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.builder import AssetRefIn, UniverseSpecIn


class PairCorrelationOut(BaseModel):
    label_a: str
    label_b: str
    current_correlation: float
    baseline_correlation: float
    correlation_change: float
    is_contagion: bool


class ConcentrationOut(BaseModel):
    eigenvalues: list[float]
    first_eigenvalue_ratio: float
    concentration_status: Literal[
        "diversified", "moderate_concentration", "high_concentration"
    ]
    absorption_ratio: float
    absorption_status: Literal["normal", "warning", "critical"]
    mp_threshold: float  # Marchenko-Pastur upper bound λ₊
    n_signal_eigenvalues: int


class CorrelationRegimeOut(BaseModel):
    instrument_count: int
    labels: list[str]
    window_days: int
    correlation_matrix: list[list[float]]
    pair_correlations: list[PairCorrelationOut]
    concentration: ConcentrationOut
    diversification_ratio: float
    dr_alert: bool
    average_correlation: float
    baseline_average_correlation: float
    regime_shift_detected: bool
    sufficient_data: bool


class CorrelationRegimeRequest(BaseModel):
    """Analyze either an explicit ``assets`` list OR a ``universe`` spec
    (exactly one), over the optimizer's aligned returns matrix.
    """

    assets: Annotated[list[AssetRefIn], Field(min_length=2, max_length=50)] | None = None
    universe: UniverseSpecIn | None = None
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None

    @model_validator(mode="after")
    def _check_source(self) -> "CorrelationRegimeRequest":
        if (self.assets is None) == (self.universe is None):
            raise ValueError(
                "provide exactly one of 'assets' (explicit list) or 'universe' "
                "(filter+rank the fund universe)"
            )
        return self
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_route.py -k "schema or request or roundtrip" -v`
  - Expected: all 5 schema tests pass. (The exactly-one-source validator mirrors `OptimizeRequest._check_asset_source` at builder.py lines 148–154; `window_days` bound mirrors builder.py line 142.)

- [ ] **Step 5: Commit.**
  - `git add backend/app/schemas/correlation_regime.py backend/tests/test_correlation_regime_route.py`
  - Message:
    ```
    feat(schemas): correlation-regime request/response schemas

    CorrelationRegimeOut/ConcentrationOut/PairCorrelationOut + a
    CorrelationRegimeRequest mirroring the builder's assets-OR-universe shape
    (reuses AssetRefIn/UniverseSpecIn). Decimal-fraction scale;
    exactly-one-source validator.

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-5: Correlation-regime/contagion service (pure assemble over the (T,N) matrix, using the RMT module)

**Files:**
- Create: `backend/app/services/correlation_regime.py`
- Test: `backend/tests/test_correlation_regime_service.py`

Pure `assemble_correlation_regime(returns_matrix, labels, ...) -> CorrelationRegimeOut` (no I/O) plus an async `run_correlation_regime(session, refs, window_days=None, today=None) -> CorrelationRegimeOut` orchestrator that loads the SAME aligned `(T,N)` matrix the optimizer builds (`optimizer_data.load_aligned_returns(session, refs, window_days=..., today=...)` — VERIFIED signature `(session, assets, window_days, today)`, then `frame.to_numpy(dtype=float)`) and calls the pure assembler. The assembler ports the legacy rolling logic (`compute_correlation_regime` lines 373–501): recent window (≤60d) and baseline split, constant-correlation LW shrinkage on BOTH (via `app.analytics.rmt`), MP denoise for eigenvalue/contagion analysis (raw correlation for display), per-pair contagion (`|Δ|>0.3 AND current>0.7`), average-corr regime shift, concentration status, and absorption (via `rmt.absorption_ratio` — NOT duplicated). Imports the T3F-6 schema. PREREQUISITE: T3F-6 must be committed first.

> Dependency note (T2C): this service is self-contained over the numpy matrix; it has no hard dependency on T2C. See open_questions.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_correlation_regime_service.py`:

```python
"""Unit tests for the correlation-regime/contagion pure assembler.

assemble_correlation_regime operates on a synthetic (T,N) returns matrix — no
DB, no I/O. Math is delegated to app.analytics.rmt (shared) — these tests pin
the regime/contagion ASSEMBLY, not the RMT primitives (covered in T3F-1).
"""

import numpy as np
import pytest

from app.services import correlation_regime as cr


def _regime_returns(
    t: int, n: int, recent_load: float, base_load: float, window: int = 60, seed: int = 7
) -> np.ndarray:
    """(T,N) returns where the LAST `window` rows have a different common-factor
    loading than the earlier (baseline) rows — a synthetic regime shift."""
    rng = np.random.default_rng(seed)
    base_t = t - window
    base_common = rng.standard_normal((base_t, 1))
    base = base_load * base_common + (1.0 - base_load) * rng.standard_normal((base_t, n))
    rec_common = rng.standard_normal((window, 1))
    rec = recent_load * rec_common + (1.0 - recent_load) * rng.standard_normal((window, n))
    return np.vstack([base, rec])


def test_assemble_returns_full_payload_shape() -> None:
    x = _regime_returns(560, 5, recent_load=0.6, base_load=0.6)
    labels = [f"fund:{i}" for i in range(5)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.instrument_count == 5
    assert out.labels == labels
    assert len(out.correlation_matrix) == 5
    assert all(len(row) == 5 for row in out.correlation_matrix)
    assert len(out.pair_correlations) == 10  # N*(N-1)/2 unordered pairs
    assert out.concentration.absorption_status in {"normal", "warning", "critical"}
    assert out.sufficient_data is True


def test_assemble_detects_contagion_when_recent_corr_spikes() -> None:
    # Baseline weakly correlated, recent strongly correlated ⇒ contagion pairs.
    x = _regime_returns(560, 4, recent_load=0.95, base_load=0.1)
    labels = [f"fund:{i}" for i in range(4)]
    out = cr.assemble_correlation_regime(x, labels)
    assert any(p.is_contagion for p in out.pair_correlations)
    assert out.regime_shift_detected is True


def test_assemble_no_contagion_in_stable_regime() -> None:
    x = _regime_returns(560, 4, recent_load=0.3, base_load=0.3)
    labels = [f"fund:{i}" for i in range(4)]
    out = cr.assemble_correlation_regime(x, labels)
    assert not any(p.is_contagion for p in out.pair_correlations)


def test_assemble_high_concentration_for_single_factor() -> None:
    x = _regime_returns(560, 6, recent_load=0.97, base_load=0.97)
    labels = [f"fund:{i}" for i in range(6)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.concentration.first_eigenvalue_ratio > 0.5
    assert out.concentration.concentration_status in {
        "moderate_concentration",
        "high_concentration",
    }


def test_assemble_insufficient_data_flag() -> None:
    x = _regime_returns(40, 3, recent_load=0.5, base_load=0.5, window=20)
    labels = [f"fund:{i}" for i in range(3)]
    out = cr.assemble_correlation_regime(x, labels, min_observations=45)
    assert out.sufficient_data is False
    assert out.pair_correlations == []


def test_assemble_rejects_label_count_mismatch() -> None:
    x = _regime_returns(560, 4, recent_load=0.5, base_load=0.5)
    with pytest.raises(ValueError, match="labels"):
        cr.assemble_correlation_regime(x, ["a", "b"])  # 2 labels, 4 columns


def test_assemble_rejects_nan() -> None:
    x = _regime_returns(560, 3, recent_load=0.5, base_load=0.5)
    x[10, 0] = np.nan
    with pytest.raises(ValueError, match="NaN"):
        cr.assemble_correlation_regime(x, ["a", "b", "c"])


def test_diversification_ratio_at_least_one() -> None:
    x = _regime_returns(560, 5, recent_load=0.6, base_load=0.6)
    labels = [f"fund:{i}" for i in range(5)]
    out = cr.assemble_correlation_regime(x, labels)
    assert out.diversification_ratio >= 1.0 - 1e-9
```

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_service.py -v`
  - Expected failure: `ModuleNotFoundError: No module named 'app.services.correlation_regime'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/services/correlation_regime.py`:

```python
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
    return corr


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
    if first_ratio > _CONCENTRATION_HIGH:
        status = "high_concentration"
    elif first_ratio > _CONCENTRATION_MODERATE:
        status = "moderate_concentration"
    else:
        status = "diversified"
    ar = rmt.absorption_ratio(corr_denoised)
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
```

  Note: `np.mean(...)` here is over a CORRELATION matrix's upper triangle, not a returns mean — the gate G5 structural test (`.mean(` count) only inspects `engine.py`, `data.py`, and `black_litterman.py`, NOT `app/services/`, so this is unconstrained. `assemble_correlation_regime` also calls `arr.mean(...)` indirectly only inside `rmt.ledoit_wolf_constant_correlation` (analytics package, also unconstrained by G5).

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_service.py -v`
  - Expected: all 8 tests pass. (Verified numerically: 10 pairs for N=5; contagion+regime_shift True when recent spikes from 0.1→0.95; no contagion in stable 0.3/0.3; first_ratio=0.999>0.5 → high_concentration; insufficient → sufficient_data=False & pairs=[]; DR≥1 by construction.) REQUIRES T3F-6 committed (imports `app.schemas.correlation_regime`).

- [ ] **Step 5: Commit.**
  - `git add backend/app/services/correlation_regime.py backend/tests/test_correlation_regime_service.py`
  - Message:
    ```
    feat(services): correlation-regime/contagion assembler over the (T,N) optimizer matrix

    Pure assemble_correlation_regime + async run_correlation_regime (reuses
    optimizer_data.load_aligned_returns). Recent-vs-baseline rolling, per-pair
    contagion (|Δ|>0.3 & current>0.7), avg-corr regime shift, concentration +
    absorption — all RMT math delegated to app.analytics.rmt (no duplication).

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-7: Thin POST /correlation-regime route (validate → run → map ValueError to 422)

**Files:**
- Create: `backend/app/api/routes/correlation_regime.py`
- Modify: `backend/app/main.py` — add the import after the macro import (line 10) and the registration after the macro registration (line 59).
- Test: `backend/tests/test_correlation_regime_route.py` (append the ROUTE section)

Thin route over `app.services.correlation_regime`: translate request asset refs (or a universe spec) into `optimizer_data.AssetRef`s exactly as the builder does (verified `optimizer_data.FundAssetRef(id=...)` / `optimizer_data.EquityAssetRef(ticker=...)`, data.py lines 34–52), call `run_correlation_regime`, and map any `ValueError` (insufficient history, unknown asset, NaN) to HTTP 422. The universe path reuses `optimizer_data.select_universe_funds` (data.py lines 177–234, keyword-only after `*`) with `portfolio_builder._filters_from_spec` (portfolio_builder.py line 182). The route depends on `app.core.db.get_session` (verified import in builder route), overridable in tests via `app.dependency_overrides`.

- [ ] **Step 1: Write the failing test.** Append the ROUTE section to `backend/tests/test_correlation_regime_route.py`:

```python
# ── T3F-7: route ─────────────────────────────────────────────────────────────

from httpx import ASGITransport, AsyncClient

from app.core.db import get_session
from app.main import create_app
from app.services import correlation_regime as cr_service


def _route_client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _sample_out() -> CorrelationRegimeOut:
    return CorrelationRegimeOut(
        instrument_count=2,
        labels=["equity:SPY", "equity:QQQ"],
        window_days=60,
        correlation_matrix=[[1.0, 0.85], [0.85, 1.0]],
        pair_correlations=[
            PairCorrelationOut(
                label_a="equity:SPY",
                label_b="equity:QQQ",
                current_correlation=0.85,
                baseline_correlation=0.5,
                correlation_change=0.35,
                is_contagion=True,
            )
        ],
        concentration=_concentration(),
        diversification_ratio=1.05,
        dr_alert=True,
        average_correlation=0.85,
        baseline_average_correlation=0.5,
        regime_shift_detected=True,
        sufficient_data=True,
    )


async def test_route_returns_regime_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(session, refs, window_days=None, today=None):
        # Echo that the two equity refs were translated correctly.
        assert [r.label for r in refs] == ["equity:SPY", "equity:QQQ"]
        return _sample_out()

    monkeypatch.setattr(cr_service, "run_correlation_regime", fake_run)
    async with _route_client() as client:
        resp = await client.post(
            "/correlation-regime",
            json={
                "assets": [
                    {"kind": "equity", "ticker": "SPY"},
                    {"kind": "equity", "ticker": "QQQ"},
                ]
            },
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["regime_shift_detected"] is True
    assert body["pair_correlations"][0]["is_contagion"] is True
    assert body["concentration"]["absorption_status"] == "warning"


async def test_route_maps_value_error_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_run(session, refs, window_days=None, today=None):
        raise ValueError("insufficient common history: 12 overlapping observations")

    monkeypatch.setattr(cr_service, "run_correlation_regime", fake_run)
    async with _route_client() as client:
        resp = await client.post(
            "/correlation-regime",
            json={
                "assets": [
                    {"kind": "equity", "ticker": "SPY"},
                    {"kind": "equity", "ticker": "QQQ"},
                ]
            },
        )
    assert resp.status_code == 422
    assert "insufficient common history" in resp.json()["detail"]


async def test_route_rejects_missing_source_422() -> None:
    async with _route_client() as client:
        resp = await client.post("/correlation-regime", json={})
    # Pydantic request validation → 422.
    assert resp.status_code == 422
```

  Monkeypatch note: the route calls `cr_service.run_correlation_regime(...)` by attribute at request time (it imports the MODULE `from app.services import correlation_regime as cr_service`), so `monkeypatch.setattr(cr_service, "run_correlation_regime", fake_run)` is picked up. Tests need no asyncio marker (`asyncio_mode = "auto"`, verified in pyproject.toml).

- [ ] **Step 2: Run it, expect FAIL.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_route.py -k "route" -v`
  - Expected failure: the POST returns 404 (route not registered in `create_app` yet), so the 200/422 status assertions fail. (The schema/service modules already exist from T3F-6/T3F-5, so the test file imports resolve; the failure is purely the missing route.)

- [ ] **Step 3: Write the minimal implementation.**

  (a) Create `backend/app/api/routes/correlation_regime.py`:

```python
"""Correlation-regime / contagion endpoint (T3F): POST /correlation-regime.

Thin route over ``app.services.correlation_regime``: resolve the request asset
refs (explicit list OR universe spec, reusing the builder's fund selection),
run the service over the optimizer's aligned (T,N) matrix, and map any domain
ValueError (insufficient history, unknown asset, NaN) to HTTP 422.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.optimizer import data as optimizer_data
from app.schemas.builder import EquityRefIn, FundRefIn
from app.schemas.correlation_regime import CorrelationRegimeOut, CorrelationRegimeRequest
from app.services import correlation_regime as cr_service
from app.services import portfolio_builder

router = APIRouter(tags=["correlation-regime"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]


def _to_data_ref(ref: FundRefIn | EquityRefIn) -> optimizer_data.AssetRef:
    if isinstance(ref, FundRefIn):
        return optimizer_data.FundAssetRef(id=ref.id)
    return optimizer_data.EquityAssetRef(ticker=ref.ticker.upper())


@router.post("/correlation-regime", response_model=CorrelationRegimeOut)
async def correlation_regime(
    payload: CorrelationRegimeRequest, session: SessionDep
) -> CorrelationRegimeOut:
    """Correlation-regime + contagion analysis over an explicit asset list or a
    resolved fund universe. Decimal-fraction scale. Domain failures → 422.
    """
    try:
        if payload.assets is not None:
            refs = [_to_data_ref(ref) for ref in payload.assets]
        else:
            assert payload.universe is not None  # validator guarantees one
            spec = payload.universe
            candidates = await optimizer_data.select_universe_funds(
                session,
                portfolio_builder._filters_from_spec(spec),
                rank_by=spec.rank_by,
                rank_dir=spec.rank_dir,
                max_assets=spec.max_assets,
                require_aum=False,
                include_ids=spec.include_instrument_ids,
                window_days=payload.window_days,
            )
            if len(candidates) < 2:
                raise ValueError(
                    f"universe selection matched {len(candidates)} fund(s) — relax the "
                    "filters or widen the window (at least 2 are required)"
                )
            refs = [optimizer_data.FundAssetRef(id=c.id) for c in candidates]
        return await cr_service.run_correlation_regime(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

  (b) In `backend/app/main.py`, add the import immediately after line 10 (`from app.api.routes import macro as macro_router`):

```python
from app.api.routes import correlation_regime as correlation_regime_router
```

  and register it immediately after line 59 (`application.include_router(macro_router.router)`):

```python
    application.include_router(correlation_regime_router.router)
```

- [ ] **Step 4: Run tests, expect PASS.**
  - Command: `cd backend && python -m pytest tests/test_correlation_regime_route.py -v`
  - Expected: all schema + route tests pass (200 payload echo with refs translated to `equity:SPY`/`equity:QQQ`; 422 on the service ValueError with the message in `detail`; 422 on the missing-source Pydantic validation).

- [ ] **Step 5: Commit.**
  - `git add backend/app/api/routes/correlation_regime.py backend/app/main.py backend/tests/test_correlation_regime_route.py`
  - Message:
    ```
    feat(api): POST /correlation-regime route (thin) over the correlation-regime service

    Resolves explicit assets OR a fund universe (reusing the builder's
    selection helpers), runs the regime/contagion assembler over the
    optimizer's aligned matrix, maps domain ValueError → 422. Registered in
    create_app after the macro router.

    Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
    ```

---

### Task T3F-8: Full-cluster regression gate (no breakage across optimizer/services/routes)

**Files:**
- Test: (no new file) — run the affected suites together.

A final guard that the new SCS ladder / re-verification did not regress existing optimizer gates and that the new modules import cleanly under the full app.

- [ ] **Step 1: Run the optimizer + new T3F suites together.**
  - Command: `cd backend && python -m pytest tests/test_optimizer_engine.py tests/test_optimizer_black_litterman.py tests/test_analytics_rmt.py tests/test_correlation_regime_service.py tests/test_correlation_regime_route.py -v`
  - Expected: all pass, including the pre-existing G2/G4/G5 gates. In particular `test_g5_structural_no_mean_estimation_in_engine_or_data` must stay green: `engine.py`/`data.py` contain no `.mean(`/`np.average`, and `black_litterman.py` contains EXACTLY one `.mean(` (the unchanged `historical_mean_ann` at L223).

- [ ] **Step 2: Run the builder route + schema suites (consumers of the engine `_finalize` change).**
  - Command: `cd backend && python -m pytest tests/test_builder_route.py tests/test_builder_schema.py -v`
  - Expected: all pass — `_finalize`'s 2-tuple back-compat path keeps `portfolio_builder.run_optimize` working unchanged (it calls `engine.solve_min_vol`/`solve_min_cvar`/`solve_bl_utility`, none of which change their return shape).

- [ ] **Step 3: Commit (only if an incidental fix was needed; otherwise skip).**
  - If a consumer needed a touch-up, `git add` the exact file(s) and commit with message `test(optimizer): green full T3F + optimizer/builder regression gate`. If everything was already green, no commit — this task is a verification gate.

---

## Tier 3 — Remaining/advanced: regime-adjusted CVaR limit, CVaR annualization+verifier, PSD eigen-repair, CVaR breach governance, BL Woodbury/full-Ω, TAA regime bands (LARGE), fundamental factor track (LARGE)

This cluster ports five SMALL, self-contained quant primitives from the legacy `quant_engine` into the light app (ranks 37, 39, 40, 41, 43) as pure, unit-tested functions, plus two LARGE spike/decision tasks (ranks 45, 46) that require new ingestion/data-model substrate before any TDD code can be written.

**Read before starting** (real source, line numbers re-verified against the files in this pass):
- LEGACY `E:/investintell-allocation/backend/quant_engine/cvar_service.py` — `get_cvar_utilization` (lines 409-424), `classify_trigger_status` (lines 427-443), `check_breach_status` (lines 446-505, the consecutive-day counter is lines 487-490), `ProfileCVaRConfig`/`_DEFAULT_CVAR_CONFIG` (lines 29-62), `_BREACH_EPSILON = 1e-6` (line 67), `compute_regime_cvar_audited` (lines 268-354, the regime-conditional CVaR concept behind rank 37's multiplier).
- LEGACY `quant_engine/rebalance_service.py` — `determine_cascade_action` (lines 76-157; NOTE its real signature is 6-arg and formats utilization into reason strings — T3G-4 ports a profile-free 2-arg simplification, see open_questions), `VALID_TRANSITIONS`/`validate_status_transition` (lines 35-45, 160-163), cascade event-type docstring (lines 10-13).
- LEGACY `quant_engine/black_litterman_service.py` — `View` dataclass with full `Omega` (lines 59-77), `compute_bl_posterior_multi_view` Woodbury data-update form (the solve is lines 239-253), per-entry Ω diagonal floor (lines 218-237), `REG_OMEGA_EPS_FACTOR = 1e-8` (line 56).
- LEGACY `quant_engine/factor_model_service.py` — `assemble_factor_covariance` (lines 679-725); the standalone eigenvalue-floor PSD repair is lines 706-723 (floor = `max(1e-10, max_eigval / kappa_target)`, default `kappa_target = 1e4`).
- LEGACY `quant_engine/taa_band_service.py` — `compute_effective_band` (lines 80-114), `smooth_regime_centers` (lines 122-157, EMA halflife=5 + max_daily_shift=0.03 cap), `_disaggregate_centers_to_blocks` (line 165) — the LARGE TAA reference.
- LIGHT `backend/app/optimizer/engine.py` — `OptimizerError` (line 31), `_check_constraint_params` (58-77), `base_constraints` (80-89), `_finalize` (92-112), `_validate_sigma` (115-121, square+finite check + symmetrization), `solve_min_cvar` (237-282; the RU `cvar` expression is line 274, `cons = base_constraints(...)` is line 275, `problem = cp.Problem(cp.Minimize(cvar), cons)` is line 281), module constants `DEFAULT_CAP`/`DEFAULT_CVAR_ALPHA`/`_WEIGHT_ATOL` (lines 25-28).
- LIGHT `backend/app/optimizer/black_litterman.py` — `posterior` (174-210, inverts τΣ directly via `np.linalg.inv`), `omega_idzorek` (135-171), `equilibrium` (84-97), `build_view_matrices` (100-132), `AbsoluteView`/`RelativeView`/`View` (39-58), `DEFAULT_TAU = 0.05` (line 32), `_FULL_CONFIDENCE_EPS = 1e-6` (line 36); `_validate_sigma` is imported from engine at lines 22-29.
- LIGHT `backend/app/analytics/risk.py` — `historical_cvar` (88-114, POSITIVE loss-magnitude convention), `historical_var` (64-85), `annualized_volatility` (45-61, √252 convention); `math` (line 10), `dataclass` (line 11), `pd` (line 15), `reject_nan` (line 17), `_MIN_TAIL_POINTS = 10` (line 20) are already imported/defined.
- LIGHT `backend/app/models/rebalance.py` — `RebalancePolicy` (26-74); the sqlalchemy import block is lines 11-19 (Boolean, CheckConstraint, DateTime, Float, ForeignKey, String, func — `Integer` is NOT yet imported), `last_evaluated_at` ends at line 56, `created_at` starts at line 58.
- LIGHT `backend/alembic/versions/` — head revision is **0012** (`0012_fund_risk_class_metrics.py`, `revision: str = "0012"`, `down_revision: str | None = "0011"`). Convention: numbered filename `NNNN_descriptive.py`, typed module-level `revision`/`down_revision` strings, `import sqlalchemy as sa` + `from alembic import op`. The new migration is therefore `0013_rebalance_breach_governance.py` with `revision = "0013"`, `down_revision = "0012"` — NO `alembic heads` lookup needed (head is known).
- LIGHT `backend/app/optimizer/__init__.py` — docstring only, NO `__all__`/exports; a module-level `import` of a new function is sufficient, no `__init__` change required.

**Dependency order:** T3G-3 (PSD repair, no prereqs) → T3G-2 (CVaR annualization+verifier, pure analytics) → T3G-1 (regime-adjusted CVaR limit — see T2C blocker in open_questions) → T3G-4 (breach governance FSM + migration) → T3G-5 (BL Woodbury/full-Ω) → T3G-6 (TAA spike) → T3G-7 (factor spike). T3G-1 and T3G-4 carry product/data-model blockers recorded in open_questions; the pure code in each is safe to land independently of the blocked wiring.

**Conventions used everywhere below** (verified against the light repo): tests are FLAT files in `backend/tests/` (e.g. `test_optimizer_engine.py`, `test_analytics_risk.py`, `test_rebalance.py`, `test_models.py` — confirmed by `ls`), not subfolders; pure analytics raise `ValueError` on bad/insufficient data and never return NaN; the optimizer raises `OptimizerError` (a `ValueError` subclass, engine.py:31); fractional quantities are decimal fractions; CVaR sign convention DIFFERS by module — in `app.analytics.risk` it is POSITIVE = loss magnitude (`historical_cvar` returns +0.03 for a 3% shortfall) while the legacy `cvar_service`/governance FSM uses RETURN-SPACE (NEGATIVE = loss, `cvar_limit = -0.08`). T3G-2 uses the POSITIVE analytics convention; T3G-4 uses the NEGATIVE return-space convention (matching the legacy it ports). Gate G5: no objective consumes a sample mean; the regime multiplier in T3G-1 is supplied by the caller, never estimated.

---

### Task T3G-3: PSD eigenvalue-floor repair (rank 40)

Port the legacy `assemble_factor_covariance` eigenvalue-floor logic (factor_model_service.py:706-723) into a standalone, reusable covariance-repair helper in the optimizer engine. No factor model needed — it is a pure matrix routine any Σ producer (BL posterior, sample covariance, future factor Σ) can call to guarantee a PSD, well-conditioned matrix before it reaches cvxpy. This is the leaf dependency; do it first.

**Files:**
- Modify: `backend/app/optimizer/engine.py` (add `repair_psd` immediately after `_validate_sigma`, which ends at line 121)
- Test: `backend/tests/test_optimizer_psd_repair.py` (Create)

- [ ] **Step 1: Write the failing test.**
```python
"""PSD eigenvalue-floor repair (rank 40) — ported from legacy
assemble_factor_covariance conditioning (factor_model_service.py:706-723)."""

import numpy as np
import pytest

from app.optimizer import engine


def _symmetrize(m: np.ndarray) -> np.ndarray:
    return (m + m.T) / 2.0


def test_repair_psd_floors_negative_eigenvalues() -> None:
    # Construct a symmetric matrix with one negative eigenvalue.
    q, _ = np.linalg.qr(np.random.default_rng(0).standard_normal((3, 3)))
    sigma = q @ np.diag([1.0, 0.5, -0.2]) @ q.T
    sigma = _symmetrize(sigma)
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    eigvals = np.linalg.eigvalsh(repaired)
    # All eigenvalues are now >= 0 (floored at max_eigval / kappa_target).
    assert eigvals.min() >= 0.0
    assert np.allclose(repaired, repaired.T, atol=1e-12)


def test_repair_psd_enforces_conditioning_band() -> None:
    # Pathological conditioning: kappa = 1e8, far above target 1e4.
    sigma = np.diag([1.0, 1e-8, 1e-8])
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    eigvals = np.linalg.eigvalsh(repaired)
    kappa = float(eigvals.max() / eigvals.min())
    assert kappa <= 1e4 + 1.0  # floored to max_eigval / kappa_target


def test_repair_psd_leaves_well_conditioned_matrix_unchanged() -> None:
    sigma = np.diag([0.04, 0.03, 0.05])
    repaired = engine.repair_psd(sigma, kappa_target=1e4)
    np.testing.assert_allclose(repaired, sigma, atol=1e-12)


def test_repair_psd_rejects_non_square() -> None:
    with pytest.raises(engine.OptimizerError, match="square"):
        engine.repair_psd(np.zeros((2, 3)))


def test_repair_psd_rejects_nan() -> None:
    sigma = np.array([[1.0, np.nan], [np.nan, 1.0]])
    with pytest.raises(engine.OptimizerError, match="NaN/inf"):
        engine.repair_psd(sigma)


def test_repair_psd_invalid_kappa_target() -> None:
    with pytest.raises(engine.OptimizerError, match="kappa_target"):
        engine.repair_psd(np.diag([1.0, 1.0]), kappa_target=0.5)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_optimizer_psd_repair.py -v`
  Expected failure: `AttributeError: module 'app.optimizer.engine' has no attribute 'repair_psd'`.

- [ ] **Step 3: Write the minimal implementation.** Add to `backend/app/optimizer/engine.py` immediately after `_validate_sigma` (after line 121):
```python
def repair_psd(sigma: np.ndarray, kappa_target: float = 1e4) -> np.ndarray:
    """Symmetrize Σ and floor its eigenvalues to enforce PSD + conditioning.

    Ported from the legacy factor covariance assembler
    (quant_engine/factor_model_service.py:706-723). The eigenvalue floor is
    ``max(1e-10, max_eigval / kappa_target)``: any eigenvalue below it (including
    negatives from numerical drift or shrinkage) is clamped up, bounding the
    condition number κ = λ_max/λ_min at ``kappa_target``. A matrix already inside
    the band is returned unchanged (up to symmetrization).

    Raises:
        OptimizerError: if ``sigma`` is non-square, contains NaN/inf, or
            ``kappa_target`` is not > 1.
    """
    sigma = _validate_sigma(sigma, "repair_psd")  # square + finite + symmetrize
    if not kappa_target > 1.0:
        raise OptimizerError(f"kappa_target must be > 1, got {kappa_target}")
    eigvals, eigvecs = np.linalg.eigh(sigma)
    max_eigval = float(eigvals.max())
    clamp_val = max(1e-10, max_eigval / kappa_target)
    if eigvals.min() < clamp_val:
        eigvals = np.maximum(eigvals, clamp_val)
        sigma = eigvecs @ np.diag(eigvals) @ eigvecs.T
        sigma = (sigma + sigma.T) / 2.0
    return np.asarray(sigma, dtype=float)
```
  Note: `_validate_sigma` (engine.py:115-121) already raises `OptimizerError` with `"sigma must be square"` on non-square (line 118) and `"sigma contains NaN/inf"` on non-finite (line 120), and symmetrizes (line 121) — so the `"square"` / `"NaN/inf"` test messages are satisfied by re-using it.

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_optimizer_psd_repair.py -v`
  Expected: 6 passed.

- [ ] **Step 5: Commit.**
  `cd backend && git add app/optimizer/engine.py tests/test_optimizer_psd_repair.py`
  Commit message: `feat(optimizer): PSD eigenvalue-floor repair helper (rank 40, ported from legacy factor cov)`

---

### Task T3G-2: CVaR annualization + realized-CVaR verifier (rank 39)

Add two pure analytics helpers to `app/analytics/risk.py`: (1) `annualize_cvar` — scale a per-period CVaR to an annual horizon under the √h convention, matching the existing `annualized_volatility` √252 convention (risk.py:45-61); (2) `verify_realized_cvar` — an out-of-sample verifier that recomputes realized CVaR (via the existing `historical_cvar`) on a held-out return window and reports the breach ratio versus a stated limit. Pure functions on pandas Series, fail-loud on NaN/insufficient data. No DB, no optimizer dependency. The realized estimator is the analytics `historical_cvar`, NOT the optimizer's in-LP RU expression (see open_questions for the audit-semantics note).

**Files:**
- Modify: `backend/app/analytics/risk.py` (append after `historical_cvar`, which ends at line 114; re-uses `dataclass` line 11, `math` line 10, `pd` line 15, `historical_cvar` line 88 — all already imported/defined)
- Test: `backend/tests/test_analytics_cvar_annualization.py` (Create)

- [ ] **Step 1: Write the failing test.**
```python
"""CVaR annualization + realized-CVaR verifier (rank 39)."""

import math

import numpy as np
import pandas as pd
import pytest

from app.analytics import risk


def _series(values: list[float]) -> pd.Series:
    idx = pd.date_range("2020-01-01", periods=len(values), freq="B")
    return pd.Series(values, index=idx, dtype=float)


def test_annualize_cvar_sqrt_time_scaling() -> None:
    # Square-root-of-time: annual = periodic * sqrt(periods_per_year).
    periodic_cvar = 0.02
    annual = risk.annualize_cvar(periodic_cvar, periods_per_year=252)
    assert math.isclose(annual, 0.02 * math.sqrt(252), rel_tol=1e-12)


def test_annualize_cvar_monthly() -> None:
    annual = risk.annualize_cvar(0.05, periods_per_year=12)
    assert math.isclose(annual, 0.05 * math.sqrt(12), rel_tol=1e-12)


def test_annualize_cvar_rejects_negative_input() -> None:
    # CVaR in this module is a POSITIVE loss magnitude (risk.historical_cvar).
    with pytest.raises(ValueError, match="positive"):
        risk.annualize_cvar(-0.02)


def test_annualize_cvar_rejects_bad_periods() -> None:
    with pytest.raises(ValueError, match="periods_per_year"):
        risk.annualize_cvar(0.02, periods_per_year=0)


def test_verify_realized_cvar_within_limit() -> None:
    # Mild returns: realized CVaR well below a generous 10% limit.
    rng = np.random.default_rng(7)
    returns = _series(list(rng.normal(0.0, 0.01, 300)))
    result = risk.verify_realized_cvar(returns, cvar_limit=0.10, confidence=0.95)
    assert result.realized_cvar > 0.0
    assert result.realized_cvar < 0.10
    assert result.breach is False
    assert 0.0 <= result.utilization < 1.0


def test_verify_realized_cvar_breach() -> None:
    # Fat left tail forces realized CVaR above a tight 1% limit.
    base = [0.001] * 290
    crash = [-0.20] * 10
    returns = _series(base + crash)
    result = risk.verify_realized_cvar(returns, cvar_limit=0.01, confidence=0.95)
    assert result.realized_cvar > 0.01
    assert result.breach is True
    assert result.utilization > 1.0


def test_verify_realized_cvar_rejects_nonpositive_limit() -> None:
    returns = _series([0.001] * 50)
    with pytest.raises(ValueError, match="cvar_limit"):
        risk.verify_realized_cvar(returns, cvar_limit=0.0)


def test_verify_realized_cvar_rejects_short_window() -> None:
    returns = _series([0.001] * 5)
    with pytest.raises(ValueError, match="at least 10"):
        risk.verify_realized_cvar(returns, cvar_limit=0.05)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_analytics_cvar_annualization.py -v`
  Expected failure: `AttributeError: module 'app.analytics.risk' has no attribute 'annualize_cvar'`.

- [ ] **Step 3: Write the minimal implementation.** Append to `backend/app/analytics/risk.py` after `historical_cvar` (after line 114):
```python
@dataclass(frozen=True)
class RealizedCVaRCheck:
    """Out-of-sample realized-CVaR verification against a stated limit.

    ``realized_cvar`` and ``cvar_limit`` are POSITIVE decimal-fraction loss
    magnitudes (same convention as :func:`historical_cvar`). ``utilization`` is
    realized_cvar / cvar_limit; ``breach`` is True when utilization > 1.
    """

    realized_cvar: float
    cvar_limit: float
    utilization: float
    breach: bool
    confidence: float
    n_obs: int


def annualize_cvar(cvar_periodic: float, periods_per_year: int = 252) -> float:
    """Scale a per-period CVaR to an annual horizon via square-root-of-time.

    Matches the √(periods_per_year) convention of :func:`annualized_volatility`
    (CVaR of an i.i.d. sum scales like the standard deviation under the
    Gaussian/√h approximation). ``cvar_periodic`` is a POSITIVE loss magnitude
    (decimal fraction); the annualized result is likewise positive.

    Raises:
        ValueError: if ``cvar_periodic`` is negative (wrong sign convention) or
            ``periods_per_year`` is not a positive integer.
    """
    if cvar_periodic < 0:
        raise ValueError(
            f"cvar_periodic must be a positive loss magnitude (decimal fraction), "
            f"got {cvar_periodic}"
        )
    if periods_per_year <= 0:
        raise ValueError(f"periods_per_year must be positive, got {periods_per_year}")
    return cvar_periodic * math.sqrt(periods_per_year)


def verify_realized_cvar(
    returns: pd.Series,
    cvar_limit: float,
    confidence: float = 0.95,
) -> RealizedCVaRCheck:
    """Recompute realized CVaR on a held-out window and compare to a limit.

    The realized CVaR is computed by :func:`historical_cvar` (same estimator,
    same per-period horizon as ``cvar_limit``). ``utilization`` is the ratio to
    the limit; ``breach`` fires when realized CVaR exceeds the limit. Used to
    audit whether an ex-ante optimizer CVaR cap held out-of-sample.

    Raises:
        ValueError: if ``cvar_limit`` is not a positive decimal fraction, or any
            condition that :func:`historical_cvar` rejects (confidence not in
            (0,1), < 10 returns, empty tail, NaN input).
    """
    if cvar_limit <= 0:
        raise ValueError(
            f"cvar_limit must be a positive loss magnitude (decimal fraction), "
            f"got {cvar_limit}"
        )
    realized = historical_cvar(returns, confidence=confidence)
    utilization = realized / cvar_limit
    return RealizedCVaRCheck(
        realized_cvar=realized,
        cvar_limit=cvar_limit,
        utilization=utilization,
        breach=utilization > 1.0,
        confidence=confidence,
        n_obs=int(len(returns)),
    )
```
  Note: `dataclass` (risk.py:11), `math` (line 10), `pd` (line 15), and `historical_cvar` (line 88) are already imported/defined at the top of `risk.py`. The `"at least 10"` message in the short-window test comes from `historical_cvar`'s own guard (risk.py:103-105: `"historical_cvar requires at least 10 returns"`).

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_analytics_cvar_annualization.py tests/test_analytics_risk.py -v`
  Expected: 8 new passed; existing `test_analytics_risk.py` still green (additive functions, nothing changed).

- [ ] **Step 5: Commit.**
  `cd backend && git add app/analytics/risk.py tests/test_analytics_cvar_annualization.py`
  Commit message: `feat(analytics): CVaR √-time annualization + realized-CVaR verifier (rank 39)`

---

### Task T3G-1: Regime-adjusted CVaR limit (rank 37)

Add a pure helper `compute_regime_adjusted_limit(base_limit, regime_multiplier)` that tightens a base CVaR limit under stress regimes (multiplier < 1 tightens, > 1 loosens), then wire an OPTIONAL `cvar_limit` constraint into `solve_min_cvar` so the optimizer can reject portfolios whose ex-ante CVaR exceeds the (regime-adjusted) limit. The legacy reference is the regime-conditional CVaR in `cvar_service.compute_regime_cvar_audited` (lines 268-354) and the limit-utilization logic in `get_cvar_utilization` (lines 409-424). The multiplier is supplied by the caller from the regime detector — this function performs NO estimation (gate G5).

**PREREQUISITE (see open_questions):** rank 37 "depends on the T2C CVaR-limit path". CONFIRMED: the light `solve_min_cvar` (engine.py:237-244) has NO `cvar_limit` parameter today (grep of `backend/app/` for `cvar_limit|cvar_cap|cvar_constraint` returns zero matches). This task therefore ships BOTH the multiplier helper AND the minimal `cvar_limit` constraint addition. If T2C lands the `cvar_limit` parameter first, drop Step 3b and keep only the helper + a test asserting the helper feeds T2C's parameter.

**Files:**
- Modify: `backend/app/optimizer/engine.py` (add `compute_regime_adjusted_limit` after the module constants, after `_WEIGHT_ATOL = 1e-6` at line 28 and before `class OptimizerError` at line 31 — place it AFTER the class so `OptimizerError` is defined; see Step 3a; and extend `solve_min_cvar` signature + constraint, lines 237-282)
- Test: `backend/tests/test_optimizer_cvar_limit.py` (Create)

- [ ] **Step 1: Write the failing test.**
```python
"""Regime-adjusted CVaR limit (rank 37)."""

import numpy as np
import pytest

from app.optimizer import engine


def _scenarios(t: int = 600, n: int = 4, seed: int = 11) -> np.ndarray:
    rng = np.random.default_rng(seed)
    cov = np.diag([0.01, 0.012, 0.02, 0.03]) ** 2
    return rng.multivariate_normal(np.zeros(n), cov[:n, :n], size=t)


def test_regime_multiplier_tightens_limit_in_stress() -> None:
    # base limit 0.10 (10% loss); stress multiplier 0.5 tightens to 0.05.
    adjusted = engine.compute_regime_adjusted_limit(0.10, 0.5)
    assert adjusted == pytest.approx(0.05)


def test_regime_multiplier_loosens_limit_in_calm() -> None:
    adjusted = engine.compute_regime_adjusted_limit(0.10, 1.5)
    assert adjusted == pytest.approx(0.15)


def test_regime_multiplier_rejects_nonpositive_base() -> None:
    with pytest.raises(engine.OptimizerError, match="base_limit"):
        engine.compute_regime_adjusted_limit(0.0, 1.0)


def test_regime_multiplier_rejects_nonpositive_multiplier() -> None:
    with pytest.raises(engine.OptimizerError, match="regime_multiplier"):
        engine.compute_regime_adjusted_limit(0.10, 0.0)


def test_min_cvar_with_generous_limit_is_feasible() -> None:
    scenarios = _scenarios()
    weights, status = engine.solve_min_cvar(scenarios, cvar_limit=0.50)
    assert status == "optimal"
    assert abs(float(weights.sum()) - 1.0) < 1e-6


def test_min_cvar_with_impossible_limit_fails_loud() -> None:
    # An absurdly tight CVaR limit (0.0001) is infeasible -> OptimizerError.
    scenarios = _scenarios()
    with pytest.raises(engine.OptimizerError):
        engine.solve_min_cvar(scenarios, cvar_limit=0.0001)


def test_min_cvar_rejects_nonpositive_cvar_limit() -> None:
    scenarios = _scenarios()
    with pytest.raises(engine.OptimizerError, match="cvar_limit"):
        engine.solve_min_cvar(scenarios, cvar_limit=0.0)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_optimizer_cvar_limit.py -v`
  Expected failure: `AttributeError: module 'app.optimizer.engine' has no attribute 'compute_regime_adjusted_limit'` (and `solve_min_cvar` has no `cvar_limit` kwarg → `TypeError`).

- [ ] **Step 3a: Add the multiplier helper.** Insert in `backend/app/optimizer/engine.py` immediately AFTER the `OptimizerError` class definition (after line 32, `"""Solver failed / problem infeasible / invalid inputs. Mapped to 422."""`), so `OptimizerError` is already defined:
```python
def compute_regime_adjusted_limit(base_limit: float, regime_multiplier: float) -> float:
    """Scale a base CVaR loss limit by a regime multiplier.

    ``base_limit`` is a POSITIVE loss magnitude (decimal fraction). A
    ``regime_multiplier`` < 1 tightens the limit under stress (legacy intent:
    in a detected stress regime the institutional CVaR budget shrinks); > 1
    loosens it in calm regimes. The multiplier is supplied by the caller from
    the regime detector — this function performs no estimation (gate G5).

    Raises:
        OptimizerError: if ``base_limit`` or ``regime_multiplier`` is not > 0.
    """
    if not base_limit > 0:
        raise OptimizerError(
            f"base_limit must be > 0 (loss magnitude), got {base_limit}"
        )
    if not regime_multiplier > 0:
        raise OptimizerError(
            f"regime_multiplier must be > 0, got {regime_multiplier}"
        )
    return base_limit * regime_multiplier
```

- [ ] **Step 3b: Wire the optional `cvar_limit` constraint into `solve_min_cvar`.** In `backend/app/optimizer/engine.py`, change the signature (lines 237-244) to add `cvar_limit: float | None = None`. Replace:
```python
def solve_min_cvar(
    scenarios: np.ndarray,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    ret_floor: float | None = None,
    mu: np.ndarray | None = None,
) -> tuple[np.ndarray, str]:
```
  with:
```python
def solve_min_cvar(
    scenarios: np.ndarray,
    alpha: float = DEFAULT_CVAR_ALPHA,
    cap: float | None = DEFAULT_CAP,
    min_weight: float | None = None,
    ret_floor: float | None = None,
    mu: np.ndarray | None = None,
    cvar_limit: float | None = None,
) -> tuple[np.ndarray, str]:
```
  Then, immediately BEFORE `problem = cp.Problem(cp.Minimize(cvar), cons)` (line 281), insert (the `cvar` RU expression already exists at line 274, `cons` at line 275):
```python
    if cvar_limit is not None:
        if not cvar_limit > 0:
            raise OptimizerError(
                f"min_cvar: cvar_limit must be > 0 (loss magnitude), got {cvar_limit}"
            )
        # cvar is the RU loss expression (return-space loss; positive = loss).
        # Cap it at the regime-adjusted limit; infeasibility -> solver status
        # not optimal -> _finalize raises OptimizerError (fail-loud).
        cons.append(cvar <= cvar_limit)
```
  Also append one line to the `solve_min_cvar` docstring (after line 252, before the closing `"""` at line 253): ``The optional ``cvar_limit`` (positive loss magnitude) adds the hard constraint CVaR_α(w) ≤ cvar_limit; infeasibility fails loud via the solver status (gate G5: no mean involved).``

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_optimizer_cvar_limit.py tests/test_optimizer_engine.py -v`
  Expected: 7 new passed; the existing `test_optimizer_engine.py` min-CVaR tests (`test_g2_min_cvar_optimal_sum_and_caps` line 80, `test_g5_min_cvar_floor_requires_explicit_mu` line 148) still green — default `cvar_limit=None` is a no-op.

- [ ] **Step 5: Commit.**
  `cd backend && git add app/optimizer/engine.py tests/test_optimizer_cvar_limit.py`
  Commit message: `feat(optimizer): regime-adjusted CVaR limit + optional min-CVaR cap constraint (rank 37)`

---

### Task T3G-4: CVaR breach governance FSM + persistence (rank 41)

Port the legacy breach state machine — `get_cvar_utilization` (cvar_service.py:409-424), `classify_trigger_status` (427-443), the consecutive-day counter inside `check_breach_status` (446-505), and `determine_cascade_action` (rebalance_service.py:76-157) — into a PURE governance module `app/rebalance/governance.py` (no I/O), plus an additive migration adding `consecutive_breach_days` and `last_trigger_status` to `rebalance_policies` so the FSM can persist across evaluations.

**BLOCKERS (see open_questions):** the light app has no per-profile CVaR config and no profile concept. The legacy `determine_cascade_action` is 6-arg and formats utilization/thresholds into reason strings from a profile config; T3G-4 ports a SIMPLIFIED profile-free 2-arg `determine_cascade_action(trigger_status, previous_trigger_status)` with STATIC reason strings (no config to format). The product owner must decide the limit/warning/breach_days values and whether the FSM persists on the advisory preview path. The PURE FSM + the additive migration in this task are safe to land regardless and do NOT wire into the evaluator yet. Sign convention here is RETURN-SPACE (NEGATIVE = loss, `cvar_limit = -0.08`), matching the legacy `cvar_service` it ports — distinct from the POSITIVE convention in `app.analytics.risk`.

**Files:**
- Create: `backend/app/rebalance/governance.py` (the `app/rebalance/` package exists — confirmed: it holds `__init__.py` and `evaluator.py`)
- Modify: `backend/app/models/rebalance.py` (add two columns to `RebalancePolicy` after `last_evaluated_at` at line 56, before `created_at` at line 58; add `Integer` to the sqlalchemy import block at lines 11-19)
- Create: `backend/alembic/versions/0013_rebalance_breach_governance.py` (head is `0012` — confirmed; `down_revision = "0012"`)
- Test: `backend/tests/test_rebalance_governance.py` (Create)

- [ ] **Step 1: Write the failing test.**
```python
"""CVaR breach governance FSM (rank 41) — pure, no I/O.

Ports cvar_service.get_cvar_utilization / classify_trigger_status / the
check_breach_status consecutive-day counter and rebalance_service.
determine_cascade_action (profile-free 2-arg simplification) into the light app.
Sign convention: return-space, losses are NEGATIVE (cvar_limit = -0.08)."""

import math

import pytest

from app.rebalance import governance as gov


# -- utilization --------------------------------------------------------------


def test_utilization_loss_case_positive() -> None:
    # current -0.06, limit -0.08 -> 75% utilized.
    util = gov.cvar_utilization(cvar_current=-0.06, cvar_limit=-0.08)
    assert util == pytest.approx(75.0)


def test_utilization_gain_clamped_to_zero() -> None:
    util = gov.cvar_utilization(cvar_current=0.01, cvar_limit=-0.08)
    assert util == 0.0


def test_utilization_rejects_nonnegative_limit() -> None:
    with pytest.raises(ValueError, match="cvar_limit must be negative"):
        gov.cvar_utilization(cvar_current=-0.05, cvar_limit=0.0)


# -- classification -----------------------------------------------------------


def test_classify_ok_below_warning() -> None:
    assert gov.classify_trigger_status(50.0, 0) == "ok"


def test_classify_warning_at_threshold() -> None:
    assert gov.classify_trigger_status(80.0, 0, warning_threshold_pct=80.0) == "warning"


def test_classify_breach_requires_consecutive_days() -> None:
    # over 100% but not enough consecutive days -> warning, not breach.
    assert gov.classify_trigger_status(120.0, 2, breach_consecutive_days=5) == "warning"
    assert gov.classify_trigger_status(120.0, 5, breach_consecutive_days=5) == "breach"


def test_classify_boundary_epsilon_no_false_breach() -> None:
    # exactly 100% utilization must NOT breach (epsilon tolerance).
    assert gov.classify_trigger_status(100.0, 10, breach_consecutive_days=5) == "warning"


# -- breach step (consecutive-day counter) ------------------------------------


def test_breach_step_increments_counter_over_limit() -> None:
    result = gov.step_breach(
        cvar_current=-0.09,
        cvar_limit=-0.08,
        prior_consecutive_days=2,
        warning_threshold_pct=80.0,
        breach_consecutive_days=3,
    )
    assert result.consecutive_breach_days == 3
    assert result.trigger_status == "breach"
    assert result.utilization > 100.0


def test_breach_step_resets_counter_when_compliant() -> None:
    result = gov.step_breach(
        cvar_current=-0.04,
        cvar_limit=-0.08,
        prior_consecutive_days=4,
        warning_threshold_pct=80.0,
        breach_consecutive_days=3,
    )
    assert result.consecutive_breach_days == 0
    assert result.trigger_status == "ok"


def test_breach_step_degraded_on_nan() -> None:
    result = gov.step_breach(
        cvar_current=math.nan,
        cvar_limit=-0.08,
        prior_consecutive_days=1,
        warning_threshold_pct=80.0,
        breach_consecutive_days=3,
    )
    assert result.trigger_status == "degraded"
    assert result.consecutive_breach_days == 0
    assert math.isnan(result.utilization)


# -- cascade action (transition events) ---------------------------------------


def test_cascade_escalation_ok_to_warning() -> None:
    event, reason = gov.determine_cascade_action("warning", "ok")
    assert event == "cvar_breach"
    assert "warning" in reason.lower() or "utilization" in reason.lower()


def test_cascade_recovery_breach_to_ok() -> None:
    event, reason = gov.determine_cascade_action("ok", "breach")
    assert event == "cvar_recovery"


def test_cascade_degraded_event() -> None:
    event, reason = gov.determine_cascade_action("degraded", "ok")
    assert event == "cvar_degraded"


def test_cascade_no_action_steady_ok() -> None:
    event, reason = gov.determine_cascade_action("ok", "ok")
    assert event is None and reason is None


def test_cascade_no_action_steady_breach() -> None:
    # already in breach last period -> no new escalation event.
    event, reason = gov.determine_cascade_action("breach", "breach")
    assert event is None and reason is None
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_rebalance_governance.py -v`
  Expected failure: `ModuleNotFoundError: No module named 'app.rebalance.governance'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/rebalance/governance.py`:
```python
"""CVaR breach governance FSM (rank 41) — pure, no I/O.

Ported from the legacy quant_engine breach state machine:
  * cvar_service.get_cvar_utilization          -> cvar_utilization
  * cvar_service.classify_trigger_status       -> classify_trigger_status
  * cvar_service.check_breach_status (counter) -> step_breach
  * rebalance_service.determine_cascade_action -> determine_cascade_action
    (profile-free 2-arg simplification — the legacy 6-arg version formats a
    per-profile config into its reason strings; the light app has no profile
    taxonomy, so the reasons here are static. See cluster open_questions.)

Sign convention (matches legacy cvar_service): cvar_current and cvar_limit are
RETURN-SPACE values — losses are NEGATIVE (cvar_limit = -0.08 means an 8% loss
limit). Utilization is a positive percentage (0-100+). This DIFFERS from the
POSITIVE loss-magnitude convention in app.analytics.risk.

This module is I/O-free. Persistence of consecutive_breach_days /
last_trigger_status across evaluations lives on RebalancePolicy
(app/models/rebalance.py); the caller pre-fetches and re-stamps them.
"""

import math
from dataclasses import dataclass

# Floating-point tolerance for the 100% breach boundary (legacy _BREACH_EPSILON,
# cvar_service.py:67).
_BREACH_EPSILON = 1e-6


@dataclass(frozen=True)
class BreachStep:
    """Result of one breach-FSM evaluation step."""

    trigger_status: str  # ok | warning | breach | degraded
    utilization: float   # positive percentage; NaN when degraded
    consecutive_breach_days: int


def cvar_utilization(cvar_current: float, cvar_limit: float) -> float:
    """CVaR utilization as a percentage of the limit (legacy get_cvar_utilization).

    Both inputs are return-space (negative = loss). Returns a positive
    percentage, clamped to 0 for gains.

    Raises:
        ValueError: if ``cvar_limit`` is not negative (return-space loss limit).
    """
    if cvar_limit >= 0:
        raise ValueError(
            f"cvar_limit must be negative (return-space loss limit), got {cvar_limit}"
        )
    ratio = cvar_current / cvar_limit
    return max(0.0, ratio * 100.0)


def classify_trigger_status(
    utilization_pct: float,
    consecutive_days: int,
    warning_threshold_pct: float = 80.0,
    breach_consecutive_days: int = 5,
) -> str:
    """Classify CVaR trigger status (legacy classify_trigger_status).

    Returns 'ok', 'warning', or 'breach'. The epsilon tolerance prevents a
    false breach at exactly 100% utilization from floating-point drift.
    """
    if (
        utilization_pct >= (100.0 + _BREACH_EPSILON)
        and consecutive_days >= breach_consecutive_days
    ):
        return "breach"
    if utilization_pct >= warning_threshold_pct:
        return "warning"
    return "ok"


def step_breach(
    cvar_current: float,
    cvar_limit: float,
    prior_consecutive_days: int,
    warning_threshold_pct: float = 80.0,
    breach_consecutive_days: int = 5,
) -> BreachStep:
    """Advance the breach FSM one evaluation (legacy check_breach_status core).

    NaN ``cvar_current`` (insufficient/degraded data upstream) surfaces as a
    'degraded' status with a reset counter — never silently 'ok'.
    """
    if math.isnan(cvar_current):
        return BreachStep(
            trigger_status="degraded",
            utilization=float("nan"),
            consecutive_breach_days=0,
        )
    utilization = cvar_utilization(cvar_current, cvar_limit)
    if utilization >= (100.0 + _BREACH_EPSILON):
        new_consecutive = prior_consecutive_days + 1
    else:
        new_consecutive = 0
    trigger = classify_trigger_status(
        utilization,
        new_consecutive,
        warning_threshold_pct=warning_threshold_pct,
        breach_consecutive_days=breach_consecutive_days,
    )
    return BreachStep(
        trigger_status=trigger,
        utilization=utilization,
        consecutive_breach_days=new_consecutive,
    )


def determine_cascade_action(
    trigger_status: str,
    previous_trigger_status: str | None,
) -> tuple[str | None, str | None]:
    """Map a status transition to a cascade event (legacy determine_cascade_action).

    Profile-free 2-arg simplification. Returns (event_type, reason) or
    (None, None). Event types (legacy rebalance_service.py:10-13):
      * cvar_breach    — escalation (->warning from ok/None/degraded; ->breach)
      * cvar_recovery  — de-escalation (warning/breach/degraded -> ok)
      * cvar_degraded  — CVaR unavailable this period (risk-blind record)
    """
    if trigger_status == "degraded":
        return "cvar_degraded", (
            "CVaR unavailable — insufficient or invalid data; "
            "cascade evaluation skipped this period"
        )
    if trigger_status == "ok" and previous_trigger_status in (
        "warning",
        "breach",
        "degraded",
    ):
        return "cvar_recovery", (
            f"CVaR returned to compliance from {previous_trigger_status}"
        )
    if trigger_status == "ok":
        return None, None
    if trigger_status == "warning" and previous_trigger_status in (
        None,
        "ok",
        "degraded",
    ):
        return "cvar_breach", "CVaR utilization crossed the warning threshold"
    if trigger_status == "breach" and previous_trigger_status != "breach":
        return "cvar_breach", "CVaR breach: consecutive days above limit"
    return None, None
```

- [ ] **Step 4a: Add persistence columns.** In `backend/app/models/rebalance.py`, first add `Integer` to the import block (lines 11-19). Replace:
```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    String,
    func,
)
```
  with:
```python
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    func,
)
```
  Then insert AFTER `last_evaluated_at` (after line 56, before `created_at` at line 58):
```python
    # CVaR breach FSM state, persisted across evaluations (rank 41). The
    # advisory preview does not stamp these; only the scheduled job does
    # (mirrors last_evaluated_at). last_trigger_status is one of
    # ok | warning | breach | degraded (NULL before first breach evaluation).
    consecutive_breach_days: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    last_trigger_status: Mapped[str | None] = mapped_column(String, nullable=True)
```

- [ ] **Step 4b: Migration.** Create `backend/alembic/versions/0013_rebalance_breach_governance.py` (head is `0012`, confirmed — follow the in-repo typed-identifier convention from `0012_fund_risk_class_metrics.py`):
```python
"""rebalance breach governance state (rank 41)

Revision ID: 0013
Revises: 0012

Additive: persist the CVaR breach FSM (app/rebalance/governance.py) across
evaluations. consecutive_breach_days defaults to 0; last_trigger_status is NULL
until the first breach evaluation. Server defaults keep existing rows valid.
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.add_column(
        "rebalance_policies",
        sa.Column(
            "consecutive_breach_days",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )
    op.add_column(
        "rebalance_policies",
        sa.Column("last_trigger_status", sa.String(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("rebalance_policies", "last_trigger_status")
    op.drop_column("rebalance_policies", "consecutive_breach_days")
```

- [ ] **Step 5: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_rebalance_governance.py tests/test_models.py tests/test_rebalance.py -v`
  Expected: 16 governance tests passed; existing model/rebalance tests still green (additive columns with server defaults do not break existing rows or the evaluator, which never reads them yet — `test_rebalance.py` exercises calendar/macro triggers only, e.g. `test_calendar_due_when_never_evaluated` line 39).

- [ ] **Step 6: Commit.**
  `cd backend && git add app/rebalance/governance.py app/models/rebalance.py alembic/versions/0013_rebalance_breach_governance.py tests/test_rebalance_governance.py`
  Commit message: `feat(rebalance): pure CVaR breach governance FSM + persistence columns (rank 41)`

---

### Task T3G-5: BL Woodbury / full-Ω multi-view posterior (rank 43)

Add a `posterior_woodbury` function to `app/optimizer/black_litterman.py` that solves the BL master formula in the Woodbury data-update form (ported from legacy `compute_bl_posterior_multi_view`, black_litterman_service.py:239-253), supporting FULL (non-diagonal) Ω and per-entry Ω regularization (legacy lines 218-237). The light `posterior` (black_litterman.py:174-210) inverts τΣ directly via `np.linalg.inv` (lines 203-207) and only takes the diagonal Ω from `omega_idzorek`; the Woodbury form never inverts τΣ (only the strictly-PD K×K view-space matrix), so a zero-variance asset transmits no information instead of blowing up, and correlated views are supported.

**Files:**
- Modify: `backend/app/optimizer/black_litterman.py` (add `_REG_OMEGA_EPS_FACTOR` constant + `posterior_woodbury` after `posterior`, which ends at line 210; re-uses `_validate_sigma` imported at lines 22-29, `DEFAULT_TAU` at line 32)
- (No `backend/app/optimizer/__init__.py` change — it has no `__all__`; a module-level import of the new function is sufficient. Confirmed by reading the file.)
- Test: `backend/tests/test_optimizer_bl_multiview.py` (Create)

- [ ] **Step 1: Write the failing test.**
```python
"""BL Woodbury / full-Ω multi-view posterior (rank 43)."""

import numpy as np
import pytest

from app.optimizer import black_litterman as bl


def _fixture_sigma() -> np.ndarray:
    vols = np.array([0.10, 0.15, 0.20])
    corr = np.array([[1.0, 0.3, 0.2], [0.3, 1.0, 0.25], [0.2, 0.25, 1.0]])
    return corr * np.outer(vols, vols)


_W_MKT = np.array([0.5, 0.3, 0.2])


def test_woodbury_matches_classic_posterior_diagonal_omega() -> None:
    # With a diagonal, well-conditioned Omega, Woodbury == classic inverse form.
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    views = [bl.AbsoluteView(asset=0, q=0.12, confidence=0.6)]
    p, q = bl.build_view_matrices(views, 3)
    omega = bl.omega_idzorek(p, sigma, [0.6])
    mu_classic, _ = bl.posterior(sigma, pi, p, q, omega)
    mu_wood = bl.posterior_woodbury(sigma, pi, p, q, omega)
    np.testing.assert_allclose(mu_classic, mu_wood, atol=1e-9)


def test_woodbury_supports_full_offdiagonal_omega() -> None:
    # Two correlated views with a non-diagonal Omega (off-diag != 0).
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
    q = np.array([0.12, 0.09])
    omega = np.array([[4e-4, 1e-4], [1e-4, 5e-4]])  # PSD, off-diagonal
    mu = bl.posterior_woodbury(sigma, pi, p, q, omega)
    assert mu.shape == (3,)
    assert np.all(np.isfinite(mu))
    # Bullish absolute view on asset 0 raises its posterior above equilibrium.
    assert mu[0] > pi[0]


def test_woodbury_zero_variance_asset_does_not_blow_up() -> None:
    # Asset 2 has zero variance (flat NAV) -> its row of tauSigma*P^T is zero;
    # the Woodbury form must still produce finite output (classic inv(tauSigma)
    # would be singular).
    sigma = _fixture_sigma()
    sigma[2, :] = 0.0
    sigma[:, 2] = 0.0
    sigma = (sigma + sigma.T) / 2.0
    pi = np.array([0.05, 0.06, 0.0])
    views = [bl.AbsoluteView(asset=0, q=0.12, confidence=0.6)]
    p, q = bl.build_view_matrices(views, 3)
    omega = np.diag([4e-4])
    mu = bl.posterior_woodbury(sigma, pi, p, q, omega)
    assert np.all(np.isfinite(mu))


def test_woodbury_rejects_non_psd_omega() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0]])
    q = np.array([0.12])
    omega = np.array([[-1e-4]])  # negative -> not PSD
    with pytest.raises(ValueError, match="PSD|positive"):
        bl.posterior_woodbury(sigma, pi, p, q, omega)


def test_woodbury_rejects_shape_mismatch() -> None:
    sigma = _fixture_sigma()
    pi = bl.equilibrium(sigma, _W_MKT)
    p = np.array([[1.0, 0.0, 0.0]])
    q = np.array([0.12, 0.09])  # 2 entries but P has 1 row
    omega = np.diag([4e-4])
    with pytest.raises(ValueError, match="inconsistent|shape|rows"):
        bl.posterior_woodbury(sigma, pi, p, q, omega)
```

- [ ] **Step 2: Run it, expect FAIL.**
  Command: `cd backend && python -m pytest tests/test_optimizer_bl_multiview.py -v`
  Expected failure: `AttributeError: module 'app.optimizer.black_litterman' has no attribute 'posterior_woodbury'`.

- [ ] **Step 3: Write the minimal implementation.** Add to `backend/app/optimizer/black_litterman.py` after `posterior` (after line 210). `_validate_sigma` (imported lines 22-29) and `DEFAULT_TAU = 0.05` (line 32) already exist:
```python
# Per-entry Ω regularization floor (legacy REG_OMEGA_EPS_FACTOR,
# black_litterman_service.py:56): a confidence=1 view drives Ω_ii -> 0; we floor
# each diagonal entry relative to its own magnitude so a near-certain view stays
# dominant without making Ω singular.
_REG_OMEGA_EPS_FACTOR = 1e-8


def posterior_woodbury(
    sigma_ann: np.ndarray,
    pi: np.ndarray,
    p: np.ndarray,
    q: np.ndarray,
    omega: np.ndarray,
    tau: float = DEFAULT_TAU,
) -> np.ndarray:
    """BL posterior mean via the Woodbury data-update form (full Ω supported).

    Ported from quant_engine/black_litterman_service.py:239-253:

        μ_BL = π + τΣ·Pᵀ · (P·τΣ·Pᵀ + Ω)⁻¹ · (Q − P·π)

    Never inverts τΣ — only the strictly-PD K×K view-space matrix
    (P·τΣ·Pᵀ + Ω_reg). A zero-variance asset transmits no information (its row
    of τΣ·Pᵀ is zero) instead of producing a singular τΣ. Accepts a FULL
    (non-diagonal) Ω; a per-entry diagonal floor keeps the solve stable even
    for confidence≈1 views.

    Returns the posterior MEAN only (the classic :func:`posterior` returns mean
    and Σ_BL; callers needing Σ_BL keep using it). All inputs annualized.

    Raises:
        ValueError: shape mismatch, non-finite inputs, non-symmetric/non-PSD Ω,
            tau ≤ 0, or a singular view-space matrix.
    """
    sigma_ann = _validate_sigma(sigma_ann, "posterior_woodbury")
    pi = np.asarray(pi, dtype=float).ravel()
    p = np.asarray(p, dtype=float)
    q = np.asarray(q, dtype=float).ravel()
    omega = np.asarray(omega, dtype=float)
    n = sigma_ann.shape[0]
    if pi.shape != (n,):
        raise ValueError(f"pi has shape {pi.shape}, expected ({n},)")
    if p.ndim != 2 or p.shape[1] != n:
        raise ValueError(f"P shape {p.shape} inconsistent with n ({n})")
    k = p.shape[0]
    if q.shape != (k,):
        raise ValueError(f"Q shape {q.shape} inconsistent with P rows ({k})")
    if omega.shape != (k, k):
        raise ValueError(f"Omega shape {omega.shape} inconsistent with P rows ({k})")
    if tau <= 0:
        raise ValueError(f"tau must be > 0, got {tau}")
    if not (np.isfinite(pi).all() and np.isfinite(p).all()
            and np.isfinite(q).all() and np.isfinite(omega).all()):
        raise ValueError("posterior_woodbury: non-finite input")
    if not np.allclose(omega, omega.T, atol=1e-12):
        raise ValueError("Omega must be symmetric")
    if float(np.linalg.eigvalsh(omega).min()) < -1e-10:
        raise ValueError("Omega is not PSD (negative eigenvalue)")

    # Per-entry diagonal regularization (legacy lines 218-237).
    omega_diag = np.clip(np.diag(omega), 0.0, None)
    positive = omega_diag[omega_diag > 0.0]
    if positive.size == 0:
        eps_vec = np.full(k, 1e-12)
    else:
        floor_for_zero = _REG_OMEGA_EPS_FACTOR * float(positive.min())
        eps_vec = np.where(
            omega_diag > 0.0, _REG_OMEGA_EPS_FACTOR * omega_diag, floor_for_zero
        )
    omega_reg = omega + np.diag(eps_vec)

    tau_sigma = tau * sigma_ann                       # (N, N)
    tau_sigma_pt = tau_sigma @ p.T                    # (N, K)
    view_space = p @ tau_sigma_pt + omega_reg         # (K, K) strictly PD
    innovation = q - p @ pi                           # (K,)
    try:
        mu_post = pi + tau_sigma_pt @ np.linalg.solve(view_space, innovation)
    except np.linalg.LinAlgError as exc:
        raise ValueError(
            f"posterior_woodbury: singular view-space matrix (P·τΣ·Pᵀ + Ω): {exc}"
        ) from exc
    if not np.all(np.isfinite(mu_post)):
        raise ValueError("posterior_woodbury produced non-finite output")
    return np.asarray(mu_post, dtype=float)
```

- [ ] **Step 4: Run tests, expect PASS.**
  Command: `cd backend && python -m pytest tests/test_optimizer_bl_multiview.py tests/test_optimizer_black_litterman.py -v`
  Expected: 5 new passed; existing BL gate tests in `test_optimizer_black_litterman.py` still green (the classic `posterior` is untouched).

- [ ] **Step 5: Commit.**
  `cd backend && git add app/optimizer/black_litterman.py tests/test_optimizer_bl_multiview.py`
  Commit message: `feat(optimizer): BL Woodbury full-Ω multi-view posterior (rank 43, ported from legacy)`

---

### Task T3G-6: SPIKE/DECISION — TAA regime bands (rank 45, LARGE — NO code yet)

This is a multi-sprint track that CANNOT be TDD-coded today because the light app lacks the entire substrate the legacy `taa_band_service` (taa_band_service.py:80-353) assumes. This task produces a written decision record + phased breakdown, not implementation. **Do not fabricate band code.**

**Files:**
- Create (decision doc only, NOT code): `docs/superpowers/plans/2026-06-14-taa-regime-bands-spike.md`

**What the legacy needs that the light app does NOT have (verified):**
1. An asset-class **block** taxonomy + per-block IPS min/max bounds (`StrategicAllocation`). The light optimizer is per-asset (fund/equity) with only `cap`/`min_weight` (engine.base_constraints, engine.py:80-89) — there is no block layer, no `BlockConstraint`, no `AllocationBlock` model (light `app/models/` has eod_price/fund/instrument/news_item/portfolio/rebalance/screen/screener_metrics/universe only).
2. A persisted **`taa_regime_state`** row carrying `smoothed_centers`, `raw_regime` (RISK_ON/RISK_OFF/INFLATION/CRISIS), `stress_score`, `_previous_smoothed_centers` — and a worker to compute + EMA-smooth it (`smooth_regime_centers`, taa_band_service.py:122-157, halflife=5, max_daily_shift=0.03). None exists.
3. A 4-state regime label. The light regime signal is BINARY credit stress (`app.services.macro_regime` — NOTE: the exact symbol name `fetch_composite_regime` is from the draft and was NOT opened in this pass; verify before any wiring, see open_questions) — no per-asset-class centers, no 4-regime taxonomy.

**Phased breakdown to record in the doc (each phase its own future cluster):**
- Phase 0 (DECISION, blocking): does the light product have/want an asset-class block model, or are TAA bands expressed per-fund? (open_questions)
- Phase 1 (WORKERS repo, `[repo: investintell-datalake-workers]`): extend the regime worker to emit a 4-state label + per-asset-class target centers; persist a `taa_regime_state` table in the data-lake.
- Phase 2 (LIGHT data-model): add the block taxonomy + IPS bounds model (only if Phase 0 says block-level).
- Phase 3 (LIGHT analytics, TDD): port `compute_effective_band` (IPS∩regime intersection, taa_band_service.py:80-114) and `smooth_regime_centers` (EMA + max-daily-shift cap, lines 122-157) as pure functions on synthetic dicts — THESE are TDD-able once Phases 0-2 land.
- Phase 4 (LIGHT optimizer wiring): translate effective bands into per-asset `min_weight`/`cap` vectors and feed the engine.

**Validation gate to record:** backtest the band-constrained optimizer vs. the unconstrained min-CVaR product default; TAA must not degrade Sharpe/DD beyond an agreed tolerance (reuse the regime-detector backtest harness referenced in memory `regime-detector-alternatives`).

- [ ] **Step 1:** Write the decision doc with the three substrate gaps, the phased breakdown above, and the Phase 0 decision question. NO test, NO implementation code — this task's deliverable is the doc + the open_questions entry. Commit: `git add docs/superpowers/plans/2026-06-14-taa-regime-bands-spike.md && git commit -m "docs(taa): rank 45 TAA regime bands spike + phased plan (substrate-blocked)"`.

---

### Task T3G-7: SPIKE/DECISION — fundamental factor track (rank 46, LARGE — NO code yet)

The legacy fundamental factor model (`factor_model_service.py` — `assemble_factor_covariance` lines 679-725 building Σ = B·F·B' + diag(D) from a `FundamentalFactorFit`, plus the EWMA-WLS loadings fit and 8-factor panel ingestion elsewhere in the file) is portable MATH but meaningless without the factor-return panel it ingests, which does not exist in the light app. This task produces a decision record + phased plan, not code. **Do not fabricate factor code.** (Note: the PSD eigen-repair sub-part of `assemble_factor_covariance`, lines 706-723, is already extracted in T3G-3, so the conditioning piece is done.)

**Files:**
- Create (decision doc only, NOT code): `docs/superpowers/plans/2026-06-14-fundamental-factor-track-spike.md`

**What the legacy needs that the light app does NOT have (verified):**
1. A **`benchmark_nav`** table (daily benchmark NAV levels for SPY/IEF/HYG/IWM/IWD/IWF/EFA) — absent (light `app/models/` has eod_price/fund/instrument/news_item/portfolio/rebalance/screen/screener_metrics/universe only).
2. A **`macro_data`** table for OAS credit-spread macro proxies — absent.
3. An **`AllocationBlock.benchmark_ticker`** mapping — absent (no block model, same gap as T3G-6).
4. A **`write_audit_event`** sink — absent.

**Phased breakdown to record in the doc:**
- Phase 0 (DECISION, blocking): is per-fund fundamental factor exposure a product requirement, or does the existing Ledoit-Wolf Σ (`engine.sigma_ledoit_wolf`, engine.py:35-55) suffice? Which factor proxies are ingestible from the data sources the light app has (Tiingo for benchmark ETFs; FRED for OAS macro)? (open_questions)
- Phase 1 (WORKERS repo, `[repo: investintell-datalake-workers]`, the DB-first home per the project contract): build the offline factor-return panel ingestion (benchmark ETF NAVs + macro proxies → aligned daily simple-return panel, levels-then-pct_change + ffill conventions) and persist it to TimescaleDB Cloud. File e.g. `src/workers/factor_panel.py`.
- Phase 2 (WORKERS repo): compute + persist the assembled factor covariance Σ = B·F·Bᵀ + diag(D) per fund universe (port the EWMA-WLS loadings fit + `assemble_factor_covariance` lines 679-725, calling the already-ported T3G-3 `repair_psd` for the eigenvalue floor). Persist Σ to the data-lake.
- Phase 3 (LIGHT app): READ the persisted factor Σ via `app.core.datalake` AsyncSession and feed it to the optimizer as an alternative to the in-app Ledoit-Wolf Σ — the app does NOT recompute the heavy factor fit (DB-first contract).

**Validation gate to record:** compare optimizer outputs (weights, ex-ante CVaR) under factor-Σ vs. Ledoit-Wolf Σ on the same universe; factor-Σ must improve out-of-sample CVaR/condition number to justify the ingestion cost. The factor fit math is TDD-able as pure functions in the WORKERS repo once Phases 0-1 land the panel.

- [ ] **Step 1:** Write the decision doc with the four substrate gaps, the phased breakdown above (Phases 1-2 explicitly labelled `[repo: investintell-datalake-workers]`), and the Phase 0 decision questions. NO test, NO implementation code — deliverable is the doc + open_questions entry. Commit: `git add docs/superpowers/plans/2026-06-14-fundamental-factor-track-spike.md && git commit -m "docs(factor): rank 46 fundamental factor track spike + phased plan (substrate-blocked, worker-repo home)"`.

---

## Perguntas em aberto / decisoes necessarias (Tier 3)

_Resolver antes (ou no inicio) da execucao das tasks afetadas._

### T3A
- The cluster brief states 'per-block benchmark_nav exists in the data-lake' and asks for a 'new fact-sheet endpoint'. VERIFIED FALSE in the light repo: `grep -ri benchmark_nav backend/` and `grep -ri AllocationBlock backend/` each return ZERO hits (re-run during this hardening pass). Light benchmarks are SINGLE tickers whose adjusted closes come from eod_prices (see app/services/portfolio_analysis.py `assemble_portfolio_analysis(..., benchmark_adj_close)`). Therefore T3A builds the composite-benchmark synthesizer as a PURE analytics function (port of legacy compute_composite_nav) that takes already-resolved per-block return Series; it does NOT read the data-lake. The DB-read orchestrator (run_*) + fact-sheet HTTP route are deliberately deferred because the data source (a block-weighted multi-benchmark model) does not yet exist in light. DECISION NEEDED from the owner: (a) is a multi-block composite benchmark a product concept in light, or is the single-ticker benchmark sufficient? (b) if composite is wanted, where do per-block benchmark returns live (a new data-lake table the WORKERS repo must materialize, or computed on the fly from eod_prices of a benchmark-ticker-per-block map)? Until that is decided, the run_*/route layer cannot be specified without inventing a schema (would violate the no-placeholder contract).
- Legacy return_statistics_service._to_monthly_returns aggregates daily->monthly via fixed 21-day END-ANCHORED blocks (drops the oldest `len % 21` days; verbatim at legacy lines 136-151). This is a documented approximation (calendar months are not exactly 21 trading days). Ported verbatim in T3A-2 to stay numerically identical to the legacy fact-sheet. Flag for the owner: if the fact-sheet must reconcile to a calendar-month eVestment report, a true month-end resample (`returns.resample('ME')`) would be required instead. Kept the legacy behavior to preserve cross-system parity.
- Legacy _compute_sterling_ratio (legacy lines 182-226) splits the daily series into 252-day yearly chunks (end-anchored), averages each chunk's max drawdown, then uses denominator |avg_max_dd - 0.10| (Kestner 1996 additive-cushion convention, pinned WMJ-022). Ported as-is in T3A-4 (reusing light max_drawdown on per-chunk NAV Series instead of legacy compute_drawdown_series; verified numerically identical during this hardening pass). If light later wants calendar-year chunking instead of fixed 252-day chunks, the chunk boundaries would change; confirm the fixed-252 convention is acceptable for light's fact-sheet.
- Scale change vs legacy: legacy up/down proficiency and the relative ratios returned PERCENTAGES (`* 100`, e.g. 60.0) and the result fields were rounded (round(x, 8/4/2)). T3A re-expresses proficiency as DECIMAL FRACTIONS in [0,1] (0.6 = 60%) to honour the light scale contract, and returns UNROUNDED floats (rounding is a serialization concern, not an analytics concern, in light). This is an intentional, documented divergence from legacy output magnitude; confirm any downstream fact-sheet renderer multiplies by 100 for display.

### T3B
- Style-box growth/value axis: equity_characteristics_monthly has book_to_market (a VALUE proxy) but NO standalone growth metric (verified columns: size_log_mkt_cap, book_to_market, mom_12_1, quality_roa, investment_growth, profitability_gross — characteristics.sql lines 52-57). The legacy style_analysis.classify_fund_style (E:/investintell-allocation/backend/quant_engine/style_analysis.py lines 81-191) derived growth via SECTOR exposure of N-PORT holdings (GROWTH_SECTORS/VALUE_SECTORS frozensets, lines 19-26) — a DIFFERENT data source than this cluster's spec. This plan defines the value/growth axis from book_to_market alone (high B/M => value, low B/M => growth), per the cluster directive 'size_log_mkt_cap/book_to_market thresholds + tilt'. Confirm product accepts a single-metric (B/M) growth axis rather than a multi-factor or sector-based composite.
- Style-box thresholds: there are no canonical size/value cut-points in the light repo or legacy for the FUND-level chars (size_log_mkt_cap is log of summed equity-sleeve market value per the legacy aggregation; book_to_market is fund-aggregate). The legacy StyleConfig used a fixed growth_tilt_threshold=0.55 over SECTOR sums (style_analysis.py line 37), not over B/M, so it is not reusable here. This plan uses cross-sectional TERCILE breakpoints (33.3333/66.6667 percentiles) computed from the as-of cohort (data-driven, no magic numbers) — the standard Morningstar-style approach. Confirm tercile (33/67) vs. fixed absolute cut-points.
- gamma_drift persistence target: factor_model.sql has no drift column today (verified: columns end at asset_class, schemas/factor_model.sql line 34; last index at line 45). Task T3B-3 ADDS gamma_drift_vs_prior NUMERIC + drift_alert BOOLEAN to factor_model_fits via idempotent ALTER ... ADD COLUMN IF NOT EXISTS. Confirm storing drift on the fit row is acceptable vs. a separate factor_model_drift table. The DDL apply step (psql -f) against TimescaleDB Cloud must be run by someone holding the cloud DSN — flagged in the task as a manual ops step.
- K grid upper bound: legacy fit_universe used max_k=6 (factor_model_ipca_service.py line 54) and the worker CHARS_COLS has L=6 instruments (factor_model.py lines 76-83). This plan uses k in 1..min(max_k, L) and the worker's existing oos_r_squared walk-forward (min_train/test_window configurable, default 24/12 — factor_model.py lines 255-263). NOTE the legacy CV used a FIXED 60m-train/12m-test window and required len(dates)>=72 (factor_model_ipca_service.py lines 92, 116-120); the worker oos_r_squared is parameterized instead, so the K-selection tests pass min_train=36/test_window=12 explicitly. Confirm 6 (or L) is the desired ceiling and that the parameterized window (vs. legacy's hard-coded 60/12) is acceptable.

### T3C
- manager_score is a numeric(5,2) column of fund_risk_metrics in the WORKERS repo and is copied verbatim into the light's fund_risk_latest_mv MV (E:/investintell-light/backend/db/ddl/2026-06-13_dynamic_catalog.sql lines 71-73 SELECT it) and onto the light ORM (E:/investintell-light/backend/app/models/fund.py FundRiskLatest.manager_score line 177). The brief said 'New light service over fund_risk_metrics' but the DB-first contract forbids the app computing recurring quant. This cluster therefore implements the composite + enriched peer ranking as WORKER post-steps that populate the columns the light already READS (no app-side compute). If the product owner instead wants an on-demand app-side recompute that ignores the persisted column, that is a separate service NOT covered here.
- VERIFIED CORRECTION to the legacy port: the legacy equity composite (scoring_service._compute_equity_score, lines 706-789) has SIX weighted components in _DEFAULT_SCORING_WEIGHTS (lines 94-101): return_consistency 0.20, risk_adjusted_return 0.25, drawdown_control 0.20, information_ratio 0.15, flows_momentum 0.10, fee_efficiency 0.10. fund_risk_metrics carries NEITHER an expense ratio (no fee_efficiency) NOR a flows signal (no flows_momentum), so BOTH are dropped and the remaining FOUR risk weights (0.20/0.25/0.20/0.15, summing 0.80) are renormalized /0.80 to 0.25/0.3125/0.25/0.1875 (sum 1.0). The earlier draft invented a 5th 'robust_sharpe' peaked component (weight 0.10) that does NOT exist anywhere in the legacy (grep of scoring_service.py for 'robust_sharpe' hits only the use_robust_sharpe flag at lines 320/331, never a component) — it is REMOVED. The robust-Sharpe behavior IS faithfully preserved inside risk_adjusted_return via _resolve_sharpe (sharpe_cf preferred, fall back to sharpe_1y), exactly as legacy _resolve_sharpe_input does with use_robust_sharpe=True (lines 307-334).
- elite_flag remains a dead boolean column (schemas/risk_metrics.sql line 150; light model FundRiskLatest.elite_flag line 178; light MV selects it at DDL line 73). The brief lists only manager_score as the column to populate; no elite-flag threshold rule exists in the legacy sources, so elite_flag is left NULL (out of scope). Confirm whether a threshold (e.g. manager_score >= cutoff) should set it.
- Three new peer columns (peer_overall_quartile, peer_band_low, peer_band_mid, peer_band_high) are added to schemas/risk_metrics.sql so the enriched SQL has somewhere to write. The light's fund_risk_latest_mv DDL (2026-06-13_dynamic_catalog.sql lines 71-73) selects manager_score/peer_sharpe_pctl/.../elite_flag but NOT these new columns, and FundRiskLatest (fund.py lines 138-178) has no quartile/band fields — so a follow-up LIGHT-SIDE migration (extend the MV SELECT + add ORM columns) is needed to SURFACE them to the app. T3C only persists them in the worker table and is forward-compatible; flag for a downstream light task.
- Pre-existing regression guarded: tests/test_risk_metrics.py::test_run_refreshes_mv_after_lock_released (lines 386-421) monkeypatches every run() I/O seam EXCEPT the new _update_manager_scores. Because _fetch_fund_ids returns [] there, run() takes the serial path and would call the REAL _update_manager_scores against the _FakeConn whose _FakeCursor (lines 315-326) has no fetchall(). T3C-2 Step 3(e) adds monkeypatch.setattr(rm, '_update_manager_scores', lambda _c, _cd: 0) to that existing test to keep it green.

### T3D
- RESOLVED BY SOURCE READ (kept for the executing engineer's awareness) — EXPENSE-RATIO SYNC BOUNDARY. The contract suggested applying expense normalization 'at ingest' in backend/app/sync/mother_db.py. Verified: backend/app/sync/mother_db.py contains NO 'expense_ratio' reference (grep: 0 matches) — it syncs only fundamentals_snapshot and universe_constituents, neither of which carries expense_ratio. backend/app/sync/funds.py does NOT exist (the Python fund sync was decommissioned in commit 026dea1; only backfill.py, metrics.py, mother_db.py remain in app/sync/). Fund expense ratios are read from Fund.expense_ratio (backed by the funds_v dynamic VIEW). The ONLY live Python seam that emits expense_ratio to a client is the fund-profile route (backend/app/api/routes/funds.py line 280, float(fund.expense_ratio)). Task T3D-3 therefore ports the pure normalizer into app/analytics/expense_ratio.py and applies it at that READ seam. The alternative (push normalization into the funds_v VIEW SQL on Tiger, backend/db/ddl/2026-06-13_dynamic_catalog.sql) is a DDL change outside the app's Python test surface and is NOT modeled as a TDD task. CONFIRM the read-seam placement is acceptable for the product; the app-side normalizer was chosen because it is unit-testable and reversible.
- RESOLVED BY SOURCE READ — EXPENSE-RATIO SCALE-DETECT SOURCE OF TRUTH. The authoritative current legacy file E:/investintell-allocation/backend/quant_engine/expense_ratio_validator.py has signature to_decimal_fraction(value: Any) -> float | None with NO 'source' kwarg, classifies (0.15, 1.0] as whole percent (line 93-114), divides >100 by 10000 (bps), and clamps to [0.0, 0.15]. The older audit test that called to_decimal_fraction(0.1, source='N-CEN') references a kwarg that no longer exists. Task T3D-3 ports the CURRENT (no-source) version. Verified: grep over backend/ found ZERO callers of to_decimal_fraction in the Light app today, so porting the no-source signature breaks nothing.
- RESOLVED BY SOURCE READ — TWO-TIER DRIFT THRESHOLDS. Legacy drift_service.compute_block_drifts (E:/investintell-allocation/backend/quant_engine/drift_service.py lines 137-184) uses maintenance_trigger=0.05 / urgent_trigger=0.10 absolute bands with inclusive '>=' comparisons (lines 168-171). The Light evaluator (backend/app/rebalance/evaluator.py) exposes DEFAULT_BAND_ABS=0.05 (line 57) and per-policy band_abs (line 276); it has NO urgent band today. Task T3D-1 maps the EXISTING band_abs to 'maintenance' and introduces a derived 'urgent' threshold = 2 x band_abs clamped to <= 1.0, mirroring the legacy 0.10 when band_abs is the default 0.05. CONFIRM the 2x relationship vs. a separately-stored urgent band on the RebalancePolicy model — the latter would require an Alembic migration (RebalancePolicy is at backend/app/models/rebalance.py), which is out of scope for this analytics-only cluster. No DB migration is included.
- MINOR — RebalancePolicyIn already validates band_abs with Field(gt=0, le=1) (backend/app/schemas/rebalance.py line 18), so a stored band_abs is in (0, 1] and default_urgent_band clamps the 2x to <= 1.0 only for band_abs > 0.5. No schema change is needed for the urgent band because it is DERIVED, not stored or accepted as input.

### T3E
- Sign convention divergence resolved by design, not a blocker: legacy tail_var_service.py (compute_tail_risk) and cvar_service.py (compute_cvar) return NEGATIVE return-space losses; the Light app analytics (app/analytics/risk.py historical_var/historical_cvar, lines 64-114) return POSITIVE loss magnitudes. This plan ports the math but keeps the Light POSITIVE-loss convention for all new functions to stay consistent with the existing rail, and documents the conversion explicitly in each function's docstring.
- Wiring the tail panel into the live statistics service (assemble_scenario / a /statistics/tail-panel endpoint and ScenarioStatistics schema fields) is intentionally OUT OF SCOPE for T3E ranks 30-31 (it would touch the schemas/route rail owned by other clusters). T3E delivers the pure analytics (tail.py panel + risk.py parametric/EVT carrier) that the service layer will consume. If the live-service endpoint is required under this cluster it needs a product decision on the response schema shape (how to surface the EVT degraded carrier) and should be a follow-up rank — flagged here, not fabricated.
- lmoments3 is NOT a guaranteed dependency in the Light backend (legacy pot_gpd.py guards its L-moments fallback via LMOMENTS_AVAILABLE / importlib find_spec, lines 130-143). This plan does NOT port the L-moments fallback; it uses scipy genpareto MLE only — exactly the worker risk_metrics.py::evt_tail recipe (lines 243-293), which is proven offline. The EVT carrier degrades fail-closed when the GPD MLE does not converge or the fit is invalid.
- The EVT VaR clamp `var_loss = max(var_loss, u)` is ported from legacy pot_gpd.py line 205 (POT VaR is bounded below by the threshold u), NOT from the worker evt_tail (which omits it because it only queries deep quantiles 0.99/0.999 where the bound is never binding). It is included here as a defensive bound because evt_tail_var_cvar accepts an arbitrary confidence; it is harmless for the deep tail and documented as such in the code comment.

### T3F
- T2E absorption-ratio module is still absent from the light app (grep 'absorption' under backend/app returns nothing). This plan makes backend/app/analytics/rmt.py the SINGLE owner of absorption_ratio(); T2E must import it from here. If T2E is scheduled to create its own absorption module first, re-point T3F-1's absorption_ratio to import that and flag at execution time.
- T2C is not present in this repo (no module/marker found). The correlation-regime service is SELF-CONTAINED: it consumes the (T,N) numpy matrix via optimizer_data.load_aligned_returns (verified signature (session, assets, window_days, today)) and calls app.analytics.rmt directly — NO hard dependency on T2C. If T2C later supplies a shared returns-matrix loader, refactor run_correlation_regime (T3F-5) to call it; recorded, not blocking.
- Product decision: separate POST /correlation-regime endpoint vs folding the regime block into POST /builder/optimize. This plan ships a dedicated endpoint with a minimal CorrelationRegimeRequest (assets OR universe, window_days) mirroring OptimizeRequest's verified shape (FundRefIn/EquityRefIn discriminated union, UniverseSpecIn). Confirm with product.
- robust/vol-target SOCP solvers (solve_bl_robust, solve_bl_vol_target) live in black_litterman.py per gate G5. T3F-3/T3F-4 deliver + unit-test the engine-level functions but DO NOT wire them into portfolio_builder.run_optimize objective dispatch (the Objective Literal in app/schemas/builder.py lines 72-74 is currently equal_weight|min_vol|erc|max_diversification|min_cvar|bl_utility). Extending that enum ('bl_robust','bl_vol_target') + request fields (uncertainty_level, vol_target_annual, confidence) is a follow-up rank. Flag if the builder enum extension is in-scope for this tier.
- The SCS fallback ladder in T3F-2 only applies to solvers routing through engine._finalize: solve_min_vol, solve_min_cvar (engine.py) and solve_bl_utility, solve_bl_robust, solve_bl_vol_target (black_litterman.py). solve_erc (engine.py lines 182-193) and solve_max_diversification (lines 220-234) keep their OWN inline problem.solve()/status checks and are NOT changed here. If product wants the ladder on ERC/max-div too, that is an additional rank.
- T3F-7 route tests cover the explicit-assets happy path + two 422 paths (service ValueError, missing source). A universe-path route test (select_universe_funds stubbed) is deferred to keep the route thin; the universe selection logic is already covered by builder tests. Add a universe-path route test if product wants the regime endpoint's universe branch independently pinned.
- ECOS is NOT in cp.installed_solvers() (CLARABEL, HIGHS, OSQP, SCIPY, SCS are). The SCS ladder uses only CLARABEL+SCS, so this is fine; the T3F-2 telemetry test was tightened to assert solver in {CLARABEL, SCS} (the original draft's {CLARABEL,SCS,OSQP,ECOS} set was permissive but referenced an uninstalled solver).

### T3G
- T2C dependency (BLOCKER for T3G-1, rank 37): the light min-CVaR solver has NO cvar_limit parameter today. CONFIRMED by grep -rE 'cvar_limit|cvar_cap|cvar_constraint' over backend/app/ -> ZERO matches. backend/app/optimizer/engine.py:237-244 solve_min_cvar(scenarios, alpha, cap, min_weight, ret_floor, mu) has no cap. The cluster brief says rank 37 'depends on the T2C CVaR-limit path'. T3G-1 is therefore written to ADD a thin optional cvar_limit constraint to solve_min_cvar as a self-contained increment (default None = no-op, so the existing tests test_g2_min_cvar_optimal_sum_and_caps and test_g5_min_cvar_floor_requires_explicit_mu at test_optimizer_engine.py:80/148 stay green). If T2C lands the cvar_limit parameter first, drop T3G-1 Step 3b and keep only compute_regime_adjusted_limit + a test that feeds it into T2C's parameter. Confirm with the T2C author who owns the solve_min_cvar signature change to avoid a merge collision.
- Rank 41 data-model decision (BLOCKER for full FSM wiring, NOT for the pure code): the legacy breach FSM (cvar_service.check_breach_status lines 446-505 + rebalance_service.determine_cascade_action lines 76-157) requires (a) a per-profile CVaR config ProfileCVaRConfig {window_months, confidence, limit, warning_pct, breach_days} keyed by 'conservative'/'moderate'/'growth' (_DEFAULT_CVAR_CONFIG lines 40-62) and (b) persistence of consecutive_breach_days + previous_trigger_status across evaluations. The light app has NO portfolio-profile config table and NO profile concept (portfolios are user-built, profile-free); RebalancePolicy (backend/app/models/rebalance.py:26-74) stores only frequency/band_abs/band_rel/macro_trigger_enabled/last_evaluated_at/created_at/updated_at. NOTE: the legacy determine_cascade_action signature is 6-arg (trigger_status, previous_trigger_status, cvar_utilization, consecutive_breach_days, risk_profile=None, config=None) and formats utilization/thresholds INTO its reason strings; T3G-4 ports a SIMPLIFIED profile-free 2-arg determine_cascade_action(trigger_status, previous_trigger_status) whose reason strings are static (no profile config), because the light app has no profile/config to format. Product decisions still open: (1) what limit/warning_pct/breach_days values apply with no profile taxonomy? (2) does the FSM persist on the advisory preview path (which stamps nothing today) or only on the scheduled job scripts/evaluate_rebalance.py (which is what stamps last_evaluated_at)? Owner must answer before wiring into the evaluator; the PURE FSM + additive migration in T3G-4 are safe to land regardless.
- Rank 45 (TAA regime bands, LARGE) substrate is ABSENT: legacy taa_band_service (compute_effective_band lines 80-114, smooth_regime_centers lines 122-157, _disaggregate_centers_to_blocks line 165) consumes (a) a per-block asset_class taxonomy + StrategicAllocation IPS min/max bounds, (b) a persisted taa_regime_state row (smoothed_centers, raw_regime, stress_score, _previous_smoothed_centers), and (c) BlockConstraint from optimizer_service. The light optimizer is FUND/EQUITY-level (per-asset cap/min_weight only — engine.base_constraints engine.py:80-89), has NO block/asset-class layer, NO StrategicAllocation/IPS model, NO taa_regime_state table, NO EMA-smoothing worker (backend/app/models/ has eod_price/fund/instrument/news_item/portfolio/rebalance/screen/screener_metrics/universe only). The light regime signal that exists is the binary credit-stress detector (app.services.macro_regime — NOTE: not opened in this pass; the draft cites fetch_composite_regime state+last_flip — verify exact symbol name before any wiring). Product decision required: does the light product have an asset-class block model, or are bands expressed per-fund? Multi-sprint track needing new substrate; T3G-6 is a SPIKE/decision doc, not code.
- Rank 46 (fundamental factor track, LARGE) substrate is ABSENT: legacy factor_model_service.assemble_factor_covariance (lines 679-725) builds Σ = B·F·B' + diag(D) from a FundamentalFactorFit (fit.loadings/factor_cov/residual_variance, line 699-701) that depends on a benchmark_nav table, a macro_data table (8 factor proxies: SPY/IEF/HYG/IWM/IWD/IWF/EFA + OAS macro), an AllocationBlock.benchmark_ticker mapping, and a write_audit_event sink — NONE exist in the light app. The eigenvalue-floor PSD-repair sub-part (lines 706-723) is the ONLY portable-standalone piece and is extracted in T3G-3. The full EWMA-WLS loadings fit + factor-return panel ingestion belongs in the WORKER repo (investintell-datalake-workers) per the DB-first contract; the app would READ the persisted Σ. Product decisions required: which benchmark/macro series are ingestible from Tiingo/FRED today, and is per-fund fundamental factor exposure a product requirement vs. the existing Ledoit-Wolf Σ (engine.sigma_ledoit_wolf engine.py:35-55)? T3G-7 is a SPIKE/decision doc, not code.
- T3G-2 RealizedCVaRCheck dataclass note: the realized-CVaR verifier reuses historical_cvar (risk.py:88-114), whose tail estimator differs slightly from the optimizer's in-engine Rockafellar-Uryasev cvar expression (engine.py:274, which uses cp.pos and the (1-alpha)*T denominator). They will NOT be bit-identical. T3G-2 verifies the REALIZED out-of-sample shortfall via the analytics estimator, not by re-deriving the optimizer's exact LP value — this is the intended audit semantics, but confirm with the rank-39 owner that 'verify' means realized-shortfall-vs-limit and not exact-LP-reproduction.

