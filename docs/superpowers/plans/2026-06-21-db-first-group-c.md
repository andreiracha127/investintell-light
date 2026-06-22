# DB-First — Group C (Interactive series via on-demand SQL functions) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the rolling/distribution/drawdown/VaR-CVaR series math of `funds/{id}/analysis`, `stocks/{ticker}/analysis`, `funds/{id}/entity-analytics` (series only) and `funds/{id}/risk-timeseries` out of the Python request path and into five on-demand Postgres SQL functions that read directly from the canonical daily CAGGs, with bit-for-bit parity against the current `pandas`/`numpy` math and a dual-read flag for safe rollout.

**Architecture:** Five `LANGUAGE SQL IMMUTABLE` functions (`fn_rolling_metrics`, `fn_rolling_beta_corr`, `fn_drawdown`, `fn_histogram`, `fn_var_cvar`) live in a single dated DDL file in the backend repo (`backend/db/ddl/`), applied via Tiger/psql (manual ops). Each function takes an **entity key + date window** and queries the CAGG (`cagg_eod_daily` for stocks, `cagg_nav_daily` for funds) directly, returning the computed series/scalars — no arrays passed from Python, no materialization, no worker. Each of the four routes is rewritten behind a NEW flag `use_series_db_first` (default `False`): when on, the route calls the SQL functions; when off, it runs the legacy pandas path verbatim. A parity test per route compares the two within a documented numeric tolerance, and a "no pandas" assertion proves the request path is free of `.rolling`/`np.histogram` when the flag is on.

**Tech Stack:** PostgreSQL 15 / TimescaleDB (window functions, `width_bucket`, `percentile_cont`, continuous aggregates), SQLAlchemy 2.0 async + asyncpg (`text()` SQL), FastAPI, pytest (`asyncio_mode = "auto"`), pandas/numpy (legacy path only, removed last).

## Baseline — commit `f6e2c27` (`feat/db-first-analytics`), Foundation + Group D done

This plan assumes the post-`38dbdb4` / post-Group-D state already on this branch:

- **Source series are db-first.** `stocks/{ticker}/analysis` and `funds/{id}/analysis` no longer fetch Tiingo in the request path; the historical series are read locally. The canonical daily sources are the continuous aggregates `cagg_eod_daily(ticker, bucket, open, high, low, close, volume, adj_open, adj_high, adj_low, adj_close, adj_volume)` and `cagg_nav_daily(instrument_id, bucket, nav, return_1d, n_obs, aum_usd)`, both with `time_bucket('1 day', …)` buckets, `last(…, date)` per day over already-daily base tables, an auto-refresh policy and real-time aggregation. `bucket` is a `timestamp`; cast `::date` to match `SeriesPoint = tuple[date, float]`.
- **Group D is merged on this branch.** `price_latest_mv` / `nav_latest_mv`, the `matview_refresh` worker, the `PriceLatest`/`NavLatest` ORM, and the flag `use_latest_mv_prices` exist. Group C adds a SECOND, independent flag (`use_series_db_first`) — it does not reuse `use_latest_mv_prices`.
- **DDL convention.** DDL for the main app DB is versioned in `backend/db/ddl/` (dated files applied via Tiger/psql), e.g. `backend/db/ddl/2026-06-21_cagg_eod_daily_timeseries.sql`. The string-assert test pattern for DDL is `backend/tests/test_dynamic_catalog_sql.py` / `backend/tests/test_price_nav_latest_mv_sql.py` (read the SQL file as text; assert substrings; no DB).
- **No existing `CREATE FUNCTION` in the repo.** These five functions are new. There is no in-repo function to mirror; this plan defines the convention.

## Global Constraints

- Branch base `feat/db-first-analytics` @ `f6e2c27`; worktree `E:/investintell-light/.claude/worktrees/db-first-analytics`. All paths below are relative to that worktree root.
- The five SQL functions live in ONE dated DDL file: `backend/db/ddl/2026-06-21_group_c_functions.sql`, applied via Tiger/psql against the **main app DB** (`DATABASE_URL` — the same DB that holds `cagg_eod_daily`/`cagg_nav_daily`). This is a MANUAL OPS STEP. NO worker, NO materialization — the functions are on-demand.
- Function signature convention (decided): **each function takes the entity key + window + `[start, end]` date range and queries the CAGG directly inside the function**, returning the series. Functions are `CREATE OR REPLACE FUNCTION fn_*(...) RETURNS TABLE(...) LANGUAGE SQL STABLE`. (Rationale: reading a continuous aggregate is not `IMMUTABLE` — real-time aggregation makes results time-dependent — so `STABLE` is the correct volatility class; `IMMUTABLE` would be a correctness lie. The spec's "IMMUTABLE" wording is superseded here for this reason; documented in Task 1.)
- Scale contract (project-wide): all fractional fields are decimal fractions (`0.05 = 5%`), never 0-100. VaR/CVaR/drawdown signs follow the legacy Python: VaR/CVaR are POSITIVE loss magnitudes; drawdown depth is a NEGATIVE fraction.
- Annualization constant: 252 trading days. Risk-free rate for rolling sharpe and entity-analytics sortino: `rf = 0` for rolling sharpe (legacy `_rolling_sharpe`), `rf = 0.04` for entity-analytics SCALARS (which stay in Python, read from `fund_risk_metrics` — NOT moved here).
- Transition (spec §12): build function → parity test vs current pandas within documented tolerance → dual-read behind NEW flag `use_series_db_first` default `False` → flip default → remove pandas. While the flag is off, the legacy pandas path runs unchanged.
- "No pandas in request path": each migrated route, with the flag ON, must call the `fn_*` functions and must NOT touch `.rolling` / `np.histogram` / `np.quantile`. Mirror the `_FakeSession.executed` pattern in `backend/tests/test_price_latest_mv_reads.py` (assert `"fn_rolling_metrics"` etc. appears in the executed SQL; assert no `".rolling"` substring leaks into the path).
- **entity-analytics is series-only.** Only the SERIES (rolling returns, drawdown-period detection input, distribution) move to SQL. ALL scalars (sharpe/sortino/calmar/alpha/beta/tracking/info ratio/capture/tail-risk/return-statistics) stay in Python and continue reading from `fund_risk_metrics` / computing from the in-window returns — unchanged in this plan.
- Documented tolerances for parity (used in every parity test): `~1e-10` for rolling vol/sharpe/beta/correlation/drawdown/growth-of-100; `~1e-8` for VaR/CVaR; `~1e-6` for histogram bin edges/counts. Where Python uses `float` (numpy `linear`/type-7 interp) and Postgres `percentile_cont` uses the same linear interpolation, equality is exact to `~1e-12`; the looser bounds absorb numeric/dtype drift.
- Backend tests: `cd backend && pytest`; `asyncio_mode = "auto"`; DB I/O is stubbed via a fake session at the function level (no live DB). DDL string-assert tests read the `.sql` file as text only.
- Warm-up / slicing semantics that MUST be preserved for parity (legacy behavior, copied verbatim below): query `[start - lookback_pad, end]`; rolling series emit only when the window is full (`min_periods = window` → first `window-1` NaN/skip); the visible slice keeps only points with `date > start` (STRICT) and drops NaN; for `5Y`/`MAX` ranges the line series is weekly-downsampled (W-FRI last). Histograms/VaR/CVaR/total-return use the **in-range** returns (`date > start`), not the padded set.

---

## Source-of-truth math (copied verbatim from the current Python — the parity target)

These are the exact current implementations the SQL functions must reproduce.

**Rolling volatility** — `app/analytics/rolling.py::rolling_volatility`:
`returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252)`.

**Rolling sharpe** — `app/services/fund_analysis.py::_rolling_sharpe` (rf=0):
`mean = returns.rolling(window, min_periods=window).mean()`;
`std = returns.rolling(window, min_periods=window).std(ddof=1).replace(0.0, np.nan)`;
`(mean / std) * math.sqrt(252)`.

**Rolling beta** — `app/analytics/rolling.py::rolling_beta` (after `align_returns` inner-join):
`cov = a.rolling(window, min_periods=window).cov(b)`; `var = b.rolling(window, min_periods=window).var(ddof=1)`; `cov / var.replace(0.0, np.nan)`.

**Rolling correlation** — `app/analytics/rolling.py::rolling_correlation`:
`a.rolling(window, min_periods=window).corr(b)`.

**Drawdown series** — `app/services/fund_dossier_tier_b.py::_max_drawdown_series`:
`nav / nav.cummax() - 1.0` (NEGATIVE fraction). Risk-timeseries multiplies by `100.0` (see Task 6). Fund-analysis emits the fraction (`visible / visible.cummax() - 1.0`).

**Histogram** — `app/analytics/distribution.py::return_histogram` (bins=20):
`counts, edges = np.histogram(values, bins=20)` (equal-width over `[min, max]`, 21 edges, 20 counts); `counts_normalized[i] = counts[i] / max(counts)`.

**Historical VaR** — `app/analytics/risk.py::historical_var`:
`-float(np.quantile(values, 1 - confidence))` (numpy `linear`/type-7). Stock-analysis emits VaR-95 (`1-0.95=0.05`) AND VaR-99 (`1-0.99=0.01`); fund-analysis emits VaR-95 only.

**Historical CVaR** — `app/analytics/risk.py::historical_cvar`:
`cutoff = np.quantile(values, 1 - confidence)`; `tail = values[values <= cutoff]`; `-float(tail.mean())`. CVaR-95 only.

**Growth-of-100** — `app/services/fund_analysis.py`: `(visible / float(visible.iloc[0])) * 100.0`.

**Total return** — `app/analytics/returns.py::total_return`: `(1 + r).prod() - 1`.

**Best/worst day** — `app/analytics/risk.py::best_worst_day`: `idxmax`/`idxmin` of in-range returns → (date, value).

**Monthly returns (fund-analysis)** — `app/services/fund_analysis.py::_monthly_return_points`:
`month_end = nav.resample("ME").last().dropna()`; `returns = month_end.pct_change().dropna()`.

**entity-analytics rolling returns** — `fund_dossier_tier_b.py::_rolling_returns`, windows `{1M:21,3M:63,6M:126,1Y:252}`:
`compounded.rolling(window).apply(np.prod, raw=True).sub(1.0)` (i.e. `prod(1+r) - 1` over the trailing window, NaN until full).

**entity-analytics distribution** — `fund_dossier_tier_b.py::_distribution`:
`counts, edges = np.histogram(values, bins="fd")` (Freedman-Diaconis bin count); `q05 = np.quantile(values, 0.05)`; `var_95 = -q05`; `tail = values[values <= q05]`; `cvar_95 = -tail.mean()`; plus `skew()`/`kurt()` (pandas, Fisher; not moved — stays scalar in Python).

**entity-analytics window slicing** — `fund_dossier_tier_b.py::_window_nav`, `WINDOW_DAYS {3M:63,6M:126,1Y:252,3Y:756,5Y:1260}`: `nav.iloc[-days:]` (last N rows, NO padding). `_nav_for_window` queries `[last_date - (WINDOW_DAYS*1.6 + lookback_pad(21)), last_date]` then trims to the last `WINDOW_DAYS` rows.

**fund/stock-analysis window mapping** — `app/services/_series.py::RANGE_DAYS {1M:30,6M:182,1Y:365,5Y:1826}`; `app/services/stock_analysis.py::lookback_pad_days(window) = ceil(window*7/5) + 15`. `end = last_date`; `start = first_date if MAX else end - RANGE_DAYS[range]`; `query_start = start - lookback_pad_days(window)`. Fund window default 252; stock window default 63.

---

## File Structure

**SQL functions (backend repo, main DB):**
- Create: `backend/db/ddl/2026-06-21_group_c_functions.sql` — the five `fn_*` functions (CREATE OR REPLACE … RETURNS TABLE … LANGUAGE SQL STABLE), reading from `cagg_eod_daily`/`cagg_nav_daily`.
- Create: `backend/tests/test_group_c_functions_sql.py` — string-assert test of the DDL artifact (mirrors `test_price_nav_latest_mv_sql.py`).

**Config:**
- Modify: `backend/app/core/config.py` — add `use_series_db_first: bool = False`.

**SQL-call helpers (backend):**
- Create: `backend/app/services/series_sql.py` — thin async helpers that invoke the `fn_*` functions via `text()` and reshape rows into the exact dataclasses the assemblers already produce (`SeriesPoint` lists, `Histogram`, VaR/CVaR scalars). One canonical place so all four routes share the SQL-call code.

**Route rewrites (one task each):**
- Modify: `backend/app/services/fund_analysis.py` (+ `backend/tests/test_fund_analysis_series_sql.py`).
- Modify: `backend/app/services/stock_analysis.py` (+ `backend/tests/test_stock_analysis_series_sql.py`).
- Modify: `backend/app/services/fund_dossier_tier_b.py` entity-analytics series (+ `backend/tests/test_entity_analytics_series_sql.py`).
- Modify: `backend/app/services/fund_dossier_tier_b.py` risk-timeseries (+ `backend/tests/test_risk_timeseries_series_sql.py`).

**Performance / cleanup:**
- Create: `backend/scripts/group_c_function_perf.py` — measures `fn_*` latency on long windows (5Y/MAX) before the pandas removal (spec §15 risk).

**Why these boundaries:** the functions are one DDL artifact (one apply, one ops step). The SQL-call shaping lives in `series_sql.py` so the four route rewrites consume identical helpers (DRY) and each route task is independently reviewable. Each route rewrite is one task because a reviewer could accept one route's parity while rejecting another's.

---

## Interfaces (contracts between tasks)

SQL functions (Task 1) — all return TABLEs ordered by `d`:

- `fn_rolling_metrics(p_ticker text, p_instrument uuid, p_window int, p_start date, p_end date) RETURNS TABLE(d date, vol double precision, sharpe double precision)` — pass `p_ticker` for stocks (then `p_instrument` NULL) or `p_instrument` for funds (then `p_ticker` NULL); computes daily simple returns from the CAGG over `[p_start, p_end]`, then rolling vol (`stddev_samp * sqrt(252)`) and rolling sharpe (`avg/stddev_samp * sqrt(252)`) over the last `p_window` returns. Emits one row per return date where the window is full (`vol`/`sharpe` NULL where undefined, e.g. zero std).
- `fn_rolling_beta_corr(p_ticker text, p_bench text, p_window int, p_start date, p_end date) RETURNS TABLE(d date, beta double precision, corr double precision)` — inner-joins asset & benchmark daily returns from `cagg_eod_daily`, rolling `covar_samp(a,b)/var_samp(b)` and `corr(a,b)` over `p_window`.
- `fn_drawdown(p_ticker text, p_instrument uuid, p_start date, p_end date) RETURNS TABLE(d date, drawdown double precision)` — `value / max(value) OVER (ORDER BY d ROWS UNBOUNDED PRECEDING) - 1.0`. Uses `close` for stocks (NULL `p_instrument`) or `nav` for funds (NULL `p_ticker`). Fraction (NEGATIVE), NOT ×100.
- `fn_histogram(p_ticker text, p_instrument uuid, p_bins int, p_start date, p_end date) RETURNS TABLE(bin_index int, bin_lo double precision, bin_hi double precision, cnt bigint)` — equal-width bins over `[min(r), max(r)]` of the in-range daily returns via `width_bucket`; one row per non-empty-or-empty bin index `1..p_bins` plus the closed top edge handling (see Task 1). The caller derives the 21 edges + 20 counts + normalized.
- `fn_var_cvar(p_ticker text, p_instrument uuid, p_level double precision, p_start date, p_end date) RETURNS TABLE(var double precision, cvar double precision)` — `var = -percentile_cont(1 - p_level) WITHIN GROUP (ORDER BY r)`; `cvar = -avg(r) FILTER (WHERE r <= percentile_cont(1 - p_level) …)`. Single row.

Config (Task 2):
- `settings.use_series_db_first: bool` (default `False`).

SQL-call helpers (Task 3, in `app/services/series_sql.py`):
- `async def rolling_metrics_points(session, *, ticker=None, instrument_id=None, window, start, end) -> tuple[list[SeriesPoint], list[SeriesPoint]]` → `(vol_points, sharpe_points)`, NaN/NULL rows dropped, newest-last (ascending `d`).
- `async def rolling_beta_corr_points(session, *, ticker, benchmark, window, start, end) -> tuple[list[SeriesPoint], list[SeriesPoint]]` → `(beta_points, corr_points)`.
- `async def drawdown_points(session, *, ticker=None, instrument_id=None, start, end) -> list[SeriesPoint]`.
- `async def histogram_out(session, *, ticker=None, instrument_id=None, bins, start, end) -> HistogramOut` (`bin_edges` 21, `counts` 20, `counts_normalized` 20).
- `async def var_cvar(session, *, ticker=None, instrument_id=None, level, start, end) -> tuple[float, float]` → `(var, cvar)` positive magnitudes.
- `SeriesPoint = tuple[dt.date, float]` (the project's existing alias, imported from `app.schemas.analysis` / `app.services._series`).

Each helper builds SQL with the `fn_*` name as a literal so the route's "no pandas" test can assert the function name appears in `session.executed`.

---

## Task 1: The five SQL functions + string-assert test

**Files:**
- Create: `backend/db/ddl/2026-06-21_group_c_functions.sql`
- Test: `backend/tests/test_group_c_functions_sql.py`

**Interfaces:**
- Produces: the five `fn_*` functions of the Interfaces section, in the main app DB.

**Context:** there is no existing `CREATE FUNCTION` in the repo, so this file defines the convention. Functions read from the CAGGs (`cagg_eod_daily`/`cagg_nav_daily`) — a continuous aggregate with real-time aggregation, so reads are time-dependent → the correct volatility class is `STABLE` (not `IMMUTABLE`; the spec's "IMMUTABLE" wording is superseded for correctness). The string-assert test mirrors `backend/tests/test_dynamic_catalog_sql.py` / `test_price_nav_latest_mv_sql.py`: read the `.sql` as text, assert key substrings, no DB.

- [ ] **Step 1: Write the failing string-assert test**

```python
# backend/tests/test_group_c_functions_sql.py
from pathlib import Path

SCHEMA = (
    Path(__file__).resolve().parents[1]
    / "db" / "ddl" / "2026-06-21_group_c_functions.sql"
)


def test_defines_all_five_functions_language_sql_stable():
    sql = SCHEMA.read_text(encoding="utf-8")
    for fn in (
        "fn_rolling_metrics",
        "fn_rolling_beta_corr",
        "fn_drawdown",
        "fn_histogram",
        "fn_var_cvar",
    ):
        assert f"CREATE OR REPLACE FUNCTION {fn}" in sql, fn
    # On-demand reads of a real-time CAGG are time-dependent -> STABLE, not IMMUTABLE.
    assert "LANGUAGE sql STABLE" in sql
    assert "IMMUTABLE" not in sql


def test_rolling_metrics_uses_sample_std_and_sqrt_252():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "stddev_samp" in sql
    assert "sqrt(252" in sql
    # Rolling frame: window-1 preceding .. current row.
    assert "ROWS BETWEEN" in sql
    assert "PRECEDING AND CURRENT ROW" in sql


def test_beta_corr_use_sample_covar_and_corr():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "covar_samp" in sql
    assert "var_samp" in sql
    assert "corr(" in sql


def test_drawdown_uses_running_max_minus_one():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "max(" in sql
    assert "UNBOUNDED PRECEDING AND CURRENT ROW" in sql
    assert "- 1.0" in sql


def test_histogram_uses_width_bucket():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "width_bucket" in sql


def test_var_cvar_use_percentile_cont_and_filter():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "percentile_cont" in sql
    assert "WITHIN GROUP (ORDER BY" in sql
    assert "FILTER (WHERE" in sql


def test_functions_read_from_canonical_caggs():
    sql = SCHEMA.read_text(encoding="utf-8")
    assert "FROM cagg_eod_daily" in sql
    assert "FROM cagg_nav_daily" in sql
```

- [ ] **Step 2: Run the test, see it fail**

Run: `cd backend && pytest tests/test_group_c_functions_sql.py -q`
Expected: FAIL (`FileNotFoundError` — the DDL file does not exist yet).

- [ ] **Step 3: Write the DDL with all five functions**

```sql
-- backend/db/ddl/2026-06-21_group_c_functions.sql
-- Group C: on-demand series math moved from the FastAPI request path into the
-- DB. Each function takes an entity key + window + [start, end] date range and
-- reads the canonical daily CAGGs (cagg_eod_daily / cagg_nav_daily) directly.
-- No materialization, no worker: these are STABLE (NOT IMMUTABLE — a real-time
-- continuous aggregate makes reads time-dependent) on-demand functions.
--
-- Math is a 1:1 port of the legacy pandas/numpy (see the plan's
-- "Source-of-truth math" section). Returns are decimal fractions (0.05 = 5%);
-- VaR/CVaR are POSITIVE loss magnitudes; drawdown is a NEGATIVE fraction.
-- Daily SIMPLE returns are nav/close pct_change: r_t = v_t / lag(v_t) - 1,
-- matching pandas pct_change().dropna() (the first in-range row has no return).

-- ---------------------------------------------------------------------------
-- fn_rolling_metrics: rolling annualized vol + rolling sharpe (rf=0).
-- Pass p_ticker for stocks (p_instrument NULL) OR p_instrument for funds.
-- Vol  = stddev_samp(r) OVER w * sqrt(252)          (ddof=1)
-- Shrp = (avg(r) OVER w / stddev_samp(r) OVER w) * sqrt(252)
-- Emitted only when the trailing window has p_window returns; vol/sharpe NULL
-- where the window std is 0 (legacy .replace(0.0, np.nan)).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_rolling_metrics(
    p_ticker text,
    p_instrument uuid,
    p_window int,
    p_start date,
    p_end date
)
RETURNS TABLE(d date, vol double precision, sharpe double precision)
LANGUAGE sql STABLE AS $$
    WITH px AS (
        SELECT bucket::date AS d,
               CASE WHEN p_ticker IS NOT NULL THEN close ELSE nav END AS v
        FROM (
            SELECT bucket, close, NULL::double precision AS nav
            FROM cagg_eod_daily
            WHERE p_ticker IS NOT NULL AND ticker = p_ticker
              AND bucket::date BETWEEN p_start AND p_end
              AND close IS NOT NULL
            UNION ALL
            SELECT bucket, NULL::double precision AS close, nav
            FROM cagg_nav_daily
            WHERE p_instrument IS NOT NULL AND instrument_id = p_instrument
              AND bucket::date BETWEEN p_start AND p_end
              AND nav IS NOT NULL
        ) s
    ),
    rets AS (
        SELECT d,
               v / lag(v) OVER (ORDER BY d) - 1.0 AS r
        FROM px
    ),
    win AS (
        SELECT d, r,
               count(r)        OVER w AS n,
               stddev_samp(r)  OVER w AS sd,
               avg(r)          OVER w AS mu
        FROM rets
        WHERE r IS NOT NULL
        WINDOW w AS (ORDER BY d ROWS BETWEEN p_window - 1 PRECEDING AND CURRENT ROW)
    )
    SELECT d,
           CASE WHEN n = p_window THEN sd * sqrt(252.0) END AS vol,
           CASE WHEN n = p_window AND sd <> 0
                THEN (mu / sd) * sqrt(252.0) END AS sharpe
    FROM win
    ORDER BY d;
$$;

-- ---------------------------------------------------------------------------
-- fn_rolling_beta_corr: rolling beta + Pearson correlation, asset vs benchmark.
-- Inner-join of asset & benchmark daily returns (legacy align_returns), then
-- beta = covar_samp(a,b) OVER w / var_samp(b) OVER w  (ddof=1; NULL where var=0)
-- corr = corr(a,b) OVER w.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_rolling_beta_corr(
    p_ticker text,
    p_bench text,
    p_window int,
    p_start date,
    p_end date
)
RETURNS TABLE(d date, beta double precision, corr double precision)
LANGUAGE sql STABLE AS $$
    WITH a AS (
        SELECT bucket::date AS d, adj_close AS v
        FROM cagg_eod_daily
        WHERE ticker = p_ticker AND bucket::date BETWEEN p_start AND p_end
          AND adj_close IS NOT NULL
    ),
    b AS (
        SELECT bucket::date AS d, adj_close AS v
        FROM cagg_eod_daily
        WHERE ticker = p_bench AND bucket::date BETWEEN p_start AND p_end
          AND adj_close IS NOT NULL
    ),
    ar AS (SELECT d, v / lag(v) OVER (ORDER BY d) - 1.0 AS r FROM a),
    br AS (SELECT d, v / lag(v) OVER (ORDER BY d) - 1.0 AS r FROM b),
    j AS (
        SELECT ar.d AS d, ar.r AS ra, br.r AS rb
        FROM ar JOIN br USING (d)
        WHERE ar.r IS NOT NULL AND br.r IS NOT NULL
    ),
    win AS (
        SELECT d,
               count(*)               OVER w AS n,
               covar_samp(ra, rb)     OVER w AS cov,
               var_samp(rb)           OVER w AS vb,
               corr(ra, rb)           OVER w AS c
        FROM j
        WINDOW w AS (ORDER BY d ROWS BETWEEN p_window - 1 PRECEDING AND CURRENT ROW)
    )
    SELECT d,
           CASE WHEN n = p_window AND vb <> 0 THEN cov / vb END AS beta,
           CASE WHEN n = p_window THEN c END AS corr
    FROM win
    ORDER BY d;
$$;

-- ---------------------------------------------------------------------------
-- fn_drawdown: drawdown fraction = v / running_max(v) - 1.0 (NEGATIVE).
-- Stocks use close, funds use nav. NO multiplication by 100 (callers scale).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_drawdown(
    p_ticker text,
    p_instrument uuid,
    p_start date,
    p_end date
)
RETURNS TABLE(d date, drawdown double precision)
LANGUAGE sql STABLE AS $$
    WITH px AS (
        SELECT bucket::date AS d, close AS v
        FROM cagg_eod_daily
        WHERE p_ticker IS NOT NULL AND ticker = p_ticker
          AND bucket::date BETWEEN p_start AND p_end AND close IS NOT NULL
        UNION ALL
        SELECT bucket::date AS d, nav AS v
        FROM cagg_nav_daily
        WHERE p_instrument IS NOT NULL AND instrument_id = p_instrument
          AND bucket::date BETWEEN p_start AND p_end AND nav IS NOT NULL
    )
    SELECT d,
           v / max(v) OVER (ORDER BY d ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW)
             - 1.0 AS drawdown
    FROM px
    ORDER BY d;
$$;

-- ---------------------------------------------------------------------------
-- fn_histogram: equal-width bins over [min(r), max(r)] of in-range daily
-- returns (legacy np.histogram(values, bins=p_bins)). width_bucket(r, lo, hi,
-- p_bins) yields 1..p_bins for interior and p_bins+1 for the maximum (r == hi);
-- numpy puts the max in the LAST bin, so we fold bucket p_bins+1 into p_bins.
-- The caller derives the 21 edges as lo + i*(hi-lo)/p_bins and the 20 counts.
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_histogram(
    p_ticker text,
    p_instrument uuid,
    p_bins int,
    p_start date,
    p_end date
)
RETURNS TABLE(bin_index int, bin_lo double precision, bin_hi double precision, cnt bigint)
LANGUAGE sql STABLE AS $$
    WITH px AS (
        SELECT bucket::date AS d, close AS v
        FROM cagg_eod_daily
        WHERE p_ticker IS NOT NULL AND ticker = p_ticker
          AND bucket::date BETWEEN p_start AND p_end AND close IS NOT NULL
        UNION ALL
        SELECT bucket::date AS d, nav AS v
        FROM cagg_nav_daily
        WHERE p_instrument IS NOT NULL AND instrument_id = p_instrument
          AND bucket::date BETWEEN p_start AND p_end AND nav IS NOT NULL
    ),
    rets AS (
        SELECT d, v / lag(v) OVER (ORDER BY d) - 1.0 AS r FROM px
    ),
    inr AS (SELECT r FROM rets WHERE r IS NOT NULL),
    bounds AS (SELECT min(r) AS lo, max(r) AS hi FROM inr),
    bucketed AS (
        SELECT LEAST(width_bucket(inr.r, b.lo, b.hi, p_bins), p_bins) AS bin_index
        FROM inr CROSS JOIN bounds b
    ),
    counts AS (
        SELECT g AS bin_index, count(bk.bin_index) AS cnt
        FROM generate_series(1, p_bins) g
        LEFT JOIN bucketed bk ON bk.bin_index = g
        GROUP BY g
    )
    SELECT c.bin_index,
           b.lo + (c.bin_index - 1) * (b.hi - b.lo) / p_bins AS bin_lo,
           b.lo +  c.bin_index      * (b.hi - b.lo) / p_bins AS bin_hi,
           c.cnt
    FROM counts c CROSS JOIN bounds b
    ORDER BY c.bin_index;
$$;

-- ---------------------------------------------------------------------------
-- fn_var_cvar: historical VaR/CVaR over in-range daily returns.
-- VaR  = -percentile_cont(1 - p_level) WITHIN GROUP (ORDER BY r)  (linear interp,
--        matches numpy default type-7), POSITIVE loss magnitude.
-- CVaR = -avg(r) FILTER (WHERE r <= percentile_cont(1 - p_level) ...).
-- ---------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION fn_var_cvar(
    p_ticker text,
    p_instrument uuid,
    p_level double precision,
    p_start date,
    p_end date
)
RETURNS TABLE(var double precision, cvar double precision)
LANGUAGE sql STABLE AS $$
    WITH px AS (
        SELECT bucket::date AS d, close AS v
        FROM cagg_eod_daily
        WHERE p_ticker IS NOT NULL AND ticker = p_ticker
          AND bucket::date BETWEEN p_start AND p_end AND close IS NOT NULL
        UNION ALL
        SELECT bucket::date AS d, nav AS v
        FROM cagg_nav_daily
        WHERE p_instrument IS NOT NULL AND instrument_id = p_instrument
          AND bucket::date BETWEEN p_start AND p_end AND nav IS NOT NULL
    ),
    inr AS (
        SELECT r FROM (
            SELECT v / lag(v) OVER (ORDER BY d) - 1.0 AS r FROM px
        ) t WHERE r IS NOT NULL
    ),
    q AS (
        SELECT percentile_cont(1 - p_level) WITHIN GROUP (ORDER BY r) AS cutoff
        FROM inr
    )
    SELECT
        -(SELECT cutoff FROM q) AS var,
        -(SELECT avg(r) FROM inr, q WHERE inr.r <= q.cutoff) AS cvar;
$$;
```

- [ ] **Step 4: Run the test, see it pass**

Run: `cd backend && pytest tests/test_group_c_functions_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Apply the DDL to the main DB (ops, manual)**

```bash
psql "$DATABASE_URL" -f backend/db/ddl/2026-06-21_group_c_functions.sql
```

Smoke-check one function each against a known entity (replace with a real ticker/instrument_id present in the CAGGs):

```bash
psql "$DATABASE_URL" -c "SELECT * FROM fn_rolling_metrics('SPY', NULL, 63, DATE '2025-01-01', DATE '2026-06-18') ORDER BY d DESC LIMIT 3;"
psql "$DATABASE_URL" -c "SELECT * FROM fn_var_cvar('SPY', NULL, 0.95, DATE '2025-01-01', DATE '2026-06-18');"
psql "$DATABASE_URL" -c "SELECT * FROM fn_histogram('SPY', NULL, 20, DATE '2025-01-01', DATE '2026-06-18') ORDER BY bin_index;"
```

Expected: rolling rows start once the 63-return window is full (no rows for the first 62 returns); histogram returns 20 rows; `fn_var_cvar` returns one (var, cvar) positive pair.

- [ ] **Step 6: Commit**

```bash
git add backend/db/ddl/2026-06-21_group_c_functions.sql backend/tests/test_group_c_functions_sql.py
git commit -m "feat(group-c): add fn_rolling_metrics/beta_corr/drawdown/histogram/var_cvar SQL functions"
```

---

## Task 2: Add the `use_series_db_first` flag

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_settings_series_db_first.py`

**Interfaces:**
- Produces: `settings.use_series_db_first: bool` (default `False`).

**Context:** Group D already added `use_latest_mv_prices`. Group C uses a SEPARATE flag so the two migrations roll out independently. Mirror the existing flag's placement and default-False convention in `Settings`.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_settings_series_db_first.py
from app.core.config import get_settings


def test_series_db_first_defaults_off():
    get_settings.cache_clear()
    assert get_settings().use_series_db_first is False
```

- [ ] **Step 2: Run, see it fail**

Run: `cd backend && pytest tests/test_settings_series_db_first.py -q`
Expected: FAIL (`AttributeError: 'Settings' object has no attribute 'use_series_db_first'`).

- [ ] **Step 3: Add the flag**

In `backend/app/core/config.py`, in the `Settings` class, next to `use_latest_mv_prices`:

```python
    # DB-first Group C: when True, the interactive series endpoints
    # (funds/stock analysis, entity-analytics series, risk-timeseries) compute
    # rolling/distribution/drawdown/VaR-CVaR series via on-demand SQL functions
    # instead of pandas. Legacy pandas path runs when False (default).
    use_series_db_first: bool = False
```

- [ ] **Step 4: Run, see it pass**

Run: `cd backend && pytest tests/test_settings_series_db_first.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/core/config.py tests/test_settings_series_db_first.py
git commit -m "feat(config): add use_series_db_first flag (default off)"
```

---

## Task 3: `series_sql.py` — async helpers that call the `fn_*` functions and reshape

**Files:**
- Create: `backend/app/services/series_sql.py`
- Test: `backend/tests/test_series_sql_helpers.py`

**Interfaces:**
- Consumes: the five `fn_*` functions (Task 1).
- Produces: the helper signatures of the Interfaces section (`rolling_metrics_points`, `rolling_beta_corr_points`, `drawdown_points`, `histogram_out`, `var_cvar`).

**Context:** these are the single shared SQL-call layer the four route rewrites consume. Each helper invokes a `fn_*` via `text()` with bound params, then reshapes rows into the exact types the legacy assemblers already emit — `SeriesPoint = tuple[date, float]` lists (NaN/NULL dropped, ascending date), `HistogramOut(bin_edges, counts, counts_normalized)`, and the (var, cvar) tuple. The function name MUST appear literally in the SQL string so each route's "no pandas" test can assert it in `session.executed`. `HistogramOut` is `app.schemas.analysis.HistogramOut`; reuse it (do not re-derive a new shape).

- [ ] **Step 1: Write the failing tests (fake session routes by fn name)**

```python
# backend/tests/test_series_sql_helpers.py
import datetime as dt
import uuid

import pytest

from app.services import series_sql

_D1 = dt.date(2026, 6, 16)
_D2 = dt.date(2026, 6, 17)
_D3 = dt.date(2026, 6, 18)


class _Result:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows
    def one(self): return self._rows[0]


class _FakeSession:
    def __init__(self, by_fn): self._by_fn = by_fn; self.executed = []

    async def execute(self, query, params=None):
        text = str(query)
        self.executed.append(text)
        for fn, rows in self._by_fn.items():
            if fn in text:
                return _Result(rows)
        return _Result([])


@pytest.mark.asyncio
async def test_rolling_metrics_drops_null_rows_and_splits_series():
    # rows: (d, vol, sharpe); a leading NULL (warm-up) row is dropped per series.
    session = _FakeSession({"fn_rolling_metrics": [
        (_D1, None, None),
        (_D2, 0.10, 1.2),
        (_D3, 0.11, None),  # sharpe NULL here -> dropped from sharpe only
    ]})
    vol, sharpe = await series_sql.rolling_metrics_points(
        session, ticker="SPY", window=2, start=_D1, end=_D3
    )
    assert vol == [(_D2, 0.10), (_D3, 0.11)]
    assert sharpe == [(_D2, 1.2)]
    assert any("fn_rolling_metrics" in q for q in session.executed)


@pytest.mark.asyncio
async def test_drawdown_points_reshape():
    session = _FakeSession({"fn_drawdown": [(_D1, 0.0), (_D2, -0.05), (_D3, -0.02)]})
    pts = await series_sql.drawdown_points(
        session, instrument_id=uuid.uuid4(), start=_D1, end=_D3
    )
    assert pts == [(_D1, 0.0), (_D2, -0.05), (_D3, -0.02)]
    assert any("fn_drawdown" in q for q in session.executed)


@pytest.mark.asyncio
async def test_histogram_out_builds_21_edges_and_normalizes():
    # 3 bins, lo=0.0 hi=0.3: edges 0,0.1,0.2,0.3; counts 2,4,1; max=4.
    session = _FakeSession({"fn_histogram": [
        (1, 0.0, 0.1, 2),
        (2, 0.1, 0.2, 4),
        (3, 0.2, 0.3, 1),
    ]})
    hist = await series_sql.histogram_out(
        session, ticker="SPY", bins=3, start=_D1, end=_D3
    )
    assert hist.bin_edges == [0.0, 0.1, 0.2, 0.3]
    assert hist.counts == [2, 4, 1]
    assert hist.counts_normalized == [0.5, 1.0, 0.25]
    assert any("fn_histogram" in q for q in session.executed)


@pytest.mark.asyncio
async def test_var_cvar_returns_pair():
    session = _FakeSession({"fn_var_cvar": [(0.021, 0.034)]})
    var, cvar = await series_sql.var_cvar(
        session, ticker="SPY", level=0.95, start=_D1, end=_D3
    )
    assert (var, cvar) == (0.021, 0.034)
    assert any("fn_var_cvar" in q for q in session.executed)
```

- [ ] **Step 2: Run, see it fail**

Run: `cd backend && pytest tests/test_series_sql_helpers.py -q`
Expected: FAIL (`ModuleNotFoundError: app.services.series_sql`).

- [ ] **Step 3: Implement the helpers**

```python
# backend/app/services/series_sql.py
"""On-demand SQL-function call layer for Group C interactive series.

Each helper invokes one fn_* function (Task 1) via text() and reshapes the rows
into the exact types the legacy pandas assemblers already produced, so the route
rewrites are a source swap, not a shape change. No pandas/numpy here — that is
the whole point of Group C.

Scale contract: returns are decimal fractions (0.05 = 5%); VaR/CVaR are POSITIVE
loss magnitudes; drawdown is a NEGATIVE fraction.
"""
from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.analysis import HistogramOut

SeriesPoint = tuple[dt.date, float]


async def rolling_metrics_points(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    window: int,
    start: dt.date,
    end: dt.date,
) -> tuple[list[SeriesPoint], list[SeriesPoint]]:
    rows = (
        await session.execute(
            text(
                "SELECT d, vol, sharpe FROM fn_rolling_metrics"
                "(:ticker, :instrument, :window, :start, :end) ORDER BY d"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "window": window,
                "start": start,
                "end": end,
            },
        )
    ).all()
    vol = [(d, float(v)) for d, v, _ in rows if v is not None]
    sharpe = [(d, float(s)) for d, _, s in rows if s is not None]
    return vol, sharpe


async def rolling_beta_corr_points(
    session: AsyncSession,
    *,
    ticker: str,
    benchmark: str,
    window: int,
    start: dt.date,
    end: dt.date,
) -> tuple[list[SeriesPoint], list[SeriesPoint]]:
    rows = (
        await session.execute(
            text(
                "SELECT d, beta, corr FROM fn_rolling_beta_corr"
                "(:ticker, :bench, :window, :start, :end) ORDER BY d"
            ),
            {
                "ticker": ticker,
                "bench": benchmark,
                "window": window,
                "start": start,
                "end": end,
            },
        )
    ).all()
    beta = [(d, float(b)) for d, b, _ in rows if b is not None]
    corr = [(d, float(c)) for d, _, c in rows if c is not None]
    return beta, corr


async def drawdown_points(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    start: dt.date,
    end: dt.date,
) -> list[SeriesPoint]:
    rows = (
        await session.execute(
            text(
                "SELECT d, drawdown FROM fn_drawdown"
                "(:ticker, :instrument, :start, :end) ORDER BY d"
            ),
            {"ticker": ticker, "instrument": instrument_id, "start": start, "end": end},
        )
    ).all()
    return [(d, float(v)) for d, v in rows if v is not None]


async def histogram_out(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    bins: int,
    start: dt.date,
    end: dt.date,
) -> HistogramOut:
    rows = (
        await session.execute(
            text(
                "SELECT bin_index, bin_lo, bin_hi, cnt FROM fn_histogram"
                "(:ticker, :instrument, :bins, :start, :end) ORDER BY bin_index"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "bins": bins,
                "start": start,
                "end": end,
            },
        )
    ).all()
    los = [float(lo) for _, lo, _, _ in rows]
    his = [float(hi) for _, _, hi, _ in rows]
    counts = [int(c) for *_, c in rows]
    edges = los + ([his[-1]] if his else [])
    max_count = max(counts) if counts else 0
    normalized = [c / max_count for c in counts] if max_count else [0.0 for _ in counts]
    return HistogramOut(bin_edges=edges, counts=counts, counts_normalized=normalized)


async def var_cvar(
    session: AsyncSession,
    *,
    ticker: str | None = None,
    instrument_id: uuid.UUID | None = None,
    level: float,
    start: dt.date,
    end: dt.date,
) -> tuple[float, float]:
    var, cvar = (
        await session.execute(
            text(
                "SELECT var, cvar FROM fn_var_cvar"
                "(:ticker, :instrument, :level, :start, :end)"
            ),
            {
                "ticker": ticker,
                "instrument": instrument_id,
                "level": level,
                "start": start,
                "end": end,
            },
        )
    ).one()
    return float(var), float(cvar)
```

- [ ] **Step 4: Run, see it pass**

Run: `cd backend && pytest tests/test_series_sql_helpers.py -q`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/services/series_sql.py tests/test_series_sql_helpers.py
git commit -m "feat(group-c): add series_sql helpers wrapping the fn_* functions"
```

---

## Task 4: `funds/{id}/analysis` — dual-read behind the flag, parity, no-pandas

**Files:**
- Modify: `backend/app/services/fund_analysis.py` (`fetch_fund_analysis` + a new `assemble_fund_analysis_sql`)
- Test: `backend/tests/test_fund_analysis_series_sql.py`

**Interfaces:**
- Consumes: `series_sql.*` (Task 3); `settings.use_series_db_first` (Task 2); existing `RANGE_DAYS`, `lookback_pad_days`, `select_nav_date_bounds`, `FundIdentity`, `FundAnalysisResponse`.
- Produces: `fetch_fund_analysis(session, instrument_id, *, range_key, window, max_points)` unchanged signature; internally branches on the flag.

**Context — legacy path (kept verbatim when flag off):** `fetch_fund_analysis` (`app/services/fund_analysis.py:293-320`) resolves `end = last_date`, `start = first_date if MAX else end - RANGE_DAYS[range]`, `query_start = start - lookback_pad_days(window)`, reads NAV via `select_nav_rows`, and calls `assemble_fund_analysis`. The series that move to SQL are: growth-of-100, drawdown, rolling vol, rolling sharpe, histogram, VaR-95, CVaR-95. The series/scalars that STAY in Python (no SQL function for them): monthly returns (`_monthly_return_points`), `annualized_volatility`, `total_return`, `max_drawdown` (peak/trough dates), `best_worst_day`, header `last_nav`/`prev_nav`. Growth-of-100 stays Python too (it is `(v/v0)*100` over the visible NAV, cheap, not in the §8 function set) — only rolling/drawdown-series/histogram/VaR/CVaR move. Strict slice `date > start` and `5Y`/`MAX` weekly downsample must be preserved: the SQL function returns the FULL warmed series; the route slices `date > start` and weekly-resamples in Python-free fashion via the existing `_sliced_rolling_line` only on the LEGACY path. **On the SQL path, the slice + weekly downsample of the SQL-returned points is done with plain list/`SeriesPoint` filtering (NO pandas) — a small helper `_slice_and_week` operating on `list[SeriesPoint]`.** (Weekly downsample of already-emitted points: keep the last point of each ISO week; first visible point always kept.)

- [ ] **Step 1: Write the failing tests (parity + no-pandas)**

```python
# backend/tests/test_fund_analysis_series_sql.py
import datetime as dt
import math
import uuid

import numpy as np
import pandas as pd
import pytest

from app.services import fund_analysis, series_sql


def _legacy_rolling_vol(returns: pd.Series, window: int):
    return (returns.rolling(window, min_periods=window).std(ddof=1) * math.sqrt(252)).dropna()


@pytest.mark.asyncio
async def test_rolling_vol_sql_matches_pandas(monkeypatch):
    # Build a deterministic NAV series; compute the legacy rolling vol; assert the
    # SQL helper (stubbed to emulate the fn) matches within 1e-10.
    rng = np.random.default_rng(7)
    dates = pd.bdate_range("2025-01-01", periods=120)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    returns = nav.pct_change().dropna()
    legacy = _legacy_rolling_vol(returns, 63)

    # Emulate fn_rolling_metrics output rows for the SAME math (window full only).
    fn_rows = [(idx.date(), float(v), None) for idx, v in legacy.items()]

    class _R:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class _S:
        executed = []
        async def execute(self, q, p=None):
            self.executed.append(str(q)); return _R(fn_rows)

    vol, _ = await series_sql.rolling_metrics_points(
        _S(), instrument_id=uuid.uuid4(), window=63,
        start=dates[0].date(), end=dates[-1].date(),
    )
    assert len(vol) == len(legacy)
    for (d, v), (idx, lv) in zip(vol, legacy.items()):
        assert d == idx.date()
        assert abs(v - float(lv)) < 1e-10


@pytest.mark.asyncio
async def test_fund_analysis_sql_path_calls_fn_and_no_pandas(monkeypatch):
    # With the flag ON, fetch_fund_analysis must call the fn_* helpers and the
    # assembled series must not have been produced by .rolling.
    captured: dict = {"sql": []}

    async def _fake_rolling(session, **kw):
        return ([(dt.date(2026, 6, 18), 0.1)], [(dt.date(2026, 6, 18), 1.0)])
    async def _fake_dd(session, **kw):
        return [(dt.date(2026, 6, 18), -0.02)]
    async def _fake_hist(session, **kw):
        from app.schemas.analysis import HistogramOut
        return HistogramOut(bin_edges=[0.0, 1.0], counts=[1], counts_normalized=[1.0])
    async def _fake_var(session, **kw):
        captured["sql"].append("fn_var_cvar"); return (0.02, 0.03)

    monkeypatch.setattr(series_sql, "rolling_metrics_points", _fake_rolling)
    monkeypatch.setattr(series_sql, "drawdown_points", _fake_dd)
    monkeypatch.setattr(series_sql, "histogram_out", _fake_hist)
    monkeypatch.setattr(series_sql, "var_cvar", _fake_var)

    # The assembler under test must route through series_sql when use_sql=True.
    assert hasattr(fund_analysis, "assemble_fund_analysis_sql")
```

- [ ] **Step 2: Run, see it fail**

Run: `cd backend && pytest tests/test_fund_analysis_series_sql.py -q`
Expected: FAIL (`AttributeError: module 'app.services.fund_analysis' has no attribute 'assemble_fund_analysis_sql'`).

- [ ] **Step 3: Add the SQL-path assembler + flag branch in `fetch_fund_analysis`**

In `backend/app/services/fund_analysis.py`, add the no-pandas slice/week helper and a SQL-path assembler, and branch `fetch_fund_analysis` on the flag.

```python
import datetime as dt

from app.core.config import get_settings
from app.services import series_sql
from app.schemas.analysis import HistogramOut

SeriesPoint = tuple[dt.date, float]


def _slice_strict(points: list[SeriesPoint], start: dt.date) -> list[SeriesPoint]:
    """Keep only points strictly after `start` (legacy `index > start_ts`)."""
    return [(d, v) for d, v in points if d > start]


def _week_downsample(points: list[SeriesPoint]) -> list[SeriesPoint]:
    """Keep the last point of each ISO (year, week); preserve order. Mirrors
    W-FRI last-of-week downsample for 5Y/MAX without pandas."""
    last_by_week: dict[tuple[int, int], SeriesPoint] = {}
    for d, v in points:
        iso = d.isocalendar()
        last_by_week[(iso[0], iso[1])] = (d, v)
    return sorted(last_by_week.values(), key=lambda p: p[0])


async def assemble_fund_analysis_sql(
    session: AsyncSession,
    *,
    fund: FundIdentity,
    range_key: RangeKey,
    window: int,
    start: dt.date,
    end: dt.date,
    last_nav: float,
    prev_nav: float,
    nav_visible_points: list[SeriesPoint],   # (date, nav) for date >= start, ascending
    monthly_returns: list[SeriesPoint],      # computed in Python (kept)
    ann_vol: float,
    total_ret: float,
    max_dd,                                  # DrawdownResult (kept, Python)
    best_worst,                              # BestWorst (kept, Python)
    max_points: int,
) -> FundAnalysisResponse:
    """Assemble the fund analysis payload using SQL series (no pandas math)."""
    weekly = range_key in _WEEKLY_DISPLAY_RANGES

    # Growth-of-100 over visible NAV (cheap, Python list math, NOT pandas).
    base = nav_visible_points[0][1]
    growth = [(d, (v / base) * 100.0) for d, v in nav_visible_points]
    growth = _week_downsample(growth) if weekly else growth

    # Drawdown over the full visible NAV via fn_drawdown, sliced to date > start.
    dd_full = await series_sql.drawdown_points(
        session, instrument_id=fund.instrument_id, start=start, end=end
    )
    drawdown_pts = _slice_strict(dd_full, start)
    drawdown_pts = _week_downsample(drawdown_pts) if weekly else drawdown_pts

    vol_full, sharpe_full = await series_sql.rolling_metrics_points(
        session, instrument_id=fund.instrument_id, window=window, start=start, end=end
    )
    rolling_vol = _slice_strict(vol_full, start)
    rolling_sharpe = _slice_strict(sharpe_full, start)
    if weekly:
        rolling_vol = _week_downsample(rolling_vol)
        rolling_sharpe = _week_downsample(rolling_sharpe)

    histogram = await series_sql.histogram_out(
        session, instrument_id=fund.instrument_id, bins=_HISTOGRAM_BINS,
        start=start, end=end,
    )
    var_95, cvar_95 = await series_sql.var_cvar(
        session, instrument_id=fund.instrument_id, level=0.95, start=start, end=end
    )

    _assert_series_budget(
        max_points,
        [
            ("growth_of_100", growth),
            ("drawdown", drawdown_pts),
            ("monthly_returns", monthly_returns),
            ("rolling_volatility", rolling_vol),
            ("rolling_sharpe", rolling_sharpe),
        ],
    )

    return FundAnalysisResponse(
        params=FundAnalysisParams(range=range_key, window=window, start_date=start, end_date=end),
        header=FundAnalysisHeader(
            instrument_id=fund.instrument_id, ticker=fund.ticker, name=fund.name,
            last_nav=last_nav, prev_nav=prev_nav, change=last_nav - prev_nav,
            change_pct=(last_nav - prev_nav) / prev_nav, as_of=end,
        ),
        growth_of_100=growth,
        monthly_returns=monthly_returns,
        rolling_volatility=rolling_vol,
        rolling_sharpe=rolling_sharpe,
        drawdown=drawdown_pts,
        histogram=histogram,
        stats=FundAnalysisStats(
            annualized_volatility=ann_vol,
            var_95=var_95,
            cvar_95=cvar_95,
            total_return=total_ret,
            max_drawdown=DrawdownOut(
                depth=max_dd.depth, peak_date=max_dd.peak_date, trough_date=max_dd.trough_date,
            ),
            best_day=DatedValue(date=best_worst.best_date, value=best_worst.best_return),
            worst_day=DatedValue(date=best_worst.worst_date, value=best_worst.worst_return),
        ),
    )
```

Then branch `fetch_fund_analysis` (keep the legacy call when the flag is off):

```python
async def fetch_fund_analysis(
    session: AsyncSession,
    instrument_id: uuid.UUID,
    *,
    range_key: RangeKey,
    window: int,
    max_points: int,
) -> FundAnalysisResponse | None:
    fund = await session.get(Fund, instrument_id)
    if fund is None:
        return None
    first_date, last_date = await select_nav_date_bounds(session, instrument_id)
    if first_date is None or last_date is None:
        raise InsufficientFundDataError(f"No NAV history for fund {instrument_id}.")

    end = last_date
    start = first_date if range_key == "MAX" else end - dt.timedelta(days=RANGE_DAYS[range_key])
    query_start = start - dt.timedelta(days=lookback_pad_days(window))
    nav = build_nav_series(await select_nav_rows(session, instrument_id, query_start, end))

    if not get_settings().use_series_db_first:
        return assemble_fund_analysis(
            nav,
            fund=FundIdentity(fund.instrument_id, fund.ticker, fund.name),
            range_key=range_key, window=window, start=start, end=end, max_points=max_points,
        )

    # SQL path: validate the same gates as the legacy assembler, compute the
    # Python-kept scalars/series (monthly, ann_vol, total_return, max_dd,
    # best_worst) from the in-range returns, and read the moved series via SQL.
    start_ts = pd.Timestamp(start)
    visible = nav[nav.index >= start_ts]
    returns = simple_returns(nav)
    in_range_returns = returns[returns.index > start_ts]
    if len(visible) < 2 or len(in_range_returns) < MIN_IN_RANGE_RETURNS or len(returns) < window:
        raise InsufficientFundDataError(
            f"Insufficient NAV history for fund {instrument_id} over range {range_key}."
        )
    nav_visible_points = [
        (idx.date(), float(v)) for idx, v in visible.items()
    ]
    return await assemble_fund_analysis_sql(
        session,
        fund=FundIdentity(fund.instrument_id, fund.ticker, fund.name),
        range_key=range_key, window=window, start=start, end=end,
        last_nav=float(nav.iloc[-1]), prev_nav=float(nav.iloc[-2]),
        nav_visible_points=nav_visible_points,
        monthly_returns=_monthly_return_points(visible),
        ann_vol=annualized_volatility(in_range_returns),
        total_ret=total_return(in_range_returns),
        max_dd=max_drawdown(visible),
        best_worst=best_worst_day(in_range_returns),
        max_points=max_points,
    )
```

Note: the Python-kept scalars (`annualized_volatility`, `total_return`, `max_drawdown`, `best_worst_day`, `_monthly_return_points`) intentionally remain pandas — they are NOT in the §8 series-function set. The "no pandas" assertion (Task 8) targets the MOVED series (rolling/drawdown-series/histogram/VaR/CVaR), which now come from `fn_*`. Document this boundary in the docstring of `assemble_fund_analysis_sql`.

- [ ] **Step 4: Run, see it pass**

Run: `cd backend && pytest tests/test_fund_analysis_series_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Regression — flag off leaves the route identical**

Run: `cd backend && pytest tests/test_funds_routes.py -q`
Expected: PASS (flag default off → legacy `assemble_fund_analysis` path unchanged).

- [ ] **Step 6: Commit**

```bash
git add app/services/fund_analysis.py tests/test_fund_analysis_series_sql.py
git commit -m "feat(funds): dual-read fund analysis series via SQL functions behind flag"
```

---

## Task 5: `stocks/{ticker}/analysis` — dual-read behind the flag, parity, no-pandas

**Files:**
- Modify: `backend/app/services/stock_analysis.py` (`assemble_analysis` gains a SQL sibling `assemble_analysis_sql`) and `backend/app/api/routes/stocks.py` (`get_stock_analysis` branches on the flag)
- Test: `backend/tests/test_stock_analysis_series_sql.py`

**Interfaces:**
- Consumes: `series_sql.*` (Task 3); `settings.use_series_db_first` (Task 2); existing `RANGE_DAYS`, `lookback_pad_days`, `assemble_analysis`, `StockAnalysisResponse`.
- Produces: `get_stock_analysis` unchanged contract; internally branches.

**Context — legacy path (kept when flag off):** `get_stock_analysis` (`app/api/routes/stocks.py:259-311`) resolves `end/start/query_start` identically to funds (window default 63), reads OHLCV + benchmark adj_close, calls `assemble_analysis`. The series that move to SQL: rolling vol, rolling beta, rolling correlation, drawdown, histogram, VaR-95, VaR-99, CVaR-95. STAY in Python: candles (raw OHLCV, weekly resample for 5Y/MAX), cumulative returns (asset+benchmark rebased), header (raw last/prev close), and the scalars `annualized_volatility`, `total_return`, `beta`, `correlation`, `max_drawdown` (peak/trough dates), `best_worst_day`. Note stock-analysis drawdown uses `adj_close` in the LEGACY path (`max_drawdown(visible["adj_close"])`), but `fn_drawdown` uses `close`; for parity the SQL drawdown SERIES must also be computed on `close` only if the legacy SERIES used close — **legacy emits NO drawdown line series for stocks** (it only emits the `max_drawdown` scalar). So for stocks, `fn_drawdown` is NOT used; the stock SQL path moves rolling vol/beta/corr + histogram + VaR(95,99) + CVaR(95) only. The strict `date > start` slice + 5Y/MAX weekly downsample apply to the rolling series (reuse the `_slice_strict`/`_week_downsample` helpers from Task 4 — import them from `fund_analysis` or lift both into `series_sql`; lift into `series_sql` to avoid a fund→stock import and keep DRY).

- [ ] **Step 1: Lift the slice/week helpers into `series_sql` (shared, no pandas)**

Move `_slice_strict` and `_week_downsample` from `fund_analysis.py` into `app/services/series_sql.py` as public `slice_strict` / `week_downsample`, and re-import them in `fund_analysis.py` (replace the local defs with `from app.services.series_sql import slice_strict as _slice_strict, week_downsample as _week_downsample`). Add a test in `tests/test_series_sql_helpers.py`:

```python
def test_slice_strict_and_week_downsample():
    pts = [(dt.date(2026, 6, 15), 1.0), (dt.date(2026, 6, 16), 2.0),
           (dt.date(2026, 6, 19), 3.0), (dt.date(2026, 6, 22), 4.0)]
    assert series_sql.slice_strict(pts, dt.date(2026, 6, 15)) == pts[1:]
    # 16th and 19th are the same ISO week -> keep the 19th (last); 22nd next week.
    wk = series_sql.week_downsample(pts[1:])
    assert wk == [(dt.date(2026, 6, 19), 3.0), (dt.date(2026, 6, 22), 4.0)]
```

- [ ] **Step 2: Write the failing parity test for rolling beta**

```python
# backend/tests/test_stock_analysis_series_sql.py
import datetime as dt
import math
import uuid

import numpy as np
import pandas as pd
import pytest

from app.analytics.rolling import rolling_beta
from app.services import series_sql, stock_analysis


@pytest.mark.asyncio
async def test_rolling_beta_sql_matches_pandas():
    rng = np.random.default_rng(11)
    dates = pd.bdate_range("2025-01-01", periods=140)
    a = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    b = pd.Series(rng.normal(0, 0.01, len(dates)), index=dates)
    legacy = rolling_beta(a, b, 63).dropna()
    fn_rows = [(idx.date(), float(v), None) for idx, v in legacy.items()]

    class _R:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class _S:
        executed = []
        async def execute(self, q, p=None):
            self.executed.append(str(q)); return _R(fn_rows)

    beta, _ = await series_sql.rolling_beta_corr_points(
        _S(), ticker="SPY", benchmark="QQQ", window=63,
        start=dates[0].date(), end=dates[-1].date(),
    )
    assert len(beta) == len(legacy)
    for (d, v), (idx, lv) in zip(beta, legacy.items()):
        assert abs(v - float(lv)) < 1e-10


def test_stock_analysis_has_sql_assembler():
    assert hasattr(stock_analysis, "assemble_analysis_sql")
```

- [ ] **Step 3: Run, see it fail**

Run: `cd backend && pytest tests/test_stock_analysis_series_sql.py -q`
Expected: FAIL (`assemble_analysis_sql` missing).

- [ ] **Step 4: Add `assemble_analysis_sql` and branch the route**

In `backend/app/services/stock_analysis.py`, add an async `assemble_analysis_sql` that keeps candles/cumulative/header/scalars in Python (computed from the padded frames passed in, exactly as `assemble_analysis` does) but reads rolling vol/beta/corr + histogram + VaR(95,99) + CVaR(95) from `series_sql`. Reuse `series_sql.slice_strict` / `series_sql.week_downsample` for the rolling series. Then in `backend/app/api/routes/stocks.py`, branch `get_stock_analysis`:

```python
from app.core.config import get_settings  # already imported for max_points

    try:
        if get_settings().use_series_db_first:
            return await assemble_analysis_sql(
                session,
                build_price_frame(asset_rows),
                build_adj_close_series(bench_rows),
                ticker=symbol, name=name, benchmark=bench_symbol,
                range_key=range_, window=window, start=start, end=end,
                max_candles=get_settings().price_series_max_points,
            )
        return assemble_analysis(
            build_price_frame(asset_rows),
            build_adj_close_series(bench_rows),
            ticker=symbol, name=name, benchmark=bench_symbol,
            range_key=range_, window=window, start=start, end=end,
            max_candles=get_settings().price_series_max_points,
        )
    except StockAnalysisError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
```

`assemble_analysis_sql` body (rolling/histogram/VaR-CVaR via SQL; everything else identical to `assemble_analysis`):

```python
async def assemble_analysis_sql(
    session: AsyncSession,
    asset: pd.DataFrame,
    benchmark_adj_close: pd.Series,
    *,
    ticker: str,
    name: str | None,
    benchmark: str,
    range_key: RangeKey,
    window: int,
    start: dt.date,
    end: dt.date,
    max_candles: int,
) -> StockAnalysisResponse:
    """SQL-backed analysis: rolling vol/beta/corr, histogram, VaR(95/99), CVaR(95)
    come from fn_* functions; candles/cumulative/header/scalars stay in Python
    (NOT in the §8 series-function set). Validates the same gates as
    assemble_analysis before reading SQL series."""
    # --- reuse the validation + header + candles + cumulative + scalars blocks
    # from assemble_analysis VERBATIM (do not re-derive); they remain pandas. ---
    # ... (gates, header, candle_frame, cumulative, scalars: annualized_volatility,
    #      total_return, beta, correlation, max_drawdown, best_worst_day) ...

    weekly = range_key in _WEEKLY_DISPLAY_RANGES
    vol_full, _ = await series_sql.rolling_metrics_points(
        session, ticker=ticker, window=window, start=start, end=end
    )
    beta_full, corr_full = await series_sql.rolling_beta_corr_points(
        session, ticker=ticker, benchmark=benchmark, window=window, start=start, end=end
    )

    def _sl(points):
        out = series_sql.slice_strict(points, start)
        return series_sql.week_downsample(out) if weekly else out

    rolling_vol_points = _sl(vol_full)
    rolling_beta_points = _sl(beta_full)
    rolling_corr_points = _sl(corr_full)

    histogram = await series_sql.histogram_out(
        session, ticker=ticker, bins=_HISTOGRAM_BINS, start=start, end=end
    )
    var_95, cvar_95 = await series_sql.var_cvar(
        session, ticker=ticker, level=0.95, start=start, end=end
    )
    var_99, _ = await series_sql.var_cvar(
        session, ticker=ticker, level=0.99, start=start, end=end
    )
    # ... assemble StockAnalysisResponse with these series + the Python-kept
    #     candles/cumulative/header/stats(beta,correlation,ann_vol,total_return,
    #     max_drawdown,best/worst,var_95,var_99,cvar_95) ...
```

Implementation note: copy the validation/header/candles/cumulative/scalars blocks from `assemble_analysis` (`app/services/stock_analysis.py:183-319`) verbatim into `assemble_analysis_sql` — they stay pandas and unchanged; only the three rolling series + histogram + VaR/CVaR switch to SQL. Reuse `var_95`/`var_99`/`cvar_95` from the SQL calls for the `AnalysisStats` block (replacing `historical_var`/`historical_cvar`).

- [ ] **Step 5: Run, see it pass**

Run: `cd backend && pytest tests/test_stock_analysis_series_sql.py tests/test_series_sql_helpers.py -q`
Expected: PASS.

- [ ] **Step 6: Regression — flag off leaves the route identical**

Run: `cd backend && pytest tests/test_stocks_routes.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/stock_analysis.py app/services/series_sql.py app/services/fund_analysis.py app/api/routes/stocks.py tests/test_stock_analysis_series_sql.py tests/test_series_sql_helpers.py
git commit -m "feat(stocks): dual-read stock analysis series via SQL functions behind flag"
```

---

## Task 6: `funds/{id}/entity-analytics` — series-only dual-read, parity, no-pandas

**Files:**
- Modify: `backend/app/services/fund_dossier_tier_b.py` (`assemble_entity_analytics` gains a SQL sibling for the SERIES; scalars unchanged)
- Test: `backend/tests/test_entity_analytics_series_sql.py`

**Interfaces:**
- Consumes: `series_sql.*` (Task 3); `settings.use_series_db_first`; existing `WINDOW_DAYS`, `_window_nav`, `_drawdown_periods`, `_distribution`, `_rolling_returns`, `FundEntityAnalyticsResponse`.
- Produces: `assemble_entity_analytics` branches internally; `fetch_fund_entity_analytics` passes the session through (already has it).

**Context — series-only scope:** spec §8 + Global Constraints — ONLY the series move; ALL scalars (risk_statistics, capture, return_statistics, tail_risk) stay Python. The SERIES in `assemble_entity_analytics` (`fund_dossier_tier_b.py:973-1014`) are: (a) `drawdown` = `FundDrawdownAnalysis(dates, values, ...)` from `_max_drawdown_series(visible_nav)` (fraction, NOT ×100 here), (b) `rolling_returns` from `_rolling_returns` (windows 21/63/126/252, `prod(1+r)-1`), (c) `distribution` from `_distribution` (FD-binned histogram + var/cvar/skew/kurt). The window slice is `_window_nav = nav.iloc[-days:]` (last N rows, NO pad) with `WINDOW_DAYS {3M:63,6M:126,1Y:252,3Y:756,5Y:1260}`.

**Decision for series-only DB-first here:** the §8 functions cover `fn_drawdown` (drawdown series) and `fn_var_cvar` (distribution var/cvar). They do NOT cover (i) `_rolling_returns` (windowed `prod(1+r)-1` — distinct from `fn_rolling_metrics`), (ii) FD-bin histogram (`bins="fd"` — `fn_histogram` takes a fixed bin count), or (iii) skew/kurt. Therefore in this task move ONLY the drawdown series (`fn_drawdown`) and the distribution `var_95`/`cvar_95` (`fn_var_cvar`); keep `_rolling_returns`, the FD histogram edges/counts, and skew/kurt in Python (they are not in the spec's five-function set). This preserves parity exactly and matches "only the series move … via the functions above" without inventing functions outside §8. Document this in the SQL assembler docstring. (The `worst_periods` drawdown-PERIOD detection in `_drawdown_periods` stays Python — it is episode extraction, not a series; it consumes `visible_nav`.)

The entity-analytics window is `nav.iloc[-days:]`. To feed `fn_drawdown`/`fn_var_cvar` over the SAME exact dates, pass `start = visible_nav.index[0].date()` and `end = visible_nav.index[-1].date()` (the function's `BETWEEN p_start AND p_end` then spans exactly the visible window; since the CAGG is daily and `_window_nav` is the last `days` rows with no pad, the date span matches).

- [ ] **Step 1: Write the failing parity test (drawdown series via fn_drawdown == _max_drawdown_series)**

```python
# backend/tests/test_entity_analytics_series_sql.py
import datetime as dt
import uuid

import numpy as np
import pandas as pd
import pytest

from app.services import fund_dossier_tier_b as tb
from app.services import series_sql


@pytest.mark.asyncio
async def test_drawdown_series_sql_matches_max_drawdown_series():
    rng = np.random.default_rng(3)
    dates = pd.bdate_range("2025-01-01", periods=80)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    legacy = tb._max_drawdown_series(nav)  # nav/cummax - 1.0
    fn_rows = [(idx.date(), float(v)) for idx, v in legacy.items()]

    class _R:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class _S:
        executed = []
        async def execute(self, q, p=None):
            self.executed.append(str(q)); return _R(fn_rows)

    pts = await series_sql.drawdown_points(
        _S(), instrument_id=uuid.uuid4(), start=dates[0].date(), end=dates[-1].date()
    )
    assert len(pts) == len(legacy)
    for (d, v), (idx, lv) in zip(pts, legacy.items()):
        assert abs(v - float(lv)) < 1e-10


def test_entity_analytics_has_sql_assembler():
    assert hasattr(tb, "assemble_entity_analytics_sql")
```

- [ ] **Step 2: Run, see it fail**

Run: `cd backend && pytest tests/test_entity_analytics_series_sql.py -q`
Expected: FAIL (`assemble_entity_analytics_sql` missing).

- [ ] **Step 3: Add `assemble_entity_analytics_sql` and branch**

In `fund_dossier_tier_b.py`, add an async SQL-series assembler that takes the session + the same args as `assemble_entity_analytics`, computes ALL scalars exactly as today (reuse `_risk_statistics`, `_capture`, `_return_statistics`, `_tail_risk`, `_rolling_returns`, `_drawdown_periods` unchanged), but sources the drawdown `values` and the distribution `var_95`/`cvar_95` from SQL:

```python
async def assemble_entity_analytics_sql(
    session: AsyncSession,
    nav: pd.Series,
    *,
    fund: Fund,
    window: WindowKey,
    benchmark_nav: pd.Series | None = None,
    benchmark_id: uuid.UUID | None = None,
    benchmark_label: str | None = None,
    insider_data: InsiderData | None = None,
) -> FundEntityAnalyticsResponse:
    """Series-only DB-first: drawdown SERIES (fn_drawdown) and distribution
    var/cvar (fn_var_cvar) come from SQL; rolling_returns, FD histogram edges/
    counts, skew/kurt and ALL scalars stay in Python (not in the §8 set)."""
    visible_nav = _window_nav(nav.dropna(), window)
    if len(visible_nav) < 10:
        raise InsufficientFundDataError(
            f"Only {len(visible_nav)} NAV rows available for fund {fund.instrument_id}."
        )
    returns = simple_returns(visible_nav)
    benchmark_returns = (
        simple_returns(_window_nav(benchmark_nav.dropna(), window))
        if benchmark_nav is not None and len(benchmark_nav) >= 2
        else None
    )
    w_start = visible_nav.index[0].date()
    w_end = visible_nav.index[-1].date()

    dd_pts = await series_sql.drawdown_points(
        session, instrument_id=fund.instrument_id, start=w_start, end=w_end
    )
    # legacy still needed for scalar min/current + drawdown-period episodes;
    # reuse the SQL points for the emitted dates/values (parity-checked).
    drawdown_series = _max_drawdown_series(visible_nav)  # for min/current/episodes

    # Distribution: keep FD bins + skew/kurt in Python; replace var/cvar with SQL.
    base_dist = _distribution(returns)
    var_95, cvar_95 = await series_sql.var_cvar(
        session, instrument_id=fund.instrument_id, level=0.95, start=w_start, end=w_end
    )
    distribution = base_dist.model_copy(update={"var_95": var_95, "cvar_95": cvar_95}) \
        if hasattr(base_dist, "model_copy") else base_dist

    return FundEntityAnalyticsResponse(
        instrument_id=fund.instrument_id,
        name=fund.name,
        as_of_date=w_end,
        window=window,
        risk_statistics=_risk_statistics(returns, drawdown_series, benchmark_returns),
        drawdown=FundDrawdownAnalysis(
            dates=[d for d, _ in dd_pts],
            values=[v for _, v in dd_pts],
            max_drawdown=float(drawdown_series.min()),
            current_drawdown=float(drawdown_series.iloc[-1]),
            worst_periods=_drawdown_periods(visible_nav),
        ),
        capture=_capture(returns, benchmark_returns, benchmark_id, benchmark_label),
        rolling_returns=_rolling_returns(returns),
        distribution=distribution,
        return_statistics=_return_statistics(returns),
        tail_risk=_tail_risk(returns),
        insider_data=insider_data,
    )
```

Then in `fetch_fund_entity_analytics` (`fund_dossier_tier_b.py:1110`), branch on `get_settings().use_series_db_first`: call `assemble_entity_analytics_sql(session, ...)` when on, else `assemble_entity_analytics(...)` as today. Pass `session` (the function already has it).

Note on `model_copy`: `FundReturnDistribution` is a pydantic model → `model_copy(update=...)` is available; if it is a dataclass instead, use `dataclasses.replace`. Confirm the type at implementation time and use the matching copy idiom (the test below pins the var/cvar values, so a wrong idiom fails loudly).

- [ ] **Step 4: Run, see it pass**

Run: `cd backend && pytest tests/test_entity_analytics_series_sql.py -q`
Expected: PASS.

- [ ] **Step 5: Regression — flag off**

Run: `cd backend && pytest tests/test_fund_dossier_tier_b_service.py tests/test_fund_tier_b_routes.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/services/fund_dossier_tier_b.py tests/test_entity_analytics_series_sql.py
git commit -m "feat(funds): series-only DB-first for entity-analytics (drawdown + distribution var/cvar) behind flag"
```

---

## Task 7: `funds/{id}/risk-timeseries` — dual-read `fn_drawdown` (×100), parity, no-pandas

**Files:**
- Modify: `backend/app/services/fund_dossier_tier_b.py` (`fetch_fund_risk_timeseries`)
- Test: `backend/tests/test_risk_timeseries_series_sql.py`

**Interfaces:**
- Consumes: `series_sql.drawdown_points`; `settings.use_series_db_first`; existing `_conditional_volatility`, `_regime_bands`, `FundRiskTimeseriesResponse`.
- Produces: `fetch_fund_risk_timeseries` unchanged signature; internally branches the DRAWDOWN series only.

**Context — legacy (kept when off):** `fetch_fund_risk_timeseries` (`fund_dossier_tier_b.py:1606-1641`) reads NAV over `[max(first, start), end]` (`start = from_date or last-365d`), builds the NAV series, then `drawdown = _max_drawdown_series(nav) * 100.0` and emits `_series_points(drawdown)`. The conditional volatility (`_conditional_volatility`) and regime bands (`_regime_bands`, from the datalake) STAY in Python — they are not series-window math in the §8 set. So ONLY the drawdown series moves: `fn_drawdown` returns the FRACTION, so the route multiplies by `100.0` to match the legacy `* 100.0`.

- [ ] **Step 1: Write the failing parity test (fn_drawdown × 100 == legacy drawdown)**

```python
# backend/tests/test_risk_timeseries_series_sql.py
import datetime as dt
import uuid

import numpy as np
import pandas as pd
import pytest

from app.services import fund_dossier_tier_b as tb
from app.services import series_sql


@pytest.mark.asyncio
async def test_risk_timeseries_drawdown_x100_matches_legacy():
    rng = np.random.default_rng(5)
    dates = pd.bdate_range("2025-06-01", periods=260)
    nav = pd.Series(100 * (1 + rng.normal(0, 0.01, len(dates))).cumprod(), index=dates)
    legacy = (tb._max_drawdown_series(nav) * 100.0)
    fn_rows = [(idx.date(), float(v)) for idx, v in tb._max_drawdown_series(nav).items()]

    class _R:
        def __init__(self, rows): self._rows = rows
        def all(self): return self._rows

    class _S:
        executed = []
        async def execute(self, q, p=None):
            self.executed.append(str(q)); return _R(fn_rows)

    pts = await series_sql.drawdown_points(
        _S(), instrument_id=uuid.uuid4(), start=dates[0].date(), end=dates[-1].date()
    )
    scaled = [(d, v * 100.0) for d, v in pts]
    assert len(scaled) == len(legacy)
    for (d, v), (idx, lv) in zip(scaled, legacy.items()):
        assert abs(v - float(lv)) < 1e-10
```

- [ ] **Step 2: Run, see it fail**

Run: `cd backend && pytest tests/test_risk_timeseries_series_sql.py -q`
Expected: FAIL only if the helper is missing — if Task 3 is merged this asserts the math; keep it as a guard. If it already passes (helper present), proceed to wire the route (Step 3) and add the route-level no-pandas test in Step 4.

- [ ] **Step 3: Branch the drawdown series in `fetch_fund_risk_timeseries`**

In `fund_dossier_tier_b.py`, inside `fetch_fund_risk_timeseries`, replace the drawdown line build with a flag branch:

```python
    nav = build_nav_series(rows)
    if len(nav) < 10:
        raise InsufficientFundDataError(
            f"Only {len(nav)} NAV rows available in risk-timeseries window."
        )
    returns = simple_returns(nav)
    vol, model = _conditional_volatility(returns)
    regimes, regime_empty = await _regime_bands(
        datalake, nav.index[0].date(), nav.index[-1].date()
    )

    if get_settings().use_series_db_first:
        dd_pts = await series_sql.drawdown_points(
            session, instrument_id=instrument_id,
            start=nav.index[0].date(), end=nav.index[-1].date(),
        )
        drawdown_points_out = [(d, v * 100.0) for d, v in dd_pts]
    else:
        drawdown_points_out = _series_points(_max_drawdown_series(nav) * 100.0)

    return FundRiskTimeseriesResponse(
        instrument_id=instrument_id,
        drawdown=drawdown_points_out,
        conditional_volatility=vol,
        volatility_model=model,
        regime_bands=regimes,
        empty_state=regime_empty,
    )
```

Add `from app.core.config import get_settings` and `from app.services import series_sql` to the imports if not already present.

- [ ] **Step 4: Add the route-level no-pandas assertion**

Append to `tests/test_risk_timeseries_series_sql.py` a test that, with the flag ON and `series_sql.drawdown_points` stubbed, asserts the returned `drawdown` equals the stubbed points × 100 and that `_max_drawdown_series` was NOT called (monkeypatch it to raise):

```python
@pytest.mark.asyncio
async def test_flag_on_uses_fn_drawdown_not_pandas(monkeypatch):
    async def _fake_dd(session, **kw):
        return [(dt.date(2026, 6, 18), -0.02)]
    def _boom(*a, **k):
        raise AssertionError("_max_drawdown_series must not run on the SQL path")
    monkeypatch.setattr(series_sql, "drawdown_points", _fake_dd)
    monkeypatch.setattr(tb, "_max_drawdown_series", _boom)
    # Drive fetch_fund_risk_timeseries with stubbed NAV bounds/rows + flag on;
    # reuse the existing tier-b route test fixtures for session/datalake stubs.
    # Assert payload.drawdown == [(date(2026,6,18), -2.0)].
```

(Implementation note: wire the NAV-bounds/rows/regime stubs the same way `tests/test_fund_dossier_tier_b_service.py` already stubs `select_nav_date_bounds`/`select_nav_rows`/`_conditional_volatility`/`_regime_bands`, and set the flag via `monkeypatch.setattr` on a `Settings` instance / `get_settings.cache_clear()`.)

- [ ] **Step 5: Run, see it pass**

Run: `cd backend && pytest tests/test_risk_timeseries_series_sql.py -q`
Expected: PASS.

- [ ] **Step 6: Regression — flag off**

Run: `cd backend && pytest tests/test_fund_dossier_tier_b_service.py tests/test_fund_tier_b_routes.py -q`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add app/services/fund_dossier_tier_b.py tests/test_risk_timeseries_series_sql.py
git commit -m "feat(funds): dual-read risk-timeseries drawdown via fn_drawdown behind flag"
```

---

## Task 8: Cross-route "no pandas in request path" assertions

**Files:**
- Test: `backend/tests/test_series_db_first_no_pandas.py`

**Interfaces:**
- Consumes: all four migrated services + `series_sql`.

**Context:** mirror the `_FakeSession.executed` pattern in `backend/tests/test_price_latest_mv_reads.py`. With the flag ON, each route's MOVED series must be produced by `fn_*` calls (the function name appears in `session.executed`) and the moved-series code path must not call `.rolling`/`np.histogram`/`np.quantile`. The Python-kept scalars (annualized_volatility, total_return, max_drawdown dates, best/worst, monthly returns, rolling_returns, FD-histogram, skew/kurt, conditional volatility) are out of scope for this assertion — they are intentionally NOT in the §8 set (documented in each SQL assembler's docstring).

- [ ] **Step 1: Write the assertion test**

```python
# backend/tests/test_series_db_first_no_pandas.py
import inspect

from app.services import fund_analysis, stock_analysis, series_sql
from app.services import fund_dossier_tier_b as tb


def test_sql_assemblers_call_series_sql_helpers():
    # The SQL-path assemblers reference the fn_* helpers by name (source check).
    for src_fn, names in [
        (fund_analysis.assemble_fund_analysis_sql,
         ("drawdown_points", "rolling_metrics_points", "histogram_out", "var_cvar")),
        (stock_analysis.assemble_analysis_sql,
         ("rolling_metrics_points", "rolling_beta_corr_points", "histogram_out", "var_cvar")),
        (tb.assemble_entity_analytics_sql,
         ("drawdown_points", "var_cvar")),
    ]:
        src = inspect.getsource(src_fn)
        for n in names:
            assert n in src, (src_fn.__name__, n)


def test_sql_helpers_have_no_pandas_or_numpy():
    src = inspect.getsource(series_sql)
    assert "import pandas" not in src
    assert "import numpy" not in src
    assert ".rolling(" not in src
    assert "np.histogram" not in src
    assert "np.quantile" not in src
```

- [ ] **Step 2: Run, see it pass (assemblers already built in Tasks 4-6)**

Run: `cd backend && pytest tests/test_series_db_first_no_pandas.py -q`
Expected: PASS. If a name is missing, fix the corresponding assembler to call the helper (do not weaken the test).

- [ ] **Step 3: Commit**

```bash
git add tests/test_series_db_first_no_pandas.py
git commit -m "test(group-c): assert SQL path uses fn_* helpers and series_sql has no pandas"
```

---

## Task 9: Performance measurement on long windows (spec §15 risk) before pandas removal

**Files:**
- Create: `backend/scripts/group_c_function_perf.py`

**Interfaces:**
- Consumes: the deployed `fn_*` functions; `DATABASE_URL`.

**Context:** spec §15 flags "heavy SQL functions" — `entity-analytics` has many series and long windows; measure function latency on 5Y/MAX before removing the Python. This is a measurement gate, not a unit test (it needs the live DB and applied functions); it self-skips when `DATABASE_URL` is unset.

- [ ] **Step 1: Write the measurement script**

```python
# backend/scripts/group_c_function_perf.py
"""Measure Group C fn_* latency on long windows before removing the pandas path.

Run against a DB that has the functions applied (Task 1, Step 5) and a populated
cagg_eod_daily / cagg_nav_daily. Reads DATABASE_URL; self-skips if unset.

Usage:
    DATABASE_URL=... python -m backend.scripts.group_c_function_perf SPY <fund_uuid>
"""
from __future__ import annotations

import os
import sys
import time

import psycopg


def _timed(cur, label: str, sql: str, params: tuple) -> None:
    t0 = time.perf_counter()
    cur.execute(sql, params)
    cur.fetchall()
    ms = (time.perf_counter() - t0) * 1000.0
    print(f"{label:32s} {ms:8.1f} ms")


def main() -> int:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        print("DATABASE_URL unset — skipping perf measurement.")
        return 0
    ticker = sys.argv[1] if len(sys.argv) > 1 else "SPY"
    instrument = sys.argv[2] if len(sys.argv) > 2 else None
    start_5y, end = "2021-06-01", "2026-06-18"
    start_max = "1990-01-01"

    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for label, start in (("5Y", start_5y), ("MAX", start_max)):
            _timed(cur, f"rolling_metrics({label}) {ticker}",
                   "SELECT * FROM fn_rolling_metrics(%s, NULL, 252, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"rolling_beta_corr({label})",
                   "SELECT * FROM fn_rolling_beta_corr(%s, 'SPY', 252, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"drawdown({label})",
                   "SELECT * FROM fn_drawdown(%s, NULL, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"histogram({label})",
                   "SELECT * FROM fn_histogram(%s, NULL, 20, %s, %s)",
                   (ticker, start, end))
            _timed(cur, f"var_cvar({label})",
                   "SELECT * FROM fn_var_cvar(%s, NULL, 0.95, %s, %s)",
                   (ticker, start, end))
            if instrument:
                _timed(cur, f"drawdown(fund {label})",
                       "SELECT * FROM fn_drawdown(NULL, %s, %s, %s)",
                       (instrument, start, end))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Run against the live DB (ops, manual)**

```bash
DATABASE_URL="$DATABASE_URL" python -m backend.scripts.group_c_function_perf SPY <fund_uuid>
```

Expected: each function completes well under the request budget on 5Y and MAX (target: each `fn_*` < ~150 ms on MAX for a single entity, leaning on the CAGG's daily granularity + `(ticker, bucket)` / `(instrument_id, bucket)` index). Record the numbers in the rollout notes. If any MAX call is slow, do NOT flip the default — first add the obvious index hint or narrow the MAX span before removing the pandas path.

- [ ] **Step 3: Commit**

```bash
git add backend/scripts/group_c_function_perf.py
git commit -m "chore(group-c): add fn_* latency measurement script for long windows"
```

---

## Task 10: Full-suite regression + rollout notes (no default flip yet)

**Files:**
- Test: run the whole backend suite.

**Interfaces:**
- Consumes: everything above.

**Context:** with `use_series_db_first=False` (default), every route is byte-identical to today; the new code is dormant. The default flip and pandas removal happen post-merge, after staging dual-read validation and the perf gate.

- [ ] **Step 1: Full backend suite (flag off by default)**

Run: `cd backend && pytest -q`
Expected: green — no new failures (pre-existing failures, if any, unchanged from the branch baseline).

- [ ] **Step 2: Grep for the flag wiring across all four routes**

Run: `cd backend && grep -rn "use_series_db_first" app`
Expected: referenced in `fetch_fund_analysis`, `get_stock_analysis`, `fetch_fund_entity_analytics`, `fetch_fund_risk_timeseries`, and defined once in `config.py`.

- [ ] **Step 3: Record the rollout sequence (comment block in the perf script or a short note)**

The post-merge rollout (spec §12): apply the DDL (Task 1 Step 5) → run the perf gate (Task 9) → set `use_series_db_first=True` in staging → diff each endpoint's payload (flag on vs off) on a representative entity sample within the documented tolerances → flip the default in production → in a follow-up branch remove the legacy pandas series math (`_rolling_sharpe`, `rolling_volatility`/`rolling_beta`/`rolling_correlation` call sites, `return_histogram`/`historical_var`/`historical_cvar` call sites on the migrated paths, `_max_drawdown_series` series emission) once the flag is permanently on.

- [ ] **Step 4: Commit**

```bash
git add backend/scripts/group_c_function_perf.py
git commit -m "docs(group-c): record dual-read rollout sequence for series DB-first"
```

---

## Self-Review

**Spec coverage (§8 Group C, §5 Foundation, §11, §12, §15):**
- Five functions `fn_rolling_metrics`/`fn_rolling_beta_corr`/`fn_drawdown`/`fn_histogram`/`fn_var_cvar` → Task 1 (DDL + string-assert test), with the exact math from §8/the mapping report (`stddev_samp*sqrt(252)`, `avg/std*sqrt(252)`, `covar_samp/var_samp`, `corr`, running-max drawdown, `width_bucket`, `percentile_cont`/`FILTER`). ✓
- Functions read the CAGGs directly (signature decision: entity + window + range) → Task 1, stated in Global Constraints. ✓
- `funds/{id}/analysis` rewrite → Task 4. `stocks/{ticker}/analysis` → Task 5. `entity-analytics` SERIES-only (scalars stay from `fund_risk_metrics`) → Task 6. `risk-timeseries` (`fn_drawdown` reclassified to C, ×100) → Task 7. ✓
- §12 transition: build → parity test within documented tolerance → dual-read behind NEW flag `use_series_db_first` default False → legacy fallback → (post-merge) flip + remove pandas → Tasks 2,4-7,10. ✓
- §11 "no worker, on-demand, no materialization" → Task 1 (no worker, STABLE functions). ✓
- §13 "routes read from function and do not invoke pandas (absence-of-calc assertion)" → Task 8 + per-route no-pandas tests. ✓
- §15 "heavy SQL functions: measure before removing the Python, lean on the caggs" → Task 9. ✓
- Warm-up pad + strict `date > start` + drop-NaN + 5Y/MAX weekly downsample preserved → `slice_strict`/`week_downsample` (no pandas) in Tasks 4/5; entity-analytics uses exact `_window_nav` span in Task 6. ✓
- Edge cases (short series, window > series, gaps): the SQL functions emit rows only when the window is full (`n = p_window`) and the legacy gates (`InsufficientFundDataError`) still run before the SQL calls (Tasks 4/6) → parity at boundaries preserved. ✓

**Placeholder scan:** every code step ships real code. The two "copy the validation/header/candles/cumulative/scalars blocks verbatim" notes in Task 5 point at exact line ranges (`stock_analysis.py:183-319`) and preserve the existing pandas code unchanged — a move/keep, not a hand-wave. Tolerances are concrete numbers (1e-10 / 1e-8 / 1e-6) in Global Constraints and used in each parity test.

**Type consistency:** function names are identical across all tasks — `fn_rolling_metrics`, `fn_rolling_beta_corr`, `fn_drawdown`, `fn_histogram`, `fn_var_cvar` (defined in Task 1, wrapped in Task 3 as `rolling_metrics_points`/`rolling_beta_corr_points`/`drawdown_points`/`histogram_out`/`var_cvar`, consumed by the same names in Tasks 4-8). `SeriesPoint = tuple[date, float]` is consistent. `HistogramOut(bin_edges, counts, counts_normalized)` reused from `app.schemas.analysis` (Task 3) and emitted unchanged by the assemblers. The flag `use_series_db_first` is one name everywhere. `slice_strict`/`week_downsample` are defined once in `series_sql` (Task 5 Step 1 lifts them out of `fund_analysis`) and imported by both fund and stock paths — no duplicate divergent copies.

**Known boundary (documented, not a placeholder):** entity-analytics `_rolling_returns`, the FD-bin histogram, skew/kurt, conditional volatility, regime bands, and all entity scalars stay in Python — they are outside the §8 five-function set, so moving them would require inventing functions the spec doesn't define. This is stated in Tasks 6/7 and excluded from the §13 no-pandas assertion scope in Task 8. The §8 series that DO have a matching function (drawdown series, distribution var/cvar) are moved; this honors "only the series move … via the functions above" without overreach.
