# NAV Data-Quality Fix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix two product-wide NAV data-quality bugs — log-return convention consumed as simple (Bug 1) and near-zero NAV glitch prints (Bug 2) — so the live builder's backtest/projection/Monte-Carlo curves are correct, with an eligibility flag for irreparable series.

**Architecture:** Read-side conversion in the light app (a pure helper + simple-frame loaders, applied ONLY to performance curves; covariance/optimizer stay in log); source cleanup in the datalake ingestion (a round-trip glitch sanitizer + reprocess script); an eligibility flag computed by the risk_metrics worker and honored by optimizer + backtest.

**Tech Stack:** Python 3.12, FastAPI, SQLAlchemy async, numpy/pandas, pytest (light app `investintell-light/backend`); Python, psycopg, pytest (`investintell-datalake-workers`); TimescaleDB Cloud (Tiger `t83f4np6x4`).

**Spec:** `docs/superpowers/specs/2026-06-22-nav-data-quality-fix-design.md`

## Global Constraints

- Returns/CVaR/drawdown are decimal fractions (0.05 = 5%), never 0-100 (project scale contract).
- `GLITCH_LOG_THRESHOLD = 0.40` — `|log return|` above this is zeroed on the read side (matches `backend/scripts/local_fund_backtest.py` `--logfix`).
- Covariance/risk paths stay in LOG: do NOT touch `optimizer/engine`, `optimizer/data.py` LOG loaders, `risk_metrics` math, or the builder optimizer objective (`min_cvar`/`max_return_cvar` scenarios).
- Fail-loud: domain errors raise `ValueError`/`BacktestError`/`InsufficientDataError` (→ HTTP 422); never NaN-out or silently relax a limit.
- Tiger is READ-ONLY for diagnosis. Data changes ONLY via the ingestion/reprocess pipeline + `refresh_continuous_aggregate`, never ad-hoc UPDATE.
- Two repos: `investintell-light` (app) and `investintell-datalake-workers` (workers). Each task names its repo. Paths are relative to that repo's root.
- Isolation: dedicated worktrees off `main` for both repos (Task 0). Frequent commits, one per task.
- Regression invariant: proxy-only book B (the harness `prets` path) MUST stay numerically identical. Only fund/book-A paths change.

---

### Task 0: Worktrees off main + carry the spec

**Repo:** both. **Files:** none (setup).

- [ ] **Step 1: Create the light worktree off main**

```bash
cd /e/investintell-light
git worktree add -b feat/nav-data-quality ../investintell-light-navfix main
```

- [ ] **Step 2: Create the datalake worktree off main**

```bash
cd /e/investintell-datalake-workers
git worktree add -b feat/nav-glitch-sanitize ../investintell-datalake-workers-navfix main
```

- [ ] **Step 3: Copy the spec + this plan into the light worktree and commit**

```bash
mkdir -p ../investintell-light-navfix/docs/superpowers/specs ../investintell-light-navfix/docs/superpowers/plans
cp docs/superpowers/specs/2026-06-22-nav-data-quality-fix-design.md ../investintell-light-navfix/docs/superpowers/specs/
cp docs/superpowers/plans/2026-06-22-nav-data-quality-fix.md ../investintell-light-navfix/docs/superpowers/plans/
cd ../investintell-light-navfix
git add docs/superpowers/specs/2026-06-22-nav-data-quality-fix-design.md docs/superpowers/plans/2026-06-22-nav-data-quality-fix.md
git commit -m "docs: NAV data-quality fix spec + plan"
```

All subsequent light tasks run in `../investintell-light-navfix`; datalake tasks in `../investintell-datalake-workers-navfix`.

---

## Part A — Bug 1 read-side conversion (repo: investintell-light)

### Task L1: `to_simple_returns` pure helper

**Repo:** investintell-light
**Files:**
- Create: `backend/app/analytics/return_convention.py`
- Test: `backend/tests/test_return_convention.py`

**Interfaces:**
- Produces: `GLITCH_LOG_THRESHOLD: float = 0.40`; `to_simple_returns(values: pd.Series | np.ndarray, return_types: Sequence[str] | np.ndarray | None = None, *, glitch_threshold: float = GLITCH_LOG_THRESHOLD) -> pd.Series | np.ndarray` — element-wise: for `"log"` entries, zero where `|value| > glitch_threshold` then `expm1`; for `"arithmetic"` entries, identity. `return_types=None` ⇒ all `"log"`. Returns the same container type (Series keeps index).

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_return_convention.py
import numpy as np
import pandas as pd
import pytest

from app.analytics.return_convention import GLITCH_LOG_THRESHOLD, to_simple_returns


def test_log_clean_converts_with_expm1():
    out = to_simple_returns(np.array([0.01, -0.02, 0.0]))
    np.testing.assert_allclose(out, np.expm1([0.01, -0.02, 0.0]))


def test_glitch_logs_are_zeroed_then_expm1():
    # PAAA-style round-trip pair: both |log| > 0.40 -> zeroed -> expm1(0) == 0
    out = to_simple_returns(np.array([-6.89060912, 6.891625897]))
    np.testing.assert_allclose(out, [0.0, 0.0], atol=1e-12)


def test_threshold_boundary_keeps_just_below_and_zeros_just_above():
    out = to_simple_returns(np.array([0.40, 0.4001]))
    # 0.40 is NOT > 0.40 -> kept (expm1); 0.4001 > 0.40 -> zeroed
    np.testing.assert_allclose(out, [np.expm1(0.40), 0.0])


def test_arithmetic_is_identity_even_when_large():
    out = to_simple_returns(np.array([0.01, 0.9]), ["arithmetic", "arithmetic"])
    np.testing.assert_allclose(out, [0.01, 0.9])


def test_mixed_conventions_per_element():
    out = to_simple_returns(np.array([0.01, 0.01]), ["log", "arithmetic"])
    np.testing.assert_allclose(out, [np.expm1(0.01), 0.01])


def test_series_preserves_index():
    s = pd.Series([0.01, -0.02], index=pd.to_datetime(["2020-01-02", "2020-01-03"]))
    out = to_simple_returns(s)
    assert isinstance(out, pd.Series)
    assert list(out.index) == list(s.index)


def test_nan_propagates_positionally():
    out = to_simple_returns(np.array([np.nan, 0.01]))
    assert np.isnan(out[0])
    np.testing.assert_allclose(out[1], np.expm1(0.01))


def test_threshold_constant_matches_harness():
    assert GLITCH_LOG_THRESHOLD == 0.40
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_return_convention.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.analytics.return_convention'`.

- [ ] **Step 3: Write minimal implementation**

```python
# backend/app/analytics/return_convention.py
"""Return-convention conversion for PERFORMANCE consumers (Bug 1 + Bug 2 guard).

`nav_timeseries.return_1d` is a LOG return for ~99.8% of rows (return_type='log')
and arithmetic for a small proxy-ETF minority (return_type='arithmetic'). The
backtest / projection / Monte-Carlo curves compound returns as SIMPLE
(prod(1+r)); feeding them log returns is wrong (catastrophically so on a glitch).

This helper converts to SIMPLE honoring the per-element convention, and zeroes
residual log glitches above GLITCH_LOG_THRESHOLD as a safety net for any print
the source cleanup has not yet reprocessed. The COVARIANCE/risk path keeps log
and does NOT use this helper.

Pure; no I/O. Scale contract: inputs and outputs are decimal fractions.
"""

from collections.abc import Sequence

import numpy as np
import pandas as pd

#: |log return| above this is treated as a residual glitch and zeroed (matches
#: backend/scripts/local_fund_backtest.py --logfix).
GLITCH_LOG_THRESHOLD: float = 0.40


def to_simple_returns(
    values: pd.Series | np.ndarray,
    return_types: Sequence[str] | np.ndarray | None = None,
    *,
    glitch_threshold: float = GLITCH_LOG_THRESHOLD,
) -> pd.Series | np.ndarray:
    """Convert returns to SIMPLE honoring per-element convention, with a glitch guard.

    For ``"log"`` entries: zero where ``|value| > glitch_threshold`` (Bug 2 net),
    then ``expm1`` (log→simple). For ``"arithmetic"`` entries: identity (already
    simple). ``return_types=None`` treats every element as ``"log"`` (the fund
    default). NaN propagates positionally. A ``pd.Series`` keeps its index.
    """
    is_series = isinstance(values, pd.Series)
    index = values.index if is_series else None
    arr = np.asarray(values, dtype=float)

    if return_types is None:
        log_mask = np.ones(arr.shape, dtype=bool)
    else:
        types = np.asarray(return_types, dtype=object)
        if types.shape != arr.shape:
            raise ValueError(
                f"return_types shape {types.shape} != values shape {arr.shape}"
            )
        log_mask = types == "log"

    out = arr.copy()
    glitch = log_mask & (np.abs(arr) > glitch_threshold)
    out[glitch] = 0.0
    out[log_mask] = np.expm1(out[log_mask])
    # arithmetic entries are left as-is (already simple).

    if is_series:
        return pd.Series(out, index=index)
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && python -m pytest tests/test_return_convention.py -v`
Expected: PASS (8 passed).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analytics/return_convention.py backend/tests/test_return_convention.py
git commit -m "feat(analytics): to_simple_returns helper (log->simple + glitch guard)"
```

---

### Task L2: simple-frame loaders in `optimizer/data.py`

**Repo:** investintell-light
**Files:**
- Modify: `backend/app/optimizer/data.py` (add `_fund_simple_return_series`; add `convention` param to `_load_fund_returns`, `_load_fund_returns_batch`, `_load_equity_returns`, `load_aligned_returns`, `load_returns_matrix`)
- Test: `backend/tests/test_optimizer_data_convention.py`

**Interfaces:**
- Consumes: `to_simple_returns` (L1).
- Produces: `_fund_simple_return_series(rows: list[tuple[date, float|None, float|None, str|None]]) -> pd.Series`; `load_aligned_returns(session, assets, window_days=..., today=..., *, convention: Literal["log","simple"] = "log") -> pd.DataFrame`; same `convention` kwarg on `load_returns_matrix`. `convention="log"` is byte-identical to today.

- [ ] **Step 1: Write the failing test (pure series builder)**

```python
# backend/tests/test_optimizer_data_convention.py
import datetime as dt

import numpy as np

from app.optimizer.data import _fund_simple_return_series


def _d(n):
    return dt.date(2020, 1, 1) + dt.timedelta(days=n)


def test_simple_series_expm1s_log_return_1d():
    rows = [(_d(0), 10.0, None, "log"), (_d(1), 10.0, 0.01, "log")]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [np.expm1(0.01)])


def test_simple_series_honors_arithmetic():
    rows = [(_d(0), 10.0, None, "arithmetic"), (_d(1), 10.1, 0.01, "arithmetic")]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [0.01])


def test_simple_series_guards_glitch_pair():
    # 19.66 -> 0.02 -> 19.68 : two impossible log prints, both zeroed
    rows = [
        (_d(0), 19.66, None, "log"),
        (_d(1), 0.02, -6.89060912, "log"),
        (_d(2), 19.68, 6.891625897, "log"),
    ]
    s = _fund_simple_return_series(rows)
    np.testing.assert_allclose(s.to_numpy(), [0.0, 0.0], atol=1e-12)


def test_simple_series_log_fallback_when_return_1d_null():
    rows = [(_d(0), 10.0, None, "log"), (_d(1), 10.1, None, "log")]
    s = _fund_simple_return_series(rows)
    # fallback computes log(10.1/10.0), then expm1 -> simple 0.01
    np.testing.assert_allclose(s.to_numpy(), [0.1 / 10.0], atol=1e-9)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_optimizer_data_convention.py -v`
Expected: FAIL — `ImportError: cannot import name '_fund_simple_return_series'`.

- [ ] **Step 3: Add `_fund_simple_return_series` and thread `convention`**

In `backend/app/optimizer/data.py`, after the existing `_fund_return_series` (ends line 82), add:

```python
def _fund_simple_return_series(
    rows: list[tuple[dt.date, float | None, float | None, str | None]],
) -> pd.Series:
    """SIMPLE daily returns from (nav_date, nav, return_1d, return_type) rows.

    Builds the per-fund series honoring ``return_type`` and the glitch guard via
    ``to_simple_returns`` (PERFORMANCE path). Where ``return_1d`` is NULL, falls
    back to ``log(navₜ/navₜ₋₁)`` (then converted to simple). The COVARIANCE path
    keeps log and uses ``_fund_return_series`` instead.
    """
    from app.analytics.return_convention import to_simple_returns

    dates: list[dt.date] = []
    log_values: list[float] = []
    types: list[str] = []
    prev_nav: float | None = None
    for nav_date, nav, return_1d, return_type in rows:
        if return_1d is not None:
            dates.append(nav_date)
            log_values.append(float(return_1d))
            types.append(return_type or "log")
        elif nav is not None and nav > 0 and prev_nav is not None and prev_nav > 0:
            dates.append(nav_date)
            log_values.append(float(np.log(nav / prev_nav)))
            types.append("log")
        if nav is not None and nav > 0:
            prev_nav = float(nav)
    simple = to_simple_returns(np.asarray(log_values, dtype=float), types)
    return pd.Series(simple, index=pd.Index(dates), dtype=float)
```

Add a module import at the top (`from typing import Literal`). Then thread the `convention` kwarg. Update `_load_fund_returns`:

```python
async def _load_fund_returns(
    session: AsyncSession,
    ref: FundAssetRef,
    since: dt.date | None,
    *,
    convention: Literal["log", "simple"] = "log",
) -> pd.Series:
    cols = [FundNav.nav_date, FundNav.nav, FundNav.return_1d]
    if convention == "simple":
        cols.append(FundNav.return_type)
    stmt = select(*cols).where(FundNav.instrument_id == ref.id)
    if since is not None:
        stmt = stmt.where(FundNav.nav_date >= since)
    result = await session.execute(stmt.order_by(FundNav.nav_date))
    raw = result.all()
    if not raw:
        raise ValueError(f"unknown asset or no NAV history in window: {ref.label}")
    if convention == "simple":
        rows = [
            (d, float(n) if n is not None else None,
             float(r) if r is not None else None, rt)
            for d, n, r, rt in raw
        ]
        return _fund_simple_return_series(rows)
    rows3 = [
        (d, float(n) if n is not None else None, float(r) if r is not None else None)
        for d, n, r in raw
    ]
    return _fund_return_series(rows3)
```

Add `FundNav.return_type` to the model — in `backend/app/models/fund.py` `FundNav`, after `aum_usd` (line 306) add:

```python
    return_type: Mapped[str | None] = mapped_column(String, nullable=True)
```

Apply the same `convention` branch to `_load_fund_returns_batch` (select `FundNav.return_type` when simple, build 4-tuples per fund, call `_fund_simple_return_series`) and to `_load_equity_returns` (when `convention == "simple"`, return `to_simple_returns(log_prices.diff().dropna())` — i.e. `expm1` of the log diffs). Thread `convention` through `load_aligned_returns` and `load_returns_matrix` to the per-asset loaders.

- [ ] **Step 4: Run the pure test + the existing data tests**

Run: `cd backend && python -m pytest tests/test_optimizer_data_convention.py tests/test_optimizer_data.py tests/test_optimizer_data_broad.py -v`
Expected: PASS (new tests pass; existing tests unchanged — `convention` defaults to `"log"`).

- [ ] **Step 5: Add a loader-level equivalence test**

Append to `backend/tests/test_optimizer_data_convention.py`, copying the async session fixture used by `tests/test_optimizer_data.py` (same fixture name/imports). The assertion:

```python
# (uses the same `session` fixture + seed helpers as tests/test_optimizer_data.py)
import pytest


@pytest.mark.asyncio
async def test_simple_frame_is_expm1_of_log_frame(session):
    # Seed two funds with clean log return_1d using the same helper
    # test_optimizer_data.py uses to insert FundNav rows, then:
    from app.optimizer.data import FundAssetRef, load_aligned_returns

    assets = [FundAssetRef(id=FUND_A), FundAssetRef(id=FUND_B)]  # ids from the seed
    log_frame = await load_aligned_returns(session, assets, convention="log")
    simple_frame = await load_aligned_returns(session, assets, convention="simple")
    np.testing.assert_allclose(
        simple_frame.to_numpy(), np.expm1(log_frame.to_numpy()), rtol=1e-9
    )
```

Run: `cd backend && python -m pytest tests/test_optimizer_data_convention.py -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/optimizer/data.py backend/app/models/fund.py backend/tests/test_optimizer_data_convention.py
git commit -m "feat(optimizer): simple-frame loaders (convention=simple) honoring return_type"
```

---

### Task L3: dual-representation backtest (`analytics/backtest.py`)

**Repo:** investintell-light
**Files:**
- Modify: `backend/app/analytics/backtest.py` (add `perf_returns` param to `assemble_walk_forward_backtest`)
- Test: `backend/tests/test_backtest_analytics.py` (add cases)

**Interfaces:**
- Produces: `assemble_walk_forward_backtest(returns, solve_fn, *, perf_returns: pd.DataFrame | None = None, n_splits=..., ...)`. `solve_fn` receives the `returns` (log) TRAIN block; OOS composition uses `perf_returns` (simple) TEST block. `perf_returns=None` defaults to `returns` (back-compat). Must be index/column-aligned to `returns`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_backtest_analytics.py
import numpy as np
import pandas as pd

from app.analytics.backtest import assemble_walk_forward_backtest


def _equal_weight_solve(train):
    n = train.shape[1]
    return np.full(n, 1.0 / n)


def test_perf_returns_used_for_oos_not_returns():
    # returns = log frame; perf = simple frame (expm1). The OOS curve must be
    # built from perf_returns. Build enough history for one fold.
    idx = pd.bdate_range("2018-01-01", periods=400)
    rng = np.random.default_rng(0)
    log = pd.DataFrame(rng.normal(0, 0.01, size=(400, 2)), index=idx, columns=["a", "b"])
    perf = np.expm1(log)

    res_log = assemble_walk_forward_backtest(
        log, _equal_weight_solve, n_splits=2, min_train_size=200, test_size=50, gap=2
    )
    res_dual = assemble_walk_forward_backtest(
        log, _equal_weight_solve, perf_returns=perf,
        n_splits=2, min_train_size=200, test_size=50, gap=2,
    )
    # The dual curve differs from the all-log curve and equals the simple-frame curve.
    res_simple = assemble_walk_forward_backtest(
        perf, _equal_weight_solve, n_splits=2, min_train_size=200, test_size=50, gap=2
    )
    dual_navs = [v for _, v in res_dual.oos_curve]
    simple_navs = [v for _, v in res_simple.oos_curve]
    np.testing.assert_allclose(dual_navs, simple_navs, rtol=1e-9)
    log_navs = [v for _, v in res_log.oos_curve]
    assert dual_navs != log_navs  # composition convention actually changed the curve


def test_perf_returns_must_align():
    idx = pd.bdate_range("2018-01-01", periods=400)
    log = pd.DataFrame(0.001, index=idx, columns=["a", "b"])
    bad = pd.DataFrame(0.001, index=idx[:399], columns=["a", "b"])
    with pytest.raises(ValueError, match="perf_returns"):
        assemble_walk_forward_backtest(
            log, _equal_weight_solve, perf_returns=bad,
            n_splits=2, min_train_size=200, test_size=50, gap=2,
        )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_backtest_analytics.py::test_perf_returns_used_for_oos_not_returns -v`
Expected: FAIL — `assemble_walk_forward_backtest() got an unexpected keyword argument 'perf_returns'`.

- [ ] **Step 3: Implement `perf_returns`**

In `backend/app/analytics/backtest.py`, change the signature (line 98-109) to add `perf_returns: pd.DataFrame | None = None` after `solve_fn`. After the existing `matrix = returns.to_numpy(...)` and validation (around line 133-135), add:

```python
    if perf_returns is None:
        perf_matrix = matrix
    else:
        if not perf_returns.index.equals(returns.index) or list(
            perf_returns.columns
        ) != list(returns.columns):
            raise ValueError(
                "perf_returns must be index- and column-aligned to returns"
            )
        perf_matrix = perf_returns.to_numpy(dtype=float)
        if not np.isfinite(perf_matrix).all():
            raise ValueError("perf_returns contain NaN/inf — refusing to backtest")
```

In the fold loop, the solve still uses `matrix` (log), but the OOS composition uses `perf_matrix`. Replace `test_block = matrix[test_idx]` (line 169) with `test_block = perf_matrix[test_idx]`. The solve at line 166 (`solve_fn(matrix[train_idx])`) stays on `matrix` (log → covariance unchanged).

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_backtest_analytics.py -v`
Expected: PASS (new + existing — `perf_returns=None` keeps old behavior).

- [ ] **Step 5: Commit**

```bash
git add backend/app/analytics/backtest.py backend/tests/test_backtest_analytics.py
git commit -m "feat(backtest): perf_returns dual frame (solve on log, OOS compose on simple)"
```

---

### Task L4: wire the backtest service to pass both frames

**Repo:** investintell-light
**Files:**
- Modify: `backend/app/services/backtest.py:128-166`
- Test: `backend/tests/test_backtest_service.py` (add a case)

**Interfaces:**
- Consumes: `load_aligned_returns(..., convention=...)` (L2), `assemble_walk_forward_backtest(..., perf_returns=...)` (L3).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_backtest_service.py — assert the service loads a
# simple perf frame and passes it through. Spy on assemble_walk_forward_backtest.
import pandas as pd

from app.services import backtest as bt_service


@pytest.mark.asyncio
async def test_service_passes_simple_perf_returns(session, monkeypatch, seeded_request):
    captured = {}
    real = bt_service.assemble_walk_forward_backtest

    def spy(returns, solve_fn, *, perf_returns=None, **kw):
        captured["perf_is_set"] = perf_returns is not None
        captured["aligned"] = (
            perf_returns is not None
            and perf_returns.index.equals(returns.index)
        )
        return real(returns, solve_fn, perf_returns=perf_returns, **kw)

    monkeypatch.setattr(bt_service, "assemble_walk_forward_backtest", spy)
    await bt_service.run_walk_forward_backtest(session, seeded_request)
    assert captured["perf_is_set"] is True
    assert captured["aligned"] is True
```

(Use the existing seeded request/fixtures from `test_backtest_service.py`; `seeded_request` stands for whatever the file already builds.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_backtest_service.py::test_service_passes_simple_perf_returns -v`
Expected: FAIL — `perf_is_set` is False (service does not pass perf_returns yet).

- [ ] **Step 3: Load both frames and pass `perf_returns`**

In `backend/app/services/backtest.py` `run_walk_forward_backtest`, after the existing `frame = await optimizer_data.load_aligned_returns(...)` (line 129-131), load the aligned SIMPLE frame too:

```python
    try:
        frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days, convention="log"
        )
        perf_frame: pd.DataFrame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days, convention="simple"
        )
    except ValueError as exc:
        raise BacktestError(str(exc)) from exc
```

Then pass it into the assemble call (line 157-166):

```python
        result = assemble_walk_forward_backtest(
            frame,
            solve_fn,
            perf_returns=perf_frame,
            n_splits=payload.n_splits,
            gap=payload.gap,
            test_size=payload.test_size,
            min_train_size=payload.min_train_size,
            cost_bps=payload.cost_bps,
            risk_free_annual=payload.risk_free_annual,
        )
```

(Both loads share the same dates because `load_aligned_returns` dropna's on the same rows; the alignment assert in L3 guards it.)

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_backtest_service.py tests/test_backtest_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/backtest.py backend/tests/test_backtest_service.py
git commit -m "feat(backtest-service): load simple perf frame, pass perf_returns"
```

---

### Task L5: wire the portfolio Monte-Carlo service to the simple frame

**Repo:** investintell-light
**Files:**
- Modify: `backend/app/services/monte_carlo.py:260-282`
- Test: `backend/tests/test_monte_carlo_service.py` (add a case)

**Interfaces:**
- Consumes: `load_aligned_returns(..., convention="simple")` (L2).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_monte_carlo_service.py
import numpy as np

from app.services import monte_carlo as mc_service


@pytest.mark.asyncio
async def test_portfolio_mc_uses_simple_frame(session, monkeypatch, seeded_portfolio_request):
    seen = {}

    async def fake_load(s, refs, window_days=None, today=None, *, convention="log"):
        seen["convention"] = convention
        import pandas as pd
        idx = pd.bdate_range("2019-01-01", periods=300)
        return pd.DataFrame(
            {"fund:%s" % r.id if hasattr(r, "id") else r.label: 0.001 for r in refs},
            index=idx,
        )

    monkeypatch.setattr(mc_service.optimizer_data, "load_aligned_returns", fake_load)
    await mc_service.run_portfolio_monte_carlo(session, seeded_portfolio_request)
    assert seen["convention"] == "simple"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_monte_carlo_service.py::test_portfolio_mc_uses_simple_frame -v`
Expected: FAIL — `seen["convention"] == "log"` (default).

- [ ] **Step 3: Load the simple frame**

In `backend/app/services/monte_carlo.py` `run_portfolio_monte_carlo`, change the load (line 262-264) to:

```python
        frame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days, convention="simple"
        )
```

`portfolio_returns = frame.to_numpy(dtype=float) @ w` (line 282) is now a true portfolio SIMPLE-return series; the rest is unchanged.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_monte_carlo_service.py tests/test_monte_carlo_portfolio_route.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/monte_carlo.py backend/tests/test_monte_carlo_service.py
git commit -m "feat(mc-service): portfolio Monte-Carlo on simple-return frame"
```

---

## Part B — Bug 2 source cleanup (repo: investintell-datalake-workers)

### Task D1: NAV glitch sanitizer

**Repo:** investintell-datalake-workers
**Files:**
- Create: `src/workers/_nav_sanitize.py`
- Test: `tests/test_nav_sanitize.py`

**Interfaces:**
- Produces: `LOW_RATIO=0.2`, `WINDOW=5`, `SCALE_STEP_RATIO=10.0`, `GLITCH_LOG=1.0`; `@dataclass SanitizeResult(nav: list[float|None], repaired: list[bool], glitch_count: int, dead: bool, scale_step: bool)`; `sanitize_nav_series(series: list[tuple[date, float|None]]) -> SanitizeResult` — date-ordered; repairs transient round-trip near-zero prints by log-linear interpolation; flags (does not repair) dead / scale-step series.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_nav_sanitize.py
import datetime as dt

from src.workers._nav_sanitize import sanitize_nav_series


def _series(navs, start=dt.date(2020, 1, 1)):
    return [(start + dt.timedelta(days=i), v) for i, v in enumerate(navs)]


def test_single_round_trip_dip_is_repaired():
    res = sanitize_nav_series(_series([10.0, 10.1, 0.02, 10.2, 10.3]))
    assert res.repaired[2] is True
    assert 9.0 < res.nav[2] < 11.0       # interpolated back to the local level
    assert res.glitch_count == 1
    assert res.dead is False and res.scale_step is False


def test_alternating_glitches_paaa_style_all_repaired():
    res = sanitize_nav_series(_series([19.66, 0.02, 19.68, 0.01, 19.69]))
    assert res.repaired[1] is True and res.repaired[3] is True
    assert all(15.0 < v < 25.0 for v in res.nav)
    assert res.glitch_count == 2


def test_real_large_move_not_flagged():
    # a genuine -45% then sustained level (no round-trip) is NOT a glitch
    res = sanitize_nav_series(_series([100.0, 100.0, 55.0, 55.0, 55.0, 56.0]))
    assert not any(res.repaired)
    assert res.glitch_count == 0


def test_dead_fund_flagged_not_repaired():
    res = sanitize_nav_series(_series([10.0, 9.5, 0.01, 0.01, 0.01, 0.01]))
    assert res.dead is True
    assert not any(res.repaired)          # sustained near-zero is not interpolated


def test_scale_step_flagged_not_repaired():
    # a persistent ~70x level shift that never reverts = scale change
    res = sanitize_nav_series(_series([1.0, 1.0, 1.0, 71.0, 71.0, 71.0, 71.0]))
    assert res.scale_step is True
    assert not any(res.repaired)


def test_clean_series_unchanged():
    navs = [10.0, 10.1, 10.0, 10.2, 10.15]
    res = sanitize_nav_series(_series(navs))
    assert res.nav == navs
    assert res.glitch_count == 0 and not res.dead and not res.scale_step
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_nav_sanitize.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'src.workers._nav_sanitize'`.

- [ ] **Step 3: Implement the sanitizer**

```python
# src/workers/_nav_sanitize.py
"""NAV glitch sanitizer — repair transient near-zero round-trip prints (Bug 2).

Tiingo occasionally prints a spurious near-zero NAV that round-trips against its
neighbours (e.g. PAAA 19.66 -> 0.02 -> 19.68). Such a print produces an
impossible |log return| (>2.7x/day) and, downstream, a negative multiplier under
prod(1+r). This module detects TRANSIENT dips against a robust local level and
repairs them by log-linear interpolation BEFORE return_1d is computed.

It does NOT invent data: a fund that is genuinely dead (sustained near-zero) or
has a persistent scale step (NAV reported in the wrong units) is FLAGGED for the
eligibility column, not repaired.
"""

from __future__ import annotations

import datetime as _dt
import math
import statistics
from dataclasses import dataclass

LOW_RATIO = 0.2          # nav < ref * LOW_RATIO => candidate transient dip
WINDOW = 5               # centered window (half=2 each side) for the local median
SCALE_STEP_RATIO = 10.0  # persistent >=10x level shift that never reverts = scale change
GLITCH_LOG = 1.0         # |log return| above this is "impossible" (>2.7x/day)
_DEAD_FRACTION = 0.5     # >= this fraction of points near-zero => dead fund


@dataclass
class SanitizeResult:
    nav: list[float | None]
    repaired: list[bool]
    glitch_count: int
    dead: bool
    scale_step: bool


def _local_ref(values: list[float], i: int) -> float | None:
    """Median of the centered WINDOW excluding index i (positive values only)."""
    half = WINDOW // 2
    lo, hi = max(0, i - half), min(len(values), i + half + 1)
    neigh = [values[j] for j in range(lo, hi) if j != i and values[j] > 0]
    return statistics.median(neigh) if neigh else None


def sanitize_nav_series(
    series: list[tuple[_dt.date, float | None]],
) -> SanitizeResult:
    ordered = sorted(series)
    navs: list[float | None] = [v for _d, v in ordered]
    n = len(navs)
    repaired = [False] * n
    if n == 0:
        return SanitizeResult([], [], 0, False, False)

    positives = [v for v in navs if v is not None and v > 0]
    # Dead: most of the series sits near-zero relative to the overall level.
    overall = statistics.median(positives) if positives else 0.0
    near_zero = sum(1 for v in positives if v < overall * LOW_RATIO)
    dead = bool(positives) and near_zero >= _DEAD_FRACTION * len(positives)

    # Scale step: a persistent level shift >= SCALE_STEP_RATIO between the first
    # and last thirds that does not revert (median-of-thirds ratio).
    scale_step = False
    if len(positives) >= 6:
        third = len(positives) // 3
        head = statistics.median(positives[:third])
        tail = statistics.median(positives[-third:])
        if head > 0 and tail > 0:
            ratio = max(head / tail, tail / head)
            scale_step = ratio >= SCALE_STEP_RATIO

    glitch_count = 0
    if not dead and not scale_step:
        for i in range(n):
            v = navs[i]
            if v is None or v <= 0:
                continue
            ref = _local_ref([x if x is not None else 0.0 for x in navs], i)
            if ref is not None and ref > 0 and v < ref * LOW_RATIO:
                # transient dip — interpolate from nearest valid non-dip neighbours
                left = _nearest(navs, i, -1, ref)
                right = _nearest(navs, i, +1, ref)
                navs[i] = _interp(left, right, ref)
                repaired[i] = True

    # Residual impossible prints after repair (diagnostic for the flag).
    prev: float | None = None
    for v in navs:
        if v is not None and v > 0:
            if prev is not None and abs(math.log(v / prev)) > GLITCH_LOG:
                glitch_count += 1
            prev = v

    return SanitizeResult(navs, repaired, glitch_count, dead, scale_step)


def _nearest(navs, i, step, ref):
    j = i + step
    while 0 <= j < len(navs):
        v = navs[j]
        if v is not None and v >= ref * LOW_RATIO:
            return v
        j += step
    return None


def _interp(left, right, ref):
    if left is not None and right is not None:
        return math.exp((math.log(left) + math.log(right)) / 2.0)
    return left if left is not None else (right if right is not None else ref)
```

- [ ] **Step 4: Run tests**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_nav_sanitize.py -v`
Expected: PASS (6 passed). If a threshold case fails, tune `LOW_RATIO`/`WINDOW`/`SCALE_STEP_RATIO` against the test fixtures (calibration is part of this task).

- [ ] **Step 5: Commit**

```bash
git add src/workers/_nav_sanitize.py tests/test_nav_sanitize.py
git commit -m "feat(ingest): NAV glitch sanitizer (round-trip repair; dead/scale flags)"
```

---

### Task D2: wire the sanitizer into ingestion

**Repo:** investintell-datalake-workers
**Files:**
- Modify: `src/workers/instrument_ingestion.py:108-129` (`build_rows`)
- Test: `tests/test_instrument_ingestion.py` (add a case)

**Interfaces:**
- Consumes: `sanitize_nav_series` (D1).

- [ ] **Step 1: Write the failing test**

```python
# add to tests/test_instrument_ingestion.py
import datetime as dt

from src.workers.instrument_ingestion import build_rows


def test_build_rows_repairs_glitch_before_return():
    series = [
        (dt.date(2020, 1, 1), 19.66),
        (dt.date(2020, 1, 2), 0.02),    # glitch
        (dt.date(2020, 1, 3), 19.68),
    ]
    rows = build_rows(series, [("iid-1", "USD")])
    nav_by_date = {r["nav_date"]: r["nav"] for r in rows}
    assert 15.0 < nav_by_date[dt.date(2020, 1, 2)] < 25.0   # repaired, not 0.02
    # no impossible log return remains
    rets = [r["return_1d"] for r in rows if r["return_1d"] is not None]
    assert all(abs(x) < 1.0 for x in rets)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_instrument_ingestion.py::test_build_rows_repairs_glitch_before_return -v`
Expected: FAIL — nav at 2020-01-02 is 0.02.

- [ ] **Step 3: Sanitize inside `build_rows`**

In `src/workers/instrument_ingestion.py`, add the import near the top (`from src.workers._nav_sanitize import sanitize_nav_series`) and rewrite `build_rows`:

```python
def build_rows(series: list[tuple[_dt.date, float | None]],
               instruments: list[tuple[Any, str]] | tuple[tuple[Any, str], ...],
               source: str = "tiingo") -> list[dict[str, Any]]:
    """One ticker series → rows for every instrument (log returns, glitch-sanitized)."""
    ordered = sorted((d, p) for d, p in series if p is not None and p > 0)
    clean = sanitize_nav_series(ordered)
    rows: list[dict[str, Any]] = []
    prev: float | None = None
    for (d, _orig), price in zip(ordered, clean.nav):
        if price is None or price <= 0:
            continue
        ret = round(math.log(price / prev), 8) if prev else None
        for instrument_id, currency in instruments:
            rows.append({
                "instrument_id": instrument_id,
                "nav_date": d,
                "nav": round(price, 6),
                "return_1d": ret,
                "return_type": "log",
                "currency": currency,
                "source": source,
            })
        prev = price
    return rows
```

- [ ] **Step 4: Run tests**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_instrument_ingestion.py -v`
Expected: PASS (new + existing `test_build_rows_*`).

- [ ] **Step 5: Commit**

```bash
git add src/workers/instrument_ingestion.py tests/test_instrument_ingestion.py
git commit -m "feat(ingest): sanitize NAV before computing return_1d"
```

---

### Task D3: reprocess script for the affected funds

**Repo:** investintell-datalake-workers
**Files:**
- Create: `scripts/reprocess_nav_glitches.py`
- Test: `tests/test_reprocess_nav_glitches.py` (unit-test the pure selection/repair planning)

**Interfaces:**
- Consumes: `sanitize_nav_series` (D1), `upsert_nav_timeseries` (existing).
- Produces: `plan_repairs(rows_by_fund: dict[str, list[tuple[date, float]]]) -> dict[str, SanitizeResult]`; `run(dsn, *, dry_run=True, fund_ids=None) -> dict`.

- [ ] **Step 1: Write the failing test (pure planner)**

```python
# tests/test_reprocess_nav_glitches.py
import datetime as dt

from scripts.reprocess_nav_glitches import plan_repairs


def test_plan_repairs_reports_per_fund_changes():
    rows_by_fund = {
        "f1": [(dt.date(2020, 1, 1), 19.66), (dt.date(2020, 1, 2), 0.02),
               (dt.date(2020, 1, 3), 19.68)],
        "f2": [(dt.date(2020, 1, 1), 10.0), (dt.date(2020, 1, 2), 10.1)],
    }
    plans = plan_repairs(rows_by_fund)
    assert plans["f1"].glitch_count >= 0 and any(plans["f1"].repaired)
    assert not any(plans["f2"].repaired)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_reprocess_nav_glitches.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement the script**

```python
# scripts/reprocess_nav_glitches.py
"""Reprocess NAV glitches for affected funds: read existing nav_timeseries,
sanitize, upsert corrected (nav, return_1d), then refresh cagg_nav_daily.

Operates on existing rows (NOT a Tiingo re-fetch) so it is deterministic. The
default selection is every instrument with any |return_1d| > 1.0 (the 279
funds). --dry-run reports per-fund changes without writing.
"""

from __future__ import annotations

import argparse
import os

from src.db import connect
from src.workers._nav_sanitize import SanitizeResult, sanitize_nav_series

SELECT_AFFECTED = """
SELECT DISTINCT instrument_id FROM nav_timeseries
WHERE abs(return_1d) > 1.0
"""
SELECT_ROWS = """
SELECT nav_date, nav FROM nav_timeseries
WHERE instrument_id = %s AND nav IS NOT NULL ORDER BY nav_date
"""
UPSERT = """
INSERT INTO nav_timeseries (instrument_id, nav_date, nav, return_1d, return_type, currency, source)
VALUES (%s, %s, %s, %s, 'log', COALESCE(%s, 'USD'), 'reprocess')
ON CONFLICT (instrument_id, nav_date) DO UPDATE SET nav = EXCLUDED.nav, return_1d = EXCLUDED.return_1d
"""


def plan_repairs(rows_by_fund):
    return {fid: sanitize_nav_series(rows) for fid, rows in rows_by_fund.items()}


def run(dsn: str, *, dry_run: bool = True, fund_ids: list | None = None) -> dict:
    import math
    stats = {"funds": 0, "repaired_funds": 0, "rows_updated": 0, "dead": 0, "scale_step": 0}
    touched_min = touched_max = None
    with connect(dsn) as conn:
        with conn.cursor() as cur:
            if fund_ids is None:
                cur.execute(SELECT_AFFECTED)
                fund_ids = [r[0] for r in cur.fetchall()]
            for iid in fund_ids:
                cur.execute(SELECT_ROWS, (iid,))
                rows = [(d, float(n)) for d, n in cur.fetchall()]
                res: SanitizeResult = sanitize_nav_series(rows)
                stats["funds"] += 1
                if res.dead:
                    stats["dead"] += 1
                if res.scale_step:
                    stats["scale_step"] += 1
                if not any(res.repaired):
                    continue
                stats["repaired_funds"] += 1
                prev = None
                updates = []
                for (d, _o), nav in zip(rows, res.nav):
                    ret = round(math.log(nav / prev), 8) if prev else None
                    updates.append((iid, d, round(nav, 6), ret, None))
                    prev = nav
                    touched_min = d if touched_min is None or d < touched_min else touched_min
                    touched_max = d if touched_max is None or d > touched_max else touched_max
                if not dry_run:
                    cur.executemany(UPSERT, updates)
                    conn.commit()
                stats["rows_updated"] += sum(1 for i, _ in enumerate(res.repaired) if res.repaired[i])
        if not dry_run and touched_min is not None:
            with connect(dsn, autocommit=True) as rconn, rconn.cursor() as rcur:
                rcur.execute(
                    "CALL refresh_continuous_aggregate('cagg_nav_daily', %s, %s)",
                    (touched_min, touched_max),
                )
    return stats


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()
    dsn = os.environ["DATALAKE_DB_URL"]
    out = run(dsn, dry_run=not args.apply)
    print(out)
```

- [ ] **Step 4: Run tests**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_reprocess_nav_glitches.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/reprocess_nav_glitches.py tests/test_reprocess_nav_glitches.py
git commit -m "feat(scripts): reprocess_nav_glitches (sanitize existing rows + cagg refresh)"
```

---

## Part C — Eligibility flag (both repos)

### Task C1: schema — `nav_quality_ok` + `nav_glitch_count`

**Repo:** investintell-light (DDL lives here; applied to Tiger)
**Files:**
- Create: `backend/db/ddl/2026-06-22_nav_quality_flag.sql`
- Modify: `backend/db/ddl/2026-06-13_dynamic_catalog.sql:73-84` (add the two columns to the `fund_risk_latest_mv` projection)
- Modify: `backend/app/models/fund.py` (`FundRiskLatest`: add columns)
- Test: `backend/tests/test_models.py` (assert the columns exist on the model)

**Interfaces:**
- Produces: `fund_risk_metrics.nav_quality_ok boolean`, `fund_risk_metrics.nav_glitch_count int`; same projected into `fund_risk_latest_mv`; `FundRiskLatest.nav_quality_ok`, `FundRiskLatest.nav_glitch_count`.

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_models.py
from app.models.fund import FundRiskLatest


def test_fund_risk_latest_has_nav_quality_columns():
    cols = {c.name for c in FundRiskLatest.__table__.columns}
    assert "nav_quality_ok" in cols
    assert "nav_glitch_count" in cols
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_models.py::test_fund_risk_latest_has_nav_quality_columns -v`
Expected: FAIL — columns absent.

- [ ] **Step 3: Add the DDL + model columns**

Create `backend/db/ddl/2026-06-22_nav_quality_flag.sql`:

```sql
-- NAV data-quality eligibility flag (Bug 2). Computed by the risk_metrics
-- worker; honored by the optimizer universe gate and the backtest service.
ALTER TABLE fund_risk_metrics
  ADD COLUMN IF NOT EXISTS nav_quality_ok boolean,
  ADD COLUMN IF NOT EXISTS nav_glitch_count integer;
```

In `backend/db/ddl/2026-06-13_dynamic_catalog.sql`, add the two columns to the `fund_risk_latest_mv` SELECT list (after `crisis_alpha_score` on line 84):

```sql
       empirical_duration, credit_beta, inflation_beta, crisis_alpha_score,
       nav_quality_ok, nav_glitch_count
```

In `backend/app/models/fund.py` `FundRiskLatest`, after `crisis_alpha_score` (line 229) add:

```python
    nav_quality_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    nav_glitch_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
```

- [ ] **Step 4: Run tests + apply DDL to Tiger**

Run: `cd backend && python -m pytest tests/test_models.py -v`
Expected: PASS.

Apply the base-table ALTER to Tiger (idempotent; the MV rebuild happens via the worker's `REFRESH … CONCURRENTLY` after the projection change is deployed — note the MV must be DROP/CREATE'd once for the new columns to appear). Record the apply in the commit message.

- [ ] **Step 5: Commit**

```bash
git add backend/db/ddl/2026-06-22_nav_quality_flag.sql backend/db/ddl/2026-06-13_dynamic_catalog.sql backend/app/models/fund.py backend/tests/test_models.py
git commit -m "feat(schema): nav_quality_ok / nav_glitch_count on fund_risk_metrics + MV + model"
```

---

### Task C2: risk_metrics worker computes the flag

**Repo:** investintell-datalake-workers
**Files:**
- Modify: `src/workers/risk_metrics.py` (`compute_metrics` or its caller; add the two keys to `_METRIC_COLUMNS`)
- Test: `tests/test_risk_metrics_nav_quality.py`

**Interfaces:**
- Consumes: `sanitize_nav_series` (D1).
- Produces: `nav_quality(nav_rows: list[tuple[date, float]]) -> tuple[bool, int]` → `(nav_quality_ok, nav_glitch_count)`; both written by `_upsert` via `_METRIC_COLUMNS`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_risk_metrics_nav_quality.py
import datetime as dt

from src.workers.risk_metrics import nav_quality


def _rows(navs):
    return [(dt.date(2020, 1, 1) + dt.timedelta(days=i), v) for i, v in enumerate(navs)]


def test_clean_series_is_ok():
    ok, count = nav_quality(_rows([10, 10.1, 10.0, 10.2, 10.15]))
    assert ok is True and count == 0


def test_dead_series_not_ok():
    ok, _ = nav_quality(_rows([10, 9.5, 0.01, 0.01, 0.01, 0.01]))
    assert ok is False


def test_scale_step_not_ok():
    ok, _ = nav_quality(_rows([1, 1, 1, 71, 71, 71, 71]))
    assert ok is False


def test_repairable_glitch_is_ok_after_repair():
    ok, count = nav_quality(_rows([19.66, 0.02, 19.68, 0.01, 19.69]))
    assert ok is True and count == 0    # repaired -> no residual impossible print
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_risk_metrics_nav_quality.py -v`
Expected: FAIL — `ImportError: cannot import name 'nav_quality'`.

- [ ] **Step 3: Implement `nav_quality` and wire it into the metrics dict**

In `src/workers/risk_metrics.py`, add near the metric helpers:

```python
from src.workers._nav_sanitize import sanitize_nav_series


def nav_quality(nav_rows: list[tuple]) -> tuple[bool, int]:
    """(nav_quality_ok, nav_glitch_count) from raw (date, nav) rows.

    OK = not dead AND not a scale step AND no residual impossible print after
    the round-trip repair. Mirrors the ingestion sanitizer so the flag tracks
    exactly what the source cleanup can and cannot fix.
    """
    res = sanitize_nav_series([(d, float(n)) for d, n in nav_rows])
    ok = (not res.dead) and (not res.scale_step) and (res.glitch_count == 0)
    return ok, res.glitch_count
```

Add `"nav_quality_ok"` and `"nav_glitch_count"` to `_METRIC_COLUMNS` (grep `_METRIC_COLUMNS =` for the list). In BOTH the serial path (line 1059-1079) and `_process_shard` (line 877-896), after `nav = np.array(...)` and before/with the `metrics` dict, compute and inject:

```python
            ok, gcount = nav_quality([(r[0], r[1]) for r in rows])
            metrics["nav_quality_ok"] = ok
            metrics["nav_glitch_count"] = gcount
```

(Place it after `metrics = compute_metrics(nav, rf)` and the `if metrics is None: continue` guard, so a fund with metrics still records its quality.)

- [ ] **Step 4: Run tests**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest tests/test_risk_metrics_nav_quality.py tests/test_risk_metrics*.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/workers/risk_metrics.py tests/test_risk_metrics_nav_quality.py
git commit -m "feat(risk-metrics): compute nav_quality_ok / nav_glitch_count"
```

---

### Task C3: optimizer + backtest honor the flag (fail-open NULL)

**Repo:** investintell-light
**Files:**
- Modify: `backend/app/optimizer/data.py` `select_universe_funds` (add the quality gate)
- Modify: `backend/app/services/backtest.py` (fail-loud on an explicitly bad asset)
- Test: `backend/tests/test_optimizer_data.py` (add a gate case)

**Interfaces:**
- Consumes: `FundRiskLatest.nav_quality_ok` (C1).

- [ ] **Step 1: Write the failing test**

```python
# add to backend/tests/test_optimizer_data.py — seed two funds, one with
# nav_quality_ok=False, assert it is excluded while NULL/true survive.
@pytest.mark.asyncio
async def test_select_universe_excludes_nav_quality_false(session, seed_universe):
    # seed_universe inserts fund GOOD (nav_quality_ok NULL), BAD (False)
    from app.optimizer.data import select_universe_funds
    from app.services import funds_catalog

    funds = await select_universe_funds(
        session, funds_catalog.FundFilters(), rank_by="aum_usd", rank_dir="desc",
        max_assets=50,
    )
    ids = {f.id for f in funds}
    assert GOOD_ID in ids          # NULL = fail-open, kept
    assert BAD_ID not in ids       # explicitly False = excluded
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && python -m pytest tests/test_optimizer_data.py::test_select_universe_excludes_nav_quality_false -v`
Expected: FAIL — BAD_ID is still returned.

- [ ] **Step 3: Add the gate (fail-open NULL)**

In `backend/app/optimizer/data.py` `select_universe_funds`, in the `conditions` block (after line 502), add:

```python
    # NAV data-quality gate (Bug 2): exclude funds the risk worker flagged as
    # irreparable (dead / scale-step / residual glitch). NULL is fail-open so the
    # universe is never emptied before the worker populates the column.
    conditions.append(
        sa.or_(
            FundRiskLatest.nav_quality_ok.is_(None),
            FundRiskLatest.nav_quality_ok.is_(True),
        )
    )
```

(Add `import sqlalchemy as sa` if not present.) In `backend/app/services/backtest.py`, after loading the frame, raise `BacktestError` if any requested fund is explicitly `nav_quality_ok=False` (query `FundRiskLatest` for the requested fund ids; name the offender). Keep NULL fail-open.

- [ ] **Step 4: Run tests**

Run: `cd backend && python -m pytest tests/test_optimizer_data.py tests/test_backtest_service.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/optimizer/data.py backend/app/services/backtest.py backend/tests/test_optimizer_data.py
git commit -m "feat(eligibility): optimizer+backtest honor nav_quality_ok (fail-open NULL)"
```

---

## Part D — Green gate + reprocess (authorized after green)

### Task V1: full suites, dry-run, reprocess, harness validation

**Repo:** both. **Files:** none (validation/ops).

- [ ] **Step 1: Light suite green**

Run: `cd /e/investintell-light-navfix/backend && python -m pytest -q`
Expected: no NEW failures vs `main` (record any pre-existing failures separately).

- [ ] **Step 2: Datalake suite green**

Run: `cd /e/investintell-datalake-workers-navfix && python -m pytest -q`
Expected: PASS.

- [ ] **Step 3: Dry-run the reprocess and review**

Run: `cd /e/investintell-datalake-workers-navfix && DATALAKE_DB_URL=<tiger dsn> python scripts/reprocess_nav_glitches.py --dry-run`
Expected: `funds` ≈ 279; `repaired_funds` > 0; `dead`/`scale_step` counts reported. Sanity-check a couple of funds (PAAA `f31fed45-…`, `fc4f396b-…`) would be repaired.

- [ ] **Step 4: Apply the reprocess + cagg refresh (authorized)**

Run: `cd /e/investintell-datalake-workers-navfix && DATALAKE_DB_URL=<tiger dsn> python scripts/reprocess_nav_glitches.py --apply`
Then verify (READ-ONLY) on Tiger: `SELECT count(*) FROM cagg_nav_daily WHERE abs(return_1d) > 1.0` drops sharply; PAAA/fc4f396b have no impossible spikes.

- [ ] **Step 5: Harness regression**

Rebuild the harness cache so it reads the cleaned cagg (the refresh/rebuild flag in `backend/scripts/local_fund_backtest.py` argparse), then run WITHOUT `--logfix`:
Run: `cd /e/investintell-light-navfix/backend && python scripts/local_fund_backtest.py`
Expected: book A approaches the fixed targets (agg ≈9.3 CAGR / 31.3 MaxDD, mod ≈7.6/24.2, con ≈6.0/21.0); book B (proxy-only) UNCHANGED.

- [ ] **Step 6: Recompute the flag for the universe**

Run the risk_metrics worker (calc for the latest date) so `nav_quality_ok`/`nav_glitch_count` populate `fund_risk_metrics`; the MV refresh follows. Verify the optimizer universe gate now excludes the flagged funds.

---

## Self-Review

**Spec coverage:**
- §4 A1 → L1. A2 → L2. A3 → L3. A4 (services) → L4 + L5. A5 (do-not-touch) → enforced by Global Constraints + carve-out in L3/L5.
- §4 B1 → D1. B2 → D2. B3 → D3.
- §4 C1 → C1. C2 → C2. C3 → C3.
- §6 acceptance → V1 (suites, dry-run, reprocess, harness, flag).
- §8 rollout order → Task ordering (A+B+detector, then C, then green gate, then reprocess).

**Placeholder scan:** test bodies that reference existing fixtures (`session`, `seeded_request`, `seed_universe`, `seed`/`_METRIC_COLUMNS`) name a concrete existing pattern rather than inventing one — each step says which existing test file to copy the fixture from. No "TBD/handle edge cases/write tests for the above".

**Type consistency:** `to_simple_returns(values, return_types, *, glitch_threshold)` used identically in L1/L2. `_fund_simple_return_series` 4-tuple `(date, nav, return_1d, return_type)` consistent across L2 and its tests. `assemble_walk_forward_backtest(..., perf_returns=...)` consistent L3↔L4. `SanitizeResult(nav, repaired, glitch_count, dead, scale_step)` consistent D1↔D2↔D3↔C2. `nav_quality(...) -> (bool, int)` consistent C2. `nav_quality_ok`/`nav_glitch_count` column names consistent C1↔C2↔C3.
