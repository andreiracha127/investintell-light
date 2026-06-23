# NAV Data-Quality Fix — Design Spec

Date: 2026-06-22
Status: approved-design (pending spec review)
Repos: `investintell-light` (app) + `investintell-datalake-workers` (ingestion/workers)
Tiger service: `t83f4np6x4` (role `tsdbadmin`; worker DSN = `DATALAKE_DB_URL`)

## 1. Problem

Two compound, product-wide NAV data-quality bugs, verified at the source in this
investigation (read-only Tiger queries + code reading). Neither is hypothetical;
both are reproduced below with concrete rows.

### Bug 1 — return convention (log stored, simple consumed)

`nav_timeseries.return_1d` (and the `cagg_nav_daily.return_1d` derived from it)
is a **log** return for ~99.8% of rows, declared by `nav_timeseries.return_type`:

| return_type | source | rows |
|---|---|---|
| log | tiingo | 34,854,720 |
| log | yahoo | 643,719 |
| arithmetic | tiingo_eod_proxy | 79,993 |
| log | barchart | 1,213 |
| arithmetic | tiingo | 63 |

Mixed convention (mostly `log`, a small `arithmetic` minority from the proxy ETFs).

Numerically confirmed:
- PAAA (`f31fed45-c90c-4fa2-8033-32b2d4da8f29`): NAV 19.66 → 0.02 gives
  `return_1d = -6.89060912 = ln(0.02/19.66)`, **not** the simple `-0.99898`.
- Fund `fc4f396b-f4d0-4346-aae2-b421477ade67`, an ordinary day:
  `return_1d = -0.00384346 = log(navₜ/navₜ₋₁)`, not the simple `-0.0038360876`.

The PERFORMANCE consumers compound as if **simple** (`prod(1+r)`, `(1+r).cumprod()`):
- `backend/app/analytics/returns.py:45,61,113` (`cumulative_return_series`, `total_return`, `to_monthly_returns`)
- `backend/app/analytics/backtest.py:180,185-186,220` (`assemble_walk_forward_backtest`)
- `backend/app/analytics/monte_carlo.py:81,88,117,123` (`block_bootstrap_monte_carlo`)

The optimizer loader `backend/app/optimizer/data.py:_fund_return_series` (lines 63-82)
passes `return_1d` at face value (= log) and uses log in the NULL fallback. For
COVARIANCE/risk this is **consistent and correct** (log is standard for covariance);
it is NOT a bug. The bug is only on the performance / backtest / projection /
Monte-Carlo path (the live builder curves) that treats log as simple.

Effect: negligible on clean data (log ≈ simple), catastrophic on a glitch (a
negative multiplier under `prod(1+r)`; and a pair of glitch logs that would cancel
under `exp(Σlog)` does NOT cancel under `prod(1+r)`).

### Bug 2 — near-zero NAV prints at the source (Tiingo)

`nav_timeseries` for PAAA: 19.66 → 0.02 → 19.68 → 0.01 → 19.69 (source=tiingo) —
spurious near-zero prints that round-trip against their neighbours.

Prevalence over the full universe (`cagg_nav_daily`):
- `abs(return_1d) > 1.0` (a >2.7×/day move — impossible): **3,112 rows / 279 funds**.
- `abs(return_1d) ∈ (0.40, 1.0]` (grey band): 1,918 rows / (≤701 funds with `>0.40`).
- `nav < 0.05`: 14,490 rows — dominated by **sustained** near-zero (dead funds),
  which do NOT round-trip and are NOT repaired (see eligibility flag).

Dominated by fixed income. Because `fund_analysis`/`fund_dossier_tier_b` read the
NAV **price** series (`simple_returns(nav)`), the glitch poisons them too — so Bug 2
MUST be fixed at the source (`nav_timeseries`), not merely read-side.

### Validated target (the proof the fix works)

`backend/scripts/local_fund_backtest.py` `--logfix` mode (lines 1810-1825):
`fixed = np.expm1(np.where(np.abs(raw) > 0.40, 0.0, raw))` over raw `frets` (= log
`return_1d`): zero impossible prints (|log|>0.40 = Bug 2), then `expm1` (log→simple
= Bug 1). `prets` (book B, from `adj_close`) is untouched. Result (book B unchanged
= sanity; book A improves):

| profile | CAGR_A buggy→fixed | MaxDD_A buggy→fixed |
|---|---|---|
| aggressive | 7.2 → 9.3 | 33.3 → 31.3 |
| moderate | 6.0 → 7.6 | 25.6 → 24.2 |
| conservative | 4.8 → 6.0 | 25.2 → 21.0 |

These are the regression targets for the product-wide implementation.

## 2. Owner decisions (locked 2026-06-22)

1. **Bug 1 convention:** read-side helper (a). Covariance/optimizer/risk_metrics
   stay in log. No data migration. Reversible. (Source-side standardization is a
   later cleanup, out of scope here.)
2. **Bug 2 detector:** round-trip near-zero repair at ingestion + a read-side guard
   at `|log| > 0.40` (= the harness-proven threshold) as a safety net.
3. **Eligibility flag:** a column on `fund_risk_metrics`, computed by the
   risk_metrics worker, honored by both optimizer and backtest.
4. **Reprocessing:** authorized after a green gate — once tests pass and the dry-run
   matches the harness numbers, run the reprocess of the 279 funds + cagg refresh
   without further confirmation.

## 3. Architecture facts established (do not re-derive)

- The app reads `nav_timeseries` directly: `FundNav.__tablename__ = "nav_timeseries"`
  (`backend/app/models/fund.py:285-306`). `fund_nav` is deprecated.
- `cagg_nav_daily` is a continuous aggregate, `materialized_only = true`, defined as
  `last(nav, nav_date)`, `last(return_1d, nav_date)`, `count(*)`, `last(aum_usd,
  nav_date)` grouped by `(instrument_id, time_bucket('1 day', nav_date))`. The series
  is daily ⇒ one row per bucket ⇒ the cagg is effectively a copy; cleaning
  `nav_timeseries` + `refresh_continuous_aggregate` propagates exactly.
- Ingestion (`investintell-datalake-workers`): `src/workers/instrument_ingestion.py`
  `build_rows()` computes `ret = round(math.log(price/prev), 8)`, sets
  `return_type='log'`, drops `price <= 0`, and upserts (`ON CONFLICT (instrument_id,
  nav_date) DO UPDATE`). No outlier clamp/winsorize exists today. Re-runs are a
  stale-only watermark sweep; there is no dedicated NAV reprocess script.
- Performance consumers of fund `return_1d` are ONLY the backtest and the portfolio
  Monte-Carlo. `fund_analysis` (Tier A) and `fund_dossier_tier_b` derive their own
  simple returns from NAV prices and are NOT Bug-1 consumers (but ARE Bug-2 victims
  via the NAV price, fixed by the source cleanup).

## 4. Design

Three parts. Part A (light, read-side) and Part B (datalake, source) are independent
and can land in parallel; Part C (flag) spans both and depends on Part B's detector
to define "irreparable".

### Part A — Bug 1 read-side conversion (repo: investintell-light)

Reversible, no data migration. Applied ONLY to performance curves; the optimizer
objective and covariance keep log.

**A1. New pure helper** `backend/app/analytics/return_convention.py`
- `GLITCH_LOG_THRESHOLD = 0.40` — `|log return|` above this is treated as a residual
  glitch and zeroed (Bug-2 safety net; matches the harness).
- `to_simple_returns(values, return_types=None, *, glitch_threshold=GLITCH_LOG_THRESHOLD)`:
  element-wise. For `log` entries: zero where `|value| > glitch_threshold`, then
  `expm1`. For `arithmetic` entries: identity (already simple). `return_types=None`
  ⇒ treat all as `log` (the fund default). Pure; accepts `pd.Series`/`np.ndarray`;
  preserves index/dtype; propagates NaN positionally (callers validate at the
  composition boundary, as today — the helper adds no new NaN policy).
- Rationale for the guard living here too: not all historical rows will be
  reprocessed immediately, and equities feed this path as well — the read-side guard
  keeps a single residual glitch from detonating a live curve.

**A2. Simple-frame loaders** `backend/app/optimizer/data.py`
- Add a `convention: Literal["log","simple"] = "log"` path (sibling builders, not a
  rewrite of the existing log loaders, which stay byte-identical):
  - `_fund_return_series` gains a simple variant that carries `return_type` per row
    and applies `to_simple_returns` (honoring the convention) instead of face value.
  - `_load_fund_returns` / `_load_fund_returns_batch` additionally select
    `nav_timeseries.return_type` (directly in the loader query — the existing log
    loaders stay byte-identical, selecting only `nav_date, nav, return_1d`) and build
    simple series when `convention="simple"`.
  - `_load_equity_returns`: equities are log diffs of `adj_close`; the simple variant
    applies `expm1` (clean data ⇒ no guard effect). Equity adj_close has no glitch
    population, but the guard is harmless.
  - `load_aligned_returns` / `load_returns_matrix` gain `convention` and pass through.
- The existing log callers (optimizer covariance) call with the default `"log"` and
  are unchanged.

**A3. Backtest dual representation** `backend/app/analytics/backtest.py`
- `assemble_walk_forward_backtest(returns, solve_fn, *, perf_returns=None, ...)`:
  `perf_returns` defaults to `returns` (back-compatible). The solve uses the `returns`
  (log) TRAIN block — covariance unchanged. The OOS composition (`test_block @ w`
  → `prod(1+r)`, the chained NAV, gross/net) uses `perf_returns` (simple) TEST block.
  This fixes two latent errors: (i) a weighted sum of asset returns is the portfolio
  return only for SIMPLE returns; (ii) composing log as simple. `perf_returns` must
  be index/column aligned to `returns` (assert).
- `backend/app/services/backtest.py`: load both frames
  (`convention="log"` for solve, `convention="simple"` for perf) and pass both.

**A4. Monte-Carlo simple frame** `backend/app/services/monte_carlo.py`
- Load the frame with `convention="simple"`; `portfolio_returns = frame_simple @ w`
  (now a true portfolio simple-return series). `analytics/monte_carlo.py` is
  unchanged (it correctly composes simple).

**A5. Do NOT touch** (log is correct / not a Bug-1 consumer): optimizer objective
(`min_cvar`/`max_return_cvar` scenarios in `portfolio_builder.py`), `engine`
(Ledoit-Wolf/pairwise), `risk_metrics`, `fund_analysis`, `fund_dossier_tier_b`.
These benefit from Bug 2's source cleanup automatically.

### Part B — Bug 2 source cleanup (repo: investintell-datalake-workers)

**B1. New sanitizer** `src/workers/_nav_sanitize.py`
- `sanitize_nav_series(rows) -> SanitizeResult` where `rows` is date-ordered
  `(nav_date, nav)`; returns cleaned NAV series + per-day repair flags + stats
  (`glitch_count`, `dead`, `scale_step`).
- Round-trip near-zero detector: for each point, compute a robust local reference
  (median of a centered window excluding the point, e.g. window=5). A point is a
  TRANSIENT glitch if `nav < ref * LOW_RATIO` (default `LOW_RATIO = 0.2`) **and** a
  valid non-glitch neighbour exists on both sides (so a dip that recovers). Robust to
  alternating glitches (PAAA 0.02/19.68/0.01/19.69) because the window median tracks
  the true level, not the spikes.
- Repair: replace each glitch NAV by log-linear interpolation between the nearest
  non-glitch neighbours; `return_1d` is recomputed from the repaired series.
- NOT repaired (left for the eligibility flag, never invented):
  - dead: NAV sustained near-zero (the local reference itself is near-zero) → mark
    `dead=True`, leave values, do not interpolate.
  - scale step: a persistent level jump of ≥ `SCALE_STEP_RATIO` (default 10×) that
    does NOT revert within the window → mark `scale_step=True`, leave values (which
    scale is "true" is ambiguous; repairing would invent data).
- Thresholds (`LOW_RATIO`, window, `SCALE_STEP_RATIO`) are module constants,
  documented, and covered by tests; calibration is part of implementation (validated
  against the 279-fund population + PAAA/fc4f396b).

**B2. Wire into ingestion** `src/workers/instrument_ingestion.py`
- `build_rows()` runs `sanitize_nav_series` on each instrument's price series BEFORE
  computing `return_1d`, so new ingests never write a glitch. `return_type` stays
  `log`. Existing per-source parsing is unchanged.

**B3. Reprocess script** `scripts/reprocess_nav_glitches.py`
- Reads the affected funds' existing rows from `nav_timeseries` (default selection:
  `instrument_id` having any `abs(return_1d) > 1.0`, i.e. the 279), sanitizes,
  upserts corrected `(nav, return_1d)` via the existing upsert, then
  `refresh_continuous_aggregate('cagg_nav_daily', <min>, <max>)` over the touched
  window. Idempotent. `--dry-run` reports what would change without writing.
- Operates on existing rows (not a Tiingo re-fetch) so it is deterministic and does
  not depend on the upstream still serving the same bad print.

### Part C — Eligibility flag (Task 3; spans both repos)

**C1. Schema** — add to `fund_risk_metrics`:
- `nav_quality_ok boolean` (derived) and `nav_glitch_count int` (diagnostic).
- DDL in `investintell-light/backend/db/ddl/2026-06-22_nav_quality_flag.sql`, applied
  to Tiger; project both columns into `fund_risk_latest_mv` (and into `funds_list_mv`
  only if a UI surface is later wanted — not required now).

**C2. Worker computation** (datalake risk_metrics worker)
- Compute `nav_glitch_count` (post-repair residual `abs(return_1d) > 1.0`) and
  `nav_quality_ok = (not dead) AND (not scale_step) AND (nav_glitch_count == 0)`.

**C3. Model + readers** (light)
- `FundRiskLatest` (`backend/app/models/fund.py`): add `nav_quality_ok`,
  `nav_glitch_count`.
- `select_universe_funds` (`backend/app/optimizer/data.py`): add a quality gate that
  excludes `nav_quality_ok = false`. **NULL is treated as OK** (fail-open) until the
  worker populates the column, so the flag never excludes the universe en masse
  before it is computed.
- Backtest/optimize service: a fund explicitly flagged `nav_quality_ok = false`
  raises a fail-loud `ValueError` (→ 422) naming the fund, rather than silently
  producing a bad curve.

## 5. Units & interfaces (isolation)

| Unit | Purpose | Depends on | Tested via |
|---|---|---|---|
| `return_convention.to_simple_returns` | log→simple + glitch guard, per convention | numpy/pandas | `test_return_convention.py` |
| `data.py` simple loaders | DB → simple daily-return frame | helper, models | `test_optimizer_data*.py` |
| `analytics/backtest.assemble_walk_forward_backtest` (perf_returns) | OOS curve from simple perf returns; solve on log | — | `test_backtest_analytics.py` |
| `services/backtest`, `services/monte_carlo` | wire dual/simple frames | loaders, analytics | `test_backtest_service.py`, `test_monte_carlo_service.py` |
| `_nav_sanitize.sanitize_nav_series` | detect+repair round-trip glitch; flag dead/scale | numpy | `test_nav_sanitize.py` |
| `instrument_ingestion.build_rows` | sanitize before return_1d | sanitizer | `test_instrument_ingestion.py` |
| `reprocess_nav_glitches.py` | reprocess 279 + cagg refresh | sanitizer, DB | manual dry-run + post-run validation |
| `fund_risk_metrics.nav_quality_ok` | eligibility signal | worker | worker test + `select_universe_funds` test |

## 6. Validation / acceptance criteria

- Proxy-only (book B) results UNCHANGED (regression).
- Live builder backtest/projection/MC correct on clean funds; small change in the
  direction of the harness `--logfix` on clean data.
- The 279 glitch funds clean in the cagg; PAAA/fc4f396b have no impossible spikes.
- Re-running the harness WITHOUT `--logfix` over the cleaned cagg approaches the
  "fixed" numbers in §1 (agg ≈9.3/31.3, mod ≈7.6/24.2, con ≈6.0/21.0).
- Tests: `to_simple_returns` (log vs arithmetic vs glitch), the glitch detector
  (round-trip single + alternating + dead + scale-step + a real big move NOT
  flagged), and the dual-frame backtest.
- Gates green: backend tests (light), worker tests (datalake), no regression in the
  existing suites.

## 7. Constraints / non-goals

- Product-wide, affects LIVE builder output → branch + tests; reprocess only after a
  green gate (decision 4).
- Do not silently relax limits. An irreparable fund is flagged inelegible, never
  invented.
- Tiger queries are READ-ONLY for diagnosis. Data changes only via the
  ingestion/reprocess pipeline + `refresh_continuous_aggregate`, never ad-hoc UPDATE.
- Out of scope: source-side convention standardization (decision 1b); full
  scale-mismatch repair (the 14 scale-mismatch funds are flagged, not corrected);
  any UI surfacing of the flag.
- Isolation: dedicated worktrees off `main` for both repos (the current working tree
  is on `feat/bl-amplo-constraints-drift` with unrelated changes).

## 8. Rollout order

1. Part A (light) + Part B detector (datalake) with TDD, in worktrees off `main`.
2. Part C schema/worker/readers (fail-open NULL).
3. Green gate (both suites) + dry-run of the reprocess matching harness numbers.
4. Run reprocess of the 279 funds + `refresh_continuous_aggregate` (authorized).
5. Compute the flag (worker) for the universe; verify optimizer/backtest honor it.
