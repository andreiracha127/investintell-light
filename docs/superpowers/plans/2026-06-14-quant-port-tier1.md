# Quant Port -- Tier 1 -- Analytics online de alto valor (vitorias baratas) (Implementation Plan)

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Entregar, sobre dados que o `light` ja calcula, as metricas ajustadas ao risco e de diversificacao que faltam no caminho online, alinhar o CVaR in-sample ao estimador RU do otimizador e expor os scorecards macro ja materializados no data-lake.

**Architecture:** Sao majoritariamente funcoes puras de ~30 linhas em numpy/pandas mais fiacao de schema/rota. Cada item segue o padrao analytics puro + wiring em `assemble_*`/`run_*`, ou um reader DB-first espelhando `services/macro_regime.py`.

**Tech Stack:** Python 3.12, numpy, pandas, pydantic, FastAPI, SQLAlchemy async (todos ja presentes).

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

- **T1A** (8 tasks) -- #1 Sharpe/Sortino/IR online, #2 Effective Number of Bets (entropia), #3 Active Share
- **T1B** (9 tasks) -- #4 Metricas de regressao RF/alternativos (duracao empirica, credit/inflation beta, crisis alpha)
- **T1C** (3 tasks) -- #5 CVaR in-sample -> estimador RU exato
- **T1D** (4 tasks) -- #6 Serving macro regional + indicadores globais + fiscal Tesouro

---

## Tier 1 — Online risk-adjusted analytics (Sharpe/Sortino/IR, Effective Number of Bets, Active Share)

This cluster adds five pure analytics functions and wires the directly-wireable ones into the response schemas/services. Every function follows the Light's established fail-loud + min-obs guard pattern (raise `ValueError` on insufficient/NaN data, never return NaN), uses the decimal-fraction scale contract (0.05 = 5%, never 0-100), and is unit-tested directly on synthetic pandas/numpy inputs before any service wiring. None of these functions consume a sample mean of asset returns as an expected-return signal, so gate G5 (mu-free) is untouched: Sharpe/Sortino/IR are descriptive ratios of a *realized* return series, ENB is a covariance decomposition, and Active Share is a weight distance.

Source provenance (all line numbers verified by re-reading the files):
- Sharpe/Sortino formulae mirror `E:/investintell-allocation/backend/quant_engine/return_statistics_service.py` (`compute_sharpe_ratio` lines 39-72, `compute_sortino_ratio` lines 75-102; `DEFAULT_RISK_FREE_RATE = 0.04` line 36, `TRADING_DAYS_PER_YEAR = 252` line 34) and the worker `E:/investintell-datalake-workers/src/workers/risk_metrics.py` (`sharpe` lines 132-141, `sortino` lines 144-154). Both use daily excess = `returns - rf/252`, annualize by sqrt(252), `ddof=1` for Sharpe vol, and Target-Downside-Deviation `sqrt(mean(min(excess,0)**2))` (full-sample N denominator) for Sortino. The Light port DROPS the worker's `MIN_ANNUALIZED_VOL` floor (a stale-NAV data-quality filter for batch screening) and instead fails loud on exactly-zero denominators, matching the Light's other ratio functions (`beta`, `correlation`).
- Information Ratio mirrors the worker `regression_metrics` (lines 455-505), specifically the active-return block lines 484-488: `te = std(active, ddof=1)*sqrt(252)`; `IR = mean(active)*252 / te`.
- Effective Number of Bets (entropy) mirrors `diversification_service._entropy_enb` (lines 198-209): `exp(-Sum RC_i ln RC_i)` over normalized non-negative risk contributions, applied to the Light's existing `risk_contributions()` dict (`backend/app/analytics/portfolio.py` lines 244-280, which returns a CTR decomposition summing to 1).
- Active Share mirrors `active_share_service.compute_active_share` (lines 31-124): `0.5 * Sum|w_p,i - w_b,i|` over the union of identifiers, with a weight-sum sanity guard (legacy `_WEIGHT_SUM_TOL = 0.05` at line 80) — but returns a DECIMAL FRACTION (Light scale contract) rather than the legacy 0-100 (legacy line 103 multiplies by 100).

Light targets (verified): `backend/app/analytics/risk.py` already imports `math` (line 10), `numpy as np` (line 14), `pandas as pd` (line 15), `reject_nan, to_date` (line 17), `align_returns` (line 18), and defines `_MIN_TAIL_POINTS = 10` (line 20). `backend/app/analytics/portfolio.py` already imports `math` (line 40), `Mapping` (line 41), `numpy as np` (line 43), `pandas as pd` (line 44), and defines `risk_contributions` (lines 244-280). `_MIN_TAIL_POINTS` is re-exported from `__init__.py` as `MIN_IN_RANGE_RETURNS` (lines 27-29). The shared guard `reject_nan` is in `backend/app/analytics/_validation.py` (lines 25-39).

Tasks are ordered by dependency: the three ratios (T1A-1..3) and ENB (T1A-4) are pure-analytics; T1A-5 wires all four into the portfolio-analysis assembler; active_share (T1A-6) is a standalone module (no auto-wiring — see open_questions); T1A-7 wires Sharpe/Sortino into the ScenarioStatistics schema; T1A-8 is the regression gate.

---

### Task T1A-1: `sharpe_ratio` pure function in `app/analytics/risk.py`

**Files:**
- Modify: `backend/app/analytics/risk.py` (add `DEFAULT_RISK_FREE_RATE`, `_MIN_RATIO_POINTS` after the `_MIN_TAIL_POINTS = 10` line at line 20; add `sharpe_ratio` after `annualized_volatility` which ends at line 61)
- Modify: `backend/app/analytics/__init__.py` (export `sharpe_ratio`, `DEFAULT_RISK_FREE_RATE`)
- Test: `backend/tests/test_analytics_risk.py` (append; the helpers `_dated` lines 20-21 and `_random_returns` lines 24-26 already exist, and `math`/`np`/`pd`/`pytest` are imported at lines 3-7)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_risk.py`:

```python
# --- Sharpe ratio (T1A-1) ----------------------------------------------------

from app.analytics import DEFAULT_RISK_FREE_RATE, sharpe_ratio  # noqa: E402


def test_sharpe_ratio_matches_manual_formula() -> None:
    """sharpe = mean(excess)/std(excess, ddof=1) * sqrt(252), excess = r - rf/252."""
    returns = _random_returns(252, seed=11)
    rf = 0.04
    excess = returns.to_numpy(dtype=float) - rf / 252
    expected = float(np.mean(excess) / np.std(excess, ddof=1) * math.sqrt(252))
    assert sharpe_ratio(returns, risk_free_rate=rf) == pytest.approx(expected, rel=1e-12)


def test_sharpe_ratio_default_rf_is_canonical() -> None:
    assert DEFAULT_RISK_FREE_RATE == 0.04
    returns = _random_returns(252, seed=12)
    assert sharpe_ratio(returns) == pytest.approx(
        sharpe_ratio(returns, risk_free_rate=0.04), rel=1e-12
    )


def test_sharpe_ratio_higher_for_higher_mean() -> None:
    base = _random_returns(252, seed=13)
    shifted = base + 0.001  # shift mean up, same vol
    assert sharpe_ratio(shifted) > sharpe_ratio(base)


def test_sharpe_ratio_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        sharpe_ratio(_dated([0.01] * 9))


def test_sharpe_ratio_zero_vol_raises() -> None:
    with pytest.raises(ValueError, match="zero volatility|undefined"):
        sharpe_ratio(_dated([0.01] * 30))


def test_sharpe_ratio_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        sharpe_ratio(_dated([0.01, np.nan, 0.02] * 5))
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k sharpe_ratio -v`. Expected failure: `ImportError: cannot import name 'sharpe_ratio' from 'app.analytics'` (the function and the `DEFAULT_RISK_FREE_RATE` export do not exist yet).

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/analytics/risk.py`, immediately after the `_MIN_TAIL_POINTS = 10` line (line 20) add the module constants:

```python
# Canonical annual risk-free rate (matches the worker risk_metrics rf handling
# and the legacy return_statistics_service.DEFAULT_RISK_FREE_RATE = 0.04). Used
# when a request carries no explicit rate.
DEFAULT_RISK_FREE_RATE = 0.04

# Risk-adjusted ratios need a meaningful sample; reuse the tail-points floor.
_MIN_RATIO_POINTS = _MIN_TAIL_POINTS
```

  Then after `annualized_volatility` (ends line 61) add:

```python
def sharpe_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = 252,
) -> float:
    """Annualized Sharpe ratio of a daily return series.

    ``excess = returns - risk_free_rate / periods_per_year``; the ratio is
    ``mean(excess) / std(excess, ddof=1) * sqrt(periods_per_year)`` — the
    canonical arithmetic-mean daily-excess form used by the risk_metrics
    worker and the legacy return_statistics_service. Inputs and ``risk_free_rate``
    are decimal fractions (0.04 = 4%), never 0-100; the result is unitless.

    Raises:
        ValueError: if fewer than 10 returns are supplied, the input contains
            NaN/inf values, or the excess-return volatility is 0 (Sharpe
            undefined for a constant series).
    """
    if len(returns) < _MIN_RATIO_POINTS:
        raise ValueError(
            f"sharpe_ratio requires at least {_MIN_RATIO_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "sharpe_ratio")
    excess = returns.to_numpy(dtype=float) - risk_free_rate / periods_per_year
    vol = float(np.std(excess, ddof=1))
    if vol == 0:
        raise ValueError("sharpe_ratio is undefined: zero volatility (constant series)")
    return float(np.mean(excess) / vol * math.sqrt(periods_per_year))
```

  Then in `backend/app/analytics/__init__.py` add `DEFAULT_RISK_FREE_RATE,` and `sharpe_ratio,` to the `from app.analytics.risk import (...)` block (the multi-name block at lines 30-40) and to `__all__` (insert `"DEFAULT_RISK_FREE_RATE",` after `"DEFAULT_INITIAL_NAV",` at line 49, and `"sharpe_ratio",` after `"risk_contributions",` at line 69).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k sharpe_ratio -v`. Expected: 6 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/risk.py app/analytics/__init__.py tests/test_analytics_risk.py` then commit with message: `feat(analytics): add annualized sharpe_ratio pure function (T1A-1)`.

---

### Task T1A-2: `sortino_ratio` pure function in `app/analytics/risk.py`

**Files:**
- Modify: `backend/app/analytics/risk.py` (add `sortino_ratio` immediately after `sharpe_ratio`)
- Modify: `backend/app/analytics/__init__.py` (export `sortino_ratio`)
- Test: `backend/tests/test_analytics_risk.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_risk.py`:

```python
# --- Sortino ratio (T1A-2) ---------------------------------------------------

from app.analytics import sortino_ratio  # noqa: E402


def test_sortino_ratio_matches_manual_formula() -> None:
    """sortino = mean(excess)/TDD * sqrt(252); TDD = sqrt(mean(min(excess,0)^2))."""
    returns = _random_returns(252, seed=21)
    rf = 0.04
    excess = returns.to_numpy(dtype=float) - rf / 252
    shortfall = np.minimum(excess, 0.0)
    tdd = float(np.sqrt(np.mean(shortfall**2)))
    expected = float(np.mean(excess) / tdd * math.sqrt(252))
    assert sortino_ratio(returns, risk_free_rate=rf) == pytest.approx(expected, rel=1e-12)


def test_sortino_ratio_ge_sharpe_for_this_seed() -> None:
    """For seed=22 (positive-Sharpe series) the Target Downside Deviation is
    below the total excess std, so Sortino > Sharpe. This is NOT a universal
    property (it inverts for negative-mean series), hence the fixed seed."""
    returns = _random_returns(252, seed=22)
    assert sortino_ratio(returns) >= sharpe_ratio(returns) - 1e-9


def test_sortino_ratio_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        sortino_ratio(_dated([0.01] * 9))


def test_sortino_ratio_no_downside_raises() -> None:
    """All-positive excess => TDD == 0 => undefined (fail loud, never inf/NaN)."""
    with pytest.raises(ValueError, match="downside|undefined"):
        sortino_ratio(_dated([0.05] * 30))  # 0.05 > rf/252, no shortfall


def test_sortino_ratio_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        sortino_ratio(_dated([0.01, np.nan, -0.02] * 5))
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k sortino_ratio -v`. Expected failure: `ImportError: cannot import name 'sortino_ratio' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/analytics/risk.py`, immediately after `sharpe_ratio` add:

```python
def sortino_ratio(
    returns: pd.Series,
    risk_free_rate: float = DEFAULT_RISK_FREE_RATE,
    periods_per_year: int = 252,
) -> float:
    """Annualized Sortino ratio with canonical Target Downside Deviation.

    ``excess = returns - risk_free_rate / periods_per_year``; the denominator is
    the Target Downside Deviation ``TDD = sqrt(mean(min(excess, 0)**2))`` over
    the FULL sample (N denominator, matching the risk_metrics worker and the
    legacy return_statistics_service). The ratio is
    ``mean(excess) / TDD * sqrt(periods_per_year)``. Inputs are decimal
    fractions (0.04 = 4%), never 0-100; the result is unitless.

    Raises:
        ValueError: if fewer than 10 returns are supplied, the input contains
            NaN/inf values, or there is no downside (TDD == 0), which leaves the
            ratio undefined.
    """
    if len(returns) < _MIN_RATIO_POINTS:
        raise ValueError(
            f"sortino_ratio requires at least {_MIN_RATIO_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "sortino_ratio")
    excess = returns.to_numpy(dtype=float) - risk_free_rate / periods_per_year
    shortfall = np.minimum(excess, 0.0)
    tdd = float(np.sqrt(np.mean(shortfall**2)))
    if tdd == 0:
        raise ValueError(
            "sortino_ratio is undefined: no downside (target downside deviation is 0)"
        )
    return float(np.mean(excess) / tdd * math.sqrt(periods_per_year))
```

  Then in `backend/app/analytics/__init__.py` add `sortino_ratio,` to the risk import block and `"sortino_ratio",` to `__all__` (insert after `"simple_returns",` at line 73).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k sortino_ratio -v`. Expected: 5 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/risk.py app/analytics/__init__.py tests/test_analytics_risk.py` then commit: `feat(analytics): add annualized sortino_ratio pure function (T1A-2)`.

---

### Task T1A-3: `information_ratio` pure function in `app/analytics/risk.py`

**Files:**
- Modify: `backend/app/analytics/risk.py` (add `information_ratio` after `sortino_ratio`; uses `align_returns` already imported at line 18 and `_MIN_TAIL_POINTS` at line 20)
- Modify: `backend/app/analytics/__init__.py` (export `information_ratio`)
- Test: `backend/tests/test_analytics_risk.py` (append)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_risk.py`:

```python
# --- Information ratio (T1A-3) -----------------------------------------------

from app.analytics import information_ratio  # noqa: E402


def test_information_ratio_matches_manual_formula() -> None:
    """IR = mean(active)*252 / (std(active, ddof=1)*sqrt(252)), active = p - b."""
    port = _random_returns(252, seed=31)
    bench = _random_returns(252, seed=32)
    active = (port - bench).to_numpy(dtype=float)
    te = float(np.std(active, ddof=1) * math.sqrt(252))
    expected = float(np.mean(active) * 252 / te)
    assert information_ratio(port, bench) == pytest.approx(expected, rel=1e-12)


def test_information_ratio_identical_series_raises() -> None:
    """Identical series => zero active return AND zero tracking error => undefined."""
    bench = _random_returns(252, seed=33)
    with pytest.raises(ValueError, match="tracking error|undefined"):
        information_ratio(bench, bench)


def test_information_ratio_inner_joins_on_common_dates() -> None:
    """A benchmark carrying one EXTRA leading date is inner-joined away; the IR
    must equal the IR computed on the already-overlapping window."""
    port = _random_returns(60, seed=34)
    bench = _random_returns(60, seed=35)
    # Prepend one out-of-grid leading observation to the benchmark only; the
    # inner join must drop it so both runs see the same 60 overlapping dates.
    extra_date = port.index[0] - pd.Timedelta(days=1)
    bench_extra = pd.concat([pd.Series([0.123], index=[extra_date]), bench])
    assert information_ratio(port, bench_extra) == pytest.approx(
        information_ratio(port, bench), rel=1e-12
    )


def test_information_ratio_short_overlap_raises() -> None:
    port = _dated([0.01, -0.02, 0.015, 0.0, -0.01], start="2024-01-01")
    bench = _dated([0.005, -0.01, 0.02, 0.001, -0.005], start="2024-01-01")
    with pytest.raises(ValueError, match="at least 10"):
        information_ratio(port, bench)


def test_information_ratio_nan_input_raises() -> None:
    port = _dated([0.01, np.nan, -0.02] * 5)
    bench = _random_returns(15, seed=36)
    with pytest.raises(ValueError, match="NaN|overlapping"):
        information_ratio(port, bench)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k information_ratio -v`. Expected failure: `ImportError: cannot import name 'information_ratio' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/analytics/risk.py`, after `sortino_ratio` add (note: `align_returns` is already imported at line 18 and inner-joins + drops NaN rows, raising on < 2 overlap; `_MIN_TAIL_POINTS` at line 20):

```python
def information_ratio(
    portfolio_returns: pd.Series,
    benchmark_returns: pd.Series,
    periods_per_year: int = 252,
) -> float:
    """Annualized Information Ratio of active returns vs a benchmark.

    Series are aligned first (inner join, NaNs dropped). With
    ``active = portfolio - benchmark``, the tracking error is
    ``TE = std(active, ddof=1) * sqrt(periods_per_year)`` and
    ``IR = mean(active) * periods_per_year / TE`` — the active-return form used
    by the risk_metrics worker's regression_metrics. The risk-free rate does
    not appear (it cancels in the active return). Inputs are decimal fractions
    (0.05 = 5%), never 0-100; the result is unitless.

    Raises:
        ValueError: if fewer than 10 aligned points remain, the inputs contain
            NaN/inf values (propagated from align_returns), or the tracking
            error is 0 (IR undefined when the portfolio tracks the benchmark
            exactly).
    """
    p, b = align_returns(portfolio_returns, benchmark_returns)
    if len(p) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"information_ratio requires at least {_MIN_TAIL_POINTS} common points, got {len(p)}"
        )
    active = p.to_numpy(dtype=float) - b.to_numpy(dtype=float)
    te = float(np.std(active, ddof=1) * math.sqrt(periods_per_year))
    if te == 0:
        raise ValueError("information_ratio is undefined: zero tracking error")
    return float(np.mean(active) * periods_per_year / te)
```

  Note on the NaN test: `align_returns` (`backend/app/analytics/returns.py` lines 63-78) drops NaN rows in its inner join, so a portfolio series with a NaN loses that row; with 15 input returns and one NaN dropped, fewer than 10 of the 5-period repeat pattern may overlap — either branch ("at least 10 common points" or align_returns' "at least 2 overlapping") satisfies the test regex `match="NaN|overlapping"`. If overlap stays >= 10, the residual NaN is impossible because align_returns already dropped it; the test passes via the overlap-count path. (The regex tolerates both outcomes; do not add a separate reject_nan call — it would change which message is raised.)

  Then in `backend/app/analytics/__init__.py` add `information_ratio,` to the risk import block and `"information_ratio",` to `__all__` (insert after `"historical_var",` at line 63).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py -k information_ratio -v`. Expected: 5 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/risk.py app/analytics/__init__.py tests/test_analytics_risk.py` then commit: `feat(analytics): add annualized information_ratio pure function (T1A-3)`.

---

### Task T1A-4: `effective_number_of_bets` entropy ENB over risk contributions

**Files:**
- Modify: `backend/app/analytics/portfolio.py` (add `effective_number_of_bets` after `risk_contributions` which ends at line 280, before `diversification_ratio` at line 283; `math` line 40, `Mapping` line 41, `numpy as np` line 43, `pandas as pd` line 44 already imported)
- Modify: `backend/app/analytics/__init__.py` (export `effective_number_of_bets`)
- Test: `backend/tests/test_analytics_portfolio.py` (append; helpers `_price_frame` lines 31-34, `_seeded_prices` lines 37-44, `_orthogonal_returns` lines 47-57 already exist, and `risk_contributions`/`np`/`pd`/`pytest` are imported at the top)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_analytics_portfolio.py`:

```python
# --- Effective Number of Bets (entropy ENB) (T1A-4) --------------------------

from app.analytics import effective_number_of_bets  # noqa: E402


def test_enb_equals_n_for_equal_risk_contributions() -> None:
    """When every asset contributes equal risk, ENB == number of assets.

    _orthogonal_returns gives two zero-covariance columns; at equal vol and
    equal weights the two risk contributions are equal (0.5 each), so the
    entropy ENB exp(-sum p ln p) for p=1/2 is exactly 2.
    """
    returns = _orthogonal_returns(0.01, 0.01, blocks=5)  # 2 assets, equal vol
    weights = {"A": 0.5, "B": 0.5}
    assert effective_number_of_bets(returns, weights) == pytest.approx(2.0, rel=1e-9)


def test_enb_below_n_for_concentrated_risk() -> None:
    """Unequal risk contributions => ENB strictly below the asset count."""
    returns = _orthogonal_returns(0.03, 0.005, blocks=5)  # very unequal vol
    weights = {"A": 0.5, "B": 0.5}
    enb = effective_number_of_bets(returns, weights)
    assert 1.0 <= enb < 2.0


def test_enb_matches_entropy_of_risk_contributions() -> None:
    """ENB must equal exp(-sum RC_i ln RC_i) over risk_contributions() output."""
    returns = _seeded_prices(["A", "B", "C"], periods=120, seed=5).pct_change().dropna()
    weights = {"A": 0.4, "B": 0.35, "C": 0.25}
    rc = risk_contributions(returns, weights)
    rc_arr = np.array(list(rc.values()), dtype=float)
    rc_pos = np.where(rc_arr > 0.0, rc_arr, 0.0)
    rc_norm = rc_pos / rc_pos.sum()
    mask = rc_norm > 0.0
    expected = float(np.exp(-np.sum(rc_norm[mask] * np.log(rc_norm[mask]))))
    assert effective_number_of_bets(returns, weights) == pytest.approx(expected, rel=1e-9)


def test_enb_short_input_raises() -> None:
    one_row = _price_frame({"A": [100.0, 101.0], "B": [50.0, 50.5]}).pct_change().dropna()
    with pytest.raises(ValueError, match="at least 2"):
        effective_number_of_bets(one_row, {"A": 0.5, "B": 0.5})


def test_enb_bad_weights_raises() -> None:
    returns = _orthogonal_returns(0.01, 0.01, blocks=5)
    with pytest.raises(ValueError, match="sum to 1|long-only"):
        effective_number_of_bets(returns, {"A": 0.5, "B": 0.4})  # sums to 0.9
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_portfolio.py -k enb -v`. Expected failure: `ImportError: cannot import name 'effective_number_of_bets' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/analytics/portfolio.py`, after `risk_contributions` (ends line 280) and before `diversification_ratio` (line 283) add:

```python
def effective_number_of_bets(
    returns: pd.DataFrame, weights: Mapping[str, float]
) -> float:
    """Entropy Effective Number of Bets over the covariance risk contributions.

    Reuses :func:`risk_contributions` (the CTR decomposition that sums to 1) and
    applies the Meucci (2009) entropy diversification measure
    ``ENB = exp(-Sum RC_i ln RC_i)``. Tiny negative CTRs from floating-point
    noise are floored at 0 and the survivors renormalized before the entropy so
    ``ENB`` is bounded in ``[1, n_assets]``: ``n_assets`` when every asset
    contributes equal risk, near 1 when one asset dominates. Unitless.

    Raises:
        ValueError: if the returns frame has NaN or fewer than 2 rows, or the
            weights fail the engine guard (exact keys, each > 0, sum == 1
            within 1e-6) — propagated unchanged from :func:`risk_contributions`;
            also if all risk contributions floor to a non-positive total.
    """
    contributions = risk_contributions(returns, weights)
    rc = np.array(list(contributions.values()), dtype=float)
    rc_pos = np.where(rc > 0.0, rc, 0.0)
    total = float(rc_pos.sum())
    if total <= 0.0:
        raise ValueError(
            "effective_number_of_bets is undefined: non-positive risk contributions"
        )
    rc_norm = rc_pos / total
    # log(0) is guarded by the rc_norm>0 mask: zero-contribution terms add 0
    # (lim p->0 of p ln p = 0), so restrict the entropy sum to positives.
    mask = rc_norm > 0.0
    entropy = -float(np.sum(rc_norm[mask] * np.log(rc_norm[mask])))
    return float(np.exp(entropy))
```

  Then in `backend/app/analytics/__init__.py` add `effective_number_of_bets,` to the `from app.analytics.portfolio import (...)` block (lines 9-20) and `"effective_number_of_bets",` to `__all__` (insert after `"diversification_ratio",` at line 61).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_portfolio.py -k enb -v`. Expected: 5 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/portfolio.py app/analytics/__init__.py tests/test_analytics_portfolio.py` then commit: `feat(analytics): add entropy effective_number_of_bets over risk contributions (T1A-4)`.

---

### Task T1A-5: Wire Sharpe/Sortino/IR + ENB into `PortfolioStats` and the portfolio-analysis assembler

**Files:**
- Modify: `backend/app/schemas/portfolio_analysis.py` (`PortfolioStats` lines 220-260 — add four fields after `diversification_ratio` which ends line 257, before `max_drawdown: DrawdownOut` at line 258)
- Modify: `backend/app/services/portfolio_analysis.py` (import block lines 28-49; `PortfolioStats(...)` construction lines 317-333)
- Test: `backend/tests/test_portfolio_analysis_service.py` (append; helpers `_default_inputs` lines 24-27 and `_assemble` lines 30-44 already exist; `np`/`pd`/`pytest` imported at lines 3-5)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_portfolio_analysis_service.py`:

```python
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
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_portfolio_analysis_service.py -k "sharpe_sortino_ir_enb or enb_matches_engine" -v`. Expected failure: `pydantic_core.ValidationError` / `AttributeError` — `PortfolioStats` has no `sharpe_ratio` / `sortino_ratio` / `information_ratio` / `effective_number_of_bets` fields yet.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/schemas/portfolio_analysis.py`, inside `PortfolioStats`, immediately after the `diversification_ratio` field (ends line 257) and before `max_drawdown: DrawdownOut` (line 258) add:

```python
    sharpe_ratio: float = Field(
        description="Annualized Sharpe ratio of the replayed portfolio's daily returns "
        "at the canonical 4% risk-free rate (unitless)."
    )
    sortino_ratio: float = Field(
        description="Annualized Sortino ratio (Target Downside Deviation denominator) at "
        "the canonical 4% risk-free rate (unitless)."
    )
    information_ratio: float = Field(
        description="Annualized information ratio of the portfolio's active return vs the "
        "benchmark over the aligned daily grid (unitless)."
    )
    effective_number_of_bets: float = Field(
        description="Entropy Effective Number of Bets over the per-asset risk contributions "
        "at the effective initial weights; in [1, n_positions] (unitless)."
    )
```

  In `backend/app/services/portfolio_analysis.py` add the four names to the `from app.analytics import (...)` block (lines 28-49), keeping the alphabetical order of that block: `effective_number_of_bets,` (after `diversification_ratio,` line 38), `information_ratio,` (after `historical_var,` line 40), `sharpe_ratio,` (after `risk_contributions,` line 45), `sortino_ratio,` (after `simple_returns,` line 46). Then extend the `stats = PortfolioStats(...)` construction (lines 317-333) by adding, after the `diversification_ratio=diversification_ratio(returns_frame, effective_weights),` line (line 325):

```python
        sharpe_ratio=sharpe_ratio(port_returns),
        sortino_ratio=sortino_ratio(port_returns),
        information_ratio=information_ratio(aligned_port, aligned_bench),
        effective_number_of_bets=effective_number_of_bets(
            returns_frame, effective_weights
        ),
```

  All five referenced locals are already in scope at line 325 (verified): `port_returns` (line 235), `aligned_port`/`aligned_bench` (line 247), `returns_frame` (line 311), `effective_weights` (line 217).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_portfolio_analysis_service.py -v`. Expected: all existing tests plus the 2 new ones pass (the new fields are additive; existing assertions are unaffected).

- [ ] **Step 5: Commit.** `cd backend && git add app/schemas/portfolio_analysis.py app/services/portfolio_analysis.py tests/test_portfolio_analysis_service.py` then commit: `feat(portfolio-analysis): expose sharpe/sortino/IR + ENB in PortfolioStats (T1A-5)`.

---

### Task T1A-6: `active_share` pure function in new `app/analytics/active_share.py`

**Files:**
- Create: `backend/app/analytics/active_share.py`
- Modify: `backend/app/analytics/__init__.py` (export `active_share`)
- Test: `backend/tests/test_analytics_active_share.py` (new file)

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_analytics_active_share.py`:

```python
"""Tests for app.analytics.active_share."""

import pytest

from app.analytics import active_share


def test_active_share_identical_portfolios_is_zero() -> None:
    weights = {"AAPL": 0.5, "MSFT": 0.5}
    assert active_share(weights, weights) == pytest.approx(0.0, abs=1e-12)


def test_active_share_disjoint_portfolios_is_one() -> None:
    """No overlap => 0.5 * (sum|p| + sum|b|) = 0.5 * (1 + 1) = 1.0 (decimal)."""
    portfolio = {"AAPL": 0.6, "MSFT": 0.4}
    benchmark = {"GOOG": 0.7, "AMZN": 0.3}
    assert active_share(portfolio, benchmark) == pytest.approx(1.0, rel=1e-12)


def test_active_share_matches_half_sum_abs_diff() -> None:
    portfolio = {"AAPL": 0.5, "MSFT": 0.3, "TSLA": 0.2}
    benchmark = {"AAPL": 0.4, "MSFT": 0.4, "GOOG": 0.2}
    # union ids: AAPL |0.5-0.4|=0.1, MSFT |0.3-0.4|=0.1, TSLA |0.2-0|=0.2,
    # GOOG |0-0.2|=0.2 => sum=0.6 => active_share = 0.3
    assert active_share(portfolio, benchmark) == pytest.approx(0.3, rel=1e-12)


def test_active_share_is_decimal_fraction_in_unit_range() -> None:
    portfolio = {"AAPL": 0.9, "MSFT": 0.1}
    benchmark = {"AAPL": 0.1, "MSFT": 0.9}
    result = active_share(portfolio, benchmark)
    assert 0.0 <= result <= 1.0


def test_active_share_empty_portfolio_raises() -> None:
    with pytest.raises(ValueError, match="empty|at least one"):
        active_share({}, {"AAPL": 1.0})


def test_active_share_empty_benchmark_raises() -> None:
    with pytest.raises(ValueError, match="empty|at least one"):
        active_share({"AAPL": 1.0}, {})


def test_active_share_weight_sum_out_of_range_raises() -> None:
    with pytest.raises(ValueError, match="sum to 1"):
        active_share({"AAPL": 0.5, "MSFT": 0.2}, {"AAPL": 1.0})  # portfolio sums 0.7


def test_active_share_nan_weight_raises() -> None:
    with pytest.raises(ValueError, match="finite|NaN"):
        active_share({"AAPL": float("nan"), "MSFT": 0.5}, {"AAPL": 1.0})
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_analytics_active_share.py -v`. Expected failure: `ImportError: cannot import name 'active_share' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/analytics/active_share.py`:

```python
"""Active Share over look-through weights vs a benchmark.

Active Share (Cremers & Petajisto 2009; eVestment p.73, ported from
quant_engine.active_share_service) measures how much a portfolio's holdings
differ from a benchmark's:

    active_share = 0.5 * sum(|w_portfolio,i - w_benchmark,i|)  over the union
                   of position identifiers.

Scale contract (project-wide): both weight maps are decimal fractions
(0.5 = 50%), and the RESULT is a decimal fraction in [0, 1] (1.0 = 100% active,
no overlap with the benchmark) — NOT the 0-100 scale of the legacy
quant_engine.active_share_service (which multiplies by 100). Both maps must
already be normalized to sum to 1 within tolerance; this function fails loud
rather than silently rescaling.
"""

import math
from collections.abc import Mapping

# Matches the legacy active_share_service._WEIGHT_SUM_TOL (= 0.05): look-through
# weights rarely sum to exactly 1, so a 5% tolerance is permitted before failing.
_WEIGHT_SUM_TOL = 0.05


def _check_weights(weights: Mapping[str, float], name: str) -> None:
    if not weights:
        raise ValueError(
            f"active_share requires at least one {name} position (got empty)"
        )
    for ticker, weight in weights.items():
        if not math.isfinite(weight):
            raise ValueError(
                f"active_share {name} weights must be finite; {ticker}={weight}"
            )
    total = float(sum(weights.values()))
    if abs(total - 1.0) > _WEIGHT_SUM_TOL:
        raise ValueError(
            f"active_share {name} weights must sum to 1 within {_WEIGHT_SUM_TOL}, got {total}"
        )


def active_share(
    portfolio_weights: Mapping[str, float],
    benchmark_weights: Mapping[str, float],
) -> float:
    """Active Share of look-through weights against a benchmark.

    ``active_share = 0.5 * Sum|w_p,i - w_b,i|`` over the union of identifiers, in
    decimal fractions (0.0 = identical to benchmark, 1.0 = fully active). Both
    inputs are decimal-fraction weight maps that must each sum to 1 within 0.05.

    Raises:
        ValueError: if either map is empty, any weight is NaN/inf, or either
            map's weights do not sum to 1 within tolerance.
    """
    _check_weights(portfolio_weights, "portfolio")
    _check_weights(benchmark_weights, "benchmark")
    all_ids = set(portfolio_weights) | set(benchmark_weights)
    total_diff = 0.0
    for identifier in all_ids:
        w_p = float(portfolio_weights.get(identifier, 0.0))
        w_b = float(benchmark_weights.get(identifier, 0.0))
        total_diff += abs(w_p - w_b)
    result = total_diff / 2.0
    # Clamp residual float noise into [0, 1] (the math already guarantees it,
    # but a defensive clamp keeps the contract exact).
    return min(max(result, 0.0), 1.0)
```

  Then in `backend/app/analytics/__init__.py` add an import line after the portfolio import block (after line 20):

```python
from app.analytics.active_share import active_share
```

  and add `"active_share",` to `__all__` (insert after `"align_returns",` at line 53).

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_active_share.py -v`. Expected: 8 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/analytics/active_share.py app/analytics/__init__.py tests/test_analytics_active_share.py` then commit: `feat(analytics): add active_share pure function over lookthrough weights (T1A-6)`.

---

### Task T1A-7: Wire Sharpe/Sortino into `ScenarioStatistics` and the scenario assembler

**Files:**
- Modify: `backend/app/schemas/statistics.py` (`ScenarioStatistics` lines 143-164 — add two fields after the `var_99` field which ends line 164)
- Modify: `backend/app/services/statistics.py` (import block lines 36-52; `_build_stats` inner `ScenarioStatistics(...)` construction lines 392-404)
- Test: `backend/tests/test_statistics_service.py` (append; helpers `_series_map` lines 53-54, `QUANTITIES` line 57, `MAX_POINTS` line 42, `assemble_scenario` imported line 36, `join_prices` imported line 32, `simple_returns`/`nav_by_position` available via the app.analytics import block — see below)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_statistics_service.py`:

```python
# --- Sharpe/Sortino in ScenarioStatistics (T1A-7) ----------------------------

from app.analytics import nav_by_position, sharpe_ratio, sortino_ratio  # noqa: E402


def test_scenario_statistics_carry_sharpe_sortino() -> None:
    series = _series_map(300)
    resp = assemble_scenario(
        series,
        portfolio_id=1,
        name="Test",
        quantities=QUANTITIES,
        cash=0.0,
        max_points=MAX_POINTS,
    )
    stats = resp.statistics
    assert stats.sharpe_ratio == stats.sharpe_ratio  # not NaN
    assert stats.sortino_ratio == stats.sortino_ratio  # not NaN


def test_scenario_statistics_sharpe_matches_engine_on_total_returns() -> None:
    series = _series_map(300)
    resp = assemble_scenario(
        series,
        portfolio_id=1,
        name="Test",
        quantities=QUANTITIES,
        cash=0.0,
        max_points=MAX_POINTS,
    )
    # Rebuild the cash-inclusive total daily returns the assembler computes:
    # values = nav_by_position(prices, quantities); total = values.sum(axis=1) + cash.
    prices = join_prices(series)
    total = nav_by_position(prices, QUANTITIES).sum(axis=1) + 0.0
    total_returns = simple_returns(total)
    assert resp.statistics.sharpe_ratio == pytest.approx(
        sharpe_ratio(total_returns), rel=1e-9
    )
    assert resp.statistics.sortino_ratio == pytest.approx(
        sortino_ratio(total_returns), rel=1e-9
    )
```

  Note: `nav_by_position` is the exact engine the assembler uses (`backend/app/services/statistics.py` line 343: `values = nav_by_position(prices, quantities)`), and `simple_returns`/`join_prices` are already imported in this test module (lines 25 and 32). Importing `nav_by_position`/`sharpe_ratio`/`sortino_ratio` here is additive.

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_statistics_service.py -k "carry_sharpe_sortino or sharpe_matches_engine" -v`. Expected failure: `pydantic_core.ValidationError` / `AttributeError` — `ScenarioStatistics` has no `sharpe_ratio` / `sortino_ratio` fields.

- [ ] **Step 3: Write the minimal implementation.** In `backend/app/schemas/statistics.py`, inside `ScenarioStatistics`, after the `var_99` field (ends line 164) add:

```python
    sharpe_ratio: float = Field(
        description="Annualized Sharpe ratio of the cash-inclusive total's daily returns "
        "at the canonical 4% risk-free rate (unitless)."
    )
    sortino_ratio: float = Field(
        description="Annualized Sortino ratio (Target Downside Deviation denominator) of "
        "the cash-inclusive total's daily returns at the canonical 4% risk-free rate "
        "(unitless)."
    )
```

  In `backend/app/services/statistics.py` add `sharpe_ratio,` and `sortino_ratio,` to the `from app.analytics import (...)` block (lines 36-52) keeping its alphabetical order: insert `sharpe_ratio,` after `return_histogram,` (line 48) and `sortino_ratio,` after `simple_returns,` (line 50). Then in `_build_stats` extend the `ScenarioStatistics(...)` construction (lines 392-404) by adding, after the `var_99=historical_var(total_returns, confidence=0.99),` line (line 403):

```python
            sharpe_ratio=sharpe_ratio(total_returns),
            sortino_ratio=sortino_ratio(total_returns),
```

  `total_returns` is in scope at line 377; the whole `_build_stats` block is already wrapped by `_engine(_build_stats)` at line 411, so any `ValueError` from a zero-variance/no-downside total maps to the existing 422 `InsufficientDataError` contract — no extra error handling needed.

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_statistics_service.py -v`. Expected: all existing tests plus the 2 new ones pass.

- [ ] **Step 5: Commit.** `cd backend && git add app/schemas/statistics.py app/services/statistics.py tests/test_statistics_service.py` then commit: `feat(statistics): expose sharpe/sortino in ScenarioStatistics (T1A-7)`.

---

### Task T1A-8: Full-suite regression gate

**Files:**
- Test: (no new files — runs the affected suites together)

- [ ] **Step 1: Run the analytics + service suites together, expect PASS.** Command: `cd backend && python -m pytest tests/test_analytics_risk.py tests/test_analytics_portfolio.py tests/test_analytics_active_share.py tests/test_portfolio_analysis_service.py tests/test_statistics_service.py -v`. Expected: all green (existing + new tests). This confirms the additive schema fields did not break the route/assembly tests and the new pure functions integrate cleanly.

- [ ] **Step 2: Run the route smoke tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_portfolio_route.py tests/test_statistics_routes.py -v`. Expected: all green — the new response fields serialize through the OpenAPI layer without contract violations. (Both files exist: `backend/tests/test_portfolio_route.py`, `backend/tests/test_statistics_routes.py`.)

- [ ] **Step 3: Commit (only if any incidental snapshot/fixture updates were needed).** If the route tests required no changes, skip this commit. Otherwise `cd backend && git add -A tests/` and commit: `test(tier1): regression-gate sharpe/sortino/IR/ENB/active-share wiring (T1A-8)`.

---

## Tier 1 — Fixed-income & alternatives regression metrics (empirical duration, credit beta, inflation beta, crisis alpha) [repo: investintell-datalake-workers]

This cluster ports four return-based regression metrics from the LEGACY `quant_engine` services into the **investintell-datalake-workers** `risk_metrics` worker, persists them into the existing `fund_risk_metrics` table, and exposes them in the LIGHT `FundRiskOut` schema (the columns that exist in the legacy migrations 0123/0125 but were never wired into the data-lake worker nor the dynamic catalog).

The four metrics (rank 4):
- **empirical_duration** = `-beta` of OLS(fund daily returns vs ΔDGS10) — sensitivity to Treasury-yield changes (legacy `compute_empirical_duration`, `E:/investintell-allocation/backend/quant_engine/fixed_income_analytics_service.py:57`).
- **credit_beta** = `-beta` of OLS(fund daily returns vs ΔBAA10Y) — sensitivity to credit-spread changes (legacy `compute_credit_beta`, `fixed_income_analytics_service.py:87`).
- **inflation_beta** = `+beta` of OLS(fund MONTHLY returns vs monthly ΔCPIAUCSL) — inflation-hedge sensitivity (legacy `compute_inflation_beta`, `E:/investintell-allocation/backend/quant_engine/alternatives_analytics_service.py:182`).
- **crisis_alpha_score** = fund cumulative return − benchmark cumulative return on benchmark-drawdown days < −10% (legacy `compute_crisis_alpha`, `alternatives_analytics_service.py:131`).

Each FI metric also carries its R² (`empirical_duration_r2`, `credit_beta_r2`, `inflation_beta_r2`) gated by the legacy `min_r_squared` / `inflation_min_r2` floors. `scoring_model` tags the pass that produced the row (`'fixed_income'` / `'alternatives'` / `'equity'` / `'cash'`), mirroring legacy `risk_calc.py` (`E:/investintell-allocation/backend/app/jobs/workers/risk_calc.py:1962,2021,2092`).

**Data sources (verified):** `macro_data` is fed by the macro_ingestion worker, which registers `DGS10` (`src/workers/macro_ingestion.py:105`), `BAA10Y` (`:158`), `CPIAUCSL` (`:102`). Fund → `asset_class` is read from `instruments_universe.asset_class` (the worker already reads this table in `_fetch_fund_benchmarks` via `_FUND_BENCHMARKS_SQL`, `risk_metrics.py:367`). The coarse values are `'equity'`, `'fixed_income'`, `'cash'`, `'alternatives'` (the Light Fund/FundRiskLatest model documents 100% coverage of these four, `backend/app/models/fund.py:79`). NOTE: `'alternatives'` is NOT in `BENCHMARK_BY_ASSET_CLASS` (it maps only equity/fixed_income/cash, `risk_metrics.py:348-352`) — the new asset-class fetcher reads the raw `instruments_universe.asset_class`, not the benchmark map.

**Scale contract:** FRED yields are in PERCENT (4.25 = 4.25%); the legacy worker converts yield changes to decimal (`/100.0`) before regression (`risk_calc.py:485`, verbatim, with a forward-fill gap guard `> 7` days at `:484`). We reproduce both. CPI is an index level → MoM fractional change `(curr - prev) / prev` (legacy `_fetch_monthly_cpi_changes`, `risk_calc.py:1220`, guard `prev > 0` at `:1252`). All persisted metrics are decimal fractions; betas are dimensionless; `crisis_alpha_score` is a decimal return difference.

**Worker test harness (separate from light pytest):** the worker repo has NO `pyproject.toml`/`conftest.py`/`pytest.ini` (verified). Pure-function tests run with plain `pytest` from the repo root (`E:/investintell-datalake-workers`): `python -m pytest tests/test_risk_metrics.py::<name> -v` (imports `from src.workers import risk_metrics as rm`). DB-touching tests self-skip when Postgres is unreachable; the tests added here are PURE (synthetic numpy/date frames) and need no DB. The worker test module already imports `datetime as _dt` and `numpy as np` (`tests/test_risk_metrics.py:29,31`). The light pytest runs from `E:/investintell-light/backend` with `python -m pytest` (asyncio_mode=auto, testpaths=["tests"]).

---

### Task T1B-1: Add the regression-metric columns to the worker `fund_risk_metrics` schema

The data-lake schema file currently declares NONE of the FI/alt regression columns (only the peer/scoring `ALTER TABLE` block at lines 143-151). Add idempotent `ALTER TABLE ... ADD COLUMN IF NOT EXISTS` for the four metrics plus the three R² helpers and `scoring_model`, matching the mother-DB migration types EXACTLY (verified against `0123_add_fixed_income_risk_metrics.py:24-30` and `0125_add_alternatives_risk_metrics.py:26-32`). This must precede the worker code that upserts into them.

**Files:**
- Modify: `schemas/risk_metrics.sql` (append after the `equity_correlation_252d` ALTER at line 151)

Steps:

- [ ] **Step 1: Add the idempotent ALTER block.** Append the following to the END of `schemas/risk_metrics.sql` (after line 151):

```sql

-- ─────────────────────────────────────────────────────────────────────────────
-- Class-specific regression metrics (Tier 1, rank 4): fixed-income empirical
-- duration / credit beta and alternatives inflation beta / crisis alpha. Ported
-- from the mother-DB migrations 0123 (FI) and 0125 (alternatives). Computed by
-- the risk_metrics worker per fund using its instruments_universe.asset_class
-- and the macro_data series DGS10 / BAA10Y / CPIAUCSL. Types match the mother DB:
--   empirical_duration / credit_beta / inflation_beta : numeric(8,4)
--   *_r2                                               : numeric(6,4)
--   crisis_alpha_score                                 : numeric(10,6)
-- scoring_model tags the pass that produced the row (fixed_income / alternatives
-- / equity / cash), mirroring risk_calc.metrics["scoring_model"].
-- ─────────────────────────────────────────────────────────────────────────────
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS scoring_model text;
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS empirical_duration numeric(8,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS empirical_duration_r2 numeric(6,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS credit_beta numeric(8,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS credit_beta_r2 numeric(6,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS inflation_beta numeric(8,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS inflation_beta_r2 numeric(6,4);
ALTER TABLE fund_risk_metrics ADD COLUMN IF NOT EXISTS crisis_alpha_score numeric(10,6);
```

- [ ] **Step 2: Verify the SQL parses (no DB needed).** This is a DDL file applied with `psql -f`; there is no unit test. Confirm each appended line is a well-formed `ALTER TABLE` statement ending with `;`. No command runs here — the schema is exercised end-to-end by the worker against a real Postgres in deployment, and the pure-function tests below do not touch the DB. (Optional cloud check, requires creds: apply against Tiger and re-run — `IF NOT EXISTS` makes re-apply a no-op.)

- [ ] **Step 3: Commit.**
```bash
cd /e/investintell-datalake-workers && git add schemas/risk_metrics.sql && git commit -m "feat(risk_metrics): add FI/alt regression columns to fund_risk_metrics schema

empirical_duration, credit_beta, inflation_beta, crisis_alpha_score (+ R2
helpers and scoring_model), idempotent ALTER IF NOT EXISTS, types matching
the mother-DB migrations 0123/0125.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-2: Pure `empirical_duration` from dated fund returns vs ΔDGS10

Port `compute_empirical_duration` (legacy `fixed_income_analytics_service.py:57`, OLS `_ols_regression` at `:39`) as a self-contained function in the worker, taking date-aligned arrays. Worker style: pure module-level functions, `_clip`-style rounding (`risk_metrics.py:75`), returns `(value, r2)` tuple, `None` when insufficient or R² below threshold.

**Files:**
- Modify: `src/workers/risk_metrics.py` (add config constants + `_ols_beta_r2` + `empirical_duration` immediately AFTER `regression_metrics`, which ends at line 505, and BEFORE the `# Per-fund metric assembly` banner at line 508)
- Test: `tests/test_risk_metrics.py` (append; pure synthetic test)

Steps:

- [ ] **Step 1: Write the failing test.** Append to `tests/test_risk_metrics.py`:
```python
# ──────────────────────────────────────────────────────────────────────────────
# Class regression metrics (Tier 1, rank 4): empirical duration, credit beta,
# inflation beta, crisis alpha. Pure — synthetic dated frames, no DB.
# ──────────────────────────────────────────────────────────────────────────────
def test_empirical_duration_recovers_known_beta():
    """Fund return = -6 * delta_yield (+ tiny noise) → empirical_duration ≈ 6."""
    rng = np.random.default_rng(7)
    start = _dt.date(2023, 1, 2)
    n = 400
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    dy = rng.normal(0.0, 0.0005, n)          # daily yield change in DECIMAL (5bp sd)
    fund_ret = -6.0 * dy + rng.normal(0.0, 1e-5, n)
    fund_dated = list(zip(dates, fund_ret.tolist(), strict=True))
    dy_dated = list(zip(dates, dy.tolist(), strict=True))

    dur, r2 = rm.empirical_duration(fund_dated, dy_dated)
    assert dur is not None and abs(dur - 6.0) < 0.1
    assert r2 is not None and r2 > 0.95


def test_empirical_duration_none_below_min_observations():
    """Fewer than REG_MIN_OBSERVATIONS aligned dates → (None, None)."""
    start = _dt.date(2024, 1, 1)
    dates = [start + _dt.timedelta(days=i) for i in range(50)]  # < 120
    fund_dated = [(d, 0.001) for d in dates]
    dy_dated = [(d, 0.0001) for d in dates]
    assert rm.empirical_duration(fund_dated, dy_dated) == (None, None)


def test_empirical_duration_none_below_min_r_squared():
    """Pure-noise fund return uncorrelated with yield → R² below floor → None."""
    rng = np.random.default_rng(11)
    start = _dt.date(2023, 1, 2)
    n = 400
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    fund_dated = list(zip(dates, rng.normal(0, 0.01, n).tolist(), strict=True))
    dy_dated = list(zip(dates, rng.normal(0, 0.0005, n).tolist(), strict=True))
    dur, r2 = rm.empirical_duration(fund_dated, dy_dated)
    assert dur is None and r2 is None
```

- [ ] **Step 2: Run it, expect FAIL.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_empirical_duration_recovers_known_beta tests/test_risk_metrics.py::test_empirical_duration_none_below_min_observations tests/test_risk_metrics.py::test_empirical_duration_none_below_min_r_squared -v
```
Expected: `AttributeError: module 'src.workers.risk_metrics' has no attribute 'empirical_duration'` (function not defined yet).

- [ ] **Step 3: Write the minimal implementation.** Insert into `src/workers/risk_metrics.py` immediately AFTER `regression_metrics` (after line 505) and BEFORE the `# Per-fund metric assembly` banner (line 508). Note: `Any`, `np`, `_dt`, `_clip` are already imported/defined in this module (`risk_metrics.py:31,34,36,75`):
```python
# ──────────────────────────────────────────────────────────────────────────────
# Class regression metrics (Tier 1, rank 4) — fixed-income empirical duration /
# credit beta (vs macro_data ΔDGS10 / ΔBAA10Y) and alternatives inflation beta /
# crisis alpha. Pure ports of quant_engine.fixed_income_analytics_service and
# quant_engine.alternatives_analytics_service. Date-aligned by inner join.
# ──────────────────────────────────────────────────────────────────────────────
# OLS gates (verbatim from FIRegressionConfig / AltAnalyticsConfig).
REG_MIN_OBSERVATIONS = 120          # ~6 months of daily data (FIRegressionConfig)
REG_WINDOW_DAYS = 504               # 2 years (2 * 252) (FIRegressionConfig)
REG_MIN_R_SQUARED = 0.05            # FI duration / credit beta floor
INFLATION_MIN_MONTHS = 12           # inflation beta minimum aligned months
INFLATION_MIN_R2 = 0.02             # inflation beta R² floor
CRISIS_DRAWDOWN_THRESHOLD = -0.10   # benchmark drawdown defining "crisis"
CRISIS_MIN_DAYS = 20                # minimum crisis days to report crisis alpha


def _ols_beta_r2(y: np.ndarray, x: np.ndarray) -> tuple[float, float]:
    """OLS y = alpha + beta*x → (beta, r_squared). Verbatim legacy math
    (fixed_income_analytics_service._ols_regression)."""
    design = np.column_stack([np.ones(len(x)), x])
    coeffs = np.linalg.lstsq(design, y, rcond=None)[0]
    beta = float(coeffs[1])
    y_hat = design @ coeffs
    ss_res = float(np.sum((y - y_hat) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r2 = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0
    return beta, r2


def empirical_duration(
    fund_ret_dated: list[tuple[_dt.date, float]],
    dgs10_change_dated: list[tuple[_dt.date, float]],
) -> tuple[float | None, float | None]:
    """Empirical duration = -beta of OLS(fund returns vs ΔDGS10 in decimal).

    R_fund(t) = alpha + beta * ΔY_10Y(t); empirical_duration = -beta.
    Inner-joins on date, takes the latest REG_WINDOW_DAYS, and returns
    (duration, r2) or (None, None) when fewer than REG_MIN_OBSERVATIONS
    aligned points or R² < REG_MIN_R_SQUARED.
    """
    yld = dict(dgs10_change_dated)
    pairs = [(r, yld[d]) for d, r in fund_ret_dated if d in yld]
    if len(pairs) < REG_MIN_OBSERVATIONS:
        return None, None
    pairs = pairs[-REG_WINDOW_DAYS:]
    y = np.array([p[0] for p in pairs], dtype=float)
    x = np.array([p[1] for p in pairs], dtype=float)
    beta, r2 = _ols_beta_r2(y, x)
    if r2 < REG_MIN_R_SQUARED:
        return None, None
    return _clip(-beta, 4), _clip(r2, 4)
```

- [ ] **Step 4: Run tests, expect PASS.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_empirical_duration_recovers_known_beta tests/test_risk_metrics.py::test_empirical_duration_none_below_min_observations tests/test_risk_metrics.py::test_empirical_duration_none_below_min_r_squared -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
cd /e/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py && git commit -m "feat(risk_metrics): pure empirical_duration vs delta DGS10 (OLS)

Port of quant_engine.fixed_income_analytics_service.compute_empirical_duration
with the legacy 120-obs / 504-day window / 0.05 R2 gates; shared _ols_beta_r2
helper and date inner-join.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-3: Pure `credit_beta` from dated fund returns vs ΔBAA10Y

Port `compute_credit_beta` (legacy `fixed_income_analytics_service.py:87`). Same shape as `empirical_duration` (credit_beta = `-beta`), reusing `_ols_beta_r2` and the FI gates. Depends on T1B-2 (uses the constants and helper added there).

**Files:**
- Modify: `src/workers/risk_metrics.py` (add `credit_beta` immediately after `empirical_duration`)
- Test: `tests/test_risk_metrics.py` (append)

Steps:

- [ ] **Step 1: Write the failing test.** Append to `tests/test_risk_metrics.py`:
```python
def test_credit_beta_recovers_known_beta():
    """Fund return = -3 * delta_spread (+ tiny noise) → credit_beta ≈ 3."""
    rng = np.random.default_rng(13)
    start = _dt.date(2023, 1, 2)
    n = 400
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    ds = rng.normal(0.0, 0.0004, n)          # daily spread change, DECIMAL
    fund_ret = -3.0 * ds + rng.normal(0.0, 1e-5, n)
    fund_dated = list(zip(dates, fund_ret.tolist(), strict=True))
    ds_dated = list(zip(dates, ds.tolist(), strict=True))

    cb, r2 = rm.credit_beta(fund_dated, ds_dated)
    assert cb is not None and abs(cb - 3.0) < 0.1
    assert r2 is not None and r2 > 0.95


def test_credit_beta_none_below_min_observations():
    start = _dt.date(2024, 1, 1)
    dates = [start + _dt.timedelta(days=i) for i in range(60)]  # < 120
    fund_dated = [(d, 0.001) for d in dates]
    ds_dated = [(d, 0.0001) for d in dates]
    assert rm.credit_beta(fund_dated, ds_dated) == (None, None)
```

- [ ] **Step 2: Run it, expect FAIL.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_credit_beta_recovers_known_beta tests/test_risk_metrics.py::test_credit_beta_none_below_min_observations -v
```
Expected: `AttributeError: module 'src.workers.risk_metrics' has no attribute 'credit_beta'`.

- [ ] **Step 3: Write the minimal implementation.** Insert into `src/workers/risk_metrics.py` immediately AFTER the `empirical_duration` function added in T1B-2:
```python
def credit_beta(
    fund_ret_dated: list[tuple[_dt.date, float]],
    baa10y_change_dated: list[tuple[_dt.date, float]],
) -> tuple[float | None, float | None]:
    """Credit beta = -beta of OLS(fund returns vs ΔBAA10Y in decimal).

    R_fund(t) = alpha + beta * ΔSpread(t); credit_beta = -beta.
    Same gates and windowing as empirical_duration.
    """
    spread = dict(baa10y_change_dated)
    pairs = [(r, spread[d]) for d, r in fund_ret_dated if d in spread]
    if len(pairs) < REG_MIN_OBSERVATIONS:
        return None, None
    pairs = pairs[-REG_WINDOW_DAYS:]
    y = np.array([p[0] for p in pairs], dtype=float)
    x = np.array([p[1] for p in pairs], dtype=float)
    beta, r2 = _ols_beta_r2(y, x)
    if r2 < REG_MIN_R_SQUARED:
        return None, None
    return _clip(-beta, 4), _clip(r2, 4)
```

- [ ] **Step 4: Run tests, expect PASS.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_credit_beta_recovers_known_beta tests/test_risk_metrics.py::test_credit_beta_none_below_min_observations -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit.**
```bash
cd /e/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py && git commit -m "feat(risk_metrics): pure credit_beta vs delta BAA10Y (OLS)

Port of quant_engine.fixed_income_analytics_service.compute_credit_beta;
credit_beta = -beta, same FI gates as empirical_duration.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-4: Pure `inflation_beta` from MONTHLY fund returns vs monthly ΔCPI

Port `compute_inflation_beta` + the daily→monthly resampling and CPI alignment (legacy `alternatives_analytics_service.py:182`, the resampling in `compute_alt_analytics:291-312`, and the CPI MoM calc in `risk_calc._fetch_monthly_cpi_changes:1220`). inflation_beta is the RAW `+beta` (positive = inflation hedge). CPI changes are monthly fractional MoM changes keyed by (year, month). Depends on T1B-2 for `_ols_beta_r2` and the `INFLATION_MIN_*` constants.

**Files:**
- Modify: `src/workers/risk_metrics.py` (add `_daily_to_monthly_by_ym` + `inflation_beta` immediately after `credit_beta`)
- Test: `tests/test_risk_metrics.py` (append)

Steps:

- [ ] **Step 1: Write the failing test.** Append to `tests/test_risk_metrics.py`:
```python
def test_inflation_beta_recovers_positive_beta():
    """Monthly fund return = 0.5 * monthly_cpi_change (+noise) → inflation_beta ≈ 0.5.

    Daily fund returns compound to a monthly return ≈ the per-month target; the
    function resamples daily→monthly internally, so we hand it ~21 trading days
    per month with the per-month return spread evenly.
    """
    rng = np.random.default_rng(21)
    fund_dated: list = []
    cpi_dated: list = []
    for k in range(18):                       # 18 months ≥ INFLATION_MIN_MONTHS
        year = 2023 + (k // 12)
        month = (k % 12) + 1
        cpi_chg = float(rng.normal(0.003, 0.002))      # monthly CPI MoM, decimal
        cpi_dated.append((_dt.date(year, month, 1), cpi_chg))
        target_month_ret = 0.5 * cpi_chg + float(rng.normal(0.0, 1e-4))
        daily = (1.0 + target_month_ret) ** (1.0 / 21) - 1.0
        for day in range(1, 22):
            fund_dated.append((_dt.date(year, month, day), daily))

    ib, r2 = rm.inflation_beta(fund_dated, cpi_dated)
    assert ib is not None and abs(ib - 0.5) < 0.15
    assert r2 is not None and r2 >= rm.INFLATION_MIN_R2


def test_inflation_beta_none_below_min_months():
    """Fewer than INFLATION_MIN_MONTHS aligned months → (None, None)."""
    fund_dated = [(_dt.date(2024, m, d), 0.001) for m in range(1, 4) for d in range(1, 22)]
    cpi_dated = [(_dt.date(2024, m, 1), 0.002) for m in range(1, 4)]  # 3 months
    assert rm.inflation_beta(fund_dated, cpi_dated) == (None, None)
```

- [ ] **Step 2: Run it, expect FAIL.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_inflation_beta_recovers_positive_beta tests/test_risk_metrics.py::test_inflation_beta_none_below_min_months -v
```
Expected: `AttributeError: module 'src.workers.risk_metrics' has no attribute 'inflation_beta'`.

- [ ] **Step 3: Write the minimal implementation.** Insert into `src/workers/risk_metrics.py` immediately AFTER the `credit_beta` function:
```python
def _daily_to_monthly_by_ym(
    dated_returns: list[tuple[_dt.date, float]],
) -> dict[tuple[int, int], float]:
    """Compound daily returns into monthly returns keyed by (year, month).
    Mirrors alternatives_analytics_service._daily_to_monthly grouping."""
    grouped: dict[tuple[int, int], list[float]] = {}
    for d, r in dated_returns:
        grouped.setdefault((d.year, d.month), []).append(float(r))
    by_month: dict[tuple[int, int], float] = {}
    for key, daily in grouped.items():
        compounded = 1.0
        for r in daily:
            compounded *= 1.0 + r
        by_month[key] = compounded - 1.0
    return by_month


def inflation_beta(
    fund_ret_dated: list[tuple[_dt.date, float]],
    cpi_monthly_change_dated: list[tuple[_dt.date, float]],
) -> tuple[float | None, float | None]:
    """Inflation beta = +beta of OLS(monthly fund returns vs monthly ΔCPI).

    R_fund(month) = alpha + beta * ΔCPI(month); positive beta = inflation hedge.
    Resamples daily fund returns to monthly, inner-joins with the monthly CPI
    change by (year, month), and returns (beta, r2) or (None, None) below
    INFLATION_MIN_MONTHS aligned months or R² < INFLATION_MIN_R2.
    """
    fund_by_ym = _daily_to_monthly_by_ym(fund_ret_dated)
    cpi_by_ym = {(d.year, d.month): float(v) for d, v in cpi_monthly_change_dated}
    months = sorted(set(fund_by_ym) & set(cpi_by_ym))
    if len(months) < INFLATION_MIN_MONTHS:
        return None, None
    y = np.array([fund_by_ym[m] for m in months], dtype=float)
    x = np.array([cpi_by_ym[m] for m in months], dtype=float)
    beta, r2 = _ols_beta_r2(y, x)
    if r2 < INFLATION_MIN_R2:
        return None, None
    return _clip(beta, 4), _clip(r2, 4)
```

- [ ] **Step 4: Run tests, expect PASS.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_inflation_beta_recovers_positive_beta tests/test_risk_metrics.py::test_inflation_beta_none_below_min_months -v
```
Expected: 2 passed.

- [ ] **Step 5: Commit.**
```bash
cd /e/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py && git commit -m "feat(risk_metrics): pure inflation_beta (monthly OLS vs CPI MoM)

Port of quant_engine.alternatives_analytics_service.compute_inflation_beta
with daily->monthly resampling and (year,month) CPI alignment; raw +beta,
12-month / 0.02 R2 gates.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-5: Pure `crisis_alpha` conditional on benchmark-drawdown days

Port `compute_crisis_alpha` (legacy `alternatives_analytics_service.py:131`): compute the benchmark running drawdown over the date-aligned series, mask days where drawdown < −10%, and return fund-cumulative minus benchmark-cumulative return over those days. The legacy guard is `n < 60` (`:144`) and `crisis_mask.sum() < min_crisis_days` (`:157`). Takes the SAME dated inputs used by `relative_metrics_for` (fund and benchmark daily returns). No dependency on the OLS helper.

**Files:**
- Modify: `src/workers/risk_metrics.py` (add `crisis_alpha` immediately after `inflation_beta`)
- Test: `tests/test_risk_metrics.py` (append)

Steps:

- [ ] **Step 1: Write the failing test.** Append to `tests/test_risk_metrics.py`:
```python
def test_crisis_alpha_positive_when_fund_outperforms_in_drawdown():
    """Construct a benchmark with a deep (> -10%) drawdown stretch; the fund is
    flat during it. Fund cum − bench cum over crisis days must be > 0."""
    start = _dt.date(2023, 1, 2)
    n = 120
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    bench_ret = [0.0] * n
    # Days 30..70: benchmark falls ~1%/day → cumulative drawdown well past -10%.
    for i in range(30, 71):
        bench_ret[i] = -0.01
    fund_ret = [0.0] * n                        # fund flat throughout
    fund_dated = list(zip(dates, fund_ret, strict=True))
    bench_dated = list(zip(dates, bench_ret, strict=True))

    ca = rm.crisis_alpha(fund_dated, bench_dated)
    assert ca is not None and ca > 0.0


def test_crisis_alpha_none_when_too_few_crisis_days():
    """No benchmark drawdown beyond threshold → fewer than CRISIS_MIN_DAYS
    crisis days → None."""
    start = _dt.date(2023, 1, 2)
    n = 120
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    flat = list(zip(dates, [0.0001] * n, strict=True))   # gently rising, no DD
    assert rm.crisis_alpha(flat, flat) is None


def test_crisis_alpha_none_below_min_aligned():
    """Fewer than 60 aligned days → None (matches legacy guard)."""
    start = _dt.date(2024, 1, 1)
    dates = [start + _dt.timedelta(days=i) for i in range(40)]
    rows = list(zip(dates, [0.0] * 40, strict=True))
    assert rm.crisis_alpha(rows, rows) is None
```

- [ ] **Step 2: Run it, expect FAIL.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_crisis_alpha_positive_when_fund_outperforms_in_drawdown tests/test_risk_metrics.py::test_crisis_alpha_none_when_too_few_crisis_days tests/test_risk_metrics.py::test_crisis_alpha_none_below_min_aligned -v
```
Expected: `AttributeError: module 'src.workers.risk_metrics' has no attribute 'crisis_alpha'`.

- [ ] **Step 3: Write the minimal implementation.** Insert into `src/workers/risk_metrics.py` immediately AFTER the `inflation_beta` function:
```python
def crisis_alpha(
    fund_ret_dated: list[tuple[_dt.date, float]],
    bench_ret_dated: list[tuple[_dt.date, float]],
) -> float | None:
    """Crisis alpha: fund cum return − benchmark cum return on benchmark-
    drawdown days < CRISIS_DRAWDOWN_THRESHOLD.

    Inner-joins fund and benchmark daily returns by date, computes the
    benchmark's running drawdown, and over the masked crisis days returns
    prod(1+fund)-1 minus prod(1+bench)-1. Positive = the fund cushioned the
    drawdown (diversification value). None below 60 aligned days or fewer than
    CRISIS_MIN_DAYS crisis days (legacy compute_crisis_alpha guards).
    """
    bench_map = dict(bench_ret_dated)
    pairs = [(f, bench_map[d]) for d, f in fund_ret_dated if d in bench_map]
    if len(pairs) < 60:
        return None
    fund_d = np.array([p[0] for p in pairs], dtype=float)
    bench_d = np.array([p[1] for p in pairs], dtype=float)

    bench_cum = np.cumprod(1.0 + bench_d)
    bench_peak = np.maximum.accumulate(bench_cum)
    bench_dd = (bench_cum - bench_peak) / bench_peak
    crisis_mask = bench_dd < CRISIS_DRAWDOWN_THRESHOLD
    if int(crisis_mask.sum()) < CRISIS_MIN_DAYS:
        return None

    fund_crisis = float(np.prod(1.0 + fund_d[crisis_mask]) - 1.0)
    bench_crisis = float(np.prod(1.0 + bench_d[crisis_mask]) - 1.0)
    return _clip(fund_crisis - bench_crisis, 6)
```

- [ ] **Step 4: Run tests, expect PASS.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_crisis_alpha_positive_when_fund_outperforms_in_drawdown tests/test_risk_metrics.py::test_crisis_alpha_none_when_too_few_crisis_days tests/test_risk_metrics.py::test_crisis_alpha_none_below_min_aligned -v
```
Expected: 3 passed.

- [ ] **Step 5: Commit.**
```bash
cd /e/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py && git commit -m "feat(risk_metrics): pure crisis_alpha conditional on benchmark drawdown

Port of quant_engine.alternatives_analytics_service.compute_crisis_alpha;
fund cum minus benchmark cum over benchmark-drawdown days < -10%, 60-day /
20-crisis-day guards.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-6: Wire the four metrics into the worker — macro fetch, asset-class dispatch, persist

Wire the pure functions into the worker's read/compute/upsert path:
1. Add `_fetch_macro_changes(conn, calc_date)` that loads daily ΔDGS10 / ΔBAA10Y (decimal, gap-guarded `> 7` days) and monthly ΔCPI from `macro_data` — a direct port of `risk_calc._batch_fetch_macro_yield_changes` (`:445`) + `_fetch_monthly_cpi_changes` (`:1220`).
2. Add `_fetch_fund_asset_classes(conn)` mapping `instrument_id(str) → asset_class` from `instruments_universe`.
3. Add a pure `class_regression_metrics_for(rows, asset_class, macro_changes)` that, given a fund's NAV rows and its asset_class, calls the right pure functions and returns the metric dict (+ `scoring_model`).
4. Call it alongside `relative_metrics_for` in BOTH execution paths (`_process_shard` loop body at line ~710 and the serial branch at line ~879), pass the shared `macro_changes`/`fund_asset_classes` read once in `run()` (after line 863), and add the new columns to `_METRIC_COLUMNS` (lines 55-69) so `_upsert` persists them.

**Files:**
- Modify: `src/workers/risk_metrics.py` — extend `_METRIC_COLUMNS` (lines 67-69); add the two I/O fetchers after `_fetch_benchmark_returns` (ends line 420); add `class_regression_metrics_for` after `crisis_alpha`; thread `macro_changes`/`fund_asset_classes` through `run()` (read after line 863), the serial branch (after line 883), and `_process_shard` (signature lines 680-687, body after line 714, submit call lines 902-911).
- Test: `tests/test_risk_metrics.py` (append a pure assembly test + a `_METRIC_COLUMNS` membership test, and patch the existing MV-refresh test)

Steps:

- [ ] **Step 1: Write the failing tests.** Append to `tests/test_risk_metrics.py`:
```python
def test_metric_columns_include_class_regression():
    """The upsert column list carries the four new metrics + helpers."""
    for col in (
        "scoring_model", "empirical_duration", "empirical_duration_r2",
        "credit_beta", "credit_beta_r2", "inflation_beta", "inflation_beta_r2",
        "crisis_alpha_score",
    ):
        assert col in rm._METRIC_COLUMNS, col


def _nav_rows_from_returns(start, daily_returns):
    """[(date, nav)] from a daily-return list, NAV seeded at 100."""
    rows = [(start - _dt.timedelta(days=1), 100.0)]
    nav = 100.0
    for i, r in enumerate(daily_returns):
        nav *= (1.0 + r)
        rows.append((start + _dt.timedelta(days=i), nav))
    return rows


def test_class_regression_fixed_income_populates_duration_and_credit():
    """A fixed_income fund whose returns track ΔDGS10/ΔBAA10Y gets
    empirical_duration, credit_beta and scoring_model='fixed_income';
    alt-only keys absent."""
    rng = np.random.default_rng(5)
    start = _dt.date(2023, 1, 2)
    n = 420
    dates = [start + _dt.timedelta(days=i) for i in range(n)]
    dy = rng.normal(0.0, 0.0005, n)
    ds = rng.normal(0.0, 0.0004, n)
    fund_ret = (-6.0 * dy - 3.0 * ds + rng.normal(0.0, 1e-5, n)).tolist()
    rows = _nav_rows_from_returns(start, fund_ret)
    macro_changes = {
        "DGS10": list(zip(dates, dy.tolist(), strict=True)),
        "BAA10Y": list(zip(dates, ds.tolist(), strict=True)),
        "CPI": [],
    }
    out = rm.class_regression_metrics_for(rows, "fixed_income", macro_changes)
    assert out["scoring_model"] == "fixed_income"
    assert out["empirical_duration"] is not None
    assert out["credit_beta"] is not None
    assert "crisis_alpha_score" not in out
    assert "inflation_beta" not in out


def test_class_regression_equity_is_noop():
    """An equity fund only gets scoring_model='equity', no regression keys."""
    rows = [(_dt.date(2024, 1, 1) + _dt.timedelta(days=i), 100.0 + i) for i in range(30)]
    out = rm.class_regression_metrics_for(rows, "equity", {"DGS10": [], "BAA10Y": [], "CPI": []})
    assert out == {"scoring_model": "equity"}
```

- [ ] **Step 2: Run them, expect FAIL.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_metric_columns_include_class_regression tests/test_risk_metrics.py::test_class_regression_fixed_income_populates_duration_and_credit tests/test_risk_metrics.py::test_class_regression_equity_is_noop -v
```
Expected: `test_metric_columns_include_class_regression` FAILS with `AssertionError: scoring_model` (column not yet listed); the others FAIL with `AttributeError: ... has no attribute 'class_regression_metrics_for'`.

- [ ] **Step 3: Implement.**

  (a) Extend `_METRIC_COLUMNS` — replace the last two entries (lines 67-69, currently `"cvar_99_evt", "cvar_999_evt", "evt_xi_shape",` / `"fed_funds_rate_at_calc", "data_quality_flags",` / `]`) so the new columns are persisted:
```python
    "cvar_99_evt", "cvar_999_evt", "evt_xi_shape",
    "fed_funds_rate_at_calc", "data_quality_flags",
    # Class-specific regression metrics (Tier 1, rank 4).
    "scoring_model",
    "empirical_duration", "empirical_duration_r2",
    "credit_beta", "credit_beta_r2",
    "inflation_beta", "inflation_beta_r2",
    "crisis_alpha_score",
]
```

  (b) Add the pure assembly function immediately AFTER `crisis_alpha` (from T1B-5). `dated_simple_returns` already exists (`risk_metrics.py:423`):
```python
def class_regression_metrics_for(
    rows: list,
    asset_class: str | None,
    macro_changes: dict[str, list[tuple[_dt.date, float]]],
) -> dict[str, Any]:
    """Class-specific regression metrics from a fund's NAV rows + macro changes.

    ``rows`` is _fetch_nav output ([(date, nav)] ascending). ``macro_changes``
    carries 'DGS10' / 'BAA10Y' daily decimal changes, 'CPI' monthly decimal
    changes, and '_equity_benchmark' daily benchmark returns (injected by the
    caller). fixed_income → empirical_duration + credit_beta; alternatives →
    inflation_beta + crisis_alpha_score (vs the equity benchmark). scoring_model
    tags the pass; equity/cash get only the tag.
    """
    fund_ret = dated_simple_returns([(r[0], r[1]) for r in rows])
    out: dict[str, Any] = {}
    if asset_class == "fixed_income":
        out["scoring_model"] = "fixed_income"
        dur, dur_r2 = empirical_duration(fund_ret, macro_changes.get("DGS10", []))
        if dur is not None:
            out["empirical_duration"] = dur
            out["empirical_duration_r2"] = dur_r2
        cb, cb_r2 = credit_beta(fund_ret, macro_changes.get("BAA10Y", []))
        if cb is not None:
            out["credit_beta"] = cb
            out["credit_beta_r2"] = cb_r2
    elif asset_class == "alternatives":
        out["scoring_model"] = "alternatives"
        ib, ib_r2 = inflation_beta(fund_ret, macro_changes.get("CPI", []))
        if ib is not None:
            out["inflation_beta"] = ib
            out["inflation_beta_r2"] = ib_r2
        eq = macro_changes.get("_equity_benchmark", [])
        if eq:
            ca = crisis_alpha(fund_ret, eq)
            if ca is not None:
                out["crisis_alpha_score"] = ca
    else:
        out["scoring_model"] = "cash" if asset_class == "cash" else "equity"
    return out
```

  (c) Add the two I/O fetchers immediately AFTER `_fetch_benchmark_returns` (ends line 420). The window mirrors the legacy fetch (REG_WINDOW_DAYS plus slack for holidays/CPI history):
```python
def _fetch_macro_changes(
    conn, calc_date: _dt.date
) -> dict[str, list[tuple[_dt.date, float]]]:
    """Daily ΔDGS10 / ΔBAA10Y (decimal, gap-guarded) and monthly ΔCPI from
    macro_data. Yields are FRED percent → /100 for decimal changes; CPI is an
    index level → MoM fractional change. Port of risk_calc._batch_fetch_macro_
    yield_changes (gap > 7 days skipped) + _fetch_monthly_cpi_changes."""
    start = calc_date - _dt.timedelta(days=(REG_WINDOW_DAYS + 60) * 2)
    with conn.cursor() as cur:
        cur.execute(
            """SELECT series_id, obs_date, value FROM macro_data
               WHERE series_id = ANY(%s) AND obs_date <= %s AND obs_date >= %s
                 AND value IS NOT NULL
               ORDER BY series_id, obs_date""",
            (["DGS10", "BAA10Y", "CPIAUCSL"], calc_date, start),
        )
        rows = cur.fetchall()
    levels: dict[str, list[tuple[_dt.date, float]]] = {}
    for sid, d, v in rows:
        levels.setdefault(sid, []).append((d, float(v)))

    out: dict[str, list[tuple[_dt.date, float]]] = {"DGS10": [], "BAA10Y": [], "CPI": []}
    for sid in ("DGS10", "BAA10Y"):
        obs = levels.get(sid, [])
        for i in range(1, len(obs)):
            pd, pv = obs[i - 1]
            cd, cv = obs[i]
            if (cd - pd).days > 7:          # forward-fill gap guard (legacy :484)
                continue
            out[sid].append((cd, (cv - pv) / 100.0))
    cpi = levels.get("CPIAUCSL", [])
    for i in range(1, len(cpi)):
        pv = cpi[i - 1][1]
        if pv > 0:
            out["CPI"].append((cpi[i][0], (cpi[i][1] - pv) / pv))
    return out


def _fetch_fund_asset_classes(conn) -> dict[str, str]:
    """instrument_id(str) → asset_class from instruments_universe."""
    out: dict[str, str] = {}
    with conn.cursor() as cur:
        cur.execute(
            "SELECT instrument_id, asset_class FROM instruments_universe "
            "WHERE asset_class IS NOT NULL"
        )
        for iid, ac in cur.fetchall():
            out[str(iid)] = ac
    return out
```

  (d) Thread the shared data through `run()`. After `fund_benchmarks = _fetch_fund_benchmarks(conn)` (line 863) add:
```python
            macro_changes = _fetch_macro_changes(conn, cdate)
            macro_changes["_equity_benchmark"] = bench_returns.get(EQUITY_BENCHMARK_BLOCK, [])
            fund_asset_classes = _fetch_fund_asset_classes(conn)
```
In the SERIAL branch, immediately after the existing `metrics.update(relative_metrics_for(...))` (lines 879-883) add:
```python
                    metrics.update(
                        class_regression_metrics_for(
                            rows, fund_asset_classes.get(str(iid)), macro_changes
                        )
                    )
```
Extend `_process_shard`'s signature (lines 680-687) to add `macro_changes` and `fund_asset_classes` (full new signature):
```python
def _process_shard(
    dsn: str,
    calc_date_iso: str,
    rf: float,
    fund_ids: list,
    fund_benchmarks: dict[str, str],
    bench_returns: dict[str, list[tuple[_dt.date, float]]],
    macro_changes: dict[str, list[tuple[_dt.date, float]]],
    fund_asset_classes: dict[str, str],
) -> tuple[int, int]:
```
In `_process_shard`'s loop, immediately after the existing `metrics.update(relative_metrics_for(...))` (lines 710-714) add:
```python
            metrics.update(
                class_regression_metrics_for(
                    rows, fund_asset_classes.get(str(iid)), macro_changes
                )
            )
```
In the `pool.submit(...)` call (lines 902-911) pass the two new args (the `_equity_benchmark` key is already inside `macro_changes`, so children get it for free):
```python
                        pool.submit(
                            _process_shard,
                            dsn,
                            cdate_iso,
                            rf,
                            shard,
                            {str(i): b for i in shard if (b := fund_benchmarks.get(str(i)))},
                            bench_returns,
                            macro_changes,
                            {str(i): fund_asset_classes[str(i)]
                             for i in shard if str(i) in fund_asset_classes},
                        )
```

  (e) Patch the existing MV-refresh test so the two new fetchers are monkeypatched (otherwise `run()` calls the real DB). In `test_run_refreshes_mv_after_lock_released` (line 386), alongside the existing `monkeypatch.setattr(rm, "_fetch_fund_benchmarks", lambda _c: {})` (line 411) add:
```python
    monkeypatch.setattr(
        rm, "_fetch_macro_changes",
        lambda _c, _cd: {"DGS10": [], "BAA10Y": [], "CPI": []},
    )
    monkeypatch.setattr(rm, "_fetch_fund_asset_classes", lambda _c: {})
```

- [ ] **Step 4: Run the new + the MV-refresh + the existing relative-metrics tests, expect PASS.**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py::test_metric_columns_include_class_regression tests/test_risk_metrics.py::test_class_regression_fixed_income_populates_duration_and_credit tests/test_risk_metrics.py::test_class_regression_equity_is_noop tests/test_risk_metrics.py::test_relative_metrics_synthetic_beta_two tests/test_risk_metrics.py::test_run_refreshes_mv_after_lock_released -v
```
Expected: all passed.

- [ ] **Step 5: Run the FULL worker risk_metrics suite (pure tests pass; DB tests self-skip).**
```bash
cd /e/investintell-datalake-workers && python -m pytest tests/test_risk_metrics.py -v
```
Expected: the new pure tests pass; the DB-touching tests (`test_run_end_to_end_and_idempotent`, `test_recalc_vs_legacy`, `test_advisory_lock_is_distinct`, `test_peer_percentiles_set_based`) self-skip if Postgres@5434 is unreachable, or pass if reachable. No errors.

- [ ] **Step 6: Commit.**
```bash
cd /e/investintell-datalake-workers && git add src/workers/risk_metrics.py tests/test_risk_metrics.py && git commit -m "feat(risk_metrics): wire FI/alt regression metrics into the worker

Fetch macro changes (DGS10/BAA10Y/CPI) and fund asset_class, dispatch the
class regression pass per asset_class, persist into fund_risk_metrics; threaded
through serial and process-pool paths.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-7: Add the four columns to the LIGHT `fund_risk_latest_mv` DDL

The light read path is the Tiger materialized view `fund_risk_latest_mv` (defined in `backend/db/ddl/2026-06-13_dynamic_catalog.sql`, CREATE block lines 63-76, unique index lines 78-79), which enumerates 33 columns and OMITS the FI/alt regression metrics. Add the four new headline columns (no R² in the MV — the UI surfaces only the headline metric, matching how `equity_correlation_252d` etc. are exposed without their R²). Because `CREATE MATERIALIZED VIEW IF NOT EXISTS` will NOT alter an existing MV, the DDL must DROP and re-CREATE it (it is read-only and rebuilt by the worker's `REFRESH MATERIALIZED VIEW CONCURRENTLY` path, `risk_metrics.py:825`).

**Files:**
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql` (the `fund_risk_latest_mv` block, lines 60-79)

Steps:

- [ ] **Step 1: Edit the MV definition.** Replace the comment + `CREATE MATERIALIZED VIEW IF NOT EXISTS fund_risk_latest_mv AS ... ORDER BY instrument_id, calc_date DESC;` block (lines 60-76) with the block below. The `CREATE UNIQUE INDEX IF NOT EXISTS fund_risk_latest_mv_pk` at lines 78-79 stays unchanged and re-creates after the DROP:
```sql
-- Latest risk metrics per fund (replaces the sync_funds.py fund_risk_latest
-- snapshot). organization_id IS NULL = the global (non-org) calc. The column
-- set mirrors the MV-backed model plus the Tier-1 class regression metrics.
-- DROP+CREATE (not CREATE IF NOT EXISTS) so column additions take effect — the
-- MV is read-only and rebuilt by the risk_metrics worker's
-- REFRESH MATERIALIZED VIEW CONCURRENTLY path; the unique index below must be
-- recreated after the DROP for CONCURRENTLY to work.
DROP MATERIALIZED VIEW IF EXISTS fund_risk_latest_mv;
CREATE MATERIALIZED VIEW fund_risk_latest_mv AS
SELECT DISTINCT ON (instrument_id)
       instrument_id, calc_date,
       return_1m, return_3m, return_1y, return_3y_ann, return_5y_ann,
       volatility_1y, max_drawdown_1y, max_drawdown_3y,
       sharpe_1y, sharpe_3y, sortino_1y, calmar_ratio_3y,
       alpha_1y, beta_1y, information_ratio_1y, tracking_error_1y,
       var_95_1m, cvar_95_1m, cvar_95_12m, cvar_99_evt,
       peer_sharpe_pctl, peer_sortino_pctl, peer_return_pctl, peer_drawdown_pctl,
       manager_score, downside_capture_1y, upside_capture_1y,
       equity_correlation_252d, peer_strategy_label, peer_count, elite_flag,
       empirical_duration, credit_beta, inflation_beta, crisis_alpha_score
FROM fund_risk_metrics
WHERE organization_id IS NULL
ORDER BY instrument_id, calc_date DESC;
```

- [ ] **Step 2: Verify the file is internally consistent.** No automated test runs against the DDL (it is applied to Tiger via psql, not alembic — see the MV note at `dynamic_catalog.sql:60-62`). Confirm the new SELECT lists 37 columns and that the four added names exactly match the `fund_risk_metrics` columns from Task T1B-1 (`empirical_duration`, `credit_beta`, `inflation_beta`, `crisis_alpha_score`) and the ORM column names from Task T1B-8.

- [ ] **Step 3: Commit.**
```bash
cd /e/investintell-light && git add backend/db/ddl/2026-06-13_dynamic_catalog.sql && git commit -m "feat(catalog): expose FI/alt regression metrics in fund_risk_latest_mv

Add empirical_duration, credit_beta, inflation_beta, crisis_alpha_score to the
risk MV (DROP+CREATE so the columns take effect); read by FundRiskLatest /
FundRiskOut.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-8: Expose the four metrics on the LIGHT `FundRiskLatest` ORM model and `FundRiskOut` schema

`FundProfileResponse.risk` is a `FundRiskOut` built with `from_attributes=True` from the `FundRiskLatest` ORM row, via `FundRiskOut.model_validate(profile.risk)` in the route (`app/api/routes/funds.py:291`; `fetch_fund_profile` passes the ORM row straight through, `funds_catalog.py:480`). Add the four columns to the ORM model (so SQLAlchemy reads them off the MV) and the four fields to the response schema. TDD: a route serialization test proving the profile JSON carries the metrics.

NOTE (side effect, no action required): `_RISK_SORT_FIELDS` is derived dynamically from `FundRiskLatest.__table__.columns` (`funds_catalog.py:65-69`), so adding the four ORM columns automatically makes them valid `sort=` codes on GET /funds and auto-includes them (as None) in the `_profile()` fixture's `risk_fields` comprehension — the explicit dict override in Step 1 still wins. This is consistent with how the other risk columns behave.

**Files:**
- Modify: `backend/app/models/fund.py` (`FundRiskLatest`, immediately after `equity_correlation_252d` at line 181)
- Modify: `backend/app/schemas/funds.py` (`FundRiskOut`, immediately after `equity_correlation_252d` at line 100)
- Test: `backend/tests/test_funds_routes.py` (extend the `risk` SimpleNamespace in `_profile()` at lines 260-270 + add assertions in `test_fund_profile_payload` after line 319)

Steps:

- [ ] **Step 1: Write the failing test.** In `backend/tests/test_funds_routes.py`: (a) change the `risk` SimpleNamespace block in `_profile()` (lines 260-270) to include the new keys:
```python
    risk = SimpleNamespace(
        **{
            **risk_fields,
            "calc_date": _CALC,
            "sharpe_1y": 1.1,
            "cvar_95_12m": -0.21,
            "peer_strategy_label": "Large Cap Blend",
            "peer_count": 412,
            "elite_flag": True,
            "empirical_duration": 6.4,
            "credit_beta": 1.2,
            "inflation_beta": 0.35,
            "crisis_alpha_score": 0.042,
        }
    )
```
(b) Add to `test_fund_profile_payload` immediately after `assert body["risk"]["peer_count"] == 412` (line 319):
```python
    assert body["risk"]["empirical_duration"] == 6.4
    assert body["risk"]["credit_beta"] == 1.2
    assert body["risk"]["inflation_beta"] == 0.35
    assert body["risk"]["crisis_alpha_score"] == 0.042
```

- [ ] **Step 2: Run it, expect FAIL.**
```bash
cd /e/investintell-light/backend && python -m pytest tests/test_funds_routes.py::test_fund_profile_payload -v
```
Expected: `KeyError: 'empirical_duration'` on `body["risk"]["empirical_duration"]` — `FundRiskOut` does not yet declare the field, so Pydantic drops it from the serialized payload.

- [ ] **Step 3: Implement.**

  (a) In `backend/app/models/fund.py`, add to `FundRiskLatest` immediately AFTER the `equity_correlation_252d` line (line 181):
```python
    # Class-specific regression metrics (Tier 1, rank 4) — read off the risk MV
    # (db/ddl/2026-06-13_dynamic_catalog.sql), computed by the risk_metrics
    # worker per asset_class. NULL for funds outside the matching class.
    empirical_duration: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    credit_beta: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    inflation_beta: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
    crisis_alpha_score: Mapped[Decimal | None] = mapped_column(Numeric, nullable=True)
```

  (b) In `backend/app/schemas/funds.py`, add to `FundRiskOut` immediately AFTER the `equity_correlation_252d` line (line 100):
```python
    # Class-specific regression metrics (dimensionless betas / decimal fractions).
    empirical_duration: float | None = None
    credit_beta: float | None = None
    inflation_beta: float | None = None
    crisis_alpha_score: float | None = None
```
(Defaults `= None` so the list-row path and any other `FundRiskOut` construction sites stay valid without these attributes.)

- [ ] **Step 4: Run the test + the catalog/route suites, expect PASS.**
```bash
cd /e/investintell-light/backend && python -m pytest tests/test_funds_routes.py tests/test_funds_catalog_service.py -v
```
Expected: all passed (the profile test now serializes the four metrics; no regression in the catalog/route tests, including the SORT_WHITELIST-dependent ones).

- [ ] **Step 5: Commit.**
```bash
cd /e/investintell-light && git add backend/app/models/fund.py backend/app/schemas/funds.py backend/tests/test_funds_routes.py && git commit -m "feat(funds): expose FI/alt regression metrics in FundRiskOut

Add empirical_duration, credit_beta, inflation_beta, crisis_alpha_score to the
FundRiskLatest ORM (reads the risk MV) and the FundRiskOut profile schema.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

---

### Task T1B-9: Regenerate the OpenAPI contract / TS types for the new `FundRiskOut` fields

The repo keeps a generated contract in sync via `make types` / `make types-check` (`Makefile:30-37`): `backend/scripts/export_openapi.py` writes `backend/openapi.json`, then `pnpm run types` (frontend/package.json:11, `openapi-typescript ../backend/openapi.json -o src/lib/api/api.d.ts`) writes `frontend/src/lib/api/api.d.ts`. `make types-check` (part of `make check`) runs both and `git diff --exit-code` on the two artifacts — so adding fields to `FundRiskOut` (T1B-8) WILL fail that gate until the artifacts are regenerated. Commit `b634ce9` is the precedent ("regen openapi/types …"). This is a concrete generation step, not a spike.

CONTEXT (flag for the owner): commit `b634ce9` REMOVED the `FundProfileView.tsx` UI rows for these exact metrics (and the out-of-scope FI/cash ones) because the fields were always-NULL. Re-exposing the schema (T1B-8) and regenerating types here re-adds the fields to `api.d.ts`, but this task does NOT restore the `FundProfileView` rows — that is a separate frontend task to schedule once the worker actually populates non-NULL values. The regeneration here only keeps the contract gate green.

**Files:**
- Modify: `backend/openapi.json` (generated — do NOT hand-edit)
- Modify: `frontend/src/lib/api/api.d.ts` (generated — do NOT hand-edit)

Steps:

- [ ] **Step 1: Regenerate both artifacts.** Run the same commands the `types` target uses:
```bash
cd /e/investintell-light/backend && uv run python scripts/export_openapi.py
cd /e/investintell-light/frontend && pnpm run types
```
Expected: `backend/openapi.json` is rewritten ("Wrote …/openapi.json") and `frontend/src/lib/api/api.d.ts` regenerates from it.

- [ ] **Step 2: Verify the four fields landed in the contract under `FundRiskOut`.**
```bash
cd /e/investintell-light && git --no-pager diff --name-only -- backend/openapi.json frontend/src/lib/api/api.d.ts
git --no-pager grep -n "empirical_duration\|credit_beta\|inflation_beta\|crisis_alpha_score" -- backend/openapi.json | head
```
Expected: both files appear in the diff; the four names appear in `backend/openapi.json` under the `FundRiskOut` schema as nullable numbers (and consequently in `api.d.ts`).

- [ ] **Step 3: Run the contract gate, expect PASS after staging.**
```bash
cd /e/investintell-light && git add backend/openapi.json frontend/src/lib/api/api.d.ts && make types-check
```
Expected: `make types-check` re-runs the generators and `git diff --exit-code` is clean (the regenerated artifacts match what is staged → exit 0). If it reports a diff, the generators are non-deterministic with the environment — re-run Step 1 and re-stage.

- [ ] **Step 4: Commit.**
```bash
cd /e/investintell-light && git commit -m "chore(contract): regen openapi/types for FundRiskOut FI/alt metrics

empirical_duration, credit_beta, inflation_beta, crisis_alpha_score added to
the FundRiskOut schema (T1B-8); openapi.json + api.d.ts regenerated via
scripts/export_openapi.py + pnpm run types.

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>"
```

> If `uv` or `pnpm` is unavailable in the execution environment, this task is BLOCKED, not skippable: the T1B-8 schema change will fail `make types-check` (part of `make check`). Record the blocker and have the owner run `make types` on a machine with the toolchain. The generator and artifacts are confirmed to exist, so there is no "no generator → skip" path.

---

## Tier 1 — Swap in-sample CVaR to exact Rockafellar–Uryasev estimator

**Context (read before executing — every fact below was re-verified against the live source files; line numbers are real):**

- The optimizer objective in `backend/app/optimizer/engine.py` `solve_min_cvar` (signature lines 237–244, body 254–282) is the plain daily Rockafellar–Uryasev empirical CVaR with **no drift term**: `losses = -scenarios @ w` (line 273), `cvar = z + cp.sum(cp.pos(losses - z)) / ((1 - alpha) * t)` (line 274), with `DEFAULT_CVAR_ALPHA = 0.95` (engine.py line 26). At optimality over `z` this equals `var_loss + Σ max(losses - var_loss, 0)/((1-α)·T)` where `var_loss` is the **upper** α-quantile of the losses (`np.quantile(losses, α, method="higher")`).
- The builder in-sample report in `backend/app/services/portfolio_builder.py` currently computes `cvar_95 = historical_cvar(portfolio_daily, confidence=0.95)` on the RAW scenarios (line 311; import line 36; inline comment line 308). `historical_cvar` (risk.py lines 88–114) is a **naive tail-mean**: `-mean(values[values <= np.quantile(values, 1-confidence)])` using numpy's default linear-interpolation quantile. This diverges from the optimizer objective whenever `(1-α)·T` is non-integer.
- The legacy reference estimator is `E:/investintell-allocation/backend/quant_engine/ru_cvar_lp.py::realized_cvar_from_weights` (lines 167–215, loss-space k-th-worst form) and `quant_engine/cvar_service.py::compute_cvar_from_returns` (lines 379–406: `var_loss = np.quantile(losses, confidence, method="higher")`, then `var_loss + u.sum()/((1-confidence)*losses.size)`, returned NEGATIVE in loss-space with a soft `len<5 -> NaN`). We port the **return-space, fail-loud, positive-decimal** variant into the light analytics module to match the sibling `historical_var`/`historical_cvar` conventions.
- Conventions to preserve (risk.py header lines 1–8 + the `historical_var`/`historical_cvar` pattern): result is a **POSITIVE decimal fraction**; `_MIN_TAIL_POINTS = 10` (risk.py line 20) is the min-obs gate; fail loud via `ValueError`; reject NaN/inf via `reject_nan` (imported at risk.py line 17 from `app.analytics._validation`, message contains "NaN"); `confidence` must be in `(0,1)`.
- **Verified numeric fixtures** (each recomputed against the optimizer formula, see commands in the steps):
  - 30-point series in T1C-1: `(1-0.95)·30 = 1.5` (non-integer) ⇒ RU CVaR = `0.025343666666666667`, naive `historical_cvar` = `0.023867` — they diverge by ≈ `0.001477`, RU > naive, proving the swap is observable.
  - 20-point series with `(1-0.95)·20 = 1.0` (integer): RU and naive coincide at `0.073` (single worst observation), the integer-tail edge case.
  - Builder route at the existing `n_obs=500` stub: `(1-α)·T = 25` is an integer, so the two estimators COINCIDE → existing builder tests do NOT regress.
  - Builder route at the T1C-3 `n_obs=30` stub: `(1-α)·T = 1.5` is non-integer; BEFORE the swap the route reports the naive value `0.011884577701881338`; AFTER the swap it reports the RU value `0.012764325546793808`. This is the failing-first signal that proves the builder change (and only the builder change) makes the report optimizer-consistent.

Dependency order: **T1C-1** (add `realized_cvar` analytics fn, TDD) → **T1C-2** (export it from the analytics package; this is when the T1C-1 tests go green) → **T1C-3** (switch the builder in-sample report to it, with a builder-route numeric test that fails first because the builder still reports the tail-mean).

---

### Task T1C-1: Add exact Rockafellar–Uryasev `realized_cvar` to the risk analytics module

**Files:**
- Modify: `backend/app/analytics/risk.py` (add `realized_cvar` immediately after `historical_cvar` ends at line 114, before `max_drawdown` at line 117; reuse module constant `_MIN_TAIL_POINTS` at line 20, `reject_nan` imported at line 17, `np` at line 14, `pd` at line 15)
- Test: `backend/tests/test_analytics_risk.py` (append; file imports from `app.analytics` at lines 9–17, defines `_dated` at lines 20–21 and `_random_returns` at lines 24–26, already imports `historical_cvar`/`historical_var` at lines 14/15)

- [ ] **Step 1: Write the failing tests.** Append the following to `backend/tests/test_analytics_risk.py`. The 30-point literal `0.025343666666666667` and the 20-point `0.073` were computed directly from the optimizer's RU objective and verified.

```python
# --- exact Rockafellar–Uryasev realized_cvar (T1C) ----------------------------

from app.analytics import realized_cvar  # noqa: E402  (export added in T1C-2)


# Fixed 30-point return series: (1-0.95)*30 = 1.5 (non-integer tail) so the
# exact RU estimator DIVERGES from the naive tail-mean historical_cvar.
_RU_SERIES_30 = [
    -0.012459, -0.004381, 0.017143, 0.002922, 0.012363, 0.007902, -0.007874,
    0.007445, -0.003716, -0.003791, 0.001663, -0.019437, 0.015898, -0.008324,
    0.013404, 0.002172, 0.020316, -0.00818, -0.003653, 0.004791, -0.028297,
    0.011163, 0.020441, 0.015048, 0.010212, -0.001498, 0.017065, 0.014362,
    0.005504, 0.000466,
]


def _ru_reference(returns: pd.Series, confidence: float) -> float:
    """Independent RU empirical CVaR, mirroring the optimizer objective.

    Single-asset losses = -returns; CVaR_alpha = var_loss + sum of positive
    excess over the upper-quantile VaR, scaled by 1/((1-alpha)*T). Positive
    decimal fraction (same sign convention as the production estimator).
    """
    losses = -returns.to_numpy(dtype=float)
    t = losses.size
    var_loss = float(np.quantile(losses, confidence, method="higher"))
    excess = np.maximum(losses - var_loss, 0.0)
    return var_loss + float(excess.sum()) / ((1.0 - confidence) * t)


def test_realized_cvar_matches_ru_reference_non_integer_tail() -> None:
    """On a 30-point series (1.5 expected tail obs) realized_cvar equals the
    exact Rockafellar–Uryasev value used by the optimizer objective."""
    returns = _dated(_RU_SERIES_30)
    expected = _ru_reference(returns, 0.95)
    assert realized_cvar(returns, 0.95) == pytest.approx(expected, abs=1e-12)
    # Pin the literal so a regression to tail-mean is caught loudly.
    assert realized_cvar(returns, 0.95) == pytest.approx(
        0.025343666666666667, abs=1e-12
    )


def test_realized_cvar_diverges_from_naive_tail_mean() -> None:
    """The whole point of the swap: with a non-integer expected tail size the
    exact RU estimator differs from the naive historical_cvar tail-mean."""
    returns = _dated(_RU_SERIES_30)
    assert realized_cvar(returns, 0.95) != pytest.approx(
        historical_cvar(returns, 0.95), abs=1e-9
    )
    # naive tail-mean of this series is 0.023867 (mean of the worst 2).
    assert historical_cvar(returns, 0.95) == pytest.approx(0.023867, abs=1e-9)
    assert realized_cvar(returns, 0.95) > historical_cvar(returns, 0.95)


def test_realized_cvar_integer_tail_matches_tail_mean() -> None:
    """Edge case: when (1-alpha)*T is an integer (here 20*0.05 = 1.0) the RU
    estimator and the tail-mean coincide (single worst observation)."""
    returns = _dated(
        [
            0.012, -0.034, 0.008, -0.021, 0.005, -0.058, 0.017, -0.009, 0.003,
            -0.045, 0.022, -0.011, 0.006, -0.073, 0.014, -0.002, 0.019, -0.027,
            0.001, -0.039,
        ]
    )
    assert realized_cvar(returns, 0.95) == pytest.approx(0.073, abs=1e-12)
    assert realized_cvar(returns, 0.95) == pytest.approx(
        historical_cvar(returns, 0.95), abs=1e-12
    )


def test_realized_cvar_at_least_var() -> None:
    """CVaR >= VaR (expected shortfall dominates the threshold)."""
    r = _random_returns(500, seed=17)
    assert realized_cvar(r, 0.95) >= historical_var(r, 0.95)


def test_realized_cvar_positive_for_lossy_series() -> None:
    assert realized_cvar(_random_returns(), 0.95) > 0


def test_realized_cvar_monotonicity() -> None:
    """CVaR(99%) >= CVaR(95%): a deeper tail is at least as costly."""
    r = _random_returns(500, seed=17)
    assert realized_cvar(r, 0.99) >= realized_cvar(r, 0.95)


def test_realized_cvar_short_input_raises() -> None:
    with pytest.raises(ValueError, match="at least 10"):
        realized_cvar(_dated([0.01] * 9))


def test_realized_cvar_bad_confidence_raises() -> None:
    with pytest.raises(ValueError, match="confidence"):
        realized_cvar(_random_returns(), confidence=95.0)


def test_realized_cvar_nan_input_raises() -> None:
    with pytest.raises(ValueError, match="NaN"):
        realized_cvar(_dated([0.01, np.nan, -0.02] + [0.0] * 7))
```

- [ ] **Step 2: Run the tests, expect FAIL.** The import `from app.analytics import realized_cvar` cannot resolve yet (function does not exist in risk.py and is not exported from the package), so collection fails.

  Command:
  ```
  cd backend && python -m pytest tests/test_analytics_risk.py -k realized_cvar -v
  ```
  Expected: collection error — `ImportError: cannot import name 'realized_cvar' from 'app.analytics'`.

- [ ] **Step 3: Write the minimal implementation.** Insert this function in `backend/app/analytics/risk.py` between `historical_cvar` (ends line 114) and `max_drawdown` (line 117). It reuses the already-imported `reject_nan` (line 17), `np` (line 14), `pd` (line 15) and the module constant `_MIN_TAIL_POINTS` (line 20).

```python
def realized_cvar(returns: pd.Series, confidence: float = 0.95) -> float:
    """Exact Rockafellar–Uryasev empirical CVaR as a POSITIVE decimal fraction.

    This is the estimator the min-CVaR optimizer minimizes
    (``app.optimizer.engine.solve_min_cvar``): with single-asset losses
    ``L = -returns`` and ``alpha = confidence``,

        VaR_a  = upper alpha-quantile of L (``np.quantile(L, alpha, method="higher")``)
        CVaR_a = VaR_a + (1/((1-alpha)*T)) * sum(max(L_t - VaR_a, 0))

    At optimality this equals ``min_z [ z + sum(max(L - z, 0))/((1-alpha)*T) ]``,
    i.e. the optimizer's objective value, so the builder's in-sample report is
    consistent with the objective the weights were chosen to minimize. Unlike
    :func:`historical_cvar` (a naive tail-mean), this is exact even when the
    expected tail size ``(1-alpha)*T`` is non-integer.

    Same sign convention as :func:`historical_cvar`: a result of 0.03 means "on
    the worst ~5% of days the conditional expected loss is 3%". Inputs and
    result are decimal fractions (0.05 = 5%), never 0-100.

    Raises:
        ValueError: if ``confidence`` is not in (0, 1), fewer than 10 returns
            are supplied, or the input contains NaN/infinite values.
    """
    if not 0 < confidence < 1:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")
    if len(returns) < _MIN_TAIL_POINTS:
        raise ValueError(
            f"realized_cvar requires at least {_MIN_TAIL_POINTS} returns, got {len(returns)}"
        )
    reject_nan(returns, "realized_cvar")
    losses = -returns.to_numpy(dtype=float)
    t = losses.size
    var_loss = float(np.quantile(losses, confidence, method="higher"))
    excess = np.maximum(losses - var_loss, 0.0)
    cvar = var_loss + float(excess.sum()) / ((1.0 - confidence) * t)
    return cvar
```

- [ ] **Step 4: Verify the implementation in isolation (the pytest run goes green only after T1C-2 adds the package export).** The package import in the new tests still fails until T1C-2, so confirm the function value directly from the module:
  ```
  cd backend && python -c "import pandas as pd; from app.analytics.risk import realized_cvar; print(realized_cvar(pd.Series([-0.012459,-0.004381,0.017143,0.002922,0.012363,0.007902,-0.007874,0.007445,-0.003716,-0.003791,0.001663,-0.019437,0.015898,-0.008324,0.013404,0.002172,0.020316,-0.00818,-0.003653,0.004791,-0.028297,0.011163,0.020441,0.015048,0.010212,-0.001498,0.017065,0.014362,0.005504,0.000466]), 0.95))"
  ```
  Expected stdout: `0.025343666666666667`.

- [ ] **Step 5: Commit.**
  ```
  cd backend && git add app/analytics/risk.py tests/test_analytics_risk.py
  git commit -m "feat(risk): add exact Rockafellar-Uryasev realized_cvar estimator"
  ```
  Commit message footer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T1C-2: Export `realized_cvar` from the analytics package

**Files:**
- Modify: `backend/app/analytics/__init__.py` (the `from app.analytics.risk import (...)` block at lines 30–40; the `__all__` list at lines 47–77)

- [ ] **Step 1: Confirm the test that requires the export still fails.** The T1C-1 tests do `from app.analytics import realized_cvar`. Until the export exists this errors:
  ```
  cd backend && python -m pytest tests/test_analytics_risk.py -k realized_cvar -v
  ```
  Expected: `ImportError: cannot import name 'realized_cvar' from 'app.analytics'`.

- [ ] **Step 2: Add the import.** In `backend/app/analytics/__init__.py`, replace the risk import block (lines 30–40) — which currently is:
  ```python
  from app.analytics.risk import (
      BestWorst,
      DrawdownResult,
      annualized_volatility,
      best_worst_day,
      beta,
      correlation,
      historical_cvar,
      historical_var,
      max_drawdown,
  )
  ```
  with (add `realized_cvar` after `max_drawdown`):
  ```python
  from app.analytics.risk import (
      BestWorst,
      DrawdownResult,
      annualized_volatility,
      best_worst_day,
      beta,
      correlation,
      historical_cvar,
      historical_var,
      max_drawdown,
      realized_cvar,
  )
  ```

- [ ] **Step 3: Add to `__all__`.** In the `__all__` list, replace the existing pair (lines 67–68):
  ```python
      "portfolio_returns",
      "return_histogram",
  ```
  with (insert `"realized_cvar",` in alphabetical order between them):
  ```python
      "portfolio_returns",
      "realized_cvar",
      "return_histogram",
  ```

- [ ] **Step 4: Run the full risk test module, expect PASS.**
  ```
  cd backend && python -m pytest tests/test_analytics_risk.py -v
  ```
  Expected: all tests pass — the 9 new `realized_cvar` tests from T1C-1 plus the 27 pre-existing tests (baseline was 27 green), 36 total, no regressions.

- [ ] **Step 5: Commit.**
  ```
  cd backend && git add app/analytics/__init__.py
  git commit -m "feat(risk): export realized_cvar from analytics package"
  ```
  Commit message footer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

### Task T1C-3: Switch the builder in-sample CVaR report to `realized_cvar` (optimizer-consistent)

**Files:**
- Modify: `backend/app/services/portfolio_builder.py` (import line 36; module docstring lines 17–19; inline comment line 308; in-sample CVaR computation lines 309–313)
- Test: `backend/tests/test_builder_route.py` (append a builder-route numeric test; file exists per commit 27e2487 and already wires the httpx/monkeypatch harness — `_client` at lines 27–30, `_stub_returns` at lines 37–52, `_fund_ref` at lines 33–34, `_FUND_IDS` at line 24)

- [ ] **Step 1: Write the failing test.** Append to `backend/tests/test_builder_route.py`. This is a TRUE builder-route test: it stubs `load_aligned_returns` with a 30-observation matrix (so `(1-0.95)*30 = 1.5` is non-integer and the two estimators differ), POSTs `/builder/optimize`, and asserts the reported `cvar_95_in_sample` equals the exact RU value of the optimizer's own solved portfolio and is NOT the naive tail-mean. It fails first because the builder still reports `historical_cvar`. The independent recomputation re-derives the weights from the IDENTICAL deterministic scenario matrix via `engine.solve_min_cvar`, so it is bit-exact (verified).

```python
# --- T1C: builder in-sample CVaR uses the exact RU estimator ------------------

from app.analytics import historical_cvar, realized_cvar  # noqa: E402
from app.optimizer import engine  # noqa: E402


def _stub_returns_30(monkeypatch: pytest.MonkeyPatch) -> None:
    """30-obs stub: (1-0.95)*30 = 1.5 -> non-integer tail, so the exact RU
    estimator and the naive tail-mean DIFFER (unlike the 500-obs stub where
    25 is integer and they coincide). Identical RNG recipe to _stub_returns."""

    async def fake_load(
        session: Any,
        assets: list[optimizer_data.AssetRef],
        window_days: int = 730,
        today: dt.date | None = None,
    ) -> pd.DataFrame:
        rng = np.random.default_rng(11)
        index = pd.bdate_range("2024-01-02", periods=30)
        data = {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, 30)
            for i, ref in enumerate(assets)
        }
        return pd.DataFrame(data, index=index)

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_builder_reports_ru_in_sample_cvar_not_tail_mean(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The /builder/optimize response reports the exact Rockafellar–Uryasev
    in-sample CVaR (consistent with the min-CVaR objective), not the naive
    tail-mean. The two differ on this 30-obs (non-integer tail) fixture."""
    _stub_returns_30(monkeypatch)
    payload = {
        "assets": [_fund_ref(i) for i in range(4)],
        "objective": "min_cvar",
    }
    async with _client() as client:
        response = await client.post("/builder/optimize", json=payload)
    assert response.status_code == 200, response.text
    reported = response.json()["expected"]["cvar_95_in_sample"]
    assert response.json()["diagnostics"]["n_obs"] == 30

    # Reconstruct the builder's post-solve report from the IDENTICAL stub: same
    # RNG -> same scenarios -> deterministic solve -> portfolio_daily.
    rng = np.random.default_rng(11)
    index = pd.bdate_range("2024-01-02", periods=30)
    refs = [
        optimizer_data.FundAssetRef(id=_FUND_IDS[i]) for i in range(4)
    ]
    frame = pd.DataFrame(
        {
            ref.label: rng.normal(0.0003, 0.008 + 0.002 * i, 30)
            for i, ref in enumerate(refs)
        },
        index=index,
    )
    scenarios = frame.to_numpy(dtype=float)
    weights, status = engine.solve_min_cvar(scenarios, cap=0.25, min_weight=None)
    assert status == "optimal"
    portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)

    ru = realized_cvar(portfolio_daily, confidence=0.95)
    naive = historical_cvar(portfolio_daily, confidence=0.95)

    # The estimators disagree on this fixture (the swap is observable).
    assert ru != pytest.approx(naive, abs=1e-9)
    # The builder reports the RU value (optimizer-consistent), not the tail-mean.
    assert reported == pytest.approx(ru, abs=1e-12)
    assert reported != pytest.approx(naive, abs=1e-9)
```

- [ ] **Step 2: Run the test, expect FAIL.** Before the builder swap the route still computes `historical_cvar` (the naive tail-mean = `0.011884577701881338`), while the test demands the RU value (`0.012764325546793808`), so the `reported == pytest.approx(ru)` assertion fails (and `reported != naive` fails too). `optimizer_data.FundAssetRef` already exists (`portfolio_builder._to_data_ref` constructs it at line 93). Command:
  ```
  cd backend && python -m pytest tests/test_builder_route.py::test_builder_reports_ru_in_sample_cvar_not_tail_mean -v
  ```
  Expected: FAIL on `assert reported == pytest.approx(ru, abs=1e-12)` — reported `0.011884577701881338` (naive) vs ru `0.012764325546793808`.

  Confirm the fixture discriminates (RU != naive) with a direct value print:
  ```
  cd backend && python -c "import numpy as np, pandas as pd; from app.analytics import realized_cvar, historical_cvar; from app.optimizer import engine; rng=np.random.default_rng(11); idx=pd.bdate_range('2024-01-02',periods=30); f=pd.DataFrame({i: rng.normal(0.0003,0.008+0.002*i,30) for i in range(4)}, index=idx); s=f.to_numpy(float); w,_=engine.solve_min_cvar(s,cap=0.25,min_weight=None); pdl=pd.Series(s@w,index=idx); print('ru=',realized_cvar(pdl,0.95),'naive=',historical_cvar(pdl,0.95))"
  ```
  Expected: two DIFFERENT numbers (`ru= 0.012764325546793808 naive= 0.011884577701881338`).

- [ ] **Step 3: Apply the builder change.** Three edits in `backend/app/services/portfolio_builder.py`.

  Edit 3a — import (line 36): replace
  ```python
  from app.analytics import historical_cvar
  ```
  with
  ```python
  from app.analytics import realized_cvar
  ```

  Edit 3b — the inline comment + computation (lines 308–313). Replace
  ```python
      # In-sample CVaR on RAW scenarios, F3 estimator (gate G3 comparability).
      portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)
      try:
          cvar_95 = historical_cvar(portfolio_daily, confidence=0.95)
      except ValueError as exc:
          raise BuilderError(f"in-sample CVaR undefined: {exc}") from exc
  ```
  with
  ```python
      # In-sample CVaR on RAW scenarios using the EXACT Rockafellar–Uryasev
      # estimator (app.analytics.realized_cvar) — the same objective the
      # min-CVaR optimizer minimizes — so the reported figure is consistent
      # with how the weights were chosen (T1C). alpha=0.95 matches
      # engine.DEFAULT_CVAR_ALPHA.
      portfolio_daily = pd.Series(scenarios @ weights, index=frame.index)
      try:
          cvar_95 = realized_cvar(portfolio_daily, confidence=0.95)
      except ValueError as exc:
          raise BuilderError(f"in-sample CVaR undefined: {exc}") from exc
  ```

  Edit 3c — module docstring (lines 17–19). Replace
  ```python
  In-sample CVaR of the proposal is computed from the RAW scenarios (never the
  re-centered ones) with the SAME F3 estimator (``app.analytics.historical_cvar``)
  so it is directly comparable with portfolio-analysis numbers (gate G3).
  ```
  with
  ```python
  In-sample CVaR of the proposal is computed from the RAW scenarios (never the
  re-centered ones) with the EXACT Rockafellar–Uryasev estimator
  (``app.analytics.realized_cvar``, alpha=0.95) — the same objective
  ``engine.solve_min_cvar`` minimizes — so the reported figure is consistent
  with how the weights were chosen.
  ```

- [ ] **Step 4: Run the new test plus the builder and risk suites, expect PASS (no regressions).**
  ```
  cd backend && python -m pytest tests/test_builder_route.py tests/test_analytics_risk.py -v
  ```
  Expected: the new `test_builder_reports_ru_in_sample_cvar_not_tail_mean` passes (`reported == ru`, `reported != naive`), and the 18 pre-existing builder-route tests plus the 36 risk tests stay green. The existing `test_optimize_min_cvar_no_views_happy_path` (n_obs=500, integer tail) is unaffected because RU and naive coincide there. Then confirm the builder is wired to `realized_cvar`:
  ```
  cd backend && python -c "import app.services.portfolio_builder as b; assert hasattr(b, 'realized_cvar'); assert not hasattr(b, 'historical_cvar'); print('builder wired to realized_cvar OK')"
  ```
  Expected stdout: `builder wired to realized_cvar OK`.

- [ ] **Step 5: Commit.**
  ```
  cd backend && git add app/services/portfolio_builder.py tests/test_builder_route.py
  git commit -m "fix(builder): report exact RU in-sample CVaR consistent with optimizer objective"
  ```
  Commit message footer:
  ```
  Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
  ```

---

## Tier 1 — Serving layer for regional macro scorecards + global indicators + treasury fiscal data

This cluster adds three DB-first reader endpoints over data-lake tables that are already materialized by the workers (`investintell-datalake-workers`): `macro_regional_snapshots` (regional scorecards + global indicators, written by `macro_ingestion`) and `treasury_data` (fiscal series, written by `treasury_ingestion`). The Light only READS — no FRED/Treasury API calls, no scoring math in any request path. Everything mirrors the established DB-first reader style of `backend/app/services/macro_regime.py` (frozen dataclass + `text()` SQL + `await datalake.execute(...).first()`/`.all()`) and `backend/app/services/lookthrough.py` (same shape, grouping rows in Python and returning `None`/empty when nothing is materialized so the route maps to 404). Gate G5 (μ-free optimizer) is unaffected: none of these readers touch the optimizer; they expose macro/fiscal observations only.

Verified facts (read the WORKER SOURCE that writes the tables — authoritative for the contract — plus the LIGHT reader/route/test patterns; live-DB read was not available this session, see open_questions):
- `macro_ingestion.build_regional_snapshot` (E:/investintell-datalake-workers/src/workers/macro_ingestion.py, lines 727-754) writes `data_json` shape (version 1): `{"version": 1, "as_of_date": "YYYY-MM-DD", "regions": {"US"|"EUROPE"|"ASIA"|"EM": {"composite_score": float, "coverage": float, "dimensions": {<dim>: {"score": float, "n_indicators": int, "indicators": {<series_id>: float}}}, "data_freshness": {<series_id>: {"last_date": "YYYY-MM-DD"|null, "days_stale": int|null, "weight": float, "status": "fresh"|"decaying"|"stale"}}}}, "global_indicators": {"geopolitical_risk_score": float, "energy_stress": float, "commodity_stress": float, "usd_strength": float}}` (the four global keys are exactly the dict returned by `score_global_indicators`, lines 700-724). `upsert_snapshot` (lines 815-824) writes columns `as_of_date`, `data_json`, `created_by`/`updated_by` with conflict key `(as_of_date)`, so `as_of_date` is unique and the latest is `ORDER BY as_of_date DESC LIMIT 1`.
- `treasury_ingestion.upsert_treasury_data` (E:/investintell-datalake-workers/src/workers/treasury_ingestion.py, lines 255-275) writes columns `obs_date`, `series_id`, `value`, `source`, `metadata_json` with conflict key `(obs_date, series_id)`. Series-id prefixes are `RATE_`/`DEBT_`/`AUCTION_`/`FX_`/`INTEREST_` (the five `_ROW_BUILDERS`, lines 109-183). DEBT_ ids are `DEBT_TOTAL_PUBLIC`/`DEBT_INTRAGOV`/`DEBT_HELD_PUBLIC` (lines 120-124). AUCTION_ rows carry `metadata_json = {"security_type", "security_term", "bid_to_cover"?}` (`rows_from_auctions`, lines 136-149); other prefixes pass `metadata=None`.
- LIGHT wiring: `backend/app/main.py` imports `from app.api.routes import macro as macro_router` (line 10) and `from app.api.routes import stocks as stocks_router` (line 17); registers `application.include_router(macro_router.router)` (line 59) and `application.include_router(rebalance_router.router)` (line 60). `backend/app/api/routes/macro.py` already defines `router = APIRouter(tags=["macro"])` (line 24) and already imports `Annotated` (line 10), `APIRouter, Depends, HTTPException` (line 12), `AsyncSession` (line 13), `get_datalake_session` (line 15), and `from app.services import macro_regime` (line 22) — so the new handlers only need two extra import lines (the new schemas + the new service). The datalake dependency is `app.core.datalake.get_datalake_session`.
- Test infra: `backend/pyproject.toml` line 53 sets `asyncio_mode = "auto"` (pytest-asyncio) AND `anyio` is installed, so route tests use the `@pytest.mark.anyio` marker exactly like `backend/tests/test_macro_regime_route.py` and `backend/tests/test_lookthrough.py` (both verified to use `import pytest` + `@pytest.mark.anyio`). Route tests build the app with `create_app()`, override `get_datalake_session` with `lambda: None`, then `monkeypatch.setattr` the service fetcher at its canonical module. Service unit tests use a tiny fake async session whose `.execute()` returns an object exposing `.first()`/`.all()`; this mirrors `_FakeResult`/`_FakeSession` in `backend/tests/test_optimizer_data.py` (lines 22-41) and run unmarked under auto mode.

Order: T1D-1 (macro scorecards service) → T1D-2 (macro scorecards schemas + routes on the existing macro router) → T1D-3 (treasury fiscal service) → T1D-4 (treasury fiscal schemas + new treasury router + main.py wiring).

---

### Task T1D-1: DB-first reader service for regional macro scorecards + global indicators

**Files:**
- Create: `backend/app/services/macro_scorecards.py`
- Test: `backend/tests/test_macro_scorecards_service.py`

This service reads the latest `macro_regional_snapshots` row and parses `data_json` into frozen dataclasses. It is a pure SQL reader (no scoring) returning `None` when no snapshot is materialized, mirroring `macro_regime.fetch_composite_regime` (`backend/app/services/macro_regime.py` lines 160-194: `text()` SELECT → `.first()` → `None` guard → build frozen dataclass).

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_macro_scorecards_service.py` with the COMPLETE code below. It uses a fake async session that returns the latest snapshot row (mirroring `_FakeResult`/`_FakeSession` in `backend/tests/test_optimizer_data.py`, but with `.first()` since the SQL has `LIMIT 1`). Async tests run unmarked under `asyncio_mode = "auto"` (matches `test_optimizer_data.py`).

```python
"""Unit tests for app/services/macro_scorecards.py (DB-first snapshot reader).

The regional scorecard + global indicators are COMPUTED by the macro_ingestion
worker (repo investintell-datalake-workers, build_regional_snapshot) and
materialized into macro_regional_snapshots.data_json (version 1). The Light only
READS the latest row and parses it — no scoring here. A fake async session feeds
canned rows; no live cloud, no live DB.
"""

import datetime as dt
from typing import Any

from app.services import macro_scorecards as ms

_DATA_JSON: dict[str, Any] = {
    "version": 1,
    "as_of_date": "2026-06-14",
    "regions": {
        "US": {
            "composite_score": 47.72,
            "coverage": 0.85,
            "dimensions": {
                "growth": {
                    "score": 57.93,
                    "n_indicators": 4,
                    "indicators": {"CFNAI": 68.07, "PAYEMS": 100.0},
                },
            },
            "data_freshness": {
                "CPIAUCSL": {
                    "last_date": "2026-05-31",
                    "days_stale": 14,
                    "weight": 1.0,
                    "status": "fresh",
                },
                "JTSJOL": {
                    "last_date": None,
                    "days_stale": None,
                    "weight": 0.0,
                    "status": "stale",
                },
            },
        },
        "EUROPE": {
            "composite_score": 52.10,
            "coverage": 0.60,
            "dimensions": {},
            "data_freshness": {},
        },
    },
    "global_indicators": {
        "geopolitical_risk_score": 81.51,
        "energy_stress": 55.59,
        "commodity_stress": 100.0,
        "usd_strength": 54.36,
    },
}


class _FakeResult:
    def __init__(self, row: Any) -> None:
        self._row = row

    def first(self) -> Any:
        return self._row


class _FakeRow:
    def __init__(self, as_of_date: dt.date, data_json: dict[str, Any]) -> None:
        self.as_of_date = as_of_date
        self.data_json = data_json


class _FakeSession:
    def __init__(self, row: Any) -> None:
        self._row = row
        self.executed = 0

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.executed += 1
        return _FakeResult(self._row)


async def test_fetch_macro_scorecards_parses_latest_snapshot() -> None:
    session = _FakeSession(_FakeRow(dt.date(2026, 6, 14), _DATA_JSON))
    result = await ms.fetch_macro_scorecards(session)  # type: ignore[arg-type]
    assert result is not None
    assert result.as_of_date == dt.date(2026, 6, 14)
    assert set(result.regions) == {"US", "EUROPE"}
    us = result.regions["US"]
    assert us.region == "US"
    assert us.composite_score == 47.72
    assert us.coverage == 0.85
    growth = us.dimensions["growth"]
    assert growth.score == 57.93
    assert growth.n_indicators == 4
    assert growth.indicators["PAYEMS"] == 100.0
    fresh = us.data_freshness["CPIAUCSL"]
    assert fresh.last_date == dt.date(2026, 5, 31)
    assert fresh.days_stale == 14
    assert fresh.weight == 1.0
    assert fresh.status == "fresh"
    stale = us.data_freshness["JTSJOL"]
    assert stale.last_date is None
    assert stale.days_stale is None
    assert stale.status == "stale"
    g = result.global_indicators
    assert g.geopolitical_risk_score == 81.51
    assert g.energy_stress == 55.59
    assert g.commodity_stress == 100.0
    assert g.usd_strength == 54.36


async def test_fetch_macro_scorecards_none_when_not_materialized() -> None:
    session = _FakeSession(None)
    assert await ms.fetch_macro_scorecards(session) is None  # type: ignore[arg-type]


async def test_fetch_macro_scorecards_tolerates_missing_freshness_keys() -> None:
    minimal = {
        "version": 1,
        "as_of_date": "2026-06-14",
        "regions": {
            "ASIA": {
                "composite_score": 50.0,
                "coverage": 0.0,
                "dimensions": {},
                "data_freshness": {
                    "X": {"weight": 0.5, "status": "decaying"},
                },
            },
        },
        "global_indicators": {
            "geopolitical_risk_score": 50.0,
            "energy_stress": 50.0,
            "commodity_stress": 50.0,
            "usd_strength": 50.0,
        },
    }
    session = _FakeSession(_FakeRow(dt.date(2026, 6, 14), minimal))
    result = await ms.fetch_macro_scorecards(session)  # type: ignore[arg-type]
    assert result is not None
    fr = result.regions["ASIA"].data_freshness["X"]
    assert fr.last_date is None
    assert fr.days_stale is None
    assert fr.weight == 0.5
    assert fr.status == "decaying"
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_macro_scorecards_service.py -v`. Expected failure: `ModuleNotFoundError: No module named 'app.services.macro_scorecards'` (the service file does not exist yet — verified absent under `backend/app/services/`).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/services/macro_scorecards.py` with the COMPLETE code below. It mirrors `macro_regime.py`: a `text()` SELECT with `ORDER BY as_of_date DESC LIMIT 1`, `.first()`, return `None` when missing, parse `data_json` into frozen dataclasses. `_parse_date` tolerates `None`/missing keys (fail-loud is N/A here: the worker is the producer and guarantees the shape; the parser only defends against optional keys absent in older vintages).

```python
"""Regional macro scorecard reader (Tier 1 serving layer — DB-first).

Reads the latest version-1 snapshot materialized by the ``macro_ingestion``
worker (repo investintell-datalake-workers, ``build_regional_snapshot``) into
``macro_regional_snapshots.data_json``, and parses it into frozen dataclasses.
No scoring here — the percentile-rank composites, staleness weights and global
indicators are all produced offline by the worker; the Light only READS.

data_json (version 1) shape, verbatim from the worker's
``build_regional_snapshot``:
  {"version": 1, "as_of_date": "YYYY-MM-DD",
   "regions": {<REGION>: {"composite_score", "coverage",
       "dimensions": {<dim>: {"score", "n_indicators", "indicators": {...}}},
       "data_freshness": {<series_id>: {"last_date", "days_stale",
                                        "weight", "status"}}}},
   "global_indicators": {"geopolitical_risk_score", "energy_stress",
                         "commodity_stress", "usd_strength"}}
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


@dataclass(frozen=True)
class DimensionScore:
    score: float
    n_indicators: int
    indicators: dict[str, float]


@dataclass(frozen=True)
class DataFreshness:
    last_date: dt.date | None
    days_stale: int | None
    weight: float
    status: str


@dataclass(frozen=True)
class RegionScorecard:
    region: str
    composite_score: float
    coverage: float
    dimensions: dict[str, DimensionScore]
    data_freshness: dict[str, DataFreshness]


@dataclass(frozen=True)
class GlobalIndicators:
    geopolitical_risk_score: float
    energy_stress: float
    commodity_stress: float
    usd_strength: float


@dataclass(frozen=True)
class MacroScorecards:
    as_of_date: dt.date
    regions: dict[str, RegionScorecard]
    global_indicators: GlobalIndicators


_LATEST_SQL = text("""
    SELECT as_of_date, data_json
    FROM macro_regional_snapshots
    ORDER BY as_of_date DESC
    LIMIT 1
""")


def _parse_date(value: Any) -> dt.date | None:
    if value is None:
        return None
    if isinstance(value, dt.date):
        return value
    return dt.date.fromisoformat(str(value))


def _parse_dimension(raw: dict[str, Any]) -> DimensionScore:
    return DimensionScore(
        score=float(raw.get("score", 0.0)),
        n_indicators=int(raw.get("n_indicators", 0)),
        indicators={k: float(v) for k, v in (raw.get("indicators") or {}).items()},
    )


def _parse_freshness(raw: dict[str, Any]) -> DataFreshness:
    days = raw.get("days_stale")
    return DataFreshness(
        last_date=_parse_date(raw.get("last_date")),
        days_stale=int(days) if days is not None else None,
        weight=float(raw.get("weight", 0.0)),
        status=str(raw.get("status", "stale")),
    )


def _parse_region(name: str, raw: dict[str, Any]) -> RegionScorecard:
    return RegionScorecard(
        region=name,
        composite_score=float(raw.get("composite_score", 50.0)),
        coverage=float(raw.get("coverage", 0.0)),
        dimensions={
            dim: _parse_dimension(d) for dim, d in (raw.get("dimensions") or {}).items()
        },
        data_freshness={
            sid: _parse_freshness(f)
            for sid, f in (raw.get("data_freshness") or {}).items()
        },
    )


async def fetch_macro_scorecards(datalake: AsyncSession) -> MacroScorecards | None:
    """Latest materialized regional scorecards + global indicators, or None."""
    latest = (await datalake.execute(_LATEST_SQL)).first()
    if latest is None:
        return None
    data = latest.data_json or {}
    gi = data.get("global_indicators") or {}
    return MacroScorecards(
        as_of_date=_parse_date(latest.as_of_date) or _parse_date(data.get("as_of_date")),
        regions={
            name: _parse_region(name, raw)
            for name, raw in (data.get("regions") or {}).items()
        },
        global_indicators=GlobalIndicators(
            geopolitical_risk_score=float(gi.get("geopolitical_risk_score", 50.0)),
            energy_stress=float(gi.get("energy_stress", 50.0)),
            commodity_stress=float(gi.get("commodity_stress", 50.0)),
            usd_strength=float(gi.get("usd_strength", 50.0)),
        ),
    )
```

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_macro_scorecards_service.py -v`. Expected: 3 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/services/macro_scorecards.py tests/test_macro_scorecards_service.py && git commit -m "feat(macro): DB-first reader for regional scorecards + global indicators"`

---

### Task T1D-2: Pydantic schemas + GET /macro/regional and /macro/global-indicators routes

**Files:**
- Create: `backend/app/schemas/macro_scorecards.py`
- Modify: `backend/app/api/routes/macro.py` (add two imports + append two route handlers; the router already exists at line 24, `router = APIRouter(tags=["macro"])`)
- Test: `backend/tests/test_macro_scorecards_route.py`

Two thin endpoints on the existing macro router that call the T1D-1 service and map `None` → 404, mirroring `get_macro_regime` in the same file (`backend/app/api/routes/macro.py` lines 29-70: `Annotated[AsyncSession, Depends(get_datalake_session)]` param, `None` → `HTTPException(status_code=404, ...)`).

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_macro_scorecards_route.py` with the COMPLETE code below. It builds the app with `create_app()`, overrides `get_datalake_session` with `lambda: None`, and monkeypatches the service fetcher at `app.services.macro_scorecards` (pattern in `backend/tests/test_macro_regime_route.py`, including `import pytest` + `@pytest.mark.anyio`).

```python
"""Tests for GET /macro/regional and GET /macro/global-indicators.

The scorecards are materialized by the macro_ingestion worker into
macro_regional_snapshots; the Light only reads. Service stubbed at its canonical
module — no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import macro_scorecards as ms


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _scorecards() -> ms.MacroScorecards:
    return ms.MacroScorecards(
        as_of_date=dt.date(2026, 6, 14),
        regions={
            "US": ms.RegionScorecard(
                region="US",
                composite_score=47.72,
                coverage=0.85,
                dimensions={
                    "growth": ms.DimensionScore(
                        score=57.93, n_indicators=4,
                        indicators={"PAYEMS": 100.0},
                    ),
                },
                data_freshness={
                    "CPIAUCSL": ms.DataFreshness(
                        last_date=dt.date(2026, 5, 31), days_stale=14,
                        weight=1.0, status="fresh",
                    ),
                },
            ),
        },
        global_indicators=ms.GlobalIndicators(
            geopolitical_risk_score=81.51,
            energy_stress=55.59,
            commodity_stress=100.0,
            usd_strength=54.36,
        ),
    )


@pytest.mark.anyio
async def test_regional_returns_scorecards(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return _scorecards()

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regional")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of_date"] == "2026-06-14"
    us = body["regions"]["US"]
    assert us["composite_score"] == 47.72
    assert us["coverage"] == 0.85
    assert us["dimensions"]["growth"]["score"] == 57.93
    assert us["dimensions"]["growth"]["indicators"]["PAYEMS"] == 100.0
    fr = us["data_freshness"]["CPIAUCSL"]
    assert fr["last_date"] == "2026-05-31"
    assert fr["status"] == "fresh"


@pytest.mark.anyio
async def test_global_indicators_returns_scores(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return _scorecards()

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/global-indicators")
    assert resp.status_code == 200
    body = resp.json()
    assert body["as_of_date"] == "2026-06-14"
    assert body["geopolitical_risk_score"] == 81.51
    assert body["energy_stress"] == 55.59
    assert body["commodity_stress"] == 100.0
    assert body["usd_strength"] == 54.36


@pytest.mark.anyio
async def test_regional_404_when_not_materialized(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/regional")
    assert resp.status_code == 404
    assert "macro_ingestion" in resp.json()["detail"]


@pytest.mark.anyio
async def test_global_indicators_404_when_not_materialized(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_fetch(datalake):
        return None

    monkeypatch.setattr(ms, "fetch_macro_scorecards", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/global-indicators")
    assert resp.status_code == 404
    assert "macro_ingestion" in resp.json()["detail"]
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_macro_scorecards_route.py -v`. Expected failure: the two GET routes do not exist yet, so every request returns 404 with FastAPI's default `{"detail":"Not Found"}` — the 200 assertions fail and the 404 tests fail because the body lacks `"macro_ingestion"`.

- [ ] **Step 3a: Write the schemas.** Create `backend/app/schemas/macro_scorecards.py` with the COMPLETE code below.

```python
"""Response schemas for GET /macro/regional and /macro/global-indicators.

Mirrors the version-1 macro_regional_snapshots.data_json materialized by the
macro_ingestion worker. dimensions/data_freshness are open maps because the
worker's indicator keys vary by region/vintage (free-form series_id → score):
US growth carries CFNAI/INDPRO/PAYEMS; the BIS credit_cycle dimension carries
credit_gap/debt_service/property_prices; the IMF-blended fiscal dimension carries
fiscal_balance/government_debt (see macro_ingestion._enrich_region).
"""

import datetime as dt

from pydantic import BaseModel


class DimensionOut(BaseModel):
    score: float  # 0-100 composite of indicators in this dimension
    n_indicators: int
    indicators: dict[str, float]  # series_id → 0-100 percentile-rank score


class DataFreshnessOut(BaseModel):
    last_date: dt.date | None
    days_stale: int | None
    weight: float  # 0.0-1.0 staleness-adjusted weight
    status: str  # 'fresh' | 'decaying' | 'stale'


class RegionScorecardOut(BaseModel):
    region: str  # 'US' | 'EUROPE' | 'ASIA' | 'EM'
    composite_score: float  # 0-100 (50 = historical median; neutral on low coverage)
    coverage: float  # 0-1 fraction of total dimension weight with data
    dimensions: dict[str, DimensionOut]
    data_freshness: dict[str, DataFreshnessOut]


class MacroRegionalResponse(BaseModel):
    """Latest regional macro scorecards (worker macro_ingestion, DB-first)."""

    as_of_date: dt.date
    regions: dict[str, RegionScorecardOut]


class GlobalIndicatorsResponse(BaseModel):
    """Global macro risk indicators (0-100; higher score = better conditions)."""

    as_of_date: dt.date
    geopolitical_risk_score: float
    energy_stress: float
    commodity_stress: float
    usd_strength: float
```

- [ ] **Step 3b: Append the routes.** Add the two import lines below to `backend/app/api/routes/macro.py`. Place them immediately after the existing service import at line 22 (`from app.services import macro_regime`). All other names used by the handlers (`Annotated`, `Depends`, `HTTPException`, `AsyncSession`, `get_datalake_session`) are already imported at the top of the file (lines 10-15), so no other import changes are needed.

```python
from app.schemas.macro_scorecards import (
    DataFreshnessOut,
    DimensionOut,
    GlobalIndicatorsResponse,
    MacroRegionalResponse,
    RegionScorecardOut,
)
from app.services import macro_scorecards
```

Then append at the end of the file (after the existing `get_macro_regime` handler, which ends at line 70):

```python
_NOT_MATERIALIZED = (
    "Macro scorecards not materialized — the macro_ingestion worker has not "
    "populated macro_regional_snapshots yet."
)


@router.get("/macro/regional", response_model=MacroRegionalResponse)
async def get_macro_regional(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> MacroRegionalResponse:
    """Latest regional macro scorecards (composite + dimensions + freshness)."""
    snap = await macro_scorecards.fetch_macro_scorecards(datalake)
    if snap is None:
        raise HTTPException(status_code=404, detail=_NOT_MATERIALIZED)
    return MacroRegionalResponse(
        as_of_date=snap.as_of_date,
        regions={
            name: RegionScorecardOut(
                region=r.region,
                composite_score=r.composite_score,
                coverage=r.coverage,
                dimensions={
                    dim: DimensionOut(
                        score=d.score,
                        n_indicators=d.n_indicators,
                        indicators=d.indicators,
                    )
                    for dim, d in r.dimensions.items()
                },
                data_freshness={
                    sid: DataFreshnessOut(
                        last_date=f.last_date,
                        days_stale=f.days_stale,
                        weight=f.weight,
                        status=f.status,
                    )
                    for sid, f in r.data_freshness.items()
                },
            )
            for name, r in snap.regions.items()
        },
    )


@router.get("/macro/global-indicators", response_model=GlobalIndicatorsResponse)
async def get_macro_global_indicators(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
) -> GlobalIndicatorsResponse:
    """Latest global macro risk indicators (geopolitical/energy/commodity/USD)."""
    snap = await macro_scorecards.fetch_macro_scorecards(datalake)
    if snap is None:
        raise HTTPException(status_code=404, detail=_NOT_MATERIALIZED)
    g = snap.global_indicators
    return GlobalIndicatorsResponse(
        as_of_date=snap.as_of_date,
        geopolitical_risk_score=g.geopolitical_risk_score,
        energy_stress=g.energy_stress,
        commodity_stress=g.commodity_stress,
        usd_strength=g.usd_strength,
    )
```

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_macro_scorecards_route.py -v`. Expected: 4 passed. Then run the existing macro regime route test to confirm no regression: `cd backend && python -m pytest tests/test_macro_regime_route.py -v` — expected all pass (the router import and the prior `/macro/regime` route are untouched).

- [ ] **Step 5: Commit.** `cd backend && git add app/schemas/macro_scorecards.py app/api/routes/macro.py tests/test_macro_scorecards_route.py && git commit -m "feat(macro): GET /macro/regional + /macro/global-indicators serving endpoints"`

---

### Task T1D-3: DB-first reader service for treasury fiscal series

**Files:**
- Create: `backend/app/services/treasury_fiscal.py`
- Test: `backend/tests/test_treasury_fiscal_service.py`

Reads `treasury_data` filtered by series-id prefix over a lookback window, returning per-series time series with the auction `metadata_json` passed through. Pure SQL reader, mirroring `lookthrough.fetch_many_lookthroughs` (`backend/app/services/lookthrough.py` lines 156-192: one `text()` query, `.all()`, group rows in Python). Returns an empty `FiscalData` (no rows) rather than `None` so the route layer can distinguish "configured but empty" and map emptiness to 404 (T1D-4).

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_treasury_fiscal_service.py` with the COMPLETE code below. The fake session captures the bound params and returns canned rows. Async tests run unmarked under `asyncio_mode = "auto"`.

```python
"""Unit tests for app/services/treasury_fiscal.py (DB-first treasury reader).

treasury_data is materialized by the treasury_ingestion worker (repo
investintell-datalake-workers, rows_from_*/upsert_treasury_data). The Light only
READS, filtered by series_id prefix over a lookback window. A fake async session
feeds canned rows; no live DB.
"""

import datetime as dt
from typing import Any

from app.services import treasury_fiscal as tf


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeRow:
    def __init__(self, series_id: str, obs_date: dt.date, value: float,
                 metadata_json: dict[str, Any] | None = None) -> None:
        self.series_id = series_id
        self.obs_date = obs_date
        self.value = value
        self.metadata_json = metadata_json


class _FakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows
        self.params: dict[str, Any] | None = None

    async def execute(self, stmt: Any, params: Any = None) -> _FakeResult:
        self.params = params
        return _FakeResult(self._rows)


async def test_fetch_treasury_series_groups_by_series_id() -> None:
    rows = [
        _FakeRow("RATE_TREASURY_BILLS", dt.date(2026, 5, 1), 5.05),
        _FakeRow("RATE_TREASURY_BILLS", dt.date(2026, 6, 1), 5.10),
        _FakeRow("RATE_TREASURY_NOTES", dt.date(2026, 6, 1), 4.20),
    ]
    session = _FakeSession(rows)
    result = await tf.fetch_treasury_series(
        session, prefix="RATE_", lookback_days=365,  # type: ignore[arg-type]
    )
    assert result.prefix == "RATE_"
    assert {s.series_id for s in result.series} == {
        "RATE_TREASURY_BILLS", "RATE_TREASURY_NOTES"
    }
    bills = next(s for s in result.series if s.series_id == "RATE_TREASURY_BILLS")
    # The SQL orders ascending by date within a series; the service preserves order.
    assert [p.obs_date for p in bills.points] == [
        dt.date(2026, 5, 1), dt.date(2026, 6, 1)
    ]
    assert [p.value for p in bills.points] == [5.05, 5.10]
    assert bills.points[0].metadata is None


async def test_fetch_treasury_series_passes_metadata_through() -> None:
    meta = {"security_type": "Bond", "security_term": "30-Year", "bid_to_cover": 2.4}
    rows = [_FakeRow("AUCTION_BOND_30_YEAR", dt.date(2026, 6, 11), 5.02, meta)]
    session = _FakeSession(rows)
    result = await tf.fetch_treasury_series(
        session, prefix="AUCTION_", lookback_days=365,  # type: ignore[arg-type]
    )
    pt = result.series[0].points[0]
    assert pt.metadata == meta
    assert pt.value == 5.02


async def test_fetch_treasury_series_cutoff_uses_lookback(monkeypatch) -> None:
    monkeypatch.setattr(tf, "_today", lambda: dt.date(2026, 6, 14))
    session = _FakeSession([])
    result = await tf.fetch_treasury_series(
        session, prefix="DEBT_", lookback_days=30,  # type: ignore[arg-type]
    )
    assert result.series == []
    assert session.params["prefix"] == "DEBT_%"
    assert session.params["cutoff"] == dt.date(2026, 5, 15)
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_treasury_fiscal_service.py -v`. Expected failure: `ModuleNotFoundError: No module named 'app.services.treasury_fiscal'` (verified absent under `backend/app/services/`).

- [ ] **Step 3: Write the minimal implementation.** Create `backend/app/services/treasury_fiscal.py` with the COMPLETE code below. The `LIKE :prefix` filter mirrors the worker's prefixed series ids (`treasury_ingestion._series_id`); `_today()` is a seam for the cutoff test; rows are grouped by `series_id` and the SQL `ORDER BY series_id ASC, obs_date ASC` keeps points ascending by date within each series.

```python
"""Treasury fiscal-data reader (Tier 1 serving layer — DB-first).

Reads the treasury_data table materialized by the treasury_ingestion worker
(repo investintell-datalake-workers, rows_from_*/upsert_treasury_data): five
Fiscal Data endpoints mapped to prefixed series ids
(RATE_/DEBT_/AUCTION_/FX_/INTEREST_). The Light only READS, filtered by
series_id prefix over a lookback window; auction metadata_json
(security_type/security_term/bid_to_cover) is passed through unchanged.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

VALID_PREFIXES = ("RATE_", "DEBT_", "AUCTION_", "FX_", "INTEREST_")


@dataclass(frozen=True)
class FiscalPoint:
    obs_date: dt.date
    value: float
    metadata: dict[str, Any] | None


@dataclass(frozen=True)
class FiscalSeries:
    series_id: str
    points: list[FiscalPoint]


@dataclass(frozen=True)
class FiscalData:
    prefix: str
    series: list[FiscalSeries]


_SERIES_SQL = text("""
    SELECT series_id, obs_date, value, metadata_json
    FROM treasury_data
    WHERE series_id LIKE :prefix
      AND obs_date >= :cutoff
      AND value IS NOT NULL
    ORDER BY series_id ASC, obs_date ASC
""")


def _today() -> dt.date:
    return dt.date.today()


async def fetch_treasury_series(
    datalake: AsyncSession, *, prefix: str, lookback_days: int
) -> FiscalData:
    """All treasury_data series for one prefix over the lookback window.

    Empty ``series`` means nothing materialized for that prefix/window — the
    route maps that to 404. Rows are grouped per series_id, ascending by date.
    """
    cutoff = _today() - dt.timedelta(days=lookback_days)
    rows = (
        await datalake.execute(
            _SERIES_SQL, {"prefix": f"{prefix}%", "cutoff": cutoff}
        )
    ).all()

    grouped: dict[str, list[FiscalPoint]] = {}
    for r in rows:
        grouped.setdefault(r.series_id, []).append(
            FiscalPoint(
                obs_date=r.obs_date,
                value=float(r.value),
                metadata=r.metadata_json,
            )
        )
    return FiscalData(
        prefix=prefix,
        series=[
            FiscalSeries(series_id=sid, points=points)
            for sid, points in grouped.items()
        ],
    )
```

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_treasury_fiscal_service.py -v`. Expected: 3 passed.

- [ ] **Step 5: Commit.** `cd backend && git add app/services/treasury_fiscal.py tests/test_treasury_fiscal_service.py && git commit -m "feat(treasury): DB-first reader for treasury_data fiscal series by prefix"`

---

### Task T1D-4: Schemas + GET /macro/fiscal route + main.py wiring

**Files:**
- Create: `backend/app/schemas/treasury_fiscal.py`
- Create: `backend/app/api/routes/treasury.py`
- Modify: `backend/app/main.py` (add one import after line 17 `from app.api.routes import stocks as stocks_router`; add one `include_router` call after line 59 `application.include_router(macro_router.router)`)
- Test: `backend/tests/test_treasury_fiscal_route.py`

A thin endpoint that validates the `category` query param against the five prefixes (via `Literal`, which yields 422 for unknown values), calls T1D-3, and maps empty to 404. Lives on a dedicated router (`tags=["macro"]`, path `/macro/fiscal`) so the macro file stays focused; wired into the app in `main.py`.

- [ ] **Step 1: Write the failing test.** Create `backend/tests/test_treasury_fiscal_route.py` with the COMPLETE code below (uses `import pytest` + `@pytest.mark.anyio`, matching `test_macro_regime_route.py`).

```python
"""Tests for GET /macro/fiscal (treasury fiscal series, DB-first).

treasury_data is materialized by the treasury_ingestion worker; the Light only
reads. Service stubbed at its canonical module — no live DB.
"""

import datetime as dt

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.datalake import get_datalake_session
from app.main import create_app
from app.services import treasury_fiscal as tf


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_datalake_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fiscal(prefix: str = "RATE_") -> tf.FiscalData:
    return tf.FiscalData(
        prefix=prefix,
        series=[
            tf.FiscalSeries(
                series_id="RATE_TREASURY_BILLS",
                points=[
                    tf.FiscalPoint(dt.date(2026, 5, 1), 5.05, None),
                    tf.FiscalPoint(dt.date(2026, 6, 1), 5.10, None),
                ],
            ),
        ],
    )


def _fiscal_auctions() -> tf.FiscalData:
    meta = {"security_type": "Bond", "security_term": "30-Year", "bid_to_cover": 2.4}
    return tf.FiscalData(
        prefix="AUCTION_",
        series=[
            tf.FiscalSeries(
                series_id="AUCTION_BOND_30_YEAR",
                points=[tf.FiscalPoint(dt.date(2026, 6, 11), 5.02, meta)],
            ),
        ],
    )


@pytest.mark.anyio
async def test_fiscal_returns_series_for_category(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_fetch(datalake, *, prefix, lookback_days):
        captured["prefix"] = prefix
        captured["lookback_days"] = lookback_days
        return _fiscal(prefix)

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "rates"})
    assert resp.status_code == 200
    assert captured["prefix"] == "RATE_"
    body = resp.json()
    assert body["category"] == "rates"
    assert body["prefix"] == "RATE_"
    s = body["series"][0]
    assert s["series_id"] == "RATE_TREASURY_BILLS"
    assert s["points"][0]["obs_date"] == "2026-05-01"
    assert s["points"][1]["value"] == 5.10
    assert s["points"][0]["metadata"] is None


@pytest.mark.anyio
async def test_fiscal_passes_auction_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake, *, prefix, lookback_days):
        return _fiscal_auctions()

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "auctions"})
    assert resp.status_code == 200
    pt = resp.json()["series"][0]["points"][0]
    assert pt["metadata"]["security_type"] == "Bond"
    assert pt["metadata"]["bid_to_cover"] == 2.4


@pytest.mark.anyio
async def test_fiscal_default_category_is_rates(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict = {}

    async def fake_fetch(datalake, *, prefix, lookback_days):
        captured["prefix"] = prefix
        return _fiscal(prefix)

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal")
    assert resp.status_code == 200
    assert captured["prefix"] == "RATE_"


@pytest.mark.anyio
async def test_fiscal_invalid_category_422() -> None:
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "bogus"})
    assert resp.status_code == 422


@pytest.mark.anyio
async def test_fiscal_404_when_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_fetch(datalake, *, prefix, lookback_days):
        return tf.FiscalData(prefix=prefix, series=[])

    monkeypatch.setattr(tf, "fetch_treasury_series", fake_fetch)
    async with _client() as client:
        resp = await client.get("/macro/fiscal", params={"category": "debt"})
    assert resp.status_code == 404
    assert "treasury_ingestion" in resp.json()["detail"]
```

- [ ] **Step 2: Run it, expect FAIL.** Command: `cd backend && python -m pytest tests/test_treasury_fiscal_route.py -v`. Expected failure: `/macro/fiscal` is not registered, so all requests return FastAPI's default 404 `{"detail":"Not Found"}` — the 200/422 assertions fail and the empty-case 404 lacks `"treasury_ingestion"`.

- [ ] **Step 3a: Write the schemas.** Create `backend/app/schemas/treasury_fiscal.py` with the COMPLETE code below.

```python
"""Response schema for GET /macro/fiscal (treasury_data, DB-first)."""

import datetime as dt
from typing import Any

from pydantic import BaseModel


class FiscalPointOut(BaseModel):
    obs_date: dt.date
    value: float
    # Auction series carry {security_type, security_term, bid_to_cover}; others null.
    metadata: dict[str, Any] | None


class FiscalSeriesOut(BaseModel):
    series_id: str
    points: list[FiscalPointOut]  # ascending by obs_date


class FiscalResponse(BaseModel):
    """Treasury fiscal series for one category (worker treasury_ingestion)."""

    category: str  # 'rates' | 'debt' | 'auctions' | 'fx' | 'interest'
    prefix: str  # the treasury_data series_id prefix the category maps to
    series: list[FiscalSeriesOut]
```

- [ ] **Step 3b: Write the route.** Create `backend/app/api/routes/treasury.py` with the COMPLETE code below. The `category → prefix` map and the `Literal` query type give a 422 for unknown categories for free; `lookback_days` is bounded `ge=1, le=3650`.

```python
"""Treasury fiscal-data endpoint (Tier 1 serving layer — DB-first).

Thin endpoint over treasury_data, materialized by the treasury_ingestion worker
in the data-lake (DB-first, no computation here). The ``category`` maps to the
worker's series_id prefix; empty result → 404.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.datalake import get_datalake_session
from app.schemas.treasury_fiscal import (
    FiscalPointOut,
    FiscalResponse,
    FiscalSeriesOut,
)
from app.services import treasury_fiscal

router = APIRouter(tags=["macro"])

_CATEGORY_PREFIX: dict[str, str] = {
    "rates": "RATE_",
    "debt": "DEBT_",
    "auctions": "AUCTION_",
    "fx": "FX_",
    "interest": "INTEREST_",
}

FiscalCategory = Literal["rates", "debt", "auctions", "fx", "interest"]


@router.get("/macro/fiscal", response_model=FiscalResponse)
async def get_macro_fiscal(
    datalake: Annotated[AsyncSession, Depends(get_datalake_session)],
    category: Annotated[FiscalCategory, Query()] = "rates",
    lookback_days: Annotated[int, Query(ge=1, le=3650)] = 365,
) -> FiscalResponse:
    """Treasury fiscal series for one category over the lookback window."""
    prefix = _CATEGORY_PREFIX[category]
    data = await treasury_fiscal.fetch_treasury_series(
        datalake, prefix=prefix, lookback_days=lookback_days
    )
    if not data.series:
        raise HTTPException(
            status_code=404,
            detail=(
                "Treasury fiscal data not materialized — the treasury_ingestion "
                f"worker has not populated treasury_data for category '{category}'."
            ),
        )
    return FiscalResponse(
        category=category,
        prefix=prefix,
        series=[
            FiscalSeriesOut(
                series_id=s.series_id,
                points=[
                    FiscalPointOut(
                        obs_date=p.obs_date, value=p.value, metadata=p.metadata
                    )
                    for p in s.points
                ],
            )
            for s in data.series
        ],
    )
```

- [ ] **Step 3c: Wire into the app.** In `backend/app/main.py`, add the import immediately after line 17 (`from app.api.routes import stocks as stocks_router`):

```python
from app.api.routes import treasury as treasury_router
```

and register it immediately after line 59 (`application.include_router(macro_router.router)`):

```python
    application.include_router(treasury_router.router)
```

- [ ] **Step 4: Run tests, expect PASS.** Command: `cd backend && python -m pytest tests/test_treasury_fiscal_route.py -v`. Expected: 5 passed. Then run the whole new-cluster suite + the existing macro suite to confirm no regressions: `cd backend && python -m pytest tests/test_macro_scorecards_service.py tests/test_macro_scorecards_route.py tests/test_treasury_fiscal_service.py tests/test_treasury_fiscal_route.py tests/test_macro_regime_route.py -v` — expected all pass.

- [ ] **Step 5: Commit.** `cd backend && git add app/schemas/treasury_fiscal.py app/api/routes/treasury.py app/main.py tests/test_treasury_fiscal_route.py && git commit -m "feat(treasury): GET /macro/fiscal serving endpoint + app wiring"`

---

## Perguntas em aberto / decisoes necessarias (Tier 1)

_Resolver antes (ou no inicio) da execucao das tasks afetadas._

### T1A
- Active Share wiring requires a BENCHMARK CONSTITUENT WEIGHTS map (e.g. SPY's index weights) keyed by the same identifiers as the portfolio look-through weights. The current portfolio-analysis assembler (assemble_portfolio_analysis in backend/app/services/portfolio_analysis.py) receives ONLY the benchmark's adjusted-close PRICE series (benchmark_adj_close at line 245, used for bench_returns), not its constituent weights; PortfolioStats has no benchmark-weights input. Task T1A-6 therefore delivers active_share as a fully unit-tested PURE function over two weight dicts but does NOT auto-wire it into PortfolioStats because no constituent-weights data source exists yet. DECISION NEEDED: where do benchmark constituent weights come from (a static index-holdings table? a new datalake read? the N-PORT look-through of an index ETF via app.services.lookthrough)? Until that source is decided, active_share stays a library function. The legacy active_share_service.compute_active_share (E:/investintell-allocation/backend/quant_engine/active_share_service.py lines 31-124) returns 0-100 scale (line 103: `total_diff / 2.0 * 100`); the Light port in T1A-6 returns a DECIMAL FRACTION (0.30 = 30%) per the project scale contract, diverging intentionally from legacy.
- Information Ratio in PortfolioStats (T1A-5, computed by T1A-3's pure function) uses the portfolio-vs-benchmark active return from the assembler's already-aligned aligned_port/aligned_bench (backend/app/services/portfolio_analysis.py line 247). The risk-free rate is NOT used by IR (it cancels in the active return). For Sharpe/Sortino (T1A-1, T1A-2) the pure functions default the risk-free rate to DEFAULT_RISK_FREE_RATE = 0.04 (matching the worker E:/investintell-datalake-workers/src/workers/risk_metrics.py rf-handling and legacy return_statistics_service.DEFAULT_RISK_FREE_RATE = 0.04 at line 36) because neither the PortfolioAnalysisRequest nor the ScenarioRequest schema carries an rf field (confirmed: ScenarioRequest in backend/app/schemas/statistics.py lines 110-118 has only portfolio_id). CONFIRM whether a per-request risk-free override should be added to the request schemas, or whether sourcing the live Fed Funds (DFF) rate from the data-lake is preferred over the static 0.04 default.
- Effective Number of Bets in the legacy diversification_service.effective_number_of_bets (E:/investintell-allocation/backend/quant_engine/diversification_service.py lines 50-182) is a FACTOR-space entropy over factor risk contributions (Meucci 2009/2013, requires factor_loadings B + factor covariance Sigma_f). The Light has no factor model wired into the portfolio_analysis assembler. T1A-4 ports the ASSET-space entropy ENB over the existing risk_contributions() output (exp(-Sum RC_i ln RC_i), mirroring the legacy _entropy_enb at lines 198-209), which is the directly-available decomposition. CONFIRM this asset-space ENB is the intended Tier-1 metric (vs deferring the full factor/minimum-torsion ENB to a later tier that introduces a factor model).

### T1B
- Whether the CLOUD fund_risk_metrics table (TimescaleDB) already has empirical_duration / credit_beta / inflation_beta / crisis_alpha_score / *_r2 / scoring_model columns added out-of-band. The data-lake schemas/risk_metrics.sql does NOT declare them (only the peer/scoring ALTER block at lines 143-151). The mother-DB alembic migrations 0123 (FI) and 0125 (alt) DO declare them, but those run against the legacy DB, not the data-lake. Task T1B-1 adds them via idempotent ALTER ... ADD COLUMN IF NOT EXISTS so it is a no-op if already present. Confirm with the owner (or run `mcp__tiger__db_execute_query` against the cloud) before deploy.
- duration_adj_drawdown_1y and yield_proxy_12m (FI pass) and seven_day_net_yield / nav_per_share_mmf / pct_weekly_liquid / weighted_avg_maturity_days (cash/MMF pass) are part of the legacy class metric passes (migration 0012 / 0123 / 0124 / 0125) but are OUT OF SCOPE for rank-4 (only empirical_duration, credit_beta, inflation_beta, crisis_alpha_score are named). They are intentionally NOT ported here. Flag if the owner wants the full FI/cash/alt pass instead of the 4 named metrics.
- The light fund_risk_latest_mv is a Tiger materialized view defined in db/ddl/2026-06-13_dynamic_catalog.sql (CREATE block lines 63-76, unique index lines 78-79), NOT via alembic. CREATE MATERIALIZED VIEW IF NOT EXISTS will NOT add columns to an existing MV, so Task T1B-7 uses DROP MATERIALIZED VIEW IF EXISTS + CREATE. Confirm the owner is OK dropping+recreating the MV in production (it is read-only and rebuilt by the worker's REFRESH MATERIALIZED VIEW CONCURRENTLY path; the unique index must be recreated after DROP for CONCURRENTLY to work).
- Frontend UI surfacing: commit b634ce9 REMOVED the FundProfileView.tsx rows for these exact metrics (empirical_duration, credit_beta, inflation_beta, crisis_alpha_score, plus the out-of-scope yield/cash ones) because the FundRiskOut fields were 'always-null'. This cluster RE-EXPOSES the schema fields and regenerates the TS types (T1B-8/T1B-9) so the data flows through the contract again, but does NOT re-add the FundProfileView UI rows. Confirm whether the owner wants the UI rows restored (a separate frontend task) once the worker actually populates non-NULL values.
- Adding the four columns to the FundRiskLatest ORM (T1B-8) AUTO-EXTENDS catalog.SORT_WHITELIST, because _RISK_SORT_FIELDS is derived dynamically from FundRiskLatest.__table__.columns (funds_catalog.py:65-69). Side effects: (a) the four names become valid `sort=` codes on GET /funds (harmless, consistent with the other risk columns); (b) the _profile() test fixture's `risk_fields` dict-comprehension over SORT_WHITELIST will auto-include them as None — the explicit dict override in T1B-8 Step 1 still wins, so the test is correct. No action needed beyond awareness.

### T1C
- No backend/tests/analytics/ subdirectory exists; the existing single-asset risk tests live in backend/tests/test_analytics_risk.py (verified: 27 tests, all green at baseline). This plan appends the new realized_cvar tests to that existing file to match the repo's actual layout. The SHARED CONTRACT example path tests/analytics/test_risk.py does NOT exist here.
- The builder module docstring (portfolio_builder.py lines 17-19) and the inline comment (line 308) currently advertise that in-sample CVaR uses the SAME F3 estimator (historical_cvar) 'so it is directly comparable with portfolio-analysis numbers (gate G3)'. Switching the in-sample report to realized_cvar (exact RU) makes the builder report optimizer-consistent but no longer bit-identical to any F2/F3 portfolio-analysis CVaR that still uses historical_cvar. This plan resolves the conflict in favour of optimizer-consistency (the rank-5 directive) and updates BOTH the docstring and the inline comment accordingly. Confirm with product that builder-report CVaR matching the optimizer objective is preferred over matching the portfolio-analysis tail-mean. No portfolio-analysis module is changed by this cluster.
- VERIFIED at baseline (n_obs=500 stub in test_builder_route.py): (1-alpha)*T = 25 is an INTEGER, so realized_cvar and historical_cvar COINCIDE there. Therefore the existing 500-obs builder tests cannot distinguish the two estimators and will NOT regress. T1C-3 introduces a dedicated 30-obs stub ((1-alpha)*T = 1.5, non-integer) so the swap is observable end to end; this is the only fixture in the file with a non-integer tail.
- The legacy reference uses LOSS-space, returns NEGATIVE numbers, and has a soft len<5 -> NaN gate (cvar_service.py compute_cvar_from_returns lines 379-406) / a k-th-worst partition form (ru_cvar_lp.py realized_cvar_from_weights lines 167-215). The light port is RETURN-space, POSITIVE-decimal, fail-loud (ValueError, _MIN_TAIL_POINTS=10), matching the conventions of the sibling historical_var/historical_cvar in risk.py; the numeric value is identical to the legacy magnitude (verified).

### T1D
- macro_regional_snapshots.data_json regional 'dimensions' objects carry per-series 'indicators' maps whose keys vary by region/vintage (e.g. CFNAI/INDPRO/PAYEMS for US growth; credit_gap/debt_service/property_prices for the BIS credit_cycle dimension; fiscal_balance/government_debt for the IMF-blended fiscal dimension — confirmed in macro_ingestion.build_regional_snapshot / _enrich_region). The schemas expose 'dimensions' and 'data_freshness' as open dict[str, ...] pass-throughs (RegionScorecardOut.dimensions: dict[str, DimensionOut]) rather than enumerating every series, matching the worker's free-form indicators dict. This is the only stable contract; confirm the frontend does not require a fixed indicator enum.
- Treasury AUCTION_ series carry metadata_json {security_type, security_term, bid_to_cover} (treasury_ingestion.rows_from_auctions); the /macro/fiscal endpoint returns metadata as an opaque dict[str, Any] | None pass-through. If a typed AuctionMeta schema is later required, it is an additive change. No blocker.
- DATALAKE_DB_URL must be configured in the deployed Light env for these endpoints to return data; absent it, get_datalake_session raises HTTP 503 (app/core/datalake.py lines 47-54). No code change needed; flagged for deploy.
- I could not read the live data-lake during hardening (no DB access in this session). The data_json shape, treasury_data columns, prefixes and auction metadata keys are verified against the WORKER SOURCE that writes them (macro_ingestion.build_regional_snapshot/upsert_snapshot and treasury_ingestion.rows_from_*/upsert_treasury_data), which is authoritative for the contract. Row counts and the latest as_of_date in the draft are illustrative only and are not asserted by any test.

