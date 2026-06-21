> SUPERSEDED by docs/superpowers/specs/2026-06-21-combo-regime-allocator-design.md

# COMBO — Regime-Conditioned Cross-Asset Bands (Design Spec)

**Status:** Decided & empirically validated on QuantConnect Lean cloud. This document captures THE settled design; it is not an open brainstorm.

**Date:** 2026-06-20

**Reference implementation (validated, port faithfully):** `E:/investintell-light/lean-research/TaaCvarSuite/main.py` (variant `COMBO`).

**Validation evidence:** `lean-research/hw_sweep_results.txt`, `lean-research/macro_vs_bands_results.txt`, `lean-research/taarob_results.txt`.

---

## 1. Investment thesis

The optimizer today lets the CVaR engine pick weights subject only to a per-asset cap and (optionally) per-class block budgets the user types in. There is no regime awareness in the *allocation envelope* — the only regime input is a credit-only gate that tightens the CVaR ceiling in risk-off (`portfolio_builder.regime_cvar_multiplier`, `backend/app/services/portfolio_builder.py:109`).

COMBO adds a regime-conditioned *envelope*: for each asset class it sets a loose `(min, max)` band that the existing CVaR optimizer fills. The band's regime is driven by BOTH the in-product risk-on/off composite (`regime_composite_daily`, vote2of3 credit/trend/NFCI) AND a new growth×inflation macro quadrant. The composite catches stress; the quadrant catches the growth/inflation rotation the composite is blind to. The envelope is deliberately WIDE — the regime nudges the center of gravity, CVaR does the fine optimization inside.

The validated reading is that this is the most *robust* all-weather configuration: it is rarely the single best in any one window, but it has the best worst-case and never collapses (see §3).

## 2. The definitive validated config (do not re-litigate)

Regime for the bands = composite-stress gate OR macro-quadrant overlay (`_combined_regime`, `main.py:528`):

- if composite == `RISK_OFF` → use `RISK_OFF` bands (composite stress dominates).
- else (composite risk_on), from the macro quadrant (`_macro_quadrant`, `main.py:503`):
  - `RECOVERY` (growth up, inflation down) → `RISK_ON` bands
  - `EXPANSION` (growth up, inflation up) → `INFLATION` bands (real-asset tilt) when `use_infl_bands=yes`
  - `SLOWDOWN` (growth down, inflation up) → `RISK_OFF` bands (stagflation defensive)
  - `CONTRACTION` (growth down, inflation down) → `RISK_OFF` bands when `defensive_on=growth_down`

Signals (factor-mimicking from tradable proxies, `main.py:503-526`):

- Growth = SPY 126-trading-day return sign (`g_look=126`). `> 0` ⇒ growth up.
- Inflation-surprise = (TIP/IEF breakeven) 126-day momentum sign (`i_look=126`): `(TIP 126d return − IEF 126d return) > 0` ⇒ inflation up.

Bands (`DEFAULT_TAA_BANDS`, `main.py:70-103`; `_effective_class_bands`, `main.py:574`):

- A per-regime/class table of `center` and `half_width`.
- Centers are EMA-smoothed (`smooth_regime_centers`, `main.py:234`; `ema_halflife_days=5`, `max_daily_shift_pct=0.03`).
- Half-widths multiplied by `hw_scale=1.5` (KEY validated finding: WIDE bands generalize; tight bands overfit — see §3).
- Then clamped to IPS hard bounds per class (`compute_effective_band`, `main.py:216`; `IPS_CLASS_BOUNDS`, `main.py:121`) → per-class `(min, max)`.
- Fed to the optimizer as block-budget constraints (per-class Σw ∈ [min, max]).

Asset classes: `equity`, `fixed_income`, `alternatives`, `cash`. (The light optimizer vocabulary also includes `multi_asset`, `backend/app/schemas/builder.py:84`; COMBO maps `multi_asset` representatives to the closest band class or leaves them unbounded — see §6 open question O3.)

The `DEFAULT_TAA_BANDS` table verbatim from the validated reference:

| regime | equity (c/hw) | fixed_income | alternatives | cash |
|---|---|---|---|---|
| RISK_ON | 0.52 / 0.08 | 0.30 / 0.06 | 0.12 / 0.04 | 0.06 / 0.03 |
| RISK_OFF | 0.38 / 0.08 | 0.36 / 0.06 | 0.13 / 0.04 | 0.13 / 0.05 |
| INFLATION | 0.42 / 0.08 | 0.25 / 0.06 | 0.22 / 0.06 | 0.11 / 0.04 |
| CRISIS | 0.25 / 0.06 | 0.35 / 0.06 | 0.15 / 0.05 | 0.25 / 0.08 |

`IPS_CLASS_BOUNDS`: equity (0, 1), fixed_income (0, 1), alternatives (0, 0.40), cash (0, 1).

COMBO uses only `RISK_ON / RISK_OFF / INFLATION` (never `CRISIS`; the composite gate replaces the price-classifier CRISIS state). `hw_scale=1.5` applied to every half-width.

The product's regime signal for the composite gate is `regime_composite_daily` (read today via `macro_regime.fetch_composite_regime`, `backend/app/services/macro_regime.py:187`). The builder currently uses credit-only (`fetch_credit_regime`, `portfolio_builder.py:703`) for CVaR scaling — COMBO switches the band gate (and the CVaR scaling) to the composite.

## 3. Empirical justification (validated numbers)

From `hw_sweep_results.txt` (COMBO with `g_look=126, defensive_on=growth_down, use_infl_bands=yes`; cell = Sharpe/MaxDD, worst & mean over windows):

| hw_scale | Train 08-17 | Hold 17-26 | Full 08-26 | U2 full | worst | mean |
|---|---|---|---|---|---|---|
| 0.5x | 0.607/19% | 0.000/0% | 0.533/24% | 0.605/23% | 0.000 | 0.436 |
| 0.75x | 0.682/18% | 0.050/10% | 0.519/26% | 0.625/21% | 0.050 | 0.469 |
| 1.0x | 0.611/18% | 0.432/22% | 0.507/22% | 0.588/22% | 0.432 | 0.534 |
| **1.5x** | 0.503/16% | **0.527/16%** | 0.509/16% | **0.614/19%** | **0.503** | **0.538** |
| 2.0x | 0.507/15% | 0.528/18% | 0.512/18% | 0.604/20% | 0.507 | 0.538 |

Findings (quoted from the sweep verdict): tight bands (0.5x/0.75x) are FRAGILE — great in train (0.607/0.682) but COLLAPSE out-of-sample (holdout 0.000/0.050), the regime centers dominate and the model gets stuck defensive in the bull. Wide bands (1.5x/2.0x) are robust winners: best worst-case Sharpe (0.503 vs 0.432 base), best mean (0.538), and dramatically lower, more consistent drawdown (~16-18% across all windows vs 22% at base). The gain generalizes across train + holdout + full + U2. Interpretation: the regime overlay should be a LOOSE envelope; let CVaR drive risk within it. **Final config: `hw_scale=1.5`** → Full 0.509/16% | Holdout 0.527/16% | U2 0.614/19% | worst-case 0.503.

From `macro_vs_bands_results.txt` (head-to-head COMBO vs alternatives): COMBO does NOT beat V2/composite on Sharpe in benign cells (0.507 vs 0.538 full; 0.611 vs 0.646 early; 0.588 vs 0.614 U2) — the overlay costs a little there. COMBO WINS where it matters: LATE 2017-2026 bull it is the best tactical by far (0.432 vs V2_proxy 0.35, MACRO 0.318) and recovers CAGR (9.34% vs 7.6-7.9%) keeping DD lowest (22.5%). It is the most ROBUST: best worst-case Sharpe of all tactical variants; never collapses. COMBO also avoided the V2/composite 2017 no-trade anomaly (160 orders, clean). Cost: higher turnover (377 orders full vs ~109 for V2/composite).

From `taarob_results.txt` (validates the composite as band driver): TAA-bands (V2) beat naive 60/40 (V0) and CVaR-only (V1) on Sharpe in EVERY valid period and BOTH universes while cutting drawdown vs V0. The in-product macro composite is the best band driver (composite 0.538 vs proxy_bin 0.489 full; 0.646 vs 0.556 early; top on U2 0.614 vs proxy 0.599) — this validates wiring `regime_composite_daily`.

## 4. Architecture — mapping to real files

The design maps onto four components, each grounded in existing code.

### 4.1 Data-lake worker (repo `E:/investintell-datalake-workers`)

A new `macro_factor_daily` worker, structured exactly like `src/workers/regime_composite.py`: a pure engine (no I/O) computing the growth/inflation states and quadrant, an I/O layer that reads price series and upserts rows, and a `run(dsn, *, calc_date=None, limit=None) -> dict` entrypoint guarded by a postgres advisory lock (`src/db.py:29` `advisory_lock`, lock id registered in `src/db.py:47-62`). DDL in `schemas/macro_factor_daily.sql`, loaded idempotently by `ensure_schema()`. Persists daily rows: `date, growth_state, inflation_state, growth_score, inflation_score, quadrant` (plus provenance).

Data source decision (verified against the lake, Tiger service `t83f4np6x4`): `eod_prices(ticker, date, adj_close, …)` holds SPY back to 1993 (8404 rows) but does NOT contain TIP or IEF. The worker therefore fetches SPY, TIP and IEF via Tiingo (`src/workers/_tiingo.py` `TiingoClient.fetch_daily_prices`), exactly as `regime_composite._fetch_spy` does for SPY (`regime_composite.py:175`). This avoids depending on an ingest that does not exist yet. (Alternative: extend `benchmark_ingest` to land TIP/IEF in `eod_prices`; deferred — see §6 O1.)

Scheduled daily via a Railway service (`railway.toml`), targeting ~06:50 UTC (after `credit_regime`/`regime_composite` 06:30-06:45, before `risk_metrics` 07:00). `python -m src.run macro_factor_daily` (CLI) / `python -m src.run_worker` with `WORKER=macro_factor_daily` (Railway).

### 4.2 Backend service — regime → per-class bands (repo `E:/investintell-light/backend`)

A new pure module `app/services/taa_bands.py` ports `DEFAULT_TAA_BANDS`, `compute_effective_band`, `smooth_regime_centers`, the macro quadrant logic and `_combined_regime`/`_effective_class_bands`. It consumes the composite snapshot (`macro_regime.fetch_composite_regime`, `macro_regime.py:187`) and the new `macro_factor_daily` quadrant (read via a small reader analogous to the composite reader) and returns per-class `(min, max)`. The clamp targets the same per-class semantics as `portfolio_constraints` (`ClassLimit`, `portfolio_constraints.py:36`) and the same vocabulary (`builder.py:84`). `hw_scale` is a service constant `1.5`.

### 4.3 Optimizer/builder wire

A new objective `"combo"` in `Objective` (`builder.py:65`). In `portfolio_builder.run_optimize` (`portfolio_builder.py`), the COMBO branch (a) reads the composite + quadrant, (b) calls `taa_bands` to get per-class `(min, max)`, (c) converts them to `engine.BlockBudget` rows (the engine already honors `blocks=`/`linear=` across all solvers — `BlockBudget` `engine.py:234`, `BoundsBundle` `engine.py:345`), and (d) solves the CVaR objective inside that envelope. It also switches the CVaR-scaling regime read from `fetch_credit_regime` to `fetch_composite_regime` (the `state` field is compatible with `regime_cvar_multiplier`, `portfolio_builder.py:109`). Works in both explicit and broad-universe modes (broad applies bands over the selected representatives).

### 4.4 Macro page (frontend)

The existing `MacroRegimeView` (`frontend/src/components/macro/MacroRegimeView.tsx`) renders the growth×inflation quadrant via `buildHcMacroRrgOption` (`frontend/src/lib/charts/hc/macro-rrg.ts`), today fed by the risk-on/off ensemble signals (credit/trend/conditions). COMBO drives the quadrant from the new growth/inflation factors: the backend `/macro/regime` response (`MacroRegimeResponse`, `app/api/routes/macro.py:42`) gains a `macro_quadrant` block (current quadrant + growth/inflation scores + the resulting per-class bands), surfaced to the client via `fetchMacroRegime` (`frontend/src/lib/api/client.ts:1423`) after `pnpm run types`. The page shows the current quadrant and the resulting bands (reusing the band-visualization pattern from `rebalance.ts` `buildHcDriftBandsOption` and the class enumeration in `PortfolioConstraintsSection.tsx`).

## 5. The four components (deliverable plans)

1. **Worker** — `macro_factor_daily` in `E:/investintell-datalake-workers`. Plan: `2026-06-20-combo-1-worker-macro-factor.md`.
2. **Service** — `app/services/taa_bands.py` (band math + readers). Plan: `2026-06-20-combo-2-service-taa-bands.md`.
3. **Optimizer/builder wire** — `"combo"` objective + composite switch. Plan: `2026-06-20-combo-3-builder-wire.md`.
4. **Macro page** — quadrant + bands UI. Plan: `2026-06-20-combo-4-macro-page.md`.

Execution order: worker → service → builder wire → macro page (each builds on the prior).

## 6. Decisions & open questions

Decisions (settled):

- Bands are a LOOSE envelope; `hw_scale=1.5` (validated §3). Centers/`i_look` not swept — keep as in the reference.
- Band gate = composite OR quadrant overlay, composite stress dominates (`_combined_regime`, `main.py:528`). `defensive_on=growth_down`, `use_infl_bands=yes`.
- Inflation proxy = TIP/IEF breakeven momentum (a deliberate choice, not the only one).
- Worker fetches TIP/IEF/SPY from Tiingo (TIP/IEF absent from `eod_prices`).
- CVaR-scaling regime read switches credit-only → composite.

Open questions (need owner input; flagged in the plans, not blockers):

- **O1:** Persist TIP/IEF into `eod_prices` (via `benchmark_ingest`) vs. always Tiingo-fetch in the worker. Plan assumes Tiingo-fetch (no new dependency).
- **O2:** Should COMBO be selectable per-portfolio (persisted in `portfolio_constraints` as a mode) or only an ad-hoc builder objective? Plan does the ad-hoc objective first (YAGNI); persistence deferred.
- **O3:** `multi_asset` representatives have no band class in the 4-class table. Plan leaves `multi_asset` unbounded (no block budget) and documents it; owner may prefer mapping to `equity`/`fixed_income`.
- **O4:** Turnover/cost — COMBO has higher turnover (377 vs ~109 orders). The builder is point-in-time (no rebalancing engine here) so this is informational; revisit if/when a scheduled rebalancer consumes COMBO.

## 7. Known caveats (carry into the plans)

- Single asset-era backtest 2008–2026 (one regime history); validation is not multi-decade.
- Band CENTERS and `i_look` were NOT swept — only `hw_scale` was; the centers are the legacy `DEFAULT_TAA_BANDS`.
- Inflation proxy is a modeling choice (TIP/IEF breakeven); a CPI-surprise series would differ.
- The 2017 no-trade anomaly was V2/composite-only; COMBO avoided it (160 orders, clean) — but it shows the composite signal can start constant at a window edge.
- Higher turnover than V2/composite (cost not modeled in the point-in-time builder).

## 8. Self-review vs the goal

- Regime gate (composite OR quadrant overlay) → §2, ported in plans 2 & 3.
- Growth (SPY 126d) and inflation-surprise (TIP/IEF breakeven 126d) signals → §2/§4.1, plan 1 (worker) + plan 2 (reader).
- `DEFAULT_TAA_BANDS`, EMA smoothing, `hw_scale=1.5`, IPS clamp → §2, plan 2.
- BlockBudget feed to CVaR optimizer → §4.3, plan 3 (engine already supports it, `engine.py:234`).
- Switch credit-only → composite for CVaR scaling → §4.3, plan 3.
- Persist daily analogous to `regime_composite_daily` → §4.1, plan 1.
- Macro page driven by new factors + show quadrant & bands → §4.4, plan 4.
- Empirical justification quoted (sweep numbers) → §3.
- Caveats honestly stated → §6/§7.

Gap check: every settled config element from the prompt maps to a plan task. The only unsettled items are O1-O4, explicitly flagged as owner decisions with a default chosen so the plans remain executable.
