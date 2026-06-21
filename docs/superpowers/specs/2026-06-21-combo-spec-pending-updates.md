# COMBO spec — pending updates (changelog to fold into the spec rewrite)

> The original spec/plans `2026-06-20-combo-*` predate the regime-research results.
> When the research converges, the spec must be rewritten to the FINAL model. This
> file is the accumulating delta to incorporate. Full evidence in
> `lean-research/{regime_live_gate_findings,dd_lever_findings,u3_final_results}.txt`
> and memory `taa-bands-combo-validation`.

## 2026-06-21 — Fund catalog universe expanded
- Owner loosened the fund-catalog gates: investable instruments **4.5k → 8.6k**.
- Implication for the spec: the broad-universe optimizer has ~2× the candidates, so
  per-asset-class bands, the overlap/look-through cap, and finding genuinely low-beta /
  haven assets are all EASIER to satisfy (more names per class/strategy). The spec's
  universe-selection section should reflect the new gate counts. (Cross-ref memory
  `fund-catalog-production-sync`.)

## Final-model deltas vs the original COMBO spec (validated in research)
- **Regime detector = LIVE gate** replacing the frozen `regime_composite_daily`
  change-points: 2-of-3 cross-asset risk-off vote (SPY<SMA200, HYG/IEF<SMA60,
  SPY 63d-drawdown≥6%) with dwell-time hysteresis (`confirm≈21d`). Catches 2022 +
  all post-2020 stress the frozen composite missed; improves Sharpe OOS on both
  universes without over-staying. → needs a data-lake worker materializing this live
  gate (the frozen composite is stuck RISK-ON since 2020-06-01).
- **slowdown_haven (gold, regime-conditioned)**: in the SLOWDOWN quadrant (growth↓ +
  inflation↑, e.g. 2022) route the defensive sleeve to a gold-led haven, NOT bonds
  (bonds fell with equities in 2022). Confined to SLOWDOWN; CONTRACTION/CRISIS still
  route to bonds/cash (handles the deflationary liquidity-crunch where gold also falls,
  e.g. Mar-2020). Cut 2022 DD 31.7%→~18%, lifted full Sharpe 0.530→0.633.
  - **FINAL haven config (2026-06-21, validated): goldfix with**
    `gld_w=0.30, voov_w=0.20, qai_w=0.20, gcc_w=0.0, bil_w=0.30`
    = 30% gold / 20% large value / 20% long-short / 30% cash (NO position > 30%).
    Capping gold at 30% + a 20% large-value anchor did NOT cost Sharpe/DD — it IMPROVED
    both (full Sharpe 0.633 tied the gold-heavy version; full MaxDD 35.1%->33.6%).
    Diagnosis: 50-65% gold was OVER-CONCENTRATION; gold's marginal protection above ~30%
    is small, and large value (held in 2022) + cash give equal protection with far less
    concentration risk. The "fully quant" gold-heavy version was the inferior one. Weights
    CLI-tunable (gld_w/voov_w/qai_w/gcc_w/bil_w) — conviction adjustable without code.
  - vs original baseline: full Sharpe 0.530->0.633, holdout 0.566->0.617, 2022 DD ~18%,
    GFC ~34%, CAGR preserved (~14.2%). Defensible to an investment committee.
- **Overlays**: vol_grad (1.5) and beta_grad (1.0, low-beta defensive routing) — modest
  net-positive; keep. Overlap look-through cap = structural control (not a DD reducer).
- **Cadence**: monthly (drift) + the live gate provides the regime response; raw
  intra-month event-rebalance was REFUTED (whipsaw). Per-security stops REFUTED.
- **Honest caveat for the spec**: the gold-haven DD win rests on n=1 inflationary bear
  (2022); it is a structural conviction position (gold as monetary hedge post-QE), not
  calibrated alpha. Size as conviction (CLI-tunable weights), monitor the quadrant's
  inflationary-vs-deflationary classification in production.

## 2026-06-21 — Live-gate WORKER architecture (Plan 1) + macro-signal backlog

**The live gate is a Railway CRON WORKER in `E:/investintell-datalake-workers`, NOT streaming.**
Rationale: the gate's signals are DAILY (SPY<SMA200, HYG/IEF<SMA60, SPY 63d-drawdown≥6%)
with a 21-day dwell debounce → the *confirmed* flip is a daily event; real-time/livefeed
would not make it fire sooner, and acting intra-day on unconfirmed signals is the exact
whipsaw the debounce prevents. (`livefeed` is price-streaming only — no DB, no regime; the
topology arrow is not a regime pipeline.)

- New worker `regime_gate` (pattern of `regime_composite`: daily cron, full-history
  recompute, advisory lock — next free, e.g. 900_208). Writes `regime_gate_daily`
  (regime_date, state, vote_count, individual votes, flip, dwell_days). Reads SPY/HYG/IEF
  (Tiingo REST like `credit_regime`, or eod_prices where available).
- **Vote = trend/credit/drawdown + 21d debounce** (the Lean-validated set). The debounce is
  the robust innovation (the frozen `regime_composite` lacked it → whipsaw + stuck-RISK-ON-
  since-2020). Production may use richer signals — see backlog below — but must re-validate.
- **PUSH on flip (closes the pull-only gap)**: ON a confirmed state flip, the worker triggers
  the existing drift/rebalance evaluation (`materialize_all_portfolio_drifts`, bl-amplo sprint)
  → in-app rebalance alert. (Chosen over pg_notify+LISTEN or a new API endpoint: reuses the
  alert infra we already built; no new listener to operate.) So "regime change → alert" is
  delivered within a day of the confirmed flip — ample for a 21d-debounced signal.
- Optimizer/builder consume `regime_gate_daily` (latest state) to drive the COMBO regime
  bands, REPLACING the frozen `regime_composite_daily` read.

**MACRO-SIGNAL BACKLOG (Phase 2, worker-only — validate before promoting):** raw macro
levels lost to the price drawdown-proxy 3× on the Lean node (NFCI>0, VIX>20, MANEMP YoY) —
because the rule was crude (raw level) and/or the data was wrong (MANEMP ≠ PMI; secular
manufacturing decline → 51-55% over-staying). They are NOT dead — re-test in the worker with
the RIGHT rule + data: NFCI relative (vs its own MA / rising) or as continuous input, and as
a 4th vote (NFCI+drawdown) not a substitute; VIX in relative/term-structure form (VIX/VIX3M,
add_index full coverage) not raw level; **real ISM PMI** (not on QC FRED — redistribution
limit) on the SLOWDOWN growth axis, where it could improve gold-haven routing. Promote a
signal ONLY if it beats the drawdown-proxy in that calibration, keeping 21d debounce + pkgB.

**FINAL validated config (locked):** `COMBO + vol_grad(1.5) + beta_grad(1.0) +
gate=live(confirm 21, votes trend/credit/drawdown) + slowdown_haven=goldfix
(gld 0.30 / voov 0.20 / qai 0.20 / gcc 0.0 / bil 0.30)` → full 0.633/MaxDD 33.6,
holdout 0.617/MaxDD 26.5.

## 2026-06-21 — Growth-axis test: leading (yield curve) vs coincident (SPY) → both, in the worker

New Lean test on the COMBO **growth axis** (the growth×inflation quadrant that routes
SLOWDOWN/CONTRACTION → the gold haven). Compared the locked baseline (growth = SPY 126d
trend, COINCIDENT) against growth = yield-curve **T10Y2Y** slope (LEADING):

| (Sharpe / MaxDD) | SPY-growth (base) | Curve T10Y2Y |
|---|---|---|
| train  | 0.704 / 33.6 | 0.666 / 28.3 (GFC 28.3) |
| holdout| 0.617 / 26.5 (2022 DD 17.6) | 0.571 / 29.9 (2022 DD 24.9) |
| full   | 0.633 / 33.6 | 0.598 / 28.4 (GFC 28.3) |

Reading (both directions true):
- The curve **LEADS**: it inverted 2006-07 *before* the 2008 crash and cut GFC DD 33.6→28.3
  and full MaxDD 33.6→28.4 — protection the coincident SPY can't give (SPY only reacts after
  the drop starts).
- But two honest costs the data exposes: (1) **OVER-STAYING** from the long/variable lead — the
  curve inverted in 2022 and stayed inverted through 2023-24 with NO recession → defensive
  through the 2023-24 rally → %def 28-33% vs 22%, Sharpe down (full 0.633→0.598, holdout
  0.617→0.571). (2) **LATE for 2022** — 2022 was a rates/valuation repricing, not a
  curve-predicted recession; the curve only inverted mid-2022 after the drop began, so 2022 DD
  WORSENED (17.6→24.9), while coincident SPY turned negative earlier and fired the gold haven
  sooner.

**Verdict — no single growth signal dominates**: coincident (SPY) wins fast repricing bears
(2022); leading (curve) wins slow recession bears (2008). The synthesis is **LEADER +
COINCIDENT** combined (curve to anticipate recession + market momentum to catch repricing),
with rules that adjust the lead.

Implication for the spec:
- **v1 LOCKED config is UNCHANGED**: growth = SPY 126d trend (coincident). The curve does NOT
  replace it (loses Sharpe OOS, over-stays in the 2023-24 rally).
- The **leader+coincident growth COMPOSITE** moves into the MACRO-SIGNAL backlog (Phase 2,
  WORKER territory) as a refinement of the quadrant's growth axis. Build with the RIGHT series —
  **USPHCI / ISM** via the product's data pipeline (they don't provision clean on the QC node) —
  and **NEVER USREC** (NBER recession flag = look-ahead bias, published with long lag/revisions).
  Promote only if the leader+coincident composite beats the coincident-only baseline OOS while
  keeping the 21d debounce + pkgB haven.
