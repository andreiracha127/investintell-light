-- Additive, non-destructive dynamic-catalog DDL (Tiger t83f4np6x4, public).
-- Idempotent where possible; safe to re-run. Rollback in the deploy runbook.

-- 1) EOD weekly OHLC (adjusted) for Highcharts long-range downsample.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_weekly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 week', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 week', date)
WITH NO DATA;

-- 2) EOD monthly OHLC (adjusted).
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_eod_monthly
WITH (timescaledb.continuous) AS
SELECT ticker,
       time_bucket('1 month', date) AS bucket,
       first(adj_open,  date) AS adj_open,
       max(adj_high)          AS adj_high,
       min(adj_low)           AS adj_low,
       last(adj_close, date)  AS adj_close,
       sum(adj_volume)        AS adj_volume
FROM eod_prices
GROUP BY ticker, time_bucket('1 month', date)
WITH NO DATA;

-- 3) NAV weekly (last-of-week) — cagg_nav_monthly already exists.
CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_weekly
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('1 week', nav_date) AS bucket,
       last(nav, nav_date)      AS nav_eow,
       first(nav, nav_date)     AS nav_bow,
       count(*)                 AS n_obs,
       last(aum_usd, nav_date)  AS aum_eow
FROM nav_timeseries
GROUP BY instrument_id, time_bucket('1 week', nav_date)
WITH NO DATA;

-- Populate once, then keep fresh daily (ingestion writes daily).
CALL refresh_continuous_aggregate('cagg_eod_weekly',  NULL, NULL);
CALL refresh_continuous_aggregate('cagg_eod_monthly', NULL, NULL);
CALL refresh_continuous_aggregate('cagg_nav_weekly',  NULL, NULL);

SELECT add_continuous_aggregate_policy('cagg_eod_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_eod_monthly',
  start_offset => INTERVAL '180 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
SELECT add_continuous_aggregate_policy('cagg_nav_weekly',
  start_offset => INTERVAL '90 days', end_offset => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 day', if_not_exists => true);
