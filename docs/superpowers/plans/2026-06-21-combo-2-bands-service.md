# COMBO Sprint 2 — Backend `taa_bands` service (regime → bands + quadrant + goldfix + overlays) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A pure backend module `app/services/taa_bands.py` that ports the validated band math from `lean-research/TaaCvarSuite/main.py` — `DEFAULT_TAA_BANDS` (incl. STAGFLATION), `compute_effective_band`, `smooth_regime_centers`, `_effective_class_bands` (hw_scale=1.5 + IPS clamp), `_combined_regime` (gate + quadrant overlay, SLOWDOWN→goldfix route), the goldfix SLOWDOWN haven target, and the vol/beta graduated cap vectors — plus a `regime_gate_daily` reader that consumes Sprint 1's gate AND the worker-materialized growth/inflation/quadrant. **Decision A (spec §9):** the backend NO LONGER computes the quadrant from TIP/IEF proxies (the backend lacks TIP/IEF — verified not in `eod_prices`); the `regime_gate` worker materializes `growth_score`/`inflation_score`/`quadrant` into `regime_gate_daily`, and this service READS them. The pure `macro_quadrant_from_proxies` classifier is still ported here (parity with the worker + unit-testable), but it is NOT on the backend's runtime path. **Done when:** every ported function has a green unit test transcribing the reference's exact numbers, and `fetch_gate_regime` reads the latest gate state + quadrant from the data-lake.

**Architecture:** A single pure module (math + dataclasses only — NO cvxpy/engine dependency) returns per-class `(min, max)` bands keyed by the product vocabulary, plus the goldfix target dict and the graduated cap vectors. The gate (Sprint 1) REPLACES the frozen composite as the stress gate that drives the bands; the quadrant is READ from `regime_gate_daily` (materialized by the Sprint-1 worker — decision A, supersedes O2), NOT computed in the backend. `combined_regime` consumes the read quadrant (gate-stress dominates; else quadrant → bands/haven incl. SLOWDOWN→goldfix). The `_macro_quadrant` math lives in the WORKER (Sprint 1), not the backend. A new reader mirrors `macro_regime.fetch_composite_regime` to read `regime_gate_daily` and now returns growth/inflation/quadrant alongside the gate state. This sprint produces the building blocks; Sprint 3 wires them into the optimizer.

**Tech Stack:** Python 3.12, SQLAlchemy async (data-lake session), Pydantic v2 / dataclasses, numpy, pytest (`asyncio_mode = "auto"`). Repo `E:/investintell-light/backend`.

## Repo & base branch

- Runs in `E:/investintell-light/backend` on branch `feat/combo-regime-allocator`, based on `feat/bl-amplo-constraints-drift` (the COMBO work builds on bl-amplo's `BlockBudget`/`LinearConstraint`/`BoundsBundle`/`portfolio_constraints`, which `main` does NOT have). Depends on Sprint 1 (`regime_gate_daily` table) being deployed for the reader's integration path, but ALL unit tests here use fakes and do not require the table.
- **The implementer must NOT create/switch branches** (shared working tree). Commit on the current branch.

## Architecture (components touched, ported from which `main.py` symbols)

- **NEW** `app/services/taa_bands.py`:
  - `DEFAULT_TAA_BANDS` + `IPS_CLASS_BOUNDS` + constants ← `main.py:70-114`, `main.py:132-137`, transition block `main.py:107-112`.
  - `compute_effective_band` ← `main.py:252-267` (verbatim).
  - `smooth_regime_centers` ← `main.py:270-285` (verbatim).
  - `effective_class_bands` ← `main.py:803-821` (de-classed; smoothed centers passed/returned explicitly).
  - `macro_quadrant_from_proxies` ← `main.py:710-739` (`_macro_quadrant`; growth = SPY 126d sign, inflation = TIP−IEF 126d breakeven sign). **PARITY-ONLY (decision A): ported + unit-tested for fidelity to the worker, but NOT called on the backend runtime path — the quadrant is READ from `regime_gate_daily`. Kept so the band-routing logic can be verified end-to-end in one place and to document the exact mapping the worker materializes.**
  - `combined_regime` ← `main.py:741-773` (`_combined_regime`; gate dominates → RISK_OFF; RECOVERY→RISK_ON; EXPANSION→INFLATION; SLOWDOWN→STAG_GOLD; CONTRACTION→RISK_OFF).
  - `goldfix_target` ← `main.py:959-972` (the goldfix branch of `_haven_weights`).
  - `vol_graduated_caps` / `beta_graduated_caps` / `asset_betas` / `market_stress` ← `main.py:1039-1061`, `1016-1024`, `998-1014`, `1026-1037`.
  - `fetch_gate_regime` (data-lake reader) ← analogous to `macro_regime.fetch_composite_regime` (`macro_regime.py:187-238`), reading `regime_gate_daily`.

## Global Constraints

- **Pure module:** NO cvxpy/engine import in `taa_bands.py` (math + dataclasses + an async reader). Sprint 3 consumes it.
- **Band table verbatim** (from `main.py:70-114`, transcribe EXACTLY):

  | regime | equity (c/hw) | fixed_income | alternatives | cash |
  |---|---|---|---|---|
  | RISK_ON | 0.52 / 0.08 | 0.30 / 0.06 | 0.12 / 0.04 | 0.06 / 0.03 |
  | RISK_OFF | 0.38 / 0.08 | 0.36 / 0.06 | 0.13 / 0.04 | 0.13 / 0.05 |
  | INFLATION | 0.42 / 0.08 | 0.25 / 0.06 | 0.22 / 0.06 | 0.11 / 0.04 |
  | CRISIS | 0.25 / 0.06 | 0.35 / 0.06 | 0.15 / 0.05 | 0.25 / 0.08 |
  | STAGFLATION | 0.20 / 0.06 | 0.20 / 0.06 | 0.35 / 0.08 | 0.25 / 0.08 |

  COMBO uses `RISK_ON / RISK_OFF / INFLATION` for the band states; STAGFLATION exists in the table but the validated final config routes SLOWDOWN to the goldfix HAVEN (not STAGFLATION bands) — STAGFLATION-as-bands was REFUTED on U3. CRISIS is unused by COMBO.
- **`IPS_CLASS_BOUNDS`** (`main.py:132-137`): equity (0,1), fixed_income (0,1), alternatives (0, 0.40), cash (0,1).
- **Constants:** `HW_SCALE = 1.5` (KEY validated finding — wide bands generalize), `EMA_HALFLIFE_DAYS = 5`, `MAX_DAILY_SHIFT = 0.03`, `ASSET_CLASSES = ["equity", "fixed_income", "alternatives", "cash"]` (order matters), `G_LOOK = 126`, `I_LOOK = 126`, `GATE_DD = 0.06`, `VG_BETA = 1.5`, `BG_COEF = 1.0`.
- **goldfix FINAL weights** (CLI-tunable conviction, defaults): `GLD 0.30 / VOOV 0.20 / QAI 0.20 / GCC 0.0 / BIL 0.30`. Drop weights ≤ 0, keep only names present in the live set, renormalize; fallback `{"BIL": 1.0}` if none available.
- **Product vocabulary:** `equity | fixed_income | cash | alternatives | multi_asset` (verified `AssetClassFilter`, `builder.py:84`; `PortfolioClassLimit` ASSET_CLASSES, `portfolio_constraint.py:40`). The band table covers the first 4; `multi_asset` gets NO band (decision O5 — unbounded, documented).
- **State value convention:** the gate's `state` is lowercase `'risk_on'/'risk_off'` (verified, matches `regime_composite_daily` + `CompositeRegimeSnapshot.state`). `combined_regime` normalizes case before comparing.
- **DECISION A (spec §9 — SUPERSEDES O2):** the growth×inflation quadrant is **materialized by the `regime_gate` worker** (Sprint 1) into `regime_gate_daily.quadrant` (+ `growth_score`/`inflation_score`) and **READ by this service** via `fetch_gate_regime`. The backend does NOT compute it from proxies — TIP/IEF are NOT in `eod_prices` (verified), so a backend computation is infeasible; and the worker is the single source of truth consumed identically by the builder (Sprint 3) and the macro route (Sprint 4). `taa_bands` still ports the pure `macro_quadrant_from_proxies` classifier (parity + unit tests), but `combined_regime` consumes the READ quadrant. This restores the SLOWDOWN→goldfix haven (the mechanism that cut 2022 DD 31.7%→~18%); degrading the quadrant to `None` would silently drop it.
- **O3 DECISION:** the gate drives the bands + (in Sprint 3) the CVaR scaling; the composite stays the Macro-page headline detector. This sprint provides `fetch_gate_regime`; it does NOT touch `macro_regime.fetch_composite_regime`.
- **TDD:** red → green → refactor. **VERIFICATION COMMANDS (confirmed):** `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -v`; lint `ruff check app/`; types `mypy app/`.

---

### Task 1: Constants + `compute_effective_band` + `smooth_regime_centers`

**Files:**
- Create: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: nothing.
- Produces (port verbatim from `main.py:252-267` and `main.py:270-285`):
  - `def compute_effective_band(ips_min: float, ips_max: float, regime_center: float, regime_half_width: float) -> tuple[float, float]`.
  - `def smooth_regime_centers(current_centers: dict[str, float], previous_smoothed: dict[str, float] | None, *, halflife_days: int = EMA_HALFLIFE_DAYS, max_daily_shift: float = MAX_DAILY_SHIFT) -> dict[str, float]`.
  - Module constants `DEFAULT_TAA_BANDS`, `IPS_CLASS_BOUNDS`, `ASSET_CLASSES`, `HW_SCALE`, `EMA_HALFLIFE_DAYS`, `MAX_DAILY_SHIFT` (and `G_LOOK`, `I_LOOK`, `GATE_DD`, `VG_BETA`, `BG_COEF` for later tasks).

- [ ] **Step 1: Write the failing tests** in `tests/test_taa_bands.py`:

```python
from app.services import taa_bands as tb


def test_default_bands_table_values():
    rb = tb.DEFAULT_TAA_BANDS["regime_bands"]
    assert rb["RISK_ON"]["equity"]["center"] == 0.52
    assert rb["RISK_ON"]["equity"]["half_width"] == 0.08
    assert rb["RISK_OFF"]["cash"]["half_width"] == 0.05
    assert rb["INFLATION"]["alternatives"]["center"] == 0.22
    assert rb["STAGFLATION"]["alternatives"]["center"] == 0.35


def test_ips_bounds():
    assert tb.IPS_CLASS_BOUNDS["alternatives"] == (0.0, 0.40)
    assert tb.IPS_CLASS_BOUNDS["equity"] == (0.0, 1.0)


def test_effective_band_clamps_to_ips():
    # center 0.52, hw 0.12 (=0.08*1.5) => [0.40, 0.64]; ips (0,1) keeps it
    lo, hi = tb.compute_effective_band(0.0, 1.0, 0.52, 0.12)
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9


def test_effective_band_center_above_ips_max():
    # alternatives ips max 0.40; center 0.50 hw 0.06 -> regime [0.44,0.56] infeasible
    lo, hi = tb.compute_effective_band(0.0, 0.40, 0.50, 0.06)
    assert hi == 0.40
    assert abs(lo - 0.28) < 1e-9   # max(0.40 - 2*0.06, 0.0)


def test_smooth_first_pass_returns_copy():
    cur = {"equity": 0.52, "cash": 0.06}
    out = tb.smooth_regime_centers(cur, None)
    assert out == cur and out is not cur


def test_smooth_respects_max_daily_shift():
    out = tb.smooth_regime_centers({"equity": 0.52}, {"equity": 0.30},
                                   halflife_days=5, max_daily_shift=0.03)
    assert abs(out["equity"] - 0.33) < 1e-9   # clamped +0.03
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -v`
Expected: FAIL (`ModuleNotFoundError`).

- [ ] **Step 3: Implement** the module skeleton with all constants and the two helpers. Transcribe `DEFAULT_TAA_BANDS` (all 5 regimes), `IPS_CLASS_BOUNDS`, the transition block (`ema_halflife_days=5`, `max_daily_shift_pct=0.03`), and copy `compute_effective_band`/`smooth_regime_centers` verbatim (replace `math` import as needed; `smooth` uses `math.exp`/`math.log`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands constants, effective-band clamp, EMA center smoothing"
```

---

### Task 2: `macro_quadrant_from_proxies` (growth × inflation clock — PARITY-ONLY)

> **Decision A (spec §9):** this classifier is ported + unit-tested for FIDELITY to the worker (Sprint 1 ports the same `_macro_quadrant` and materializes its output), but it is NOT on the backend runtime path — `combined_regime` consumes the quadrant READ from `regime_gate_daily` (Task 7), not a value computed here. Keep it: it documents the exact mapping the worker writes and lets the band-routing be verified end-to-end in one place.

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: `G_LOOK`, `I_LOOK`.
- Produces (port `_macro_quadrant`, `main.py:710-739`):
  - `def _pct_return(closes_desc: list[float], k: int) -> float | None` — newest-first `closes_desc`: `now = closes_desc[0]`, `then = closes_desc[k]`, `return now/then - 1.0` if `len > k` and `then > 0` else `None` (matches `ret_k`, `main.py:714-719`).
  - `def macro_quadrant_from_proxies(spy_desc: list[float], tip_desc: list[float], ief_desc: list[float], *, g_look: int = G_LOOK, i_look: int = I_LOOK) -> dict | None` — returns `{"quadrant", "growth_state", "inflation_state", "growth_score", "inflation_score"}` or `None` if any return is `None`. `growth_score = _pct_return(spy, g_look)`; `inflation_score = _pct_return(tip, i_look) - _pct_return(ief, i_look)`; `growth_up = growth_score > 0`; `infl_up = inflation_score > 0`. Mapping (verbatim `main.py:733-739`): `growth_up & ¬infl_up → RECOVERY`; `growth_up & infl_up → EXPANSION`; `¬growth_up & infl_up → SLOWDOWN`; `¬growth_up & ¬infl_up → CONTRACTION`. `*_state` are `"up"/"down"` strings.

- [ ] **Step 1: Write the failing tests**:

```python
def test_quadrant_recovery():
    spy = [110.0] + [100.0] * 126          # +10% growth up
    tip = [100.0] + [100.0] * 126          # 0%
    ief = [105.0] + [100.0] * 126          # +5% => tip-ief = -5% inflation down
    q = tb.macro_quadrant_from_proxies(spy, tip, ief)
    assert q["quadrant"] == "RECOVERY"
    assert q["growth_state"] == "up" and q["inflation_state"] == "down"


def test_quadrant_expansion():
    spy = [110.0] + [100.0] * 126
    tip = [108.0] + [100.0] * 126
    ief = [102.0] + [100.0] * 126          # +6% breakeven => inflation up
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "EXPANSION"


def test_quadrant_slowdown():
    spy = [90.0] + [100.0] * 126           # -10% growth down
    tip = [108.0] + [100.0] * 126
    ief = [102.0] + [100.0] * 126          # inflation up
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "SLOWDOWN"


def test_quadrant_contraction():
    spy = [90.0] + [100.0] * 126
    tip = [100.0] + [100.0] * 126
    ief = [105.0] + [100.0] * 126          # inflation down
    assert tb.macro_quadrant_from_proxies(spy, tip, ief)["quadrant"] == "CONTRACTION"


def test_quadrant_none_when_insufficient():
    assert tb.macro_quadrant_from_proxies([1.0], [1.0], [1.0]) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k quadrant -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `_pct_return` and `macro_quadrant_from_proxies` (note newest-first ordering — `closes_desc[0]` is "now", `closes_desc[k]` is "k periods ago").

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k quadrant -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands.macro_quadrant_from_proxies (growth/inflation clock)"
```

---

### Task 3: `combined_regime` (gate + quadrant overlay)

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: nothing.
- Produces (port `_combined_regime`, `main.py:741-773`): `def combined_regime(gate_state: str | None, quadrant: str | None, *, defensive_on: str = "growth_down", use_infl_bands: bool = True, slowdown_haven: str = "goldfix") -> str` returning one of `"RISK_ON" | "RISK_OFF" | "INFLATION" | "STAG_GOLD"`. **Both `gate_state` AND `quadrant` are upper-normalized at entry** (the worker materializes the quadrant lowercase, e.g. `"slowdown"`; the reader returns it as-stored, so `combined_regime` must `.upper()` it before matching). Rules (verbatim):
  - `gate_state` normalized-upper == `"RISK_OFF"` → `"RISK_OFF"` (gate dominates).
  - else `quadrant` (normalized-upper) is `None` or `"RECOVERY"` → `"RISK_ON"`.
  - `"EXPANSION"` → `"INFLATION"` if `use_infl_bands` else `"RISK_ON"`.
  - `"SLOWDOWN"` → `"STAG_GOLD"` if `slowdown_haven in ("gold","goldfix")` else (`"STAGFLATION"` / `"INFLATION"` / `"RISK_OFF"` by the legacy switch — for COMBO the default `goldfix` always yields `STAG_GOLD`).
  - `"CONTRACTION"` → `"RISK_OFF"` if `defensive_on=="growth_down"` else `"RISK_ON"`.
  - **NOTE:** `"STAG_GOLD"` is the routing SENTINEL (not a band-table key) telling Sprint 3 to use the goldfix haven instead of class bands. `effective_class_bands` (Task 4) must NOT be called with `"STAG_GOLD"`.

- [ ] **Step 1: Write the failing tests**:

```python
def test_combined_gate_riskoff_dominates():
    assert tb.combined_regime("risk_off", "EXPANSION") == "RISK_OFF"
    assert tb.combined_regime("RISK_OFF", "RECOVERY") == "RISK_OFF"


def test_combined_recovery_is_riskon():
    assert tb.combined_regime("risk_on", "RECOVERY") == "RISK_ON"
    assert tb.combined_regime("risk_on", None) == "RISK_ON"


def test_combined_expansion_uses_inflation_bands():
    assert tb.combined_regime("risk_on", "EXPANSION") == "INFLATION"
    assert tb.combined_regime("risk_on", "EXPANSION", use_infl_bands=False) == "RISK_ON"


def test_combined_slowdown_routes_to_goldfix():
    assert tb.combined_regime("risk_on", "SLOWDOWN") == "STAG_GOLD"
    assert tb.combined_regime("risk_on", "SLOWDOWN", slowdown_haven="bonds") == "RISK_OFF"


def test_combined_normalizes_lowercase_quadrant_from_worker():
    # the regime_gate worker materializes the quadrant lowercase
    assert tb.combined_regime("risk_on", "slowdown") == "STAG_GOLD"
    assert tb.combined_regime("risk_on", "expansion") == "INFLATION"


def test_combined_contraction_defensive():
    assert tb.combined_regime("risk_on", "CONTRACTION") == "RISK_OFF"
    assert tb.combined_regime("risk_on", "CONTRACTION", defensive_on="x") == "RISK_ON"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k combined -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `combined_regime` with `gate_state` upper-normalization.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k combined -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands.combined_regime (gate + quadrant overlay, goldfix route)"
```

---

### Task 4: `effective_class_bands` (regime → per-class (min,max), hw_scale + clamp)

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: `compute_effective_band`, `smooth_regime_centers`, `DEFAULT_TAA_BANDS`, `IPS_CLASS_BOUNDS`, `HW_SCALE`, `ASSET_CLASSES`.
- Produces (port `_effective_class_bands`, `main.py:803-821`, de-classed): `def effective_class_bands(regime: str, *, previous_smoothed: dict[str, float] | None = None, hw_scale: float = HW_SCALE) -> tuple[dict[str, tuple[float, float]], dict[str, float]]` — returns `(bands_by_class, smoothed_centers)`. For the band-table regimes (`RISK_ON/RISK_OFF/INFLATION`, also CRISIS/STAGFLATION exist): `raw_centers[ac] = table[regime][ac]["center"]`; `half_widths[ac] = table[regime][ac]["half_width"] * hw_scale`; smooth the centers via `smooth_regime_centers(raw_centers, previous_smoothed)`; `bands[ac] = compute_effective_band(ips_min, ips_max, smoothed[ac], half_widths[ac])` for each `ac in ASSET_CLASSES`. In the builder point-in-time path `previous_smoothed=None` → smoothing returns the raw centers (faithful to the reference's first step). Raise `ValueError` if `regime == "STAG_GOLD"` (that's a haven sentinel, not a band state) or `regime not in DEFAULT_TAA_BANDS["regime_bands"]`.

- [ ] **Step 1: Write the failing tests**:

```python
def test_effective_class_bands_risk_on_wide():
    bands, _ = tb.effective_class_bands("RISK_ON")          # hw_scale 1.5
    lo, hi = bands["equity"]                                 # c .52, hw .08*1.5=.12
    assert abs(lo - 0.40) < 1e-9 and abs(hi - 0.64) < 1e-9
    a_lo, a_hi = bands["alternatives"]                       # c .12 hw .06 -> [.06,.18]
    assert abs(a_lo - 0.06) < 1e-9 and abs(a_hi - 0.18) < 1e-9


def test_effective_class_bands_inflation_alt_tilt():
    bands, _ = tb.effective_class_bands("INFLATION")
    a_lo, a_hi = bands["alternatives"]                       # c .22 hw .06*1.5=.09 -> [.13,.31]
    assert abs(a_lo - 0.13) < 1e-9 and abs(a_hi - 0.31) < 1e-9


def test_effective_class_bands_riskoff_equity():
    bands, _ = tb.effective_class_bands("RISK_OFF")
    lo, hi = bands["equity"]                                 # c .38 hw .08*1.5=.12 -> [.26,.50]
    assert abs(lo - 0.26) < 1e-9 and abs(hi - 0.50) < 1e-9


def test_effective_class_bands_covers_four_classes_only():
    bands, _ = tb.effective_class_bands("RISK_OFF")
    assert set(bands) == {"equity", "fixed_income", "alternatives", "cash"}


def test_effective_class_bands_rejects_stag_gold():
    import pytest
    with pytest.raises(ValueError):
        tb.effective_class_bands("STAG_GOLD")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k effective_class -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `effective_class_bands` (apply `hw_scale`, smooth, clamp; reject the haven sentinel).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k effective_class -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands.effective_class_bands (hw_scale + IPS clamp)"
```

---

### Task 5: `goldfix_target` (SLOWDOWN haven)

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: nothing.
- Produces (port the goldfix branch, `main.py:959-972`): `def goldfix_target(live_tickers: set[str] | list[str], *, gld_w: float = 0.30, voov_w: float = 0.20, qai_w: float = 0.20, gcc_w: float = 0.0, bil_w: float = 0.30) -> dict[str, float] | None` — `target = {GLD: gld_w, VOOV: voov_w, QAI: qai_w, GCC: gcc_w, BIL: bil_w}`; drop weights ≤ 0; keep only names in `live_tickers`; renormalize to sum 1. If none available, return `{"BIL": 1.0}` when BIL is live else `None`.

- [ ] **Step 1: Write the failing tests**:

```python
def test_goldfix_default_weights_renormalize():
    out = tb.goldfix_target({"GLD", "VOOV", "QAI", "BIL"})  # GCC absent + gcc_w=0
    assert abs(sum(out.values()) - 1.0) < 1e-9
    # 0.30/0.20/0.20/0.30 already sums to 1.0; renorm is identity
    assert abs(out["GLD"] - 0.30) < 1e-9
    assert "GCC" not in out


def test_goldfix_drops_missing_and_renormalizes():
    out = tb.goldfix_target({"GLD", "BIL"})   # only 0.30 + 0.30 -> 0.5/0.5
    assert abs(out["GLD"] - 0.5) < 1e-9 and abs(out["BIL"] - 0.5) < 1e-9


def test_goldfix_fallback_to_bil():
    assert tb.goldfix_target({"BIL"}) == {"BIL": 1.0}


def test_goldfix_none_when_nothing_available():
    assert tb.goldfix_target({"SPY"}) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k goldfix -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `goldfix_target`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k goldfix -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands.goldfix_target (SLOWDOWN gold haven)"
```

---

### Task 6: vol/beta graduated cap vectors

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands.py`

**Interfaces:**
- Consumes: `numpy`, `VG_BETA`, `BG_COEF`.
- Produces (port `main.py:998-1061`, de-classed — caller supplies the return matrices instead of instance windows):
  - `def market_stress(spy_closes_desc: list[float], *, window: int = 63) -> float` — same as Sprint 1's (SPY drawdown from trailing `window`-day high ÷ 0.12, clamped [0,1]); duplicated here so the bands service is self-contained. Returns 0.0 if `< window+1` points.
  - `def asset_betas(asset_returns: dict[str, np.ndarray], spy_returns: np.ndarray) -> dict[str, float]` — per-asset trailing beta `cov(r, spy)/var(spy)` over the common tail (≥40 obs and `var>0` else 1.0); port `_asset_betas` (`main.py:998-1014`).
  - `def vol_graduated_caps(base_cap: float, asset_returns_by_index: list[np.ndarray], spy_closes_desc: list[float], *, vg_beta: float = VG_BETA) -> np.ndarray` — `stress = market_stress(spy)`; if `stress<=0` return `full(n, base_cap)`; per-asset `vol = std(returns)` (use up to 42 obs), `med = median(vols>0)`, `excess = max(0, vol_i/med - 1)`, `cap_i = base_cap * min(1, max(0.02, 1 - vg_beta*stress*excess))` (port `_vol_graduated_caps`, `main.py:1039-1061`).
  - `def beta_graduated_caps(base_caps: np.ndarray, betas_in_order: list[float], *, bg_coef: float = BG_COEF) -> np.ndarray` — `cap_i = base_caps[i] * min(1, max(0.02, 1 - bg_coef*max(0, beta_i - 0.3)))` (port `_beta_graduated_caps`, `main.py:1016-1024`). Applied only in RISK_OFF (the caller gates this).

- [ ] **Step 1: Write the failing tests**:

```python
import numpy as np


def test_vol_graduated_no_stress_returns_base():
    spy_flat = [100.0] * 70
    rets = [np.array([0.01, -0.01, 0.02, -0.02, 0.01, 0.0, 0.01])] * 3
    caps = tb.vol_graduated_caps(0.25, rets, spy_flat)
    assert np.allclose(caps, 0.25)


def test_vol_graduated_cuts_high_vol_under_stress():
    # SPY in 12% drawdown => full stress; asset 0 high vol, asset 1 low vol
    spy = [88.0] + [100.0] * 63
    hi = np.array([0.05, -0.05, 0.06, -0.06, 0.05, -0.05, 0.05])
    lo = np.array([0.001, -0.001, 0.001, -0.001, 0.001, -0.001, 0.001])
    caps = tb.vol_graduated_caps(0.25, [hi, lo], spy, vg_beta=1.5)
    assert caps[0] < 0.25          # above-median vol cut
    assert abs(caps[1] - 0.25) < 1e-9 or caps[1] <= 0.25  # at/below median untouched


def test_beta_graduated_throttles_high_beta():
    base = np.array([0.25, 0.25])
    caps = tb.beta_graduated_caps(base, [1.3, 0.2], bg_coef=1.0)
    # beta 1.3: excess 1.0 => factor max(0.02, 1-1.0)=0.02 => 0.005
    assert abs(caps[0] - 0.25 * 0.02) < 1e-9
    # beta 0.2 < 0.3: no cut
    assert abs(caps[1] - 0.25) < 1e-9


def test_asset_betas_default_when_short():
    out = tb.asset_betas({"A": np.array([0.01, 0.02])}, np.array([0.01, 0.02]))
    assert out["A"] == 1.0   # <40 obs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k "graduated or betas or stress" -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `market_stress`, `asset_betas`, `vol_graduated_caps`, `beta_graduated_caps`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py -k "graduated or betas or stress" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands.py
git commit -m "Add taa_bands vol/beta graduated cap vectors"
```

---

### Task 7: `regime_gate_daily` reader

**Files:**
- Modify: `app/services/taa_bands.py`
- Test: `tests/test_taa_bands_reader.py`

**Interfaces:**
- Consumes: a data-lake `AsyncSession`; the `regime_gate_daily` table (Sprint 1).
- Produces (mirror `macro_regime.fetch_composite_regime`, `macro_regime.py:187-238`, and its `_COMPOSITE_LATEST_SQL` pattern, `macro_regime.py:147`):
  - `@dataclass(frozen=True) class GateRegimeSnapshot: as_of: date; state: str; vote_count: int; trend_vote: bool; credit_vote: bool; drawdown_vote: bool; dwell_days: int; last_flip: date | None; growth_score: float | None; inflation_score: float | None; quadrant: str | None`. **The last three (decision A) carry the worker-materialized quadrant — this is the single source of truth the builder + macro route consume; `quadrant` is stored lowercase (`recovery|expansion|slowdown|contraction|None`).**
  - `async def fetch_gate_regime(datalake: AsyncSession) -> GateRegimeSnapshot | None` — `SELECT regime_date, state, vote_count, trend_vote, credit_vote, drawdown_vote, dwell_days, growth_score, inflation_score, quadrant FROM regime_gate_daily ORDER BY regime_date DESC LIMIT 1`. Returns `None` on empty result; degrade to `None` (wrap in try/except) if the table is absent, matching how the composite reader tolerates a missing relation. (Robustness: if `growth_score`/`inflation_score`/`quadrant` are absent — an older Sprint-1 table without decision-A columns — default them to `None` so the reader still works.)

**Required investigation (implementer):** read `macro_regime.py:117-238` and copy EXACTLY the raw-`text()` query + row-mapping idiom (`.first()` vs `.mappings().first()`, type coercion, `None` handling). Keep the test's fake aligned to whatever idiom the implementation uses.

- [ ] **Step 1: Write the failing test** in `tests/test_taa_bands_reader.py`:

```python
import datetime as dt
import pytest
from app.services import taa_bands as tb


class _Result:
    def __init__(self, row): self._row = row
    def first(self): return self._row
    def mappings(self):
        class _M:
            def __init__(self, r): self._r = r
            def first(self): return self._r
        return _M(self._row)


class _FakeSession:
    def __init__(self, row): self._row = row
    async def execute(self, *a, **k): return _Result(self._row)


@pytest.mark.asyncio
async def test_fetch_gate_regime_maps_row():
    row = {"regime_date": dt.date(2026, 6, 18), "state": "risk_off",
           "vote_count": 2, "trend_vote": True, "credit_vote": True,
           "drawdown_vote": False, "dwell_days": 35,
           "growth_score": -0.04, "inflation_score": 0.02, "quadrant": "slowdown"}
    snap = await tb.fetch_gate_regime(_FakeSession(row))
    assert snap.state == "risk_off"
    assert snap.as_of == dt.date(2026, 6, 18)
    assert snap.dwell_days == 35
    assert snap.quadrant == "slowdown"
    assert snap.growth_score == -0.04


@pytest.mark.asyncio
async def test_fetch_gate_regime_empty_is_none():
    assert await tb.fetch_gate_regime(_FakeSession(None)) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands_reader.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement** `GateRegimeSnapshot` + `fetch_gate_regime`, mirroring `fetch_composite_regime`. Adjust the test fake to the real mapping idiom if needed.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands_reader.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/taa_bands.py backend/tests/test_taa_bands_reader.py
git commit -m "Add regime_gate_daily reader (fetch_gate_regime)"
```

---

### Task 8: Verification gate

- [ ] **Step 1:** `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_taa_bands.py tests/test_taa_bands_reader.py -v` → all green.
- [ ] **Step 2:** Full suite `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest -q` → green (or only the known pre-existing bl-amplo-branch failures).
- [ ] **Step 3:** `ruff check app/app/services/taa_bands.py` (i.e. `ruff check app/`) and `mypy app/` clean on the new module.
- [ ] **Step 4:** Commit any gate fixups.

## Verification gate (the green bar)

- `.venv/Scripts/python -m pytest tests/test_taa_bands.py tests/test_taa_bands_reader.py -v` green.
- `.venv/Scripts/python -m pytest -q` green (modulo documented pre-existing failures).
- `ruff check app/` and `mypy app/` clean on `app/services/taa_bands.py`.

## Self-Review (assumptions, risks, spec gaps)

**Coverage of spec §3.2 / §2.1 / §7.2:**
- `DEFAULT_TAA_BANDS` (incl. STAGFLATION) + IPS + EMA constants → Task 1.
- `compute_effective_band` / `smooth_regime_centers` (verbatim) → Task 1.
- quadrant classifier (PARITY-ONLY — decision A: materialized by the Sprint-1 worker, READ via Task 7; ported here for fidelity/tests) → Task 2.
- `combined_regime` (gate + overlay, SLOWDOWN→goldfix) → Task 3.
- `effective_class_bands` (hw_scale=1.5 + clamp) → Task 4.
- goldfix haven target → Task 5.
- vol/beta graduated overlays → Task 6.
- `regime_gate_daily` reader (consumes Sprint 1) → Task 7.

**Assumptions.**
- `taa_bands` returns building blocks; Sprint 3 owns the dispatch/solve. The graduated caps are de-classed (caller supplies return matrices + SPY closes), faithful to the reference math but decoupled from the QC `RollingWindow` instance state.
- Point-in-time `previous_smoothed=None` ⇒ no EMA smoothing ⇒ raw centers. This is the correct builder behavior (the builder optimizes a single snapshot, not a daily path), and matches the reference's first-step behavior. EMA smoothing only matters in a daily-walk worker (Phase 2) — flagged.
- `STAG_GOLD` is a routing sentinel, not a band-table regime; `effective_class_bands` rejects it and Sprint 3 routes it to `goldfix_target`.

**Risks / what could go wrong.**
- **Quadrant data source — RESOLVED (decision A, spec §9):** the quadrant is materialized by the Sprint-1 `regime_gate` worker (which now fetches TIP too) and READ here via `fetch_gate_regime`. This removes the former open dependency (the backend has no TIP/IEF — verified). Residual risk: the reader and the worker DDL must agree on the column names/lowercase quadrant values (Sprint 1 Task 2 ↔ this Task 7); the reader defaults missing columns to `None` for resilience.
- **Float exactness:** the band tests assert to 1e-9; transcribe the table values EXACTLY (a transposed digit in `half_width` silently shifts a band).
- **`market_stress` duplication:** it appears in both Sprint 1 (worker) and here. Acceptable (separate repos for Sprint 1; within the backend it's one definition). If the owner prefers, extract to a shared util later — YAGNI now.

**Spec gaps / ambiguities / errors found (bias-check payoff).**
- **RESOLVED (decision A, spec §9) — TIP/IEF source.** The earlier gap ("where do TIP/IEF closes come from in the backend?") is settled: they do NOT come from the backend (VERIFIED not in `eod_prices`). Option (a) was chosen — **the `regime_gate` worker fetches SPY/HYG/IEF/TIP and materializes `growth_score`/`inflation_score`/`quadrant` into `regime_gate_daily`** — because the worker is off the request path (no synchronous-Tiingo latency cost, unlike option (b)) and gives a single source of truth consumed identically by the builder (Sprint 3) and the macro route (Sprint 4). This service READS those columns (Task 7); `macro_quadrant_from_proxies` stays as a parity classifier (Task 2) but is off the runtime path. If the worker has not backfilled the quadrant yet, the reader returns `quadrant=None` and the regime is gate-only (RISK_ON/RISK_OFF) — a safe degrade, but the SLOWDOWN→goldfix haven is inactive until the quadrant is populated.
- **MINOR — `effective_class_bands` is de-classed.** The reference is a method using `self.regime`/`self.smoothed_centers`/`self.hw_scale`. The port passes these explicitly. Equivalent, but the implementer must NOT accidentally carry instance state across calls (each builder run starts fresh with `previous_smoothed=None`).
- **MINOR — STAGFLATION/CRISIS bands are transcribed but unused by COMBO.** Kept in the table for fidelity and future use; tests only assert the 3 live regimes + a STAGFLATION center spot-check. Documented so a reviewer doesn't think they're dead-by-mistake.
