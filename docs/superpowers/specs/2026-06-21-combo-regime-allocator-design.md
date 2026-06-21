# COMBO — Regime-Conditioned Cross-Asset Allocator (Final Design Spec)

**Status:** Decided & empirically validated on QuantConnect Lean cloud (months of research converged). This document captures THE settled FINAL design. It is a SPEC (the WHAT and WHY, grounded in real files); the TDD execution plans are written separately, one per sprint, FROM this spec.

**Date:** 2026-06-21

**Supersedes:** `docs/superpowers/specs/2026-06-20-combo-regime-bands-design.md` (predated the regime-research results — frozen-composite design, no live gate, no gold haven). The 2026-06-20 plan files `docs/superpowers/plans/2026-06-20-combo-{1,2,3,4}-*.md` are stale and will be re-derived from this spec.

**Reference implementation (validated, port faithfully):** `E:/investintell-light/lean-research/TaaCvarSuite/main.py` (variant `COMBO`), final config below.

**Primary evidence:** `lean-research/regime_live_gate_findings.txt`, `lean-research/dd_lever_findings.txt`, `lean-research/u3_final_results.txt`, `lean-research/REGIME_MODEL_RESEARCH_BRIEF.md`. Accumulated changelog: `docs/superpowers/specs/2026-06-21-combo-spec-pending-updates.md`. Project memory: `taa-bands-combo-validation`.

---

## 1. Thesis & problem

We run a **regime-conditioned cross-asset allocator**: a market-regime signal sets per-asset-class bands (a loose envelope), and a min-CVaR optimizer allocates within them. Validated as the most robust all-weather construction (TAA bands beat 60/40 and CVaR-only on Sharpe in every valid window while cutting drawdown — `taarob_results.txt`, memory `taa-bands-combo-validation`). It had two unresolved weaknesses, and the research fixed both:

**Weakness 1 — the risk-off ENTRY signal is too weak (the central problem).** The in-product regime signal is the frozen `regime_composite_daily` (vote2of3 credit/trend/NFCI), whose change-points END 2020-06-01 → it is **stuck RISK-ON since 2020-06** and **missed the entire 2022 bear** (`REGIME_MODEL_RESEARCH_BRIEF.md` §1; reference change-points `main.py:181-188`). In a bear the allocator therefore gets little or no regime protection. This is NOT the legacy failure (the legacy system had the OPPOSITE problem — it over-stayed in risk-off, bleeding return). The goal is the optimum between the two: catch durable bears (2008/2020/2022) WITHOUT over-staying.

**Weakness 2 — recurring deep, structural drawdowns.** The strategy draws down ~32–39% in every major bear (GFC 38.8%, COVID 36.6%, 2022 32.0% — `REGIME_MODEL_RESEARCH_BRIEF.md` §2). Exhaustive mechanical DD levers (event-rebalance, per-security trailing stops + re-entry blocks, band-width sweeps, overlap look-through cap) were all tested and REFUTED as risk-adjusted wins (`dd_lever_findings.txt`, `regime_live_gate_findings.txt` ADENDOs 1–2). The structural ~33–39% bear DD of a long-only monthly equity-tilted book is reducible only by trading return for safety — a MANDATE dial, not a model fix. The exception is a *targeted, theory-grounded* haven for the one bear where it is addressable (2022; see §3).

The research question — does a regime-detection + portfolio-construction model exist that detects durable risk-off entries reliably without whipsaw/over-staying and delivers higher risk-adjusted return and lower bear drawdown than the baseline — is answered YES, by the FINAL config in §2.

## 2. The FINAL validated config (locked — do not re-litigate)

```
COMBO
  + vol_grad(vg_beta=1.5)
  + beta_grad(bg_coef=1.0)
  + gate=live(confirm=21, votes = trend / credit / drawdown)
  + slowdown_haven=goldfix(gld 0.30 / voov 0.20 / qai 0.20 / gcc 0.0 / bil 0.30)
```

Results vs the original baseline (U3; `regime_live_gate_findings.txt` ADENDO 8, `u3_final_results.txt` ADENDO 7):

| Window | Baseline Sharpe | FINAL Sharpe | FINAL MaxDD | FINAL 2022 DD | FINAL CAGR |
|---|---|---|---|---|---|
| Full 2008–2026 | 0.530 | **0.633** | 33.6% | ~18% | ~14.2% |
| Holdout 2017–2026 | 0.566 | **0.617** | 26.5% | 17.6% | ~14.1% |
| Train 2008–2017 | 0.524 | 0.704 | 33.6% | — | — |

2022 DD cut 31.7% → ~18%; GFC ~34% (was 38.8%); CAGR preserved (~14.2%). Defensible to an investment committee.

**In words.** A LIVE debounced regime gate sets per-asset-class bands (a loose envelope); a min-CVaR optimizer allocates within them; vol/beta-graduated overlays trim high-vol / high-beta names defensively as market stress rises; a gold-led (≤30%) haven REPLACES the bond sleeve ONLY in the SLOWDOWN quadrant (growth↓ + inflation↑, e.g. 2022, where bonds fell with equities). The growth axis stays COINCIDENT (SPY 126d) for v1; the leader+coincident composite is deferred to the worker (Phase 2, §7).

### 2.1 The mechanisms (each ported from `main.py`)

- **`DEFAULT_TAA_BANDS`** (`main.py:70-114`) — per-regime/class `center` + `half_width` table for `RISK_ON / RISK_OFF / INFLATION / CRISIS / STAGFLATION`. COMBO uses `RISK_ON / RISK_OFF / INFLATION` for the band states (plus the `STAG_GOLD` haven branch, §2.1 goldfix). The STAGFLATION band exists (a genuinely defensive real-asset state: equity 0.20 / FI 0.20 / alts 0.35 / cash 0.25) but the validated final config routes SLOWDOWN to the goldfix haven, NOT to STAGFLATION bands — STAGFLATION-as-bands was REFUTED on U3 (the alts class is REIT/BDC-heavy; `regime_live_gate_findings.txt` LEVER 1). The verbatim band table:

  | regime | equity (c/hw) | fixed_income | alternatives | cash |
  |---|---|---|---|---|
  | RISK_ON | 0.52 / 0.08 | 0.30 / 0.06 | 0.12 / 0.04 | 0.06 / 0.03 |
  | RISK_OFF | 0.38 / 0.08 | 0.36 / 0.06 | 0.13 / 0.04 | 0.13 / 0.05 |
  | INFLATION | 0.42 / 0.08 | 0.25 / 0.06 | 0.22 / 0.06 | 0.11 / 0.04 |
  | CRISIS | 0.25 / 0.06 | 0.35 / 0.06 | 0.15 / 0.05 | 0.25 / 0.08 |
  | STAGFLATION | 0.20 / 0.06 | 0.20 / 0.06 | 0.35 / 0.08 | 0.25 / 0.08 |

- **EMA smoothing + IPS clamp** (`smooth_regime_centers`, `main.py:270-285`; `compute_effective_band`, `main.py:252-267`; `_effective_class_bands`, `main.py:803-821`). Half-widths × `hw_scale=1.5` (KEY validated finding: WIDE bands generalize, tight bands overfit — `hw_sweep_results.txt`; memory `taa-bands-combo-validation`). `IPS_CLASS_BOUNDS` (`main.py:132-137`): equity (0,1), fixed_income (0,1), alternatives (0, 0.40), cash (0,1). EMA: `ema_halflife_days=5`, `max_daily_shift_pct=0.03`.

- **`_macro_quadrant`** (`main.py:710-739`) — growth × inflation clock → `RECOVERY / EXPANSION / SLOWDOWN / CONTRACTION`. Growth = SPY 126d return sign (`g_look=126`, COINCIDENT — v1 lock). Inflation-surprise = (TIP/IEF breakeven) 126d momentum sign (`i_look=126`): rising breakeven ⇒ inflation up.

- **`_combined_regime`** (`main.py:741-773`) — the band-state resolver. Stress gate dominates: if gate risk-off → `RISK_OFF` bands; else from the quadrant: `RECOVERY`→`RISK_ON`, `EXPANSION`→`INFLATION` (when `use_infl_bands=yes`), `SLOWDOWN`→`STAG_GOLD` (goldfix haven, the validated route), `CONTRACTION`→`RISK_OFF` (deflationary bust: bonds OK; `defensive_on=growth_down`).

- **The live gate `_live_gate_riskoff`** (`main.py:674-708`) — LIVE debounced 2-of-3 cross-asset risk-off vote with dwell-time hysteresis. Votes: (1) **trend** SPY < SMA200, (2) **credit** HYG/IEF < SMA60, (3) **drawdown** SPY 63d-drawdown ≥ `gate_dd=0.06` (the `_market_stress` proxy, `main.py:1026-1037`: SPY drawdown from trailing 63d high, 12% ⇒ full stress). Enter risk-off only after `votes>=2` holds `gate_confirm=21` consecutive days; exit only after `votes<2` holds 21 days. The 21d dwell-time debounce is the robust innovation the frozen composite LACKED.

- **`_haven_weights` / goldfix** (`main.py:950-985`) — the SLOWDOWN haven. min-CVaR over a curated whitelist degenerated to ~76% CASH (it prefers riskless cash to volatile gold; diagnosed in `regime_live_gate_findings.txt` ADENDO 5), so the owner's structural thesis (post-QE, gold replaces cash as flight-to-safety) must be IMPOSED as a fixed target. `goldfix` forces `target = {GLD: gld_w, VOOV: voov_w, QAI: qai_w, GCC: gcc_w, BIL: bil_w}`, kept to available names and renormalized. FINAL weights: **GLD 0.30 / VOOV 0.20 / QAI 0.20 / GCC 0.0 / BIL 0.30** (30% gold / 20% large value / 20% long-short / 30% cash; no position > 30%). Weights are CLI-tunable (conviction, not code).

- **Overlays.** `_vol_graduated_caps` (`main.py:1039-1061`): a continuous market-stress score shrinks each asset's cap in proportion to its EXCESS vol over the cross-sectional median (only above-median-vol names cut; value untouched), entering early and releasing fast on the rebound. `_beta_graduated_caps` (`main.py:1016-1024`) + `_asset_betas` (`main.py:998-1014`): in RISK_OFF, cap = base × (1 − bg_coef·max(0, β−0.3)) — routes away from high-beta-to-SPY names (cuts e.g. TLT in 2022 when its beta turned positive), keeping low-beta/cash/gold.

- **The min-CVaR objective** — Rockafellar–Uryasev LP/SOCP via cvxpy (`build_ru_cvar_objective`, `main.py:207-221`; deterministic single solver, `_solve_cvxpy`, `main.py:853-864`). The annual CVaR ceiling (`build_ru_cvar_constraints`, `main.py:224-238`) is the V4 path; COMBO uses the objective form.

- **Ragged universe / fixed window** — `_live_tickers` (`main.py:775-780`): only tickers with a FULL 1y window are optimizable (ragged ETF launch dates); `_scenario_matrix` (`main.py:782-795`): a fixed 252d (T,N) daily-return matrix over the live subset, so a freshly-launched fund can't shrink the covariance window for everyone.

### 2.2 Empirical justification — the journey (real numbers)

1. **Detection fixed by the 21d live gate.** The `gate_confirm` sweep (`regime_live_gate_findings.txt` LEVER 2): confirm {15,21,30} ALL beat baseline on the holdout (0.570–0.576 vs 0.566); confirm=21 is best holdout AND full (0.576 / 0.547 vs 0.530), turnover-neutral (1429 vs 1426 orders). confirm=10 over-stays (holdout 0.541); 15 whipsaws full (orders inflate to 1726 → reject). The detection trace (confirm=21, full) catches 2022 as a 315-day contiguous episode (2022-04-20 → 2023-03-01) the frozen composite MISSED, plus every post-2020 stress, with whipsaw limited to rare 0–6d blips (negligible at monthly rebalance). The live gate gives up ~0.006 on TRAIN (the frozen change-points ARE implicitly over-fit to 2008–2011 history) but GENERALISES better. Cross-universe (U2, confirm=21): holdout 0.633→0.636, full 0.596→0.608.

2. **2022 DD fixed by the gold haven.** Band-remap havens (`real`, `stagflation`) were REFUTED on U3 — they RAISE equity (INFLATION bands center equity 0.42) or route into FALLING REITs/BDCs (`regime_live_gate_findings.txt` LEVER 1). The fix (owner's idea, ADENDO 3): on SLOWDOWN route to a CURATED whitelist and let min-CVaR pick within it. Isolated routing effect (U3+GLD): 2022 DD 34.6% → 15.2% with gold+gate21, holdout Sharpe 0.547 → 0.586. But the diagnosis (ADENDO 5) showed min-CVaR's "gold" was ~76% CASH; forcing gold (`goldfix`) beat the cash-degenerate version on Sharpe (holdout 0.622 vs 0.585) while preserving CAGR — real assets capture return dead cash discards.

3. **Explainability cap is FREE.** A PM cannot defend 50–65% gold to an IC. Capping GLD at 30% + a 20% large-value (VOOV) anchor was DIAGNOSED as de-concentration that IMPROVED both Sharpe and DD (`u3_final_results.txt` ADENDO 7): pkgB (30g/20v/20ls/30cash) + gate ties the gold-heavy version on full Sharpe (0.633) AND improves full MaxDD (35.1% → 33.6%). 50–65% gold was over-concentration with small marginal protection above ~30%; large value (held in 2022) + cash give equal protection with far less concentration risk. The "fully quant" gold-heavy version was the inferior one. (pkgC's +10% GCC is marginally better, 0.638, but the ~0.005 comes entirely from the non-repeatable 2022 energy spike → pkgB is the clean choice. Pure gold without commodity, ADENDO 6, also ties — confirming the commodity leg is the least robust piece.)

4. **vol_grad fixed the U3 holdout collapse.** The U1/U2 config did NOT generalize to the representative U3 universe — the COMBO holdout collapsed to **0.088 / DD 54.7%** from concentration in high-vol equity sub-strategies (tech/growth). hw_scale sweeping did not resolve it. The fix (owner's idea — volatility-graduated, asymmetric defensive overlay): holdout **0.088 → 0.566**, DD 54.7% → 32.9%, CAGR 4.6% → 15.0% (`u3_final_results.txt`; memory `taa-bands-combo-validation`). vol_grad is for RICH universes only (on a 1-equity toy universe it has no vol dispersion to graduate and HURTS); production has a rich universe → ON.

5. **The growth-axis finding (why curve is worker territory).** A Lean test of growth = yield-curve T10Y2Y slope (LEADING) vs SPY 126d (COINCIDENT) showed neither dominates (`combo-spec-pending-updates.md` §"Growth-axis test"; `regime_live_gate_findings.txt` ADENDO 11): the curve LEADS (inverted 2006-07 before the GFC; cut GFC DD 33.6 → 28.3, full MaxDD 33.6 → 28.4) — anticipation the coincident SPY cannot give. But it OVER-STAYS (inverted 2022–2024 with no recession → defensive through the 2023-24 rally → full Sharpe 0.633 → 0.598, holdout 0.617 → 0.571) and is LATE for 2022 (a rates repricing, not a curve-predicted recession; curve inverted only mid-2022 after the drop → 2022 DD WORSENED 17.6 → 24.9). Verdict: coincident wins fast repricing bears (2022); leading wins slow recession bears (2008); the synthesis is leader+coincident COMBINED — Phase 2 worker territory (§7), NOT v1.

6. **What was REFUTED (do not re-test).** Per-security trailing stops (DD-only dial, train-only Sharpe gain that COLLAPSES OOS: holdout 0.367 vs 0.566 — `regime_live_gate_findings.txt` ADENDO 1); re-entry blocks (partial Sharpe rescue paid back in DD, slides along the same frontier — ADENDO 2); event-driven intra-month rebalance (whipsaw; COVID is a fast-V where de-risk sells the bottom — `dd_lever_findings.txt`); overlap look-through cap as a DD reducer (the big DDs were broad, not concentration-led — keep ONLY as a structural control); raw macro levels (NFCI>0, VIX>20, MANEMP/CFNAI level-cru) all SUBPERFORMED the price drawdown-proxy when implemented crudely on the node (ADENDOs 8–10).

## 3. Architecture across both repos

The design maps onto four components, each grounded in real, verified files. **Divergences from the pending-updates note are flagged inline.**

### 3.1 `regime_gate` worker (`E:/investintell-datalake-workers`)

**A NEW worker `src/workers/regime_gate.py`** (does not exist yet — the plan/sprint creates it), structured exactly like the existing `regime_composite` worker `src/workers/regime_composite.py`:

- **Pure engine (no I/O)** mirroring `regime_composite.py:50-144` — computes the daily 2-of-3 vote (trend SPY<SMA200, credit HYG/IEF<SMA60, drawdown SPY 63d-DD≥6%) and applies the 21d dwell-time debounce (port `_live_gate_riskoff`, `main.py:674-708`, and `_market_stress`, `main.py:1026-1037`). State machine over a full daily series → latched `state` + `dwell_days` + per-day flip flag.
- **I/O layer** mirroring `regime_composite.py:148-233`. Data sources (verified): SPY via Tiingo (`from src.workers._tiingo import TiingoClient`, `regime_composite.py:177`; `TiingoClient.fetch_daily_prices`, `_tiingo.py:104-139`). HYG/IEF: the credit leg can reuse `credit_regime_daily` (the `credit_regime` worker already materializes the HYG/IEF ratio + threshold — `regime_composite._fetch_credit_daily`, `regime_composite.py:160-172`, reads `SELECT regime_date, ratio, p20_5y FROM credit_regime_daily`). For the 60d SMA-crossover form the gate uses, either reuse that ratio or fetch HYG/IEF via Tiingo (decide in the plan; default = reuse `credit_regime_daily` ratio, no new dependency — see O1).
- **Full-history recompute, idempotent upsert** — `regime_composite` recomputes the entire series each run (adjusted closes change retroactively on dividends; `regime_composite.py:27-29`) and upserts via `INSERT ... ON CONFLICT (regime_date) DO UPDATE` in 1000-row chunks (`regime_composite.py:218-233`). `regime_gate` follows the same shape.
- **Advisory lock** — `from src.db import advisory_lock` (`src/db.py:29-44`); register a new lock id in the registry (`src/db.py:47-62`). **DIVERGENCE:** the pending-note guessed `900_208`; the verified next free id in the 900_2xx band is **`900_207`** (`LOCK_REGIME_COMPOSITE = 900_206` is the highest in that band). Use 900_207 (the plan confirms it is still free at execution time).
- **Schema/DDL** — a new `schemas/regime_gate.sql`, loaded idempotently by an `ensure_schema()` opening `schemas/regime_gate.sql` and executing it (pattern: `regime_composite.py:150-157`). **DIVERGENCE:** the pending-note implied a file named after the table; the actual convention names the file after the WORKER (`schemas/regime_composite.sql`, not `..._daily.sql`). Table **`regime_gate_daily`** columns (modeled on `regime_composite_daily`, whose CREATE TABLE is in `schemas/regime_composite.sql`): `regime_date date PK`, `state text` (`'risk_on' | 'risk_off'`), `trend_vote bool`, `credit_vote bool`, `drawdown_vote bool`, `vote_count smallint (0..3)`, `flip bool`, `dwell_days int`, provenance (e.g. `spy_dd numeric`, `hyg_ief_ratio numeric`), `computed_at timestamptz DEFAULT now()`, with CHECK constraints mirroring `regime_composite_daily`.
- **Worker registration** — `src/run.py` dispatches by dynamic import `src.workers.{worker}` (`src/run.py:26`) and `src/run_worker.py` by `WORKER=` env var; there is NO registry dict — the worker name must match the filename. So `python -m src.run regime_gate` (CLI) and `WORKER=regime_gate` (Railway) work once the file exists. **DIVERGENCE:** the pending-note's `src.run_worker WORKER=` / `python -m src.run` are both correct; just note dispatch is by-filename, not a table.
- **Railway cron** — a new service in `railway.toml` (`startCommand = "python -m src.run_worker"`, per-service `WORKER=regime_gate` + `DATABASE_URL` + cron). Schedule after `credit_regime`/`regime_composite` (e.g. ~06:50 UTC) so the credit leg is fresh.

**The `run(dsn, *, calc_date=None, limit=None) -> dict` entrypoint** matches `regime_composite.run` (`regime_composite.py:239-244`), returning `{days, upserted, state, vote_count, flips, last_flip, dwell_days, calc_date}`.

#### 3.1.1 PUSH on confirmed flip — the cross-repo reality (IMPORTANT divergence)

The pending-note says: "ON a confirmed state flip, the worker triggers the existing drift/rebalance evaluation (`materialize_all_portfolio_drifts`, bl-amplo sprint) → in-app rebalance alert (chosen over pg_notify/LISTEN or a new endpoint)." **Verified reality: `materialize_all_portfolio_drifts` is NOT in the data-lake workers repo — it lives in the BACKEND** (`E:/investintell-light/backend/app/services/portfolio_drift.py:475`), and is invoked by the BACKEND job `app/jobs/workers/portfolio_drift_daily.py` (`run(...)`, lines 76-108; advisory lock `900_042`, entrypoint `python -m app.jobs.workers.portfolio_drift_daily`). The data-lake `regime_gate` worker (separate repo, separate Railway service, its own `DATABASE_URL`) therefore **cannot call it in-process**.

The spec keeps the intent (regime change → drift re-eval → in-app alert, reusing the alert infra already built, NOT pg_notify/LISTEN and NOT a brand-new listener) but the mechanism must be one of (decide in the plan, recommended order):
  1. **(Recommended) The BACKEND drift job becomes flip-aware.** `regime_gate_daily.flip` is a queryable DB row in the same data-lake the backend already reads (the backend opens a read-only data-lake session — `portfolio_drift_daily._open_datalake`, lines 61-73). The backend `portfolio_drift_daily` worker (already scheduled daily) reads "did the gate flip since my last run?" from `regime_gate_daily` and, on a flip, runs `materialize_all_portfolio_drifts` (which it ALREADY calls — line 91) so drift statuses (and the existing in-app alert surfaced from `portfolio_drift_status`) refresh within a day. This reuses BOTH workers as-is and adds only a flip-read; no new service, no cross-repo call.
  2. The `regime_gate` worker writes the flip, and a lightweight backend trigger (the existing drift job run on a tighter post-flip schedule) picks it up. Same as (1) with a schedule nuance.
  3. (Rejected, per owner) pg_notify/LISTEN or a new API endpoint — new listener to operate.

A 21d-debounced signal flips rarely and a confirmed flip is a daily event, so "within a day" is ample (the gate is a Railway cron, not streaming — `livefeed` is price-only and would not fire it sooner; pending-note §"Live-gate WORKER architecture"). **The plan must wire the flip-read into `portfolio_drift_daily` (backend) — that is the real entrypoint, file `app/jobs/workers/portfolio_drift_daily.py`.**

### 3.2 Backend gate/bands service (`E:/investintell-light/backend`)

**A new pure module `app/services/taa_bands.py`** (does not exist yet) ports the band math from `main.py`: `DEFAULT_TAA_BANDS` (incl. STAGFLATION), `compute_effective_band`, `smooth_regime_centers`, `_macro_quadrant`, `_combined_regime`, `_effective_class_bands`, vol_grad/beta_grad cap logic, and the goldfix SLOWDOWN haven routing. It returns per-class `(min, max)`. `hw_scale` is a service constant `1.5`. The clamp targets the same per-class vocabulary as the persisted constraints (`ClassLimit`, verified at `app/services/portfolio_constraints.py:36`; ORM `PortfolioClassLimit`, `app/models/portfolio_constraint.py:78`) and the builder's `AssetClassFilter` (`app/schemas/builder.py:84` — `equity, fixed_income, cash, alternatives, multi_asset`).

**It consumes the gate, REPLACING the frozen composite read.** A new reader (analogous to `fetch_composite_regime`, `app/services/macro_regime.py:187`) reads `regime_gate_daily` latest state (+ votes/dwell) from the data-lake. The growth/inflation quadrant is computed by the backend from price proxies (SPY 126d, TIP/IEF breakeven 126d) OR materialized by the worker — decide in the plan (O2). The per-class `(min, max)` output is converted to `engine.BlockBudget` (§3.3).

**DIVERGENCE/clarification:** the pending-note frames the gate as "REPLACING the frozen `regime_composite_daily` read." Verified: the builder's CVaR-scaling regime read today is **credit-only** (`fetch_credit_regime`, called at `portfolio_builder.py:703`), NOT the composite. The macro PAGE route (`GET /macro/regime`) already reads the composite (`macro.py:43-47` → `fetch_composite_regime`). So the COMBO wire (a) introduces the gate as the BAND driver (new) and (b) switches the builder's CVaR-scaling read from credit-only → gate (`portfolio_builder.py:703`). The composite remains the macro-page detector unless the owner promotes the gate there too (O3).

### 3.3 Optimizer / builder wire (`E:/investintell-light/backend`)

**A new objective `"combo"`** added to `Objective` (`app/schemas/builder.py:65-68` — verified current literals end with `max_return_cvar`; `"combo"` is NEW, NOT yet present). In the optimize entrypoint `run_optimize` (`portfolio_builder.py:429`, `async def run_optimize(session, payload, datalake=None) -> OptimizeResponse`) the COMBO branch sits alongside the existing dispatch (`portfolio_builder.py:683` bl_utility / `:695` max_return_cvar / `:723` min_cvar+views / `:744` min_cvar):
  1. read the gate state + quadrant (§3.2 reader);
  2. call `taa_bands` → per-class `(min, max)`;
  3. convert to `engine.BlockBudget` rows — the engine already honors `blocks=`/`linear=` across EVERY objective (verified: `BlockBudget` `engine.py:235`, `LinearConstraint` `engine.py:250`, `BoundsBundle` `engine.py:346`; constructed in the builder by `_resolve_block_budgets` `portfolio_builder.py:237-282` and `_resolve_overlap_constraints` `:355-422`; passed via `BoundsBundle` built at `portfolio_builder.py:673` and threaded into `solve_min_cvar`/`solve_max_return_cvar_capped` at `:714`/`:745`);
  4. solve the min-CVaR objective inside that envelope;
  5. route the SLOWDOWN goldfix haven (when the quadrant is SLOWDOWN, the allocation is the fixed goldfix target over available names, bypassing the broad class bands — port `_haven_weights` goldfix branch, `main.py:959-972`);
  6. apply the vol_grad/beta_grad cap vectors (port `_vol_graduated_caps`/`_beta_graduated_caps`) as the per-asset cap inputs (the engine takes a cap; the COMBO branch supplies the graduated vector — the plan determines whether this rides `BoundsBundle.cap_vec`, verified field at `engine.py:353`).

**Switch the CVaR-scaling regime read** from `fetch_credit_regime` → the gate at `portfolio_builder.py:703` (the `state` field is compatible with `regime_cvar_multiplier`, `portfolio_builder.py:109`; note the existing `_OVERRIDE_REGIME_STATE` test hook at `:701`). Works in both explicit-list and broad-universe modes — broad applies bands over the selected representatives (the 2-stage selection: Stage-1 `optimizer_selection.*` clustering on pre-computed risk features `portfolio_builder.py:441-488`; Stage-2 pairwise/aligned covariance `:524-577`). The investable catalog expansion (§4) gives broad mode ~2× the candidates per class, making bands/overlap/low-beta easier to satisfy.

Request/response models verified: `OptimizeRequest` (`builder.py:189`), `OptimizeResponse` (`builder.py:310`), `ConstraintsIn` with `block_budgets`/`overlap_cap` (`builder.py:117-135`).

### 3.4 Macro page (frontend) (`E:/investintell-light/frontend`)

Drive the existing growth×inflation quadrant with the factors and show the live gate. Verified components: `src/components/macro/MacroRegimeView.tsx` (renders regime KPI tiles + RRG); the RRG builder `buildHcMacroRrgOption` in `src/lib/charts/hc/macro-rrg.ts` (a Relative Rotation Graph — quadrant plane); the API client `fetchMacroRegime` at `src/lib/api/client.ts:1424` returning the generated `MacroRegime` type (`client.ts:290-291`, generated from the OpenAPI schema — run `pnpm run types` after the backend response changes).

**The response must grow growth/inflation/quadrant + gate fields.** Verified: `MacroRegimeResponse` (`app/schemas/macro.py:39-57`) today exposes ONLY the vote2of3 detector (`detector, state, vote_count, votes{credit,trend,nfci}, signal, recent_flips, history`) — there is NO growth/inflation/quadrant block and NO gate block yet. The COMBO macro work adds: the current macro quadrant (+ growth/inflation scores), the live gate state (+ trend/credit/drawdown votes + dwell_days), and the resulting per-class bands + the haven tilt (when SLOWDOWN). The page shows quadrant + gate + bands, reusing the band-visualization pattern (the drift-bands chart `buildHcDriftBandsOption` and the class enumeration in `PortfolioConstraintsSection.tsx`). **DIVERGENCE:** the pending/2026-06-20 note implied the route already exposes growth×inflation; it does NOT — that block is new.

## 4. Investable catalog

The fund-catalog gates were loosened: investable instruments **~4.5k → ~8.6k** (`combo-spec-pending-updates.md` §"Fund catalog universe expanded"; cross-ref memory `fund-catalog-production-sync` and `catalog-coverage-gap`). Implication: the broad-universe optimizer has ~2× the candidates, so per-asset-class bands, the overlap/look-through cap, and finding genuinely low-beta / haven assets (gold, large value, long-short, cash) are all EASIER to satisfy (more names per class/strategy). The universe-selection section of the plan should reflect the new gate counts.

## 5. Honest caveats (carry into the plans)

- **The gold-haven DD win is n=1 (2022).** It is a STRUCTURAL CONVICTION position (gold as a monetary hedge post-QE/M2), NOT calibrated alpha; the SLOWDOWN gate fires essentially once in the modern sample (the only clean stagflation 2008–2026). Evidence is mechanism-driven + cross-universe-consistent, not cross-episode statistical (`regime_live_gate_findings.txt` ADENDOs 3, 5–7). Size as CLI-tunable conviction (gld_w/voov_w/qai_w/gcc_w/bil_w); monitor the quadrant's inflationary-vs-deflationary classification in production — gold can have real DD (e.g. a real-rate shock like 2013), whereas cash never falls. Gold-haven is CONFINED to SLOWDOWN; deflationary crunches (CONTRACTION/CRISIS, e.g. COVID Mar-2020 where gold fell ~12%) still route to bonds/cash.
- **COVID-class fast-V DD remains ~structural** (137d catch with a fast-V lag; `regime_live_gate_findings.txt` detection trace). A long-only monthly book cannot avoid it; the Sharpe gain is on detection-quality, not on cutting the fast-V bear DD.
- **Long-only, monthly book.** Intra-month action only on a durable, debounced signal (raw immediate action whipsaws — proven). The structural ~33–39% bear DD is reducible only by strategic conservatism (a MANDATE dial), not a model fix.
- **Macro signals deferred** (§7) — the validated config is price-based (trend/credit/drawdown + SPY-growth); rich macro signals (NFCI/VIX/PMI/curve) did not beat it crudely on the node and need their own rule + clean data in the worker.
- **Single asset-era backtest 2008–2026**; band CENTERS and `i_look` were NOT swept (only `hw_scale`); the inflation proxy (TIP/IEF breakeven) is a modeling choice; COMBO has higher turnover (informational in the point-in-time builder).

## 6. MACRO-SIGNAL backlog (Phase 2 — worker-only, explicitly DEFERRED, NOT v1)

All deferred to the worker, where the product's clean data pipeline + the right rule can be tried; none is in v1 (raw forms all lost to the price drawdown-proxy on the node — `regime_live_gate_findings.txt` ADENDOs 8–11):

- **NFCI relative/rising as a 4th vote** (NFCI + drawdown, NOT a substitute) — use a relative/rising rule (vs its own MA) or continuous input, never the raw level (raw NFCI>0 underperformed and blew full MaxDD to 45.6%).
- **VIX term-structure** (VIX/VIX3M) with full coverage — not raw level (VIXCLS froze 2024-06 on the node; raw >20 underperformed).
- **Real ISM PMI** on the SLOWDOWN growth axis (oscillates ~50; could sharpen gold-haven routing) — ISM is redistribution-restricted on QC; needs the product pipeline. MANEMP/CFNAI level-cru over-stayed (secular decline, not contraction); CFNAI's right rule is the 3-month MA vs −0.7.
- **The leader+coincident growth COMPOSITE** (yield curve T10Y2Y to anticipate recession + SPY momentum to catch repricing, with an adjustable lead) — build with the RIGHT series **USPHCI / ISM via the product's data pipeline** (they don't provision clean on the QC node) and **NEVER USREC** (NBER recession flag = look-ahead bias, published with long lag/revisions).

**Promotion bar (all backlog signals):** a signal is promoted ONLY if it beats the coincident / drawdown-proxy baseline OUT-OF-SAMPLE while keeping the 21d debounce + the pkgB goldfix haven.

## 7. Suggested sprint decomposition (frame for the plan agent — do NOT expand here)

Four sprints, in dependency order (each builds on the prior):

1. **`regime_gate` worker** (`E:/investintell-datalake-workers`) — new worker + `regime_gate_daily` table + 21d-debounced 2-of-3 vote + the backend drift-job flip-read (§3.1, §3.1.1).
2. **Backend gate/bands service** (`app/services/taa_bands.py`) — port the band math + STAGFLATION + EMA/IPS/hw_scale + quadrant + goldfix haven + vol/beta overlays; the `regime_gate_daily` reader (§3.2).
3. **Optimizer/builder wire** — the `"combo"` objective consuming gate-driven bands as BlockBudgets + goldfix routing; switch the CVaR-scaling read credit-only → gate (§3.3).
4. **Macro page** — quadrant + live-gate state + resulting bands + haven tilt; the new `MacroRegimeResponse` fields + `pnpm run types` (§3.4).

## 8. Self-review

**Assumptions.**
- The gate's credit leg can reuse `credit_regime_daily.ratio` rather than re-fetching HYG/IEF (the `credit_regime` worker already materializes it). If the gate's exact SMA60-crossover form needs raw HYG/IEF closes, the worker fetches them via Tiingo (O1).
- `BlockBudget`/`LinearConstraint`/`BoundsBundle` honoring every objective (verified `engine.py:235/250/346` + builder threading) means `"combo"` needs no new engine primitive — it reuses the min-CVaR solver inside bands. If the vol/beta graduated caps need a per-asset cap VECTOR, `BoundsBundle.cap_vec` (`engine.py:353`) is the vehicle.
- The backend already opens a read-only data-lake session in the drift job (`portfolio_drift_daily._open_datalake`), so reading `regime_gate_daily` from the backend is a known pattern (no new connection plumbing).

**Risks / what could go wrong.**
- **Cross-repo PUSH**: the biggest reality-vs-note gap. The flip → drift trigger must be a DB-row read by the backend drift job, not an in-process call from the worker repo. If the plan tries a direct call it will fail (separate processes/DSNs). §3.1.1 option (1) is the safe path.
- **Lock-id collision**: 900_207 is free TODAY in the 900_2xx band but the working tree is shared; the plan must re-confirm at execution time.
- **Quadrant data source**: computing the quadrant in the backend (SPY/TIP/IEF proxies) vs materializing it in the worker is unsettled (O2); the band output depends on it.
- **Macro response shape change** breaks the generated frontend types until `pnpm run types` runs; the plan must sequence it.
- **goldfix conviction**: if a future stagflation is deflationary-misclassified, forced gold hurts where cash would not. Mitigated by SLOWDOWN-confinement + CLI-tunable weights + production monitoring, but it is a real n=1 bet.

**Open questions for the owner.**
- **O1**: Gate credit leg — reuse `credit_regime_daily.ratio` (no new dependency) vs fetch HYG/IEF via Tiingo for the exact SMA60-crossover form? (Plan default: reuse.) **→ RESOLVED in §9.**
- **O2**: Compute the growth×inflation quadrant in the backend service (price proxies) vs materialize it in the `regime_gate` worker (or a sibling) for a single source of truth on the Macro page? (Plan default: backend computes from proxies, matching `main.py`.) **→ RESOLVED in §9.**
- **O3**: Should the gate also REPLACE the composite as the Macro-page detector (`GET /macro/regime`), or only drive the bands + CVaR scaling while the composite stays the page's headline detector? (Plan default: gate drives bands + scaling; composite stays the page detector; surface the gate as an added block.)
- **O4**: Persist `"combo"` per-portfolio (a mode in `portfolio_constraints`) vs ad-hoc builder objective only? (Plan default: ad-hoc objective first, YAGNI; persistence deferred.)
- **O5**: `multi_asset` representatives have no band class in the 4-class table — leave unbounded (no block budget) vs map to equity/fixed_income? (Plan default: unbounded, documented — matches the 2026-06-20 open question O3.)
- **O6**: The drift-job flip-read cadence — keep the daily `portfolio_drift_daily` schedule (alert within a day of a confirmed flip) vs add a tighter post-flip run? (Plan default: daily is ample for a 21d-debounced signal.)

## 9. Resolved decisions (2026-06-21, post-plan bias-check)

After the four TDD plans were drafted, a verification pass found the original O1/O2 defaults would silently break the validated design. These three decisions are now settled and the plans were revised in place to match.

**Decision A — the `regime_gate` worker is SELF-CONTAINED and ALSO materializes the growth/inflation quadrant (supersedes the O1 reuse default AND the O2 backend-compute default).** The worker fetches **SPY, HYG, IEF, TIP** via Tiingo (the exact `credit_regime._fetch_prices` pattern — `TiingoClient()` context manager + `fetch_daily_prices(ticker, HISTORY_START, calc_date)` per ticker; verified `src/workers/_tiingo.py:104-139`, `credit_regime.py:224-240`). The credit vote is the VALIDATED rule **HYG/IEF < SMA60**, with SMA60 computed from the raw HYG/IEF closes the worker fetches — NOT reused from `credit_regime_daily.ratio` (that worker's vote is `ratio < p20_5y`, a different rule; reusing it would break fidelity to the backtest). The worker also computes the **growth score** (SPY 126d return), the **inflation score** ((TIP/IEF breakeven) 126d momentum), and the **quadrant** via the `_macro_quadrant` mapping (`main.py:710-739`), and materializes `growth_score`/`inflation_score`/`quadrant` into `regime_gate_daily` alongside the gate. **Reasons:** (1) the backend cannot compute the quadrant — TIP/IEF are NOT in `eod_prices` (verified); the original O2 default was infeasible. (2) Degrading the quadrant to `None` (gate-only) silently DROPS the SLOWDOWN→goldfix haven — THE mechanism that cut 2022 DD 31.7%→~18% (§2.2 item 2), i.e. the model's headline result. (3) The worker is off the request path (a Railway cron), so the 4-ticker fetch carries no serving-latency cost (unlike a synchronous backend Tiingo fetch). (4) Materializing the quadrant in the worker gives a SINGLE SOURCE OF TRUTH consumed identically by the bands service (§3.2), the builder (§3.3), and the Macro page (§3.4) — no duplicated `_macro_quadrant` math in the backend. The backend `taa_bands` service therefore READS `growth_score`/`inflation_score`/`quadrant` from `regime_gate_daily` and keeps only the band/EMA/IPS/hw_scale/goldfix/vol-beta logic; `_combined_regime` consumes the READ quadrant (gate-stress dominates; else quadrant → bands/haven incl. SLOWDOWN→goldfix). The SLOWDOWN→goldfix routing is ACTIVE in v1, not deferred.

**Decision B — the COMBO inner objective is `min_cvar` (fidelity to the Lean harness).** The validated harness MINIMIZES CVaR inside the regime envelope (`build_ru_cvar_objective`, `main.py:207-221`); `max_return_cvar` is a different optimization (maximize return s.t. a CVaR ceiling) and would not reproduce the validated results. The `"combo"` dispatch (§3.3) calls `engine.solve_min_cvar` (verified to exist at `engine.py:820` and to honor `bounds=BoundsBundle` + `blocks` + `linear`; the builder already calls it at `portfolio_builder.py:227/732/745`) within the gate-driven `BlockBudget` envelope, with goldfix routing and graduated caps. This is the decided inner objective — the earlier `max_return_cvar` default and the "flagged for owner" ambiguity are removed.

**Decision C — the drift-job flip-read stays OBSERVATIONAL in v1.** The backend `portfolio_drift_daily` job (§3.1.1) keeps its daily schedule and its already-unconditional `materialize_all_portfolio_drifts` call; it reads the latest `regime_gate_daily.flip` and surfaces it as context on the drift/alert (so a rebalance is explained as regime-driven). No cursor table, no conditional materialize, no tighter schedule in v1 (confirms O6). Wording: "observational v1 (surface flip context; materialize stays daily/unconditional)."
