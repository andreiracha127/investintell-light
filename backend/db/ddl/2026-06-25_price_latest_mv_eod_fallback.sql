-- backend/db/ddl/2026-06-25_price_latest_mv_eod_fallback.sql
-- Rebuild price_latest_mv so tickers present in eod_prices but absent from
-- cagg_eod_daily (notably proxy ETFs) stay on the DB-first latest-price path.

DROP MATERIALIZED VIEW IF EXISTS price_latest_mv;

CREATE MATERIALIZED VIEW price_latest_mv AS
WITH cagg_tickers AS (
    SELECT DISTINCT ticker
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
),
daily AS (
    SELECT ticker, bucket::date AS as_of, close
    FROM cagg_eod_daily
    WHERE close IS NOT NULL
    UNION ALL
    SELECT ticker, date AS as_of, close
    FROM eod_prices
    WHERE close IS NOT NULL
      AND ticker NOT IN (SELECT ticker FROM cagg_tickers)
),
ranked AS (
    SELECT ticker, as_of, close,
           row_number() OVER (PARTITION BY ticker ORDER BY as_of DESC) AS rn
    FROM daily
)
SELECT
    ticker,
    max(as_of) FILTER (WHERE rn = 1) AS as_of,
    max(close) FILTER (WHERE rn = 1) AS last_close,
    max(as_of) FILTER (WHERE rn = 2) AS prev_date,
    max(close) FILTER (WHERE rn = 2) AS prev_close
FROM ranked
WHERE rn <= 2
GROUP BY ticker
WITH NO DATA;

CREATE UNIQUE INDEX price_latest_mv_pk ON price_latest_mv (ticker);

REFRESH MATERIALIZED VIEW price_latest_mv;
