# COMBO Sprint 1 — `regime_gate` worker + backend drift-job flip-read — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Materialize a daily LIVE debounced 2-of-3 risk-off gate PLUS the growth/inflation quadrant into a new `regime_gate_daily` table via a new SELF-CONTAINED data-lake worker `src/workers/regime_gate.py` (modeled on `regime_composite.py`), and make the BACKEND `portfolio_drift_daily` job flip-aware so a confirmed gate flip refreshes drift/alerts within a day. **Done when:** the worker's pure-engine tests are green, `regime_gate_daily` upserts idempotently with a per-day `flip` flag AND `growth_score`/`inflation_score`/`quadrant` columns, and the backend drift job reads that flip from the data-lake it already opens and triggers `materialize_all_portfolio_drifts` on a new flip — both repos with a green gate.

**Architecture:** Port the live gate AND the macro quadrant from `lean-research/TaaCvarSuite/main.py` (`_live_gate_riskoff` `main.py:674-708`, `_market_stress` `main.py:1026-1037`, `_macro_quadrant` `main.py:710-739`) into a pure state-machine engine (no I/O), wrapped in an I/O layer that mirrors `regime_composite.py` exactly (full-history recompute, `INSERT ... ON CONFLICT DO UPDATE` in 1000-row chunks, advisory lock, `ensure_schema`). **The worker is SELF-CONTAINED (decision A, spec §9 — supersedes the O1 reuse default): it fetches SPY, HYG, IEF, TIP via Tiingo** (the exact `credit_regime._fetch_prices` pattern — `TiingoClient()` context manager + `fetch_daily_prices(ticker, HISTORY_START, calc_date)` per ticker, verified `credit_regime.py:224-240` / `_tiingo.py:104-139`) and computes the credit vote from the VALIDATED rule **HYG/IEF < SMA60**, with SMA60 computed from the raw HYG/IEF closes it fetches. It does NOT reuse `credit_regime_daily.ratio` (that worker's vote is `ratio < p20_5y` — a DIFFERENT rule; reusing it would break fidelity to the validated backtest). The worker ALSO materializes the growth/inflation quadrant: **growth score** = SPY 126d return (sign), **inflation score** = (TIP/IEF breakeven) 126d momentum (sign), **quadrant** = `_macro_quadrant` mapping. The cross-repo PUSH is a DB-ROW READ: the worker only WRITES `regime_gate_daily` (incl. `flip` + `quadrant`); the backend `portfolio_drift_daily.py` job (separate repo, separate process, its own DSN) READS the flip from the read-only data-lake session it already opens and runs `materialize_all_portfolio_drifts` (which it already calls) — NO in-process cross-repo call.

**Tech Stack:** Python 3.12, psycopg3, numpy, httpx (via `src.workers._tiingo.TiingoClient`), pytest. Worker repo `E:/investintell-datalake-workers`; backend repo `E:/investintell-light/backend`.

## Repo & base branch

- **CROSS-REPO SPRINT — two repos, two branches.**
  - **Tasks 1–5 (the worker)** run in **`E:/investintell-datalake-workers`** on a branch `feat/regime-gate-worker` (that repo's own branch; it has no `feat/bl-amplo-constraints-drift`). The worker repo is independent of the light backend.
  - **Task 6 (the flip-read)** runs in **`E:/investintell-light/backend`** on branch `feat/combo-regime-allocator` based on `feat/bl-amplo-constraints-drift` (the COMBO work depends on bl-amplo's `portfolio_drift` / `materialize_all_portfolio_drifts`, which `main` does NOT have yet). Task 6 modifies `app/jobs/workers/portfolio_drift_daily.py`, which only exists on the bl-amplo branch.
- **The implementer must NOT create/switch branches** (the working tree is shared). Assume the correct branch is already checked out in each repo at execution time. Commit on the current branch.
- This explicit cross-repo split is the single biggest correctness point of the sprint (spec §3.1.1).

## Architecture (components touched)

- **NEW** `E:/investintell-datalake-workers/src/workers/regime_gate.py` — pure engine (port of `_live_gate_riskoff` + `_market_stress` + `_macro_quadrant`) + I/O layer (fetches SPY/HYG/IEF/TIP via Tiingo) + `run()` entrypoint. Structured exactly like `src/workers/regime_composite.py`.
- **NEW** `E:/investintell-datalake-workers/schemas/regime_gate.sql` — `regime_gate_daily` DDL incl. `growth_score`/`inflation_score`/`quadrant` + raw provenance (`spy_close`, `hyg_ief_ratio`, `tip_ief_ratio`) (file named after the WORKER, per the verified convention — NOT `regime_gate_daily.sql`).
- **MODIFY** `E:/investintell-datalake-workers/src/db.py` — register `LOCK_REGIME_GATE = 900_207`.
- **MODIFY** `E:/investintell-datalake-workers/railway.toml` — document the new cron service (comment only; the real service is created in the Railway dashboard).
- **MODIFY** `E:/investintell-light/backend/app/jobs/workers/portfolio_drift_daily.py` — read `regime_gate_daily.flip` from the already-open data-lake session and force a drift re-materialize on a new flip.

## Global Constraints

- **Worker contract (verbatim from `regime_composite.py:239-244`):** `def run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict`. `limit` is accepted by contract and ignored (single series). Return dict keys mirror the composite PLUS the quadrant: `{"days", "upserted", "state", "vote_count", "flips", "last_flip", "dwell_days", "quadrant", "calc_date"}`.
- **Live gate votes (port `_live_gate_riskoff`, `main.py:674-708`):** (1) **trend** `SPY < SMA200`; (2) **credit** `HYG/IEF ratio < SMA60(ratio)` — the VALIDATED rule, with the ratio AND its SMA60 computed from the raw HYG/IEF closes the worker fetches (NOT reused from `credit_regime_daily`); (3) **drawdown** `SPY 63d-drawdown ≥ gate_dd=0.06` (i.e. `_market_stress() * 0.12 >= gate_dd`; `_market_stress` = SPY drawdown from trailing 63d high ÷ 0.12, capped [0,1] — `main.py:1026-1037`). `votes = trend + credit + drawdown`; `raw_off = votes >= 2`.
- **21-day dwell-time debounce (the robust innovation):** latched `state` flips to risk-off only after `raw_off` holds `gate_confirm=21` consecutive days; flips back to risk-on only after `not raw_off` holds 21 consecutive days. Track `gate_on_streak`/`gate_off_streak` exactly as `main.py:698-707`.
- **Macro quadrant (port `_macro_quadrant`, `main.py:710-739`):** **growth score** = SPY 126d return (`g_look=126`; `growth_up = g > 0`); **inflation score** = (TIP/IEF breakeven) 126d momentum (`i_look=126`; `infl_up = (tip_126d_ret − ief_126d_ret) > 0`). The quadrant maps `(growth_up, infl_up)` → `RECOVERY` (up, down) / `EXPANSION` (up, up) / `SLOWDOWN` (down, up) / `CONTRACTION` (down, down). Stored lowercase in `quadrant` (`{recovery,expansion,slowdown,contraction}`); `growth_score`/`inflation_score` store the signed magnitudes for provenance/UI. `quadrant` is `None`/NULL during the 126d warmup (any leg unavailable).
- **DECISION A (self-contained worker, spec §9 — SUPERSEDES the O1 reuse default):** the worker fetches **SPY, HYG, IEF, TIP** via Tiingo (the exact `credit_regime._fetch_prices` pattern: open `TiingoClient()` as a context manager, call `fetch_daily_prices(ticker, HISTORY_START, calc_date)` per ticker — verified `credit_regime.py:224-240`, `_tiingo.py:104-139`). It computes `ratio = HYG/IEF`, `SMA60(ratio)`, SPY `SMA200`, SPY 63d drawdown, and the TIP/IEF breakeven all from these raw closes. It does NOT reuse `credit_regime_daily.ratio` (different rule — would break backtest fidelity) and does NOT degrade the quadrant to `None` (the SLOWDOWN→goldfix haven that cut 2022 DD 31.7%→~18% depends on it). TIP is required for the inflation leg because TIP/IEF are NOT in the backend's `eod_prices` — the worker is the only place the quadrant can be computed.
- **State value convention:** `state ∈ {'risk_on','risk_off'}` (lowercase), matching `regime_composite_daily` and the backend's `regime_cvar_multiplier`/`CompositeRegimeSnapshot.state` (verified lowercase). CHECK constraints mirror `regime_composite_daily`.
- **Advisory lock `LOCK_REGIME_GATE = 900_207`** — VERIFIED free; `LOCK_REGIME_COMPOSITE = 900_206` is the highest in the `900_2xx` band. **Task 2 Step 1 re-confirms 900_207 is still unused** at execution time (shared working tree).
- **Full-history recompute, idempotent upsert** — adjusted closes change retroactively on dividends, so the worker recomputes the entire series each run and upserts via `INSERT ... ON CONFLICT (regime_date) DO UPDATE` in `INSERT_CHUNK = 1000`-row chunks (pattern `regime_composite.py:218-233`).
- **Worker dispatch is by-filename** (no registry dict): `src/run.py:26` does `importlib.import_module(f"src.workers.{args.worker}")` and `src/run_worker.py` reads `WORKER=` env. So `python -m src.run regime_gate` (CLI) and `WORKER=regime_gate` (Railway) work once the file exists.
- **TDD:** red → green → refactor. Pure engine tested without DB/API; integration test gated on env vars (`DATABASE_URL`, `TIINGO_API_KEY`), mirroring `tests/test_regime_composite.py` (no `pytest.ini`/`pyproject.toml`/`conftest.py` in the worker repo — standard discovery).
- **VERIFICATION COMMANDS (confirmed):**
  - Worker repo: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -v` (full suite: `python -m pytest -q`).
  - Backend repo: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_portfolio_drift_worker.py -v`; lint `ruff check app/`; types `mypy app/`.

---

### Task 1: Pure engine — the live gate state machine (no I/O)

**Files:**
- Create: `E:/investintell-datalake-workers/src/workers/regime_gate.py` (pure engine only in this task)
- Test: `E:/investintell-datalake-workers/tests/test_regime_gate.py`

**Interfaces:**
- Consumes: nothing (pure functions, testable without DB/API).
- Produces:
  - `def market_stress(spy_closes_desc: list[float], *, window: int = 63) -> float` — SPY drawdown from trailing `window`-day high, scaled (12% drawdown ⇒ 1.0), clamped to [0,1]. `spy_closes_desc` is newest-first (matches `main.py:1028-1037`: `recent = closes[:window+1]`, `hi = max(recent)`, `now = recent[0]`, `dd = (hi-now)/hi`, `return min(1, max(0, dd/0.12))`). Returns `0.0` if `< window+1` points.
  - `def gate_votes(spy_close: float, spy_sma200: float | None, ratio: float | None, ratio_sma60: float | None, spy_stress: float, *, gate_dd: float = 0.06) -> tuple[bool, bool, bool, int]` — returns `(trend_down, credit_stress, drawdown_stress, vote_count)`. `trend_down = spy_sma200 is not None and spy_close < spy_sma200`; `credit_stress = ratio is not None and ratio_sma60 is not None and ratio < ratio_sma60`; `drawdown_stress = spy_stress * 0.12 >= gate_dd` (equivalently `spy_stress >= gate_dd/0.12`); `vote_count = int(trend_down)+int(credit_stress)+int(drawdown_stress)`. (Unchanged by decision A — `ratio`/`ratio_sma60` are now computed from the raw HYG/IEF closes the worker fetches, but this signature does not change.)
  - `def macro_quadrant(spy_126: list[float], tip_ief_126: list[float], *, g_look: int = 126, i_look: int = 126) -> tuple[str | None, float | None, float | None]` — port `_macro_quadrant` (`main.py:710-739`). `spy_126`/`tip_ief_126` are newest-first windows of SPY close and the TIP/IEF breakeven ratio. `growth = spy_126[0]/spy_126[g_look] - 1` (sign → `growth_up`); `infl = tip_ief_126[0]/tip_ief_126[i_look] - 1` (sign → `infl_up`; rising breakeven ⇒ inflation up). Returns `(quadrant, growth_score, inflation_score)` where `quadrant ∈ {'recovery','expansion','slowdown','contraction'}` via `(growth_up, infl_up)` mapping (up/down→recovery, up/up→expansion, down/up→slowdown, down/down→contraction). Returns `(None, None, None)` when either window is too short (`<look+1` points) or a denominator ≤ 0.
  - `def build_rows(dates: list[date], spy: list[float], ratio: list[float | None], breakeven: list[float | None], *, gate_confirm: int = 21, gate_dd: float = 0.06, sma_trend: int = 200, sma_credit: int = 60, stress_window: int = 63, g_look: int = 126, i_look: int = 126) -> list[dict]` — runs the full daily state machine over aligned series (oldest→newest); `breakeven` is the daily TIP/IEF ratio (carried-forward; `None` before the first TIP obs). For each day `t`: compute `SMA200(spy[..t])`, `SMA60(ratio[..t])`, `market_stress(spy[..t] reversed)`, then `gate_votes`; ALSO compute the quadrant via `macro_quadrant(spy[..t] reversed, breakeven[..t] reversed)`; apply the dwell-time hysteresis on a running `state`/`on_streak`/`off_streak`; emit one row per day with keys `{"regime_date", "state", "trend_vote", "credit_vote", "drawdown_vote", "vote_count", "flip", "dwell_days", "growth_score", "inflation_score", "quadrant", "spy_close", "hyg_ief_ratio", "tip_ief_ratio", "spy_dd"}`. `flip = (state != previous_state)`. `dwell_days` = consecutive days the latched `state` has held (reset to 1 on a flip). The initial latched state before any confirm is `'risk_on'` (matches `gate_off=False` start in `main.py`). `quadrant` is `None` during the 126d warmup.
- Module constants: `GATE_CONFIRM_DEFAULT = 21`, `GATE_DD_DEFAULT = 0.06`, `SMA_TREND = 200`, `SMA_CREDIT = 60`, `STRESS_WINDOW = 63`, `GROWTH_LOOK = 126`, `INFLATION_LOOK = 126`, `SPY_TICKER = "SPY"`, `HYG_TICKER = "HYG"`, `IEF_TICKER = "IEF"`, `TIP_TICKER = "TIP"`, `HISTORY_START = date(2003, 1, 1)`, `INSERT_CHUNK = 1000`. **Do NOT import the advisory lock at module top in this task** (it's added to `src.db` in Task 2; importing it now would break the pure-engine import). Add a top-of-file docstring mirroring the `regime_composite.py` contract block.

- [ ] **Step 1: Write the failing tests** in `tests/test_regime_gate.py`:

```python
import datetime as _dt

from src.workers import regime_gate as rg


def test_market_stress_no_drawdown_is_zero():
    closes = [100.0] * 70  # flat, newest-first
    assert rg.market_stress(closes) == 0.0


def test_market_stress_full_at_12pct():
    # newest-first: now=88 (index 0), trailing-63 high=100 => dd=0.12 => 1.0
    closes = [88.0] + [100.0] * 63
    assert abs(rg.market_stress(closes) - 1.0) < 1e-9


def test_market_stress_insufficient_history():
    assert rg.market_stress([100.0, 99.0]) == 0.0


def test_gate_votes_counts_two_of_three():
    # trend down (spy<sma200) + drawdown (stress*0.12>=0.06) => 2 votes
    t, c, d, n = rg.gate_votes(
        spy_close=90.0, spy_sma200=100.0, ratio=1.0, ratio_sma60=0.9,
        spy_stress=0.6, gate_dd=0.06,
    )
    assert t is True and c is False and d is True and n == 2


def test_gate_votes_credit_leg():
    t, c, d, n = rg.gate_votes(
        spy_close=110.0, spy_sma200=100.0, ratio=0.8, ratio_sma60=0.9,
        spy_stress=0.0, gate_dd=0.06,
    )
    assert c is True and t is False and d is False and n == 1


def test_macro_quadrant_slowdown_growth_down_inflation_up():
    # newest-first: SPY down over 126d (growth<0), breakeven up over 126d (infl>0)
    spy = [90.0] + [100.0] * 126     # now 90 vs 126d-ago 100 -> growth down
    be = [1.10] + [1.00] * 126       # now 1.10 vs 1.00 -> breakeven up
    quad, g, i = rg.macro_quadrant(spy, be)
    assert quad == "slowdown" and g < 0 and i > 0


def test_macro_quadrant_warmup_is_none():
    quad, g, i = rg.macro_quadrant([100.0, 99.0], [1.0, 1.0])
    assert quad is None and g is None and i is None


def test_build_rows_debounce_holds_21_days_before_flip():
    # 30 days of deep stress then nothing should flip risk_off only after 21d
    n = 260
    dates = [_dt.date(2020, 1, 1) + _dt.timedelta(days=i) for i in range(n)]
    # SPY: rise for 200 days (warmup for SMA200), then crash hard and stay low.
    spy = [100.0 + i * 0.1 for i in range(210)] + [70.0] * (n - 210)
    ratio = [1.0] * n  # credit leg neutral (ratio == sma60 ~ no stress)
    breakeven = [1.0] * n  # neutral inflation leg
    rows = rg.build_rows(dates, spy, ratio, breakeven, gate_confirm=21)
    # find first risk_off row
    off = [r for r in rows if r["state"] == "risk_off"]
    assert off, "gate should eventually latch risk_off under a sustained crash"
    first_off_idx = rows.index(off[0])
    # the crash starts at index 210; latch needs 21 consecutive confirms
    assert first_off_idx >= 210 + 21 - 1
    # exactly one flip row at the latch boundary
    assert off[0]["flip"] is True
    assert rows[first_off_idx - 1]["flip"] is False


def test_build_rows_emits_one_row_per_ready_day_with_schema():
    n = 210
    dates = [_dt.date(2021, 1, 1) + _dt.timedelta(days=i) for i in range(n)]
    spy = [100.0 + i for i in range(n)]
    ratio = [1.0] * n
    breakeven = [1.0] * n
    rows = rg.build_rows(dates, spy, ratio, breakeven)
    assert rows, "should emit rows once SMA windows are warm"
    assert set(rows[-1]) >= {
        "regime_date", "state", "trend_vote", "credit_vote",
        "drawdown_vote", "vote_count", "flip", "dwell_days",
        "growth_score", "inflation_score", "quadrant",
        "spy_close", "hyg_ief_ratio", "tip_ief_ratio", "spy_dd",
    }
    assert rows[-1]["state"] in {"risk_on", "risk_off"}
    assert rows[-1]["quadrant"] in {
        "recovery", "expansion", "slowdown", "contraction", None,
    }
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -v`
Expected: FAIL with `ModuleNotFoundError`/`AttributeError` (module + functions do not exist).

- [ ] **Step 3: Implement the pure engine** in `src/workers/regime_gate.py`

Write the contract docstring (mirror `regime_composite.py:1-30`), the module constants, and `market_stress`, `gate_votes`, `macro_quadrant`, `build_rows`. In `build_rows`, accumulate `state`/`on_streak`/`off_streak` left-to-right exactly as `main.py:698-707`: on `raw_off` increment `on_streak`, reset `off_streak`; else increment `off_streak`, reset `on_streak`; flip to risk-off when `state=='risk_on' and on_streak>=gate_confirm`; flip to risk-on when `state=='risk_off' and off_streak>=gate_confirm`. Compute SMAs as simple trailing means over the prior `sma_*` closes (skip emitting until `SMA200` is warm, matching the composite's warmup behavior). Per day also call `macro_quadrant(...)` over the trailing 126d SPY + breakeven windows → `quadrant`/`growth_score`/`inflation_score` (all `None` during the 126d warmup). Record provenance: `spy_close = spy[t]`, `hyg_ief_ratio = ratio[t]`, `tip_ief_ratio = breakeven[t]`, `spy_dd = market_stress(...) * 0.12` (the actual drawdown fraction). Do not add I/O here.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -v`
Expected: PASS (all pure-engine tests).

- [ ] **Step 5: Commit**

```bash
git add src/workers/regime_gate.py tests/test_regime_gate.py
git commit -m "Add regime_gate pure engine (2-of-3 vote + 21d dwell debounce)"
```

---

### Task 2: DDL + advisory lock registration

**Files:**
- Create: `E:/investintell-datalake-workers/schemas/regime_gate.sql`
- Modify: `E:/investintell-datalake-workers/src/db.py` (lock registry, `src/db.py:47-62` — add after `LOCK_REGIME_COMPOSITE = 900_206`)
- Test: `E:/investintell-datalake-workers/tests/test_regime_gate.py` (add DDL + lock checks)

**Interfaces:**
- Consumes: nothing.
- Produces: idempotent `schemas/regime_gate.sql` creating `regime_gate_daily`, and `LOCK_REGIME_GATE = 900_207` in `src/db.py`.

The DDL (modeled on `schemas/regime_composite.sql`):

```sql
CREATE TABLE IF NOT EXISTS regime_gate_daily (
    regime_date     date           NOT NULL,
    state           text           NOT NULL,           -- 'risk_on' | 'risk_off' (latched)
    trend_vote      boolean        NOT NULL,           -- SPY < SMA200
    credit_vote     boolean        NOT NULL,           -- HYG/IEF ratio < SMA60 (raw closes)
    drawdown_vote   boolean        NOT NULL,           -- SPY 63d-drawdown >= gate_dd
    vote_count      smallint       NOT NULL,           -- 0..3
    flip            boolean        NOT NULL DEFAULT false,
    dwell_days      integer        NOT NULL,           -- consecutive days in latched state
    growth_score    numeric(14,8),                     -- SPY 126d return (signed); NULL in warmup
    inflation_score numeric(14,8),                     -- TIP/IEF breakeven 126d momentum (signed)
    quadrant        text,                              -- recovery|expansion|slowdown|contraction|NULL
    spy_close       numeric(14,8),                     -- SPY close (provenance)
    hyg_ief_ratio   numeric(14,8),                     -- credit ratio (provenance)
    tip_ief_ratio   numeric(14,8),                     -- inflation breakeven (provenance)
    spy_dd          numeric(14,8),                     -- SPY drawdown from 63d high (provenance)
    computed_at     timestamptz    NOT NULL DEFAULT now(),

    CONSTRAINT regime_gate_daily_pkey PRIMARY KEY (regime_date),
    CONSTRAINT ck_regime_gate_state CHECK (state IN ('risk_on', 'risk_off')),
    CONSTRAINT ck_regime_gate_votes CHECK (vote_count BETWEEN 0 AND 3),
    CONSTRAINT ck_regime_gate_quadrant CHECK (
        quadrant IS NULL OR quadrant IN
        ('recovery', 'expansion', 'slowdown', 'contraction')
    )
);
```

- [ ] **Step 1: Re-confirm the lock id is free, then write failing tests**

First re-confirm `900_207` is still unused (shared tree):
Run: `cd /e/investintell-datalake-workers && grep -n "900_207" src/db.py` → expect NO match.
If it IS taken, pick the next free id in the `900_2xx` band (e.g. `900_208`) and use that consistently everywhere in this plan; note the substitution in the commit.

Add to `tests/test_regime_gate.py`:

```python
import pathlib


def test_ddl_file_exists_and_declares_table():
    sql = (pathlib.Path(__file__).resolve().parents[1]
           / "schemas" / "regime_gate.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS regime_gate_daily" in sql
    assert "regime_gate_daily_pkey PRIMARY KEY (regime_date)" in sql
    assert "ck_regime_gate_state" in sql
    assert "ck_regime_gate_quadrant" in sql
    assert "quadrant" in sql and "growth_score" in sql


def test_lock_id_registered_and_unique():
    from src import db
    assert db.LOCK_REGIME_GATE == 900_207
    # no collision with the highest existing 900_2xx lock
    assert db.LOCK_REGIME_GATE != db.LOCK_REGIME_COMPOSITE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -k "ddl or lock" -v`
Expected: FAIL (file missing; `LOCK_REGIME_GATE` undefined).

- [ ] **Step 3: Implement DDL + lock**

Create `schemas/regime_gate.sql` (content above). In `src/db.py`, add `LOCK_REGIME_GATE = 900_207` immediately after `LOCK_REGIME_COMPOSITE = 900_206` in the lock-constant block.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -k "ddl or lock" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add schemas/regime_gate.sql src/db.py tests/test_regime_gate.py
git commit -m "Add regime_gate_daily DDL and advisory lock 900_207"
```

---

### Task 3: I/O layer — fetch, align, upsert

**Files:**
- Modify: `E:/investintell-datalake-workers/src/workers/regime_gate.py` (add I/O; no `run` yet)
- Test: `E:/investintell-datalake-workers/tests/test_regime_gate.py` (upsert via a fake connection)

**Interfaces:**
- Consumes: `src.db.connect` / `src.db.advisory_lock` / `src.db.LOCK_REGIME_GATE` (Task 2); `src.workers._tiingo.TiingoClient.fetch_daily_prices(ticker, start_date, end_date=None) -> list[tuple[date, float | None]]` (verified `_tiingo.py:104-139`). **No DB read of `credit_regime_daily` (decision A).** The credit and inflation legs come from RAW Tiingo closes, exactly like `credit_regime._fetch_prices` (`credit_regime.py:224-240`).
- Produces:
  - `def ensure_schema(conn) -> None` — reads `schemas/regime_gate.sql` and executes it (pattern `regime_composite.ensure_schema`, `regime_composite.py:150-157`).
  - `def _fetch_prices(calc_date) -> tuple[list, list, list, list]` — opens ONE `TiingoClient()` context manager and fetches SPY, HYG, IEF, TIP via `client.fetch_daily_prices(ticker, HISTORY_START, calc_date)` (the verbatim `credit_regime._fetch_prices` shape, extended from 2→4 tickers). Returns the four `[(date, close|None)]` lists. **Fail loud** (`RuntimeError`) if SPY, HYG, or IEF is empty (no detector without them); TIP may be empty/short → the inflation leg (and thus `quadrant`) is simply `None` for those days, the gate still works.
  - `def _align(spy, hyg, ief, tip) -> tuple[list[date], list[float], list[float | None], list[float | None]]` — align on SPY's date grid (SPY is the spine: the trend + drawdown legs need it daily). For each SPY date compute `ratio = HYG/IEF` (carry-forward the last HYG and IEF close on non-print days; `None` before the first HYG/IEF obs) and `breakeven = TIP/IEF` (carry-forward; `None` before the first TIP obs). Returns `(dates, spy_closes, ratio, breakeven)`. Raise `RuntimeError` if SPY is empty. (HYG/IEF/TIP are sparser only by calendar gaps; in practice they share the US equity calendar with SPY.)
  - `def _upsert(conn, rows: list[dict]) -> int` — `INSERT INTO regime_gate_daily (...) VALUES (...) ON CONFLICT (regime_date) DO UPDATE SET ...` in `INSERT_CHUNK` chunks (pattern `regime_composite._upsert`, `regime_composite.py:218-233`); the column list MUST match the Task 2 DDL (incl. `growth_score`, `inflation_score`, `quadrant`, `spy_close`, `hyg_ief_ratio`, `tip_ief_ratio`, `spy_dd`). Returns row count.

- [ ] **Step 1: Write the failing test** (fake connection; no real DB):

```python
import datetime as _dt


class _FakeCursor:
    def __init__(self, sink): self.sink = sink
    def __enter__(self): return self
    def __exit__(self, *a): return False
    def executemany(self, sql, params): self.sink.extend(params)
    def execute(self, sql, params=None): pass


class _FakeConn:
    def __init__(self): self.sink = []
    def cursor(self): return _FakeCursor(self.sink)
    def execute(self, *a, **k): pass
    def commit(self): pass


def test_upsert_chunks_all_rows():
    conn = _FakeConn()
    rows = [{
        "regime_date": _dt.date(2020, 1, 1) + _dt.timedelta(days=i),
        "state": "risk_on", "trend_vote": False, "credit_vote": False,
        "drawdown_vote": False, "vote_count": 0, "flip": False,
        "dwell_days": i + 1, "growth_score": 0.0, "inflation_score": 0.0,
        "quadrant": None, "spy_close": 100.0, "hyg_ief_ratio": 1.0,
        "tip_ief_ratio": 1.0, "spy_dd": 0.0,
    } for i in range(2500)]
    n = rg._upsert(conn, rows)
    assert n == 2500
    assert len(conn.sink) == 2500


def test_align_builds_ratio_and_breakeven_carrying_forward():
    spy = [(_dt.date(2020, 1, d), 100.0 + d) for d in range(1, 6)]
    hyg = [(_dt.date(2020, 1, 2), 90.0), (_dt.date(2020, 1, 4), 88.0)]
    ief = [(_dt.date(2020, 1, 2), 100.0), (_dt.date(2020, 1, 4), 110.0)]
    tip = [(_dt.date(2020, 1, 3), 120.0)]
    dates, s, ratio, be = rg._align(spy, hyg, ief, tip)
    assert dates[0] == _dt.date(2020, 1, 1)
    assert ratio[0] is None          # before first HYG/IEF obs
    assert abs(ratio[1] - 0.90) < 1e-9   # 90/100
    assert abs(ratio[2] - 0.90) < 1e-9   # carried forward
    assert abs(ratio[3] - 0.80) < 1e-9   # 88/110
    assert be[1] is None             # before first TIP obs
    assert abs(be[2] - 1.20) < 1e-9      # 120/100 (IEF carried from day 2)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -k "upsert or align" -v`
Expected: FAIL (`AttributeError`: `_upsert`/`_align` not defined).

- [ ] **Step 3: Implement the I/O layer**

Add `ensure_schema`, `_fetch_prices` (SPY/HYG/IEF/TIP via one `TiingoClient()` — copy the `credit_regime._fetch_prices` shape and extend 2→4 tickers), `_align`, `_upsert`. The lock import is now safe (Task 2 added `LOCK_REGIME_GATE`). Mirror `regime_composite.py:148-233` / `credit_regime.py:243-258` for the upsert column list / `ON CONFLICT` clause and the `INSERT_CHUNK` loop; the column list MUST match the Task 2 DDL.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -k "upsert or align" -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/workers/regime_gate.py tests/test_regime_gate.py
git commit -m "Add regime_gate I/O layer (fetch SPY + credit ratio, align, upsert)"
```

---

### Task 4: `run()` entrypoint + integration test

**Files:**
- Modify: `E:/investintell-datalake-workers/src/workers/regime_gate.py` (add `run`)
- Test: `E:/investintell-datalake-workers/tests/test_regime_gate.py` (env-gated integration test)

**Interfaces:**
- Consumes: all of Tasks 1–3.
- Produces: `def run(dsn: str, *, calc_date: str | None = None, limit: int | None = None) -> dict` — `connect(dsn)` + `advisory_lock(conn, LOCK_REGIME_GATE)`; if the lock is busy return `{"days": 0, "upserted": 0, "skipped": "lock_busy"}`; else `ensure_schema(conn)`; `_fetch_prices(cdate)` (SPY/HYG/IEF/TIP via Tiingo); `_align`; `build_rows(dates, spy, ratio, breakeven)`; `_upsert`; `conn.commit()`; return `{"days": len(rows), "upserted": n, "state": rows[-1]["state"] if rows else None, "vote_count": rows[-1]["vote_count"] if rows else None, "flips": sum(1 for r in rows if r["flip"]), "last_flip": (last flip date isoformat or None), "dwell_days": rows[-1]["dwell_days"] if rows else None, "quadrant": rows[-1]["quadrant"] if rows else None, "calc_date": rows[-1]["regime_date"].isoformat() if rows else None}`. `limit` accepted and ignored. The Tiingo client is constructed inside `_fetch_prices` (from `TIINGO_API_KEY` env via `TiingoClient`), exactly like `credit_regime._fetch_prices`.

- [ ] **Step 1: Write the failing/integration tests**

```python
import os
import pytest


@pytest.mark.skipif(
    not (os.getenv("DATABASE_URL") and os.getenv("TIINGO_API_KEY")),
    reason="needs cloud DSN + Tiingo key",
)
def test_run_real_history_is_idempotent():
    stats = rg.run(os.environ["DATABASE_URL"])
    assert stats["days"] > 3_000          # ~2003->today daily, post warmup
    assert stats["state"] in {"risk_on", "risk_off"}
    assert stats["quadrant"] in {
        "recovery", "expansion", "slowdown", "contraction", None,
    }
    assert isinstance(stats["flips"], int)
    stats2 = rg.run(os.environ["DATABASE_URL"])
    assert stats2["days"] == stats["days"]   # idempotent recompute
```

Also add a unit test that `run` returns the lock-busy sentinel when the lock can't be acquired, using a fake `advisory_lock` that yields `False` (monkeypatch `rg.advisory_lock`).

- [ ] **Step 2: Run tests to verify they fail/skip**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -k "run" -v`
Expected: the lock-busy unit test FAILS (run not implemented); the integration test is `skipped` without env.

- [ ] **Step 3: Implement `run`**

Add `run` (advisory lock, ensure_schema, fetch, align, build_rows, upsert, commit, summary dict). Mirror `regime_composite.run` (`regime_composite.py:239-274`).

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-datalake-workers && python -m pytest tests/test_regime_gate.py -v`
Expected: unit tests PASS; integration `skipped` (or PASS if env present).

- [ ] **Step 5: Commit**

```bash
git add src/workers/regime_gate.py tests/test_regime_gate.py
git commit -m "Add regime_gate run() entrypoint with advisory lock"
```

---

### Task 5: Railway cron documentation

**Files:**
- Modify: `E:/investintell-datalake-workers/railway.toml` (the scheduling comment block, `railway.toml:1-20`)

**Interfaces:**
- Consumes: nothing.
- Produces: a comment line documenting the new cron service. **VERIFIED:** `railway.toml` has ONE global `[deploy]` block (`startCommand = "python -m src.run_worker"`, `cronSchedule = "0 7 * * *"`); per-service `WORKER=` + `cronSchedule` are set in the Railway dashboard, NOT in this file. So this task is documentation only (matching how `credit_regime`/`regime_composite` are documented as comments, e.g. `credit_regime -> daily 06:30 UTC ...`).

- [ ] **Step 1: Edit the comment block**

Add a line after the `regime_composite` comment, e.g.:
`# regime_gate        -> daily ~06:50 UTC (self-contained: fetches SPY/HYG/IEF/TIP via Tiingo; needs TIINGO_API_KEY; schedule AFTER regime_composite, BEFORE backend portfolio_drift_daily)`

- [ ] **Step 2: Commit**

```bash
git add railway.toml
git commit -m "Document regime_gate cron in railway.toml"
```

- [ ] **Step 3 (handoff note, outside code):** record in the PR that the owner must create the Railway service `regime-gate` (`WORKER=regime_gate`, `DATABASE_URL`, `TIINGO_API_KEY`, `cronSchedule="50 6 * * *"`) and run `python -m src.run regime_gate` once for the initial backfill, scheduled to land before the backend `portfolio_drift_daily` daily run so the flip-read (Task 6) sees a fresh gate.

---

### Task 6: Backend drift-job flip-read (CROSS-REPO — light backend)

**Files:**
- Modify: `E:/investintell-light/backend/app/jobs/workers/portfolio_drift_daily.py` (the `run()` body, `portfolio_drift_daily.py:76-108`)
- Test: `E:/investintell-light/backend/tests/test_portfolio_drift_worker.py` (extend the existing worker test)

**Interfaces:**
- Consumes: the already-open read-only data-lake session from `_open_datalake()` (`portfolio_drift_daily.py:61-73`); the new `regime_gate_daily` table (Tasks 2–4).
- Produces (OBSERVATIONAL v1 — decision C, spec §9): a flip-read that, BEFORE calling `materialize_all_portfolio_drifts`, queries the latest `regime_gate_daily` row from `datalake` and surfaces its `flip`/`state` as context on the run/alert (so a rebalance is explained as regime-driven). Because `materialize_all_portfolio_drifts` is ALREADY called unconditionally on every daily run (`portfolio_drift_daily.py:91`), the implementation is: read the flip, return it in the result, and keep the unconditional materialize (the daily cadence already refreshes within a day — decision O6/C). NO conditional materialize and NO cursor table in v1. The flip-read makes the trigger EXPLICIT and observable, returning `gate_flip`/`gate_state` so the run is auditable.
  - New helper `async def _read_gate_flip(datalake: AsyncSession | None) -> tuple[bool, str | None, date | None]` — returns `(flipped_today, state, regime_date)` from `SELECT regime_date, state, flip FROM regime_gate_daily ORDER BY regime_date DESC LIMIT 1`. Returns `(False, None, None)` when `datalake is None` or the table is empty/absent (wrap in try/except for `ProgrammingError`/`UndefinedTable`, mirroring how the drift evaluator degrades when the data-lake is unavailable). `flipped_today` = the latest row's `flip` is `True`.
  - `run()` returns the existing keys PLUS `"gate_flip": flipped`, `"gate_state": state` (purely additive — does not change the existing `status`/`portfolios` contract).

**Decision (verbatim, O6):** keep the daily `portfolio_drift_daily` schedule. A 21-day-debounced gate flips rarely and a confirmed flip is a once-a-day event, so "within a day" is ample. NO tighter post-flip schedule, NO `pg_notify`/`LISTEN`, NO new endpoint, NO in-process call from the worker repo (the worker and backend are separate processes with separate DSNs — the only coupling is the `regime_gate_daily` DB row).

- [ ] **Step 1: Write the failing test** in `tests/test_portfolio_drift_worker.py`

Mirror the existing worker test's setup. Seed a `regime_gate_daily` row in the data-lake test fixture (or stub `_read_gate_flip`'s SQL via the same data-lake session the test already provides) with `flip=True`, then assert `run(...)` returns `gate_flip is True` and `gate_state` set, and still materializes the drift rows. Add a second case with no `regime_gate_daily` table → `gate_flip is False` and the run still succeeds (graceful degradation).

```python
import pytest


@pytest.mark.asyncio
async def test_drift_run_reports_gate_flip(seeded_portfolio, datalake_session):
    # given a regime_gate_daily latest row with flip=True (seed via the test
    # data-lake helper the existing worker test uses), the daily run reports it
    from app.jobs.workers import portfolio_drift_daily as job
    result = await job.run(portfolio_ids=[seeded_portfolio.id])
    assert result["status"] == "ok"
    assert result["gate_flip"] is True
    assert result["gate_state"] in {"risk_on", "risk_off"}


@pytest.mark.asyncio
async def test_drift_run_degrades_without_gate_table(seeded_portfolio):
    # no regime_gate_daily table / no datalake => gate_flip False, run still ok
    from app.jobs.workers import portfolio_drift_daily as job
    result = await job.run(portfolio_ids=[seeded_portfolio.id])
    assert result["status"] == "ok"
    assert result["gate_flip"] is False
```

(Align fixture names to the real ones in `tests/test_portfolio_drift_worker.py` — read it first to reuse its portfolio/data-lake seam.)

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_portfolio_drift_worker.py -k gate -v`
Expected: FAIL (`KeyError: 'gate_flip'` — the key isn't returned yet).

- [ ] **Step 3: Implement `_read_gate_flip` + wire it into `run()`**

Add `_read_gate_flip` and call it inside `run()` within the `async with _open_datalake() as datalake:` block, BEFORE `materialize_all_portfolio_drifts`, passing the same `datalake` session. Add `gate_flip`/`gate_state` to the returned dict. Keep the existing unconditional materialize and the lock/commit/rollback structure unchanged.

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest tests/test_portfolio_drift_worker.py -v`
Expected: PASS (no regression in existing worker tests).

- [ ] **Step 5: Commit**

```bash
git add backend/app/jobs/workers/portfolio_drift_daily.py backend/tests/test_portfolio_drift_worker.py
git commit -m "Make portfolio_drift_daily flip-aware (read regime_gate_daily)"
```

---

### Task 7: Verification gate (both repos)

- [ ] **Step 1: Worker repo** — `cd /e/investintell-datalake-workers && python -m pytest -q` → green (integration tests `skipped` without env, or green with `DATABASE_URL`+`TIINGO_API_KEY`).
- [ ] **Step 2: Backend repo** — `cd /e/investintell-light/backend && .venv/Scripts/python -m pytest -q` → green (or only the known pre-existing failures documented for the bl-amplo branch).
- [ ] **Step 3: Backend lint/type** — `ruff check app/` and `mypy app/` on the touched file (`app/jobs/workers/portfolio_drift_daily.py`).
- [ ] **Step 4: Commit** any gate fixups; otherwise the sprint is done.

## Verification gate (the green bar)

- Worker repo: `python -m pytest -q` green; `regime_gate.py` pure-engine + I/O tests pass; DDL/lock tests pass; integration test passes or skips cleanly.
- Backend repo: `.venv/Scripts/python -m pytest -q` green; `ruff check app/` and `mypy app/` clean on `portfolio_drift_daily.py`.

## Self-Review (assumptions, risks, spec gaps)

**Coverage of spec §3.1 / §3.1.1 / §7.1:**
- New `regime_gate.py` worker (pure engine + I/O + run) → Tasks 1, 3, 4.
- `regime_gate_daily` table + lock `900_207` → Task 2.
- 21d-debounced 2-of-3 vote ported from `_live_gate_riskoff`/`_market_stress` → Task 1.
- Cross-repo flip-read in `portfolio_drift_daily` (DB-row read, NOT in-process call) → Task 6.
- Railway cron documented → Task 5.

**Assumptions.**
- **The worker is self-contained (decision A, spec §9 — supersedes O1).** It fetches SPY, HYG, IEF, TIP via Tiingo and computes `ratio = HYG/IEF`, `SMA60(ratio)`, and the TIP/IEF breakeven from those raw closes. It does NOT reuse `credit_regime_daily.ratio`: the `credit_regime` worker's credit vote is a *percentile* (`ratio < p20_5y`), a DIFFERENT rule than the validated gate's `ratio < SMA60(ratio)` crossover — reusing it would break backtest fidelity. The 4-ticker Tiingo fetch follows the verified `credit_regime._fetch_prices` pattern exactly (`credit_regime.py:224-240`), extended 2→4 tickers; cost is irrelevant off the request path (Railway cron).
- The worker uses SPY as the date spine and carries HYG/IEF/TIP forward on non-print days. This is faithful to the reference (the gate evaluates daily on SPY's calendar) and avoids dropping SPY days when a leg has a calendar gap. TIP gaps (or short TIP history) leave `quadrant=None` for those days without disabling the gate.
- The backend already opens a read-only data-lake session in the drift job (`_open_datalake`), so reading `regime_gate_daily` is a known pattern — no new connection plumbing.

**Risks / what could go wrong.**
- **Lock-id collision:** `900_207` is free today but the working tree is shared. Task 2 Step 1 re-confirms; substitute the next free id if taken.
- **Cross-repo ordering:** the backend flip-read only sees a fresh flip if the `regime_gate` cron runs BEFORE the backend `portfolio_drift_daily` cron. The handoff note (Task 5 Step 3) calls this out. If they run out of order on a given day, the flip is simply picked up the next day — acceptable for a 21d-debounced signal (O6).
- **`flip` semantics:** the worker's `flip` is per-day (today differs from yesterday). The backend reads "latest row flipped". If the drift job runs multiple times in a day, the same flip is read twice — harmless because the materialize is idempotent and the existing job already materializes unconditionally.

**Spec gaps / ambiguities / errors found (bias-check payoff).**
- **RESOLVED (decision C, spec §9) — the flip-read is OBSERVATIONAL in v1.** §3.1.1 says the backend reads "did the gate flip since my last run?" but the drift job stores no "last gate read" cursor. The decided behavior is **observational v1: surface the flip context; the materialize stays daily/unconditional.** This plan reads the *latest row's* `flip` and surfaces it in the result (explicit + observable) while keeping the already-unconditional `materialize_all_portfolio_drifts`. NO cursor table in v1 (YAGNI). A future conditional materialize (skip work on non-flip days) would need a persisted "last processed regime_date" — explicitly deferred (relates to O6).
- **MINOR — `railway.toml` shape.** The pending-note and the 2026-06-20 plan implied per-service blocks in `railway.toml`; VERIFIED it has a single global `[deploy]` block and per-service config lives in the Railway dashboard. Task 5 is therefore documentation-only (corrected here).
- **MINOR — worker `run()` return keys.** The spec lists `dwell_days` in the return dict; the composite's `run()` does NOT return `dwell_days`. This plan adds it (it's cheap and useful) — a superset of the composite contract, not a conflict.
- **NON-BLOCKER — drawdown vote formula.** `main.py:694` writes `self._market_stress() * 0.12 >= self.gate_dd`; since `_market_stress = dd/0.12`, this is exactly `dd >= gate_dd`. The plan stores `spy_dd = stress*0.12` (the real drawdown) for provenance and votes on `dd >= 0.06`. Faithful.
