-- Materialize the daily NAV surface used by GET /funds/{id}/timeseries.
--
-- The route now reads this single daily CAGG for every visible range. Weekly
-- and monthly CAGGs may still exist for other workloads, but a single-fund
-- dossier chart should not switch sources by range.

CREATE MATERIALIZED VIEW IF NOT EXISTS cagg_nav_daily
WITH (timescaledb.continuous) AS
SELECT instrument_id,
       time_bucket('1 day', nav_date) AS bucket,
       last(nav, nav_date)       AS nav,
       last(return_1d, nav_date) AS return_1d,
       count(*)                  AS n_obs,
       last(aum_usd, nav_date)   AS aum_usd
FROM nav_timeseries
GROUP BY instrument_id, time_bucket('1 day', nav_date)
WITH NO DATA;

CREATE INDEX IF NOT EXISTS cagg_nav_daily_instrument_bucket_idx
    ON cagg_nav_daily (instrument_id, bucket);

CALL refresh_continuous_aggregate('cagg_nav_daily', NULL, NULL);

SELECT add_continuous_aggregate_policy(
    'cagg_nav_daily',
    start_offset => INTERVAL '90 days',
    end_offset => INTERVAL '1 day',
    schedule_interval => INTERVAL '1 day',
    if_not_exists => true
);
