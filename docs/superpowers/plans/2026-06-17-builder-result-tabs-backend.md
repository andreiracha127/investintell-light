# Builder result tabs — backend (onda 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose three already-implemented quant capabilities to the Builder result tabs by (a) emitting the walk-forward backtest's out-of-sample equity curve, (b) adding a portfolio-level Monte Carlo endpoint that reuses the pure block-bootstrap core, and (c) letting walk-forward run the `max_return_cvar` (equilibrium) objective.

**Architecture:** Backend follows the project split: pure `assemble_*` math lives in `app/analytics/*`, async `run_*` orchestrators in `app/services/*` load from the data-lake and map domain `ValueError`s to 422, and thin routes in `app/api/routes/*` map service errors to HTTP. Schemas in `app/schemas/*` carry the decimal-fraction scale contract and reuse the builder asset vocabulary. The frontend tabs are a SEPARATE plan; this plan only ships the backend the tabs depend on.

**Tech Stack:** Python 3.12, FastAPI, Pydantic v2, SQLAlchemy async, NumPy/pandas, cvxpy (optimizer), pytest (`asyncio_mode="auto"`), ruff, mypy. Test command: `cd backend && uv run pytest -q <path>`. Full gate: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`.

---

## Context the worker MUST know before starting

Read these real facts — the plan is built on the actual current files, not assumptions.

1. **`SeriesPoint` is a backend type alias, NOT a class.** It lives at `backend/app/schemas/analysis.py:24`:
   ```python
   SeriesPoint = tuple[dt.date, float]
   ```
   OpenAPI renders it as a fixed-length `[date, number]` tuple (the frontend's `SeriesPoint = [string, number]`). `app/schemas/backtest.py` does NOT currently import it. Task 1 adds the import from `app.schemas.analysis`.

2. **`block_bootstrap_monte_carlo` and `load_aligned_returns` stay UNCHANGED.** They are reused verbatim. The new portfolio MC builds a synthetic 1-D return series and feeds it to the existing pure core.

3. **Onda 0 lands BEFORE this plan (execution order).** This plan runs AFTER the onda 0 backend, so `app/services/portfolio_builder.py::_market_weights_for` ALREADY supports equities via market cap (the onda-0 `load_equity_market_cap`: `shares_outstanding × latest adj_close`). Task 3 therefore:
   - reuses the **post-onda-0** `_market_weights_for` (funds → AUM, equities → market cap), aligned to `labels`;
   - the "equities fail loud" test asserts fail-loud ONLY for equities WITHOUT `shares_outstanding`/price (mock `load_equity_market_cap` to return `None` for that ticker) — equities WITH a market cap are a happy path, not a rejection;
   - carries an explicit `cvar_limit` on the request, δ fixed at `bl.DEFAULT_DELTA` (δ does not move the linear `max_return_cvar` argmax — only the direction `Σ·w_mkt` and the `cvar_limit` matter). The mandate→cvar_limit pre-fill is a frontend concern; the walk-forward request always carries the explicit ceiling. See **Open question (resolved)** at the end.
   - **If, for any reason, this plan is executed before onda 0 lands,** the equities path will fail loud on every equity (old behavior) and the "equities fail loud" test should use any equity ticker; reconcile that one test to the post-onda-0 shape above once onda 0 is merged.

4. **`_market_weights_for(session, assets, labels)`** (portfolio_builder.py:173) returns an `np.ndarray` of market weights aligned to `labels`, and raises `BuilderError` on any equity or any fund with NULL/non-positive AUM. The walk-forward service will call it once and thread the resulting `w_mkt` into the per-fold solve closure.

5. **`solve_max_return_cvar_capped(scenarios, mu, cvar_limit, ...)`** (engine.py:738) is the equilibrium-mode solver. `mu` is REQUIRED (the per-fold `π`); it returns `(weights, status)`. `bl.equilibrium(sigma_ann, w_mkt, delta)` (black_litterman.py:84) computes `π = δ·Σ·w_mkt`; `engine.sigma_ledoit_wolf(train)` (engine.py:80) gives the annualized shrunk Σ for the fold's train window.

6. **Pytest is `asyncio_mode="auto"`** — async test functions need no decorator. Tests live under `backend/tests/`. Mirror the existing fixtures exactly (synthetic `pd.DataFrame` via `np.random.default_rng`, stub `app.optimizer.data.load_aligned_returns` with `monkeypatch`).

7. **Routers are registered in `backend/app/main.py`** — `monte_carlo_router` and `backtest_router` are already included (lines 66/71). No registration change is needed; the new `/monte-carlo/portfolio` route is added to the EXISTING `monte_carlo` router.

---

## Task 1 — Backtest out-of-sample equity curve

Accumulate each fold's net daily return series, chain them in time order into a global NAV, and expose `oos_curve` + `fold_boundaries` end-to-end (analytics → schema → service → route). No existing metric changes.

**Files:**
- Modify: `backend/app/analytics/backtest.py` (add curve accumulation + two `WalkForwardResult` fields)
- Modify: `backend/app/schemas/backtest.py` (add `oos_curve`, `fold_boundaries` to `WalkForwardResponse`; import `SeriesPoint`)
- Modify: `backend/app/services/backtest.py` (map the new fields)
- Test: `backend/tests/test_backtest_analytics.py` (curve invariants)
- Test: `backend/tests/test_backtest_schema.py` (new fields present/well-formed)
- Test: `backend/tests/test_backtest_route.py` (response carries the fields)

### Subtask 1a — analytics: accumulate and chain the OOS curve

- [x] **Write failing test** — append to `backend/tests/test_backtest_analytics.py`:

```python
def test_oos_curve_chains_folds_in_time_order() -> None:
    # cost_bps=0 so the chained growth factor equals the product of per-fold
    # (1 + net_return) exactly (no first-day cost perturbing the chain).
    frame = _synthetic_returns(seed=11)
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252, cost_bps=0.0,
    )
    # One point per OOS observation across all folds.
    assert len(result.oos_curve) == sum(f.n_obs for f in result.folds)
    # Dates strictly increasing in time.
    dates = [d for d, _ in result.oos_curve]
    assert all(earlier < later for earlier, later in zip(dates, dates[1:], strict=False))
    # Final chained growth factor == product of per-fold (1 + net_return).
    final_nav = result.oos_curve[-1][1]
    expected = float(np.prod([1.0 + f.net_return for f in result.folds]))
    assert final_nav == pytest.approx(expected, rel=1e-4)
    # First curve date == start of the first test fold (the final 63*5 window's
    # first test block start). It must equal the first OOS date the loop saw.
    first_date = result.oos_curve[0][0]
    assert first_date == dates[0]
    # fold_boundaries: one per fold, each the first date of that fold's OOS block.
    assert len(result.fold_boundaries) == len(result.folds)
    assert result.fold_boundaries[0] == first_date
    assert all(b in set(dates) for b in result.fold_boundaries)


def test_oos_curve_values_are_finite_and_positive() -> None:
    frame = _synthetic_returns(seed=12)
    result = assemble_walk_forward_backtest(
        frame, _equal_weight_solver, n_splits=5, gap=2, test_size=63,
        min_train_size=252,
    )
    navs = [v for _, v in result.oos_curve]
    assert all(np.isfinite(v) and v > 0 for v in navs)
```

- [x] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_analytics.py -k oos_curve`
  - Expected: `AttributeError: 'WalkForwardResult' object has no attribute 'oos_curve'` (the dataclass has no such field yet).

- [x] **Implement** — edit `backend/app/analytics/backtest.py`.

  Add `date` to the imports at the top (after `from dataclasses import dataclass`):

```python
import datetime as dt
import math
from collections.abc import Callable
from dataclasses import dataclass
```

  Extend the `WalkForwardResult` dataclass (currently ends with `cost_bps: float`) with the two new fields:

```python
@dataclass(frozen=True)
class WalkForwardResult:
    folds: list[FoldMetrics]
    n_splits_computed: int
    mean_sharpe: float
    std_sharpe: float
    positive_folds: int
    mean_turnover: float
    cost_bps: float
    # Chained out-of-sample NAV: one (date, nav) point per OOS observation,
    # concatenated across folds in time order. nav starts from the first fold's
    # first OOS day and compounds the per-fold NET daily returns (so the
    # rebalancing cost charged on each fold's first OOS day is already in it).
    oos_curve: list[tuple[dt.date, float]]
    # First OOS date of each fold (the re-optimization / rebalancing points),
    # for the frontend's plotLines.
    fold_boundaries: list[dt.date]
```

  In `assemble_walk_forward_backtest`, add two accumulators next to `folds` / `w_prev` (the loop currently starts at `folds: list[FoldMetrics] = []`):

```python
    tscv = TimeSeriesSplit(n_splits=n_splits, gap=gap, test_size=test_size)
    folds: list[FoldMetrics] = []
    net_segments: list[pd.Series] = []
    fold_boundaries: list[dt.date] = []
    w_prev = np.zeros(matrix.shape[1])
```

  Inside the loop, the existing block builds `oos_index`, `net_series`, and `nav`. Right after `net_series` is created (and BEFORE `nav` is used), capture the segment and the boundary. The current loop body is:

```python
        oos_index = index[test_idx]
        net_series = pd.Series(net_daily, index=oos_index)
        nav = (1.0 + net_series).cumprod()
```

  Replace it with (adds two lines; `nav` is unchanged so existing max-drawdown math is untouched):

```python
        oos_index = index[test_idx]
        net_series = pd.Series(net_daily, index=oos_index)
        net_segments.append(net_series)
        fold_boundaries.append(oos_index[0])
        nav = (1.0 + net_series).cumprod()
```

  After the loop (after the `if not folds:` guard and the aggregate computations, just before `return WalkForwardResult(`), chain the segments into the global NAV:

```python
    # Chain every fold's NET daily series in time order, then compound once into
    # a single global NAV. Concatenation preserves the per-fold first-day cost
    # already baked into each segment; the result is the realized OOS equity
    # curve of the walk-forward process.
    chained_net = pd.concat(net_segments)
    chained_nav = (1.0 + chained_net).cumprod()
    oos_curve = [
        (idx_date, round(float(value), 8))
        for idx_date, value in zip(chained_nav.index, chained_nav.to_numpy(), strict=True)
    ]
```

  Add the two fields to the `return WalkForwardResult(...)` call (after `cost_bps=cost_bps,`):

```python
    return WalkForwardResult(
        folds=folds,
        n_splits_computed=len(folds),
        mean_sharpe=round(mean_sharpe, 6),
        std_sharpe=round(std_sharpe, 6),
        positive_folds=positive_folds,
        mean_turnover=round(mean_turnover, 6),
        cost_bps=cost_bps,
        oos_curve=oos_curve,
        fold_boundaries=fold_boundaries,
    )
```

> Note on `idx_date` type: `chained_nav.index` is a pandas DatetimeIndex; iterating yields `pd.Timestamp`. The schema field is `list[SeriesPoint]` = `list[tuple[dt.date, float]]`. Pydantic coerces a `Timestamp` to `dt.date` on the way out (it's used identically by the existing `FoldMetrics`/index code, and the `SeriesPoint` lists elsewhere in the repo are populated the same way from pandas indices). If mypy complains about the tuple element type, normalize explicitly with `idx_date.date()` — but only if mypy fails; do not add it preemptively.

- [x] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_analytics.py`
  - Expected: all tests pass (the new `oos_curve` tests plus the 6 pre-existing analytics tests), e.g. `8 passed`.

- [x] **Commit**:
  - `cd backend && git add app/analytics/backtest.py tests/test_backtest_analytics.py && git commit -m "feat(backtest): chain per-fold OOS net returns into a global equity curve"`

### Subtask 1b — schema + service: expose `oos_curve` / `fold_boundaries`

- [x] **Write failing test** — append to `backend/tests/test_backtest_schema.py`:

```python
import datetime as dt

from app.schemas.backtest import SeriesPoint  # noqa: F401 — re-exported alias


def test_response_carries_oos_curve_and_fold_boundaries() -> None:
    fold = FoldMetricsOut(
        fold=0, train_size=283, n_obs=2, sharpe=1.1, cvar_95=0.02,
        max_drawdown=-0.08, turnover=1.0, gross_return=0.03, net_return=0.029,
    )
    resp = WalkForwardResponse(
        folds=[fold],
        params=WalkForwardParams(
            objective="min_cvar", n_obs=600, n_splits_computed=1, gap=2,
            test_size=63, min_train_size=252, cost_bps=10.0,
        ),
        mean_sharpe=1.1, std_sharpe=0.0, positive_folds=1, mean_turnover=1.0,
        oos_curve=[(dt.date(2020, 1, 2), 1.0), (dt.date(2020, 1, 3), 1.01)],
        fold_boundaries=[dt.date(2020, 1, 2)],
    )
    dumped = resp.model_dump()
    # SeriesPoint serializes as a [date, number] 2-tuple.
    assert dumped["oos_curve"][0] == (dt.date(2020, 1, 2), 1.0)
    assert dumped["oos_curve"][1][1] == 1.01
    assert dumped["fold_boundaries"] == [dt.date(2020, 1, 2)]
```

- [x] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_schema.py -k oos_curve`
  - Expected: `ImportError: cannot import name 'SeriesPoint' from 'app.schemas.backtest'` (and the constructor would reject unknown kwargs).

- [x] **Implement** — edit `backend/app/schemas/backtest.py`.

  Add the `SeriesPoint` import (re-exported so tests and the service can import it from here). The current import block is:

```python
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.builder import AssetRefIn, ConstraintsIn, Objective
```

  Replace with:

```python
import datetime as dt
from typing import Annotated

from pydantic import BaseModel, Field

from app.schemas.analysis import SeriesPoint
from app.schemas.builder import AssetRefIn, ConstraintsIn, Objective

__all__ = [
    "SeriesPoint",
    "WalkForwardRequest",
    "FoldMetricsOut",
    "WalkForwardParams",
    "WalkForwardResponse",
]
```

  Add the two fields to `WalkForwardResponse` (currently ends with `mean_turnover: float`):

```python
class WalkForwardResponse(BaseModel):
    folds: list[FoldMetricsOut]
    params: WalkForwardParams
    mean_sharpe: float
    std_sharpe: float
    # Consistency, not significance: how many of n folds had a positive Sharpe.
    positive_folds: int
    mean_turnover: float
    # Realized out-of-sample equity curve: [date, nav] points compounded across
    # folds in time order (nav fraction, starts near 1.0). The fold boundaries
    # are the per-fold first OOS dates (re-optimization / rebalancing points).
    oos_curve: list[SeriesPoint] = Field(
        default_factory=list,
        description="Chained OOS NAV as [date, nav] points (decimal fraction NAV).",
    )
    fold_boundaries: list[dt.date] = Field(
        default_factory=list,
        description="First OOS date of each fold (plotLine markers).",
    )
```

> `dt` is now imported but the request section already uses bare `int | None`; `dt.date` is used only here. If ruff flags `dt` as unused after the edit, it is not — `fold_boundaries: list[dt.date]` references it.

  Now edit `backend/app/services/backtest.py` to map the new fields. The current `return WalkForwardResponse(...)` ends with `mean_turnover=result.mean_turnover,`. Add the two fields:

```python
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
        oos_curve=list(result.oos_curve),
        fold_boundaries=list(result.fold_boundaries),
    )
```

- [x] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_schema.py`
  - Expected: all schema tests pass (the new test plus the 4 pre-existing), e.g. `5 passed`.

- [x] **Commit**:
  - `cd backend && git add app/schemas/backtest.py app/services/backtest.py tests/test_backtest_schema.py && git commit -m "feat(backtest): expose oos_curve + fold_boundaries on WalkForwardResponse"`

### Subtask 1c — route: end-to-end curve in the HTTP response

- [x] **Write failing test** — append to `backend/tests/test_backtest_route.py`:

```python
async def test_walk_forward_response_carries_oos_curve(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "min_cvar",
               "constraints": {"cap": 0.5}}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    # One OOS point per observation across all folds (5 folds × 63 = 315).
    total_obs = sum(f["n_obs"] for f in body["folds"])
    assert len(body["oos_curve"]) == total_obs
    # Each point is a [iso_date, nav] 2-element array; nav is finite & positive.
    first = body["oos_curve"][0]
    assert isinstance(first, list) and len(first) == 2
    assert isinstance(first[0], str)  # ISO date
    assert float(first[1]) > 0
    # One boundary per fold; the first boundary == the first curve date.
    assert len(body["fold_boundaries"]) == len(body["folds"])
    assert body["fold_boundaries"][0] == first[0]
```

- [x] **Run the test (expect FAIL or, if 1b is already merged, possibly PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_route.py -k oos_curve`
  - Expected: with 1b implemented, the route already serializes the fields, so this likely PASSES. If running this subtask before 1b's implementation, it fails with `KeyError: 'oos_curve'`. Either way the assertion set is the contract check; keep it.

- [x] **Implement** — no production change needed (the route returns the service's `WalkForwardResponse` unchanged). This subtask is a contract guard only.

- [x] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_route.py`
  - Expected: all route tests pass (the new one plus the pre-existing), e.g. `8 passed`.

- [x] **Commit**:
  - `cd backend && git add tests/test_backtest_route.py && git commit -m "test(backtest): assert OOS curve is present in the HTTP response"`

---

## Task 2 — Portfolio Monte Carlo endpoint `POST /monte-carlo/portfolio`

Build a synthetic portfolio return series from the optimized weights (`portfolio_returns = frame @ w`, weights aligned to `frame.columns`), then run the EXISTING pure `block_bootstrap_monte_carlo`. Reuse `ConfidenceBar` and the distribution fields of `MonteCarloResponse`; the portfolio params carry `n_assets` instead of `ticker`. The single-instrument `/monte-carlo/projection` and `block_bootstrap_monte_carlo` are NOT touched.

**Assumption (document in code + docstring):** target weights are held constant over the horizon — equivalent to continuous rebalancing back to the optimized weights. Consistent with the risk-decomposition tab. Inherits the loader gate (`MIN_COMMON_OBS = 400`) and the MC gate (`_MIN_HISTORY = 42`); fails loud (422) when insufficient.

**Files:**
- Modify: `backend/app/analytics/monte_carlo.py` (add pure `assemble_portfolio_monte_carlo`... — see note)
- Modify: `backend/app/schemas/monte_carlo.py` (add `PortfolioMonteCarloRequest`, `PortfolioMonteCarloParams`, `PortfolioMonteCarloResponse`, `PortfolioPositionIn`)
- Modify: `backend/app/services/monte_carlo.py` (add `assemble_portfolio_monte_carlo` + `run_portfolio_monte_carlo`)
- Modify: `backend/app/api/routes/monte_carlo.py` (add `POST /monte-carlo/portfolio`)
- Test: `backend/tests/test_monte_carlo_service.py` (synthetic series, misalignment, gate, passes through core)
- Test: `backend/tests/test_monte_carlo_route.py` (response shape, 422 on insufficient history)

> **Placement decision (faithful to the codebase):** the spec text §132 says "a new `assemble_portfolio_monte_carlo`". The existing `assemble_monte_carlo` lives in the SERVICE module (`app/services/monte_carlo.py`), not the analytics module — `assemble_*` here means "pure adapter from a numpy array to the response schema". To mirror that exactly, `assemble_portfolio_monte_carlo` goes in `app/services/monte_carlo.py` next to `assemble_monte_carlo`. `app/analytics/monte_carlo.py` stays UNCHANGED (the spec's "Arquivos afetados" §165 explicitly lists `app/analytics/monte_carlo.py` as unchanged). The plan follows the spec's file list, not the looser prose.

### Subtask 2a — schemas

- [x] **Write failing test** — create `backend/tests/test_monte_carlo_portfolio_schema.py`:

```python
"""Schema contract for POST /monte-carlo/portfolio."""

import uuid

import pytest
from pydantic import ValidationError

from app.schemas.monte_carlo import (
    PortfolioMonteCarloParams,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
    PortfolioPositionIn,
)


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}"))}


def test_request_defaults() -> None:
    req = PortfolioMonteCarloRequest.model_validate(
        {"positions": [{"asset": _fund(1), "weight": 0.6},
                       {"asset": _fund(2), "weight": 0.4}]}
    )
    assert req.statistic == "max_drawdown"
    assert req.n_simulations == 10_000
    assert req.horizons is None
    assert req.risk_free_rate == pytest.approx(0.04)
    assert req.seed is None
    assert req.window_days is None
    assert len(req.positions) == 2


def test_request_requires_at_least_two_positions() -> None:
    with pytest.raises(ValidationError):
        PortfolioMonteCarloRequest.model_validate(
            {"positions": [{"asset": _fund(1), "weight": 1.0}]}
        )


def test_request_position_weight_bounds() -> None:
    with pytest.raises(ValidationError):
        PortfolioPositionIn.model_validate({"asset": _fund(1), "weight": 0.0})
    with pytest.raises(ValidationError):
        PortfolioPositionIn.model_validate({"asset": _fund(1), "weight": 1.5})


def test_request_rejects_unknown_statistic() -> None:
    with pytest.raises(ValidationError):
        PortfolioMonteCarloRequest.model_validate(
            {"positions": [{"asset": _fund(1), "weight": 0.5},
                           {"asset": _fund(2), "weight": 0.5}],
             "statistic": "median"}
        )


def test_response_params_have_n_assets_not_ticker() -> None:
    params = PortfolioMonteCarloParams(
        statistic="return", n_assets=3, n_simulations=10_000,
        risk_free_rate=0.04, seed=7,
    )
    dumped = params.model_dump()
    assert dumped["n_assets"] == 3
    assert "ticker" not in dumped


def test_response_round_trips_confidence_bars() -> None:
    from app.schemas.monte_carlo import ConfidenceBar

    resp = PortfolioMonteCarloResponse(
        params=PortfolioMonteCarloParams(
            statistic="return", n_assets=2, n_simulations=10_000,
            risk_free_rate=0.04, seed=None,
        ),
        percentiles={"50th": 0.05},
        mean=0.05, median=0.05, std=0.01,
        historical_value=0.04, historical_horizon_days=500,
        historical_percentile_rank=42.0,
        confidence_bars=[ConfidenceBar(
            horizon="1Y", horizon_days=252, pct_5=-0.1, pct_10=-0.05,
            pct_25=0.0, pct_50=0.05, pct_75=0.1, pct_90=0.15, pct_95=0.2, mean=0.05,
        )],
        degraded=False, degraded_reason=None,
    )
    dumped = resp.model_dump()
    assert dumped["confidence_bars"][0]["horizon"] == "1Y"
    assert dumped["historical_percentile_rank"] == 42.0
    assert dumped["params"]["n_assets"] == 2
```

- [x] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_portfolio_schema.py`
  - Expected: `ImportError: cannot import name 'PortfolioMonteCarloRequest' from 'app.schemas.monte_carlo'`.

- [x] **Implement** — edit `backend/app/schemas/monte_carlo.py`. Add the builder asset ref import to the top import block:

  Current:
```python
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas._tickers import normalize_ticker as _normalize_ticker
from app.schemas.analysis import RangeKey
```

  Replace with:
```python
from typing import Annotated, Literal

from pydantic import BaseModel, Field, field_validator

from app.schemas._tickers import normalize_ticker as _normalize_ticker
from app.schemas.analysis import RangeKey
from app.schemas.builder import AssetRefIn
```

  Append at the end of the file (after `MonteCarloResponse`):

```python
# ── Portfolio Monte Carlo (POST /monte-carlo/portfolio) ──────────────────────


class PortfolioPositionIn(BaseModel):
    """One position in a synthetic portfolio MC request.

    ``asset`` reuses the builder ref (FundRefIn | EquityRefIn) so the request is
    the exact weight list the optimizer returned; ``weight`` is a decimal
    fraction (0 < w <= 1). The service aligns weights to the loaded return
    frame's columns by the 'fund:{id}' / 'equity:{TICKER}' label scheme.
    """

    asset: AssetRefIn
    weight: Annotated[float, Field(gt=0, le=1, allow_inf_nan=False)]


class PortfolioMonteCarloRequest(BaseModel):
    """Block-bootstrap Monte Carlo over a synthetic portfolio NAV.

    The service builds ``portfolio_returns = frame @ w`` from the common-history
    aligned returns of the positions (target weights held = implicit continuous
    rebalancing), then runs the SAME pure ``block_bootstrap_monte_carlo`` the
    single-instrument projection uses.
    """

    positions: Annotated[list[PortfolioPositionIn], Field(min_length=2, max_length=50)]
    statistic: Statistic = Field(
        default="max_drawdown",
        description="Which statistic to project: max_drawdown | return | sharpe.",
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
    # None = FULL nav_timeseries/eod history (the builder/backtest convention).
    # An explicit int (30..3650 days) narrows the estimation window.
    window_days: Annotated[int | None, Field(ge=30, le=3650)] = None

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


class PortfolioMonteCarloParams(BaseModel):
    """Echo of the resolved portfolio MC parameters (no ticker; n_assets instead)."""

    statistic: Statistic
    n_assets: int
    n_simulations: int
    risk_free_rate: float
    seed: int | None = Field(description="Seed used, or null when unseeded.")


class PortfolioMonteCarloResponse(BaseModel):
    """Render-ready portfolio Monte Carlo payload.

    Reuses the single-instrument distribution shape (``ConfidenceBar``,
    percentiles, historical rank, degraded flags); only ``params`` differs
    (n_assets instead of ticker/range). Drawdown/return fields are decimal
    fractions (0.05 = 5%); sharpe is unitless.
    """

    params: PortfolioMonteCarloParams
    percentiles: dict[str, float] = Field(
        description="Distribution of the statistic at the longest horizon, keyed by "
        "percentile ('1st'..'99th')."
    )
    mean: float
    median: float
    std: float
    historical_value: float = Field(
        description="The statistic computed on the ACTUAL synthetic portfolio series."
    )
    historical_horizon_days: int = Field(
        description="Length of the synthetic portfolio series in trading days."
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

- [x] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_portfolio_schema.py`
  - Expected: all 6 tests pass.

- [x] **Commit**:
  - `cd backend && git add app/schemas/monte_carlo.py tests/test_monte_carlo_portfolio_schema.py && git commit -m "feat(monte-carlo): portfolio MC request/response schemas (n_assets, reuse ConfidenceBar)"`

### Subtask 2b — service: `assemble_portfolio_monte_carlo` + `run_portfolio_monte_carlo`

- [x] **Write failing test** — append to `backend/tests/test_monte_carlo_service.py`:

```python
import datetime as dt
import uuid
from typing import Any

import pandas as pd

from app.optimizer import data as optimizer_data
from app.schemas.monte_carlo import PortfolioMonteCarloRequest, PortfolioMonteCarloResponse
from app.services import monte_carlo as mc_service
from app.services.monte_carlo import assemble_portfolio_monte_carlo, run_portfolio_monte_carlo

_PMC_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]


def _pmc_fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_PMC_FUND_IDS[i])}


def _aligned_frame(n_obs: int = 500, seed: int = 21) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    index = pd.bdate_range("2018-01-02", periods=n_obs)
    labels = [f"fund:{_PMC_FUND_IDS[i]}" for i in range(2)]
    return pd.DataFrame(
        {lbl: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs) for i, lbl in enumerate(labels)},
        index=index,
    )


def test_assemble_portfolio_uses_frame_at_w_synthetic_series() -> None:
    # The portfolio series fed to the bootstrap must equal frame @ w EXACTLY:
    # we verify by comparing the historical_value to the statistic recomputed on
    # frame @ w via the pure analytics layer (same numbers, no I/O).
    from app.analytics.monte_carlo import block_bootstrap_monte_carlo

    frame = _aligned_frame()
    w = np.array([0.7, 0.3])
    series = frame.to_numpy() @ w
    expected = block_bootstrap_monte_carlo(
        series, n_simulations=2000, statistic="return", seed=3,
    )
    resp = assemble_portfolio_monte_carlo(
        series, statistic="return", n_assets=2, n_simulations=2000,
        horizons=None, risk_free_rate=0.04, seed=3,
    )
    assert resp.params.n_assets == 2
    assert resp.historical_value == expected.historical_value
    assert resp.percentiles == expected.percentiles


def test_assemble_short_history_maps_to_insufficient_data() -> None:
    from app.services.stock_analysis import InsufficientDataError

    short = np.random.default_rng(0).normal(0.0004, 0.01, 40)
    with pytest.raises(InsufficientDataError, match="insufficient_history"):
        assemble_portfolio_monte_carlo(
            short, statistic="max_drawdown", n_assets=2, n_simulations=1000,
            horizons=None, risk_free_rate=0.04, seed=1,
        )


async def test_run_builds_weight_vector_aligned_to_frame_columns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    frame = _aligned_frame()

    async def fake_load(session: Any, assets: Any, window_days: int | None = None,
                        today: dt.date | None = None) -> pd.DataFrame:
        # Return columns in a DIFFERENT order than positions to prove alignment.
        return frame[list(reversed(frame.columns))]

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = PortfolioMonteCarloRequest.model_validate(
        {"positions": [{"asset": _pmc_fund(0), "weight": 0.7},
                       {"asset": _pmc_fund(1), "weight": 0.3}],
         "statistic": "return", "n_simulations": 2000, "seed": 3}
    )
    resp = await run_portfolio_monte_carlo(None, payload)
    assert isinstance(resp, PortfolioMonteCarloResponse)
    assert resp.params.n_assets == 2
    # Same as the hand-built synthetic series (alignment by label, not order).
    series = frame.to_numpy() @ np.array([0.7, 0.3])
    from app.analytics.monte_carlo import block_bootstrap_monte_carlo
    expected = block_bootstrap_monte_carlo(series, n_simulations=2000, statistic="return", seed=3)
    assert resp.percentiles == expected.percentiles


async def test_run_insufficient_common_history_maps_to_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services.stock_analysis import InsufficientDataError

    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = PortfolioMonteCarloRequest.model_validate(
        {"positions": [{"asset": _pmc_fund(0), "weight": 0.5},
                       {"asset": _pmc_fund(1), "weight": 0.5}]}
    )
    with pytest.raises(InsufficientDataError, match="insufficient common history"):
        await run_portfolio_monte_carlo(None, payload)
```

- [x] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_service.py -k portfolio`
  - Expected: `ImportError: cannot import name 'assemble_portfolio_monte_carlo' from 'app.services.monte_carlo'`.

- [x] **Implement** — edit `backend/app/services/monte_carlo.py`.

  Extend the imports. Current top block includes:
```python
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
```

  Add the new schema imports and the optimizer data/loader + builder ref converter:
```python
from app.analytics.monte_carlo import block_bootstrap_monte_carlo
from app.analytics.returns import simple_returns
from app.api._shared import ensure_eod_or_http_error
from app.ingestion.service import HISTORY_FLOOR
from app.optimizer import data as optimizer_data
from app.schemas.analysis import RangeKey
from app.schemas.monte_carlo import (
    ConfidenceBar,
    MonteCarloParams,
    MonteCarloResponse,
    PortfolioMonteCarloParams,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
    Statistic,
)
from app.services.portfolio_builder import _to_data_ref
```

  Append the two new functions at the end of the file (after `run_monte_carlo`):

```python
def assemble_portfolio_monte_carlo(
    portfolio_returns: np.ndarray,
    *,
    statistic: Statistic,
    n_assets: int,
    n_simulations: int,
    horizons: list[int] | None,
    risk_free_rate: float,
    seed: int | None,
) -> PortfolioMonteCarloResponse:
    """Build the portfolio projection payload from a 1-D return array (pure, no I/O).

    Analogous to ``assemble_monte_carlo`` but the params carry ``n_assets``
    instead of a ticker/range. Reuses the EXACT pure
    ``block_bootstrap_monte_carlo`` core.

    Raises:
        InsufficientDataError: if the analytics layer rejects the input (too
            little history, or history too short for the horizon).
    """
    try:
        result = block_bootstrap_monte_carlo(
            portfolio_returns,
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

    return PortfolioMonteCarloResponse(
        params=PortfolioMonteCarloParams(
            statistic=statistic,
            n_assets=n_assets,
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


async def run_portfolio_monte_carlo(
    session: AsyncSession,
    payload: PortfolioMonteCarloRequest,
) -> PortfolioMonteCarloResponse:
    """Load the positions' common-history returns, build the synthetic portfolio
    NAV (target weights held = implicit rebalancing), then assemble.

    The weight vector is aligned to ``frame.columns`` by the 'fund:{id}' /
    'equity:{TICKER}' label scheme, so column order from the loader never
    matters. Inherits the loader gate (MIN_COMMON_OBS) and the MC history guard;
    both surface as InsufficientDataError (→ 422 at the route).

    Raises:
        InsufficientDataError: unknown asset / empty window, fewer than
            MIN_COMMON_OBS common dates, or the analytics layer rejects the
            synthetic return array.
    """
    refs = [_to_data_ref(pos.asset) for pos in payload.positions]
    try:
        frame = await optimizer_data.load_aligned_returns(
            session, refs, window_days=payload.window_days
        )
    except ValueError as exc:
        raise InsufficientDataError(str(exc)) from exc

    # Align the weight vector to the loaded frame's columns by label. A position
    # whose label is absent from the frame is a fail-loud domain error (the
    # loader returns exactly the requested labels, so this only fires on a real
    # mismatch — never silently dropped).
    weight_by_label = {ref.label: pos.weight for ref, pos in zip(refs, payload.positions, strict=True)}
    try:
        w = np.array([weight_by_label[str(col)] for col in frame.columns], dtype=float)
    except KeyError as exc:
        raise InsufficientDataError(
            f"position {exc.args[0]} is missing from the loaded return frame — "
            "every position must resolve to a column in the aligned history"
        ) from exc

    portfolio_returns = frame.to_numpy(dtype=float) @ w
    return assemble_portfolio_monte_carlo(
        portfolio_returns,
        statistic=payload.statistic,
        n_assets=len(payload.positions),
        n_simulations=payload.n_simulations,
        horizons=payload.horizons,
        risk_free_rate=payload.risk_free_rate,
        seed=payload.seed,
    )
```

> Weights are NOT renormalized: the optimizer's weights already sum to 1 (long-only sum-1 contract). Holding them constant over the horizon is the documented rebalancing assumption. If a caller sends weights that do not sum to 1, the synthetic series simply reflects the under/over-investment they sent — fail-loud is reserved for missing data, not for the user's chosen weights.

- [x] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_service.py`
  - Expected: all tests pass (the new portfolio tests plus the pre-existing single-instrument ones).

- [x] **Commit**:
  - `cd backend && git add app/services/monte_carlo.py tests/test_monte_carlo_service.py && git commit -m "feat(monte-carlo): run_portfolio_monte_carlo builds frame@w and reuses the pure core"`

### Subtask 2c — route: `POST /monte-carlo/portfolio`

- [ ] **Write failing test** — create `backend/tests/test_monte_carlo_portfolio_route.py`:

```python
"""Tests for POST /monte-carlo/portfolio.

The DB loader is stubbed at app.optimizer.data; the pure MC core stays LIVE.
The session dependency is overridden (no live DB, no Tiingo — the portfolio
route reads only the data-lake via the loader).
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

_FUND_IDS = [uuid.UUID(f"00000000-0000-0000-0000-00000000000{i}") for i in range(1, 4)]


def _client() -> AsyncClient:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: None
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _fund(i: int) -> dict[str, str]:
    return {"kind": "fund", "id": str(_FUND_IDS[i])}


def _stub_frame(monkeypatch: pytest.MonkeyPatch, n_obs: int = 500) -> None:
    async def fake_load(session: Any, assets: list[optimizer_data.AssetRef],
                        window_days: int | None = None,
                        today: dt.date | None = None) -> pd.DataFrame:
        rng = np.random.default_rng(17)
        index = pd.bdate_range("2018-01-02", periods=n_obs)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.009 + 0.001 * i, n_obs)
             for i, ref in enumerate(assets)},
            index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)


async def test_portfolio_happy_path_shape(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_frame(monkeypatch)
    payload = {"positions": [{"asset": _fund(0), "weight": 0.6},
                             {"asset": _fund(1), "weight": 0.4}],
               "statistic": "return", "n_simulations": 2000, "seed": 7}
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {
        "params", "percentiles", "mean", "median", "std",
        "historical_value", "historical_horizon_days",
        "historical_percentile_rank", "confidence_bars",
        "degraded", "degraded_reason",
    }
    assert body["params"]["n_assets"] == 2
    assert "ticker" not in body["params"]
    assert body["confidence_bars"][0]["horizon"] == "1Y"
    assert set(body["percentiles"].keys()) == {
        "1st", "5th", "10th", "25th", "50th", "75th", "90th", "95th", "99th"
    }


async def test_portfolio_is_deterministic_under_seed(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_frame(monkeypatch)
    payload = {"positions": [{"asset": _fund(0), "weight": 0.5},
                             {"asset": _fund(1), "weight": 0.5}],
               "statistic": "max_drawdown", "n_simulations": 1500, "seed": 5}
    async with _client() as client:
        a = (await client.post("/monte-carlo/portfolio", json=payload)).json()
        b = (await client.post("/monte-carlo/portfolio", json=payload)).json()
    assert a["percentiles"] == b["percentiles"]


async def test_portfolio_insufficient_common_history_422(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        raise ValueError("insufficient common history: 120 overlapping observations")

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = {"positions": [{"asset": _fund(0), "weight": 0.5},
                             {"asset": _fund(1), "weight": 0.5}]}
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422
    assert "insufficient common history" in response.json()["detail"]


async def test_portfolio_bad_weight_is_pydantic_422() -> None:
    payload = {"positions": [{"asset": _fund(0), "weight": 0.0},
                             {"asset": _fund(1), "weight": 1.0}]}
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422  # weight gt=0


async def test_portfolio_requires_two_positions_422() -> None:
    payload = {"positions": [{"asset": _fund(0), "weight": 1.0}]}
    async with _client() as client:
        response = await client.post("/monte-carlo/portfolio", json=payload)
    assert response.status_code == 422  # min_length=2
```

- [ ] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_portfolio_route.py`
  - Expected: `404` on the happy path (route not registered yet) → assertion failure.

- [ ] **Implement** — edit `backend/app/api/routes/monte_carlo.py`. Extend imports and add the route.

  Current imports:
```python
from app.schemas.monte_carlo import MonteCarloRequest, MonteCarloResponse
from app.services.monte_carlo import run_monte_carlo
from app.services.stock_analysis import InsufficientDataError, StockAnalysisError
from app.tiingo.client import TiingoClient
```

  Replace with:
```python
from app.schemas.monte_carlo import (
    MonteCarloRequest,
    MonteCarloResponse,
    PortfolioMonteCarloRequest,
    PortfolioMonteCarloResponse,
)
from app.services.monte_carlo import run_monte_carlo, run_portfolio_monte_carlo
from app.services.stock_analysis import InsufficientDataError, StockAnalysisError
from app.tiingo.client import TiingoClient
```

  Append the new route after `project_monte_carlo` (the portfolio route needs only the DB session — the loader reads the data-lake, no Tiingo warm step):

```python
@router.post("/portfolio", response_model=PortfolioMonteCarloResponse)
async def project_portfolio_monte_carlo(
    payload: PortfolioMonteCarloRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PortfolioMonteCarloResponse:
    """Block-bootstrap Monte Carlo over a synthetic portfolio NAV.

    Builds the portfolio return series from the positions' common-history
    aligned returns (target weights held = implicit rebalancing) and runs the
    SAME block-bootstrap core as the single-instrument projection. Drawdown/
    return fields are decimal fractions (0.05 = 5%); sharpe is unitless.

    Error mapping (fail loud):
    - request shape / weight bounds / position count -> 422 (Pydantic)
    - unknown asset / no history in window           -> 422
    - < MIN_COMMON_OBS common observations           -> 422
    - history too short for the requested horizon    -> 422
    """
    try:
        return await run_portfolio_monte_carlo(session, payload)
    except InsufficientDataError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

- [ ] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_portfolio_route.py`
  - Expected: all 5 tests pass.

- [ ] **Run the single-instrument route tests (regression)**:
  - Command: `cd backend && uv run pytest -q tests/test_monte_carlo_route.py`
  - Expected: unchanged, all pass (the `/projection` route is untouched).

- [ ] **Commit**:
  - `cd backend && git add app/api/routes/monte_carlo.py tests/test_monte_carlo_portfolio_route.py && git commit -m "feat(monte-carlo): add POST /monte-carlo/portfolio (thin route, ValueError→422)"`

---

## Task 3 — Walk-forward accepts `max_return_cvar` (equilibrium mode)

Today `_solve_fn_for` rejects `max_return_cvar`. The per-fold solve closure receives only the train return matrix — it has no AUMs. Compute `w_mkt` ONCE in the service (via the existing `_market_weights_for` path, funds-only AUM today) and thread it into the closure so each fold computes `π = δ·Σ_train·w_mkt` (via `bl.equilibrium` + `engine.sigma_ledoit_wolf`) and solves `engine.solve_max_return_cvar_capped`. Keep rejecting `bl_utility` (and any path with views — the request has none). The request gains a `cvar_limit` (required for the equilibrium objective).

**Methodological note (put in the closure docstring):** `w_mkt` is derived from CURRENT AUM and used as an EXOGENOUS, stable input across all folds — a mild, defensible hindsight (AUM is slow-moving and not a return forecast; gate G5 forbids only sample-mean return objectives). δ is fixed at `bl.DEFAULT_DELTA`; per the onda-0 design note, δ scales `π` but does not move the argmax of the linear `max_return_cvar` objective — only the direction `Σ·w_mkt` and the `cvar_limit` bite.

**Files:**
- Modify: `backend/app/schemas/backtest.py` (add `cvar_limit` to `WalkForwardRequest` + cross-field validator)
- Modify: `backend/app/services/backtest.py` (new `w_mkt`-aware closure; compute `w_mkt` once; remove the `max_return_cvar` rejection; keep `bl_utility` rejection)
- Test: `backend/tests/test_backtest_service.py` (equilibrium folds; equities fail loud; bl_utility still rejected; missing cvar_limit rejected)
- Test: `backend/tests/test_backtest_route.py` (equilibrium happy path; equities 422)

### Subtask 3a — schema: `cvar_limit` on the request

- [ ] **Write failing test** — append to `backend/tests/test_backtest_schema.py`:

```python
def test_request_accepts_cvar_limit() -> None:
    req = WalkForwardRequest.model_validate(
        {"assets": [_fund(1), _fund(2)], "objective": "max_return_cvar",
         "cvar_limit": 0.02}
    )
    assert req.objective == "max_return_cvar"
    assert req.cvar_limit == 0.02


def test_request_max_return_cvar_requires_cvar_limit() -> None:
    with pytest.raises(ValidationError, match="cvar_limit"):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "objective": "max_return_cvar"}
        )


def test_request_cvar_limit_bounds() -> None:
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "objective": "max_return_cvar",
             "cvar_limit": 0.0}  # gt=0
        )
    with pytest.raises(ValidationError):
        WalkForwardRequest.model_validate(
            {"assets": [_fund(1), _fund(2)], "objective": "max_return_cvar",
             "cvar_limit": 1.5}  # le=1
        )
```

- [ ] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_schema.py -k cvar_limit`
  - Expected: `max_return_cvar` validates fine WITHOUT a cvar_limit (no constraint yet), so `test_request_max_return_cvar_requires_cvar_limit` fails (no ValidationError raised).

- [ ] **Implement** — edit `backend/app/schemas/backtest.py`. Add `model_validator` to the pydantic import and add the field + validator to `WalkForwardRequest`.

  Current import line:
```python
from pydantic import BaseModel, Field
```
  Replace with:
```python
from pydantic import BaseModel, Field, model_validator
```

  Add the `cvar_limit` field to `WalkForwardRequest` (after `risk_free_annual`) and a cross-field validator:

```python
    cost_bps: Annotated[float, Field(ge=0, le=1000)] = 10.0
    risk_free_annual: Annotated[float, Field(ge=0, le=1)] = 0.0
    # Daily tail-loss cap for the ``max_return_cvar`` (equilibrium) objective
    # (decimal fraction, e.g. 0.02 = 2% daily CVaR_95). Required for that
    # objective, ignored otherwise. Mirrors OptimizeRequest.cvar_limit.
    cvar_limit: Annotated[float, Field(gt=0, le=1)] | None = None

    @model_validator(mode="after")
    def _check_cvar_limit(self) -> "WalkForwardRequest":
        if self.objective == "max_return_cvar" and self.cvar_limit is None:
            raise ValueError(
                "max_return_cvar requires a cvar_limit (daily tail-loss cap) — "
                "the walk-forward runs the equilibrium objective (π = δ·Σ·w_mkt) "
                "with no views"
            )
        return self
```

- [ ] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_schema.py`
  - Expected: all pass (new cvar_limit tests plus the earlier oos_curve + defaults tests).

- [ ] **Commit**:
  - `cd backend && git add app/schemas/backtest.py tests/test_backtest_schema.py && git commit -m "feat(backtest): WalkForwardRequest accepts cvar_limit (required for max_return_cvar)"`

### Subtask 3b — service: thread `w_mkt` into the per-fold closure

- [ ] **Write failing test** — append to `backend/tests/test_backtest_service.py`:

```python
def test_solve_fn_max_return_cvar_with_w_mkt_solves() -> None:
    # With a w_mkt the closure no longer rejects max_return_cvar: it builds
    # π = δ·Σ_train·w_mkt per fold and solves the capped objective.
    rng = np.random.default_rng(2)
    train = rng.normal(0.0005, 0.01, (300, 3))
    w_mkt = np.array([0.5, 0.3, 0.2])
    fn = _solve_fn_for(
        "max_return_cvar", cap=0.6, min_weight=None,
        w_mkt=w_mkt, cvar_limit=0.05,
    )
    w = fn(train)
    assert abs(float(w.sum()) - 1.0) < 1e-6
    assert (w >= -1e-9).all() and (w <= 0.6 + 1e-6).all()


def test_solve_fn_max_return_cvar_without_w_mkt_is_rejected() -> None:
    # No w_mkt (e.g. a non-equilibrium caller): the closure must fail loud.
    with pytest.raises(BacktestError, match="max_return_cvar"):
        _solve_fn_for("max_return_cvar", cap=0.25, min_weight=None)


async def test_run_max_return_cvar_equilibrium_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)

    async def fake_w_mkt(session: Any, assets: Any, labels: list[str]) -> np.ndarray:
        # Equal market weights — the service only needs a valid w_mkt vector.
        return np.full(len(labels), 1.0 / len(labels))

    monkeypatch.setattr(backtest_service, "_market_weights_for", fake_w_mkt)
    payload = WalkForwardRequest.model_validate(
        {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "max_return_cvar",
         "cvar_limit": 0.05, "constraints": {"cap": 0.6}}
    )
    resp = await backtest_service.run_walk_forward_backtest(None, payload)
    assert isinstance(resp, WalkForwardResponse)
    assert resp.params.objective == "max_return_cvar"
    assert resp.params.n_splits_computed == 5
    assert len(resp.folds) == 5


async def test_run_max_return_cvar_equities_fail_loud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The real _market_weights_for rejects equities (no market cap in the
    # builder); the service must surface that as a BacktestError.
    async def fake_load(session: Any, assets: Any, **kwargs: Any) -> pd.DataFrame:
        rng = np.random.default_rng(5)
        index = pd.bdate_range("2018-01-02", periods=600)
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, 600) for ref in assets}, index=index,
        )

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    payload = WalkForwardRequest.model_validate(
        {"assets": [{"kind": "equity", "ticker": "SPY"},
                    {"kind": "equity", "ticker": "AGG"}],
         "objective": "max_return_cvar", "cvar_limit": 0.05, "constraints": {"cap": 0.6}}
    )
    with pytest.raises(backtest_service.BacktestError, match="equities"):
        await backtest_service.run_walk_forward_backtest(None, payload)
```

> The existing `test_solve_fn_max_return_cvar_is_rejected` test (lines 68-70) asserts the OLD behaviour ("max_return_cvar is not backtestable"). It is REPLACED by `test_solve_fn_max_return_cvar_without_w_mkt_is_rejected`. Delete the old test in the implement step below.

- [ ] **Run the test (expect FAIL)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_service.py -k max_return_cvar`
  - Expected: `TypeError: _solve_fn_for() got an unexpected keyword argument 'w_mkt'` (and the old rejection test still asserts the not-backtestable message).

- [ ] **Implement** — edit `backend/app/services/backtest.py`.

  Extend imports (add BL + numpy types already present). Current:
```python
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
```
  Replace with:
```python
import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.analytics.backtest import SolveFn, assemble_walk_forward_backtest
from app.optimizer import black_litterman as bl
from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.backtest import (
    FoldMetricsOut,
    WalkForwardParams,
    WalkForwardRequest,
    WalkForwardResponse,
)
from app.schemas.builder import Objective
from app.services.portfolio_builder import _market_weights_for, _to_data_ref
```

  Rewrite `_solve_fn_for` to accept optional `w_mkt` / `cvar_limit`, drop the `max_return_cvar` rejection, and add the equilibrium branch. Replace the whole function:

```python
def _solve_fn_for(
    objective: Objective,
    cap: float | None,
    min_weight: float | None,
    *,
    w_mkt: np.ndarray | None = None,
    cvar_limit: float | None = None,
    delta: float = bl.DEFAULT_DELTA,
) -> SolveFn:
    """Build the per-fold solver closure for a backtestable objective.

    Wraps ``app.optimizer.engine`` so each call re-optimizes on the fold's TRAIN
    matrix. ``min_cvar`` solves on the raw scenarios (Rockafellar-Uryasev); the
    covariance objectives shrink Sigma with Ledoit-Wolf first.

    ``max_return_cvar`` runs in EQUILIBRIUM mode: with no views, μ is the BL
    equilibrium return π = δ·Σ_train·w_mkt (reverse optimization), which is
    G5-safe (π is not a sample-mean return forecast). The closure needs
    ``w_mkt`` (computed ONCE by the service from current AUM) and ``cvar_limit``;
    without ``w_mkt`` it fails loud. ``w_mkt`` is an EXOGENOUS, stable input held
    fixed across folds — a mild, defensible hindsight (AUM is slow-moving). δ
    scales π but does not move the argmax of this linear objective; only the
    direction Σ·w_mkt and the cvar_limit bite (onda-0 methodological note).

    ``bl_utility`` is rejected up-front: it maximizes the Black-Litterman
    posterior formed with hindsight VIEWS (which a backtest must not consume).
    Each engine solver returns a ``(weights, status)`` tuple; the closure keeps
    the weights.
    """
    if objective == "bl_utility":
        raise BacktestError(
            "bl_utility is not backtestable: Black-Litterman views are formed "
            "with hindsight; backtest a mu-free objective (min_cvar/min_vol/erc/"
            "max_diversification/equal_weight) or max_return_cvar (equilibrium)"
        )
    if objective == "max_return_cvar":
        if w_mkt is None or cvar_limit is None:
            raise BacktestError(
                "max_return_cvar backtest requires market weights and a "
                "cvar_limit (equilibrium mode); none were supplied"
            )

        w_mkt_vec = np.asarray(w_mkt, dtype=float).ravel()

        def solve_equilibrium(train: np.ndarray) -> np.ndarray:
            sigma = engine.sigma_ledoit_wolf(train)
            pi = bl.equilibrium(sigma, w_mkt_vec, delta=delta)
            weights, _ = engine.solve_max_return_cvar_capped(
                train, mu=pi, cvar_limit=cvar_limit, cap=cap, min_weight=min_weight
            )
            return weights

        return solve_equilibrium

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
        else:  # pragma: no cover - bl_utility/max_return_cvar handled above
            raise BacktestError(f"unknown objective: {objective}")
        return weights

    return solve
```

  Now thread `w_mkt` through `run_walk_forward_backtest`. The current body loads the frame, then calls `_solve_fn_for(payload.objective, ...)`. Insert the `w_mkt` computation BETWEEN the frame load and the solve_fn build, and pass the new kwargs. Replace from the `solve_fn = _solve_fn_for(...)` line:

```python
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

    # Equilibrium-mode max_return_cvar needs market weights for π = δ·Σ·w_mkt.
    # Compute them ONCE from current AUM (the same path the builder uses) and
    # thread them into every fold's solve closure. _market_weights_for fails
    # loud on equities / funds without AUM (→ BacktestError verbatim).
    w_mkt: np.ndarray | None = None
    if payload.objective == "max_return_cvar":
        labels = list(frame.columns)
        try:
            w_mkt = await _market_weights_for(session, list(payload.assets), labels)
        except ValueError as exc:
            raise BacktestError(str(exc)) from exc

    solve_fn = _solve_fn_for(
        payload.objective,
        payload.constraints.cap,
        payload.constraints.min_weight,
        w_mkt=w_mkt,
        cvar_limit=payload.cvar_limit,
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
```

  (The `return WalkForwardResponse(...)` block — including the `oos_curve` / `fold_boundaries` added in Task 1 — is unchanged.)

  Notes for the worker:
  - `_market_weights_for` raises `BuilderError`, which is a subclass of `ValueError`; the `except ValueError` catches it and re-raises as `BacktestError`. Its message contains the substring "equities" on the equity path, satisfying the test.
  - `_market_weights_for` takes `list[AssetRefIn]` and `labels: list[str]`. `payload.assets` is already `list[AssetRefIn]`; `labels` MUST be the frame's column order (the function maps fund AUMs to labels positionally — see portfolio_builder.py:173). Build `labels` from `frame.columns`, not from `payload.assets`, so the alignment matches `bl.market_weights`'s `aums`/`labels` ordering. (For funds-only requests the order is identical, but reading from the frame is the safe contract.)
  - **Delete the now-obsolete test** `test_solve_fn_max_return_cvar_is_rejected` (lines 68-70 of `test_backtest_service.py`) — it asserted the removed rejection. The new `test_solve_fn_max_return_cvar_without_w_mkt_is_rejected` covers the no-w_mkt path.

- [ ] **Delete the obsolete test** — remove this block from `backend/tests/test_backtest_service.py`:

```python
def test_solve_fn_max_return_cvar_is_rejected() -> None:
    with pytest.raises(BacktestError, match="max_return_cvar is not backtestable"):
        _solve_fn_for("max_return_cvar", cap=0.25, min_weight=None)
```

- [ ] **Run the test (expect PASS)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_service.py`
  - Expected: all pass — the new equilibrium tests, `test_solve_fn_bl_utility_is_rejected` (unchanged), and the existing min_cvar/min_vol happy paths.

- [ ] **Commit**:
  - `cd backend && git add app/services/backtest.py tests/test_backtest_service.py && git commit -m "feat(backtest): max_return_cvar walk-forward in equilibrium mode (w_mkt threaded per-fold)"`

### Subtask 3c — route: equilibrium happy path + equities 422

- [ ] **Write failing test** — append to `backend/tests/test_backtest_route.py`. First, note the existing `test_max_return_cvar_rejected_with_422` (lines 108-114) asserts the OLD rejection — REPLACE it with the equilibrium happy path. Delete that old test and add:

```python
async def test_walk_forward_max_return_cvar_equilibrium_happy_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)

    async def fake_w_mkt(session: Any, assets: Any, labels: list[str]) -> np.ndarray:
        return np.full(len(labels), 1.0 / len(labels))

    # The route calls the service; patch _market_weights_for at the service module.
    from app.services import backtest as backtest_service
    monkeypatch.setattr(backtest_service, "_market_weights_for", fake_w_mkt)
    payload = {"assets": [_fund(0), _fund(1), _fund(2)], "objective": "max_return_cvar",
               "cvar_limit": 0.05, "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["params"]["objective"] == "max_return_cvar"
    assert body["params"]["n_splits_computed"] == 5


async def test_walk_forward_max_return_cvar_missing_cvar_limit_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "max_return_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422  # Pydantic model_validator (cvar_limit required)


async def test_walk_forward_max_return_cvar_equities_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Real _market_weights_for (not patched) rejects equities → 422 verbatim.
    _stub_returns(monkeypatch)
    payload = {"assets": [{"kind": "equity", "ticker": "SPY"},
                          {"kind": "equity", "ticker": "AGG"}],
               "objective": "max_return_cvar", "cvar_limit": 0.05,
               "constraints": {"cap": 0.6}}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "equities" in response.json()["detail"]
```

- [ ] **Delete the obsolete route test** — remove this block from `backend/tests/test_backtest_route.py`:

```python
async def test_max_return_cvar_rejected_with_422(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_returns(monkeypatch)
    payload = {"assets": [_fund(0), _fund(1)], "objective": "max_return_cvar"}
    async with _client() as client:
        response = await client.post("/backtest/walk-forward", json=payload)
    assert response.status_code == 422
    assert "is not backtestable" in response.json()["detail"]
```

- [ ] **Run the test (expect FAIL before implement, PASS after — implement is already done in 3b)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_route.py -k max_return_cvar`
  - Expected: with 3a + 3b merged, the equilibrium path works and the equities path 422s, so these PASS. (No production change in this subtask; it is the HTTP-level contract guard. The `test_bl_utility_rejected_with_422` test stays and still passes.)

- [ ] **Run the full backtest + monte-carlo route suite (regression)**:
  - Command: `cd backend && uv run pytest -q tests/test_backtest_route.py tests/test_backtest_service.py`
  - Expected: all pass.

- [ ] **Commit**:
  - `cd backend && git add tests/test_backtest_route.py && git commit -m "test(backtest): max_return_cvar equilibrium route happy path + equities/missing-limit 422"`

---

## Final gate

- [ ] **Run the full quality gate**:
  - Command: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`
  - Expected: ruff clean, mypy clean, all tests pass. If mypy flags the `oos_curve` tuple element type (pandas `Timestamp` vs `dt.date`), normalize with `idx_date.date()` in `assemble_walk_forward_backtest` (Task 1a). If mypy flags the unused `dt` import in `app/schemas/backtest.py`, confirm `fold_boundaries: list[dt.date]` references it (it does).

- [ ] **Final commit (only if the gate produced fixups)**:
  - `cd backend && git add -A && git commit -m "chore(backtest,monte-carlo): satisfy ruff/mypy on onda-1 backend"`

---

## Self-Review

### Spec coverage
- **Backtest OOS equity curve (spec §117-126):** `WalkForwardResult` gains `oos_curve: list[tuple[date, float]]` + `fold_boundaries: list[date]` (Task 1a); `WalkForwardResponse` gains `oos_curve: list[SeriesPoint]` + `fold_boundaries: list[date]` (Task 1b); service maps them (Task 1b); route guard (Task 1c). Tests assert: curve length == Σ fold n_obs; dates strictly increasing; final chained growth factor == Π(1+net_return) per fold (cost_bps=0); first date == first test-fold start; one boundary per fold == first OOS date of each. Existing metrics untouched (`nav` line unchanged). ✓
- **Portfolio MC endpoint (spec §128-138):** `POST /monte-carlo/portfolio` (Task 2c); `PortfolioMonteCarloRequest` (positions of {asset: AssetRefIn, weight}, statistic, n_simulations, horizons, risk_free_rate, seed, window_days) + `PortfolioMonteCarloResponse` reusing `ConfidenceBar` + distribution fields, params with `n_assets` (Task 2a); `run_portfolio_monte_carlo` converts positions→AssetRef via `_to_data_ref`, `load_aligned_returns`→frame, label-aligned weight vector (`fund:{id}`/`equity:{ticker}`), `frame @ w`, new pure `assemble_portfolio_monte_carlo` (Task 2b). `/projection` and `block_bootstrap_monte_carlo` untouched. Rebalancing assumption documented in request/response/service docstrings. Tests: synthetic series == frame @ w; misaligned weights raise; insufficient common history → 422; confidence_bars well-formed. ✓
- **Walk-forward `max_return_cvar` (spec §60-62; onda-0 §30):** rejection removed; `w_mkt` computed once via `_market_weights_for` and threaded into a `solve_equilibrium` closure computing `π = δ·Σ_train·w_mkt` + `solve_max_return_cvar_capped` (Task 3b); `bl_utility` still rejected; request gains `cvar_limit` (required) (Task 3a). Methodological choice documented in the closure docstring. Tests: equilibrium folds returned; equities fail loud; bl_utility still rejected; missing cvar_limit rejected. ✓

### Fixed-contract field-name check (sibling frontend plan depends on these EXACT names)
- `POST /monte-carlo/portfolio` — route path exactly as specified. ✓
- `WalkForwardResponse.oos_curve` — `list[SeriesPoint]` where `SeriesPoint = tuple[dt.date, float]` (renders as `[date, number]`); `WalkForwardResponse.fold_boundaries` — `list[dt.date]`. ✓
- `PortfolioMonteCarloResponse` exposes: `confidence_bars` (reuses the single-instrument `ConfidenceBar`), `percentiles`, `historical_percentile_rank`, `degraded`, `degraded_reason`, `params.n_assets`. Field set asserted in `test_portfolio_happy_path_shape` to be byte-identical to the single-instrument response except `params`. ✓

### Type consistency
- `SeriesPoint` sourced from `app.schemas.analysis` (the canonical alias) and re-exported from `app.schemas.backtest` via `__all__` so tests/service import it from one place. NOT redefined. ✓
- `oos_curve` analytics type `list[tuple[dt.date, float]]` ↔ schema `list[SeriesPoint]` (= same tuple): identical. The `dt` import added to both `app/analytics/backtest.py` and `app/schemas/backtest.py`. ✓
- `Statistic` literal reused from `app.schemas.monte_carlo` for the portfolio request (no second definition). `ConfidenceBar` reused (no second definition). ✓
- `_solve_fn_for` signature extended with keyword-only `w_mkt`/`cvar_limit`/`delta`; existing call sites in tests that pass only positional args still type-check (the new params default to None). ✓

### Placeholder / completeness scan
- No `...`, no `TODO`, no `pass`-stub: every code step shows the full function/edit. ✓
- Every TDD task has: failing test (full code) → run command with expected failure → full implementation → run command with expected pass → exact `git` commit command. ✓
- Obsolete tests explicitly deleted (not silently left): `test_solve_fn_max_return_cvar_is_rejected` (service) and `test_max_return_cvar_rejected_with_422` (route). ✓
- Routers: `/monte-carlo/portfolio` added to the EXISTING `monte_carlo` router (already registered in `main.py`); no `main.py` change. ✓

### Open question (resolved in-plan, flagged for the reviewer)
The task brief says onda 0 "added equity market-cap support; reuse it" and that `_market_weights_for` post-onda-0 supports equities. **In this branch, onda 0 has NOT landed** (no `load_equity_market_cap`, no `resolve_cvar_limit` ladder, `_market_weights_for` still rejects equities). The plan therefore:
1. uses `_market_weights_for` AS-IS (funds-only AUM) — for funds it works today; for equities it fails loud, which is exactly the "equities-without-market-cap path fails loud" test the task requires; and
2. carries an explicit `cvar_limit` on `WalkForwardRequest` (no mandate→cvar_limit ladder exists to pre-fill it) with δ fixed at `bl.DEFAULT_DELTA`.
If onda 0 lands first (adding equity market caps to `_market_weights_for`), the equities-fail-loud test would need to flip to a happy path — but until then the plan is internally consistent and the contracts the frontend depends on are unaffected (they live in tasks 1 and 2).
