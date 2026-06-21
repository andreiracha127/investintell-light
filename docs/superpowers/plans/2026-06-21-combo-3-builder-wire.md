# COMBO Sprint 3 — Optimizer/builder wire (`combo` objective + gate-driven scaling) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new builder objective `"combo"` that (1) reads the live gate + computes the growth×inflation quadrant, (2) calls `taa_bands.combined_regime` + `effective_class_bands` to get per-class `(min,max)`, (3) converts them to `engine.BlockBudget` rows, (4) solves the min-CVaR objective inside that envelope, (5) routes the SLOWDOWN goldfix haven (fixed target, bypassing class bands), and (6) applies the vol/beta graduated cap vectors; PLUS switching the existing CVaR-scaling regime read from credit-only → the gate. **Done when:** `objective="combo"` end-to-end honors the gate-driven equity band, the SLOWDOWN path returns the goldfix tilt, the scaling read uses the gate, and the builder suite is green.

**Architecture:** The engine ALREADY honors `blocks=`/`linear=`/`BoundsBundle` across every solver (verified: `BlockBudget` `engine.py:234`, `LinearConstraint` `engine.py:249`, `BoundsBundle` `engine.py:345`; `solve_min_cvar` `engine.py:820` and `solve_max_return_cvar_capped` `engine.py:979` both take `bounds=BoundsBundle`). So `"combo"` needs NO new engine primitive — it reuses `_resolve_block_budgets`'s class→index mapping (`portfolio_builder.py:233-283`) to turn regime bands into `BlockBudget` rows, builds a `BoundsBundle(cap_vec=graduated_caps, min_vec, blocks=regime_blocks)`, and dispatches to **`engine.solve_min_cvar`** (decision B — minimize CVaR inside the envelope; verified to honor `bounds`/`blocks`/`linear`). The `"combo"` branch sits alongside the existing dispatch (`portfolio_builder.py:683-757`). The quadrant is READ from `fetch_gate_regime` (decision A — the Sprint-1 worker materializes it; NO backend proxy computation). The CVaR-scaling read (`portfolio_builder.py:701-704`) switches `fetch_credit_regime` → `fetch_gate_regime`.

**Tech Stack:** cvxpy/CLARABEL, SQLAlchemy async, Pydantic v2, FastAPI, numpy, pytest. Repo `E:/investintell-light/backend`.

## Repo & base branch

- Runs in `E:/investintell-light/backend` on branch `feat/combo-regime-allocator`, based on `feat/bl-amplo-constraints-drift` (depends on bl-amplo's `BlockBudget`/`LinearConstraint`/`BoundsBundle`/overlap `linear`, which `main` lacks). Depends on Sprint 2 (`taa_bands`) being committed on this branch.
- **The implementer must NOT create/switch branches** (shared working tree). Commit on the current branch.

## Architecture (components touched)

- **MODIFY** `app/schemas/builder.py` — add `"combo"` to `Objective`; add `quadrant`/`regime`/`bands` to `DiagnosticsOut` (the response already carries `regime_state`/`cvar_limit_effective`, so extend that diagnostics object — do NOT change `OptimizeResponse`'s top-level shape).
- **MODIFY** `app/services/portfolio_builder.py` — new `_resolve_regime_block_budgets(...)` (reuses `_resolve_block_budgets`'s class→index logic); the `combo` dispatch branch; switch the CVaR-scaling read to the gate.
- **CONSUMES (Sprint 2)** `taa_bands.{fetch_gate_regime, combined_regime, effective_class_bands, goldfix_target, vol_graduated_caps, beta_graduated_caps}`. The quadrant comes from `fetch_gate_regime(...).quadrant` (worker-materialized — decision A); `macro_quadrant_from_proxies` is NOT consumed on the runtime path (no backend TIP/IEF).
- **Engine UNCHANGED** — only consumed.

## Global Constraints

- **Engine is NOT modified** — `BlockBudget`/`BoundsBundle`/`linear` already exist. Only consume them.
- **`combo` = MINIMIZE CVaR INSIDE regime bands (decision B, spec §9).** Base CVaR solver: **`engine.solve_min_cvar`** (`engine.py:820`, takes `bounds=BoundsBundle` + `blocks` + `linear` — verified; the builder already calls it at `portfolio_builder.py:227/732/745`). This is the DECIDED inner objective — the Lean-validated harness MINIMIZES CVaR inside the regime envelope (`build_ru_cvar_objective`, `main.py:207-221`); `max_return_cvar` is a DIFFERENT optimization (maximize return s.t. a CVaR ceiling) and would NOT reproduce the validated results. Do NOT use `solve_max_return_cvar_capped` for combo.
- **Bands come from the REGIME, not the payload.** When `objective=="combo"`, IGNORE `constraints.block_budgets` from the payload (the bands are derived) — documented. Other constraints still apply: `cap` (scalar) and `overlap_cap` (via the bl-amplo `linear` path) continue to ride along.
- **`multi_asset` gets NO BlockBudget** (decision O5 — unbounded, documented); classes absent from the final universe are skipped (same behavior as `_resolve_block_budgets`).
- **O4 DECISION:** `"combo"` is an AD-HOC builder objective — NO per-portfolio persistence (no `portfolio_constraints` mode). YAGNI; persistence deferred.
- **CVaR-scaling read switches credit-only → gate** (`portfolio_builder.py:701-704`): the COMBO wire (and the `max_return_cvar` path that shares this block) reads `fetch_gate_regime(datalake).state` instead of `fetch_credit_regime`. `regime_cvar_multiplier`/`apply_regime_cvar_limit` are UNCHANGED (they compare `state == "risk_off"`, compatible with the gate's lowercase `state`). The `_OVERRIDE_REGIME_STATE` test hook (`portfolio_builder.py:65`, used at `:701`) keeps working.
- **State convention:** the gate's `state` is lowercase `'risk_on'/'risk_off'` (verified). `combined_regime` already upper-normalizes internally.
- **Works in BOTH modes:** explicit-list and broad-universe (broad applies bands over the selected representatives — Stage-1 clustering `portfolio_builder.py:441-488`, Stage-2 covariance `:524-577`). The catalog expansion (~4.5k→~8.6k investable) gives broad ~2× candidates per class, making bands easier to satisfy.
- **TDD.** **VERIFICATION COMMANDS (confirmed):** `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -v`; full builder `... -m pytest tests/ -k builder -q`; lint `ruff check app/`; types `mypy app/`. Regime test seam: `_OVERRIDE_REGIME_STATE` (`portfolio_builder.py:65`).

---

### Task 1: `combo` objective in the schema + response diagnostics

**Files:**
- Modify: `app/schemas/builder.py` (`Objective` Literal `builder.py:65-68`; `DiagnosticsOut` `builder.py:295-307`)
- Test: `tests/test_builder_combo_schema.py`

**Interfaces:**
- Produces:
  - `Objective` gains `"combo"`: `Literal["equal_weight","min_vol","erc","max_diversification","min_cvar","bl_utility","max_return_cvar","combo"]`.
  - `DiagnosticsOut` gains (all optional, present only on the combo path): `quadrant: str | None = None`, `combined_regime: str | None = None`, `class_bands: dict[str, list[float]] | None = None` (each value `[min, max]`), `haven_tilt: dict[str, float] | None = None` (the goldfix target when SLOWDOWN, else None). Reuse the existing `regime_state`/`cvar_limit_effective` for the gate state + scaled limit.
  - `OptimizeRequest` accepts `objective="combo"` with no new required field (bands derive from the regime).

- [ ] **Step 1: Write the failing test** in `tests/test_builder_combo_schema.py`:

```python
from app.schemas.builder import OptimizeRequest, DiagnosticsOut


def test_combo_is_valid_objective():
    req = OptimizeRequest.model_validate({
        "assets": [{"kind": "equity", "id": 1}, {"kind": "equity", "id": 2}],
        "objective": "combo",
    })
    assert req.objective == "combo"


def test_diagnostics_has_combo_fields():
    d = DiagnosticsOut(n_obs=10, status="optimal", quadrant="SLOWDOWN",
                       combined_regime="STAG_GOLD",
                       class_bands={"equity": [0.26, 0.50]},
                       haven_tilt={"GLD": 0.3, "BIL": 0.3})
    assert d.quadrant == "SLOWDOWN"
    assert d.class_bands["equity"] == [0.26, 0.50]
```

(Align the `assets` shape to the real `AssetRefIn` discriminated union — verified `AssetRefIn = FundRefIn | EquityRefIn` with `Field(discriminator="kind")`; `EquityRefIn` uses `kind="equity"`. Read `builder.py` to confirm the id field name.)

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo_schema.py -v`
Expected: FAIL (`combo` not permitted; `DiagnosticsOut` has no `quadrant`).

- [ ] **Step 3: Implement** — add `"combo"` to `Objective`; add the optional fields to `DiagnosticsOut`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo_schema.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/builder.py backend/tests/test_builder_combo_schema.py
git commit -m "Add combo objective + combo diagnostics fields to builder schema"
```

---

### Task 2: `_resolve_regime_block_budgets` (regime bands → BlockBudgets)

**Files:**
- Modify: `app/services/portfolio_builder.py` (new private function near `_resolve_block_budgets`, `portfolio_builder.py:233-283`)
- Test: `tests/test_builder_combo.py`

**Interfaces:**
- Consumes: `taa_bands.fetch_gate_regime` (returns gate state AND the worker-materialized `quadrant`/`growth_score`/`inflation_score` — decision A), `taa_bands.combined_regime`, `taa_bands.effective_class_bands`; the class→column-index logic of `_resolve_block_budgets` (verified: it resolves `asset_class` per asset via `class_by_id` and fails loud for stocks without a class — `portfolio_builder.py:247-266`); `engine.BlockBudget`. **Does NOT consume `macro_quadrant_from_proxies` (decision A — no backend TIP/IEF; the quadrant is read, not computed).**
- Produces:
  - `async def _resolve_regime_block_budgets(session, datalake, assets, labels) -> tuple[list[engine.BlockBudget], str, str | None]` — returns `(regime_blocks, combined_regime_label, quadrant_or_none)`.
    1. `gate = await taa_bands.fetch_gate_regime(datalake)` (None-safe; `gate_state = gate.state if gate else None`).
    2. **`quadrant = gate.quadrant if gate else None`** — READ the worker-materialized quadrant (decision A); NO proxy computation. (`quadrant` is the lowercase value from `regime_gate_daily`; `combined_regime` upper-normalizes it.)
    3. `regime = taa_bands.combined_regime(gate_state, quadrant)`.
    4. if `regime == "STAG_GOLD"` → return `([], regime, quadrant)` (the goldfix haven bypasses class bands — Task 3 routes it).
    5. else `bands = effective_class_bands(regime)[0]`; for each class in `{equity, fixed_income, alternatives, cash}` PRESENT in the universe, build `BlockBudget(indices=<class cols>, lo=band_lo, hi=band_hi)`; skip `multi_asset` and absent classes. Return `(blocks, regime, quadrant)`.
  - **Reuse the class→index resolution** that `_resolve_block_budgets` already performs (do NOT re-implement `asset_class` discovery — extract a shared helper if needed, e.g. `_class_columns(session, assets, labels) -> dict[str, list[int]]`).

- [ ] **Step 1: Write the failing test** (monkeypatch the readers; synthetic class map — mirror `tests/test_builder_block_budgets.py` setup):

```python
import pytest
from app.services import portfolio_builder as pb
from app.services import taa_bands as tb


def _async(v):
    async def _f(*a, **k):
        return v
    return _f


@pytest.mark.asyncio
async def test_combo_builds_riskon_blocks(monkeypatch, builder_universe):
    # builder_universe: a fixture giving (session, datalake, assets, labels) with
    # known asset_class per asset (reuse the block-budget test fixture).
    session, datalake, assets, labels = builder_universe
    monkeypatch.setattr(tb, "fetch_gate_regime",
                        _async(tb.GateRegimeSnapshot(
                            as_of=None, state="risk_on", vote_count=0,
                            trend_vote=False, credit_vote=False,
                            drawdown_vote=False, dwell_days=99, last_flip=None,
                            growth_score=None, inflation_score=None, quadrant=None)))
    blocks, regime, quad = await pb._resolve_regime_block_budgets(
        session, datalake, assets, labels)   # quadrant None (gate snapshot) => RISK_ON
    assert regime == "RISK_ON"
    eq = next(b for b in blocks if 0 in b.indices)   # asset 0 is equity in the fixture
    assert abs(eq.lo - 0.40) < 1e-9 and abs(eq.hi - 0.64) < 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -k regime_blocks -v`
Expected: FAIL (`_resolve_regime_block_budgets` undefined).

- [ ] **Step 3: Implement** `_resolve_regime_block_budgets` reusing the class→index mapping; handle the `STAG_GOLD` early return.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -k regime_blocks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/portfolio_builder.py backend/tests/test_builder_combo.py
git commit -m "Derive regime BlockBudgets from taa_bands in builder"
```

---

### Task 3: `combo` dispatch — CVaR within bands + goldfix routing + graduated caps

**Files:**
- Modify: `app/services/portfolio_builder.py` (`run_optimize`, the dispatch chain `portfolio_builder.py:683-757`)
- Test: `tests/test_builder_combo.py`

**Interfaces:**
- Consumes: `_resolve_regime_block_budgets` (Task 2); `taa_bands.goldfix_target`, `taa_bands.vol_graduated_caps`, `taa_bands.beta_graduated_caps`; **`engine.solve_min_cvar`** (`engine.py:820`, takes `bounds=BoundsBundle` + `blocks` + `linear` — the DECIDED inner objective, decision B; NOT `solve_max_return_cvar_capped`); `engine.BoundsBundle` (`cap_vec`, `min_vec`, `blocks`). The CVaR-scaling read still uses `apply_regime_cvar_limit`/`regime_cvar_multiplier` (`portfolio_builder.py:109-123`) for the gate-driven CVaR *scaling*, but the combo solve itself MINIMIZES CVaR.
- Produces: in `run_optimize`, a `elif payload.objective == "combo":` branch that:
  1. calls `_resolve_regime_block_budgets(...)` → `(regime_blocks, regime, quadrant)`;
  2. **goldfix route:** if `regime == "STAG_GOLD"`, set `weights` to `taa_bands.goldfix_target(live_labels)` mapped onto the universe order (assets not in the target get 0), set `status="goldfix"`, populate `haven_tilt`, and SKIP the solver (the whitelist IS the defense — port `_haven_weights` goldfix branch, `main.py:959-972`);
  3. **band route (else) — MINIMIZE CVaR inside the envelope (decision B):** build `graduated_caps = vol_graduated_caps(cap, asset_return_cols, spy_desc)`; if `regime == "RISK_OFF"` further apply `beta_graduated_caps(graduated_caps, betas_in_order)`; build `cvar_bounds_combo = engine.BoundsBundle(cap_vec=graduated_caps, min_vec=(np.full(n,min_weight) if min_weight else None), blocks=regime_blocks)`; call `engine.solve_min_cvar(scenarios, cap=cap, min_weight=min_weight, bounds=cvar_bounds_combo, linear=linear)`. (No `cvar_limit` ceiling — `solve_min_cvar` MINIMIZES CVaR; the regime bands + graduated caps ARE the construction. The gate-driven CVaR *scaling* `limit` is still computed for the diagnostics/scaling read in Task 4, but the combo solve does not take a ceiling.) Optionally pass `mu=mu_equilibrium`/`ret_floor` ONLY if the owner later wants an equilibrium return floor — NOT in v1 (the validated harness is pure min-CVaR within bands).
  4. populate `DiagnosticsOut`: `combined_regime=regime`, `quadrant=quadrant`, `class_bands={cls: [lo,hi] for blocks}`, `regime_state=gate_state`, `cvar_limit_effective=limit` (the scaled limit from the gate read, for transparency), and `haven_tilt` when goldfix.
- **No `cvar_limit` ceiling for combo (decision B):** `solve_min_cvar` minimizes CVaR, so combo does NOT consume a payload `cvar_limit` as a ceiling (unlike `max_return_cvar`). `cvar_limit_effective` is still surfaced in diagnostics from the gate-driven scaling read (Task 4) for auditability, but it does not gate the solve. No `DEFAULT_COMBO_CVAR_LIMIT` constant is needed.

**Behavior:** combo IGNORES `constraints.block_budgets` from the payload (bands derive from the regime) — documented. Works in broad mode (representatives selected). **The quadrant is READ from the gate snapshot (decision A — worker-materialized), NOT computed from proxies.** Only `spy_desc` (SPY closes) is still needed — for the `vol_graduated_caps`/`beta_graduated_caps` market-stress overlay; when `spy_desc` is unavailable, `vol_graduated_caps` returns the flat `cap` (its no-stress branch) so the path degrades safely. When the worker has not materialized the quadrant yet, `gate.quadrant is None` → gate-only regime (RISK_ON/RISK_OFF) and the SLOWDOWN→goldfix route is simply inactive until the quadrant is populated.

- [ ] **Step 1: Write the failing end-to-end test** (via the optimize route; force regime through the gate seam):

```python
@pytest.mark.asyncio
async def test_combo_respects_riskoff_equity_band(monkeypatch, client, combo_universe):
    # combo_universe: 2 equity stocks + 1 fixed_income fund with NAV (reuse the
    # broad/explicit builder fixtures); force the gate to risk_off.
    from app.services import taa_bands as tb
    async def _gate(*a, **k):
        return tb.GateRegimeSnapshot(as_of=None, state="risk_off", vote_count=2,
                                     trend_vote=True, credit_vote=True,
                                     drawdown_vote=False, dwell_days=30, last_flip=None,
                                     growth_score=None, inflation_score=None,
                                     quadrant=None)
    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    resp = await client.post("/builder/optimize",
                             json={"assets": combo_universe.assets, "objective": "combo"})
    body = resp.json()
    assert body["diagnostics"]["combined_regime"] == "RISK_OFF"
    eq_sum = sum(w["weight"] for w in body["weights"] if combo_universe.is_equity(w))
    # RISK_OFF equity band: center .38, hw .08*1.5=.12 -> [0.26, 0.50]
    assert eq_sum <= 0.50 + 1e-6
    assert eq_sum >= 0.26 - 1e-6
```

Add a second test forcing SLOWDOWN by monkeypatching `fetch_gate_regime` to return a snapshot with `state="risk_on"` and `quadrant="slowdown"` (decision A — the quadrant comes from the gate snapshot, lowercase as the worker materializes it; `combined_regime` normalizes it to SLOWDOWN → STAG_GOLD). Assert the result is the goldfix tilt (e.g. GLD present, equity stocks at 0, `diagnostics.haven_tilt` populated, `diagnostics.combined_regime == "STAG_GOLD"`).

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -k "riskoff or slowdown" -v`
Expected: FAIL (no `combo` branch; `combined_regime` KeyError).

- [ ] **Step 3: Implement** the `combo` branch (goldfix early-return + band route + graduated caps + diagnostics). Place it in the elif-chain after `max_return_cvar` and before the `else`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py -v` and then `... -m pytest tests/ -k builder -q` (no regression).
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/portfolio_builder.py backend/tests/test_builder_combo.py
git commit -m "Wire combo objective: CVaR within regime bands + goldfix + graduated caps"
```

---

### Task 4: Switch CVaR-scaling regime read credit-only → gate

**Files:**
- Modify: `app/services/portfolio_builder.py` (`portfolio_builder.py:701-704` — the regime read that scales CVaR)
- Test: `tests/test_builder_regime_scaling.py` (new), or extend the existing scaling test

**Interfaces:**
- Consumes: `taa_bands.fetch_gate_regime` (instead of `macro_regime.fetch_credit_regime`).
- Produces: the CVaR-scaling read (used by `max_return_cvar` AND `combo`) reads `(await taa_bands.fetch_gate_regime(datalake)).state` rather than `fetch_credit_regime`. `regime_cvar_multiplier`/`apply_regime_cvar_limit` are unchanged. Keep `_OVERRIDE_REGIME_STATE` working (it short-circuits before the DB read).

**Required investigation (implementer):** confirm `fetch_gate_regime` returns `state` in the same lowercase convention (`"risk_off"`) that `regime_cvar_multiplier` expects (`portfolio_builder.py:116`). It does (Sprint 2 Task 7 + the worker DDL CHECK). No normalization needed.

- [ ] **Step 1: Write the failing test** in `tests/test_builder_regime_scaling.py`:

```python
import pytest
from app.services import portfolio_builder as pb
from app.services import taa_bands as tb


@pytest.mark.asyncio
async def test_cvar_scaling_uses_gate_risk_off(monkeypatch, max_return_cvar_universe, client):
    async def _gate(*a, **k):
        return tb.GateRegimeSnapshot(as_of=None, state="risk_off", vote_count=2,
                                     trend_vote=True, credit_vote=True,
                                     drawdown_vote=False, dwell_days=30, last_flip=None,
                                     growth_score=None, inflation_score=None,
                                     quadrant=None)
    monkeypatch.setattr(tb, "fetch_gate_regime", _gate)
    resp = await client.post("/builder/optimize", json={
        "assets": max_return_cvar_universe.assets,
        "objective": "max_return_cvar", "cvar_limit": 0.02})
    diag = resp.json()["diagnostics"]
    assert diag["regime_state"] == "risk_off"
    # risk_off scales the effective cvar limit by DEFAULT_RISK_OFF_CVAR_FACTOR (<1)
    assert diag["cvar_limit_effective"] < 0.02
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_regime_scaling.py -v`
Expected: FAIL (read still calls `fetch_credit_regime`; monkeypatching `fetch_gate_regime` has no effect yet).

- [ ] **Step 3: Implement** the swap: replace `snap = await macro_regime.fetch_credit_regime(datalake)` with `snap = await taa_bands.fetch_gate_regime(datalake)` at `portfolio_builder.py:703` (import `taa_bands` if not already). Adjust any existing scaling test that monkeypatched `fetch_credit_regime` to target `fetch_gate_regime`.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_regime_scaling.py -v` and `... -m pytest tests/ -k "builder or cvar or regime" -q`.
Expected: PASS (no regression).

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/portfolio_builder.py backend/tests/test_builder_regime_scaling.py
git commit -m "Switch CVaR-scaling regime read from credit-only to the live gate"
```

---

### Task 5: Verification gate

- [ ] **Step 1:** `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_builder_combo.py tests/test_builder_combo_schema.py tests/test_builder_regime_scaling.py -v` → green.
- [ ] **Step 2:** Builder suite `... -m pytest tests/ -k builder -q` → green; full `... -m pytest -q` → green (modulo documented pre-existing failures).
- [ ] **Step 3:** `ruff check app/` and `mypy app/` clean on `portfolio_builder.py` + `schemas/builder.py`.
- [ ] **Step 4:** Commit any gate fixups.

## Verification gate (the green bar)

- `.venv/Scripts/python -m pytest tests/test_builder_combo.py tests/test_builder_combo_schema.py tests/test_builder_regime_scaling.py -v` green.
- `.venv/Scripts/python -m pytest tests/ -k builder -q` green; full `-q` green (modulo documented pre-existing).
- `ruff check app/` + `mypy app/` clean on the touched files.

## Self-Review (assumptions, risks, spec gaps)

**Coverage of spec §3.3 / §7.3:**
- `"combo"` objective in schema → Task 1.
- regime bands → BlockBudgets (reuse of `_resolve_block_budgets` mapping + `BlockBudget`) → Task 2.
- combo dispatch: CVaR inside bands + goldfix routing + vol/beta caps + diagnostics → Task 3.
- switch CVaR-scaling read credit-only → gate → Task 4.
- `multi_asset` no band (O5), payload `block_budgets` ignored in combo, broad mode covered → Global Constraints / Task 3.

**Assumptions.**
- `DiagnosticsOut` (not `OptimizeResponse`) is the right place for `quadrant`/`combined_regime`/`class_bands`/`haven_tilt` — VERIFIED it already carries `regime_state`/`cvar_limit_effective`, so this is consistent.
- `BoundsBundle` is the carrier for both the regime blocks (`blocks=`) and the graduated per-asset caps (`cap_vec=`) — VERIFIED `cap_vec`/`min_vec`/`blocks` are the 3 `BoundsBundle` fields. The overlap `linear` constraint (bl-amplo) is a SEPARATE solver kwarg already threaded as `linear=` — combo passes it through unchanged.
- `_OVERRIDE_REGIME_STATE` overrides the gate state in tests; the quadrant now rides on the gate snapshot (decision A), so tests force SLOWDOWN by monkeypatching `fetch_gate_regime` to return a snapshot with `quadrant="slowdown"` — no separate quadrant seam needed.

**Risks / what could go wrong.**
- **Quadrant source RESOLVED (decision A); only the SPY overlay series remains.** The quadrant no longer needs proxy series in `run_optimize` — it is READ from the gate snapshot (`gate.quadrant`, worker-materialized). The only remaining proxy is **SPY closes** for the `vol_graduated_caps`/`beta_graduated_caps` market-stress overlay; SPY is in `eod_prices` (verified) so the builder can load it. When SPY closes are unavailable the overlay degrades to the flat `cap` (no-stress branch). This is now the full validated config whenever the worker has materialized the quadrant (no remaining TIP/IEF dependency in the backend).
- **goldfix universe coverage:** `goldfix_target` keeps only names present in the universe. If the user's explicit universe contains none of GLD/VOOV/QAI/GCC/BIL, the haven falls back to `{BIL:1.0}` or `None`. In broad mode the expanded catalog should contain them; in explicit mode the UI must offer them. Documented; not blocking.
- **mypy on the new branch:** the combo branch adds dict/None unions; run `mypy app/` and annotate to satisfy `disallow_untyped_defs`.

**Spec gaps / ambiguities / errors found (bias-check payoff).**
- **RESOLVED (decision A, spec §9) — the quadrant source.** The former gap (SPY/TIP/IEF proxy source for the quadrant inside `run_optimize`) is settled: option (a) was chosen — the `regime_gate` worker fetches SPY/HYG/IEF/TIP and materializes the quadrant into `regime_gate_daily`, and `run_optimize` READS it via `fetch_gate_regime` (no backend TIP/IEF — verified not in `eod_prices`). Step (1) "read the gate + quadrant" is now a single DB read. The only remaining proxy series is SPY closes for the vol/beta overlay (in `eod_prices`). This restores the SLOWDOWN→goldfix route (instead of the gate-only degrade), which is the model's headline DD result.
- **RESOLVED (decision B, spec §9) — base CVaR solver for combo is `min_cvar`.** §3.3 step (4) says "solve the min-CVaR objective" and the Lean-validated harness MINIMIZES CVaR inside the regime envelope (`build_ru_cvar_objective`, `main.py:207-221`). This plan now calls `engine.solve_min_cvar` (verified at `engine.py:820` to honor `bounds`/`blocks`/`linear`); the earlier `max_return_cvar` default and the "flagged for owner" ambiguity are REMOVED. `max_return_cvar` is a different optimization (return-subject-to-CVaR-ceiling) and would not reproduce the validated results.
- **CLARIFICATION (decision B) — combo takes NO `cvar_limit` ceiling.** Because the combo inner objective is `solve_min_cvar` (MINIMIZE CVaR), combo does NOT consume a payload `cvar_limit` as a ceiling and needs NO `DEFAULT_COMBO_CVAR_LIMIT` constant. The gate-driven `cvar_limit_effective` is still computed (from `apply_regime_cvar_limit` / `DEFAULT_RISK_OFF_CVAR_FACTOR`) and surfaced in diagnostics for transparency, but it does not gate the combo solve. (The separate `max_return_cvar` path keeps using its payload `cvar_limit` ceiling — unchanged.)
- **MINOR — line drift.** The dispatch elif-chain verified at `683/695/723/744` (close to the spec's `683/695/723/744`); the CVaR-scaling read verified at `701-709` (spec said `:701`/`:703`). Use the verified anchors.
