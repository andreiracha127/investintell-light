-- backend/db/ddl/2026-06-21_group_c_functions.sql
-- Group C: on-demand series math moved from the FastAPI request path into the
-- DB. Each function takes an entity key + window + [start, end] date range and
-- reads the canonical daily CAGGs (cagg_eod_daily / cagg_nav_daily) directly.
-- No materialization, no worker: these are STABLE (a real-time continuous
-- aggregate makes reads time-dependent, so a stronger volatility class would
-- be a correctness lie) on-demand functions.
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
        -(SELECT avg(inr.r) FILTER (WHERE inr.r <= (SELECT cutoff FROM q)) FROM inr) AS cvar;
$$;
