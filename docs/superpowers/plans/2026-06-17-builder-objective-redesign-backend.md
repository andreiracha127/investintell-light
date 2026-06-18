# Builder objective redesign — backend (onda 0) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `max_return_cvar` (maximize return subject to a user CVaR ceiling) the usable primary objective without requiring views — by falling back to the Black-Litterman equilibrium return — and support equities in that path via market cap, exposing the effective (regime-adjusted) CVaR ceiling in the response.

**Architecture:** Three surgical backend changes in the optimizer service layer. The equilibrium return `π = δ·Σ·w_mkt` is already computed for `max_return_cvar` (because `needs_bl` includes it); we just use it when no posterior exists. `w_mkt` gains equity support through a new market-cap loader mirroring `load_fund_aum`. The regime-adjusted CVaR ceiling, already computed locally, is surfaced on `DiagnosticsOut`.

**Tech Stack:** Python 3.x, FastAPI, Pydantic, SQLAlchemy (async), CVXPY (engine, untouched), pytest (`asyncio_mode = "auto"`).

**Test command:** from repo root, `cd backend && uv run pytest -q <path>` (single test: `... <path>::<test_name>`). Async tests need no decorator.

**Scope note:** This plan is the BACKEND subsystem of onda 0. The frontend (objective default, mandate selector, CVaR-limit input pre-filled by a UI preset ladder, effective-ceiling display) is a separate plan (onda 0b) and begins by regenerating `frontend/src/lib/api/api.d.ts` from the updated OpenAPI contract. The walk-forward acceptance of `max_return_cvar` is deferred to onda 1 (the Backtest tab) per the spec.

**Spec:** `docs/superpowers/specs/2026-06-17-builder-objective-redesign-design.md`

---

### Task 1: Equity market cap → `_market_weights_for` supports mixed baskets

Today `_market_weights_for` rejects equities, so the equilibrium path (and therefore `max_return_cvar`) breaks on any basket containing a stock. Add a market-cap loader and assemble the size vector in asset order (this also fixes a latent ordering assumption — the old code built sizes from `fund_ids` only while passing the full `labels`).

**Files:**
- Modify: `backend/app/optimizer/data.py` (add `load_equity_market_cap`; add one import)
- Modify: `backend/app/services/portfolio_builder.py:173-193` (`_market_weights_for`)
- Test: `backend/tests/test_portfolio_builder_market_weights.py` (create)

- [x] **Step 1: Write the failing test**

Create `backend/tests/test_portfolio_builder_market_weights.py`:

```python
"""Onda 0 — _market_weights_for supports mixed fund+equity baskets via market cap."""

import uuid

import numpy as np
import pytest

from app.optimizer import data as optimizer_data
from app.schemas.builder import EquityRefIn, FundRefIn
from app.services import portfolio_builder as pb

_FID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def test_mixed_basket_uses_aum_and_market_cap(monkeypatch: pytest.MonkeyPatch) -> None:
    assets = [FundRefIn(kind="fund", id=_FID), EquityRefIn(kind="equity", ticker="AAPL")]
    labels = [f"fund:{_FID}", "equity:AAPL"]

    async def fake_aum(session, fund_ids):
        return {_FID: 1_000_000_000.0}

    async def fake_mcap(session, tickers):
        return {"AAPL": 3_000_000_000.0}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_equity_market_cap", fake_mcap)

    w = await pb._market_weights_for(None, assets, labels)  # type: ignore[arg-type]
    # 1B / 4B = 0.25 (fund), 3B / 4B = 0.75 (equity); order matches `assets`.
    assert np.allclose(w, [0.25, 0.75])


async def test_equity_without_market_cap_fails_loud(monkeypatch: pytest.MonkeyPatch) -> None:
    assets = [FundRefIn(kind="fund", id=_FID), EquityRefIn(kind="equity", ticker="ZZZZ")]
    labels = [f"fund:{_FID}", "equity:ZZZZ"]

    async def fake_aum(session, fund_ids):
        return {_FID: 1_000_000_000.0}

    async def fake_mcap(session, tickers):
        return {"ZZZZ": None}

    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_equity_market_cap", fake_mcap)

    with pytest.raises(pb.BuilderError, match="market weights require"):
        await pb._market_weights_for(None, assets, labels)  # type: ignore[arg-type]
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest -q tests/test_portfolio_builder_market_weights.py`
Expected: FAIL — `load_equity_market_cap` does not exist yet (`AttributeError`), and the current `_market_weights_for` raises `BuilderError` on the equity before reaching market_weights.

- [x] **Step 3: Add the `load_equity_market_cap` loader**

In `backend/app/optimizer/data.py`, add the import alongside the existing model imports (the block currently imports `from app.models.eod_price import EodPrice` and `from app.models.fund import ...`):

```python
from app.models.universe import FundamentalsSnapshot
```

Then add this loader near `load_fund_aum` (after line 267):

```python
async def load_equity_market_cap(
    session: AsyncSession, tickers: list[str]
) -> dict[str, float | None]:
    """Market cap per equity ticker = shares_outstanding × latest adj_close.

    ``shares_outstanding`` from ``fundamentals_snapshot`` (one row per ticker);
    price from the most recent ``eod_prices`` row. None where either input is
    missing or non-positive — the caller (``_market_weights_for``) decides
    whether to fail loud. Mirrors ``load_fund_aum``.
    """
    if not tickers:
        return {}
    shares_result = await session.execute(
        select(
            FundamentalsSnapshot.ticker, FundamentalsSnapshot.shares_outstanding
        ).where(FundamentalsSnapshot.ticker.in_(tickers))
    )
    shares = {row[0]: row[1] for row in shares_result.all()}
    price_result = await session.execute(
        select(EodPrice.ticker, EodPrice.adj_close)
        .distinct(EodPrice.ticker)
        .where(EodPrice.ticker.in_(tickers))
        .order_by(EodPrice.ticker, EodPrice.date.desc())
    )
    prices = {row[0]: row[1] for row in price_result.all()}
    out: dict[str, float | None] = {}
    for ticker in tickers:
        s = shares.get(ticker)
        p = prices.get(ticker)
        out[ticker] = (
            float(s) * float(p) if s is not None and s > 0 and p is not None else None
        )
    return out
```

Note: `fundamentals_snapshot.ticker` is the PK (one row per ticker), so no "latest period_end" filter is needed. `eod_prices` uses `DISTINCT ON (ticker) ... ORDER BY ticker, date DESC` (Postgres/TimescaleDB) for the most recent price. The loader is thin I/O and is exercised through the mocked-loader test above (the project's optimizer tests deliberately avoid a live DB — see `conftest.py`).

- [x] **Step 4: Rewrite `_market_weights_for` to support equities**

Replace the body of `_market_weights_for` (`backend/app/services/portfolio_builder.py:173-193`) with:

```python
async def _market_weights_for(
    session: AsyncSession, assets: list[AssetRefIn], labels: list[str]
) -> np.ndarray:
    """w_mkt from real sizes: AUM for funds, market cap for equities.

    Sizes are assembled in the SAME order as ``assets``/``labels`` so the weight
    vector aligns with Sigma. Fail-loud (via ``bl.market_weights``) on any asset
    whose size is unknown/non-positive — funds without AUM and equities without a
    computable market cap (shares_outstanding × latest price).
    """
    fund_ids: list[uuid.UUID] = [ref.id for ref in assets if isinstance(ref, FundRefIn)]
    tickers: list[str] = [ref.ticker for ref in assets if isinstance(ref, EquityRefIn)]
    aum_by_id = await optimizer_data.load_fund_aum(session, fund_ids)
    mcap_by_ticker = await optimizer_data.load_equity_market_cap(session, tickers)
    sizes: list[float | None] = []
    for ref in assets:
        if isinstance(ref, FundRefIn):
            sizes.append(aum_by_id.get(ref.id))
        else:
            sizes.append(mcap_by_ticker.get(ref.ticker))
    try:
        return bl.market_weights(sizes, labels)
    except ValueError as exc:
        raise BuilderError(str(exc)) from exc
```

`bl.market_weights` already fails loud listing every label with a missing/non-positive size, so the equity-without-market-cap case raises a `ValueError` → `BuilderError` with the offending labels.

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_portfolio_builder_market_weights.py`
Expected: PASS (2 tests).

- [x] **Step 6: Commit**

```bash
git add backend/app/optimizer/data.py backend/app/services/portfolio_builder.py backend/tests/test_portfolio_builder_market_weights.py
git commit -m "feat(optimizer): w_mkt supports equities via market cap (shares × price)"
```

---

### Task 2: `max_return_cvar` uses the equilibrium return when there are no views

`mu_equilibrium` is already computed for `max_return_cvar` (line 521, because `needs_bl` includes it). Today the branch (lines 572-578) demands `mu_posterior` and raises without views. Use the equilibrium as the fallback `μ` — both are G5-safe (never the historical mean).

**Files:**
- Modify: `backend/app/services/portfolio_builder.py:572-597` (the `max_return_cvar` branch)
- Test: `backend/tests/test_builder_objective_equilibrium.py` (create)
- Test: `backend/tests/test_optimizer_engine.py` (extend — scale-invariance characterization)

- [x] **Step 1: Write the failing behavior test**

Create `backend/tests/test_builder_objective_equilibrium.py`:

```python
"""Onda 0 — max_return_cvar solves off the BL equilibrium when no views are given."""

import numpy as np
import pandas as pd
import pytest

from app.optimizer import data as optimizer_data
from app.optimizer import engine
from app.schemas.builder import OptimizeRequest
from app.services import portfolio_builder as pb

_IDS = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(1, 4)]


async def test_max_return_cvar_without_views_uses_equilibrium(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(7)

    async def fake_load(session, assets, window_days=None, today=None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, n_obs) for ref in assets}, index=index
        )

    async def fake_aum(session, fund_ids):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_class(session, fund_ids):
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(session, fund_ids):
        return {fid: "Core" for fid in fund_ids}

    captured: dict[str, object] = {}

    def fake_solver(scenarios, *, mu, cvar_limit, cap=None, min_weight=None,
                    bounds=None, alpha=0.95, cvar_tol=1e-4):
        captured["mu"] = mu
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)

    payload = OptimizeRequest(
        assets=[{"kind": "fund", "id": i} for i in _IDS],
        objective="max_return_cvar",
        cvar_limit=0.02,
    )  # NO views
    result = await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]

    mu = np.asarray(captured["mu"])
    assert mu.shape == (3,)
    assert np.isfinite(mu).all()  # equilibrium μ was passed, not None
    assert result.diagnostics.status == "optimal"
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest -q tests/test_builder_objective_equilibrium.py`
Expected: FAIL — `run_optimize` raises `BuilderError("max_return_cvar needs expected returns — provide views ...")` because `mu_posterior is None`.

- [x] **Step 3: Use the equilibrium fallback in the `max_return_cvar` branch**

In `backend/app/services/portfolio_builder.py`, replace the `max_return_cvar` branch (lines 572-597) with:

```python
        elif payload.objective == "max_return_cvar":
            assert payload.cvar_limit is not None  # schema validator guarantees it
            assert mu_equilibrium is not None  # needs_bl computes it for this objective
            # Gate G5-safe μ: the BL posterior when views exist, otherwise the
            # equilibrium return π = δ·Σ·w_mkt. Never the historical mean.
            mu = mu_posterior if mu_posterior is not None else mu_equilibrium
            state = _OVERRIDE_REGIME_STATE
            if state is None and datalake is not None:
                snap = await macro_regime.fetch_credit_regime(datalake)
                state = snap.state if snap is not None else None
            limit = apply_regime_cvar_limit(
                payload.cvar_limit, state, risk_off_factor=DEFAULT_RISK_OFF_CVAR_FACTOR
            )
            weights, status = engine.solve_max_return_cvar_capped(
                scenarios,
                mu=mu,
                cvar_limit=limit,
                cap=cap,
                min_weight=min_weight,
                bounds=cvar_bounds,
            )
```

(The regime-adjusted `limit` and `state` locals are reused by Task 3 to expose the effective ceiling — Task 3 adds the two lines that capture them.)

- [x] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest -q tests/test_builder_objective_equilibrium.py`
Expected: PASS.

- [x] **Step 5: Add the scale-invariance characterization test**

This documents the methodological note that δ does not move the portfolio in `max_return_cvar` (a linear objective's argmax is invariant to positive scaling of μ). Append to `backend/tests/test_optimizer_engine.py`:

```python
def test_max_return_cvar_argmax_invariant_to_mu_scale() -> None:
    """δ scales μ (π = δ·Σ·w_mkt) but the linear objective's argmax is
    scale-invariant — so the mandate's δ does not move a max_return_cvar
    portfolio; only the CVaR ceiling binds."""
    import numpy as np

    from app.optimizer import engine

    rng = np.random.default_rng(3)
    scenarios = rng.normal(0.0005, 0.01, size=(300, 4))
    mu = np.array([0.02, 0.05, 0.03, 0.08])
    w1, s1 = engine.solve_max_return_cvar_capped(scenarios, mu=mu, cvar_limit=0.03, cap=0.6)
    w2, s2 = engine.solve_max_return_cvar_capped(
        scenarios, mu=5.0 * mu, cvar_limit=0.03, cap=0.6
    )
    assert s1 == "optimal" and s2 == "optimal"
    assert np.allclose(w1, w2, atol=1e-4)
```

- [x] **Step 6: Run the characterization test**

Run: `cd backend && uv run pytest -q tests/test_optimizer_engine.py::test_max_return_cvar_argmax_invariant_to_mu_scale`
Expected: PASS immediately (this characterizes existing solver behavior; it is not red-green — it locks the property the design relies on).

- [x] **Step 7: Commit**

```bash
git add backend/app/services/portfolio_builder.py backend/tests/test_builder_objective_equilibrium.py backend/tests/test_optimizer_engine.py
git commit -m "feat(optimizer): max_return_cvar falls back to equilibrium return without views"
```

---

### Task 3: Surface the effective (regime-adjusted) CVaR ceiling in the response

The regime tightening (`× 0.5` on risk_off) is applied silently today. Expose the effective ceiling and the regime state on `DiagnosticsOut` so the UI can show "ceiling 2.0% → effective 1.0% (risk-off)".

**Files:**
- Modify: `backend/app/schemas/builder.py` (`DiagnosticsOut`)
- Modify: `backend/app/services/portfolio_builder.py` (declare two vars; pass them into `DiagnosticsOut`)
- Test: `backend/tests/test_builder_regime_cvar.py` (extend)

- [x] **Step 1: Write the failing test**

Append to `backend/tests/test_builder_regime_cvar.py`:

```python
async def test_run_optimize_exposes_effective_cvar_and_regime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """risk_off halves the ceiling AND the response reports both the effective
    ceiling and the regime state (max_return_cvar, no views)."""
    import numpy as np
    import pandas as pd

    from app.optimizer import data as optimizer_data
    from app.optimizer import engine
    from app.schemas.builder import OptimizeRequest

    n_obs = 500
    index = pd.bdate_range("2024-01-02", periods=n_obs)
    rng = np.random.default_rng(11)
    ids = [f"00000000-0000-0000-0000-00000000000{i}" for i in range(1, 4)]

    async def fake_load(session, assets, window_days=None, today=None):
        return pd.DataFrame(
            {ref.label: rng.normal(0.0004, 0.01, n_obs) for ref in assets}, index=index
        )

    async def fake_aum(session, fund_ids):
        return {fid: 1e9 * (i + 1) for i, fid in enumerate(fund_ids)}

    async def fake_class(session, fund_ids):
        return {fid: "equity" for fid in fund_ids}

    async def fake_strategy(session, fund_ids):
        return {fid: "Core" for fid in fund_ids}

    def fake_solver(scenarios, *, mu, cvar_limit, cap=None, min_weight=None,
                    bounds=None, alpha=0.95, cvar_tol=1e-4):
        w = np.full(scenarios.shape[1], 1.0 / scenarios.shape[1])
        return w, "optimal"

    monkeypatch.setattr(optimizer_data, "load_aligned_returns", fake_load)
    monkeypatch.setattr(optimizer_data, "load_fund_aum", fake_aum)
    monkeypatch.setattr(optimizer_data, "load_fund_asset_class", fake_class)
    monkeypatch.setattr(optimizer_data, "load_fund_strategy_label", fake_strategy)
    monkeypatch.setattr(engine, "solve_max_return_cvar_capped", fake_solver)
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", "risk_off", raising=False)

    payload = OptimizeRequest(
        assets=[{"kind": "fund", "id": i} for i in ids],
        objective="max_return_cvar",
        cvar_limit=0.20,
    )
    result = await pb.run_optimize(session=None, payload=payload)  # type: ignore[arg-type]
    assert result.diagnostics.cvar_limit_effective == pytest.approx(0.10)  # 0.20 × 0.5
    assert result.diagnostics.regime_state == "risk_off"
    monkeypatch.setattr(pb, "_OVERRIDE_REGIME_STATE", None, raising=False)
```

- [x] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest -q tests/test_builder_regime_cvar.py::test_run_optimize_exposes_effective_cvar_and_regime`
Expected: FAIL — `DiagnosticsOut` has no `cvar_limit_effective` / `regime_state` attributes (`AttributeError` or validation error).

- [x] **Step 3: Add the fields to `DiagnosticsOut`**

In `backend/app/schemas/builder.py`, add to the `DiagnosticsOut` class (after the `selection` field):

```python
    # Effective daily CVaR ceiling applied AFTER regime tightening, and the
    # credit-regime state — present only on the max_return_cvar path.
    cvar_limit_effective: float | None = None
    regime_state: str | None = None
```

- [x] **Step 4: Declare, capture, and wire the two vars in `run_optimize`**

In `backend/app/services/portfolio_builder.py`:

(a) add the declarations next to the existing BL-state vars (alongside `mu_equilibrium`/`mu_posterior` around lines 515-518):

```python
    cvar_limit_effective: float | None = None
    regime_state: str | None = None
```

(b) capture them inside the `max_return_cvar` branch, immediately after `limit = apply_regime_cvar_limit(...)`:

```python
            regime_state = state
            cvar_limit_effective = limit
```

(c) pass them to the returned `DiagnosticsOut(...)` (construction at lines ~672-680), after `selection=selection_diag`:

```python
            cvar_limit_effective=cvar_limit_effective,
            regime_state=regime_state,
```

- [x] **Step 5: Run tests to verify they pass**

Run: `cd backend && uv run pytest -q tests/test_builder_regime_cvar.py`
Expected: PASS (all existing tests + the new one).

- [x] **Step 6: Commit**

```bash
git add backend/app/schemas/builder.py backend/app/services/portfolio_builder.py backend/tests/test_builder_regime_cvar.py
git commit -m "feat(builder): expose effective CVaR ceiling + regime state in response"
```

---

### Task 4: Full backend gate

- [ ] **Step 1: Run the full backend quality gate**

Run: `cd backend && uv run ruff check . && uv run mypy app && uv run pytest -q`
Expected: clean ruff, clean mypy, all tests PASS. Fix any regressions before proceeding (the changed files are `data.py`, `portfolio_builder.py`, `builder.py` schema, plus three test files).

- [ ] **Step 2: Commit any gate fixes**

```bash
git add -A
git commit -m "chore(builder): backend gate green for objective redesign (onda 0)"
```

---

## Self-Review

**Spec coverage:**
- Spec objetivo 1 (equilibrium when no views) → Task 2. ✓
- Spec objetivo 3 (equities via market cap) → Task 1. ✓
- Spec "expose effective ceiling + regime" → Task 3. ✓
- Spec objetivo 2 (mandate → cvar_limit ladder): intentionally moved to the frontend plan (onda 0b) as a UI preset ladder; the backend receives the final `cvar_limit`. Noted in the scope note. The mandate→δ mapping (`resolve_delta`) already exists and is untouched; δ does not affect `max_return_cvar` (Task 2, Step 5 test). ✓
- Spec frontend objetivo 4 → separate plan (onda 0b). ✓ (out of scope here, stated)
- Spec walk-forward acceptance → deferred to onda 1. ✓ (stated)

**Placeholder scan:** No TBD/TODO. Every code step shows complete code. The loader's lack of a direct DB test is explained (project pattern: optimizer tests mock loaders; no DB fixture in `conftest.py`).

**Type consistency:** `load_equity_market_cap(session, tickers) -> dict[str, float | None]` is defined in Task 1 and consumed in the rewritten `_market_weights_for` (Task 1). `cvar_limit_effective`/`regime_state` are declared (Task 3 Step 4), assigned in the `max_return_cvar` branch (Task 2 Step 3 / Task 3 Step 4), added to the schema (Task 3 Step 3), and asserted in tests (Task 3 Step 1). The `solve_max_return_cvar_capped` keyword signature in the test fakes matches the real signature (`scenarios, *, mu, cvar_limit, cap, min_weight, bounds, alpha, cvar_tol`). Consistent.

**Cross-task isolation:** Each task is independently gate-green. Task 2 only changes the μ fallback and the solver call (no unused locals). Task 3 adds the schema fields, the two declarations, the in-branch capture, and the response wiring together — so `cvar_limit_effective`/`regime_state` are introduced and consumed within one task. No ordering hazard.
